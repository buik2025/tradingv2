"""
Unified Strategy Selector - v2 Rulebook Implementation

Single source of truth for strategy selection logic used by:
- Strategist (live trading signal generation)
- StrategyBacktester (backtesting)

Ensures both live and backtesting use identical entry rules per v2_rulebook.md
"""

from typing import List, Tuple
from loguru import logger

from ..models.regime import RegimePacket, RegimeType
from ..models.trade import StructureType


class StrategySelector:
    """
    Unified strategy selection logic per v2 rulebook.
    
    Maps regime → suitable structures with entry conditions.
    """
    
    @staticmethod
    def get_suitable_structures(regime: RegimePacket) -> List[Tuple[StructureType, dict]]:
        """
        Return list of suitable structures for current regime with entry conditions.
        
        Args:
            regime: RegimePacket from Sentinel
            
        Returns:
            List of (StructureType, entry_conditions_dict) tuples
            
        Per v2 Rulebook Section 4:
        - RANGE_BOUND: Short-vol (IC, Butterfly, Jade Lizard, Strangle)
        - CAUTION: Hedged structures only (Jade Lizard)
        - MEAN_REVERSION: Directional (Risk Reversal, BWB)
        - TREND: Directional hedged (Risk Reversal, Jade Lizard)
        - CHAOS: No entries
        """
        structures = []
        
        if regime.regime == RegimeType.CHAOS:
            return []  # No trades in chaos
        
        if regime.regime == RegimeType.CAUTION:
            # CAUTION: Only hedged structures
            structures.append((
                StructureType.JADE_LIZARD,
                {
                    'regime': RegimeType.CAUTION,
                    'iv_percentile_min': 35,
                    'confluence': 2,
                    'note': 'Hedged structure only in CAUTION regime'
                }
            ))
            return structures
        
        if regime.regime == RegimeType.RANGE_BOUND:
            # RANGE_BOUND: Primary short-vol structures
            # v2 rulebook Section 4: Range-bound + skew <20% + OI no surge
            
            # 1. Iron Condor (premium short-vol)
            structures.append((
                StructureType.IRON_CONDOR,
                {
                    'regime': RegimeType.RANGE_BOUND,
                    'iv_percentile_min': 40,
                    'day_range_pct_max': 0.012,
                    'gap_pct_max': 0.015,
                    'confluence': 2,
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
            from ..config.thresholds import MIN_OPEN_INTEREST
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
        
        from ..config.thresholds import MIN_OPEN_INTEREST, MIN_BID_ASK_SPREAD
        
        min_oi = min_oi or MIN_OPEN_INTEREST
        max_spread = max_spread or MIN_BID_ASK_SPREAD
        
        # Copy to avoid modifying original
        filtered = option_chain.copy()
        
        # Filter by open interest
        if 'oi' in filtered.columns:
            filtered = filtered[filtered['oi'] >= min_oi]
        
        # Filter by bid-ask spread
        if 'bid' in filtered.columns and 'ask' in filtered.columns:
            filtered['spread'] = filtered['ask'] - filtered['bid']
            filtered = filtered[filtered['spread'] <= max_spread]
        
        return filtered
