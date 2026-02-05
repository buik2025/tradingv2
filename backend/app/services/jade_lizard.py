"""Jade Lizard strategy implementation for Trading System v2.0"""

from datetime import date
from typing import Optional, Tuple, List
import pandas as pd
from loguru import logger

from ..models.regime import RegimePacket, RegimeType
from ..models.trade import TradeProposal, TradeLeg, LegType, StructureType
from ..config.constants import NFO


class JadeLizardStrategy:
    """
    Jade Lizard strategy for bullish/neutral outlook with high IV.
    
    Structure:
    - Short OTM put (collect premium)
    - Short call spread (cap upside risk)
    
    Benefits:
    - No upside risk (credit from call spread >= put strike distance)
    - Profits from time decay and IV crush
    - Defined risk on downside
    
    Entry conditions:
    - Regime: RANGE_BOUND or MEAN_REVERSION (bullish)
    - IV percentile > 50%
    - Bullish or neutral bias
    """
    
    def __init__(self, lot_size: int = 50):
        self.lot_size = lot_size
        self.name = "JADE_LIZARD"
    
    def check_entry_conditions(self, regime: RegimePacket) -> Tuple[bool, str]:
        """
        Check if entry conditions are met.
        
        Jade Lizard is ideal for CAUTION regime (hedged structure).
        Also works in RANGE_BOUND and MEAN_REVERSION.
        """
        # Regime check - Jade Lizard works in CAUTION (it's hedged)
        allowed_regimes = [RegimeType.RANGE_BOUND, RegimeType.MEAN_REVERSION, RegimeType.CAUTION]
        if regime.regime not in allowed_regimes:
            return False, f"Regime not suitable: {regime.regime.value}"
        
        # For CAUTION regime, we allow entry (it's a hedged structure)
        # For other regimes, check safety
        if regime.regime != RegimeType.CAUTION and not regime.is_safe:
            return False, f"Regime not safe: {regime.safety_reasons}"
        
        # IV check - need moderate IV for jade lizard (lowered from 50 to 35)
        if regime.metrics.iv_percentile < 35:
            return False, f"IV too low: {regime.metrics.iv_percentile:.1f}% < 35%"
        
        # Event check
        if regime.event_flag:
            return False, f"Event blackout: {regime.event_name}"
        
        # RSI check for bullish/neutral bias (relaxed for CAUTION)
        min_rsi = 35 if regime.regime == RegimeType.CAUTION else 40
        if regime.metrics.rsi < min_rsi:
            return False, f"RSI too bearish: {regime.metrics.rsi:.1f}"
        
        return True, "All conditions met"
    
    def generate_proposal(
        self,
        regime: RegimePacket,
        option_chain: pd.DataFrame,
        expiry: date
    ) -> Optional[TradeProposal]:
        """Generate Jade Lizard trade proposal."""
        conditions_met, reason = self.check_entry_conditions(regime)
        if not conditions_met:
            logger.debug(f"Jade Lizard conditions not met: {reason}")
            return None
        
        # Select strikes
        strikes = self._select_strikes(option_chain, regime.spot_price)
        if not strikes:
            return None
        
        short_put, short_call, long_call = strikes
        
        # Build legs
        legs = self._build_legs(option_chain, strikes, expiry)
        if len(legs) != 3:
            return None
        
        # Calculate metrics
        put_credit = legs[0].entry_price  # Short put
        call_spread_credit = legs[1].entry_price - legs[2].entry_price  # Short call - long call
        net_credit = put_credit + call_spread_credit
        
        # Max loss is on downside (put strike - net credit)
        max_loss = (short_put - net_credit) * self.lot_size
        
        # No upside risk if call spread credit >= distance to short put
        upside_risk = max(0, (short_call - regime.spot_price) - call_spread_credit) * self.lot_size
        
        max_profit = net_credit * self.lot_size
        target_pnl = max_profit * 0.50  # 50% of max profit
        stop_loss = -max_loss * 0.50  # 50% of max loss
        
        greeks = self._calculate_greeks(legs)
        required_margin = max_loss * 1.5
        
        days_to_expiry = (expiry - date.today()).days
        
        return TradeProposal(
            structure=StructureType.JADE_LIZARD,
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
            entry_reason=f"JL: IV={regime.metrics.iv_percentile:.1f}%, RSI={regime.metrics.rsi:.1f}",
            is_intraday=False
        )
    
    def _select_strikes(
        self,
        option_chain: pd.DataFrame,
        spot: float
    ) -> Optional[Tuple[float, float, float]]:
        """Select strikes for Jade Lizard."""
        if option_chain.empty:
            return None
        
        strikes = sorted(option_chain['strike'].unique())
        strike_step = strikes[1] - strikes[0] if len(strikes) > 1 else 50
        
        # Short put: ~3% OTM
        short_put = min(strikes, key=lambda x: abs(x - spot * 0.97) if x < spot else float('inf'))
        
        # Short call: ~2% OTM
        short_call = min(strikes, key=lambda x: abs(x - spot * 1.02) if x > spot else float('inf'))
        
        # Long call: 2-3 strikes above short call
        long_call = short_call + strike_step * 2
        if long_call not in strikes:
            long_call = max(s for s in strikes if s > short_call)
        
        return short_put, short_call, long_call
    
    def _build_legs(
        self,
        option_chain: pd.DataFrame,
        strikes: Tuple[float, float, float],
        expiry: date
    ) -> List[TradeLeg]:
        """Build the three legs of Jade Lizard."""
        short_put, short_call, long_call = strikes
        legs = []
        
        leg_configs = [
            (short_put, 'PE', LegType.SHORT_PUT),
            (short_call, 'CE', LegType.SHORT_CALL),
            (long_call, 'CE', LegType.LONG_CALL),
        ]
        
        for strike, opt_type, leg_type in leg_configs:
            mask = (
                (option_chain['strike'] == strike) &
                (option_chain['instrument_type'] == opt_type)
            )
            options = option_chain[mask]
            
            if options.empty:
                continue
            
            opt = options.iloc[0]
            legs.append(TradeLeg(
                leg_type=leg_type,
                tradingsymbol=opt.get('tradingsymbol', ''),
                instrument_token=int(opt.get('instrument_token', 0)),
                exchange=NFO,
                strike=strike,
                expiry=expiry,
                option_type=opt_type,
                quantity=self.lot_size,
                entry_price=float(opt.get('ltp', 0)),
                delta=float(opt.get('delta', 0)),
                gamma=float(opt.get('gamma', 0)),
                theta=float(opt.get('theta', 0)),
                vega=float(opt.get('vega', 0))
            ))
        
        return legs
    
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
