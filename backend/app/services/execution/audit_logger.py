"""Execution Audit Logger - Detailed trade audit trail for Trading System v2.0

Provides comprehensive logging of all trade decisions, order placements, fills,
and position lifecycle events for compliance and debugging.
"""

from datetime import datetime
from typing import Optional, Dict, List, Any
from enum import Enum
from dataclasses import dataclass, field, asdict
from loguru import logger
import json
import uuid


class AuditEventType(str, Enum):
    """Types of audit events."""
    # Signal events
    SIGNAL_GENERATED = "signal_generated"
    SIGNAL_APPROVED = "signal_approved"
    SIGNAL_REJECTED = "signal_rejected"
    
    # Order events
    ORDER_CREATED = "order_created"
    ORDER_PLACED = "order_placed"
    ORDER_MODIFIED = "order_modified"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_FILLED = "order_filled"
    ORDER_PARTIAL_FILL = "order_partial_fill"
    ORDER_REJECTED = "order_rejected"
    ORDER_TIMEOUT = "order_timeout"
    
    # Position events
    POSITION_OPENED = "position_opened"
    POSITION_UPDATED = "position_updated"
    POSITION_CLOSED = "position_closed"
    POSITION_ROLLED = "position_rolled"
    
    # Exit events
    EXIT_TRIGGERED = "exit_triggered"
    EXIT_PROFIT_TARGET = "exit_profit_target"
    EXIT_STOP_LOSS = "exit_stop_loss"
    EXIT_TRAILING_STOP = "exit_trailing_stop"
    EXIT_TIME_BASED = "exit_time_based"
    EXIT_EOD = "exit_eod"
    EXIT_REGIME_CHANGE = "exit_regime_change"
    EXIT_CIRCUIT_BREAKER = "exit_circuit_breaker"
    EXIT_MANUAL = "exit_manual"
    
    # Risk events
    RISK_CHECK_PASSED = "risk_check_passed"
    RISK_CHECK_FAILED = "risk_check_failed"
    CIRCUIT_BREAKER_TRIGGERED = "circuit_breaker_triggered"
    GREEK_LIMIT_BREACH = "greek_limit_breach"
    MARGIN_WARNING = "margin_warning"
    
    # System events
    SLIPPAGE_ALERT = "slippage_alert"
    EXECUTION_ERROR = "execution_error"
    ROLLBACK_INITIATED = "rollback_initiated"
    HEDGE_RECOMMENDED = "hedge_recommended"


@dataclass
class AuditEntry:
    """Single audit log entry."""
    event_id: str
    timestamp: datetime
    event_type: AuditEventType
    
    # Context
    correlation_id: str  # Links related events (e.g., signal -> order -> fill)
    agent: str  # Which agent generated this event
    
    # Trade context
    trade_id: Optional[str] = None
    position_id: Optional[str] = None
    order_id: Optional[str] = None
    
    # Instrument
    instrument: Optional[str] = None
    instrument_token: Optional[int] = None
    
    # Details
    details: Dict[str, Any] = field(default_factory=dict)
    
    # Regime context
    regime: Optional[str] = None
    regime_confidence: Optional[float] = None
    
    # Pricing
    price: Optional[float] = None
    quantity: Optional[int] = None
    
    # P&L
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    
    # Status
    success: bool = True
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        d['event_type'] = self.event_type.value
        return d
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)


class ExecutionAuditLogger:
    """
    Centralized audit logger for all execution events.
    
    Features:
    - Correlation IDs to link related events
    - Structured logging for easy querying
    - In-memory buffer with periodic flush to database
    - Log file backup for compliance
    """
    
    def __init__(
        self,
        buffer_size: int = 100,
        log_to_file: bool = True,
        log_file_path: str = "logs/execution_audit.jsonl"
    ):
        self.buffer_size = buffer_size
        self.log_to_file = log_to_file
        self.log_file_path = log_file_path
        
        self._buffer: List[AuditEntry] = []
        self._correlation_map: Dict[str, str] = {}  # trade_id -> correlation_id
        
        logger.info(f"ExecutionAuditLogger initialized: buffer_size={buffer_size}")
    
    def _generate_event_id(self) -> str:
        """Generate unique event ID."""
        return f"evt_{uuid.uuid4().hex[:12]}"
    
    def _generate_correlation_id(self) -> str:
        """Generate unique correlation ID."""
        return f"corr_{uuid.uuid4().hex[:12]}"
    
    def get_or_create_correlation_id(self, trade_id: Optional[str] = None) -> str:
        """Get existing correlation ID or create new one."""
        if trade_id and trade_id in self._correlation_map:
            return self._correlation_map[trade_id]
        
        corr_id = self._generate_correlation_id()
        if trade_id:
            self._correlation_map[trade_id] = corr_id
        return corr_id
    
    def log(
        self,
        event_type: AuditEventType,
        agent: str,
        correlation_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        position_id: Optional[str] = None,
        order_id: Optional[str] = None,
        instrument: Optional[str] = None,
        instrument_token: Optional[int] = None,
        details: Optional[Dict] = None,
        regime: Optional[str] = None,
        regime_confidence: Optional[float] = None,
        price: Optional[float] = None,
        quantity: Optional[int] = None,
        pnl: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> AuditEntry:
        """
        Log an audit event.
        
        Args:
            event_type: Type of event
            agent: Agent that generated the event
            correlation_id: ID to link related events
            trade_id: Associated trade ID
            position_id: Associated position ID
            order_id: Associated order ID
            instrument: Instrument symbol
            instrument_token: Instrument token
            details: Additional event details
            regime: Current market regime
            regime_confidence: Regime confidence score
            price: Relevant price
            quantity: Relevant quantity
            pnl: P&L if applicable
            pnl_pct: P&L percentage if applicable
            success: Whether event was successful
            error_message: Error message if failed
            
        Returns:
            AuditEntry that was logged
        """
        # Get or create correlation ID
        if not correlation_id:
            correlation_id = self.get_or_create_correlation_id(trade_id)
        
        entry = AuditEntry(
            event_id=self._generate_event_id(),
            timestamp=datetime.now(),
            event_type=event_type,
            correlation_id=correlation_id,
            agent=agent,
            trade_id=trade_id,
            position_id=position_id,
            order_id=order_id,
            instrument=instrument,
            instrument_token=instrument_token,
            details=details or {},
            regime=regime,
            regime_confidence=regime_confidence,
            price=price,
            quantity=quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            success=success,
            error_message=error_message
        )
        
        # Add to buffer
        self._buffer.append(entry)
        
        # Log to loguru
        log_msg = (
            f"[{entry.event_type.value}] {agent} | "
            f"corr={correlation_id[:12]} | "
            f"trade={trade_id or 'N/A'} | "
            f"order={order_id or 'N/A'}"
        )
        if instrument:
            log_msg += f" | {instrument}"
        if price:
            log_msg += f" @ {price}"
        if pnl is not None:
            log_msg += f" | P&L={pnl:.2f}"
        if not success:
            log_msg += f" | ERROR: {error_message}"
        
        if success:
            logger.info(log_msg)
        else:
            logger.error(log_msg)
        
        # Write to file if enabled
        if self.log_to_file:
            self._write_to_file(entry)
        
        # Flush buffer if full
        if len(self._buffer) >= self.buffer_size:
            self.flush_to_database()
        
        return entry
    
    def _write_to_file(self, entry: AuditEntry) -> None:
        """Write entry to JSONL file."""
        try:
            import os
            os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)
            with open(self.log_file_path, 'a') as f:
                f.write(entry.to_json() + '\n')
        except Exception as e:
            logger.warning(f"Failed to write audit log to file: {e}")
    
    def flush_to_database(self) -> int:
        """
        Flush buffer to database.
        
        Returns:
            Number of entries flushed
        """
        if not self._buffer:
            return 0
        
        count = len(self._buffer)
        
        try:
            from ...database.models import ExecutionAuditLog, SessionLocal
            
            session = SessionLocal()
            try:
                for entry in self._buffer:
                    db_entry = ExecutionAuditLog(
                        event_id=entry.event_id,
                        timestamp=entry.timestamp,
                        event_type=entry.event_type.value,
                        correlation_id=entry.correlation_id,
                        agent=entry.agent,
                        trade_id=entry.trade_id,
                        position_id=entry.position_id,
                        order_id=entry.order_id,
                        instrument=entry.instrument,
                        instrument_token=entry.instrument_token,
                        details=entry.details,
                        regime=entry.regime,
                        regime_confidence=entry.regime_confidence,
                        price=entry.price,
                        quantity=entry.quantity,
                        pnl=entry.pnl,
                        pnl_pct=entry.pnl_pct,
                        success=entry.success,
                        error_message=entry.error_message
                    )
                    session.add(db_entry)
                session.commit()
                logger.debug(f"Flushed {count} audit entries to database")
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to flush audit log to database: {e}")
            finally:
                session.close()
        except ImportError:
            # Database model not available, skip
            logger.debug("ExecutionAuditLog model not available, skipping DB flush")
        
        self._buffer.clear()
        return count
    
    # Convenience methods for common events
    
    def log_signal_generated(
        self,
        trade_id: str,
        instrument: str,
        structure: str,
        regime: str,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log signal generation."""
        return self.log(
            event_type=AuditEventType.SIGNAL_GENERATED,
            agent="Strategist",
            trade_id=trade_id,
            instrument=instrument,
            regime=regime,
            details={"structure": structure, **(details or {})}
        )
    
    def log_signal_approved(
        self,
        trade_id: str,
        instrument: str,
        size_multiplier: float,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log signal approval by Treasury."""
        return self.log(
            event_type=AuditEventType.SIGNAL_APPROVED,
            agent="Treasury",
            trade_id=trade_id,
            instrument=instrument,
            details={"size_multiplier": size_multiplier, **(details or {})}
        )
    
    def log_signal_rejected(
        self,
        trade_id: str,
        instrument: str,
        reason: str,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log signal rejection by Treasury."""
        return self.log(
            event_type=AuditEventType.SIGNAL_REJECTED,
            agent="Treasury",
            trade_id=trade_id,
            instrument=instrument,
            success=False,
            error_message=reason,
            details=details
        )
    
    def log_order_placed(
        self,
        trade_id: str,
        order_id: str,
        instrument: str,
        price: float,
        quantity: int,
        order_type: str,
        transaction_type: str,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log order placement."""
        return self.log(
            event_type=AuditEventType.ORDER_PLACED,
            agent="Executor",
            trade_id=trade_id,
            order_id=order_id,
            instrument=instrument,
            price=price,
            quantity=quantity,
            details={
                "order_type": order_type,
                "transaction_type": transaction_type,
                **(details or {})
            }
        )
    
    def log_order_filled(
        self,
        trade_id: str,
        order_id: str,
        instrument: str,
        fill_price: float,
        quantity: int,
        slippage: Optional[float] = None,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log order fill."""
        return self.log(
            event_type=AuditEventType.ORDER_FILLED,
            agent="Executor",
            trade_id=trade_id,
            order_id=order_id,
            instrument=instrument,
            price=fill_price,
            quantity=quantity,
            details={"slippage": slippage, **(details or {})}
        )
    
    def log_position_opened(
        self,
        trade_id: str,
        position_id: str,
        instrument: str,
        entry_price: float,
        quantity: int,
        structure: str,
        regime: str,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log position opening."""
        return self.log(
            event_type=AuditEventType.POSITION_OPENED,
            agent="Executor",
            trade_id=trade_id,
            position_id=position_id,
            instrument=instrument,
            price=entry_price,
            quantity=quantity,
            regime=regime,
            details={"structure": structure, **(details or {})}
        )
    
    def log_position_closed(
        self,
        trade_id: str,
        position_id: str,
        instrument: str,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        pnl_pct: float,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log position closure."""
        return self.log(
            event_type=AuditEventType.POSITION_CLOSED,
            agent="Executor",
            trade_id=trade_id,
            position_id=position_id,
            instrument=instrument,
            price=exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            details={"exit_reason": exit_reason, **(details or {})}
        )
    
    def log_exit_triggered(
        self,
        trade_id: str,
        position_id: str,
        exit_type: AuditEventType,
        trigger_value: float,
        current_value: float,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log exit trigger."""
        return self.log(
            event_type=exit_type,
            agent="Executor",
            trade_id=trade_id,
            position_id=position_id,
            details={
                "trigger_value": trigger_value,
                "current_value": current_value,
                **(details or {})
            }
        )
    
    def log_slippage_alert(
        self,
        trade_id: str,
        order_id: str,
        instrument: str,
        expected_price: float,
        actual_price: float,
        slippage_pct: float,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log slippage alert."""
        return self.log(
            event_type=AuditEventType.SLIPPAGE_ALERT,
            agent="Executor",
            trade_id=trade_id,
            order_id=order_id,
            instrument=instrument,
            price=actual_price,
            success=False,
            error_message=f"Slippage {slippage_pct:.2%} exceeds threshold",
            details={
                "expected_price": expected_price,
                "actual_price": actual_price,
                "slippage_pct": slippage_pct,
                **(details or {})
            }
        )
    
    def log_execution_error(
        self,
        trade_id: str,
        error_message: str,
        order_id: Optional[str] = None,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log execution error."""
        return self.log(
            event_type=AuditEventType.EXECUTION_ERROR,
            agent="Executor",
            trade_id=trade_id,
            order_id=order_id,
            success=False,
            error_message=error_message,
            details=details
        )
    
    def log_circuit_breaker(
        self,
        reason: str,
        current_loss: float,
        limit: float,
        details: Optional[Dict] = None
    ) -> AuditEntry:
        """Log circuit breaker trigger."""
        return self.log(
            event_type=AuditEventType.CIRCUIT_BREAKER_TRIGGERED,
            agent="Treasury",
            success=False,
            error_message=reason,
            details={
                "current_loss": current_loss,
                "limit": limit,
                **(details or {})
            }
        )
    
    def get_trade_history(self, trade_id: str) -> List[AuditEntry]:
        """Get all audit entries for a trade."""
        return [e for e in self._buffer if e.trade_id == trade_id]
    
    def get_recent_entries(self, count: int = 50) -> List[AuditEntry]:
        """Get most recent audit entries."""
        return self._buffer[-count:]
    
    def get_errors(self, since: Optional[datetime] = None) -> List[AuditEntry]:
        """Get all error entries."""
        entries = [e for e in self._buffer if not e.success]
        if since:
            entries = [e for e in entries if e.timestamp >= since]
        return entries


# Global audit logger instance
_audit_logger: Optional[ExecutionAuditLogger] = None


def get_audit_logger() -> ExecutionAuditLogger:
    """Get or create global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = ExecutionAuditLogger()
    return _audit_logger
