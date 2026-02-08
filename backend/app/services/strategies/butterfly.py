"""Butterfly strategy implementation for Trading System v2.0"""

from datetime import date
from typing import Optional, Tuple, List
import pandas as pd
from loguru import logger

from ..models.regime import RegimePacket, RegimeType
from ..models.trade import TradeProposal, TradeLeg, LegType, StructureType
from ..config.constants import NFO


class ButterflyStrategy:
    """
    Iron Butterfly strategy for low-vol, range-bound markets.
    
    Structure (Iron Butterfly):
    - Sell ATM call
    - Sell ATM put
    - Buy OTM call (wing)
    - Buy OTM put (wing)
    
    Benefits:
    - Maximum profit at ATM strike at expiry
    - Defined risk on both sides
    - Profits from time decay and pinning
    - Lower margin than iron condor
    
    Entry conditions:
    - Regime: RANGE_BOUND with high confidence
    - Low BBW (range contraction)
    - IV percentile 30-60% (moderate, not too low)
    - Neutral RSI
    """
    
    def __init__(self, lot_size: int = 50):
        self.lot_size = lot_size
        self.name = "IRON_BUTTERFLY"
    
    def check_entry_conditions(self, regime: RegimePacket) -> Tuple[bool, str]:
        """Check if entry conditions are met for butterfly."""
        # Regime check - butterflies need strong range-bound
        if regime.regime != RegimeType.RANGE_BOUND:
            return False, f"Regime not RANGE_BOUND: {regime.regime.value}"
        
        # Safety check
        if not regime.is_safe:
            return False, f"Regime not safe: {regime.safety_reasons}"
        
        # Confidence check - need high confidence for butterfly
        if regime.regime_confidence < 0.7:
            return False, f"Confidence too low: {regime.regime_confidence:.2f}"
        
        # IV check - need moderate IV (not too low, not too high)
        if regime.metrics.iv_percentile < 30:
            return False, f"IV too low for butterfly: {regime.metrics.iv_percentile:.1f}%"
        if regime.metrics.iv_percentile > 60:
            return False, f"IV too high for butterfly: {regime.metrics.iv_percentile:.1f}%"
        
        # BBW check - need low BBW (range contraction)
        bbw_ratio = regime.metrics.bbw_ratio or 1.0
        if bbw_ratio > 0.8:
            return False, f"BBW ratio too high: {bbw_ratio:.2f}"
        
        # RSI check - need neutral
        if not (40 <= regime.metrics.rsi <= 60):
            return False, f"RSI not neutral: {regime.metrics.rsi:.1f}"
        
        # Event check
        if regime.event_flag:
            return False, f"Event blackout: {regime.event_name}"
        
        return True, "All conditions met"
    
    def generate_proposal(
        self,
        regime: RegimePacket,
        option_chain: pd.DataFrame,
        expiry: date
    ) -> Optional[TradeProposal]:
        """Generate Iron Butterfly trade proposal."""
        conditions_met, reason = self.check_entry_conditions(regime)
        if not conditions_met:
            logger.debug(f"Butterfly conditions not met: {reason}")
            return None
        
        # Filter for liquid strikes first
        from .strategy_selector import StrategySelector
        liquid_chain = StrategySelector.filter_liquid_strikes(option_chain)
        if liquid_chain.empty or len(liquid_chain['strike'].unique()) < 6:
            logger.warning(f"Insufficient liquid strikes for Butterfly: {len(liquid_chain['strike'].unique()) if not liquid_chain.empty else 0} < 6")
            return None
        
        # Select strikes
        strikes = self._select_strikes(liquid_chain, regime.spot_price)
        if not strikes:
            return None
        
        atm_strike, lower_wing, upper_wing = strikes
        
        # Build legs
        legs = self._build_legs(option_chain, strikes, expiry)
        if len(legs) != 4:
            return None
        
        # Calculate metrics
        # Short ATM call + Short ATM put = credit
        # Long wings = debit
        short_credit = legs[0].entry_price + legs[1].entry_price  # ATM call + ATM put
        long_debit = legs[2].entry_price + legs[3].entry_price    # Wings
        net_credit = short_credit - long_debit
        
        # Max profit = net credit (if price pins at ATM)
        max_profit = net_credit * self.lot_size
        
        # Max loss = wing width - net credit
        wing_width = upper_wing - atm_strike
        max_loss = (wing_width - net_credit) * self.lot_size
        
        target_pnl = max_profit * 0.40  # 40% of max profit (conservative)
        stop_loss = -max_loss * 0.50    # 50% of max loss
        
        greeks = self._calculate_greeks(legs)
        required_margin = max_loss * 1.2
        
        days_to_expiry = (expiry - date.today()).days
        
        return TradeProposal(
            structure=StructureType.IRON_BUTTERFLY,
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
            position_size_pct=0.015,  # Smaller size for butterfly
            greeks=greeks,
            expiry=expiry,
            days_to_expiry=days_to_expiry,
            regime_at_entry=regime.regime.value,
            entry_reason=f"Butterfly: IV={regime.metrics.iv_percentile:.1f}%, BBW={regime.metrics.bbw_ratio:.2f}",
            is_intraday=False,
            exit_target_low=0.30,  # Target 30% of max profit
            exit_target_high=0.60  # Exit by 60% of max profit
        )
    
    def _select_strikes(
        self,
        option_chain: pd.DataFrame,
        spot: float
    ) -> Optional[Tuple[float, float, float]]:
        """Select strikes for Iron Butterfly."""
        if option_chain.empty:
            return None
        
        strikes = sorted(option_chain['strike'].unique())
        strike_step = strikes[1] - strikes[0] if len(strikes) > 1 else 50
        
        # ATM strike (closest to spot)
        atm_strike = min(strikes, key=lambda x: abs(x - spot))
        
        # Wings: 3-4 strikes away
        wing_distance = strike_step * 3
        
        lower_wing = atm_strike - wing_distance
        upper_wing = atm_strike + wing_distance
        
        # Validate strikes exist
        if lower_wing not in strikes:
            lower_wing = max(s for s in strikes if s < atm_strike)
        if upper_wing not in strikes:
            upper_wing = min(s for s in strikes if s > atm_strike)
        
        return atm_strike, lower_wing, upper_wing
    
    def _build_legs(
        self,
        option_chain: pd.DataFrame,
        strikes: Tuple[float, float, float],
        expiry: date
    ) -> List[TradeLeg]:
        """Build the four legs of Iron Butterfly."""
        atm_strike, lower_wing, upper_wing = strikes
        legs = []
        
        leg_configs = [
            (atm_strike, 'CE', LegType.SHORT_CALL),   # Short ATM call
            (atm_strike, 'PE', LegType.SHORT_PUT),    # Short ATM put
            (upper_wing, 'CE', LegType.LONG_CALL),    # Long OTM call
            (lower_wing, 'PE', LegType.LONG_PUT),     # Long OTM put
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


class BrokenWingButterflyStrategy:
    """
    Broken Wing Butterfly for directional bias with limited risk.
    
    Structure (Bearish BWB - Put):
    - Buy 1 ITM put
    - Sell 2 ATM puts
    - Buy 1 OTM put (further away - broken wing)
    
    Benefits:
    - Directional bias with defined risk
    - Can be entered for credit or small debit
    - Profits from move toward short strikes
    
    Entry conditions:
    - Regime: MEAN_REVERSION
    - RSI extreme (oversold for bullish BWB, overbought for bearish)
    """
    
    def __init__(self, lot_size: int = 50):
        self.lot_size = lot_size
        self.name = "BROKEN_WING_BUTTERFLY"
    
    def check_entry_conditions(self, regime: RegimePacket) -> Tuple[bool, str]:
        """Check if entry conditions are met."""
        # Regime check
        if regime.regime != RegimeType.MEAN_REVERSION:
            return False, f"Regime not MEAN_REVERSION: {regime.regime.value}"
        
        # Safety check
        if not regime.is_safe:
            return False, f"Regime not safe: {regime.safety_reasons}"
        
        # RSI check - need extreme for directional bias
        if not (regime.metrics.rsi < 35 or regime.metrics.rsi > 65):
            return False, f"RSI not extreme: {regime.metrics.rsi:.1f}"
        
        # IV check
        if regime.metrics.iv_percentile < 30:
            return False, f"IV too low: {regime.metrics.iv_percentile:.1f}%"
        
        # Event check
        if regime.event_flag:
            return False, f"Event blackout: {regime.event_name}"
        
        return True, "All conditions met"
    
    def generate_proposal(
        self,
        regime: RegimePacket,
        option_chain: pd.DataFrame,
        expiry: date
    ) -> Optional[TradeProposal]:
        """Generate Broken Wing Butterfly proposal."""
        conditions_met, reason = self.check_entry_conditions(regime)
        if not conditions_met:
            logger.debug(f"BWB conditions not met: {reason}")
            return None
        
        # Filter for liquid strikes first
        from .strategy_selector import StrategySelector
        liquid_chain = StrategySelector.filter_liquid_strikes(option_chain)
        if liquid_chain.empty or len(liquid_chain['strike'].unique()) < 6:
            logger.warning(f"Insufficient liquid strikes for BWB: {len(liquid_chain['strike'].unique()) if not liquid_chain.empty else 0} < 6")
            return None
        
        # Determine direction based on RSI
        is_bullish = regime.metrics.rsi < 35  # Oversold = expect bounce
        
        # Select strikes
        strikes = self._select_strikes(liquid_chain, regime.spot_price, is_bullish)
        if not strikes:
            return None
        
        body_strike, short_strike, broken_wing = strikes
        
        # Build legs
        legs = self._build_legs(option_chain, strikes, expiry, is_bullish)
        if len(legs) != 4:  # 1 + 2 + 1
            return None
        
        # Calculate metrics (simplified)
        net_premium = sum(
            leg.entry_price * (-1 if leg.is_short else 1)
            for leg in legs
        )
        
        # Max profit is at short strike
        max_profit = abs(body_strike - short_strike) * self.lot_size - abs(net_premium) * self.lot_size
        max_loss = abs(short_strike - broken_wing) * self.lot_size
        
        target_pnl = max_profit * 0.50
        stop_loss = -max_loss * 0.40
        
        greeks = self._calculate_greeks(legs)
        required_margin = max_loss * 1.3
        
        days_to_expiry = (expiry - date.today()).days
        direction = "Bullish" if is_bullish else "Bearish"
        
        return TradeProposal(
            structure=StructureType.BROKEN_WING_BUTTERFLY,
            instrument=regime.symbol,
            instrument_token=regime.instrument_token,
            legs=legs,
            entry_price=net_premium,
            is_credit=net_premium > 0,
            max_profit=max_profit,
            max_loss=max_loss,
            target_pnl=target_pnl,
            stop_loss=stop_loss,
            risk_reward_ratio=max_profit / max_loss if max_loss > 0 else 0,
            required_margin=required_margin,
            position_size_pct=0.015,
            greeks=greeks,
            expiry=expiry,
            days_to_expiry=days_to_expiry,
            regime_at_entry=regime.regime.value,
            entry_reason=f"BWB {direction}: RSI={regime.metrics.rsi:.1f}",
            is_intraday=False,
            exit_target_low=0.30,  # Target 30% of max profit
            exit_target_high=0.60  # Exit by 60% of max profit
        )
    
    def _select_strikes(
        self,
        option_chain: pd.DataFrame,
        spot: float,
        is_bullish: bool
    ) -> Optional[Tuple[float, float, float]]:
        """Select strikes for Broken Wing Butterfly."""
        if option_chain.empty:
            return None
        
        strikes = sorted(option_chain['strike'].unique())
        strike_step = strikes[1] - strikes[0] if len(strikes) > 1 else 50
        
        atm = min(strikes, key=lambda x: abs(x - spot))
        
        if is_bullish:
            # Bullish BWB with puts
            body_strike = atm - strike_step      # ITM put
            short_strike = atm - strike_step * 2  # ATM-ish puts (sell 2)
            broken_wing = atm - strike_step * 4   # Far OTM put
        else:
            # Bearish BWB with calls
            body_strike = atm + strike_step      # ITM call
            short_strike = atm + strike_step * 2  # ATM-ish calls (sell 2)
            broken_wing = atm + strike_step * 4   # Far OTM call
        
        # Validate
        for s in [body_strike, short_strike, broken_wing]:
            if s not in strikes:
                return None
        
        return body_strike, short_strike, broken_wing
    
    def _build_legs(
        self,
        option_chain: pd.DataFrame,
        strikes: Tuple[float, float, float],
        expiry: date,
        is_bullish: bool
    ) -> List[TradeLeg]:
        """Build BWB legs."""
        body_strike, short_strike, broken_wing = strikes
        opt_type = 'PE' if is_bullish else 'CE'
        legs = []
        
        leg_configs = [
            (body_strike, LegType.LONG_PUT if is_bullish else LegType.LONG_CALL, 1),
            (short_strike, LegType.SHORT_PUT if is_bullish else LegType.SHORT_CALL, 2),
            (broken_wing, LegType.LONG_PUT if is_bullish else LegType.LONG_CALL, 1),
        ]
        
        for strike, leg_type, qty_mult in leg_configs:
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
                quantity=self.lot_size * qty_mult,
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
