"""SQLAlchemy database models for Trading System v2.0"""

from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, 
    Boolean, Text, ForeignKey, JSON, create_engine, Numeric, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import uuid
import os

Base = declarative_base()

# Database URL - defaults to PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://postgres:postgres@localhost:5432/trading"
)


class KiteCredentials(Base):
    """Store Kite API credentials - only keeps latest record."""
    __tablename__ = "kite_credentials"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Credentials
    api_key = Column(String(50), nullable=False)
    api_secret = Column(String(50), nullable=False)
    access_token = Column(String(100), nullable=False)
    
    # User info from Kite
    user_id = Column(String(50))
    user_name = Column(String(100))
    email = Column(String(100))
    broker = Column(String(20), default="ZERODHA")
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime)  # Kite tokens expire at 6 AM next day
    
    # Status
    is_valid = Column(Boolean, default=True)


class TradeRecord(Base):
    """Record of completed trades."""
    __tablename__ = "trades"
    
    id = Column(String, primary_key=True)
    timestamp = Column(DateTime, default=datetime.now)
    
    # Strategy info
    strategy = Column(String, nullable=False)  # IRON_CONDOR, JADE_LIZARD, etc.
    structure = Column(String, nullable=False)
    instrument = Column(String, nullable=False)
    
    # Context
    regime_at_entry = Column(String)
    entry_reason = Column(Text)
    exit_reason = Column(String)
    
    # Prices
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float)
    
    # P&L
    pnl = Column(Float)
    pnl_pct = Column(Float)
    
    # Margin
    margin_used = Column(Float)
    
    # Timestamps
    entry_time = Column(DateTime)
    exit_time = Column(DateTime)
    
    # Legs stored as JSON
    legs = Column(JSON)
    
    # Greeks at entry
    entry_greeks = Column(JSON)
    
    # Relationship to positions
    positions = relationship("PositionRecord", back_populates="trade")


class PositionRecord(Base):
    """Record of positions (open and closed)."""
    __tablename__ = "positions"
    
    id = Column(String, primary_key=True)
    trade_id = Column(String, ForeignKey("trades.id"))
    
    # Strategy info
    strategy_type = Column(String, nullable=False)
    instrument = Column(String, nullable=False)
    
    # Legs as JSON
    legs = Column(JSON)
    
    # Entry details
    entry_price = Column(Float, nullable=False)
    entry_time = Column(DateTime, default=datetime.now)
    
    # Risk parameters
    target_pnl = Column(Float)
    stop_loss = Column(Float)
    max_loss = Column(Float)
    
    # Expiry
    expiry = Column(Date)
    
    # Status
    status = Column(String, default="OPEN")  # OPEN, CLOSED
    
    # Exit details
    exit_price = Column(Float)
    exit_time = Column(DateTime)
    exit_reason = Column(String)
    realized_pnl = Column(Float)
    
    # Relationship
    trade = relationship("TradeRecord", back_populates="positions")


class RegimeLog(Base):
    """Log of regime detections."""
    __tablename__ = "regime_log"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.now)
    
    # Instrument
    instrument_token = Column(Integer)
    symbol = Column(String)
    
    # Regime
    regime = Column(String, nullable=False)
    ml_regime = Column(String)
    ml_probability = Column(Float)
    confidence = Column(Float)
    
    # Metrics
    adx = Column(Float)
    rsi = Column(Float)
    iv_percentile = Column(Float)
    realized_vol = Column(Float)
    
    # Flags
    event_flag = Column(Boolean, default=False)
    is_safe = Column(Boolean, default=True)
    
    # Price context
    spot_price = Column(Float)
    day_range_pct = Column(Float)


class EventRecord(Base):
    """Calendar events that affect trading."""
    __tablename__ = "events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Event info
    event_name = Column(String, nullable=False)
    event_type = Column(String)  # RBI, BUDGET, FED, EARNINGS, etc.
    
    # Dates
    event_date = Column(Date, nullable=False)
    blackout_start = Column(Date)
    blackout_end = Column(Date)
    
    # Metadata
    description = Column(Text)
    impact = Column(String)  # HIGH, MEDIUM, LOW
    
    # Status
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class DailyStats(Base):
    """Daily trading statistics."""
    __tablename__ = "daily_stats"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True)
    
    # P&L
    realized_pnl = Column(Float, default=0)
    unrealized_pnl = Column(Float, default=0)
    total_pnl = Column(Float, default=0)
    
    # Trades
    trades_opened = Column(Integer, default=0)
    trades_closed = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    
    # Capital
    starting_equity = Column(Float)
    ending_equity = Column(Float)
    high_watermark = Column(Float)
    drawdown = Column(Float)
    
    # Margin
    max_margin_used = Column(Float)
    avg_margin_used = Column(Float)
    
    # Regime
    dominant_regime = Column(String)
    regime_changes = Column(Integer, default=0)


class Portfolio(Base):
    """Portfolio - collection of strategies for aggregate tracking."""
    __tablename__ = "portfolios"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(Text)
    
    # P&L tracking
    realized_pnl = Column(Numeric(14, 2), default=0)
    unrealized_pnl = Column(Numeric(14, 2), default=0)
    
    # Risk metrics
    total_margin = Column(Numeric(14, 2), default=0)
    high_watermark = Column(Numeric(14, 2), default=0)
    max_drawdown = Column(Numeric(14, 2), default=0)
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    strategies = relationship("Strategy", back_populates="portfolio")


class Strategy(Base):
    """User-defined strategy - flexible grouping of positions."""
    __tablename__ = "strategies"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    portfolio_id = Column(String, ForeignKey("portfolios.id"), nullable=True)
    
    # User-defined naming
    name = Column(String(200), nullable=False)
    description = Column(Text)
    label = Column(String(50))  # Optional: IRON_CONDOR, SPREAD, CUSTOM, etc.
    
    # Primary underlying (optional - can span multiple)
    primary_instrument = Column(String(50))
    
    # P&L tracking
    entry_value = Column(Numeric(14, 2), default=0)
    current_value = Column(Numeric(14, 2), default=0)
    realized_pnl = Column(Numeric(14, 2), default=0)
    unrealized_pnl = Column(Numeric(14, 2), default=0)
    
    # Risk parameters (optional)
    target_pnl = Column(Numeric(14, 2))
    stop_loss = Column(Numeric(14, 2))
    
    # Greeks (aggregate, calculated from positions)
    delta = Column(Numeric(10, 4), default=0)
    gamma = Column(Numeric(10, 6), default=0)
    theta = Column(Numeric(10, 4), default=0)
    vega = Column(Numeric(10, 4), default=0)
    
    # Status
    status = Column(String(20), default="OPEN")  # OPEN, CLOSED, PARTIAL
    source = Column(String(10), default="PAPER")  # PAPER or LIVE
    
    # Context
    notes = Column(Text)
    tags = Column(JSON)  # Array of user-defined tags
    
    # Exit info
    closed_at = Column(DateTime)
    close_reason = Column(String(100))
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    portfolio = relationship("Portfolio", back_populates="strategies")
    strategy_positions = relationship("StrategyPosition", back_populates="strategy", cascade="all, delete-orphan")
    trades = relationship("StrategyTrade", back_populates="strategy", cascade="all, delete-orphan")


class BrokerPosition(Base):
    """Individual position from broker (can belong to zero or one strategy)."""
    __tablename__ = "broker_positions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Broker info
    tradingsymbol = Column(String(100), nullable=False)
    instrument_token = Column(Integer, nullable=False)
    exchange = Column(String(10), default="NFO")
    
    # Position details
    quantity = Column(Integer, nullable=False)
    average_price = Column(Numeric(12, 2), nullable=False)
    last_price = Column(Numeric(12, 2))
    pnl = Column(Numeric(14, 2), default=0)
    
    # Option details (if applicable)
    strike = Column(Numeric(12, 2))
    expiry = Column(Date)
    option_type = Column(String(2))  # CE or PE
    underlying = Column(String(50))
    
    # Transaction
    transaction_type = Column(String(4))  # BUY or SELL
    product = Column(String(10))  # NRML, MIS, etc.
    
    # Source
    source = Column(String(10), default="LIVE")  # LIVE or PAPER
    broker_order_id = Column(String(50))
    
    # Timestamps
    opened_at = Column(DateTime, default=datetime.now)
    closed_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    strategy_positions = relationship("StrategyPosition", back_populates="position")


class StrategyPosition(Base):
    """Many-to-many relationship between strategies and positions."""
    __tablename__ = "strategy_positions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    strategy_id = Column(String, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False)
    position_id = Column(String, ForeignKey("broker_positions.id", ondelete="CASCADE"), nullable=False)
    
    # When this position was added to the strategy
    added_at = Column(DateTime, default=datetime.now)
    
    # Optional: quantity allocated to this strategy (for partial allocation)
    allocated_quantity = Column(Integer)
    
    # Relationships
    strategy = relationship("Strategy", back_populates="strategy_positions")
    position = relationship("BrokerPosition", back_populates="strategy_positions")
    
    __table_args__ = (
        UniqueConstraint('strategy_id', 'position_id', name='uq_strategy_position'),
    )


class PortfolioSnapshot(Base):
    """Daily snapshots for portfolio-level tracking."""
    __tablename__ = "portfolio_snapshots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(String, ForeignKey("portfolios.id"))
    date = Column(Date, nullable=False)
    
    # P&L
    realized_pnl = Column(Numeric(14, 2), default=0)
    unrealized_pnl = Column(Numeric(14, 2), default=0)
    total_pnl = Column(Numeric(14, 2), default=0)
    
    # Metrics
    strategy_count = Column(Integer, default=0)
    position_count = Column(Integer, default=0)
    
    # Risk
    margin_used = Column(Numeric(14, 2), default=0)
    high_watermark = Column(Numeric(14, 2), default=0)
    drawdown = Column(Numeric(14, 2), default=0)
    
    created_at = Column(DateTime, default=datetime.now)
    
    __table_args__ = (
        UniqueConstraint('portfolio_id', 'date', name='uq_portfolio_date'),
    )


# Keep legacy StrategyLeg for backward compatibility during migration
class StrategyLeg(Base):
    """Individual leg of a strategy (legacy - use BrokerPosition instead)."""
    __tablename__ = "strategy_legs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    strategy_id = Column(String, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False)
    
    # Leg info
    leg_type = Column(String(20), nullable=False)
    tradingsymbol = Column(String(100), nullable=False)
    instrument_token = Column(Integer, nullable=False)
    exchange = Column(String(10), default="NFO")
    
    # Option details
    strike = Column(Numeric(12, 2))
    expiry = Column(Date)
    option_type = Column(String(2))
    
    # Quantity and prices
    quantity = Column(Integer, nullable=False)
    entry_price = Column(Numeric(12, 2), nullable=False)
    current_price = Column(Numeric(12, 2))
    
    # Greeks
    delta = Column(Numeric(10, 4), default=0)
    gamma = Column(Numeric(10, 6), default=0)
    theta = Column(Numeric(10, 4), default=0)
    vega = Column(Numeric(10, 4), default=0)
    
    # Broker reference
    broker_order_id = Column(String(50))
    
    created_at = Column(DateTime, default=datetime.now)
    
    # Legacy relationship - kept for backward compatibility


class StrategyTrade(Base):
    """Individual trade belonging to a strategy.
    
    This is the key model for tracking strategy-level P&L.
    Multiple strategies can have positions in the same instrument,
    but each trade is uniquely assigned to one strategy.
    
    Unlike BrokerPosition (which mirrors Kite's aggregated view),
    StrategyTrade tracks individual entry/exit transactions.
    """
    __tablename__ = "strategy_trades"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    strategy_id = Column(String, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False)
    
    # Instrument info
    tradingsymbol = Column(String(100), nullable=False)
    instrument_token = Column(Integer, nullable=False)
    exchange = Column(String(10), default="NFO")
    
    # Instrument details (cached for quick access)
    instrument_type = Column(String(10))  # EQ, FUT, CE, PE
    lot_size = Column(Integer, default=1)
    strike = Column(Numeric(12, 2))
    expiry = Column(Date)
    option_type = Column(String(2))  # CE or PE
    underlying = Column(String(50))
    
    # Trade details
    quantity = Column(Integer, nullable=False)  # Positive for long, negative for short
    entry_price = Column(Numeric(12, 2), nullable=False)
    entry_time = Column(DateTime, default=datetime.now)
    
    # Current state (updated via WebSocket ticks)
    last_price = Column(Numeric(12, 2))
    last_updated = Column(DateTime)
    
    # P&L (calculated by backend)
    unrealized_pnl = Column(Numeric(14, 2), default=0)
    realized_pnl = Column(Numeric(14, 2), default=0)
    pnl_pct = Column(Numeric(8, 2), default=0)
    
    # Exit details (when closed)
    exit_price = Column(Numeric(12, 2))
    exit_time = Column(DateTime)
    exit_reason = Column(String(100))
    
    # Status
    status = Column(String(20), default="OPEN")  # OPEN, CLOSED, PARTIAL
    
    # Broker reference
    broker_order_id = Column(String(50))
    kite_position_id = Column(String(50))  # Reference to Kite's position if needed
    
    # Source
    source = Column(String(10), default="LIVE")  # LIVE or PAPER
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationship
    strategy = relationship("Strategy", back_populates="trades")


class StrategyPerformance(Base):
    """Aggregated performance by strategy type."""
    __tablename__ = "strategy_performance"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    strategy_type = Column(String(50), nullable=False)
    
    # Trade counts
    trades_opened = Column(Integer, default=0)
    trades_closed = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    
    # P&L
    realized_pnl = Column(Numeric(12, 2), default=0)
    unrealized_pnl = Column(Numeric(12, 2), default=0)
    
    # Metrics
    win_rate = Column(Numeric(5, 2))
    avg_win = Column(Numeric(12, 2))
    avg_loss = Column(Numeric(12, 2))
    profit_factor = Column(Numeric(8, 2))
    
    # Risk
    max_drawdown = Column(Numeric(12, 2))
    avg_holding_days = Column(Numeric(5, 2))
    
    __table_args__ = (
        UniqueConstraint('date', 'strategy_type', name='uq_date_strategy'),
    )


# Database engine and session
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL)
    return _engine


def get_session():
    """Get a new database session."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def init_db(db_url: str = None) -> None:
    """Initialize database and create tables."""
    global _engine
    if db_url:
        _engine = create_engine(db_url)
    else:
        _engine = get_engine()
    Base.metadata.create_all(_engine)
