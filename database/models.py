"""SQLAlchemy database models for Trading System v2.0"""

from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, 
    Boolean, Text, ForeignKey, JSON, create_engine
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


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


def init_db(db_path: str = "data/trading.db") -> None:
    """Initialize database and create tables."""
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
