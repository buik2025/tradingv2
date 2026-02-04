"""Data access layer for Trading System v2.0"""

from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from pathlib import Path
from sqlalchemy import create_engine, desc, and_
from sqlalchemy.orm import sessionmaker, Session
from loguru import logger

from .models import Base, TradeRecord, PositionRecord, RegimeLog, EventRecord, DailyStats


class Repository:
    """
    Data access layer for the trading system.
    Handles all database operations.
    """
    
    def __init__(self, db_path: Path = Path("data/trading.db")):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(self.engine)
        
        self.Session = sessionmaker(bind=self.engine)
    
    def _get_session(self) -> Session:
        """Get a new database session."""
        return self.Session()
    
    # Trade operations
    def save_trade(self, trade: TradeRecord) -> None:
        """Save a trade record."""
        with self._get_session() as session:
            session.merge(trade)
            session.commit()
            logger.debug(f"Saved trade: {trade.id}")
    
    def get_trade(self, trade_id: str) -> Optional[TradeRecord]:
        """Get a trade by ID."""
        with self._get_session() as session:
            return session.query(TradeRecord).filter_by(id=trade_id).first()
    
    def get_trades(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        strategy: Optional[str] = None,
        limit: int = 100
    ) -> List[TradeRecord]:
        """Get trades with optional filters."""
        with self._get_session() as session:
            query = session.query(TradeRecord)
            
            if from_date:
                query = query.filter(TradeRecord.timestamp >= datetime.combine(from_date, datetime.min.time()))
            if to_date:
                query = query.filter(TradeRecord.timestamp <= datetime.combine(to_date, datetime.max.time()))
            if strategy:
                query = query.filter(TradeRecord.strategy == strategy)
            
            return query.order_by(desc(TradeRecord.timestamp)).limit(limit).all()
    
    def get_trade_stats(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Get aggregate trade statistics."""
        trades = self.get_trades(from_date, to_date, limit=10000)
        
        if not trades:
            return {}
        
        pnls = [t.pnl or 0 for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        return {
            "total_trades": len(trades),
            "total_pnl": sum(pnls),
            "win_rate": len(wins) / len(trades) if trades else 0,
            "avg_win": sum(wins) / len(wins) if wins else 0,
            "avg_loss": sum(losses) / len(losses) if losses else 0,
            "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
        }
    
    # Position operations
    def save_position(self, position: PositionRecord) -> None:
        """Save a position record."""
        with self._get_session() as session:
            session.merge(position)
            session.commit()
    
    def get_open_positions(self) -> List[PositionRecord]:
        """Get all open positions."""
        with self._get_session() as session:
            return session.query(PositionRecord).filter_by(status="OPEN").all()
    
    def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str,
        realized_pnl: float
    ) -> None:
        """Close a position."""
        with self._get_session() as session:
            position = session.query(PositionRecord).filter_by(id=position_id).first()
            if position:
                position.status = "CLOSED"
                position.exit_price = exit_price
                position.exit_time = datetime.now()
                position.exit_reason = exit_reason
                position.realized_pnl = realized_pnl
                session.commit()
    
    # Regime log operations
    def log_regime(self, regime_log: RegimeLog) -> None:
        """Log a regime detection."""
        with self._get_session() as session:
            session.add(regime_log)
            session.commit()
    
    def get_regime_history(
        self,
        instrument_token: int,
        hours: int = 24
    ) -> List[RegimeLog]:
        """Get recent regime history."""
        with self._get_session() as session:
            cutoff = datetime.now() - timedelta(hours=hours)
            return session.query(RegimeLog).filter(
                and_(
                    RegimeLog.instrument_token == instrument_token,
                    RegimeLog.timestamp >= cutoff
                )
            ).order_by(desc(RegimeLog.timestamp)).all()
    
    def get_latest_regime(self, instrument_token: int) -> Optional[RegimeLog]:
        """Get the most recent regime for an instrument."""
        with self._get_session() as session:
            return session.query(RegimeLog).filter_by(
                instrument_token=instrument_token
            ).order_by(desc(RegimeLog.timestamp)).first()
    
    # Event operations
    def add_event(self, event: EventRecord) -> None:
        """Add a calendar event."""
        with self._get_session() as session:
            session.add(event)
            session.commit()
    
    def get_upcoming_events(self, days: int = 14) -> List[EventRecord]:
        """Get events in the next N days."""
        with self._get_session() as session:
            today = date.today()
            end_date = today + timedelta(days=days)
            return session.query(EventRecord).filter(
                and_(
                    EventRecord.event_date >= today,
                    EventRecord.event_date <= end_date,
                    EventRecord.is_active == True
                )
            ).order_by(EventRecord.event_date).all()
    
    def get_events_in_blackout(self) -> List[EventRecord]:
        """Get events where today is in blackout period."""
        with self._get_session() as session:
            today = date.today()
            return session.query(EventRecord).filter(
                and_(
                    EventRecord.blackout_start <= today,
                    EventRecord.blackout_end >= today,
                    EventRecord.is_active == True
                )
            ).all()
    
    # Daily stats operations
    def save_daily_stats(self, stats: DailyStats) -> None:
        """Save daily statistics."""
        with self._get_session() as session:
            session.merge(stats)
            session.commit()
    
    def get_daily_stats(self, target_date: date) -> Optional[DailyStats]:
        """Get stats for a specific date."""
        with self._get_session() as session:
            return session.query(DailyStats).filter_by(date=target_date).first()
    
    def get_stats_range(
        self,
        from_date: date,
        to_date: date
    ) -> List[DailyStats]:
        """Get daily stats for a date range."""
        with self._get_session() as session:
            return session.query(DailyStats).filter(
                and_(
                    DailyStats.date >= from_date,
                    DailyStats.date <= to_date
                )
            ).order_by(DailyStats.date).all()
    
    # Utility methods
    def backup(self, backup_path: Path) -> None:
        """Create a backup of the database."""
        import shutil
        shutil.copy(self.db_path, backup_path)
        logger.info(f"Database backed up to {backup_path}")
    
    def get_db_stats(self) -> Dict[str, int]:
        """Get database statistics."""
        with self._get_session() as session:
            return {
                "trades": session.query(TradeRecord).count(),
                "positions": session.query(PositionRecord).count(),
                "regime_logs": session.query(RegimeLog).count(),
                "events": session.query(EventRecord).count(),
                "daily_stats": session.query(DailyStats).count()
            }
