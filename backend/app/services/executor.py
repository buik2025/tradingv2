"""Executor Agent - Order Execution for Trading System v2.0"""

from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
from loguru import logger

from .base_agent import BaseAgent
from ..core.kite_client import KiteClient
from ..config.settings import Settings
from ..config.constants import (
    NFO, BUY, SELL, ORDER_TYPE_LIMIT, ORDER_TYPE_MARKET,
    PRODUCT_NRML, PRODUCT_MIS,
    INTRADAY_EXIT_HOUR, INTRADAY_EXIT_MINUTE,
    EXIT_PROFIT_TARGET, EXIT_STOP_LOSS, EXIT_TIME_BASED, EXIT_EOD,
    EXIT_REGIME_CHANGE, EXIT_CIRCUIT_BREAKER
)
from ..models.trade import TradeSignal, TradeLeg
from ..models.order import OrderTicket, ExecutionResult, ExitOrder, OrderStatus, TransactionType, OrderType, ProductType
from ..models.position import Position, PositionStatus
from ..models.regime import RegimeType
from ..database.repository import Repository
from ..database.models import BrokerPosition


class Executor(BaseAgent):
    """
    Order execution agent.
    
    Responsibilities:
    - Execute approved trade signals
    - Place multi-leg orders
    - Monitor order fills
    - Track positions
    - Execute exits (profit, stop, time-based)
    - Emergency flatten functionality
    """
    
    def __init__(self, kite: KiteClient, config: Settings):
        super().__init__(kite, config, name="Executor")
        self._pending_orders: Dict[str, OrderTicket] = {}
        self._positions: Dict[str, Position] = {}
        self.repository = Repository()
        
        # Load paper positions if in paper mode
        if self.kite.paper_mode:
            self._load_positions()
    
    def process(self, signal: TradeSignal) -> ExecutionResult:
        """
        Execute a trade signal.
        
        Args:
            signal: Approved trade signal from Treasury
            
        Returns:
            ExecutionResult with order details
        """
        self.logger.info(f"Executing signal: {signal.structure.value} on {signal.instrument}")
        
        orders = []
        failed_legs = []
        
        # Place orders for each leg
        for leg in signal.legs:
            order = self._create_order_ticket(signal, leg)
            
            try:
                order_id = self._place_order(order)
                order.broker_order_id = order_id
                order.status = OrderStatus.OPEN
                order.submitted_at = datetime.now()
                orders.append(order)
                self._pending_orders[order.id] = order
                
            except Exception as e:
                self.logger.error(f"Failed to place order for {leg.tradingsymbol}: {e}")
                order.status = OrderStatus.REJECTED
                failed_legs.append(leg.leg_id)
                orders.append(order)
        
        # Check if all legs executed
        success = len(failed_legs) == 0
        
        if success:
            # Wait for fills and create position
            self._wait_for_fills(orders)
            position = self._create_position(signal, orders)
            if position:
                self._positions[position.id] = position
                if self.kite.paper_mode:
                    self._persist_paper_position(position)
        else:
            # Rollback successful orders if partial failure
            self._rollback_orders([o for o in orders if o.status == OrderStatus.OPEN])
        
        # Calculate totals
        total_value = sum(
            o.average_price * o.filled_quantity * (1 if o.transaction_type == TransactionType.BUY else -1)
            for o in orders if o.is_complete
        )
        
        result = ExecutionResult(
            signal_id=signal.id,
            success=success,
            partial=len(failed_legs) > 0 and len(failed_legs) < len(signal.legs),
            orders=orders,
            total_filled_quantity=sum(o.filled_quantity for o in orders),
            total_value=total_value,
            net_premium=-total_value,  # Negative value = credit received
            failed_legs=failed_legs,
            position_id=position.id if success and position else None
        )
        
        result.calculate_costs()
        
        self.logger.info(
            f"Execution {'SUCCESS' if success else 'FAILED'}: "
            f"filled={result.total_filled_quantity}, value={result.total_value:.2f}"
        )
        
        return result
    
    def _create_order_ticket(self, signal: TradeSignal, leg: TradeLeg) -> OrderTicket:
        """Create order ticket for a leg."""
        # Determine transaction type
        if leg.is_long:
            transaction_type = TransactionType.BUY
        else:
            transaction_type = TransactionType.SELL
        
        # Determine product type
        product = ProductType.MIS if signal.product == "MIS" else ProductType.NRML
        
        return OrderTicket(
            signal_id=signal.id,
            leg_id=leg.leg_id,
            tradingsymbol=leg.tradingsymbol,
            exchange=leg.exchange,
            transaction_type=transaction_type,
            quantity=leg.quantity,
            order_type=OrderType.LIMIT,
            product=product,
            price=leg.entry_price,
            tag=f"TV2_{signal.structure.value[:3]}"
        )
    
    def _place_order(self, order: OrderTicket) -> str:
        """Place order with broker."""
        return self.kite.place_order(
            tradingsymbol=order.tradingsymbol,
            exchange=order.exchange,
            transaction_type=order.transaction_type.value,
            quantity=order.quantity,
            order_type=order.order_type.value,
            product=order.product.value,
            price=order.price,
            tag=order.tag
        )
    
    def _wait_for_fills(self, orders: List[OrderTicket], timeout_seconds: int = 30) -> None:
        """Wait for orders to fill."""
        import time as time_module
        
        start = datetime.now()
        pending = [o for o in orders if o.status == OrderStatus.OPEN]
        
        while pending and (datetime.now() - start).seconds < timeout_seconds:
            for order in pending:
                if order.broker_order_id:
                    history = self.kite.get_order_history(order.broker_order_id)
                    if history:
                        latest = history[-1]
                        status = latest.get("status", "")
                        
                        if status == "COMPLETE":
                            order.status = OrderStatus.COMPLETE
                            order.filled_quantity = latest.get("filled_quantity", order.quantity)
                            order.average_price = latest.get("average_price", order.price)
                            order.filled_at = datetime.now()
                        elif status in ["CANCELLED", "REJECTED"]:
                            order.status = OrderStatus(status)
            
            pending = [o for o in orders if o.status == OrderStatus.OPEN]
            if pending:
                time_module.sleep(1)
    
    def _rollback_orders(self, orders: List[OrderTicket]) -> None:
        """Cancel open orders on failure."""
        for order in orders:
            if order.broker_order_id and order.status == OrderStatus.OPEN:
                try:
                    self.kite.cancel_order(order.broker_order_id)
                    order.status = OrderStatus.CANCELLED
                    self.logger.info(f"Cancelled order: {order.broker_order_id}")
                except Exception as e:
                    self.logger.error(f"Failed to cancel order {order.broker_order_id}: {e}")
    
    def _create_position(self, signal: TradeSignal, orders: List[OrderTicket]) -> Optional[Position]:
        """Create position from executed orders."""
        # Update leg prices with actual fills
        legs = []
        for leg in signal.legs:
            order = next((o for o in orders if o.leg_id == leg.leg_id), None)
            if order and order.is_complete:
                leg.entry_price = order.average_price
                legs.append(leg)
        
        if len(legs) != len(signal.legs):
            return None
        
        # Calculate entry price (net premium)
        entry_price = sum(
            leg.entry_price * (-1 if leg.is_short else 1)
            for leg in legs
        )
        
        from datetime import date
        days_to_expiry = (signal.legs[0].expiry - date.today()).days if signal.legs[0].expiry else 0
        
        return Position(
            signal_id=signal.id,
            strategy_type=signal.structure,
            instrument=signal.instrument,
            instrument_token=signal.legs[0].instrument_token,
            legs=legs,
            entry_price=entry_price,
            entry_margin=signal.approved_margin,
            target_pnl=signal.target_pnl,
            stop_loss=signal.stop_loss,
            max_loss=abs(signal.stop_loss),
            expiry=signal.legs[0].expiry,
            days_to_expiry=days_to_expiry,
            exit_dte=signal.exit_dte,
            regime_at_entry=signal.structure.value,
            is_intraday=signal.product == "MIS"
        )
    
    def monitor_positions(
        self,
        current_prices: Dict[int, float],
        current_regime: Optional[RegimeType] = None
    ) -> List[ExitOrder]:
        """
        Monitor positions and generate exit orders.
        
        Args:
            current_prices: Dict of token -> current price
            current_regime: Current market regime
            
        Returns:
            List of exit orders to execute
        """
        exit_orders = []
        now = datetime.now()
        
        for pos_id, position in self._positions.items():
            if position.status != PositionStatus.OPEN:
                continue
            
            # Update position P&L
            position.update_pnl(current_prices)
            
            # Check EOD exit for intraday
            if position.is_intraday:
                if now.time() >= time(INTRADAY_EXIT_HOUR, INTRADAY_EXIT_MINUTE):
                    exit_orders.append(ExitOrder(
                        position_id=pos_id,
                        exit_reason=EXIT_EOD,
                        exit_type="EOD"
                    ))
                    continue
            
            # Check profit target
            if position.should_exit_profit():
                exit_orders.append(ExitOrder(
                    position_id=pos_id,
                    exit_reason=EXIT_PROFIT_TARGET,
                    exit_type="PROFIT_TARGET"
                ))
                continue
            
            # Check stop loss
            if position.should_exit_stop():
                exit_orders.append(ExitOrder(
                    position_id=pos_id,
                    exit_reason=EXIT_STOP_LOSS,
                    exit_type="STOP_LOSS",
                    urgency="HIGH"
                ))
                continue
            
            # Check time-based exit (DTE)
            from datetime import date
            current_dte = (position.expiry - date.today()).days if position.expiry else 999
            if position.should_exit_time(current_dte):
                exit_orders.append(ExitOrder(
                    position_id=pos_id,
                    exit_reason=EXIT_TIME_BASED,
                    exit_type="TIME_BASED"
                ))
                continue
            
            # Check regime change
            if current_regime == RegimeType.CHAOS:
                exit_orders.append(ExitOrder(
                    position_id=pos_id,
                    exit_reason=EXIT_REGIME_CHANGE,
                    exit_type="REGIME_CHANGE",
                    urgency="HIGH"
                ))
        
        return exit_orders
    
    def execute_exit(self, exit_order: ExitOrder) -> ExecutionResult:
        """Execute an exit order."""
        position = self._positions.get(exit_order.position_id)
        if not position:
            return ExecutionResult(
                signal_id="",
                success=False,
                error_message=f"Position {exit_order.position_id} not found"
            )
        
        self.logger.info(f"Executing exit for {position.id}: {exit_order.exit_reason}")
        
        orders = []
        
        # Create closing orders for each leg
        for leg in position.legs:
            # Reverse the transaction type
            if leg.is_long:
                transaction_type = TransactionType.SELL
            else:
                transaction_type = TransactionType.BUY
            
            order = OrderTicket(
                signal_id=position.signal_id,
                leg_id=leg.leg_id,
                tradingsymbol=leg.tradingsymbol,
                exchange=leg.exchange,
                transaction_type=transaction_type,
                quantity=leg.quantity,
                order_type=OrderType.MARKET if exit_order.urgency == "HIGH" else OrderType.LIMIT,
                product=ProductType.MIS if position.is_intraday else ProductType.NRML,
                price=leg.current_price,
                tag=f"TV2_EXIT"
            )
            
            try:
                order_id = self._place_order(order)
                order.broker_order_id = order_id
                order.status = OrderStatus.OPEN
                orders.append(order)
            except Exception as e:
                self.logger.error(f"Failed to place exit order: {e}")
                order.status = OrderStatus.REJECTED
                orders.append(order)
        
        # Wait for fills
        self._wait_for_fills(orders)
        
        # Calculate realized P&L
        exit_value = sum(
            o.average_price * o.filled_quantity * (1 if o.transaction_type == TransactionType.BUY else -1)
            for o in orders if o.is_complete
        )
        
        realized_pnl = position.current_pnl
        
        # Close position
        position.close(exit_value, exit_order.exit_reason)
        
        if self.kite.paper_mode:
             self._persist_paper_position(position)
        
        result = ExecutionResult(
            signal_id=position.signal_id,
            success=all(o.is_complete for o in orders),
            orders=orders,
            total_value=exit_value,
            position_id=position.id
        )
        
        exit_order.success = result.success
        exit_order.realized_pnl = realized_pnl
        exit_order.executed_at = datetime.now()
        exit_order.execution_result = result
        
        self.logger.info(f"Exit completed: P&L={realized_pnl:.2f}")
        
        return result
    
    def flatten_all(self, reason: str = EXIT_CIRCUIT_BREAKER) -> List[ExecutionResult]:
        """Emergency flatten all positions."""
        self.logger.warning(f"FLATTEN ALL: {reason}")
        
        results = []
        
        for pos_id, position in self._positions.items():
            if position.status == PositionStatus.OPEN:
                exit_order = ExitOrder(
                    position_id=pos_id,
                    exit_reason=reason,
                    exit_type="EMERGENCY",
                    order_type=OrderType.MARKET,
                    urgency="EMERGENCY"
                )
                result = self.execute_exit(exit_order)
                results.append(result)
        
        return results
    
    def get_positions(self) -> List[Position]:
        """Get all tracked positions."""
        return list(self._positions.values())
    
    def get_open_positions(self) -> List[Position]:
        """Get open positions only."""
        return [p for p in self._positions.values() if p.status == PositionStatus.OPEN]
    
    def sync_positions(self) -> None:
        """Sync positions with broker."""
        broker_positions = self.kite.get_positions()
        # Implementation would reconcile local positions with broker
        pass

    def _persist_paper_position(self, position: Position) -> None:
        """Persist paper position to database."""
        try:
            for leg in position.legs:
                # Map domain leg to DB BrokerPosition
                # Net quantity logic: positive for long, negative for short
                qty = leg.quantity if leg.is_long else -leg.quantity
                
                # If position closed, qty is 0 (or we assume flattened)
                if position.status != PositionStatus.OPEN:
                    qty = 0
                
                bp = BrokerPosition(
                     id=f"PAPER_{leg.instrument_token}", # Unique ID for paper pos
                     tradingsymbol=leg.tradingsymbol,
                     instrument_token=leg.instrument_token,
                     exchange=leg.exchange,
                     quantity=qty,
                     average_price=leg.entry_price,
                     last_price=leg.current_price,
                     pnl=0, # Calculated dynamically by PortfolioService
                     product="NRML", # Default
                     transaction_type="BUY" if qty > 0 else "SELL",
                     source="PAPER",
                     broker_order_id=f"PAPER_ORD_{leg.instrument_token}"
                )
                self.repository.save_broker_position(bp)
            self.logger.info(f"Persisted paper position {position.id}")
        except Exception as e:
            self.logger.error(f"Failed to persist paper position: {e}")

    def _load_positions(self) -> None:
        """Load paper positions from DB (Best effort)."""
        # Retrieving positions for UI visibility is handled by PortfolioService.
        # Rehydrating Executor state is complex without strategy metadata.
        # For now, we rely on in-memory state for active management during the session.
        pass
