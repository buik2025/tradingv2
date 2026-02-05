"""Position and account state models for Trading System v2.0"""

from datetime import datetime, date
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
import uuid

from .trade import TradeLeg, StructureType


class PositionStatus(str):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PARTIAL = "PARTIAL"


class Position(BaseModel):
    """
    Active position in the portfolio.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str = Field(..., description="Original signal ID")
    
    # Structure info
    strategy_type: StructureType = Field(..., description="Strategy type")
    instrument: str = Field(..., description="Underlying instrument")
    instrument_token: int = Field(..., description="Underlying token")
    
    # Legs
    legs: List[TradeLeg] = Field(..., description="Position legs")
    
    # Entry details
    entry_timestamp: datetime = Field(default_factory=datetime.now)
    entry_price: float = Field(..., description="Net entry price")
    entry_margin: float = Field(..., description="Margin at entry")
    
    # Current state
    status: str = Field(PositionStatus.OPEN)
    current_price: float = Field(0.0, description="Current net price")
    current_pnl: float = Field(0.0, description="Unrealized P&L")
    current_pnl_pct: float = Field(0.0, description="P&L as percentage")
    
    # Risk parameters
    target_pnl: float = Field(..., description="Profit target")
    stop_loss: float = Field(..., description="Stop loss level")
    max_loss: float = Field(..., description="Maximum possible loss")
    
    # Expiry
    expiry: date = Field(..., description="Expiry date")
    days_to_expiry: int = Field(..., description="Days to expiry")
    exit_dte: int = Field(5, description="Mandatory exit DTE")
    
    # Greeks (aggregate)
    greeks: Dict[str, float] = Field(
        default_factory=lambda: {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    )
    
    # Context
    regime_at_entry: str = Field(..., description="Regime at entry")
    entry_reason: str = Field("", description="Entry reason")
    
    # Flags
    is_intraday: bool = Field(False)
    is_hedged: bool = Field(True, description="True if defined-risk")
    
    # Exit info (populated on close)
    exit_timestamp: Optional[datetime] = Field(None)
    exit_price: Optional[float] = Field(None)
    exit_reason: Optional[str] = Field(None)
    realized_pnl: Optional[float] = Field(None)
    
    def update_pnl(self, current_prices: Dict[int, float]) -> None:
        """Update P&L based on current prices."""
        total_entry = 0.0
        total_current = 0.0
        
        for leg in self.legs:
            token = leg.instrument_token
            if token in current_prices:
                leg.current_price = current_prices[token]
            
            if leg.current_price:
                multiplier = 1 if leg.is_long else -1
                total_entry += leg.entry_price * leg.quantity * multiplier
                total_current += leg.current_price * leg.quantity * multiplier
        
        self.current_price = total_current
        self.current_pnl = total_current - total_entry
        if abs(total_entry) > 0:
            self.current_pnl_pct = self.current_pnl / abs(total_entry)
    
    def update_greeks(self) -> Dict[str, float]:
        """Calculate aggregate Greeks."""
        greeks = {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
        for leg in self.legs:
            multiplier = 1 if leg.is_long else -1
            greeks["delta"] += leg.delta * multiplier * leg.quantity
            greeks["gamma"] += leg.gamma * multiplier * leg.quantity
            greeks["theta"] += leg.theta * multiplier * leg.quantity
            greeks["vega"] += leg.vega * multiplier * leg.quantity
        self.greeks = greeks
        return greeks
    
    def should_exit_profit(self) -> bool:
        """Check if profit target hit."""
        return self.current_pnl >= self.target_pnl
    
    def should_exit_stop(self) -> bool:
        """Check if stop loss hit."""
        return self.current_pnl <= self.stop_loss
    
    def should_exit_time(self, current_dte: int) -> bool:
        """Check if time-based exit triggered."""
        return current_dte <= self.exit_dte
    
    def close(self, exit_price: float, exit_reason: str) -> None:
        """Close the position."""
        self.status = PositionStatus.CLOSED
        self.exit_timestamp = datetime.now()
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        self.realized_pnl = self.current_pnl


class AccountState(BaseModel):
    """
    Current account state for risk management.
    """
    timestamp: datetime = Field(default_factory=datetime.now)
    
    # Capital
    equity: float = Field(..., description="Total equity")
    available_margin: float = Field(..., description="Available margin")
    used_margin: float = Field(0.0, description="Used margin")
    margin_utilization: float = Field(0.0, description="Margin utilization %")
    
    # High watermark and drawdown
    high_watermark: float = Field(..., description="Peak equity")
    drawdown: float = Field(0.0, description="Current drawdown from HWM")
    drawdown_pct: float = Field(0.0, description="Drawdown percentage")
    
    # P&L tracking
    daily_pnl: float = Field(0.0)
    weekly_pnl: float = Field(0.0)
    monthly_pnl: float = Field(0.0)
    daily_pnl_pct: float = Field(0.0)
    weekly_pnl_pct: float = Field(0.0)
    monthly_pnl_pct: float = Field(0.0)
    
    # Positions
    open_positions: List[Position] = Field(default_factory=list)
    position_count: int = Field(0)
    
    # Portfolio Greeks
    portfolio_greeks: Dict[str, float] = Field(
        default_factory=lambda: {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    )
    
    # Circuit breaker state
    flat_days_remaining: int = Field(0)
    circuit_breaker_active: bool = Field(False)
    circuit_breaker_reason: Optional[str] = Field(None)
    
    def update_from_positions(self) -> None:
        """Update account state from open positions."""
        self.position_count = len(self.open_positions)
        
        # Aggregate Greeks
        greeks = {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
        total_margin = 0.0
        
        for pos in self.open_positions:
            for key in greeks:
                greeks[key] += pos.greeks.get(key, 0)
            total_margin += pos.entry_margin
        
        self.portfolio_greeks = greeks
        self.used_margin = total_margin
        self.margin_utilization = total_margin / self.equity if self.equity > 0 else 0
    
    def update_drawdown(self) -> None:
        """Update drawdown calculations."""
        if self.equity > self.high_watermark:
            self.high_watermark = self.equity
        
        self.drawdown = self.high_watermark - self.equity
        self.drawdown_pct = self.drawdown / self.high_watermark if self.high_watermark > 0 else 0
    
    def get_drawdown_multiplier(self) -> float:
        """Get position size multiplier based on drawdown."""
        if self.drawdown_pct >= 0.15:
            return 0.0  # Stop trading
        elif self.drawdown_pct >= 0.10:
            return 0.25
        elif self.drawdown_pct >= 0.05:
            return 0.50
        return 1.0
    
    def can_open_position(self, required_margin: float, max_positions: int = 3) -> tuple[bool, str]:
        """Check if a new position can be opened."""
        if self.circuit_breaker_active:
            return False, f"Circuit breaker active: {self.circuit_breaker_reason}"
        
        if self.position_count >= max_positions:
            return False, f"Max positions ({max_positions}) reached"
        
        new_utilization = (self.used_margin + required_margin) / self.equity
        if new_utilization > 0.40:
            return False, f"Would exceed 40% margin utilization ({new_utilization:.1%})"
        
        if self.get_drawdown_multiplier() == 0:
            return False, "Trading halted due to 15% drawdown"
        
        return True, "OK"
