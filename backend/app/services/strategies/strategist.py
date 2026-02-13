"""Strategist Agent - Signal Generation for Trading System v2.0"""

from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from loguru import logger

from ..agents.base_agent import BaseAgent
from ...core.kite_client import KiteClient
from ...config.settings import Settings
from ...config.constants import (
    ENTRY_START_HOUR, ENTRY_START_MINUTE, ENTRY_END_HOUR, ENTRY_END_MINUTE,
    NFO, BUY, SELL
)
from ...config.thresholds import (
    IV_PERCENTILE_SHORT_VOL, IV_PERCENTILE_STRANGLE,
    IC_SHORT_DELTA, IC_LONG_DELTA,
    IC_PROFIT_TARGET, IC_STOP_LOSS, IC_MIN_DTE, IC_MAX_DTE,
    MAX_PREV_DAY_RANGE, MAX_GAP_PCT, EVENT_BLACKOUT_DAYS,
    MIN_BID_ASK_SPREAD, MIN_OPEN_INTEREST,
    RSI_OVERSOLD, RSI_OVERBOUGHT
)
from ...models.regime import RegimePacket, RegimeType
from ...models.trade import TradeProposal, TradeLeg, LegType, StructureType
from .iron_condor import IronCondorStrategy
from .jade_lizard import JadeLizardStrategy
from .butterfly import ButterflyStrategy, BrokenWingButterflyStrategy
from .risk_reversal import RiskReversalStrategy
from .strangle import StrangleStrategy
from ..indicators.technical import (
    calculate_adx, calculate_rsi, calculate_atr, calculate_day_range,
    calculate_bollinger_band_width, calculate_bbw_ratio, calculate_volume_ratio
)
from ..indicators.greeks import validate_and_calculate_greeks, GreeksCalculator


class Strategist(BaseAgent):
    """
    Signal generation agent.
    
    Responsibilities:
    - Receive RegimePacket from Sentinel
    - Check time restrictions
    - Generate trade signals based on regime
    - Build option structures (Iron Condor, Jade Lizard, etc.)
    - Validate entry conditions
    - Produce TradeProposal for Treasury approval
    """
    
    def __init__(self, kite: KiteClient, config: Settings, enabled_strategies: List[str] = None, bypass_entry_window: bool = False):
        super().__init__(kite, config, name="Strategist")
        self._expiry_cache: Dict[str, List[date]] = {}
        self.bypass_entry_window = bypass_entry_window  # For backtesting
        
        # Initialize Greeks calculator
        self._greeks_calculator = GreeksCalculator()
        
        # Lot size cache (fetched from Kite API)
        self._lot_size_cache: Dict[str, int] = {}
        
        # Margin cache to avoid repeated API calls
        self._margin_cache: Dict[str, float] = {}
        
        # Initialize strategy modules with kite reference for dynamic lot size
        self._jade_lizard = JadeLizardStrategy(kite=self.kite)
        self._butterfly = ButterflyStrategy(kite=self.kite)
        self._bwb = BrokenWingButterflyStrategy(kite=self.kite)
        self._strangle = StrangleStrategy(self.kite)
        self._risk_reversal = RiskReversalStrategy(self.kite)
        
        # Filter enabled strategies
        self.enabled_strategies = enabled_strategies or [
            "iron_condor", "jade_lizard", "butterfly", "naked_strangle", "risk_reversal"
        ]
    
    def process(self, regime_packet: RegimePacket) -> List[TradeProposal]:
        """
        Generate trade proposals based on regime using unified StrategySelector.
        
        Ensures backtester and live trading use IDENTICAL strategy selection logic
        per v2_rulebook.md Section 4 (Entry and Exit Rules).
        
        Args:
            regime_packet: Current regime assessment from Sentinel
            
        Returns:
            List of TradeProposal objects, ranked by suitability
        """
        from .strategy_selector import StrategySelector
        from ...models.trade import StructureType
        
        proposals = []
        
        # Check if trading is allowed (can be bypassed for backtesting)
        if not self.bypass_entry_window and not self._is_entry_window():
            self.logger.info(f"Outside entry window (current: {datetime.now().time()}, window: {ENTRY_START_HOUR}:{ENTRY_START_MINUTE}-{ENTRY_END_HOUR}:{ENTRY_END_MINUTE})")
            return proposals
        
        self.logger.info(f"Within entry window, processing regime: {regime_packet.regime.value}")
        
        # Get suitable structures for current regime from unified selector
        suitable_structures = StrategySelector.get_suitable_structures(regime_packet)
        
        if not suitable_structures:
            self.logger.info(f"{regime_packet.regime.value} regime - no suitable structures from StrategySelector")
            return proposals
        
        self.logger.info(f"{regime_packet.regime.value} regime - {len(suitable_structures)} suitable structures: {[s[0].value for s in suitable_structures]}")
        
        # Generate proposal for each suitable structure (in priority order)
        for structure, conditions in suitable_structures:
            # Check if enabled
            strategy_name = structure.value.lower().replace('_', ' ')
            if structure == StructureType.IRON_CONDOR and "iron_condor" not in self.enabled_strategies:
                continue
            elif structure == StructureType.JADE_LIZARD and "jade_lizard" not in self.enabled_strategies:
                continue
            elif structure == StructureType.BUTTERFLY and "butterfly" not in self.enabled_strategies:
                continue
            elif structure == StructureType.BROKEN_WING_BUTTERFLY and "broken_wing_butterfly" not in self.enabled_strategies:
                continue
            elif structure == StructureType.RISK_REVERSAL and "risk_reversal" not in self.enabled_strategies:
                continue
            elif structure == StructureType.NAKED_STRANGLE and "naked_strangle" not in self.enabled_strategies:
                continue
            
            # Verify entry conditions are met
            should_enter, reason = StrategySelector.should_enter_structure(
                structure, regime_packet, conditions
            )
            
            if not should_enter:
                self.logger.info(f"Skipping {structure.value}: {reason}")
                continue
            
            self.logger.info(f"Entry conditions met for {structure.value}, generating proposal...")
            
            # Generate proposal for this structure
            proposal = None
            try:
                if structure == StructureType.IRON_CONDOR:
                    proposal = self._generate_iron_condor(regime_packet)
                elif structure == StructureType.JADE_LIZARD:
                    proposal = self._generate_jade_lizard(regime_packet)
                elif structure == StructureType.BUTTERFLY:
                    proposal = self._generate_butterfly(regime_packet)
                elif structure == StructureType.BROKEN_WING_BUTTERFLY:
                    proposal = self._generate_bwb(regime_packet)
                elif structure == StructureType.RISK_REVERSAL:
                    proposal = self._generate_risk_reversal(regime_packet)
                elif structure == StructureType.NAKED_STRANGLE:
                    proposal = self._generate_strangle(regime_packet)
            except Exception as e:
                self.logger.warning(f"Failed to generate {structure.value}: {e}")
                continue
            
            if proposal:
                # Set dynamic targets based on strategy type
                strategy_type = "SHORT_VOL" if structure in [
                    StructureType.IRON_CONDOR, StructureType.BUTTERFLY,
                    StructureType.JADE_LIZARD, StructureType.NAKED_STRANGLE
                ] else "DIRECTIONAL"
                self._set_dynamic_targets(proposal, strategy_type)
                
                proposals.append(proposal)
                self.logger.info(f"Generated {structure.value} proposal successfully")
            else:
                self.logger.warning(f"Failed to generate proposal for {structure.value} - returned None")
        
        # Limit to best proposal (avoid over-trading)
        if len(proposals) > 1:
            # Sort by risk-reward ratio (best first)
            proposals.sort(key=lambda p: p.risk_reward_ratio, reverse=True)
            proposals = proposals[:1]
            self.logger.debug(f"Selected best proposal: {proposals[0].structure}")
        
        return proposals
    
    def _generate_jade_lizard(self, regime: RegimePacket) -> Optional[TradeProposal]:
        """Generate Jade Lizard proposal using strategy module."""
        symbol = regime.symbol
        expiry = self._get_target_expiry(symbol, IC_MIN_DTE, IC_MAX_DTE)
        if not expiry:
            self.logger.warning(f"Jade Lizard: No expiry found for {symbol} with DTE {IC_MIN_DTE}-{IC_MAX_DTE}")
            return None
        
        option_chain = self.kite.get_option_chain(symbol, expiry)
        if option_chain.empty:
            self.logger.warning(f"Jade Lizard: Empty option chain for {symbol} expiry {expiry}")
            return None
        
        self.logger.info(f"Jade Lizard: Got {len(option_chain)} options for {symbol} expiry {expiry}")
        return self._jade_lizard.generate_proposal(regime, option_chain, expiry)
    
    def _generate_butterfly(self, regime: RegimePacket) -> Optional[TradeProposal]:
        """Generate Iron Butterfly proposal using strategy module."""
        symbol = regime.symbol
        expiry = self._get_target_expiry(symbol, IC_MIN_DTE, IC_MAX_DTE)
        if not expiry:
            return None
        
        option_chain = self.kite.get_option_chain(symbol, expiry)
        if option_chain.empty:
            return None
        
        return self._butterfly.generate_proposal(regime, option_chain, expiry)
    
    def _generate_bwb(self, regime: RegimePacket) -> Optional[TradeProposal]:
        """Generate Broken Wing Butterfly proposal using strategy module."""
        symbol = regime.symbol
        expiry = self._get_target_expiry(symbol, IC_MIN_DTE, IC_MAX_DTE)
        if not expiry:
            return None
        
        option_chain = self.kite.get_option_chain(symbol, expiry)
        if option_chain.empty:
            return None
        
        return self._bwb.generate_proposal(regime, option_chain, expiry)
    
    def _generate_strangle(self, regime: RegimePacket) -> Optional[TradeProposal]:
        """Generate Strangle proposal using strategy module."""
        symbol = regime.symbol
        expiry = self._get_target_expiry(symbol, IC_MIN_DTE, IC_MAX_DTE)
        if not expiry:
            return None
        
        option_chain = self.kite.get_option_chain(symbol, expiry)
        if option_chain.empty:
            return None
        
        proposal = self._strangle.generate_proposal(regime, option_chain, expiry)
        if not proposal:
            return None
            
        # Validate Greeks
        strikes = [leg.strike for leg in proposal.legs]
        if not self._validate_greeks(option_chain, strikes):
            return None
            
        return proposal
    
    def _generate_risk_reversal(self, regime: RegimePacket) -> Optional[TradeProposal]:
        """Generate Risk Reversal proposal using strategy module."""
        symbol = regime.symbol
        # Directional plays usually target 30-45 DTE
        expiry = self._get_target_expiry(symbol, 25, 45)
        if not expiry:
            self.logger.warning(f"Risk Reversal: No expiry found for {symbol} with DTE 25-45")
            return None
            
        option_chain = self.kite.get_option_chain(symbol, expiry)
        if option_chain.empty:
            self.logger.warning(f"Risk Reversal: Empty option chain for {symbol} expiry {expiry}")
            return None
        
        self.logger.info(f"Risk Reversal: Got {len(option_chain)} options for {symbol} expiry {expiry}")
            
        proposal = self._risk_reversal.generate_proposal(regime, option_chain, expiry)
        if not proposal:
            return None
            
        # Validate Greeks
        strikes = [leg.strike for leg in proposal.legs]
        if not self._validate_greeks(option_chain, strikes):
            return None
            
        return proposal
    
    def _validate_greeks(self, option_chain: pd.DataFrame, selected_strikes: List[float]) -> bool:
        """Validate that calculated Greeks match expected ranges."""
        
        for strike in selected_strikes:
            # Check if strike exists in chain
            if strike not in option_chain['strike'].values:
                continue
                
            # Get option rows (call and put) - simplified, just check any
            rows = option_chain[option_chain['strike'] == strike]
            if rows.empty:
                continue
                
            row = rows.iloc[0]
            
            # Check delta is reasonable (not > 1 or < -1)
            delta = row.get('delta', 0)
            if abs(delta) > 1.0:
                self.logger.warning(f"Invalid delta {delta} for strike {strike}")
                return False
            
            # Check theta exists (should be negative for longs in our context if we cared, 
            # but usually we sell. Actually, theta is negative for long options.
            # Short options have positive theta. Just check it's not zero/None if LTP > 0)
            theta = row.get('theta', 0)
            ltp = row.get('ltp', 0)
            if ltp > 5 and theta == 0:
                self.logger.warning(f"Theta missing for strike {strike} despite LTP {ltp}")
                return False
                
        return True
    
    def _is_entry_window(self) -> bool:
        """Check if current time is within entry window."""
        now = datetime.now().time()
        start = time(ENTRY_START_HOUR, ENTRY_START_MINUTE)
        end = time(ENTRY_END_HOUR, ENTRY_END_MINUTE)
        return start <= now <= end
    
    def _get_lot_size(self, symbol: str) -> int:
        """
        Get lot size for a symbol from Kite API (cached).
        
        Args:
            symbol: Underlying symbol (NIFTY, BANKNIFTY, etc.)
            
        Returns:
            Lot size for the symbol
        """
        if symbol in self._lot_size_cache:
            return self._lot_size_cache[symbol]
        
        lot_size = self.kite.get_lot_size(symbol)
        self._lot_size_cache[symbol] = lot_size
        self.logger.info(f"Lot size for {symbol}: {lot_size}")
        return lot_size

    def _generate_iron_condor(self, regime: RegimePacket) -> Optional[TradeProposal]:
        """
        Generate Iron Condor trade proposal.
        
        Entry conditions:
        - Regime is RANGE_BOUND
        - IV percentile > 40%
        - No events in 7 days
        - Previous day range < 1.2%
        - No gaps > 1.5% in 3 days
        - Days to expiry: 10-12
        """
        # Validate entry conditions
        if not self._validate_ic_conditions(regime):
            return None
        
        # Get option chain
        symbol = regime.symbol
        expiry = self._get_target_expiry(symbol, IC_MIN_DTE, IC_MAX_DTE)
        if not expiry:
            self.logger.warning("No suitable expiry found")
            return None
        
        option_chain = self.kite.get_option_chain(symbol, expiry)
        if option_chain.empty:
            self.logger.warning("Empty option chain")
            return None
        
        # Find strikes
        # Select strikes
        strikes = self._select_ic_strikes(option_chain, regime.spot_price)
        if not strikes:
            self.logger.warning("Could not select strikes")
            return None
            
        if not self._validate_greeks(option_chain, list(strikes)):
            self.logger.warning("Greeks validation failed for selected IC strikes")
            return None
        
        short_call_strike, short_put_strike, long_call_strike, long_put_strike = strikes
        
        # Build legs
        legs = self._build_ic_legs(option_chain, strikes, expiry, symbol=symbol)
        if not legs or len(legs) != 4:
            self.logger.warning("Could not build all legs")
            return None
        
        # Validate liquidity
        if not self._validate_liquidity(legs, option_chain):
            self.logger.warning("Liquidity check failed")
            return None
        
        # Calculate structure metrics
        net_credit = sum(
            leg.entry_price * (-1 if leg.is_short else 1)
            for leg in legs
        )
        
        wing_width = min(
            long_call_strike - short_call_strike,
            short_put_strike - long_put_strike
        )
        
        max_loss = wing_width - net_credit
        max_profit = net_credit
        target_pnl = max_profit * IC_PROFIT_TARGET
        stop_loss = -net_credit * IC_STOP_LOSS  # Loss = credit collected
        
        # Calculate Greeks (aggregate)
        greeks = {
            "delta": sum(leg.delta * (1 if leg.is_long else -1) for leg in legs),
            "gamma": sum(leg.gamma * (1 if leg.is_long else -1) for leg in legs),
            "theta": sum(leg.theta * (1 if leg.is_long else -1) for leg in legs),
            "vega": sum(leg.vega * (1 if leg.is_long else -1) for leg in legs)
        }
        
        # Get actual margin from Kite API
        required_margin = self._calculate_margin_from_api(legs, lot_size=65)
        if required_margin == 0:
            # Fallback estimation if API fails
            required_margin = wing_width * 65  # Lot size * wing width as rough estimate
            self.logger.warning(f"Using fallback margin estimate: ₹{required_margin:,.0f}")
        
        days_to_expiry = (expiry - date.today()).days
        
        proposal = TradeProposal(
            structure=StructureType.IRON_CONDOR,
            instrument=symbol,
            instrument_token=regime.instrument_token,
            legs=legs,
            entry_price=net_credit,
            is_credit=True,
            max_profit=max_profit,
            max_loss=max_loss,
            target_pnl=target_pnl,
            stop_loss=stop_loss,
            risk_reward_ratio=max_profit / max_loss if max_loss > 0 else 0,
            required_margin=required_margin,
            greeks=greeks,
            expiry=expiry,
            days_to_expiry=days_to_expiry,
            regime_at_entry=regime.regime.value,
            entry_reason=f"IC entry: IV={regime.metrics.iv_percentile:.1f}%, ADX={regime.metrics.adx:.1f}",
            is_intraday=False
        )
        
        self.logger.info(
            f"Generated IC proposal: credit={net_credit:.2f}, "
            f"max_loss={max_loss:.2f}, target={target_pnl:.2f}"
        )
        
        return proposal
    
    def _validate_ic_conditions(self, regime: RegimePacket) -> bool:
        """Validate Iron Condor entry conditions."""
        # Regime check
        if regime.regime != RegimeType.RANGE_BOUND:
            self.logger.debug(f"Regime not RANGE_BOUND: {regime.regime}")
            return False
        
        # IV check
        if regime.metrics.iv_percentile < IV_PERCENTILE_SHORT_VOL:
            self.logger.debug(f"IV too low: {regime.metrics.iv_percentile}")
            return False
        
        # Event check
        if regime.event_flag:
            self.logger.debug("Event blackout active")
            return False
        
        # Day range check
        if regime.day_range_pct > MAX_PREV_DAY_RANGE:
            self.logger.debug(f"Day range too high: {regime.day_range_pct:.2%}")
            return False
        
        # Gap check
        if abs(regime.gap_pct) > MAX_GAP_PCT:
            self.logger.debug(f"Gap too large: {regime.gap_pct:.2%}")
            return False
        
        return True
    
    def _get_target_expiry(
        self,
        symbol: str,
        min_dte: int,
        max_dte: int
    ) -> Optional[date]:
        """Get expiry date within target DTE range."""
        # Get available expiries from instruments API
        instruments = self.kite.get_instruments(NFO)
        if instruments.empty:
            self.logger.warning(f"Empty instruments list from Kite API for {NFO}")
            return None
        
        # Filter for symbol options
        options = instruments[
            (instruments['name'] == symbol) &
            (instruments['instrument_type'].isin(['CE', 'PE']))
        ]
        
        if options.empty:
            self.logger.warning(f"No options found for {symbol} in instruments")
            return None
        
        # Get unique expiries from API data
        expiries = pd.to_datetime(options['expiry'].unique()).date
        today = date.today()
        
        # Log available expiries for debugging
        sorted_expiries = sorted(expiries)
        self.logger.info(f"Available expiries for {symbol}: {sorted_expiries[:5]} (showing first 5)")
        
        # Find expiry in target range
        for exp in sorted_expiries:
            dte = (exp - today).days
            if min_dte <= dte <= max_dte:
                self.logger.info(f"Selected expiry {exp} (DTE={dte}) for {symbol}")
                return exp
        
        # If no exact match, find closest with DTE >= min_dte
        for exp in sorted_expiries:
            dte = (exp - today).days
            if dte >= min_dte:
                self.logger.info(f"Selected closest expiry {exp} (DTE={dte}) for {symbol}")
                return exp
        
        self.logger.warning(f"No suitable expiry found for {symbol} with DTE {min_dte}-{max_dte}")
        return None
    
    def _select_ic_strikes(
        self,
        option_chain: pd.DataFrame,
        spot: float
    ) -> Optional[Tuple[float, float, float, float]]:
        """
        Select Iron Condor strikes based on delta targeting.
        
        Returns:
            Tuple of (short_call, short_put, long_call, long_put) strikes
        """
        if option_chain.empty:
            return None
        
        calls = option_chain[option_chain['instrument_type'] == 'CE'].copy()
        puts = option_chain[option_chain['instrument_type'] == 'PE'].copy()
        
        if calls.empty or puts.empty:
            return None
        
        # Sort by strike
        calls = calls.sort_values('strike')
        puts = puts.sort_values('strike')
        
        # Find ATM strike
        atm_strike = self._find_atm_strike(option_chain, spot)
        
        # For 25-delta shorts, typically ~1-1.5 ATR away
        # Simplified: use percentage of spot
        short_call_strike = self._find_strike_by_delta(calls, spot, target_delta=0.25, is_call=True)
        short_put_strike = self._find_strike_by_delta(puts, spot, target_delta=-0.25, is_call=False)
        
        if not short_call_strike or not short_put_strike:
            # Fallback: use percentage-based selection
            short_call_strike = spot * 1.02  # 2% OTM
            short_put_strike = spot * 0.98   # 2% OTM
            
            # Round to nearest strike
            strikes = sorted(option_chain['strike'].unique())
            short_call_strike = min(strikes, key=lambda x: abs(x - short_call_strike))
            short_put_strike = min(strikes, key=lambda x: abs(x - short_put_strike))
        
        # Long strikes: 10 delta further OTM (wider wings)
        strike_step = self._get_strike_step(option_chain)
        wing_width = strike_step * 4  # 4 strikes wide
        
        long_call_strike = short_call_strike + wing_width
        long_put_strike = short_put_strike - wing_width
        
        # Validate strikes exist
        available_strikes = set(option_chain['strike'].unique())
        
        # Check if long call strike exists, otherwise find the highest available
        if long_call_strike not in available_strikes:
            higher_strikes = [s for s in available_strikes if s > short_call_strike]
            if not higher_strikes:
                self.logger.warning(f"No strikes available above short call {short_call_strike}, skipping IC")
                return None
            long_call_strike = max(higher_strikes)
        
        # Check if long put strike exists, otherwise find the lowest available
        if long_put_strike not in available_strikes:
            lower_strikes = [s for s in available_strikes if s < short_put_strike]
            if not lower_strikes:
                self.logger.warning(f"No strikes available below short put {short_put_strike}, skipping IC")
                return None
            long_put_strike = min(lower_strikes)
        
        return short_call_strike, short_put_strike, long_call_strike, long_put_strike
    
    def _find_atm_strike(self, option_chain: pd.DataFrame, spot: float) -> float:
        """Find the ATM strike closest to spot."""
        strikes = option_chain['strike'].unique()
        return min(strikes, key=lambda x: abs(x - spot))
    
    def _find_strike_by_delta(
        self,
        options: pd.DataFrame,
        spot: float,
        target_delta: float,
        is_call: bool
    ) -> Optional[float]:
        """
        Find strike with target delta.
        If delta not available, estimate based on moneyness.
        """
        # If delta column exists, use it
        if 'delta' in options.columns:
            options = options.copy()
            options['delta_diff'] = abs(options['delta'] - target_delta)
            best = options.loc[options['delta_diff'].idxmin()]
            return best['strike']
        
        # Estimate based on moneyness
        # 25-delta is roughly 1 standard deviation OTM
        # Simplified: ~2-3% OTM for weekly, ~4-5% for monthly
        if is_call:
            target_strike = spot * (1 + abs(target_delta) * 0.1)
        else:
            target_strike = spot * (1 - abs(target_delta) * 0.1)
        
        strikes = options['strike'].unique()
        return min(strikes, key=lambda x: abs(x - target_strike))
    
    def _get_strike_step(self, option_chain: pd.DataFrame) -> float:
        """Get the strike step/interval."""
        strikes = sorted(option_chain['strike'].unique())
        if len(strikes) < 2:
            return 50  # Default for NIFTY
        return strikes[1] - strikes[0]
    
    def _build_ic_legs(
        self,
        option_chain: pd.DataFrame,
        strikes: Tuple[float, float, float, float],
        expiry: date,
        symbol: str = "NIFTY"
    ) -> List[TradeLeg]:
        """Build the four legs of an Iron Condor."""
        short_call_strike, short_put_strike, long_call_strike, long_put_strike = strikes
        legs = []
        
        # Get spot price from option chain if available
        spot_price = None
        if 'underlying_price' in option_chain.columns:
            spot_price = option_chain['underlying_price'].iloc[0]
        elif not option_chain.empty:
            # Estimate from ATM strike
            spot_price = (short_call_strike + short_put_strike) / 2
        
        # Get lot size from Kite API
        lot_size = self._get_lot_size(symbol)
        
        # Short Call
        short_call = self._build_leg(
            option_chain, short_call_strike, 'CE', expiry,
            LegType.SHORT_CALL, quantity=lot_size, spot_price=spot_price
        )
        if short_call:
            legs.append(short_call)
        
        # Short Put
        short_put = self._build_leg(
            option_chain, short_put_strike, 'PE', expiry,
            LegType.SHORT_PUT, quantity=lot_size, spot_price=spot_price
        )
        if short_put:
            legs.append(short_put)
        
        # Long Call
        long_call = self._build_leg(
            option_chain, long_call_strike, 'CE', expiry,
            LegType.LONG_CALL, quantity=lot_size, spot_price=spot_price
        )
        if long_call:
            legs.append(long_call)
        
        # Long Put
        long_put = self._build_leg(
            option_chain, long_put_strike, 'PE', expiry,
            LegType.LONG_PUT, quantity=lot_size, spot_price=spot_price
        )
        if long_put:
            legs.append(long_put)
        
        return legs
    
    def _build_leg(
        self,
        option_chain: pd.DataFrame,
        strike: float,
        option_type: str,
        expiry: date,
        leg_type: LegType,
        quantity: int,
        spot_price: Optional[float] = None
    ) -> Optional[TradeLeg]:
        """Build a single trade leg with validated/calculated Greeks."""
        # Find the option in chain
        mask = (
            (option_chain['strike'] == strike) &
            (option_chain['instrument_type'] == option_type)
        )
        options = option_chain[mask]
        
        if options.empty:
            return None
        
        opt = options.iloc[0]
        
        # Get Greeks from chain (if available)
        chain_greeks = {
            'delta': opt.get('delta'),
            'gamma': opt.get('gamma'),
            'theta': opt.get('theta'),
            'vega': opt.get('vega')
        }
        
        # Get IV from chain or estimate
        iv = opt.get('iv', 0.20)  # Default to 20% if not available
        if iv is None or iv <= 0:
            iv = 0.20
        
        # Validate or calculate Greeks
        if spot_price is None:
            # Try to infer from option chain
            spot_price = opt.get('underlying_price', strike)
        
        greeks = validate_and_calculate_greeks(
            spot_price=spot_price,
            strike=strike,
            expiry_date=expiry,
            volatility=iv,
            option_type=option_type,
            chain_greeks=chain_greeks,
            calculator=self._greeks_calculator
        )
        
        return TradeLeg(
            leg_type=leg_type,
            tradingsymbol=opt.get('tradingsymbol', f"NIFTY{expiry.strftime('%y%b').upper()}{int(strike)}{option_type}"),
            instrument_token=int(opt.get('instrument_token', 0)),
            exchange=NFO,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            quantity=quantity,
            entry_price=float(opt.get('ltp', 0)),
            delta=greeks['delta'],
            gamma=greeks['gamma'],
            theta=greeks['theta'],
            vega=greeks['vega']
        )
    
    def _validate_liquidity(
        self,
        legs: List[TradeLeg],
        option_chain: pd.DataFrame
    ) -> bool:
        """Validate liquidity for all legs."""
        for leg in legs:
            mask = (
                (option_chain['strike'] == leg.strike) &
                (option_chain['instrument_type'] == leg.option_type)
            )
            opt = option_chain[mask]
            
            if opt.empty:
                return False
            
            opt = opt.iloc[0]
            
            # Check bid-ask spread
            bid = opt.get('bid', 0)
            ask = opt.get('ask', 0)
            if ask > 0 and bid > 0:
                spread = ask - bid
                if spread > MIN_BID_ASK_SPREAD:
                    self.logger.debug(f"Spread too wide for {leg.strike}: {spread}")
                    return False
            
            # Check OI
            oi = opt.get('oi', 0)
            if oi < MIN_OPEN_INTEREST:
                self.logger.debug(f"OI too low for {leg.strike}: {oi}")
                return False
        
        return True
    
    def _set_dynamic_targets(self, proposal: TradeProposal, structure_type: str) -> None:
        """
        Set dynamic exit targets based on structure and current conditions.
        
        Section 4 of rulebook:
        - Short-vol: 1.4-1.8% margin in low VIX, 1.2-1.5% in high VIX
        - Directional: 1.4-2.2% profit or 0.8-1.2% loss
        
        Section 11: Set up trailing profit logic
        """
        if structure_type == "SHORT_VOL":
            # Short-vol structures: target 1.4-1.8% margin
            proposal.exit_target_low = 0.014  # 1.4%
            proposal.exit_target_high = 0.018  # 1.8%
            proposal.exit_margin_type = "margin"
            proposal.trailing_mode = "bbw"  # BBW-based trailing
            proposal.target_pnl = proposal.max_profit * 0.50  # 50% initial target
            proposal.stop_loss = -proposal.max_loss * 0.35  # 35% of max loss
            
        elif structure_type == "DIRECTIONAL":
            # Directional: 1.4-2.2% profit or 0.8-1.2% loss
            proposal.exit_target_low = 0.014  # 1.4%
            proposal.exit_target_high = 0.022  # 2.2%
            proposal.exit_margin_type = "percentage"  # % of max profit
            proposal.trailing_mode = "atr"  # ATR-based trailing
            proposal.target_pnl = proposal.max_profit * 0.60  # 60% initial target
            proposal.stop_loss = -proposal.max_loss * 0.50  # 50% of max loss
        
        self.logger.debug(
            f"Dynamic targets: {structure_type} "
            f"target={proposal.target_pnl:.0f}, "
            f"trailing={proposal.trailing_mode}"
        )
    
    def _calculate_margin_from_api(self, legs: List[TradeLeg], lot_size: int = 75) -> float:
        """
        Calculate actual margin required using Kite order_margins API.
        
        Args:
            legs: List of TradeLeg objects
            lot_size: Lot size for the instrument
            
        Returns:
            Total margin required (float), or 0 if API call fails
        """
        if not legs:
            return 0.0
        
        # Build orders list for Kite API
        orders = []
        for leg in legs:
            order = {
                "exchange": leg.exchange or "NFO",
                "tradingsymbol": leg.tradingsymbol,
                "transaction_type": "SELL" if leg.is_short else "BUY",
                "variety": "regular",
                "product": "NRML",
                "order_type": "MARKET",
                "quantity": leg.quantity or lot_size,
                "price": 0
            }
            orders.append(order)
        
        # Create cache key
        cache_key = "_".join(sorted([o["tradingsymbol"] for o in orders]))
        if cache_key in self._margin_cache:
            return self._margin_cache[cache_key]
        
        try:
            # Use basket_margins for combined margin (accounts for hedging)
            basket = {"orders": orders}
            margin_result = self.kite.get_basket_margins(basket)
            
            if margin_result:
                # Basket margins returns combined margin with hedging benefit
                total_margin = margin_result.get("final", {}).get("total", 0)
                if total_margin == 0:
                    # Fallback to initial margin
                    total_margin = margin_result.get("initial", {}).get("total", 0)
                
                if total_margin > 0:
                    self._margin_cache[cache_key] = total_margin
                    self.logger.info(f"Kite API margin for {len(legs)} legs: ₹{total_margin:,.0f}")
                    return total_margin
            
            # Fallback: use order_margins for individual legs
            margin_results = self.kite.get_order_margins(orders)
            if margin_results:
                total_margin = sum(m.get("total", 0) for m in margin_results)
                if total_margin > 0:
                    self._margin_cache[cache_key] = total_margin
                    self.logger.info(f"Kite API margin (individual): ₹{total_margin:,.0f}")
                    return total_margin
                    
        except Exception as e:
            self.logger.warning(f"Failed to get margin from Kite API: {e}")
        
        return 0.0
