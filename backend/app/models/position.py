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
    
    # Dynamic Exit Targeting (Section 4 - rulebook)
    exit_target_low: float = Field(..., description="Lower bound profit target")
    exit_target_high: float = Field(..., description="Upper bound profit target")
    current_target: float = Field(..., description="Current active profit target")
    
    # Trailing Profit (Section 11 - rulebook)
    trailing_enabled: bool = Field(True, description="Enable trailing logic")
    trailing_mode: str = Field("none", description="'atr' or 'bbw' or 'none'")
    trailing_active: bool = Field(False, description="Trailing currently active")
    trailing_threshold: float = Field(0.5, description="Activate trailing at 50% profit")
    trailing_stop: Optional[float] = Field(None, description="Current trailing stop")
    trailing_last_update: Optional[datetime] = Field(None, description="Last update time")
    
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
        return self.current_pnl >= self.current_target
    
    def should_exit_stop(self) -> bool:
        """Check if stop loss hit."""
        return self.current_pnl <= self.stop_loss
    
    def update_trailing_stop(self, current_price: float, atr: Optional[float] = None,
                            bbw_ratio: Optional[float] = None) -> bool:
        """
        Update trailing stop based on market conditions.
        
        Section 11 of rulebook:
        - ATR-based for directional (±0.5x ATR, update every 15 min)
        - BBW-based for short-vol (>1.8x avg → exit if profitable)
        
        Returns True if trailing stop should trigger exit
        """
        if not self.trailing_enabled or self.trailing_mode == "none":
            return False
        
        # Activate trailing at 50% of target profit
        if not self.trailing_active and self.current_pnl >= self.current_target * self.trailing_threshold:
            self.trailing_active = True
            self.trailing_last_update = datetime.now()
            return False
        
        if not self.trailing_active:
            return False
        
        # Update based on mode
        if self.trailing_mode == "atr" and atr is not None:
            # ATR-based: ±0.5x ATR stop
            new_stop = current_price - (atr * 0.5)
            if self.trailing_stop is None or new_stop > self.trailing_stop:
                self.trailing_stop = new_stop
                self.trailing_last_update = datetime.now()
            return self.current_pnl <= self.trailing_stop
        
        elif self.trailing_mode == "bbw" and bbw_ratio is not None:
            # BBW-based: expand at >1.8x avg
            if bbw_ratio > 1.8 and self.current_pnl > 0:
                lock_amount = self.current_target * 0.6
                if self.trailing_stop is None or lock_amount > self.trailing_stop:
                    self.trailing_stop = lock_amount
                    self.trailing_last_update = datetime.now()
                return False
        
        return False
    
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
