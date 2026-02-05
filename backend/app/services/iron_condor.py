"""Iron Condor strategy implementation for Trading System v2.0"""

from datetime import date
from typing import Optional, Tuple, List
import pandas as pd
from loguru import logger

from ..models.regime import RegimePacket, RegimeType
from ..models.trade import TradeProposal, TradeLeg, LegType, StructureType
from ..config.thresholds import (
    IV_ENTRY_MIN, IC_SHORT_DELTA, IC_LONG_DELTA,
    IC_PROFIT_TARGET, IC_STOP_LOSS, IC_MIN_DTE, IC_MAX_DTE,
    MAX_PREV_DAY_RANGE, MAX_GAP_PCT, MIN_BID_ASK_SPREAD, MIN_OPEN_INTEREST
)
from ..config.constants import NFO


class IronCondorStrategy:
    """
    Iron Condor strategy for range-bound markets.
    
    Entry conditions:
    - Regime is RANGE_BOUND
    - IV percentile > 40%
    - No events in 7 days
    - Previous day range < 1.2%
    - No gaps > 1.5% in 3 days
    - Days to expiry: 10-12
    
    Structure:
    - Short 25-delta call + Short 25-delta put
    - Long 15-delta call + Long 15-delta put
    
    Exit:
    - Profit: 60% of max profit
    - Stop: 100% of credit collected
    - Time: T-5 days mandatory
    """
    
    def __init__(self, lot_size: int = 50):
        self.lot_size = lot_size
        self.name = "IRON_CONDOR"
    
    def check_entry_conditions(self, regime: RegimePacket) -> Tuple[bool, str]:
        """
        Check if entry conditions are met.
        
        Returns:
            Tuple of (conditions_met, reason)
        """
        # Regime check
        if regime.regime != RegimeType.RANGE_BOUND:
            return False, f"Regime not RANGE_BOUND: {regime.regime.value}"
        
        # Safety check
        if not regime.is_safe:
            return False, f"Regime not safe: {regime.safety_reasons}"
        
        # IV check
        if regime.metrics.iv_percentile < IV_ENTRY_MIN:
            return False, f"IV too low: {regime.metrics.iv_percentile:.1f}% < {IV_ENTRY_MIN}%"
        
        # Event check
        if regime.event_flag:
            return False, f"Event blackout: {regime.event_name}"
        
        # Day range check
        if regime.day_range_pct > MAX_PREV_DAY_RANGE:
            return False, f"Day range too high: {regime.day_range_pct:.2%} > {MAX_PREV_DAY_RANGE:.2%}"
        
        # Gap check
        if abs(regime.gap_pct) > MAX_GAP_PCT:
            return False, f"Gap too large: {regime.gap_pct:.2%}"
        
        return True, "All conditions met"
    
    def generate_proposal(
        self,
        regime: RegimePacket,
        option_chain: pd.DataFrame,
        expiry: date
    ) -> Optional[TradeProposal]:
        """
        Generate Iron Condor trade proposal.
        
        Args:
            regime: Current regime packet
            option_chain: Option chain data
            expiry: Target expiry date
            
        Returns:
            TradeProposal or None if conditions not met
        """
        # Check entry conditions
        conditions_met, reason = self.check_entry_conditions(regime)
        if not conditions_met:
            logger.debug(f"IC entry conditions not met: {reason}")
            return None
        
        # Select strikes
        strikes = self._select_strikes(option_chain, regime.spot_price)
        if not strikes:
            logger.warning("Could not select IC strikes")
            return None
        
        short_call, short_put, long_call, long_put = strikes
        
        # Build legs
        legs = self._build_legs(option_chain, strikes, expiry)
        if len(legs) != 4:
            logger.warning(f"Could not build all legs: {len(legs)}/4")
            return None
        
        # Validate liquidity
        if not self._validate_liquidity(legs, option_chain):
            logger.warning("Liquidity validation failed")
            return None
        
        # Calculate metrics
        net_credit = sum(
            leg.entry_price * (-1 if leg.is_short else 1)
            for leg in legs
        )
        
        wing_width = min(
            long_call - short_call,
            short_put - long_put
        )
        
        max_loss = wing_width * self.lot_size - net_credit
        max_profit = net_credit
        target_pnl = max_profit * IC_PROFIT_TARGET
        stop_loss = -net_credit * IC_STOP_LOSS
        
        # Calculate Greeks
        greeks = self._calculate_greeks(legs)
        
        # Estimate margin
        required_margin = wing_width * self.lot_size * 1.5  # Conservative estimate
        
        days_to_expiry = (expiry - date.today()).days
        
        return TradeProposal(
            structure=StructureType.IRON_CONDOR,
            instrument=regime.symbol,
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
            position_size_pct=0.02,
            greeks=greeks,
            expiry=expiry,
            days_to_expiry=days_to_expiry,
            regime_at_entry=regime.regime.value,
            entry_reason=f"IC: IV={regime.metrics.iv_percentile:.1f}%, ADX={regime.metrics.adx:.1f}",
            is_intraday=False
        )
    
    def _select_strikes(
        self,
        option_chain: pd.DataFrame,
        spot: float
    ) -> Optional[Tuple[float, float, float, float]]:
        """Select strikes for Iron Condor."""
        if option_chain.empty:
            return None
        
        calls = option_chain[option_chain['instrument_type'] == 'CE']
        puts = option_chain[option_chain['instrument_type'] == 'PE']
        
        if calls.empty or puts.empty:
            return None
        
        # Find ATM
        strikes = sorted(option_chain['strike'].unique())
        atm = min(strikes, key=lambda x: abs(x - spot))
        
        # Short strikes: ~2% OTM (approximating 25-delta)
        short_call = min(strikes, key=lambda x: abs(x - spot * 1.02) if x > spot else float('inf'))
        short_put = min(strikes, key=lambda x: abs(x - spot * 0.98) if x < spot else float('inf'))
        
        # Get strike step
        strike_step = strikes[1] - strikes[0] if len(strikes) > 1 else 50
        
        # Long strikes: 4 strikes further OTM
        long_call = short_call + strike_step * 4
        long_put = short_put - strike_step * 4
        
        # Validate strikes exist
        if long_call not in strikes:
            long_call = max(s for s in strikes if s > short_call)
        if long_put not in strikes:
            long_put = min(s for s in strikes if s < short_put)
        
        return short_call, short_put, long_call, long_put
    
    def _build_legs(
        self,
        option_chain: pd.DataFrame,
        strikes: Tuple[float, float, float, float],
        expiry: date
    ) -> List[TradeLeg]:
        """Build the four legs of the Iron Condor."""
        short_call, short_put, long_call, long_put = strikes
        legs = []
        
        leg_configs = [
            (short_call, 'CE', LegType.SHORT_CALL),
            (short_put, 'PE', LegType.SHORT_PUT),
            (long_call, 'CE', LegType.LONG_CALL),
            (long_put, 'PE', LegType.LONG_PUT),
        ]
        
        for strike, opt_type, leg_type in leg_configs:
            leg = self._build_single_leg(option_chain, strike, opt_type, expiry, leg_type)
            if leg:
                legs.append(leg)
        
        return legs
    
    def _build_single_leg(
        self,
        option_chain: pd.DataFrame,
        strike: float,
        option_type: str,
        expiry: date,
        leg_type: LegType
    ) -> Optional[TradeLeg]:
        """Build a single leg."""
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
            tradingsymbol=opt.get('tradingsymbol', ''),
            instrument_token=int(opt.get('instrument_token', 0)),
            exchange=NFO,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            quantity=self.lot_size,
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
            
            # Check spread
            bid = opt.get('bid', 0)
            ask = opt.get('ask', 0)
            if bid > 0 and ask > 0 and (ask - bid) > MIN_BID_ASK_SPREAD:
                return False
            
            # Check OI
            if opt.get('oi', 0) < MIN_OPEN_INTEREST:
                return False
        
        return True
    
    def _calculate_greeks(self, legs: List[TradeLeg]) -> dict:
        """Calculate aggregate Greeks."""
        greeks = {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
        
        for leg in legs:
            multiplier = 1 if leg.is_long else -1
            greeks["delta"] += leg.delta * multiplier * leg.quantity
            greeks["gamma"] += leg.gamma * multiplier * leg.quantity
            greeks["theta"] += leg.theta * multiplier * leg.quantity
            greeks["vega"] += leg.vega * multiplier * leg.quantity
        
        return greeks
