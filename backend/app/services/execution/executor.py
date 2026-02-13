"""Executor Agent - Order Execution for Trading System v2.0"""

from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
from loguru import logger
import uuid

from ..agents import BaseAgent
from ...core.kite_client import KiteClient
from ...core.state_manager import StateManager
from ...config.settings import Settings
from .greek_hedger import GreekHedger, GreekHedgeRecommendation, HedgeType
from ...config.constants import (
    NFO, BUY, SELL, ORDER_TYPE_LIMIT, ORDER_TYPE_MARKET,
    PRODUCT_NRML, PRODUCT_MIS,
    INTRADAY_EXIT_HOUR, INTRADAY_EXIT_MINUTE,
    EXIT_PROFIT_TARGET, EXIT_STOP_LOSS, EXIT_TIME_BASED, EXIT_EOD,
    EXIT_REGIME_CHANGE, EXIT_CIRCUIT_BREAKER
)
from ...config.thresholds import SLIPPAGE_ALERT_THRESHOLD, SLIPPAGE_AUTO_CORRECT_THRESHOLD
from ...models.trade import TradeSignal, TradeLeg
from ...models.order import OrderTicket, ExecutionResult, ExitOrder, OrderStatus, TransactionType, OrderType, ProductType
from ...models.position import Position, PositionStatus
from ...models.regime import RegimeType
from ...database import Repository, BrokerPosition
from ...database.models import Strategy, StrategyPosition, Portfolio


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
    
    def __init__(
        self,
        kite: KiteClient,
        config: Settings,
        state_manager: Optional[StateManager] = None,
        greek_hedger: Optional[GreekHedger] = None,
        treasury: Optional[object] = None  # Avoid circular import
    ):
        super().__init__(kite, config, name="Executor")
        self._pending_orders: Dict[str, OrderTicket] = {}
        self._positions: Dict[str, Position] = {}
        self.repository = Repository()
        self.state_manager = state_manager or StateManager()
        
        # Greek hedger for portfolio risk management
        self.greek_hedger = greek_hedger or GreekHedger(equity=10_000_000)
        
        # Treasury reference for recording trade results
        self._treasury = treasury
        
        # Slippage tracking (Section 8)
        self._slippage_alerts: List[Dict] = []
        
        # Track existing structures to prevent duplicates
        self._existing_structures: set = set()
        
        # Always load existing paper positions from DB to prevent duplicates
        # This is needed regardless of paper_mode since we track all paper strategies
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
                # Guard: Don't persist positions with zero entry price (API quotes unavailable)
                if position.entry_price == 0:
                    self.logger.warning(f"Skipping position with zero entry price - API quotes unavailable")
                    return ExecutionResult(
                        signal_id=signal.id,
                        success=False,
                        orders=orders,
                        error="Zero entry price - API quotes unavailable"
                    )
                self._positions[position.id] = position
                # Persist position to database (both paper and live)
                self._persist_position(position)
                if self.kite.paper_mode:
                    # Update paper margin tracking
                    self._update_paper_margin(signal.approved_margin, add=True)
                    # Track this structure as having an open position
                    if hasattr(self, '_existing_structures'):
                        self._existing_structures.add(position.strategy_type.value)
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
        """Wait for orders to fill and track slippage."""
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
                            
                            # Track slippage (Section 8)
                            self._track_slippage(order)
                            
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
        
        # Get dynamic exit targets from signal (Section 4 - rulebook)
        exit_target_low = getattr(signal, 'exit_target_low', signal.target_pnl * 0.8)
        exit_target_high = getattr(signal, 'exit_target_high', signal.target_pnl * 1.2)
        trailing_mode = getattr(signal, 'trailing_mode', 'none')
        
        position = Position(
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
            is_intraday=signal.product == "MIS",
            # Section 4: Dynamic exit targeting
            exit_target_low=exit_target_low,
            exit_target_high=exit_target_high,
            current_target=signal.target_pnl,
            # Section 11: Trailing profit setup
            trailing_enabled=getattr(signal, 'enable_trailing', True),
            trailing_mode=trailing_mode,
            trailing_threshold=getattr(signal, 'trailing_profit_threshold', 0.5)
        )
        
        return position
    
    def monitor_positions(
        self,
        current_prices: Dict[int, float],
        current_regime: Optional[RegimeType] = None,
        check_greeks: bool = True
    ) -> List[ExitOrder]:
        """
        Monitor positions and generate exit orders.
        
        Includes Greek hedging checks per Section 5/6 of rulebook:
        - Delta breach (±12%) triggers hedge recommendation
        - Vega breach (±35%) triggers hedge recommendation
        - Gamma breach (-0.15%) triggers risk reduction
        
        Args:
            current_prices: Dict of token -> current price
            current_regime: Current market regime
            check_greeks: Whether to check portfolio Greeks
            
        Returns:
            List of exit orders to execute
        """
        exit_orders = []
        now = datetime.now()
        
        # Update portfolio Greeks and check for hedging needs
        if check_greeks:
            self._update_portfolio_greeks()
            hedge_recommendations = self._check_greek_hedging()
        
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
            
            # Check for trailing profit (Section 11 - rulebook)
            if position.trailing_enabled and position.trailing_mode != "none":
                # Get metrics for trailing calculation
                atr = getattr(position, '_cached_atr', None)
                bbw_ratio = getattr(position, '_cached_bbw_ratio', None)
                
                if position.update_trailing_stop(position.current_price, atr, bbw_ratio):
                    exit_orders.append(ExitOrder(
                        position_id=pos_id,
                        exit_reason="TRAILING_STOP",
                        exit_type="TRAILING_STOP"
                    ))
                    continue
            
            # Check profit target (dynamic from Section 4)
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
            self._persist_position(position)  # Update position status in DB
            # Release margin when position is closed
            self._update_paper_margin(position.entry_margin, add=False)
        
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
        
        # Record trade result for consecutive win/loss tracking (Section 6/7)
        streak_info = self.state_manager.record_trade_result(realized_pnl, position.id)
        if streak_info.get("actions"):
            self.logger.info(f"Trade result recorded: {streak_info}")
        
        # Record to Treasury's circuit breaker for loss limit tracking
        is_win = realized_pnl > 0
        self._record_trade_to_treasury(pnl=realized_pnl, is_win=is_win)
        
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
    
    def _update_portfolio_greeks(self) -> None:
        """
        Update GreekHedger with current portfolio Greeks from open positions.
        
        Aggregates delta, vega, gamma, theta across all open positions.
        """
        total_delta = 0.0
        total_vega = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        
        for position in self._positions.values():
            if position.status != PositionStatus.OPEN:
                continue
            
            # Get Greeks from position legs
            for leg in position.legs:
                delta = getattr(leg, 'delta', 0) or 0
                vega = getattr(leg, 'vega', 0) or 0
                gamma = getattr(leg, 'gamma', 0) or 0
                theta = getattr(leg, 'theta', 0) or 0
                
                # Adjust for quantity (negative for short positions)
                qty_mult = leg.quantity if leg.is_long else -leg.quantity
                total_delta += delta * qty_mult
                total_vega += vega * qty_mult
                total_gamma += gamma * qty_mult
                total_theta += theta * qty_mult
        
        # Update the hedger
        self.greek_hedger.update_portfolio_greeks(
            delta=total_delta,
            vega=total_vega,
            gamma=total_gamma,
            theta=total_theta
        )
    
    def _check_greek_hedging(self) -> List[GreekHedgeRecommendation]:
        """
        Check if portfolio Greeks require hedging.
        
        Returns:
            List of hedge recommendations if Greeks are breached
        """
        recommendations = []
        
        if self.greek_hedger.should_rebalance():
            recommendations = self.greek_hedger.get_hedging_recommendations()
            
            for rec in recommendations:
                self.logger.warning(
                    f"GREEK HEDGE NEEDED: {rec.hedge_type.value} - {rec.reason} "
                    f"(current: {rec.current_value:.2%}, threshold: {rec.threshold:.2%})"
                )
        
        # Check short Greek caps (Section 5)
        cap_breaches = self.greek_hedger.check_short_greek_caps()
        if cap_breaches.get("vega_cap_breached") or cap_breaches.get("gamma_cap_breached"):
            self.logger.warning(f"SHORT GREEK CAP BREACHED: {cap_breaches}")
        
        return recommendations
    
    def get_greek_status(self) -> Dict:
        """Get current portfolio Greek status from hedger."""
        return self.greek_hedger.get_status()
    
    def set_treasury(self, treasury: object) -> None:
        """Set treasury reference for trade result recording."""
        self._treasury = treasury
    
    def _record_trade_to_treasury(self, pnl: float, is_win: bool) -> None:
        """Record trade result to Treasury's circuit breaker."""
        if self._treasury and hasattr(self._treasury, 'record_trade_result'):
            self._treasury.record_trade_result(pnl=pnl, is_win=is_win)

    def _persist_position(self, position: Position) -> None:
        """
        Persist position to database with proper Strategy and Portfolio linkage.
        
        Works for both PAPER and LIVE modes. The source field distinguishes them.
        
        Creates:
        1. BrokerPosition records for each leg
        2. Strategy record to group the legs
        3. StrategyPosition links between Strategy and BrokerPositions
        4. Default Portfolio (Paper Trading or Live Trading) if it doesn't exist
        """
        source = "PAPER" if self.kite.paper_mode else "LIVE"
        portfolio_name = "Paper Trading" if self.kite.paper_mode else "Live Trading"
        
        try:
            with self.repository._get_session() as session:
                # CRITICAL: Check for existing strategy with same label BEFORE creating
                existing_strategy = session.query(Strategy).filter(
                    Strategy.source == source,
                    Strategy.status == "OPEN",
                    Strategy.label == position.strategy_type.value
                ).first()
                
                if existing_strategy:
                    self.logger.warning(f"Strategy {position.strategy_type.value} already exists (id={existing_strategy.id}), skipping creation")
                    return
                
                # 1. Get or create default Portfolio for this mode
                portfolio = session.query(Portfolio).filter_by(
                    name=portfolio_name
                ).first()
                
                if not portfolio:
                    portfolio = Portfolio(
                        id=str(uuid.uuid4()),
                        name=portfolio_name,
                        description=f"Auto-generated portfolio for {source.lower()} trading positions",
                        is_active=True
                    )
                    session.add(portfolio)
                    session.flush()
                    self.logger.info(f"Created {portfolio_name} portfolio: {portfolio.id}")
                
                # 2. Create Strategy record
                strategy_name = f"{position.strategy_type.value} - {position.instrument}"
                strategy = Strategy(
                    id=str(uuid.uuid4()),
                    portfolio_id=portfolio.id,
                    name=strategy_name,
                    label=position.strategy_type.value,
                    primary_instrument=position.instrument,
                    status="OPEN",
                    source=source,
                    notes=f"Auto-created from {source.lower()} trade execution at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    tags=[source.lower(), "auto-generated", position.strategy_type.value.lower()]
                )
                session.add(strategy)
                session.flush()
                self.logger.info(f"Created strategy: {strategy.id} - {strategy_name} ({source})")
                
                # 3. Create BrokerPosition records and link to Strategy
                # Calculate margin per leg (distribute position margin evenly)
                num_legs = len(position.legs)
                margin_per_leg = position.entry_margin / num_legs if num_legs > 0 else 0
                
                broker_position_ids = []
                for leg in position.legs:
                    qty = leg.quantity if leg.is_long else -leg.quantity
                    
                    if position.status != PositionStatus.OPEN:
                        qty = 0
                    
                    # Use different ID prefix for paper vs live
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
                    bp_id = f"{source}_{timestamp}_{leg.instrument_token}"
                    
                    bp = BrokerPosition(
                        id=bp_id,
                        tradingsymbol=leg.tradingsymbol,
                        instrument_token=leg.instrument_token,
                        exchange=leg.exchange,
                        quantity=qty,
                        average_price=leg.entry_price,
                        last_price=leg.current_price,
                        pnl=0,
                        product="NRML",
                        transaction_type="BUY" if qty > 0 else "SELL",
                        source=source,
                        broker_order_id=leg.broker_order_id if hasattr(leg, 'broker_order_id') else f"{source}_ORD_{leg.instrument_token}",
                        margin_used=margin_per_leg
                    )
                    session.add(bp)
                    broker_position_ids.append(bp_id)
                
                session.flush()
                
                # 4. Create StrategyPosition links
                for bp_id in broker_position_ids:
                    sp = StrategyPosition(
                        id=str(uuid.uuid4()),
                        strategy_id=strategy.id,
                        position_id=bp_id
                    )
                    session.add(sp)
                
                session.commit()
                self.logger.info(f"Persisted {source} position {position.id} with strategy {strategy.id}")
                
                # Update existing structures tracking
                self._existing_structures.add(position.strategy_type.value)
                
        except Exception as e:
            self.logger.error(f"Failed to persist {source} position: {e}")

    def _load_positions(self) -> None:
        """Load existing paper positions from database to track open structures."""
        try:
            from ..database.models import Strategy, get_session
            
            session = get_session()
            
            # Get all OPEN paper strategies
            open_strategies = session.query(Strategy).filter(
                Strategy.source == "PAPER",
                Strategy.status == "OPEN"
            ).all()
            
            # Track existing structures to prevent duplicates
            self._existing_structures = set()
            for strategy in open_strategies:
                if strategy.label:
                    self._existing_structures.add(strategy.label)
                    self.logger.info(f"Tracking existing structure: {strategy.label} (strategy_id={strategy.id})")
            
            self.logger.info(f"Loaded {len(open_strategies)} open paper strategies, structures: {self._existing_structures}")
            
            session.close()
            
        except Exception as e:
            self.logger.error(f"Failed to load paper positions: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            self._existing_structures = set()

    def has_open_position_for_structure(self, structure_value: str) -> bool:
        """Check if there's already an open position for this structure type."""
        # Always refresh from DB FIRST to ensure we have latest state
        self._load_positions()
        
        # Check loaded structures from DB (highest priority)
        if hasattr(self, '_existing_structures') and structure_value in self._existing_structures:
            self.logger.info(f"Found existing structure {structure_value} in DB")
            return True
        
        # Check in-memory positions as fallback
        for pos in self._positions.values():
            if pos.strategy_type.value == structure_value:
                self.logger.info(f"Found existing structure {structure_value} in memory")
                return True
        
        self.logger.debug(f"No existing position for structure {structure_value}")
        return False

    def _update_paper_margin(self, margin_amount: float, add: bool = True) -> None:
        """
        Update paper trading margin tracking.
        
        Args:
            margin_amount: Amount of margin to add or release
            add: True to add margin (new position), False to release (closed position)
        """
        current_used = self.state_manager.get("paper_used_margin", 0)
        if add:
            new_used = current_used + margin_amount
        else:
            new_used = max(0, current_used - margin_amount)
        
        self.state_manager.set("paper_used_margin", new_used)
        self.logger.debug(f"Paper margin updated: {current_used:.0f} -> {new_used:.0f} ({'added' if add else 'released'} {margin_amount:.0f})")
    
    def _track_slippage(self, order: OrderTicket) -> Dict:
        """
        Track slippage for a filled order.
        
        Section 8: >0.5% slippage → alert/auto-correct
        
        Args:
            order: Filled order ticket
            
        Returns:
            Dict with slippage info and alert status
        """
        if order.price == 0 or order.average_price == 0:
            return {"slippage_pct": 0, "alert": False}
        
        slippage_result = self.state_manager.record_slippage(
            expected_price=order.price,
            actual_price=order.average_price,
            tradingsymbol=order.tradingsymbol,
            order_id=order.broker_order_id
        )
        
        if slippage_result.get("alert"):
            self._slippage_alerts.append({
                "order_id": order.broker_order_id,
                "tradingsymbol": order.tradingsymbol,
                "expected": order.price,
                "actual": order.average_price,
                "slippage_pct": slippage_result["slippage_pct"],
                "alert_level": slippage_result["alert_level"],
                "timestamp": datetime.now()
            })
        
        return slippage_result
    
    def get_slippage_alerts(self) -> List[Dict]:
        """Get recent slippage alerts."""
        return self._slippage_alerts
    
    def get_slippage_summary(self) -> Dict:
        """Get slippage summary for the day."""
        return {
            "total_slippage_today": self.state_manager.get("total_slippage_today", 0),
            "alert_count": len(self._slippage_alerts),
            "alerts": self._slippage_alerts[-10:]  # Last 10 alerts
        }
