"""Data access layer for Trading System v2.0"""

from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from pathlib import Path
from sqlalchemy import create_engine, desc, and_
from sqlalchemy.orm import sessionmaker, Session
from loguru import logger

from .models import (
    Base, TradeRecord, PositionRecord, RegimeLog, EventRecord, DailyStats,
    Strategy, StrategyLeg, StrategyPerformance, StrategyTrade, Portfolio, 
    BrokerPosition, StrategyPosition, DATABASE_URL
)


class Repository:
    """
    Data access layer for the trading system.
    Handles all database operations.
    """
    
    def __init__(self, db_url: str = None, db_path: Path = None):
        """
        Initialize repository with PostgreSQL or SQLite.
        
        Args:
            db_url: PostgreSQL connection URL (preferred)
            db_path: SQLite file path (legacy fallback)
        """
        if db_url:
            self.db_url = db_url
            self.db_path = None
        elif db_path:
            self.db_path = db_path
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_url = f"sqlite:///{db_path}"
        else:
            # Default to PostgreSQL
            self.db_url = DATABASE_URL
            self.db_path = None
        
        self.engine = create_engine(self.db_url)
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
                "strategies": session.query(Strategy).count(),
                "regime_logs": session.query(RegimeLog).count(),
                "events": session.query(EventRecord).count(),
                "daily_stats": session.query(DailyStats).count()
            }
    
    # Strategy operations
    def save_strategy(self, strategy: Strategy) -> None:
        """Save a strategy with its legs."""
        with self._get_session() as session:
            session.merge(strategy)
            session.commit()
            logger.debug(f"Saved strategy: {strategy.id}")
    
    def get_strategy(self, strategy_id: str) -> Optional[Strategy]:
        """Get a strategy by ID."""
        with self._get_session() as session:
            return session.query(Strategy).filter_by(id=strategy_id).first()
    
    def get_open_strategies(self, source: str = None) -> List[Strategy]:
        """Get all open strategies, optionally filtered by source."""
        with self._get_session() as session:
            query = session.query(Strategy).filter_by(status="OPEN")
            if source:
                query = query.filter_by(source=source)
            return query.order_by(desc(Strategy.entry_timestamp)).all()
    
    def get_strategies(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        strategy_type: Optional[str] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100
    ) -> List[Strategy]:
        """Get strategies with optional filters."""
        with self._get_session() as session:
            query = session.query(Strategy)
            
            if from_date:
                query = query.filter(Strategy.entry_timestamp >= datetime.combine(from_date, datetime.min.time()))
            if to_date:
                query = query.filter(Strategy.entry_timestamp <= datetime.combine(to_date, datetime.max.time()))
            if strategy_type:
                query = query.filter(Strategy.strategy_type == strategy_type)
            if status:
                query = query.filter(Strategy.status == status)
            if source:
                query = query.filter(Strategy.source == source)
            
            return query.order_by(desc(Strategy.entry_timestamp)).limit(limit).all()
    
    def close_strategy(
        self,
        strategy_id: str,
        exit_price: float,
        exit_reason: str,
        realized_pnl: float
    ) -> None:
        """Close a strategy."""
        with self._get_session() as session:
            strategy = session.query(Strategy).filter_by(id=strategy_id).first()
            if strategy:
                strategy.status = "CLOSED"
                strategy.exit_price = exit_price
                strategy.exit_timestamp = datetime.now()
                strategy.exit_reason = exit_reason
                strategy.realized_pnl = realized_pnl
                session.commit()
                logger.info(f"Closed strategy {strategy_id}: {exit_reason}, P&L: {realized_pnl}")
    
    def update_strategy_prices(self, strategy_id: str, current_price: float, current_pnl: float, current_pnl_pct: float) -> None:
        """Update current prices for a strategy."""
        with self._get_session() as session:
            strategy = session.query(Strategy).filter_by(id=strategy_id).first()
            if strategy:
                strategy.current_price = current_price
                strategy.current_pnl = current_pnl
                strategy.current_pnl_pct = current_pnl_pct
                strategy.updated_at = datetime.now()
                session.commit()
    
    def get_strategies_by_type(self) -> Dict[str, Dict[str, Any]]:
        """Get strategies grouped by type with aggregated metrics."""
        with self._get_session() as session:
            strategies = session.query(Strategy).all()
            
            result = {}
            for s in strategies:
                stype = s.strategy_type
                if stype not in result:
                    result[stype] = {
                        "strategy_type": stype,
                        "open_count": 0,
                        "closed_count": 0,
                        "total_pnl": 0,
                        "unrealized_pnl": 0,
                        "winning_trades": 0,
                        "losing_trades": 0,
                        "positions": []
                    }
                
                if s.status == "OPEN":
                    result[stype]["open_count"] += 1
                    result[stype]["unrealized_pnl"] += float(s.current_pnl or 0)
                else:
                    result[stype]["closed_count"] += 1
                    pnl = float(s.realized_pnl or 0)
                    result[stype]["total_pnl"] += pnl
                    if pnl > 0:
                        result[stype]["winning_trades"] += 1
                    elif pnl < 0:
                        result[stype]["losing_trades"] += 1
                
                result[stype]["positions"].append(s)
            
            # Calculate win rates
            for stype, data in result.items():
                total_closed = data["closed_count"]
                if total_closed > 0:
                    data["win_rate"] = data["winning_trades"] / total_closed
                else:
                    data["win_rate"] = 0
            
            return result
    
    def save_strategy_performance(self, perf: StrategyPerformance) -> None:
        """Save strategy performance record."""
        with self._get_session() as session:
            session.merge(perf)
            session.commit()
    
    def get_strategy_performance(
        self,
        from_date: date,
        to_date: date,
        strategy_type: Optional[str] = None
    ) -> List[StrategyPerformance]:
        """Get strategy performance for a date range."""
        with self._get_session() as session:
            query = session.query(StrategyPerformance).filter(
                and_(
                    StrategyPerformance.date >= from_date,
                    StrategyPerformance.date <= to_date
                )
            )
            if strategy_type:
                query = query.filter(StrategyPerformance.strategy_type == strategy_type)
            return query.order_by(StrategyPerformance.date).all()
    
    # ============== Portfolio Operations ==============
    
    def get_all_portfolios(self) -> List[Dict[str, Any]]:
        """Get all portfolios as dictionaries for API response."""
        with self._get_session() as session:
            portfolios = session.query(Portfolio).filter(
                Portfolio.is_active == True
            ).order_by(desc(Portfolio.created_at)).all()
            
            return [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "realized_pnl": float(p.realized_pnl or 0),
                    "unrealized_pnl": float(p.unrealized_pnl or 0),
                    "total_margin": float(p.total_margin or 0),
                    "is_active": p.is_active,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in portfolios
            ]
    
    def save_portfolio(self, portfolio: Portfolio) -> str:
        """Save a portfolio and return its ID."""
        with self._get_session() as session:
            session.merge(portfolio)
            session.commit()
            logger.info(f"Saved portfolio: {portfolio.id} - {portfolio.name}")
            return portfolio.id
    
    def get_portfolio(self, portfolio_id: str) -> Optional[Portfolio]:
        """Get a portfolio by ID."""
        with self._get_session() as session:
            return session.query(Portfolio).filter_by(id=portfolio_id).first()
    
    # ============== Strategy Operations (Extended) ==============
    
    def get_all_strategies(self) -> List[Dict[str, Any]]:
        """Get all strategies with their trades as dictionaries for API response."""
        with self._get_session() as session:
            strategies = session.query(Strategy).filter(
                Strategy.status == "OPEN"
            ).order_by(desc(Strategy.created_at)).all()
            
            result = []
            for s in strategies:
                # Get trades for this strategy
                trades = session.query(StrategyTrade).filter(
                    StrategyTrade.strategy_id == s.id,
                    StrategyTrade.status == "OPEN"
                ).all()
                
                result.append({
                    "id": s.id,
                    "portfolio_id": s.portfolio_id,
                    "name": s.name,
                    "description": s.description,
                    "label": s.label,
                    "status": s.status,
                    "source": s.source,
                    "realized_pnl": float(s.realized_pnl or 0),
                    "unrealized_pnl": float(s.unrealized_pnl or 0),
                    "notes": s.notes,
                    "tags": s.tags,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "trades": [
                        {
                            "id": t.id,
                            "tradingsymbol": t.tradingsymbol,
                            "instrument_token": t.instrument_token,
                            "exchange": t.exchange,
                            "instrument_type": t.instrument_type,
                            "quantity": t.quantity,
                            "entry_price": float(t.entry_price or 0),
                            "last_price": float(t.last_price) if t.last_price else None,
                            "unrealized_pnl": float(t.unrealized_pnl or 0),
                            "realized_pnl": float(t.realized_pnl or 0),
                            "pnl_pct": float(t.pnl_pct or 0),
                            "status": t.status,
                            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                        }
                        for t in trades
                    ]
                })
            
            return result
    
    def create_strategy_with_trades(
        self,
        name: str,
        trades_data: List[Dict[str, Any]],
        portfolio_id: Optional[str] = None,
        label: Optional[str] = None,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> str:
        """Create a new strategy with trades from position data."""
        import uuid
        
        with self._get_session() as session:
            # Create strategy
            strategy = Strategy(
                id=str(uuid.uuid4()),
                portfolio_id=portfolio_id,
                name=name,
                label=label,
                status="OPEN",
                source="MANUAL",
                notes=notes,
                tags=tags,
                created_at=datetime.now()
            )
            session.add(strategy)
            
            # Create trades
            for trade_data in trades_data:
                trade = StrategyTrade(
                    id=str(uuid.uuid4()),
                    strategy_id=strategy.id,
                    tradingsymbol=trade_data.get("tradingsymbol", ""),
                    instrument_token=trade_data.get("instrument_token", 0),
                    exchange=trade_data.get("exchange", "NFO"),
                    instrument_type=trade_data.get("instrument_type"),
                    lot_size=trade_data.get("lot_size", 1),
                    quantity=trade_data.get("quantity", 0),
                    entry_price=trade_data.get("average_price", 0),
                    last_price=trade_data.get("last_price"),
                    unrealized_pnl=trade_data.get("pnl", 0),
                    status="OPEN",
                    source="LIVE",
                    entry_time=datetime.now()
                )
                session.add(trade)
            
            session.commit()
            logger.info(f"Created strategy: {strategy.id} - {name} with {len(trades_data)} trades")
            return strategy.id
    
    def delete_strategy(self, strategy_id: str) -> bool:
        """Delete a strategy and its trades."""
        with self._get_session() as session:
            strategy = session.query(Strategy).filter_by(id=strategy_id).first()
            if strategy:
                session.delete(strategy)
                session.commit()
                logger.info(f"Deleted strategy: {strategy_id}")
                return True
            return False
