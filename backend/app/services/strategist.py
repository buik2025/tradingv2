"""Strategist Agent - Signal Generation for Trading System v2.0"""

from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from loguru import logger

from .base_agent import BaseAgent
from ..core.kite_client import KiteClient
from ..config.settings import Settings
from ..config.constants import (
    ENTRY_START_HOUR, ENTRY_START_MINUTE, ENTRY_END_HOUR, ENTRY_END_MINUTE,
    NFO, BUY, SELL
)
from ..config.thresholds import (
    IV_ENTRY_MIN, IC_SHORT_DELTA, IC_LONG_DELTA,
    IC_PROFIT_TARGET, IC_STOP_LOSS, IC_MIN_DTE, IC_MAX_DTE,
    MAX_PREV_DAY_RANGE, MAX_GAP_PCT, EVENT_BLACKOUT_DAYS,
    MIN_BID_ASK_SPREAD, MIN_OPEN_INTEREST
)
from ..models.regime import RegimePacket, RegimeType
from ..models.trade import TradeProposal, TradeLeg, LegType, StructureType
from .jade_lizard import JadeLizardStrategy
from .butterfly import ButterflyStrategy, BrokenWingButterflyStrategy


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
    
    def __init__(self, kite: KiteClient, config: Settings):
        super().__init__(kite, config, name="Strategist")
        self._expiry_cache: Dict[str, List[date]] = {}
        
        # Initialize strategy modules
        self._jade_lizard = JadeLizardStrategy(lot_size=50)
        self._butterfly = ButterflyStrategy(lot_size=50)
        self._bwb = BrokenWingButterflyStrategy(lot_size=50)
    
    def process(self, regime_packet: RegimePacket) -> List[TradeProposal]:
        """
        Generate trade proposals based on regime.
        
        Strategy selection:
        - RANGE_BOUND: Iron Condor, Butterfly, Jade Lizard
        - CAUTION: Jade Lizard only (hedged structure)
        - MEAN_REVERSION: Broken Wing Butterfly, Risk Reversal
        - TREND/CHAOS: No new trades
        
        Args:
            regime_packet: Current regime assessment from Sentinel
            
        Returns:
            List of TradeProposal objects
        """
        proposals = []
        
        # Check if trading is allowed
        if not self._is_entry_window():
            self.logger.debug("Outside entry window")
            return proposals
        
        # CHAOS regime - no trades
        if regime_packet.regime == RegimeType.CHAOS:
            self.logger.info("CHAOS regime - no new trades")
            return proposals
        
        # CAUTION regime - only hedged structures (Jade Lizard)
        if regime_packet.regime == RegimeType.CAUTION:
            self.logger.info("CAUTION regime - generating hedged strategies only")
            jl_proposal = self._generate_jade_lizard(regime_packet)
            if jl_proposal:
                proposals.append(jl_proposal)
            return proposals
        
        # RANGE_BOUND - multiple short-vol strategies
        if regime_packet.allows_short_vol():
            self.logger.info("RANGE_BOUND - generating short-vol signals")
            
            # Iron Condor (primary)
            ic_proposal = self._generate_iron_condor(regime_packet)
            if ic_proposal:
                proposals.append(ic_proposal)
            
            # Butterfly (if high confidence and low BBW)
            bf_proposal = self._generate_butterfly(regime_packet)
            if bf_proposal:
                proposals.append(bf_proposal)
            
            # Jade Lizard (if IV > 35%)
            jl_proposal = self._generate_jade_lizard(regime_packet)
            if jl_proposal:
                proposals.append(jl_proposal)
        
        # MEAN_REVERSION - directional strategies
        elif regime_packet.allows_directional():
            self.logger.info("MEAN_REVERSION - generating directional signals")
            
            # Broken Wing Butterfly
            bwb_proposal = self._generate_bwb(regime_packet)
            if bwb_proposal:
                proposals.append(bwb_proposal)
        
        # TREND - limited strategies
        elif regime_packet.regime == RegimeType.TREND:
            self.logger.info("TREND regime - limited strategies")
            # Could add trend-following strategies here
            pass
        
        else:
            self.logger.debug(f"No signals for regime: {regime_packet.regime}")
        
        # Limit to best proposal (avoid over-trading)
        if len(proposals) > 1:
            # Sort by risk-reward ratio
            proposals.sort(key=lambda p: p.risk_reward_ratio, reverse=True)
            proposals = proposals[:1]  # Keep only best
        
        return proposals
    
    def _generate_jade_lizard(self, regime: RegimePacket) -> Optional[TradeProposal]:
        """Generate Jade Lizard proposal using strategy module."""
        symbol = regime.symbol
        expiry = self._get_target_expiry(symbol, IC_MIN_DTE, IC_MAX_DTE)
        if not expiry:
            return None
        
        option_chain = self.kite.get_option_chain(symbol, expiry)
        if option_chain.empty:
            return None
        
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
    
    def _is_entry_window(self) -> bool:
        """Check if current time is within entry window."""
        now = datetime.now().time()
        start = time(ENTRY_START_HOUR, ENTRY_START_MINUTE)
        end = time(ENTRY_END_HOUR, ENTRY_END_MINUTE)
        return start <= now <= end
    
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
        spot = regime.spot_price
        strikes = self._select_ic_strikes(option_chain, spot)
        if not strikes:
            self.logger.warning("Could not select strikes")
            return None
        
        short_call_strike, short_put_strike, long_call_strike, long_put_strike = strikes
        
        # Build legs
        legs = self._build_ic_legs(option_chain, strikes, expiry)
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
        
        # Estimate margin (simplified - actual margin from broker)
        required_margin = wing_width * 50  # Lot size * wing width as rough estimate
        
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
        if regime.metrics.iv_percentile < IV_ENTRY_MIN:
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
        # Get available expiries from instruments
        instruments = self.kite.get_instruments(NFO)
        if instruments.empty:
            return None
        
        # Filter for symbol options
        options = instruments[
            (instruments['name'] == symbol) &
            (instruments['instrument_type'].isin(['CE', 'PE']))
        ]
        
        if options.empty:
            return None
        
        # Get unique expiries
        expiries = pd.to_datetime(options['expiry'].unique()).date
        today = date.today()
        
        # Find expiry in target range
        for exp in sorted(expiries):
            dte = (exp - today).days
            if min_dte <= dte <= max_dte:
                return exp
        
        # If no exact match, find closest
        for exp in sorted(expiries):
            dte = (exp - today).days
            if dte >= min_dte:
                return exp
        
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
        if long_call_strike not in available_strikes:
            long_call_strike = max(s for s in available_strikes if s > short_call_strike)
        if long_put_strike not in available_strikes:
            long_put_strike = min(s for s in available_strikes if s < short_put_strike)
        
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
        expiry: date
    ) -> List[TradeLeg]:
        """Build the four legs of an Iron Condor."""
        short_call_strike, short_put_strike, long_call_strike, long_put_strike = strikes
        legs = []
        
        # Short Call
        short_call = self._build_leg(
            option_chain, short_call_strike, 'CE', expiry,
            LegType.SHORT_CALL, quantity=50  # NIFTY lot size
        )
        if short_call:
            legs.append(short_call)
        
        # Short Put
        short_put = self._build_leg(
            option_chain, short_put_strike, 'PE', expiry,
            LegType.SHORT_PUT, quantity=50
        )
        if short_put:
            legs.append(short_put)
        
        # Long Call
        long_call = self._build_leg(
            option_chain, long_call_strike, 'CE', expiry,
            LegType.LONG_CALL, quantity=50
        )
        if long_call:
            legs.append(long_call)
        
        # Long Put
        long_put = self._build_leg(
            option_chain, long_put_strike, 'PE', expiry,
            LegType.LONG_PUT, quantity=50
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
        quantity: int
    ) -> Optional[TradeLeg]:
        """Build a single trade leg."""
        # Find the option in chain
        mask = (
            (option_chain['strike'] == strike) &
            (option_chain['instrument_type'] == option_type)
        )
        options = option_chain[mask]
        
        if options.empty:
            return None
        
        opt = options.iloc[0]
        
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
            delta=float(opt.get('delta', 0.25 if option_type == 'CE' else -0.25)),
            gamma=float(opt.get('gamma', 0.01)),
            theta=float(opt.get('theta', -5)),
            vega=float(opt.get('vega', 10))
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
