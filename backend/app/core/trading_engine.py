"""
Trading Engine - Core Trading Loop for Trading System v2.0

This module contains the shared trading logic used by:
- Orchestrator (live/paper trading)
- Backtest runner (historical simulation)

The trading loop is the SAME for all modes. Only the data source differs:
- Live: KiteClient with real-time data
- Paper: KiteClient with real data, simulated orders
- Backtest: HistoricalDataClient with historical data

This ensures backtest results match live trading behavior.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from loguru import logger

from ..config.constants import NIFTY_TOKEN
from ..models.regime import RegimePacket, RegimeType


@dataclass
class IterationResult:
    """Result from a single trading iteration."""
    regime: Optional[RegimePacket] = None
    entries: List[Dict] = field(default_factory=list)
    exits: List[Dict] = field(default_factory=list)
    skipped_reason: Optional[str] = None


class TradingEngine:
    """
    Core trading engine with the shared trading loop.
    
    This class encapsulates the 7-step trading logic:
    1. Sentinel: Detect regime
    2. Treasury: Get account state
    3. Executor: Monitor positions for exits
    4. Check regime safety
    5. Strategist: Generate signals
    6. Treasury: Validate signals
    7. Executor: Execute approved signals
    
    Both Orchestrator and backtest use this same engine.
    """
    
    def __init__(
        self,
        sentinel,
        strategist,
        treasury,
        executor,
        state_manager,
        kite,
        on_regime: Optional[Callable[[RegimePacket], None]] = None,
        on_entry: Optional[Callable[[Dict], None]] = None,
        on_exit: Optional[Callable[[Dict], None]] = None
    ):
        """
        Initialize trading engine with agents.
        
        Args:
            sentinel: Sentinel agent for regime detection
            strategist: Strategist agent for signal generation
            treasury: Treasury agent for risk management
            executor: Executor agent for order execution
            state_manager: State manager for tracking P&L and circuit breakers
            kite: KiteClient or HistoricalDataClient for data/orders
            on_regime: Optional callback when regime is detected
            on_entry: Optional callback when entry is executed
            on_exit: Optional callback when exit is executed
        """
        self.sentinel = sentinel
        self.strategist = strategist
        self.treasury = treasury
        self.executor = executor
        self.state_manager = state_manager
        self.kite = kite
        
        # Callbacks for tracking/logging
        self._on_regime = on_regime
        self._on_entry = on_entry
        self._on_exit = on_exit
    
    def run_iteration(self, instrument_token: int = NIFTY_TOKEN) -> IterationResult:
        """
        Run one iteration of the trading loop.
        
        This is the SINGLE SOURCE OF TRUTH for trading logic.
        Both live trading and backtesting call this method.
        
        Args:
            instrument_token: Token for the primary instrument
            
        Returns:
            IterationResult with regime, entries, exits, and any skip reason
        """
        result = IterationResult()
        
        # =====================================================================
        # STEP 1: Sentinel - Detect regime
        # =====================================================================
        regime = self.sentinel.process(instrument_token)
        result.regime = regime
        
        logger.debug(f"Regime: {regime.regime.value} (safe={regime.is_safe})")
        
        if self._on_regime:
            self._on_regime(regime)
        
        # =====================================================================
        # STEP 2: Treasury - Get account state
        # =====================================================================
        account = self.treasury.get_account_state()
        
        # =====================================================================
        # STEP 3: Executor - Monitor existing positions for exits
        # =====================================================================
        positions = self.executor.get_open_positions()
        if positions:
            tokens = set()
            for pos in positions:
                for leg in pos.legs:
                    tokens.add(leg.instrument_token)
            
            prices = self.kite.get_ltp(list(tokens))
            exit_orders = self.executor.monitor_positions(prices, regime.regime)
            
            for exit_order in exit_orders:
                logger.debug(f"Executing exit: {exit_order.exit_reason}")
                exec_result = self.executor.execute_exit(exit_order)
                
                if exec_result.success:
                    self.state_manager.update_pnl(exit_order.realized_pnl)
                    
                    exit_info = {
                        'reason': exit_order.exit_reason,
                        'pnl': exit_order.realized_pnl,
                        'position_id': getattr(exit_order, 'position_id', None)
                    }
                    result.exits.append(exit_info)
                    
                    if self._on_exit:
                        self._on_exit(exit_info)
                    
                    # Check loss limits after exit
                    limit_hit, reason, flat_days = self.treasury.check_loss_limits(account)
                    if limit_hit:
                        self.treasury.activate_circuit_breaker(reason, flat_days)
        
        # =====================================================================
        # STEP 4: Check if we should generate new signals
        # =====================================================================
        if not regime.is_safe:
            result.skipped_reason = f"Regime not safe: {regime.regime.value}"
            logger.debug(result.skipped_reason)
            return result
        
        if self.state_manager.is_circuit_breaker_active():
            result.skipped_reason = "Circuit breaker active"
            logger.debug(result.skipped_reason)
            return result
        
        # =====================================================================
        # STEP 5: Strategist - Generate signals
        # =====================================================================
        proposals = self.strategist.process(regime)
        
        if not proposals:
            result.skipped_reason = "No proposals generated"
            return result
        
        # =====================================================================
        # STEP 6: Filter out proposals for structures we already have positions for
        # =====================================================================
        filtered_proposals = []
        seen_structures = set()  # Track structures in this batch to avoid duplicates
        for proposal in proposals:
            structure_key = proposal.structure.value
            # Check both in-memory and database positions
            if self.executor.has_open_position_for_structure(structure_key):
                logger.info(f"Skipping {structure_key} - already have open position")
            elif structure_key in seen_structures:
                logger.info(f"Skipping {structure_key} - duplicate in current batch")
            else:
                filtered_proposals.append(proposal)
                seen_structures.add(structure_key)
        
        if not filtered_proposals:
            result.skipped_reason = "All proposals filtered (existing positions)"
            return result
        
        # =====================================================================
        # STEP 7 & 8: Treasury validate + Executor execute
        # =====================================================================
        for proposal in filtered_proposals:
            logger.debug(f"Proposal: {proposal.structure.value} on {proposal.instrument}")
            
            # Treasury: Validate
            approved, signal, reason = self.treasury.process(proposal, account)
            
            if approved and signal:
                logger.debug(f"Approved: {reason}")
                
                # Executor: Place order
                exec_result = self.executor.process(signal)
                
                if exec_result.success:
                    entry_info = {
                        'structure': proposal.structure.value,
                        'instrument': proposal.instrument,
                        'regime': regime.regime.value,
                        'reason': reason
                    }
                    result.entries.append(entry_info)
                    
                    if self._on_entry:
                        self._on_entry(entry_info)
            else:
                logger.debug(f"Rejected: {reason}")
        
        return result
