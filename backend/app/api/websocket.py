"""WebSocket endpoint for real-time price and P&L updates.

Architecture:
- Single Kite WebSocket ticker connection for all instrument tokens
- Frontend clients connect to our WebSocket endpoint
- Kite ticker pushes price updates -> we broadcast to all frontend clients
- No REST API polling needed
"""

import asyncio
import json
import threading
from typing import Dict, Set, Optional, Any, List
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from ..config.settings import Settings
from ..database.models import (
    BrokerPosition, Strategy, StrategyPosition, Portfolio, get_session
)


router = APIRouter()


class KiteTickerManager:
    """Singleton manager for Kite WebSocket ticker connection."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._kws = None
        self._running = False
        self._subscribed_tokens: Set[int] = set()
        self._price_cache: Dict[int, Dict] = {}  # token -> tick data
        self._position_data: Dict[int, Dict] = {}  # token -> position info
        self._callbacks: List[callable] = []
        self._thread = None
        self._access_token = None
        self._api_key = None
        logger.info("KiteTickerManager initialized")
    
    def add_callback(self, callback: callable):
        """Add callback to be called on tick updates."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)
    
    def remove_callback(self, callback: callable):
        """Remove callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def start(self, api_key: str, access_token: str):
        """Start the Kite WebSocket ticker."""
        if self._running:
            # Check if token changed
            if access_token != self._access_token:
                logger.info("Access token changed, reconnecting ticker")
                self.stop()
            else:
                return
        
        self._api_key = api_key
        self._access_token = access_token
        
        try:
            from kiteconnect import KiteTicker
            
            self._kws = KiteTicker(api_key, access_token)
            
            self._kws.on_ticks = self._on_ticks
            self._kws.on_connect = self._on_connect
            self._kws.on_close = self._on_close
            self._kws.on_error = self._on_error
            self._kws.on_reconnect = self._on_reconnect
            
            # Start in background thread
            self._thread = threading.Thread(target=self._run_ticker, daemon=True)
            self._thread.start()
            self._running = True
            logger.info("Kite WebSocket ticker started")
            
        except Exception as e:
            logger.error(f"Failed to start Kite ticker: {e}")
    
    def _run_ticker(self):
        """Run ticker in background thread."""
        try:
            self._kws.connect(threaded=True)
        except Exception as e:
            logger.error(f"Ticker connection error: {e}")
            self._running = False
    
    def stop(self):
        """Stop the ticker."""
        if self._kws:
            try:
                self._kws.close()
            except:
                pass
        self._running = False
        self._kws = None
        logger.info("Kite WebSocket ticker stopped")
    
    def subscribe(self, tokens: List[int]):
        """Subscribe to instrument tokens."""
        if not tokens:
            return
        
        new_tokens = set(tokens) - self._subscribed_tokens
        if new_tokens and self._kws and self._running:
            try:
                self._kws.subscribe(list(new_tokens))
                self._kws.set_mode(self._kws.MODE_FULL, list(new_tokens))
                self._subscribed_tokens.update(new_tokens)
                logger.info(f"Subscribed to {len(new_tokens)} new tokens")
            except Exception as e:
                logger.error(f"Failed to subscribe: {e}")
    
    def set_position_data(self, token: int, data: Dict):
        """Store position data for a token."""
        self._position_data[token] = data
    
    def get_price(self, token: int) -> Optional[float]:
        """Get cached price for token."""
        tick = self._price_cache.get(token)
        return tick.get("last_price") if tick else None
    
    def get_all_prices(self) -> Dict[int, float]:
        """Get all cached prices."""
        return {t: d.get("last_price", 0) for t, d in self._price_cache.items()}
    
    def _on_ticks(self, ws, ticks):
        """Handle incoming ticks from Kite."""
        for tick in ticks:
            token = tick.get("instrument_token")
            if token:
                self._price_cache[token] = tick
        
        # Notify all callbacks
        for callback in self._callbacks:
            try:
                callback(ticks)
            except Exception as e:
                logger.error(f"Tick callback error: {e}")
    
    def _on_connect(self, ws, response):
        """Handle connection."""
        logger.info("Kite ticker connected")
        # Resubscribe to tokens
        if self._subscribed_tokens:
            try:
                ws.subscribe(list(self._subscribed_tokens))
                ws.set_mode(ws.MODE_FULL, list(self._subscribed_tokens))
            except Exception as e:
                logger.error(f"Resubscribe error: {e}")
    
    def _on_close(self, ws, code, reason):
        """Handle close - attempt reconnection."""
        logger.warning(f"Kite ticker closed: {code} - {reason}")
        self._running = False
        
        # Attempt to reconnect after a short delay
        if self._api_key and self._access_token:
            import time
            time.sleep(2)
            logger.info("Attempting to reconnect Kite ticker...")
            try:
                self.start(self._api_key, self._access_token)
            except Exception as e:
                logger.error(f"Failed to reconnect ticker: {e}")
    
    def _on_error(self, ws, code, reason):
        """Handle error - mark as not running so reconnect can happen."""
        logger.error(f"Kite ticker error: {code} - {reason}")
        self._running = False
    
    def _on_reconnect(self, ws, attempts_count):
        """Handle reconnect."""
        logger.info(f"Kite ticker reconnecting, attempt {attempts_count}")


# Global ticker manager
ticker_manager = KiteTickerManager()


class ConnectionManager:
    """Manages WebSocket connections and broadcasts updates."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._price_cache: Dict[int, float] = {}  # instrument_token -> last_price
        self._position_cache: Dict[str, Dict] = {}  # position_id -> position data
        self._strategy_cache: Dict[str, Dict] = {}  # strategy_id -> strategy data
        self._portfolio_cache: Dict[str, Dict] = {}  # portfolio_id -> portfolio data
        self._running = False
        self._kite_ws = None
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
        
        # Send initial state
        await self._send_initial_state(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def _send_initial_state(self, websocket: WebSocket):
        """Send current positions, strategies, and portfolios on connect."""
        try:
            positions = self._get_all_positions()
            strategies = self._get_all_strategies()
            portfolios = self._get_all_portfolios()
            
            await websocket.send_json({
                "type": "initial_state",
                "data": {
                    "positions": positions,
                    "strategies": strategies,
                    "portfolios": portfolios,
                    "timestamp": datetime.now().isoformat()
                }
            })
        except Exception as e:
            logger.error(f"Failed to send initial state: {e}")
    
    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients."""
        if not self.active_connections:
            return
        
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                disconnected.add(connection)
        
        # Clean up disconnected clients
        self.active_connections -= disconnected
    
    def update_price(self, instrument_token: int, last_price: float):
        """Update price cache and trigger P&L recalculation."""
        self._price_cache[instrument_token] = last_price
    
    def _get_all_positions(self) -> list:
        """Get all open positions from database."""
        try:
            session = get_session()
            positions = session.query(BrokerPosition).filter(
                BrokerPosition.closed_at.is_(None)
            ).all()
            
            result = []
            for p in positions:
                pos_data = {
                    "id": p.id,
                    "tradingsymbol": p.tradingsymbol,
                    "instrument_token": p.instrument_token,
                    "exchange": p.exchange,
                    "quantity": p.quantity,
                    "average_price": float(p.average_price),
                    "last_price": float(p.last_price) if p.last_price else None,
                    "pnl": float(p.pnl or 0),
                    "source": p.source,
                }
                result.append(pos_data)
                self._position_cache[p.id] = pos_data
            
            session.close()
            return result
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []
    
    def _get_all_strategies(self) -> list:
        """Get all open strategies with aggregated P&L."""
        try:
            session = get_session()
            strategies = session.query(Strategy).filter(
                Strategy.status == "OPEN"
            ).all()
            
            result = []
            for s in strategies:
                # Calculate aggregate P&L from linked positions
                total_pnl = 0
                position_count = 0
                
                for sp in s.strategy_positions:
                    if sp.position and sp.position.pnl:
                        total_pnl += float(sp.position.pnl)
                        position_count += 1
                
                strat_data = {
                    "id": s.id,
                    "name": s.name,
                    "label": s.label,
                    "status": s.status,
                    "unrealized_pnl": total_pnl,
                    "realized_pnl": float(s.realized_pnl or 0),
                    "position_count": position_count,
                    "source": s.source,
                }
                result.append(strat_data)
                self._strategy_cache[s.id] = strat_data
            
            session.close()
            return result
        except Exception as e:
            logger.error(f"Failed to get strategies: {e}")
            return []
    
    def _get_all_portfolios(self) -> list:
        """Get all active portfolios with aggregated P&L."""
        try:
            session = get_session()
            portfolios = session.query(Portfolio).filter(
                Portfolio.is_active == True
            ).all()
            
            result = []
            for p in portfolios:
                # Calculate aggregate P&L from strategies
                total_unrealized = 0
                total_realized = 0
                strategy_count = 0
                
                for s in p.strategies:
                    if s.status == "OPEN":
                        # Get strategy's unrealized P&L
                        strat_pnl = 0
                        for sp in s.strategy_positions:
                            if sp.position and sp.position.pnl:
                                strat_pnl += float(sp.position.pnl)
                        total_unrealized += strat_pnl
                        strategy_count += 1
                    total_realized += float(s.realized_pnl or 0)
                
                port_data = {
                    "id": p.id,
                    "name": p.name,
                    "unrealized_pnl": total_unrealized,
                    "realized_pnl": total_realized,
                    "total_pnl": total_unrealized + total_realized,
                    "strategy_count": strategy_count,
                }
                result.append(port_data)
                self._portfolio_cache[p.id] = port_data
            
            session.close()
            return result
        except Exception as e:
            logger.error(f"Failed to get portfolios: {e}")
            return []
    
    async def recalculate_and_broadcast(self):
        """Recalculate P&L for all positions, strategies, portfolios and broadcast."""
        try:
            session = get_session()
            
            # Update positions with new prices
            positions_updated = []
            for pos_id, pos_data in self._position_cache.items():
                token = pos_data.get("instrument_token")
                if token and token in self._price_cache:
                    new_price = self._price_cache[token]
                    old_price = pos_data.get("last_price") or pos_data.get("average_price")
                    
                    if new_price != old_price:
                        # Calculate new P&L
                        qty = pos_data.get("quantity", 0)
                        avg_price = pos_data.get("average_price", 0)
                        new_pnl = (new_price - avg_price) * qty
                        
                        # Update cache
                        pos_data["last_price"] = new_price
                        pos_data["pnl"] = new_pnl
                        
                        # Update database
                        db_pos = session.query(BrokerPosition).filter_by(id=pos_id).first()
                        if db_pos:
                            db_pos.last_price = new_price
                            db_pos.pnl = new_pnl
                        
                        positions_updated.append(pos_data)
            
            if positions_updated:
                session.commit()
            
            # Recalculate strategies
            strategies = self._get_all_strategies()
            
            # Recalculate portfolios
            portfolios = self._get_all_portfolios()
            
            session.close()
            
            # Broadcast updates
            if positions_updated or strategies or portfolios:
                await self.broadcast({
                    "type": "price_update",
                    "data": {
                        "positions": positions_updated,
                        "strategies": strategies,
                        "portfolios": portfolios,
                        "timestamp": datetime.now().isoformat()
                    }
                })
        except Exception as e:
            logger.error(f"Failed to recalculate and broadcast: {e}")


# Global connection manager
manager = ConnectionManager()

# Cache for positions (fetched once, updated via ticker)
_positions_cache: Dict[int, Dict] = {}  # token -> position data
_positions_list_cache: list = []
_positions_cache_time: float = 0


@router.websocket("/ws/prices")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time price updates.
    
    Uses Kite WebSocket ticker for efficient real-time updates.
    Only fetches positions once on connect, then updates via ticker.
    """
    await websocket.accept()
    logger.info("WebSocket client connected")
    
    # Queue for tick updates (bounded to prevent memory issues)
    tick_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    connected = True
    positions = []
    
    # Get the current event loop for thread-safe scheduling
    loop = asyncio.get_running_loop()
    
    def on_tick(ticks):
        """Callback when ticks arrive from Kite (runs in separate thread)."""
        if not connected:
            return
        
        def _put_tick():
            try:
                # Drop old ticks if queue is full
                if tick_queue.full():
                    try:
                        tick_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                tick_queue.put_nowait(ticks)
            except Exception:
                pass

        # Schedule the queue update on the main event loop
        try:
            loop.call_soon_threadsafe(_put_tick)
        except Exception:
            pass
    
    async def send_heartbeat():
        """Send periodic heartbeats."""
        while connected:
            try:
                await asyncio.sleep(30)
                if connected:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": datetime.now().isoformat()
                    })
            except:
                break
    
    async def process_ticks():
        """Process tick updates and send to client."""
        nonlocal positions
        while connected:
            try:
                # Wait for tick with timeout
                ticks = await asyncio.wait_for(tick_queue.get(), timeout=5.0)
                if connected and ticks:
                    updated_positions = update_positions_with_ticks(positions, ticks)
                    
                    # Fetch strategies and portfolios with updated position data
                    strategies, portfolios = await asyncio.get_event_loop().run_in_executor(
                        None, fetch_strategies_and_portfolios, updated_positions
                    )
                    
                    await websocket.send_json({
                        "type": "price_update",
                        "data": {
                            "positions": updated_positions,
                            "strategies": strategies,
                            "portfolios": portfolios,
                            "timestamp": datetime.now().isoformat()
                        }
                    })
                    positions = updated_positions
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Tick processing error: {e}")
                continue
    
    async def receive_messages():
        """Handle incoming client messages."""
        nonlocal connected
        while connected:
            try:
                message = await websocket.receive_text()
                data = json.loads(message)
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                logger.info("WebSocket client disconnected (receive)")
                connected = False
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Receive error: {e}")
                connected = False
                break
    
    try:
        # Fetch initial positions (one-time REST call)
        positions = await asyncio.get_event_loop().run_in_executor(None, fetch_positions_once)
        
        # Start Kite ticker if we have positions
        if positions:
            config = Settings()
            from .auth import get_any_valid_access_token
            access_token = get_any_valid_access_token() or config.kite_access_token
            
            if access_token:
                ticker_manager.start(config.kite_api_key, access_token)
                ticker_manager.add_callback(on_tick)
                
                # Subscribe to all position tokens
                tokens = [p.get("instrument_token") for p in positions if p.get("instrument_token")]
                ticker_manager.subscribe(tokens)
        
        # Fetch strategies and portfolios with initial position data
        strategies, portfolios = await asyncio.get_event_loop().run_in_executor(
            None, fetch_strategies_and_portfolios, positions
        )
        
        # Send initial state
        await websocket.send_json({
            "type": "initial_state",
            "data": {
                "positions": positions,
                "strategies": strategies,
                "portfolios": portfolios,
                "timestamp": datetime.now().isoformat()
            }
        })
        
        # Run all tasks concurrently
        await asyncio.gather(
            receive_messages(),
            process_ticks(),
            send_heartbeat(),
            return_exceptions=True
        )
                
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        connected = False
        ticker_manager.remove_callback(on_tick)


def fetch_positions_once() -> list:
    """Fetch positions from Kite API (one-time call on WebSocket connect).
    
    Also refreshes instrument cache for accurate P&L calculations.
    """
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    from .auth import get_any_valid_access_token
    from ..services.instrument_cache import instrument_cache
    from ..services.pnl_calculator import PnLCalculator
    
    config = Settings()
    access_token = get_any_valid_access_token() or config.kite_access_token
    
    if not access_token:
        return []
    
    try:
        kite = KiteClient(
            api_key=config.kite_api_key,
            access_token=access_token,
            paper_mode=False,
            mock_mode=False
        )
        
        # Refresh instrument cache (will skip if recently refreshed)
        instrument_cache.refresh_from_kite(kite)
        
        positions_data = kite.get_positions()
        net_positions = positions_data.get("net", [])
        
        result = []
        for p in net_positions:
            qty = p.get("quantity", 0)
            if qty == 0:
                continue
            
            instrument_token = p.get("instrument_token", 0)
            avg_price = p.get("average_price", 0)
            last_price = p.get("last_price", 0)
            exchange = p.get("exchange", "NFO")
            
            # Use backend P&L calculator for accurate calculations
            pnl_data = PnLCalculator.calculate_position_pnl(
                instrument_token=instrument_token,
                quantity=qty,
                average_price=avg_price,
                last_price=last_price,
                exchange=exchange
            )
            
            # Get instrument info for additional context
            inst_info = instrument_cache.get(instrument_token) or {}
            
            # Calculate LTP change from previous close
            close_price = p.get("close_price", 0)
            ltp_change = last_price - close_price if close_price else 0
            ltp_change_pct = (ltp_change / close_price * 100) if close_price else 0
            
            result.append({
                "id": str(instrument_token),
                "tradingsymbol": p.get("tradingsymbol", ""),
                "instrument_token": instrument_token,
                "exchange": exchange,
                "quantity": qty,
                "average_price": avg_price,
                "last_price": last_price,
                "close_price": close_price,
                "ltp_change": round(ltp_change, 2),
                "ltp_change_pct": round(ltp_change_pct, 2),
                "pnl": pnl_data["pnl"],
                "pnl_pct": pnl_data["pnl_pct"],
                "lot_size": pnl_data["lot_size"],
                "instrument_type": pnl_data["instrument_type"],
                "source": "LIVE"
            })
        
        return result
    except Exception as e:
        logger.error(f"Failed to fetch positions: {e}")
        return []


def fetch_strategies_and_portfolios(positions: list) -> tuple:
    """Fetch strategies and portfolios from database and enrich with live position data.
    
    Args:
        positions: List of positions with live prices
        
    Returns:
        Tuple of (strategies, portfolios) lists
    """
    from ..database.repository import Repository
    
    try:
        repo = Repository()
        
        # Create position lookup by instrument_token
        pos_lookup = {p.get("instrument_token"): p for p in positions}
        
        # Get strategies from database
        strategies_data = repo.get_all_strategies()
        
        # Enrich strategies with live position data
        enriched_strategies = []
        for strategy in strategies_data:
            trades = strategy.get("trades", [])
            total_pnl = 0
            
            # Update trades with live prices
            enriched_trades = []
            for trade in trades:
                token = trade.get("instrument_token")
                live_pos = pos_lookup.get(token)
                
                if live_pos:
                    trade_pnl = live_pos.get("pnl", 0)
                    enriched_trades.append({
                        **trade,
                        "last_price": live_pos.get("last_price"),
                        "unrealized_pnl": trade_pnl,
                        "pnl_pct": live_pos.get("pnl_pct", 0)
                    })
                    total_pnl += trade_pnl
                else:
                    enriched_trades.append(trade)
                    total_pnl += trade.get("unrealized_pnl", 0)
            
            enriched_strategies.append({
                "id": strategy.get("id"),
                "name": strategy.get("name"),
                "label": strategy.get("label"),
                "status": strategy.get("status"),
                "unrealized_pnl": round(total_pnl, 2),
                "realized_pnl": strategy.get("realized_pnl", 0),
                "total_pnl": round(total_pnl + strategy.get("realized_pnl", 0), 2),
                "position_count": len(trades),
                "source": strategy.get("source", "MANUAL"),
                "trades": enriched_trades
            })
        
        # Get portfolios from database
        portfolios_data = repo.get_all_portfolios()
        
        # Enrich portfolios with strategy data
        enriched_portfolios = []
        for portfolio in portfolios_data:
            portfolio_id = portfolio.get("id")
            portfolio_strategies = [s for s in enriched_strategies if s.get("portfolio_id") == portfolio_id]
            
            total_unrealized = sum(s.get("unrealized_pnl", 0) for s in portfolio_strategies)
            total_realized = sum(s.get("realized_pnl", 0) for s in portfolio_strategies)
            
            enriched_portfolios.append({
                "id": portfolio_id,
                "name": portfolio.get("name"),
                "unrealized_pnl": round(total_unrealized, 2),
                "realized_pnl": round(total_realized, 2),
                "total_pnl": round(total_unrealized + total_realized, 2),
                "strategy_count": len(portfolio_strategies)
            })
        
        # If no portfolios, create virtual "All Strategies" portfolio
        if not enriched_portfolios and enriched_strategies:
            total_unrealized = sum(s.get("unrealized_pnl", 0) for s in enriched_strategies)
            total_realized = sum(s.get("realized_pnl", 0) for s in enriched_strategies)
            
            enriched_portfolios.append({
                "id": "all",
                "name": "All Strategies",
                "unrealized_pnl": round(total_unrealized, 2),
                "realized_pnl": round(total_realized, 2),
                "total_pnl": round(total_unrealized + total_realized, 2),
                "strategy_count": len(enriched_strategies)
            })
        
        return enriched_strategies, enriched_portfolios
        
    except Exception as e:
        logger.error(f"Failed to fetch strategies/portfolios: {e}")
        return [], []


def update_positions_with_ticks(positions: list, ticks: list) -> list:
    """Update position LTP and recalculate P&L from tick data.
    
    Backend is the source of truth for P&L calculations.
    Uses PnLCalculator for correct calculations across all instrument types.
    """
    from ..services.pnl_calculator import PnLCalculator
    
    # Create lookup by token
    tick_map = {t.get("instrument_token"): t for t in ticks}
    
    updated = []
    for pos in positions:
        token = pos.get("instrument_token")
        tick = tick_map.get(token)
        
        if tick:
            last_price = tick.get("last_price", pos.get("last_price", 0))
            close_price = pos.get("close_price", 0)
            
            # Recalculate P&L using backend calculator
            pnl_data = PnLCalculator.calculate_position_pnl(
                instrument_token=token,
                quantity=pos.get("quantity", 0),
                average_price=pos.get("average_price", 0),
                last_price=last_price,
                exchange=pos.get("exchange", "NFO")
            )
            
            # Recalculate LTP change from previous close
            ltp_change = last_price - close_price if close_price else 0
            ltp_change_pct = (ltp_change / close_price * 100) if close_price else 0
            
            updated.append({
                **pos,
                "last_price": last_price,
                "ltp_change": round(ltp_change, 2),
                "ltp_change_pct": round(ltp_change_pct, 2),
                "pnl": pnl_data["pnl"],
                "pnl_pct": pnl_data["pnl_pct"],
            })
        else:
            updated.append(pos)
    
    return updated


def fetch_positions_sync() -> list:
    """Fetch live positions from Kite API (synchronous) with caching. DEPRECATED - use fetch_positions_once."""
    import time
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    from .auth import get_any_valid_access_token
    
    global _positions_cache, _positions_cache_time
    
    # Return cached data if less than 2 seconds old
    now = time.time()
    if _positions_cache and (now - _positions_cache_time) < 2.0:
        return _positions_cache
    
    config = Settings()
    
    # Try session token first, then fall back to .env token
    access_token = get_any_valid_access_token() or config.kite_access_token
    
    if not access_token:
        return _positions_cache  # Return stale cache if no token
    
    try:
        # Reuse cached KiteClient if possible
        if _kite_client_cache is None:
            _kite_client_cache = KiteClient(
                api_key=config.kite_api_key,
                access_token=access_token,
                paper_mode=False,
                mock_mode=False
            )
        kite = _kite_client_cache
        
        positions_data = kite.get_positions()
        net_positions = positions_data.get("net", [])
        
        result = []
        for p in net_positions:
            qty = p.get("quantity", 0)
            if qty == 0:
                continue
            
            avg_price = p.get("average_price", 0)
            pnl = p.get("pnl", 0)
            instrument_token = p.get("instrument_token", 0)
            
            result.append({
                "id": str(instrument_token),
                "tradingsymbol": p.get("tradingsymbol", ""),
                "instrument_token": instrument_token,
                "exchange": p.get("exchange", ""),
                "quantity": qty,
                "average_price": avg_price,
                "last_price": p.get("last_price", 0),
                "pnl": pnl,
                "source": "LIVE"
            })
        
        # Update cache
        _positions_cache = result
        _positions_cache_time = now
        
        return result
    except Exception as e:
        logger.error(f"Failed to fetch live positions: {e}")
        return _positions_cache  # Return stale cache on error


async def fetch_live_positions() -> list:
    """Fetch live positions from Kite API (async wrapper)."""
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    
    config = Settings()
    if not config.kite_access_token:
        return []
    
    try:
        kite = KiteClient(
            api_key=config.kite_api_key,
            access_token=config.kite_access_token,
            paper_mode=False,
            mock_mode=False
        )
        
        positions_data = kite.get_positions()
        net_positions = positions_data.get("net", [])
        
        result = []
        for p in net_positions:
            qty = p.get("quantity", 0)
            if qty == 0:
                continue
            
            avg_price = p.get("average_price", 0)
            pnl = p.get("pnl", 0)
            instrument_token = p.get("instrument_token", 0)
            
            result.append({
                "id": str(instrument_token),
                "tradingsymbol": p.get("tradingsymbol", ""),
                "instrument_token": instrument_token,
                "exchange": p.get("exchange", ""),
                "quantity": qty,
                "average_price": avg_price,
                "last_price": p.get("last_price", 0),
                "pnl": pnl,
                "source": "LIVE"
            })
        
        return result
    except Exception as e:
        logger.error(f"Failed to fetch live positions: {e}")
        return []


async def start_price_stream(config: Settings):
    """Start the Kite WebSocket ticker for live prices."""
    from kiteconnect import KiteTicker
    
    if not config.kite_access_token:
        logger.warning("No access token available for WebSocket ticker")
        return
    
    try:
        kws = KiteTicker(config.kite_api_key, config.kite_access_token)
        
        def on_ticks(ws, ticks):
            """Handle incoming ticks from Kite."""
            for tick in ticks:
                token = tick.get("instrument_token")
                ltp = tick.get("last_price")
                if token and ltp:
                    manager.update_price(token, ltp)
            
            # Schedule async broadcast
            asyncio.create_task(manager.recalculate_and_broadcast())
        
        def on_connect(ws, response):
            """Subscribe to instruments on connect."""
            logger.info("Kite WebSocket connected")
            
            # Get all instrument tokens from positions
            tokens = list(manager._price_cache.keys())
            if not tokens:
                # Get from database
                session = get_session()
                positions = session.query(BrokerPosition).filter(
                    BrokerPosition.closed_at.is_(None)
                ).all()
                tokens = [p.instrument_token for p in positions if p.instrument_token]
                session.close()
            
            if tokens:
                ws.subscribe(tokens)
                ws.set_mode(ws.MODE_LTP, tokens)
                logger.info(f"Subscribed to {len(tokens)} instruments")
        
        def on_close(ws, code, reason):
            logger.warning(f"Kite WebSocket closed: {code} - {reason}")
        
        def on_error(ws, code, reason):
            logger.error(f"Kite WebSocket error: {code} - {reason}")
        
        kws.on_ticks = on_ticks
        kws.on_connect = on_connect
        kws.on_close = on_close
        kws.on_error = on_error
        
        # Run in background thread
        kws.connect(threaded=True)
        manager._kite_ws = kws
        manager._running = True
        
        logger.info("Kite WebSocket ticker started")
        
    except Exception as e:
        logger.error(f"Failed to start Kite WebSocket: {e}")


def stop_price_stream():
    """Stop the Kite WebSocket ticker."""
    if manager._kite_ws:
        try:
            manager._kite_ws.close()
            manager._running = False
            logger.info("Kite WebSocket ticker stopped")
        except Exception as e:
            logger.error(f"Error stopping Kite WebSocket: {e}")
