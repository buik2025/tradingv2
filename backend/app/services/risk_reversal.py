"""Risk Reversal strategy implementation for Trading System v2.0"""

from datetime import date
from typing import Optional, Tuple, List
import pandas as pd
from loguru import logger

from ..models.regime import RegimePacket, RegimeType
from ..models.trade import TradeProposal, TradeLeg, LegType, StructureType
from ..config.constants import NFO


class RiskReversalStrategy:
    """
    Risk Reversal strategy for directional plays.
    
    Structure (Bullish):
    - Short OTM put (fund the trade)
    - Long OTM call (directional exposure)
    
    Structure (Bearish):
    - Short OTM call
    - Long OTM put
    
    Entry conditions:
    - Regime: MEAN_REVERSION with extreme RSI
    - Clear directional bias
    - IV not too high (avoid overpaying for long option)
    """
    
    def __init__(self, lot_size: int = 50):
        self.lot_size = lot_size
        self.name = "RISK_REVERSAL"
    
    def check_entry_conditions(self, regime: RegimePacket) -> Tuple[bool, str, str]:
        """
        Check if entry conditions are met.
        
        Returns:
            Tuple of (conditions_met, reason, direction)
        """
        # Regime check
        if regime.regime != RegimeType.MEAN_REVERSION:
            return False, f"Regime not MEAN_REVERSION: {regime.regime.value}", ""
        
        # Safety check
        if not regime.is_safe:
            return False, f"Regime not safe: {regime.safety_reasons}", ""
        
        # IV check (not too high for buying options)
        if regime.metrics.iv_percentile > 70:
            return False, f"IV too high for long options: {regime.metrics.iv_percentile:.1f}%", ""
        
        # Event check
        if regime.event_flag:
            return False, f"Event blackout: {regime.event_name}", ""
        
        # Determine direction from RSI
        if regime.metrics.rsi < 30:
            return True, "Bullish reversal setup", "BULLISH"
        elif regime.metrics.rsi > 70:
            return True, "Bearish reversal setup", "BEARISH"
        else:
            return False, f"RSI not extreme: {regime.metrics.rsi:.1f}", ""
    
    def generate_proposal(
        self,
        regime: RegimePacket,
        option_chain: pd.DataFrame,
        expiry: date
    ) -> Optional[TradeProposal]:
        """Generate Risk Reversal trade proposal."""
        conditions_met, reason, direction = self.check_entry_conditions(regime)
        if not conditions_met:
            logger.debug(f"Risk Reversal conditions not met: {reason}")
            return None
        
        # Select strikes based on direction
        strikes = self._select_strikes(option_chain, regime.spot_price, direction)
        if not strikes:
            return None
        
        # Build legs
        legs = self._build_legs(option_chain, strikes, expiry, direction)
        if len(legs) != 2:
            return None
        
        # Calculate metrics
        short_leg = legs[0]  # Short option
        long_leg = legs[1]   # Long option
        
        net_premium = short_leg.entry_price - long_leg.entry_price
        is_credit = net_premium > 0
        
        # Risk is theoretically unlimited on short side
        # Use a practical stop based on spot movement
        if direction == "BULLISH":
            max_loss = strikes[0] * self.lot_size * 0.1  # 10% of put strike
        else:
            max_loss = regime.spot_price * self.lot_size * 0.1  # 10% of spot
        
        # Profit potential is significant on directional move
        max_profit = regime.spot_price * self.lot_size * 0.05  # 5% move target
        
        target_pnl = max_profit * 0.60
        stop_loss = -max_loss * 0.50
        
        greeks = self._calculate_greeks(legs)
        required_margin = max_loss * 2  # Higher margin for undefined risk
        
        days_to_expiry = (expiry - date.today()).days
        
        return TradeProposal(
            structure=StructureType.RISK_REVERSAL,
            instrument=regime.symbol,
            instrument_token=regime.instrument_token,
            legs=legs,
            entry_price=abs(net_premium),
            is_credit=is_credit,
            max_profit=max_profit,
            max_loss=max_loss,
            target_pnl=target_pnl,
            stop_loss=stop_loss,
            risk_reward_ratio=max_profit / max_loss if max_loss > 0 else 0,
            required_margin=required_margin,
            position_size_pct=0.015,  # Smaller size for undefined risk
            greeks=greeks,
            expiry=expiry,
            days_to_expiry=days_to_expiry,
            regime_at_entry=regime.regime.value,
            entry_reason=f"RR {direction}: RSI={regime.metrics.rsi:.1f}, IV={regime.metrics.iv_percentile:.1f}%",
            is_intraday=False
        )
    
    def _select_strikes(
        self,
        option_chain: pd.DataFrame,
        spot: float,
        direction: str
    ) -> Optional[Tuple[float, float]]:
        """Select strikes for Risk Reversal."""
        if option_chain.empty:
            return None
        
        strikes = sorted(option_chain['strike'].unique())
        
        if direction == "BULLISH":
            # Short put ~3% OTM, Long call ~2% OTM
            short_strike = min(strikes, key=lambda x: abs(x - spot * 0.97) if x < spot else float('inf'))
            long_strike = min(strikes, key=lambda x: abs(x - spot * 1.02) if x > spot else float('inf'))
        else:
            # Short call ~3% OTM, Long put ~2% OTM
            short_strike = min(strikes, key=lambda x: abs(x - spot * 1.03) if x > spot else float('inf'))
            long_strike = min(strikes, key=lambda x: abs(x - spot * 0.98) if x < spot else float('inf'))
        
        return short_strike, long_strike
    
    def _build_legs(
        self,
        option_chain: pd.DataFrame,
        strikes: Tuple[float, float],
        expiry: date,
        direction: str
    ) -> List[TradeLeg]:
        """Build the two legs of Risk Reversal."""
        short_strike, long_strike = strikes
        legs = []
        
        if direction == "BULLISH":
            leg_configs = [
                (short_strike, 'PE', LegType.SHORT_PUT),
                (long_strike, 'CE', LegType.LONG_CALL),
            ]
        else:
            leg_configs = [
                (short_strike, 'CE', LegType.SHORT_CALL),
                (long_strike, 'PE', LegType.LONG_PUT),
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
