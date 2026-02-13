"""
Unified Strategy Selector - v2 Rulebook Implementation

Single source of truth for strategy selection logic used by:
- Strategist (live trading signal generation)
- StrategyBacktester (backtesting)

Ensures both live and backtesting use identical entry rules per v2_rulebook.md
"""

from typing import List, Tuple, Optional
from loguru import logger

from ...models.regime import RegimePacket, RegimeType
from ...models.trade import StructureType
from ...config.thresholds import (
    MIN_DTE_EVENT_OVERRIDE, HIGH_IV_BOOST_THRESHOLD, HIGH_IV_VIX_DELTA,
    HIGH_IV_TARGET_MIN, HIGH_IV_TARGET_MAX, HIGH_IV_ADJUST_THRESHOLD,
    SKEW_THRESHOLD, SHORT_VOL_TARGET_MIN, SHORT_VOL_TARGET_MAX,
    DIRECTIONAL_TARGET_MIN, DIRECTIONAL_TARGET_MAX
)


class StrategySelector:
    """
    Unified strategy selection logic per v2 rulebook.
    
    Maps regime → suitable structures with entry conditions.
    """
    
    @staticmethod
    def get_suitable_structures(
        regime: RegimePacket,
        dte: Optional[int] = None
    ) -> List[Tuple[StructureType, dict]]:
        """
        Return list of suitable structures for current regime with entry conditions.
        
        Args:
            regime: RegimePacket from Sentinel
            dte: Days to expiry (for v2.5 Ref J event override)
            
        Returns:
            List of (StructureType, entry_conditions_dict) tuples
            
        Per v2.5 Rulebook:
        - RANGE_BOUND: Short-vol (IC, Butterfly, Jade Lizard, Strangle)
        - CAUTION: Hedged structures only (Jade Lizard)
        - MEAN_REVERSION: Directional (Risk Reversal, BWB)
        - TREND: Directional hedged (Risk Reversal, Jade Lizard)
        - CHAOS: No entries
        
        v2.5 Updates:
        - Ref J: Allow entry on event if DTE >= 10
        - Ref K: High-IV boost for short-vol targets
        - Ref M: Skew check favors risk-reversals
        """
        structures = []
        
        # v2.5: Check veto_shortvol flag
        if regime.veto_shortvol:
            logger.info("v2.5: Short-vol vetoed by sustained trigger counter")
            # Only allow directional structures
            return StrategySelector._get_directional_only_structures(regime)
        
        if regime.regime == RegimeType.CHAOS:
            return []  # No trades in chaos
        
        # v2.5 Ref J: Event override if DTE >= 10
        event_override = False
        if regime.event_flag and dte is not None and dte >= MIN_DTE_EVENT_OVERRIDE:
            event_override = True
            logger.info(f"v2.5 Ref J: Event override active (DTE={dte} >= {MIN_DTE_EVENT_OVERRIDE})")
        
        if regime.regime == RegimeType.CAUTION:
            # CAUTION: Only hedged structures
            # v2.5: Check if event override allows entry
            if regime.event_flag and not event_override:
                return []  # No entry during event blackout without override
            
            structures.append((
                StructureType.JADE_LIZARD,
                {
                    'regime': RegimeType.CAUTION,
                    'iv_percentile_min': 35,
                    'confluence': 2,
                    'event_override': event_override,
                    'note': 'Hedged structure only in CAUTION regime'
                }
            ))
            return structures
        
        if regime.regime == RegimeType.RANGE_BOUND:
            # RANGE_BOUND: Primary short-vol structures
            # v2.5: Check if event override allows entry
            if regime.event_flag and not event_override:
                return []  # No entry during event blackout without override
            
            # v2.5 Ref K: Calculate target boost for high-IV
            target_boost = StrategySelector._get_high_iv_boost(regime)
            
            # 1. Iron Condor (premium short-vol)
            structures.append((
                StructureType.IRON_CONDOR,
                {
                    'regime': RegimeType.RANGE_BOUND,
                    'iv_percentile_min': 40,
                    'day_range_pct_max': 0.012,
                    'gap_pct_max': 0.015,
                    'confluence': 2,
                    'target_boost': target_boost,
                    'event_override': event_override,
                    'note': 'IC: RANGE_BOUND + IV >40% + low range/gap'
                }
            ))
            
            # 2. Butterfly (lower risk credit)
            structures.append((
                StructureType.BUTTERFLY,
                {
                    'regime': RegimeType.RANGE_BOUND,
                    'iv_percentile_min': 30,
                    'regime_confidence_min': 0.75,
                    'confluence': 2,
                    'note': 'Butterfly: RANGE_BOUND + high confidence'
                }
            ))
            
            # 3. Jade Lizard (hedged credit)
            structures.append((
                StructureType.JADE_LIZARD,
                {
                    'regime': RegimeType.RANGE_BOUND,
                    'iv_percentile_min': 35,
                    'confluence': 2,
                    'note': 'JL: RANGE_BOUND + IV >35%'
                }
            ))
            
            # 4. Naked Strangle (IV <15th percentile, max 2 days) - high gamma risk
            structures.append((
                StructureType.NAKED_STRANGLE,
                {
                    'regime': RegimeType.RANGE_BOUND,
                    'iv_percentile_max': 15,
                    'dte_max': 2,
                    'confluence': 2,
                    'note': 'Strangle: RANGE_BOUND + IV <15th%ile + ultra-short DTE'
                }
            ))
            
            return structures
        
        if regime.regime == RegimeType.MEAN_REVERSION:
            # MEAN_REVERSION: Directional structures with mean-revert signal
            # v2 rulebook Section 4: Mean-reversion + price ±1.5-2x ATR + RSI extreme
            
            # 1. Broken Wing Butterfly (debit, lower cost)
            structures.append((
                StructureType.BROKEN_WING_BUTTERFLY,
                {
                    'regime': RegimeType.MEAN_REVERSION,
                    'rsi_extreme': (30, 70),  # RSI <30 or >70
                    'confluence': 2,
                    'note': 'BWB: MEAN_REVERSION + RSI extreme'
                }
            ))
            
            # 2. Risk Reversal (synthetic long/short)
            structures.append((
                StructureType.RISK_REVERSAL,
                {
                    'regime': RegimeType.MEAN_REVERSION,
                    'rsi_extreme': (25, 75),  # More extreme: RSI <25 or >75
                    'confluence': 2,
                    'note': 'RR: MEAN_REVERSION + RSI >75 or <25'
                }
            ))
            
            # 3. Naked Strangle alternative (if IV low)
            structures.append((
                StructureType.NAKED_STRANGLE,
                {
                    'regime': RegimeType.MEAN_REVERSION,
                    'iv_percentile_max': 20,
                    'rsi_extreme': (30, 70),
                    'confluence': 2,
                    'note': 'Strangle: MEAN_REVERSION + RSI extreme + IV <20%'
                }
            ))
            
            return structures
        
        if regime.regime == RegimeType.TREND:
            # TREND: Directional hedged structures
            # v2 rulebook Section 4: ADX >27 for trend confirmation
            
            # 1. Risk Reversal (directional)
            structures.append((
                StructureType.RISK_REVERSAL,
                {
                    'regime': RegimeType.TREND,
                    'adx_min': 25,
                    'confluence': 2,
                    'note': 'RR: TREND + ADX >25'
                }
            ))
            
            # 2. Jade Lizard (hedged directional)
            structures.append((
                StructureType.JADE_LIZARD,
                {
                    'regime': RegimeType.TREND,
                    'iv_percentile_min': 30,
                    'confluence': 2,
                    'note': 'JL: TREND + IV >30% + hedged'
                }
            ))
            
            return structures
        
        return structures
    
    @staticmethod
    def _get_high_iv_boost(regime: RegimePacket) -> dict:
        """
        v2.5 Ref K: Calculate target boost for high-IV environment.
        
        If IV %ile > 50 + VIX elevated, boost short-vol targets to 1.8-2.2%
        and tighten adjustment threshold to -0.3%.
        
        Returns:
            Dict with boost parameters or empty dict if no boost
        """
        if regime.metrics.iv_percentile > HIGH_IV_BOOST_THRESHOLD:
            # Check if VIX is elevated (use india_vix if available)
            vix_elevated = False
            if regime.metrics.india_vix is not None:
                # Assume avg VIX around 13-15, elevated if > avg + 5
                vix_elevated = regime.metrics.india_vix > 18  # ~13 + 5
            
            if vix_elevated or regime.metrics.iv_percentile > 60:
                return {
                    'target_min': HIGH_IV_TARGET_MIN,
                    'target_max': HIGH_IV_TARGET_MAX,
                    'adjust_threshold': HIGH_IV_ADJUST_THRESHOLD,
                    'boosted': True
                }
        
        return {
            'target_min': SHORT_VOL_TARGET_MIN,
            'target_max': SHORT_VOL_TARGET_MAX,
            'adjust_threshold': -0.005,
            'boosted': False
        }
    
    @staticmethod
    def _get_directional_only_structures(regime: RegimePacket) -> List[Tuple[StructureType, dict]]:
        """
        v2.5: Return only directional structures when short-vol is vetoed.
        
        Used when sustained chaos triggers veto short-vol trades.
        """
        structures = []
        
        # Only allow Risk Reversal in veto mode
        if regime.metrics.rsi < 35 or regime.metrics.rsi > 65:
            structures.append((
                StructureType.RISK_REVERSAL,
                {
                    'regime': regime.regime,
                    'rsi_extreme': (35, 65),
                    'confluence': 2,
                    'veto_mode': True,
                    'note': 'v2.5: Directional only (short-vol vetoed)'
                }
            ))
        
        return structures
    
    @staticmethod
    def check_skew_favor_risk_reversal(regime: RegimePacket, option_chain=None) -> bool:
        """
        v2.5 Ref M: Check if call/put IV skew favors risk-reversals.
        
        For NIFTY, if call IV > put IV + 5%, favor risk-reversals.
        
        Args:
            regime: RegimePacket
            option_chain: Optional option chain with IV data
            
        Returns:
            True if skew favors risk-reversals
        """
        if option_chain is None or not hasattr(option_chain, 'empty') or option_chain.empty:
            return False
        
        try:
            # Get ATM options
            spot = regime.spot_price
            atm_strike = round(spot / 50) * 50  # Round to nearest 50
            
            calls = option_chain[
                (option_chain['strike'] == atm_strike) & 
                (option_chain['instrument_type'] == 'CE')
            ]
            puts = option_chain[
                (option_chain['strike'] == atm_strike) & 
                (option_chain['instrument_type'] == 'PE')
            ]
            
            if calls.empty or puts.empty:
                return False
            
            call_iv = calls['iv'].iloc[0] if 'iv' in calls.columns else 0
            put_iv = puts['iv'].iloc[0] if 'iv' in puts.columns else 0
            
            # Ref M: Call IV > Put IV + 5% favors risk-reversals
            skew = call_iv - put_iv
            if skew > SKEW_THRESHOLD:
                logger.info(f"v2.5 Ref M: Skew favors RR (call IV {call_iv:.1%} > put IV {put_iv:.1%} + 5%)")
                return True
                
        except Exception as e:
            logger.debug(f"Skew check failed: {e}")
        
        return False
    
    @staticmethod
    def should_enter_structure(
        structure: StructureType,
        regime: RegimePacket,
        conditions: dict,
        option_chain: object = None
    ) -> Tuple[bool, str]:
        """
        Evaluate if structure should be entered given regime + conditions.
        
        Args:
            structure: StructureType to evaluate
            regime: Current RegimePacket
            conditions: Entry conditions dict returned by get_suitable_structures
            option_chain: Optional option chain DataFrame for liquidity validation
            
        Returns:
            (should_enter: bool, reason: str)
        """
        reason = []
        
        # Check regime match
        if regime.regime != conditions.get('regime'):
            return False, f"Regime mismatch: {regime.regime} != {conditions['regime']}"
        
        # Check IV percentile constraints
        iv_min = conditions.get('iv_percentile_min')
        if iv_min and regime.metrics.iv_percentile < iv_min:
            return False, f"IV too low: {regime.metrics.iv_percentile:.1f}% < {iv_min}%"
        
        iv_max = conditions.get('iv_percentile_max')
        if iv_max and regime.metrics.iv_percentile > iv_max:
            return False, f"IV too high: {regime.metrics.iv_percentile:.1f}% > {iv_max}%"
        
        # Check RSI constraints
        rsi_extreme = conditions.get('rsi_extreme')
        if rsi_extreme:
            rsi_min, rsi_max = rsi_extreme
            is_extreme = regime.metrics.rsi < rsi_min or regime.metrics.rsi > rsi_max
            if not is_extreme:
                return False, f"RSI not extreme: {regime.metrics.rsi:.1f} not <{rsi_min} or >{rsi_max}"
            reason.append(f"RSI extreme: {regime.metrics.rsi:.1f}")
        
        # Check ADX constraints
        adx_min = conditions.get('adx_min')
        if adx_min and regime.metrics.adx < adx_min:
            return False, f"ADX too low: {regime.metrics.adx:.1f} < {adx_min}"
        
        # Check confidence
        conf_min = conditions.get('regime_confidence_min')
        if conf_min and regime.regime_confidence < conf_min:
            return False, f"Regime confidence low: {regime.regime_confidence:.2f} < {conf_min}"
        
        # Check day range
        dr_max = conditions.get('day_range_pct_max')
        if dr_max and regime.day_range_pct > dr_max:
            return False, f"Day range too high: {regime.day_range_pct:.3f} > {dr_max}"
        
        # Check gap
        gap_max = conditions.get('gap_pct_max')
        if gap_max and abs(regime.gap_pct) > gap_max:
            return False, f"Gap too high: {abs(regime.gap_pct):.3f} > {gap_max}"
        
        # Note: DTE checks are handled by backtester/strategist at expiry selection time
        # (DTE is not part of RegimePacket, managed separately)
        
        # Confluence check (minimum number of conditions met)
        confluence_required = conditions.get('confluence', 1)
        confluence_met = 1  # Regime match is always 1
        if 'iv_percentile_min' in conditions or 'iv_percentile_max' in conditions:
            confluence_met += 1
        if 'rsi_extreme' in conditions:
            confluence_met += 1
        if 'adx_min' in conditions:
            confluence_met += 1
        if 'regime_confidence_min' in conditions:
            confluence_met += 1
        
        if confluence_met < confluence_required:
            return False, f"Confluence not met: {confluence_met} < {confluence_required}"
        
        # Optional: Liquidity check on option chain if provided
        if option_chain is not None and hasattr(option_chain, 'empty') and not option_chain.empty:
            from ...config.thresholds import MIN_OPEN_INTEREST
            liquid_strikes = option_chain[option_chain.get('oi', 0) >= MIN_OPEN_INTEREST]
            if len(liquid_strikes) < 5:  # Need at least 5 liquid strikes for spreads
                return False, f"Insufficient liquid strikes: {len(liquid_strikes)} < 5"
        
        reason.append(conditions.get('note', 'Entry conditions met'))
        return True, " | ".join(reason)
    
    @staticmethod
    def filter_liquid_strikes(option_chain, min_oi: int = None, max_spread: float = None) -> object:
        """
        Filter option chain to only liquid strikes based on OI and bid-ask spread.
        
        Args:
            option_chain: DataFrame with columns ['strike', 'oi', 'bid', 'ask', ...]
            min_oi: Minimum open interest threshold (uses MIN_OPEN_INTEREST from thresholds if None)
            max_spread: Maximum bid-ask spread in INR (uses MIN_BID_ASK_SPREAD if None)
            
        Returns:
            Filtered DataFrame with only liquid strikes
        """
        if option_chain is None or (hasattr(option_chain, 'empty') and option_chain.empty):
            return option_chain
        
        from ...config.thresholds import MIN_OPEN_INTEREST, MIN_BID_ASK_SPREAD
        from loguru import logger
        
        min_oi = min_oi or MIN_OPEN_INTEREST
        max_spread = max_spread or MIN_BID_ASK_SPREAD
        
        # Copy to avoid modifying original
        filtered = option_chain.copy()
        initial_strikes = len(filtered['strike'].unique()) if 'strike' in filtered.columns else 0
        
        # Filter by open interest - skip if all OI values are 0 (data unavailable)
        if 'oi' in filtered.columns:
            oi_sum = filtered['oi'].sum()
            if oi_sum > 0:  # Only filter if we have OI data
                filtered = filtered[filtered['oi'] >= min_oi]
                logger.debug(f"OI filter: {initial_strikes} -> {len(filtered['strike'].unique())} strikes (oi_sum={oi_sum})")
            else:
                logger.debug(f"Skipping OI filter (oi_sum=0), keeping {initial_strikes} strikes")
        
        # Filter by bid-ask spread - skip if all values are 0 (data unavailable)
        if 'bid' in filtered.columns and 'ask' in filtered.columns:
            bid_sum = filtered['bid'].sum()
            ask_sum = filtered['ask'].sum()
            if bid_sum > 0 or ask_sum > 0:
                filtered['spread'] = filtered['ask'] - filtered['bid']
                before = len(filtered['strike'].unique())
                filtered = filtered[filtered['spread'] <= max_spread]
                logger.debug(f"Spread filter: {before} -> {len(filtered['strike'].unique())} strikes (max_spread={max_spread})")
            else:
                logger.debug(f"Skipping spread filter (bid_sum={bid_sum}, ask_sum={ask_sum})")
        
        return filtered
