"""
Circuit Breaker and Risk Management Module - Section 6 of v2_rulebook.

Implements loss limits and drawdown tracking:
- Daily loss: -1.5% equity → flatten/rest day
- Weekly loss: -4% equity → flat 3 days
- Monthly loss: -10% equity → flat 1 week + review
- Consecutive losses: 3 losers → flat 1 day + 50% size reduction
- ML probability: loss >0.6 → preemptive flatten
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, List, Tuple
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


class CircuitBreakerState(str, Enum):
    """Circuit breaker states."""
    ACTIVE = "active"
    DAILY_HALT = "daily_halt"
    WEEKLY_HALT = "weekly_halt"
    MONTHLY_HALT = "monthly_halt"
    PREEMPTIVE_HALT = "preemptive_halt"


class CircuitBreakerMetrics(BaseModel):
    """Daily/Weekly/Monthly loss tracking."""
    
    # Daily metrics
    daily_loss_pct: float = Field(0.0, description="Daily P&L loss as % of equity")
    daily_trades: int = Field(0, description="Number of trades executed today")
    daily_wins: int = Field(0, description="Number of winning trades today")
    daily_losses: int = Field(0, description="Number of losing trades today")
    
    # Consecutive loss tracking
    consecutive_losses: int = Field(0, description="Count of consecutive losing trades")
    last_trade_date: Optional[datetime] = Field(None, description="Date of last trade")
    last_trade_pnl: float = Field(0.0, description="P&L of last trade")
    
    # Weekly metrics
    weekly_loss_pct: float = Field(0.0, description="Weekly P&L loss as % of equity")
    weekly_start_date: datetime = Field(default_factory=datetime.now)
    week_trades: int = Field(0, description="Trades this week")
    
    # Monthly metrics
    monthly_loss_pct: float = Field(0.0, description="Monthly P&L loss as % of equity")
    monthly_start_date: datetime = Field(default_factory=datetime.now)
    month_trades: int = Field(0, description="Trades this month")
    
    # Halt tracking
    halt_state: CircuitBreakerState = Field(
        CircuitBreakerState.ACTIVE,
        description="Current halt state"
    )
    halt_until: Optional[datetime] = Field(None, description="When halt expires")
    halt_reason: str = Field("", description="Reason for halt")
    
    # Size reduction
    size_reduction_active: bool = Field(False, description="50% size reduction active")
    size_reduction_until: Optional[datetime] = Field(None, description="Until date")


class CircuitBreaker:
    """Monitors and enforces loss limits."""
    
    # Thresholds from v2_rulebook Section 6
    DAILY_LOSS_LIMIT = 0.015  # -1.5%
    WEEKLY_LOSS_LIMIT = 0.04   # -4%
    MONTHLY_LOSS_LIMIT = 0.10  # -10%
    CONSECUTIVE_LOSS_LIMIT = 3  # 3 losers
    ML_LOSS_PROB_THRESHOLD = 0.6  # Preemptive halt
    
    DAILY_HALT_DAYS = 1
    WEEKLY_HALT_DAYS = 3
    MONTHLY_HALT_DAYS = 7
    CONSECUTIVE_HALT_DAYS = 1
    
    def __init__(self, initial_equity: float = 100000.0):
        """Initialize circuit breaker.
        
        Args:
            initial_equity: Starting account equity
        """
        self.initial_equity = initial_equity
        self.current_equity = initial_equity
        self.metrics = CircuitBreakerMetrics()
    
    def update_equity(self, new_equity: float) -> None:
        """Update current equity and recalculate loss percentages.
        
        Args:
            new_equity: Current account equity
        """
        self.current_equity = new_equity
        self._recalculate_losses()
    
    def _recalculate_losses(self) -> None:
        """Recalculate all loss metrics."""
        equity_loss = self.current_equity - self.initial_equity  # Negative if loss
        equity_loss_pct = equity_loss / self.initial_equity
        
        # Update loss percentages (negative = loss)
        self.metrics.daily_loss_pct = equity_loss_pct
        self.metrics.weekly_loss_pct = equity_loss_pct
        self.metrics.monthly_loss_pct = equity_loss_pct
        
        # Check thresholds
        self._check_daily_limit()
        self._check_weekly_limit()
        self._check_monthly_limit()
    
    def record_trade(self, pnl: float, is_win: bool, ml_loss_prob: float = 0.0) -> CircuitBreakerState:
        """Record a trade and check circuit breaker conditions.
        
        Args:
            pnl: Trade P&L in rupees
            is_win: True if profitable trade
            ml_loss_prob: ML probability of loss (0.0-1.0)
            
        Returns:
            Current circuit breaker state
        """
        now = datetime.now()
        
        # Update trade metrics
        self.metrics.daily_trades += 1
        self.metrics.week_trades += 1
        self.metrics.month_trades += 1
        
        if is_win:
            self.metrics.daily_wins += 1
            self.metrics.consecutive_losses = 0
        else:
            self.metrics.daily_losses += 1
            self.metrics.consecutive_losses += 1
        
        # Update last trade info
        self.metrics.last_trade_date = now
        self.metrics.last_trade_pnl = pnl
        
        # Check consecutive losses
        if self.metrics.consecutive_losses >= self.CONSECUTIVE_LOSS_LIMIT:
            self._trigger_halt(
                CircuitBreakerState.DAILY_HALT,
                "3 consecutive losses - 1 day halt + 50% size reduction",
                self.CONSECUTIVE_HALT_DAYS
            )
            self.metrics.size_reduction_active = True
            self.metrics.size_reduction_until = now + timedelta(days=1)
        
        # Check ML preemptive loss probability
        if ml_loss_prob > self.ML_LOSS_PROB_THRESHOLD:
            self._trigger_halt(
                CircuitBreakerState.PREEMPTIVE_HALT,
                f"ML loss probability {ml_loss_prob:.1%} > {self.ML_LOSS_PROB_THRESHOLD:.1%}",
                self.CONSECUTIVE_HALT_DAYS
            )
        
        return self.metrics.halt_state
    
    def _check_daily_limit(self) -> None:
        """Check if daily loss limit exceeded."""
        if (self.metrics.daily_loss_pct <= -self.DAILY_LOSS_LIMIT and
                self.metrics.halt_state == CircuitBreakerState.ACTIVE):
            self._trigger_halt(
                CircuitBreakerState.DAILY_HALT,
                f"Daily loss {self.metrics.daily_loss_pct:.1%} exceeded -{self.DAILY_LOSS_LIMIT:.1%}",
                self.DAILY_HALT_DAYS
            )
    
    def _check_weekly_limit(self) -> None:
        """Check if weekly loss limit exceeded."""
        if (self.metrics.weekly_loss_pct <= -self.WEEKLY_LOSS_LIMIT and
                self.metrics.halt_state == CircuitBreakerState.ACTIVE):
            self._trigger_halt(
                CircuitBreakerState.WEEKLY_HALT,
                f"Weekly loss {self.metrics.weekly_loss_pct:.1%} exceeded -{self.WEEKLY_LOSS_LIMIT:.1%}",
                self.WEEKLY_HALT_DAYS
            )
    
    def _check_monthly_limit(self) -> None:
        """Check if monthly loss limit exceeded."""
        if (self.metrics.monthly_loss_pct <= -self.MONTHLY_LOSS_LIMIT and
                self.metrics.halt_state == CircuitBreakerState.ACTIVE):
            self._trigger_halt(
                CircuitBreakerState.MONTHLY_HALT,
                f"Monthly loss {self.metrics.monthly_loss_pct:.1%} exceeded -{self.MONTHLY_LOSS_LIMIT:.1%}",
                self.MONTHLY_HALT_DAYS
            )
    
    def _trigger_halt(self, state: CircuitBreakerState, reason: str, days: int) -> None:
        """Trigger circuit breaker halt.
        
        Args:
            state: Halt state
            reason: Reason for halt
            days: Number of days to halt
        """
        self.metrics.halt_state = state
        self.metrics.halt_reason = reason
        self.metrics.halt_until = datetime.now() + timedelta(days=days)
        
        logger.warning(
            f"🛑 CIRCUIT BREAKER TRIGGERED: {state.value} | "
            f"Reason: {reason} | Halt until: {self.metrics.halt_until}"
        )
    
    def is_halted(self) -> bool:
        """Check if trading is halted.
        
        Returns:
            True if currently halted
        """
        if self.metrics.halt_state == CircuitBreakerState.ACTIVE:
            return False
        
        # Check if halt has expired
        if self.metrics.halt_until and datetime.now() >= self.metrics.halt_until:
            self._resume_trading()
            return False
        
        return True
    
    def _resume_trading(self) -> None:
        """Resume trading after halt expires."""
        logger.info(
            f"✅ TRADING RESUMED after {self.metrics.halt_state.value} halt. "
            f"Reason was: {self.metrics.halt_reason}"
        )
        self.metrics.halt_state = CircuitBreakerState.ACTIVE
        self.metrics.halt_until = None
    
    def get_size_multiplier(self) -> float:
        """Get position size multiplier based on circuit breaker state.
        
        Returns:
            Size multiplier (0.5 if reduction active, else 1.0)
        """
        if self.metrics.size_reduction_active:
            if self.metrics.size_reduction_until and datetime.now() >= self.metrics.size_reduction_until:
                self.metrics.size_reduction_active = False
                self.metrics.size_reduction_until = None
                logger.info("✅ Size reduction expired - resuming full sizing")
            else:
                return 0.5
        
        return 1.0
    
    def reset_daily_metrics(self) -> None:
        """Reset daily metrics at end of trading day."""
        logger.info(
            f"📊 EOD Reset: {self.metrics.daily_trades} trades, "
            f"{self.metrics.daily_wins} wins, "
            f"{self.metrics.daily_losses} losses"
        )
        self.metrics.daily_trades = 0
        self.metrics.daily_wins = 0
        self.metrics.daily_losses = 0
        self.metrics.daily_loss_pct = 0.0
    
    def reset_weekly_metrics(self) -> None:
        """Reset weekly metrics at start of new week."""
        logger.info(
            f"📊 Weekly Reset: {self.metrics.week_trades} trades, "
            f"{self.metrics.weekly_loss_pct:.2%} weekly loss"
        )
        self.metrics.week_trades = 0
        self.metrics.weekly_loss_pct = 0.0
        self.metrics.weekly_start_date = datetime.now()
    
    def reset_monthly_metrics(self) -> None:
        """Reset monthly metrics at start of new month."""
        logger.info(
            f"📊 Monthly Reset: {self.metrics.month_trades} trades, "
            f"{self.metrics.monthly_loss_pct:.2%} monthly loss"
        )
        self.metrics.month_trades = 0
        self.metrics.monthly_loss_pct = 0.0
        self.metrics.monthly_start_date = datetime.now()
    
    def get_status(self) -> Dict:
        """Get current circuit breaker status.
        
        Returns:
            Status dictionary
        """
        return {
            'state': self.metrics.halt_state.value,
            'is_halted': self.is_halted(),
            'halt_reason': self.metrics.halt_reason,
            'halt_until': self.metrics.halt_until.isoformat() if self.metrics.halt_until else None,
            'daily_loss_pct': f"{self.metrics.daily_loss_pct:.2%}",
            'weekly_loss_pct': f"{self.metrics.weekly_loss_pct:.2%}",
            'monthly_loss_pct': f"{self.metrics.monthly_loss_pct:.2%}",
            'consecutive_losses': self.metrics.consecutive_losses,
            'size_reduction_active': self.metrics.size_reduction_active,
            'size_multiplier': self.get_size_multiplier()
        }
