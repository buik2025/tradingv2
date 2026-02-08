"""Treasury Agent - Risk Management for Trading System v2.0"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple
from loguru import logger

from .base_agent import BaseAgent
from ..core.kite_client import KiteClient
from ..core.state_manager import StateManager
from ..config.settings import Settings
from ..config.thresholds import (
    MAX_MARGIN_PCT, MAX_LOSS_PER_TRADE, MAX_DAILY_LOSS, MAX_WEEKLY_LOSS,
    MAX_POSITIONS, MAX_DELTA, MAX_GAMMA, MAX_VEGA,
    DRAWDOWN_LEVEL_1, DRAWDOWN_LEVEL_2, DRAWDOWN_LEVEL_3,
    DRAWDOWN_MULTIPLIER_1, DRAWDOWN_MULTIPLIER_2, DRAWDOWN_MULTIPLIER_3,
    FLAT_DAYS_DAILY_LOSS, FLAT_DAYS_WEEKLY_LOSS
)
from ..models.trade import TradeProposal, TradeSignal
from ..models.position import AccountState, Position


class Treasury(BaseAgent):
    """
    Risk management agent.
    
    Responsibilities:
    - Validate trade proposals against risk limits
    - Check circuit breakers
    - Enforce position limits
    - Monitor margin utilization
    - Apply drawdown multipliers
    - Approve or reject trades
    """
    
    def __init__(
        self,
        kite: KiteClient,
        config: Settings,
        state_manager: Optional[StateManager] = None
    ):
        super().__init__(kite, config, name="Treasury")
        self.state_manager = state_manager or StateManager()
    
    def process(
        self,
        proposal: TradeProposal,
        account: AccountState
    ) -> Tuple[bool, Optional[TradeSignal], str]:
        """
        Validate trade proposal and approve/reject.
        
        Args:
            proposal: Trade proposal from Strategist
            account: Current account state
            
        Returns:
            Tuple of (approved, TradeSignal if approved, reason)
        """
        self.logger.info(f"Evaluating proposal: {proposal.structure.value} on {proposal.instrument}")
        
        # 1. Check circuit breakers
        if not self._check_circuit_breakers(account):
            return False, None, "Circuit breaker active"
        
        # 2. Check position count
        if not self._check_position_count(account):
            return False, None, f"Max positions ({MAX_POSITIONS}) reached"
        
        # 3. Check margin utilization
        margin_ok, margin_reason = self._check_margin(proposal, account)
        if not margin_ok:
            return False, None, margin_reason
        
        # 4. Check per-trade risk
        risk_ok, risk_reason = self._check_trade_risk(proposal, account)
        if not risk_ok:
            return False, None, risk_reason
        
        # 5. Check Greeks limits
        greeks_ok, greeks_reason = self._check_greeks(proposal, account)
        if not greeks_ok:
            return False, None, greeks_reason
        
        # 6. Get drawdown multiplier
        dd_multiplier = self._get_drawdown_multiplier(account)
        if dd_multiplier == 0:
            return False, None, "Trading halted due to drawdown"
        
        # 7. Adjust size based on drawdown
        adjusted_margin = proposal.required_margin * dd_multiplier
        adjusted_size_pct = proposal.position_size_pct * dd_multiplier
        
        # 8. Create approved signal
        signal = TradeSignal(
            proposal_id=proposal.id,
            structure=proposal.structure,
            instrument=proposal.instrument,
            legs=proposal.legs,
            approved_margin=adjusted_margin,
            approved_size_pct=adjusted_size_pct,
            drawdown_multiplier=dd_multiplier,
            target_pnl=proposal.target_pnl * dd_multiplier,
            stop_loss=proposal.stop_loss * dd_multiplier,
            approval_reason=f"Approved with {dd_multiplier:.0%} size"
        )
        
        self.logger.info(
            f"APPROVED: {proposal.structure.value}, "
            f"margin={adjusted_margin:.0f}, multiplier={dd_multiplier:.0%}"
        )
        
        return True, signal, "Approved"
    
    def _check_circuit_breakers(self, account: AccountState) -> bool:
        """Check if any circuit breakers are active."""
        if account.circuit_breaker_active:
            self.logger.warning(f"Circuit breaker active: {account.circuit_breaker_reason}")
            return False
        
        if account.flat_days_remaining > 0:
            self.logger.warning(f"Flat days remaining: {account.flat_days_remaining}")
            return False
        
        return True
    
    def _check_position_count(self, account: AccountState) -> bool:
        """Check if position count is within limit."""
        return account.position_count < MAX_POSITIONS
    
    def _check_margin(
        self,
        proposal: TradeProposal,
        account: AccountState
    ) -> Tuple[bool, str]:
        """Check margin utilization."""
        new_margin = account.used_margin + proposal.required_margin
        new_utilization = new_margin / account.equity if account.equity > 0 else 1.0
        
        if new_utilization > MAX_MARGIN_PCT:
            return False, f"Would exceed {MAX_MARGIN_PCT:.0%} margin ({new_utilization:.1%})"
        
        return True, ""
    
    def _check_trade_risk(
        self,
        proposal: TradeProposal,
        account: AccountState
    ) -> Tuple[bool, str]:
        """Check per-trade risk limit."""
        max_loss_allowed = account.equity * MAX_LOSS_PER_TRADE
        
        if proposal.max_loss > max_loss_allowed:
            return False, f"Max loss {proposal.max_loss:.0f} exceeds {MAX_LOSS_PER_TRADE:.0%} limit ({max_loss_allowed:.0f})"
        
        return True, ""
    
    def _check_greeks(
        self,
        proposal: TradeProposal,
        account: AccountState
    ) -> Tuple[bool, str]:
        """Check portfolio Greeks limits."""
        # Calculate new portfolio Greeks
        new_delta = account.portfolio_greeks.get("delta", 0) + proposal.greeks.get("delta", 0)
        new_gamma = account.portfolio_greeks.get("gamma", 0) + proposal.greeks.get("gamma", 0)
        new_vega = account.portfolio_greeks.get("vega", 0) + proposal.greeks.get("vega", 0)
        
        if abs(new_delta) > MAX_DELTA:
            return False, f"Would exceed delta limit: {new_delta:.1f} > {MAX_DELTA}"
        
        if abs(new_gamma) > MAX_GAMMA:
            return False, f"Would exceed gamma limit: {new_gamma:.2f} > {MAX_GAMMA}"
        
        if abs(new_vega) > MAX_VEGA:
            return False, f"Would exceed vega limit: {new_vega:.0f} > {MAX_VEGA}"
        
        return True, ""
    
    def _get_drawdown_multiplier(self, account: AccountState) -> float:
        """Get position size multiplier based on drawdown."""
        dd_pct = account.drawdown_pct
        
        if dd_pct >= DRAWDOWN_LEVEL_3:
            self.logger.warning(f"Drawdown {dd_pct:.1%} >= {DRAWDOWN_LEVEL_3:.0%}: STOP TRADING")
            return DRAWDOWN_MULTIPLIER_3
        elif dd_pct >= DRAWDOWN_LEVEL_2:
            self.logger.warning(f"Drawdown {dd_pct:.1%}: reducing to {DRAWDOWN_MULTIPLIER_2:.0%}")
            return DRAWDOWN_MULTIPLIER_2
        elif dd_pct >= DRAWDOWN_LEVEL_1:
            self.logger.info(f"Drawdown {dd_pct:.1%}: reducing to {DRAWDOWN_MULTIPLIER_1:.0%}")
            return DRAWDOWN_MULTIPLIER_1
        
        return 1.0
    
    def check_loss_limits(self, account: AccountState) -> Tuple[bool, Optional[str], int]:
        """
        Check if loss limits have been breached.
        
        Returns:
            Tuple of (limit_breached, reason, flat_days)
        """
        # Daily loss check
        daily_loss_pct = abs(account.daily_pnl) / account.equity if account.equity > 0 else 0
        if account.daily_pnl < 0 and daily_loss_pct >= MAX_DAILY_LOSS:
            return True, f"Daily loss limit hit: {daily_loss_pct:.1%}", FLAT_DAYS_DAILY_LOSS
        
        # Weekly loss check
        weekly_loss_pct = abs(account.weekly_pnl) / account.equity if account.equity > 0 else 0
        if account.weekly_pnl < 0 and weekly_loss_pct >= MAX_WEEKLY_LOSS:
            return True, f"Weekly loss limit hit: {weekly_loss_pct:.1%}", FLAT_DAYS_WEEKLY_LOSS
        
        return False, None, 0
    
    def activate_circuit_breaker(self, reason: str, flat_days: int) -> None:
        """Activate circuit breaker."""
        self.state_manager.activate_circuit_breaker(reason, flat_days)
        self.logger.warning(f"CIRCUIT BREAKER ACTIVATED: {reason}, flat days: {flat_days}")
    
    def monitor_positions(
        self,
        positions: List[Position],
        account: AccountState
    ) -> List[str]:
        """
        Monitor open positions for risk events.
        
        Returns:
            List of position IDs that should be closed
        """
        positions_to_close = []
        
        for pos in positions:
            # Check profit target
            if pos.should_exit_profit():
                self.logger.info(f"Position {pos.id} hit profit target")
                positions_to_close.append(pos.id)
                continue
            
            # Check stop loss
            if pos.should_exit_stop():
                self.logger.warning(f"Position {pos.id} hit stop loss")
                positions_to_close.append(pos.id)
                continue
            
            # Check time-based exit
            if pos.should_exit_time(pos.days_to_expiry):
                self.logger.info(f"Position {pos.id} time-based exit (DTE={pos.days_to_expiry})")
                positions_to_close.append(pos.id)
                continue
        
        # Check portfolio-level loss limits
        limit_breached, reason, flat_days = self.check_loss_limits(account)
        if limit_breached:
            self.activate_circuit_breaker(reason, flat_days)
            # Close all positions on circuit breaker
            positions_to_close = [p.id for p in positions]
        
        return positions_to_close
    
    def get_account_state(self) -> AccountState:
        """Build current account state from broker data."""
        margins = self.kite.get_margins()
        positions_data = self.kite.get_positions()
        
        # Extract equity info
        equity_data = margins.get("equity", {})
        available = equity_data.get("available", {})
        utilised = equity_data.get("utilised", {})
        
        equity = available.get("live_balance", 0)
        available_margin = available.get("cash", 0)
        used_margin = utilised.get("debits", 0)
        
        # Get state from persistence
        high_watermark = self.state_manager.get("high_watermark", equity)
        daily_pnl = self.state_manager.get("daily_pnl", 0)
        weekly_pnl = self.state_manager.get("weekly_pnl", 0)
        flat_days = self.state_manager.get("flat_days_remaining", 0)
        cb_active = self.state_manager.get("circuit_breaker_active", False)
        cb_reason = self.state_manager.get("circuit_breaker_reason", None)
        
        # Build account state
        account = AccountState(
            equity=equity,
            available_margin=available_margin,
            used_margin=used_margin,
            margin_utilization=used_margin / equity if equity > 0 else 0,
            high_watermark=high_watermark,
            daily_pnl=daily_pnl,
            weekly_pnl=weekly_pnl,
            flat_days_remaining=flat_days,
            circuit_breaker_active=cb_active,
            circuit_breaker_reason=cb_reason
        )
        
        account.update_drawdown()
        
        return account
