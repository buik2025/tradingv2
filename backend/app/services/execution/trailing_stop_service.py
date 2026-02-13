"""
Trailing Stop Service for Strategy-Level P&L Management

This service:
1. Tracks P&L at strategy level (aggregate of all position P&Ls)
2. Activates trailing when P&L >= activation_pct of margin
3. Trails profit by raising stop floor on each step increase
4. Places/modifies SL orders at position level proportionally
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from loguru import logger

from ...core.kite_provider import get_kite_client
from ...core.kite_client import KiteClient
from ...database.models import Strategy, StrategyTrade, get_session
from ..utilities import PnLCalculator


@dataclass
class TrailingStopState:
    """Current state of trailing stop for a strategy."""
    strategy_id: str
    strategy_name: str
    is_active: bool
    margin_used: float
    current_pnl: float
    current_pnl_pct: float  # P&L as % of margin
    activation_pct: float
    floor_pct: Optional[float]  # Current locked-in floor
    high_water_pct: Optional[float]  # Highest P&L % reached
    sl_order_ids: List[str]
    last_updated: datetime


@dataclass
class PositionSLTarget:
    """Stop-loss target for a single position."""
    trade_id: str
    tradingsymbol: str
    instrument_token: int
    exchange: str
    quantity: int
    current_price: float
    sl_trigger_price: float
    sl_price: float  # Limit price for SL order
    proportion: float  # This position's share of strategy margin


class TrailingStopService:
    """
    Service to manage trailing stop-loss for strategies.
    
    Logic:
    - Calculate strategy P&L as sum of position P&Ls
    - Calculate margin consumed by strategy positions
    - When P&L >= 0.8% of margin: activate trailing
    - Lock in 0.8% as floor
    - Every 0.1% increase in P&L: raise floor by 0.05%
    - Place SL orders at position level proportionally
    """
    
    def __init__(self, kite: Optional[KiteClient] = None):
        self.kite = kite
        self._running = False
        self._poll_interval = 5  # seconds
        self._states: Dict[str, TrailingStopState] = {}
    
    def _get_kite(self) -> Optional[KiteClient]:
        """Get KiteClient instance."""
        if self.kite:
            return self.kite
        return get_kite_client(paper_mode=False, skip_api_check=True)
    
    async def start(self, poll_interval: int = 5):
        """Start the trailing stop monitoring loop."""
        self._running = True
        self._poll_interval = poll_interval
        logger.info(f"TrailingStopService started with {poll_interval}s poll interval")
        
        while self._running:
            try:
                await self._monitor_strategies()
            except Exception as e:
                logger.error(f"Error in trailing stop monitor: {e}")
            
            await asyncio.sleep(self._poll_interval)
    
    def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        logger.info("TrailingStopService stopped")
    
    async def _monitor_strategies(self):
        """Monitor all strategies with trailing stop enabled."""
        session = get_session()
        try:
            # Get all strategies with trailing stop enabled and status OPEN
            strategies = session.query(Strategy).filter(
                Strategy.trailing_stop_enabled == True,
                Strategy.status == "OPEN"
            ).all()
            
            if not strategies:
                return
            
            kite = self._get_kite()
            if not kite:
                logger.warning("No KiteClient available for trailing stop monitoring")
                return
            
            # Collect all instrument tokens for batch quote fetch
            all_tokens = set()
            strategy_trades_map: Dict[str, List[StrategyTrade]] = {}
            
            for strategy in strategies:
                trades = [t for t in strategy.trades if t.status == "OPEN"]
                strategy_trades_map[strategy.id] = trades
                for trade in trades:
                    all_tokens.add(trade.instrument_token)
            
            if not all_tokens:
                return
            
            # Fetch quotes for all positions
            quotes = kite.get_quote(list(all_tokens))
            
            # Process each strategy
            for strategy in strategies:
                await self._process_strategy(strategy, strategy_trades_map[strategy.id], quotes, session)
            
            session.commit()
            
        except Exception as e:
            logger.error(f"Error monitoring strategies: {e}")
            session.rollback()
        finally:
            session.close()
    
    async def _process_strategy(
        self, 
        strategy: Strategy, 
        trades: List[StrategyTrade],
        quotes: Dict,
        session
    ):
        """Process a single strategy for trailing stop logic."""
        if not trades:
            return
        
        # Calculate strategy-level P&L and margin
        total_pnl = 0.0
        total_margin = 0.0
        position_details = []
        
        for trade in trades:
            token = trade.instrument_token
            quote = quotes.get(token, {})
            last_price = quote.get("last_price", float(trade.last_price or trade.entry_price))
            
            # Update trade's last_price
            trade.last_price = Decimal(str(last_price))
            trade.last_updated = datetime.now()
            
            # Calculate P&L for this position
            qty = trade.quantity
            entry_price = float(trade.entry_price)
            
            if qty > 0:  # Long position
                pnl = (last_price - entry_price) * qty
            else:  # Short position
                pnl = (entry_price - last_price) * abs(qty)
            
            trade.unrealized_pnl = Decimal(str(pnl))
            
            # Estimate margin for this position
            margin = self._estimate_position_margin(
                trade.tradingsymbol, 
                trade.exchange, 
                qty, 
                last_price,
                entry_price
            )
            
            total_pnl += pnl
            total_margin += margin
            
            position_details.append({
                "trade": trade,
                "last_price": last_price,
                "pnl": pnl,
                "margin": margin
            })
        
        if total_margin <= 0:
            return
        
        # Calculate P&L as percentage of margin
        pnl_pct = (total_pnl / total_margin) * 100
        
        # Get trailing config
        activation_pct = float(strategy.trailing_activation_pct or 0.8)
        step_pct = float(strategy.trailing_step_pct or 0.1)
        lock_pct = float(strategy.trailing_lock_pct or 0.05)
        current_floor = float(strategy.trailing_current_floor_pct) if strategy.trailing_current_floor_pct else None
        high_water = float(strategy.trailing_high_water_pct) if strategy.trailing_high_water_pct else None
        
        logger.debug(
            f"Strategy {strategy.name}: P&L={total_pnl:.2f} ({pnl_pct:.3f}%), "
            f"Margin={total_margin:.2f}, Floor={current_floor}, HW={high_water}"
        )
        
        # Check if we should activate trailing
        if current_floor is None and pnl_pct >= activation_pct:
            # Activate trailing stop
            current_floor = activation_pct
            high_water = pnl_pct
            strategy.trailing_current_floor_pct = Decimal(str(current_floor))
            strategy.trailing_high_water_pct = Decimal(str(high_water))
            strategy.trailing_margin_used = Decimal(str(total_margin))
            strategy.trailing_activated_at = datetime.now()
            
            logger.info(
                f"TRAILING ACTIVATED for {strategy.name}: "
                f"P&L={pnl_pct:.3f}% >= {activation_pct}%, Floor locked at {current_floor}%"
            )
            
            # Place initial SL orders
            await self._place_sl_orders(strategy, position_details, current_floor, total_margin, session)
        
        elif current_floor is not None:
            # Trailing is active - check if we need to raise the floor
            if pnl_pct > high_water:
                # Calculate how many steps we've moved up
                steps_up = int((pnl_pct - high_water) / step_pct)
                
                if steps_up > 0:
                    # Raise the floor
                    new_floor = current_floor + (steps_up * lock_pct)
                    new_high_water = high_water + (steps_up * step_pct)
                    
                    strategy.trailing_current_floor_pct = Decimal(str(new_floor))
                    strategy.trailing_high_water_pct = Decimal(str(new_high_water))
                    
                    logger.info(
                        f"TRAILING RAISED for {strategy.name}: "
                        f"Floor {current_floor:.3f}% -> {new_floor:.3f}%, "
                        f"HW {high_water:.3f}% -> {new_high_water:.3f}%"
                    )
                    
                    # Update SL orders
                    await self._update_sl_orders(strategy, position_details, new_floor, total_margin, session)
                    current_floor = new_floor
            
            # Check if P&L dropped below floor - SL should trigger
            if pnl_pct < current_floor:
                logger.warning(
                    f"TRAILING STOP HIT for {strategy.name}: "
                    f"P&L={pnl_pct:.3f}% < Floor={current_floor:.3f}%"
                )
                # The SL orders should have been triggered by the broker
                # We just log here - actual order execution is handled by Kite
        
        # Update state cache
        self._states[strategy.id] = TrailingStopState(
            strategy_id=strategy.id,
            strategy_name=strategy.name,
            is_active=current_floor is not None,
            margin_used=total_margin,
            current_pnl=total_pnl,
            current_pnl_pct=pnl_pct,
            activation_pct=activation_pct,
            floor_pct=current_floor,
            high_water_pct=high_water,
            sl_order_ids=strategy.trailing_sl_order_ids or [],
            last_updated=datetime.now()
        )
    
    def _estimate_position_margin(
        self, 
        symbol: str, 
        exchange: str, 
        qty: int, 
        ltp: float,
        avg_price: float
    ) -> float:
        """Estimate margin for a position."""
        notional = abs(qty) * ltp
        
        if exchange == "MCX":
            multiplier = PnLCalculator._get_mcx_multiplier(symbol)
            notional = abs(qty) * ltp * multiplier
            return notional * 0.05
        elif exchange == "NFO":
            if "PE" in symbol or "CE" in symbol:
                if qty < 0:  # Short option
                    return notional * 0.15
                else:  # Long option - premium paid
                    return abs(qty) * avg_price
            else:  # Futures
                return notional * 0.12
        else:
            return notional * 0.20
    
    async def _place_sl_orders(
        self,
        strategy: Strategy,
        position_details: List[dict],
        floor_pct: float,
        total_margin: float,
        session
    ):
        """Place SL orders for all positions in the strategy."""
        kite = self._get_kite()
        if not kite:
            return
        
        sl_order_ids = []
        
        for pos in position_details:
            trade = pos["trade"]
            last_price = pos["last_price"]
            margin = pos["margin"]
            
            # Calculate this position's share of the strategy
            proportion = margin / total_margin if total_margin > 0 else 0
            
            # Calculate SL price based on floor
            sl_target = self._calculate_sl_price(
                trade, last_price, floor_pct, proportion, total_margin
            )
            
            if sl_target is None:
                continue
            
            try:
                # Place SL order
                order_id = kite.place_order(
                    tradingsymbol=trade.tradingsymbol,
                    exchange=trade.exchange,
                    transaction_type="SELL" if trade.quantity > 0 else "BUY",
                    quantity=abs(trade.quantity),
                    order_type="SL",
                    product="NRML",
                    trigger_price=sl_target.sl_trigger_price,
                    price=sl_target.sl_price,
                    tag=f"TSL_{strategy.id[:8]}"
                )
                sl_order_ids.append(order_id)
                logger.info(
                    f"Placed SL order {order_id} for {trade.tradingsymbol}: "
                    f"trigger={sl_target.sl_trigger_price:.2f}, price={sl_target.sl_price:.2f}"
                )
            except Exception as e:
                logger.error(f"Failed to place SL order for {trade.tradingsymbol}: {e}")
        
        strategy.trailing_sl_order_ids = sl_order_ids
    
    async def _update_sl_orders(
        self,
        strategy: Strategy,
        position_details: List[dict],
        new_floor_pct: float,
        total_margin: float,
        session
    ):
        """Update existing SL orders with new trigger prices."""
        kite = self._get_kite()
        if not kite:
            return
        
        existing_order_ids = strategy.trailing_sl_order_ids or []
        
        # Cancel existing orders and place new ones
        for order_id in existing_order_ids:
            try:
                kite.cancel_order(order_id)
                logger.debug(f"Cancelled old SL order: {order_id}")
            except Exception as e:
                logger.warning(f"Failed to cancel SL order {order_id}: {e}")
        
        # Place new SL orders with updated prices
        await self._place_sl_orders(strategy, position_details, new_floor_pct, total_margin, session)
    
    def _calculate_sl_price(
        self,
        trade: StrategyTrade,
        last_price: float,
        floor_pct: float,
        proportion: float,
        total_margin: float
    ) -> Optional[PositionSLTarget]:
        """
        Calculate SL trigger and limit prices for a position.
        
        The SL price is calculated to lock in the floor_pct profit
        proportionally allocated to this position.
        """
        qty = trade.quantity
        entry_price = float(trade.entry_price)
        
        # Calculate the profit amount this position should lock in
        # floor_pct is the % of total margin we want to lock
        # This position's share = proportion * floor_pct * total_margin / 100
        target_profit = (proportion * floor_pct * total_margin) / 100
        
        # Calculate the price at which this profit is achieved
        if qty > 0:  # Long position - SL is below current price
            # profit = (sl_price - entry_price) * qty
            # target_profit = (sl_price - entry_price) * qty
            # sl_price = entry_price + (target_profit / qty)
            sl_price = entry_price + (target_profit / qty)
            
            # SL trigger should be slightly above the limit price
            sl_trigger = sl_price * 1.002  # 0.2% buffer
            
            # Ensure SL is below current price
            if sl_trigger >= last_price:
                logger.warning(
                    f"SL trigger {sl_trigger:.2f} >= LTP {last_price:.2f} for {trade.tradingsymbol}, skipping"
                )
                return None
                
        else:  # Short position - SL is above current price
            # profit = (entry_price - sl_price) * abs(qty)
            # target_profit = (entry_price - sl_price) * abs(qty)
            # sl_price = entry_price - (target_profit / abs(qty))
            sl_price = entry_price - (target_profit / abs(qty))
            
            # SL trigger should be slightly below the limit price
            sl_trigger = sl_price * 0.998  # 0.2% buffer
            
            # Ensure SL is above current price
            if sl_trigger <= last_price:
                logger.warning(
                    f"SL trigger {sl_trigger:.2f} <= LTP {last_price:.2f} for {trade.tradingsymbol}, skipping"
                )
                return None
        
        return PositionSLTarget(
            trade_id=trade.id,
            tradingsymbol=trade.tradingsymbol,
            instrument_token=trade.instrument_token,
            exchange=trade.exchange,
            quantity=qty,
            current_price=last_price,
            sl_trigger_price=round(sl_trigger, 2),
            sl_price=round(sl_price, 2),
            proportion=proportion
        )
    
    def get_state(self, strategy_id: str) -> Optional[TrailingStopState]:
        """Get current trailing stop state for a strategy."""
        return self._states.get(strategy_id)
    
    def get_all_states(self) -> Dict[str, TrailingStopState]:
        """Get all trailing stop states."""
        return self._states.copy()
    
    def enable_trailing_stop(
        self,
        strategy_id: str,
        activation_pct: float = 0.8,
        step_pct: float = 0.1,
        lock_pct: float = 0.05
    ) -> bool:
        """Enable trailing stop for a strategy."""
        session = get_session()
        try:
            strategy = session.query(Strategy).filter_by(id=strategy_id).first()
            if not strategy:
                logger.error(f"Strategy {strategy_id} not found")
                return False
            
            strategy.trailing_stop_enabled = True
            strategy.trailing_activation_pct = Decimal(str(activation_pct))
            strategy.trailing_step_pct = Decimal(str(step_pct))
            strategy.trailing_lock_pct = Decimal(str(lock_pct))
            strategy.trailing_current_floor_pct = None
            strategy.trailing_high_water_pct = None
            strategy.trailing_activated_at = None
            strategy.trailing_sl_order_ids = None
            
            session.commit()
            logger.info(
                f"Enabled trailing stop for {strategy.name}: "
                f"activation={activation_pct}%, step={step_pct}%, lock={lock_pct}%"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to enable trailing stop: {e}")
            session.rollback()
            return False
        finally:
            session.close()
    
    def disable_trailing_stop(self, strategy_id: str, cancel_orders: bool = True) -> bool:
        """Disable trailing stop for a strategy."""
        session = get_session()
        try:
            strategy = session.query(Strategy).filter_by(id=strategy_id).first()
            if not strategy:
                logger.error(f"Strategy {strategy_id} not found")
                return False
            
            # Cancel existing SL orders
            if cancel_orders and strategy.trailing_sl_order_ids:
                kite = self._get_kite()
                if kite:
                    for order_id in strategy.trailing_sl_order_ids:
                        try:
                            kite.cancel_order(order_id)
                            logger.debug(f"Cancelled SL order: {order_id}")
                        except Exception as e:
                            logger.warning(f"Failed to cancel SL order {order_id}: {e}")
            
            strategy.trailing_stop_enabled = False
            strategy.trailing_current_floor_pct = None
            strategy.trailing_high_water_pct = None
            strategy.trailing_activated_at = None
            strategy.trailing_sl_order_ids = None
            
            session.commit()
            
            # Remove from state cache
            if strategy_id in self._states:
                del self._states[strategy_id]
            
            logger.info(f"Disabled trailing stop for {strategy.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to disable trailing stop: {e}")
            session.rollback()
            return False
        finally:
            session.close()


# Singleton instance
_trailing_stop_service: Optional[TrailingStopService] = None


def get_trailing_stop_service() -> TrailingStopService:
    """Get the singleton TrailingStopService instance."""
    global _trailing_stop_service
    if _trailing_stop_service is None:
        _trailing_stop_service = TrailingStopService()
    return _trailing_stop_service
