"""Strangle Strategy Implementation

Naked Strangle strategy for directional moves with defined risk.
Targets 0.8-1% profit on margin with proper risk controls.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
from loguru import logger

from ..models.trade import TradeProposal, TradeLeg, LegType
from ..models.regime import RegimePacket, RegimeType
from ..config.thresholds import (
    MAX_LOSS_PER_TRADE,
    IV_PERCENTILE_SHORT_VOL,
    IV_PERCENTILE_STRANGLE,
    STRANGLE_DELTA_TARGET,
    STRANGLE_PROFIT_TARGET,
    MIN_BID_ASK_SPREAD,
    MIN_OPEN_INTEREST,
    RSI_NEUTRAL_MIN,
    RSI_NEUTRAL_MAX
)


class StrangleStrategy:
    """
    Naked Strangle strategy implementation.
    
    Strategy:
    - Sell OTM call + OTM put
    - Collect premium, profit from theta decay
    - Best for directional moves or high IV environments
    - Target: 0.8-1% of margin as profit
    """
    
    def __init__(self, kite_client):
        self.kite = kite_client
        self.logger = logger.bind(component="strangle")
    
    def generate_proposal(
        self,
        regime: RegimePacket,
        option_chain: Dict,
        expiry: datetime
    ) -> Optional[TradeProposal]:
        """Generate strangle proposal."""
        symbol = regime.symbol
        spot = regime.spot_price
        
        # Check IV condition (need elevated IV for better premiums)
        # Check IV condition
        # Strangles work best in low-to-moderate IV (theta decay) or high IV (premium)
        # We prioritize low IV range-bound
        pass  # Logic moved to _is_regime_suitable
        
        # Check regime suitability
        if not self._is_regime_suitable(regime):
            return None
        
        # Calculate strikes
        call_strike, put_strike = self._select_strikes(spot, option_chain, regime)
        
        if not call_strike or not put_strike:
            self.logger.debug("Could not select suitable strikes")
            return None
        
        # Get option details
        if isinstance(option_chain, pd.DataFrame):
            call_option_rows = option_chain[(option_chain['strike'] == call_strike) & (option_chain['instrument_type'] == 'CE')]
            put_option_rows = option_chain[(option_chain['strike'] == put_strike) & (option_chain['instrument_type'] == 'PE')]
            
            if call_option_rows.empty or put_option_rows.empty:
                self.logger.debug("Missing option data for selected strikes")
                return None
            
            call_option = call_option_rows.iloc[0].to_dict()
            put_option = put_option_rows.iloc[0].to_dict()
        else:
            call_option = option_chain['calls'].get(call_strike)
            put_option = option_chain['puts'].get(put_strike)
            
            if not call_option or not put_option:
                self.logger.debug("Missing option data for selected strikes")
                return None
        
        # Check liquidity
        if not self._check_liquidity(call_option, put_option):
            return None
        
        # Calculate position metrics
        premium = call_option['last_price'] + put_option['last_price']
        margin = self._estimate_margin(spot, call_strike, put_strike)
        margin = self._estimate_margin(spot, call_strike, put_strike)
        profit_target_pct = STRANGLE_PROFIT_TARGET
        profit_target = margin * profit_target_pct
        
        # Check risk-reward
        if premium < profit_target * 0.3:  # Premium should be at least 30% of target
            self.logger.debug(f"Premium too low: {premium:.2f} vs target {profit_target:.2f}")
            return None
        
        # Create legs
        legs = [
            TradeLeg(
                leg_id=f"CALL_{call_strike}",
                instrument_token=call_option['instrument_token'],
                tradingsymbol=call_option['tradingsymbol'],
                leg_type=LegType.SHORT_CALL,
                strike=call_strike,
                expiry=expiry,
                quantity=50,  # 1 lot for NIFTY
                entry_price=call_option['last_price']
            ),
            TradeLeg(
                leg_id=f"PUT_{put_strike}",
                instrument_token=put_option['instrument_token'],
                tradingsymbol=put_option['tradingsymbol'],
                leg_type=LegType.SHORT_PUT,
                strike=put_strike,
                expiry=expiry,
                quantity=50,  # 1 lot for NIFTY
                entry_price=put_option['last_price']
            )
        ]
        
        # Calculate max loss (unlimited for naked options, but we use stop loss)
        max_loss = margin * MAX_LOSS_PER_TRADE  # Cap at 1.5% of margin
        
        # Create proposal
        proposal = TradeProposal(
            id=f"STRANGLE_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            structure="NAKED_STRANGLE",
            instrument=symbol,
            instrument_token=regime.instrument_token,
            legs=legs,
            entry_premium=premium,
            max_profit=premium,  # Max profit is premium collected
            max_loss=max_loss,
            target_pnl=profit_target,
            stop_loss=margin * 0.02,  # 2% of margin as stop loss
            confidence=0.65,  # Moderate confidence due to unlimited risk
            regime_at_entry=regime.regime.value,
            expiry=expiry,
            notes=f"Strangle: C{call_strike}/P{put_strike}, IV={regime.metrics.iv_percentile:.1f}%, Target={profit_target_pct*100:.1f}%"
        )
        
        self.logger.info(f"Generated strangle proposal: {proposal.notes}")
        return proposal
    
    def _is_regime_suitable(self, regime: RegimePacket) -> bool:
        """Strangles are BEST for RANGE_BOUND markets."""
        
        # PRIMARY: Range-bound with low ADX
        if regime.regime == RegimeType.RANGE_BOUND:
            # Perfect for strangles - low ADX means no breakout
            # If IV is ultra-low (<15%), it's the "Strangle Zone"
            if regime.metrics.iv_percentile < IV_PERCENTILE_STRANGLE:
                return True
            # Also good if IV is just low/moderate
            elif regime.metrics.iv_percentile < IV_PERCENTILE_SHORT_VOL:
                return True
            
        # SECONDARY: Mean-reversion with neutral RSI
        if regime.regime == RegimeType.MEAN_REVERSION:
            # Only if RSI neutral (35-65), not at extremes
            if RSI_NEUTRAL_MIN < regime.metrics.rsi < RSI_NEUTRAL_MAX:
                return regime.metrics.iv_percentile < IV_PERCENTILE_SHORT_VOL
        
        return False
    
    def _select_strikes(
        self,
        spot: float,
        option_chain,  # Can be Dict or DataFrame
        regime: RegimePacket
    ) -> Tuple[Optional[float], Optional[float]]:
        """Select OTM strikes for strangle based on delta (~0.30)."""
        
        # Target delta for strangle: PE delta ~0.3, CE delta ~0.3
        target_delta = STRANGLE_DELTA_TARGET
        
        # Handle DataFrame option chain (from backtester)
        if isinstance(option_chain, pd.DataFrame):
            calls_df = option_chain[option_chain['instrument_type'] == 'CE'] if 'instrument_type' in option_chain.columns else pd.DataFrame()
            puts_df = option_chain[option_chain['instrument_type'] == 'PE'] if 'instrument_type' in option_chain.columns else pd.DataFrame()
            
            call_strike = None
            call_delta_diff = float('inf')
            
            for _, row in calls_df.iterrows():
                delta = row.get('delta', 0)
                strike = row.get('strike', 0)
                if delta > 0.26 and delta < 0.33:  # OTM call delta range
                    diff = abs(delta - target_delta)
                    if diff < call_delta_diff:
                        call_delta_diff = diff
                        call_strike = strike
            
            put_strike = None
            put_delta_diff = float('inf')
            
            for _, row in puts_df.iterrows():
                delta = row.get('delta', 0)
                strike = row.get('strike', 0)
                if delta < -0.26 and delta > -0.33:  # OTM put delta range
                    diff = abs(delta + target_delta)  # delta is negative for puts
                    if diff < put_delta_diff:
                        put_delta_diff = diff
                        put_strike = strike
        
        # Handle dict option chain (from live trading)
        elif isinstance(option_chain, dict) and 'calls' in option_chain and 'puts' in option_chain:
            call_strike = None
            call_delta_diff = float('inf')
            
            for strike, option_data in option_chain['calls'].items():
                delta = option_data.get('delta', 0)
                if delta > 0.26 and delta < 0.33:  # OTM call delta range
                    diff = abs(delta - target_delta)
                    if diff < call_delta_diff:
                        call_delta_diff = diff
                        call_strike = strike
            
            put_strike = None
            put_delta_diff = float('inf')
            
            for strike, option_data in option_chain['puts'].items():
                delta = option_data.get('delta', 0)
                if delta < -0.26 and delta > -0.33:  # OTM put delta range
                    diff = abs(delta + target_delta)  # delta is negative for puts
                    if diff < put_delta_diff:
                        put_delta_diff = diff
                        put_strike = strike
        else:
            self.logger.debug("Unsupported option_chain format")
            return None, None
        
        # Validate strikes
        if not call_strike or not put_strike:
            self.logger.debug(f"Could not find suitable delta strikes: C={call_strike}, P={put_strike}")
            return None, None
        
        # Ensure strikes are OTM
        if call_strike <= spot:
            self.logger.debug(f"Call strike {call_strike} is not OTM (spot={spot})")
            return None, None
        
        if put_strike >= spot:
            self.logger.debug(f"Put strike {put_strike} is not OTM (spot={spot})")
            return None, None
        
        self.logger.debug(f"Selected delta-based strikes: C{call_strike}, P{put_strike}")
        
        return call_strike, put_strike
    
    def _check_liquidity(self, call_option: Dict, put_option: Dict) -> bool:
        """Check if options have sufficient liquidity."""
        
        # Check bid-ask spreads
        call_spread = call_option.get('ask', 0) - call_option.get('bid', 0)
        put_spread = put_option.get('ask', 0) - put_option.get('bid', 0)
        
        if call_spread > MIN_BID_ASK_SPREAD or put_spread > MIN_BID_ASK_SPREAD:
            self.logger.debug(f"Bid-ask spread too wide: C={call_spread:.1f}, P={put_spread:.1f}")
            return False
        
        # Check open interest
        call_oi = call_option.get('oi', 0)
        put_oi = put_option.get('oi', 0)
        
        if call_oi < MIN_OPEN_INTEREST or put_oi < MIN_OPEN_INTEREST:
            self.logger.debug(f"Insufficient OI: C={call_oi}, P={put_oi}")
            return False
        
        return True
    
    def _estimate_margin(
        self,
        spot: float,
        call_strike: float,
        put_strike: float
    ) -> float:
        """Estimate margin requirement for naked strangle."""
        
        # Simplified margin calculation (actual broker may use SPAN)
        # For naked options: ~20% of notional value + premium
        
        call_notional = call_strike * 50  # 1 lot
        put_notional = put_strike * 50
        
        # Margin ~20% of higher strike notional
        margin = max(call_notional, put_notional) * 0.20
        
        # Add buffer for volatility
        margin *= 1.5
        
        return margin
