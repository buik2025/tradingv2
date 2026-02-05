"""Order and execution models for Trading System v2.0"""

from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


class OrderStatus(str, Enum):
    """Order status types."""
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    TRIGGER_PENDING = "TRIGGER_PENDING"


class OrderType(str, Enum):
    """Order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class TransactionType(str, Enum):
    """Transaction types."""
    BUY = "BUY"
    SELL = "SELL"


class ProductType(str, Enum):
    """Product types."""
    MIS = "MIS"  # Intraday
    NRML = "NRML"  # Overnight/positional


class OrderTicket(BaseModel):
    """
    Order ticket for a single leg, ready for execution.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str = Field(..., description="Parent signal ID")
    leg_id: str = Field(..., description="Leg ID from signal")
    
    # Order details
    tradingsymbol: str = Field(..., description="Trading symbol")
    exchange: str = Field("NFO", description="Exchange")
    transaction_type: TransactionType = Field(..., description="BUY or SELL")
    quantity: int = Field(..., description="Order quantity")
    
    order_type: OrderType = Field(OrderType.LIMIT, description="Order type")
    product: ProductType = Field(ProductType.NRML, description="Product type")
    
    price: Optional[float] = Field(None, description="Limit price")
    trigger_price: Optional[float] = Field(None, description="Trigger price for SL orders")
    
    # Execution tracking
    status: OrderStatus = Field(OrderStatus.PENDING, description="Order status")
    broker_order_id: Optional[str] = Field(None, description="Broker order ID")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    submitted_at: Optional[datetime] = Field(None)
    filled_at: Optional[datetime] = Field(None)
    
    # Fill details
    filled_quantity: int = Field(0, description="Filled quantity")
    average_price: float = Field(0.0, description="Average fill price")
    
    # Tags
    tag: str = Field("", description="Order tag for tracking")
    
    @property
    def is_complete(self) -> bool:
        return self.status == OrderStatus.COMPLETE
    
    @property
    def is_pending(self) -> bool:
        return self.status in [OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.TRIGGER_PENDING]
    
    @property
    def slippage(self) -> float:
        """Calculate slippage from limit price."""
        if self.price and self.average_price:
            return abs(self.average_price - self.price) / self.price
        return 0.0


class ExecutionResult(BaseModel):
    """
    Result of order execution attempt.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str = Field(..., description="Signal ID")
    timestamp: datetime = Field(default_factory=datetime.now)
    
    # Overall status
    success: bool = Field(..., description="True if all legs executed")
    partial: bool = Field(False, description="True if partially filled")
    
    # Order results
    orders: List[OrderTicket] = Field(default_factory=list, description="Individual order results")
    
    # Aggregate fill info
    total_filled_quantity: int = Field(0)
    total_value: float = Field(0.0, description="Total value of fills")
    net_premium: float = Field(0.0, description="Net premium received/paid")
    
    # Costs
    brokerage: float = Field(0.0)
    taxes: float = Field(0.0)
    total_costs: float = Field(0.0)
    
    # Error info
    error_message: Optional[str] = Field(None)
    failed_legs: List[str] = Field(default_factory=list, description="IDs of failed legs")
    
    # Position created
    position_id: Optional[str] = Field(None, description="ID of created position")
    
    def calculate_costs(self, brokerage_pct: float = 0.0003) -> None:
        """Calculate transaction costs."""
        self.brokerage = abs(self.total_value) * brokerage_pct
        self.taxes = abs(self.total_value) * 0.001  # Approximate STT + other charges
        self.total_costs = self.brokerage + self.taxes


class ExitOrder(BaseModel):
    """
    Exit order for closing a position or leg.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    position_id: str = Field(..., description="Position to exit")
    leg_ids: List[str] = Field(default_factory=list, description="Specific legs to exit (empty = all)")
    
    exit_reason: str = Field(..., description="Reason for exit")
    exit_type: str = Field("NORMAL", description="NORMAL, STOP_LOSS, PROFIT_TARGET, EMERGENCY")
    
    # Order parameters
    order_type: OrderType = Field(OrderType.MARKET, description="Order type for exit")
    urgency: str = Field("NORMAL", description="NORMAL, HIGH, EMERGENCY")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    executed_at: Optional[datetime] = Field(None)
    
    # Result
    success: bool = Field(False)
    realized_pnl: float = Field(0.0)
    execution_result: Optional[ExecutionResult] = Field(None)
