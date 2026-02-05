"""FastAPI routes for Trading System v2.0"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from pathlib import Path
from loguru import logger

router = APIRouter()


# ============== Request/Response Models ==============

class DataDownloadRequest(BaseModel):
    symbol: str = "NIFTY"
    days: int = 90
    interval: str = "day"


class BacktestRequest(BaseModel):
    data_file: str
    strategy: str = "iron_condor"
    initial_capital: float = 1000000
    position_size_pct: float = 0.02


class BacktestResponse(BaseModel):
    total_trades: int
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float


class TradingStatusResponse(BaseModel):
    mode: str
    running: bool
    positions: int
    daily_pnl: float
    regime: Optional[str]


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    version: str = "2.0.0"


# ============== Health ==============

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now()
    )


# ============== Data ==============

@router.post("/data/download")
async def download_data(request: DataDownloadRequest, background_tasks: BackgroundTasks):
    """Download historical data from KiteConnect."""
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    from ..config.constants import NIFTY_TOKEN, BANKNIFTY_TOKEN, INDIA_VIX_TOKEN
    
    tokens = {
        "NIFTY": NIFTY_TOKEN,
        "BANKNIFTY": BANKNIFTY_TOKEN,
        "INDIAVIX": INDIA_VIX_TOKEN
    }
    
    token = tokens.get(request.symbol.upper())
    if not token:
        raise HTTPException(status_code=400, detail=f"Unknown symbol: {request.symbol}")
    
    # Run download in background
    background_tasks.add_task(
        _download_data_task,
        request.symbol,
        token,
        request.days,
        request.interval
    )
    
    return {"message": f"Download started for {request.symbol}", "status": "processing"}


async def _download_data_task(symbol: str, token: int, days: int, interval: str):
    """Background task to download data."""
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    from datetime import timedelta
    
    config = Settings()
    kite = KiteClient(
        api_key=config.kite_api_key,
        access_token=config.kite_access_token,
        paper_mode=False
    )
    
    to_date = date.today()
    from_date = to_date - timedelta(days=days)
    
    df = kite.fetch_historical_data(
        token, interval,
        datetime.combine(from_date, datetime.min.time()),
        datetime.combine(to_date, datetime.max.time())
    )
    
    if not df.empty:
        output_dir = Path("data")
        output_dir.mkdir(exist_ok=True)
        filename = f"{symbol}_{from_date}_{to_date}_{interval}.csv"
        df.to_csv(output_dir / filename)


@router.get("/data/files")
async def list_data_files():
    """List available data files."""
    data_dir = Path("data")
    if not data_dir.exists():
        return {"files": []}
    
    files = [f.name for f in data_dir.glob("*.csv")]
    return {"files": files}


# ============== Backtest ==============

@router.post("/backtest/run", response_model=BacktestResponse)
async def run_backtest(request: BacktestRequest):
    """Run backtest on historical data."""
    from ..services.engine import BacktestEngine, BacktestConfig
    from ..services.data_loader import DataLoader
    from ..services.technical import calculate_rsi
    
    data_path = Path("data") / request.data_file
    if not data_path.exists():
        raise HTTPException(status_code=404, detail=f"Data file not found: {request.data_file}")
    
    # Load data
    loader = DataLoader()
    data = loader.load_from_csv(data_path)
    
    if data.empty:
        raise HTTPException(status_code=400, detail="No data in file")
    
    # Configure backtest
    bt_config = BacktestConfig(
        initial_capital=request.initial_capital,
        position_size_pct=request.position_size_pct,
        max_positions=3
    )
    
    # Simple entry/exit signals
    def entry_signal(data, idx):
        if idx < 20:
            return None
        rsi = calculate_rsi(data['close'].iloc[:idx+1], 14)
        if rsi.iloc[-1] < 30:
            return {
                "direction": 1,
                "stop_loss": data.iloc[idx]['close'] * 0.98,
                "take_profit": data.iloc[idx]['close'] * 1.02
            }
        return None
    
    def exit_signal(data, idx, position):
        if idx - position.metadata.get("entry_idx", 0) >= 5:
            return "TIME_EXIT"
        return None
    
    # Run backtest
    engine = BacktestEngine(bt_config, loader)
    results = engine.run(data, entry_signal, exit_signal)
    
    metrics = results["metrics"]
    
    return BacktestResponse(
        total_trades=metrics.get("num_trades", 0),
        total_return_pct=metrics.get("total_return_pct", 0),
        sharpe_ratio=metrics.get("sharpe_ratio", 0),
        max_drawdown=metrics.get("max_drawdown", 0),
        win_rate=metrics.get("win_rate", 0),
        profit_factor=metrics.get("profit_factor", 0)
    )


# ============== Trading ==============

# Global orchestrator instance
_orchestrator = None


@router.post("/trading/start")
async def start_trading(mode: str = "paper", background_tasks: BackgroundTasks = None):
    """Start the trading system."""
    global _orchestrator
    
    if _orchestrator and _orchestrator.running:
        raise HTTPException(status_code=400, detail="Trading already running")
    
    from ..config.settings import Settings
    from .orchestrator import Orchestrator
    
    config = Settings()
    _orchestrator = Orchestrator(config, mode)
    
    if background_tasks:
        background_tasks.add_task(_orchestrator.run, 300)
    
    return {"message": f"Trading started in {mode.upper()} mode"}


@router.post("/trading/stop")
async def stop_trading():
    """Stop the trading system."""
    global _orchestrator
    
    if not _orchestrator:
        raise HTTPException(status_code=400, detail="Trading not running")
    
    _orchestrator.stop()
    return {"message": "Trading stopped"}


@router.get("/trading/status", response_model=TradingStatusResponse)
async def get_trading_status():
    """Get current trading status."""
    global _orchestrator
    
    if not _orchestrator:
        return TradingStatusResponse(
            mode="stopped",
            running=False,
            positions=0,
            daily_pnl=0,
            regime=None
        )
    
    return TradingStatusResponse(
        mode=_orchestrator.mode,
        running=_orchestrator.running,
        positions=len(_orchestrator.executor.get_open_positions()) if _orchestrator.running else 0,
        daily_pnl=_orchestrator.state_manager.get("daily_pnl", 0.0) if _orchestrator.running else 0,
        regime=None  # Would need to track last regime
    )


@router.post("/trading/flatten")
async def flatten_all(reason: str = "MANUAL"):
    """Emergency flatten all positions."""
    global _orchestrator
    
    if not _orchestrator:
        raise HTTPException(status_code=400, detail="Trading not running")
    
    results = _orchestrator.flatten_all(reason)
    return {"message": "Flatten executed", "results": len(results)}


# ============== Positions & Orders ==============

@router.get("/positions")
async def get_positions(request: Request):
    """Get current positions from KiteConnect (real account positions)."""
    from ..core.kite_client import KiteClient, TokenExpiredException
    from ..config.settings import Settings
    from .auth import get_access_token
    
    config = Settings()
    access_token = get_access_token(request)
    if not access_token:
        access_token = config.kite_access_token
    
    if not access_token:
        return []
    
    kite = KiteClient(
        api_key=config.kite_api_key,
        access_token=access_token,
        paper_mode=False,  # Get real positions
        mock_mode=False
    )
    
    try:
        # Fetch real positions from Kite
        positions_data = kite.get_positions()
        net_positions = positions_data.get("net", [])
        
        # Also get paper positions from orchestrator if running
        global _orchestrator
        paper_positions = []
        if _orchestrator and _orchestrator.running:
            paper_positions = [p.tradingsymbol for p in _orchestrator.executor.get_open_positions()]
        
        result = []
        for p in net_positions:
            qty = p.get("quantity", 0)
            if qty == 0:
                continue  # Skip closed positions
                
            avg_price = p.get("average_price", 0)
            last_price = p.get("last_price", 0)
            # Use Kite's P&L directly - it's more accurate
            pnl = p.get("pnl", 0)
            
            # Determine if this is a paper position (managed by our system)
            tradingsymbol = p.get("tradingsymbol", "")
            is_paper = tradingsymbol in paper_positions
            
            # Use instrument_token as stable ID
            instrument_token = p.get("instrument_token", 0)
            
            result.append({
                "id": str(instrument_token),
                "tradingsymbol": tradingsymbol,
                "instrument_token": instrument_token,
                "exchange": p.get("exchange", ""),
                "quantity": qty,
                "average_price": avg_price,
                "last_price": last_price,
                "pnl": pnl,
                "pnl_pct": (pnl / (avg_price * abs(qty)) * 100) if avg_price and qty else 0,
                "product": p.get("product", ""),
                "source": "PAPER" if is_paper else "LIVE"
            })
        
        return result
    except TokenExpiredException as e:
        logger.error(f"Token expired: {e}")
        raise HTTPException(status_code=401, detail="Token expired. Please re-login.")
    except Exception as e:
        logger.error(f"Failed to fetch positions: {e}")
        return []


@router.get("/orders")
async def get_orders(request: Request):
    """Get today's orders from KiteConnect."""
    from ..core.kite_client import KiteClient, TokenExpiredException
    from ..config.settings import Settings
    from .auth import get_access_token
    
    config = Settings()
    access_token = get_access_token(request)
    if not access_token:
        access_token = config.kite_access_token
    
    if not access_token:
        return []
    
    kite = KiteClient(
        api_key=config.kite_api_key,
        access_token=access_token,
        paper_mode=False,
        mock_mode=False
    )
    
    try:
        orders = kite.get_orders()
        return [
            {
                "order_id": o.get("order_id", ""),
                "tradingsymbol": o.get("tradingsymbol", ""),
                "exchange": o.get("exchange", ""),
                "transaction_type": o.get("transaction_type", ""),
                "quantity": o.get("quantity", 0),
                "price": o.get("price", 0),
                "average_price": o.get("average_price", 0),
                "status": o.get("status", ""),
                "order_timestamp": str(o.get("order_timestamp", "")),
                "tag": o.get("tag", "")
            }
            for o in orders
        ]
    except TokenExpiredException as e:
        logger.error(f"Token expired: {e}")
        raise HTTPException(status_code=401, detail="Token expired. Please re-login.")
    except Exception as e:
        logger.error(f"Failed to fetch orders: {e}")
        return []


# ============== Indices ==============

class IndicesQuotesRequest(BaseModel):
    symbols: List[str]

# Symbol to display name mapping
INDEX_NAMES = {
    "NSE:NIFTY 50": "NIFTY 50",
    "BSE:SENSEX": "SENSEX",
    "NSE:NIFTY BANK": "BANK NIFTY",
    "NSE:NIFTY FIN SERVICE": "NIFTY FIN",
    "NSE:NIFTY IT": "NIFTY IT",
    "NSE:NIFTY MIDCAP 50": "MIDCAP 50",
    "NSE:INDIA VIX": "INDIA VIX",
}

@router.post("/indices/quotes")
async def get_indices_quotes(request: Request, body: IndicesQuotesRequest):
    """Get live quotes for multiple indices.
    
    Args:
        symbols: List of index symbols (e.g., ["NSE:NIFTY 50", "BSE:SENSEX"])
    
    Returns:
        quotes: List of index quotes with price, change, change_pct, and market_open status
        
    The market_open field is determined by checking if last_trade_time is recent (within last 5 minutes).
    This avoids hardcoding market hours and works across different exchanges.
    """
    from ..core.kite_client import KiteClient, TokenExpiredException
    from ..config.settings import Settings
    from .auth import get_access_token
    from datetime import datetime, timedelta
    import pytz
    
    config = Settings()
    access_token = get_access_token(request) or config.kite_access_token
    
    logger.debug(f"Fetching indices quotes for: {body.symbols}")
    
    if not access_token or not body.symbols:
        logger.warning("No access token or symbols provided")
        return {"quotes": []}
    
    kite = KiteClient(
        api_key=config.kite_api_key,
        access_token=access_token,
        paper_mode=False,
        mock_mode=False
    )
    
    try:
        quotes = kite.get_quote(body.symbols)
        logger.debug(f"Got quotes: {quotes}")
        
        result = []
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        
        for symbol in body.symbols:
            data = quotes.get(symbol, {})
            if data:
                ohlc = data.get("ohlc", {})
                last_price = data.get("last_price", 0)
                prev_close = ohlc.get("close", last_price)
                change = last_price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0
                
                # Check if market is open by looking at last_trade_time
                # If last trade was within 5 minutes, market is likely open
                last_trade_time = data.get("last_trade_time")
                market_open = False
                if last_trade_time:
                    if isinstance(last_trade_time, datetime):
                        ltt = last_trade_time
                    else:
                        try:
                            ltt = datetime.fromisoformat(str(last_trade_time).replace('Z', '+00:00'))
                        except:
                            ltt = None
                    
                    if ltt:
                        # Make timezone aware if not already
                        if ltt.tzinfo is None:
                            ltt = ist.localize(ltt)
                        # Market is open if last trade was within 5 minutes
                        market_open = (now - ltt) < timedelta(minutes=5)
                
                result.append({
                    "symbol": symbol,
                    "name": INDEX_NAMES.get(symbol, symbol.split(":")[-1]),
                    "last_price": last_price,
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "market_open": market_open,
                    "last_trade_time": str(last_trade_time) if last_trade_time else None
                })
        
        logger.debug(f"Returning {len(result)} quotes")
        return {"quotes": result}
    except TokenExpiredException as e:
        logger.error(f"Token expired: {e}")
        raise HTTPException(status_code=401, detail="Token expired. Please re-login.")
    except Exception as e:
        logger.error(f"Failed to fetch indices: {e}")
        return {"quotes": []}


@router.get("/indices")
async def get_indices(request: Request):
    """Get live index quotes for NIFTY 50 and SENSEX (legacy endpoint).
    
    Returns real-time data for major indices to display in the header.
    """
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    from .auth import get_access_token
    
    config = Settings()
    access_token = get_access_token(request) or config.kite_access_token
    
    if not access_token:
        return {"nifty": None, "sensex": None}
    
    kite = KiteClient(
        api_key=config.kite_api_key,
        access_token=access_token,
        paper_mode=False,
        mock_mode=False
    )
    
    try:
        quotes = kite.get_quote(["NSE:NIFTY 50", "BSE:SENSEX"])
        
        nifty_data = quotes.get("NSE:NIFTY 50", {})
        sensex_data = quotes.get("BSE:SENSEX", {})
        
        result = {
            "nifty": None,
            "sensex": None
        }
        
        if nifty_data:
            ohlc = nifty_data.get("ohlc", {})
            last_price = nifty_data.get("last_price", 0)
            prev_close = ohlc.get("close", last_price)
            change = last_price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            result["nifty"] = {
                "last_price": last_price,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2)
            }
        
        if sensex_data:
            ohlc = sensex_data.get("ohlc", {})
            last_price = sensex_data.get("last_price", 0)
            prev_close = ohlc.get("close", last_price)
            change = last_price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            result["sensex"] = {
                "last_price": last_price,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2)
            }
        
        return result
    except Exception as e:
        logger.error(f"Failed to fetch indices: {e}")
        return {"nifty": None, "sensex": None}


# ============== Account & Margins ==============

@router.get("/account/summary")
async def get_account_summary(request: Request):
    """Get account summary with margins, cash, and utilization.
    
    Returns:
        - total_margin: Total available margin (equity + commodity)
        - used_margin: Total margin utilized
        - available_margin: Margin available for new positions
        - cash_available: Cash balance available
        - margin_utilization_pct: Percentage of margin used
    """
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    from .auth import get_access_token
    
    config = Settings()
    access_token = get_access_token(request) or config.kite_access_token
    
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    kite = KiteClient(
        api_key=config.kite_api_key,
        access_token=access_token,
        paper_mode=False,
        mock_mode=False
    )
    
    try:
        margins = kite.get_margins()
        
        # Kite margin structure:
        # equity/commodity:
        #   - net: Available margin (after considering collateral, cash, etc.)
        #   - available:
        #       - adhoc_margin, cash, opening_balance, live_balance, collateral, intraday_payin
        #   - utilised:
        #       - debits, exposure, m2m_realised, m2m_unrealised, option_premium, payout,
        #       - span, holding_sales, turnover, liquid_collateral, stock_collateral, delivery
        
        # Extract equity segment
        equity = margins.get("equity", {})
        equity_available = equity.get("available", {})
        equity_utilised = equity.get("utilised", {})
        
        # Extract commodity segment (for MCX)
        commodity = margins.get("commodity", {})
        commodity_available = commodity.get("available", {})
        commodity_utilised = commodity.get("utilised", {})
        
        # Available margin = net (this is what Kite shows as "Available margin")
        equity_net = equity.get("net", 0)
        commodity_net = commodity.get("net", 0)
        
        # Used margin components from utilised
        equity_span = equity_utilised.get("span", 0)
        equity_exposure = equity_utilised.get("exposure", 0)
        equity_delivery = equity_utilised.get("delivery", 0)
        equity_option_premium = equity_utilised.get("option_premium", 0)
        equity_debits = equity_utilised.get("debits", 0)
        
        commodity_span = commodity_utilised.get("span", 0)
        commodity_exposure = commodity_utilised.get("exposure", 0)
        commodity_delivery = commodity_utilised.get("delivery", 0)
        
        # Used margin = SPAN + Exposure + Delivery (main margin components)
        equity_used = equity_span + equity_exposure + equity_delivery
        commodity_used = commodity_span + commodity_exposure + commodity_delivery
        
        # Cash and collateral
        equity_cash = equity_available.get("cash", 0)
        equity_collateral = equity_available.get("collateral", 0)
        equity_opening = equity_available.get("opening_balance", 0)
        
        commodity_cash = commodity_available.get("cash", 0)
        commodity_collateral = commodity_available.get("collateral", 0)
        
        # Totals
        total_available = equity_net + commodity_net
        total_used = equity_used + commodity_used
        total_cash = equity_cash + commodity_cash
        total_collateral = equity_collateral + commodity_collateral
        
        # Total margin = available + used
        total_margin = total_available + total_used
        
        # Utilization percentage
        utilization_pct = (total_used / total_margin * 100) if total_margin > 0 else 0
        
        return {
            "total_margin": round(total_margin, 2),
            "used_margin": round(total_used, 2),
            "available_margin": round(total_available, 2),
            "cash_available": round(total_cash, 2),
            "collateral": round(total_collateral, 2),
            "opening_balance": round(equity_opening, 2),
            "margin_utilization_pct": round(utilization_pct, 2),
            "segments": {
                "equity": {
                    "available": round(equity_net, 2),
                    "used": round(equity_used, 2),
                    "cash": round(equity_cash, 2),
                    "collateral": round(equity_collateral, 2),
                    "span": round(equity_span, 2),
                    "exposure": round(equity_exposure, 2),
                    "delivery": round(equity_delivery, 2),
                    "option_premium": round(equity_option_premium, 2)
                },
                "commodity": {
                    "available": round(commodity_net, 2),
                    "used": round(commodity_used, 2),
                    "cash": round(commodity_cash, 2),
                    "collateral": round(commodity_collateral, 2),
                    "span": round(commodity_span, 2),
                    "exposure": round(commodity_exposure, 2)
                }
            }
        }
    except Exception as e:
        logger.error(f"Failed to fetch account summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions/with-margins")
async def get_positions_with_margins(request: Request):
    """Get positions with margin data for each position.
    
    Each position includes:
        - margin_used: Estimated margin for this position
        - margin_pct: Percentage of total margin used by this position
        - pnl_on_margin_pct: P&L as percentage of margin used
    """
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    from .auth import get_access_token
    from ..services.pnl_calculator import PnLCalculator
    
    config = Settings()
    access_token = get_access_token(request) or config.kite_access_token
    
    if not access_token:
        return {"positions": [], "account": {}}
    
    kite = KiteClient(
        api_key=config.kite_api_key,
        access_token=access_token,
        paper_mode=False,
        mock_mode=False
    )
    
    try:
        # Fetch positions and margins
        positions_data = kite.get_positions()
        net_positions = positions_data.get("net", [])
        margins = kite.get_margins()
        
        # Calculate total margin from account
        equity = margins.get("equity", {})
        commodity = margins.get("commodity", {})
        equity_net = equity.get("net", 0)
        commodity_net = commodity.get("net", 0)
        
        equity_utilised = equity.get("utilised", {})
        commodity_utilised = commodity.get("utilised", {})
        
        # Used margin = SPAN + Exposure + Delivery
        equity_used = (equity_utilised.get("span", 0) + 
                      equity_utilised.get("exposure", 0) + 
                      equity_utilised.get("delivery", 0))
        commodity_used = (commodity_utilised.get("span", 0) + 
                         commodity_utilised.get("exposure", 0) + 
                         commodity_utilised.get("delivery", 0))
        
        total_available = equity_net + commodity_net
        total_used = equity_used + commodity_used
        total_margin = total_available + total_used
        
        # Build order list for margin calculation via Kite API
        orders_for_margin = []
        position_map = {}  # Map tradingsymbol to position data
        
        for p in net_positions:
            qty = p.get("quantity", 0)
            if qty == 0:
                continue
            
            tradingsymbol = p.get("tradingsymbol", "")
            exchange = p.get("exchange", "")
            product = p.get("product", "NRML")
            last_price = p.get("last_price", 0)
            
            position_map[tradingsymbol] = p
            
            # Build order params for margin calculation
            # We simulate the order that would create this position
            orders_for_margin.append({
                "exchange": exchange,
                "tradingsymbol": tradingsymbol,
                "transaction_type": "SELL" if qty < 0 else "BUY",
                "variety": "regular",
                "product": product,
                "order_type": "MARKET",
                "quantity": abs(qty),
                "price": 0
            })
        
        # Get actual margins from Kite API
        margin_results = []
        try:
            if orders_for_margin:
                margin_results = kite.get_order_margins(orders_for_margin)
        except Exception as e:
            logger.warning(f"Failed to get order margins, using fallback: {e}")
        
        # Create margin lookup by tradingsymbol
        margin_lookup = {}
        if margin_results:
            for i, order in enumerate(orders_for_margin):
                if i < len(margin_results):
                    margin_data = margin_results[i]
                    # Total margin = SPAN + Exposure + Additional (if any)
                    total_order_margin = margin_data.get("total", 0)
                    margin_lookup[order["tradingsymbol"]] = total_order_margin
        
        # Process positions
        result = []
        total_position_margin = 0
        
        for p in net_positions:
            qty = p.get("quantity", 0)
            if qty == 0:
                continue
            
            instrument_token = p.get("instrument_token", 0)
            exchange = p.get("exchange", "")
            tradingsymbol = p.get("tradingsymbol", "")
            avg_price = p.get("average_price", 0)
            last_price = p.get("last_price", 0)
            pnl = p.get("pnl", 0)
            product = p.get("product", "NRML")
            
            # Use actual margin from Kite API if available, otherwise estimate
            if tradingsymbol in margin_lookup:
                position_margin = margin_lookup[tradingsymbol]
            else:
                # Fallback estimation
                notional_value = abs(qty) * last_price
                
                if exchange == "MCX":
                    multiplier = PnLCalculator._get_mcx_multiplier(tradingsymbol)
                    notional_value = abs(qty) * last_price * multiplier
                    margin_pct_estimate = 0.05
                elif exchange == "NFO":
                    if "PE" in tradingsymbol or "CE" in tradingsymbol:
                        if qty < 0:
                            margin_pct_estimate = 0.15
                        else:
                            margin_pct_estimate = 0
                            notional_value = abs(qty) * avg_price
                    else:
                        margin_pct_estimate = 0.12
                else:
                    margin_pct_estimate = 0.20 if product == "MIS" else 1.0
                
                position_margin = notional_value * margin_pct_estimate if margin_pct_estimate > 0 else notional_value
            
            total_position_margin += position_margin
            
            # Calculate P&L percentage on margin
            pnl_on_margin_pct = (pnl / position_margin * 100) if position_margin > 0 else 0
            
            result.append({
                "id": str(instrument_token),
                "tradingsymbol": tradingsymbol,
                "instrument_token": instrument_token,
                "exchange": exchange,
                "quantity": qty,
                "average_price": avg_price,
                "last_price": last_price,
                "pnl": pnl,
                "pnl_pct": (pnl / (avg_price * abs(qty)) * 100) if avg_price and qty else 0,
                "product": product,
                "source": "LIVE",
                "margin_used": round(position_margin, 2),
                "margin_pct": 0,  # Will be calculated after we have total
                "pnl_on_margin_pct": round(pnl_on_margin_pct, 2)
            })
        
        # Calculate margin percentage for each position (as % of total margin)
        for pos in result:
            pos["margin_pct"] = round((pos["margin_used"] / total_margin * 100) if total_margin > 0 else 0, 2)
        
        return {
            "positions": result,
            "account": {
                "total_margin": round(total_margin, 2),
                "used_margin": round(total_used, 2),
                "available_margin": round(total_available, 2),
                "margin_utilization_pct": round((total_used / total_margin * 100) if total_margin > 0 else 0, 2)
            },
            "total_position_margin": round(total_position_margin, 2)
        }
    except Exception as e:
        logger.error(f"Failed to fetch positions with margins: {e}")
        return {"positions": [], "account": {}}


# ============== Strategy Views ==============

@router.get("/positions/by-strategy")
async def get_positions_by_strategy():
    """Get positions grouped by strategy type with aggregated metrics."""
    from ..database.repository import Repository
    
    try:
        repo = Repository()
        strategies_by_type = repo.get_strategies_by_type()
        
        result = []
        for strategy_type, data in strategies_by_type.items():
            result.append({
                "strategy_type": strategy_type,
                "open_count": data["open_count"],
                "closed_count": data["closed_count"],
                "total_pnl": data["total_pnl"],
                "unrealized_pnl": data["unrealized_pnl"],
                "win_rate": data["win_rate"],
                "winning_trades": data["winning_trades"],
                "losing_trades": data["losing_trades"],
                "positions": [
                    {
                        "id": str(p.id),
                        "instrument": p.instrument,
                        "entry_price": float(p.entry_price),
                        "current_pnl": float(p.current_pnl or 0),
                        "current_pnl_pct": float(p.current_pnl_pct or 0),
                        "status": p.status,
                        "source": p.source,
                        "entry_timestamp": p.entry_timestamp.isoformat() if p.entry_timestamp else None,
                        "expiry": p.expiry.isoformat() if p.expiry else None
                    }
                    for p in data["positions"]
                ]
            })
        
        return {"strategies": result}
    except Exception as e:
        logger.error(f"Failed to fetch strategies by type: {e}")
        return {"strategies": []}


@router.get("/strategies")
async def get_strategies(
    status: str = None,
    source: str = None,
    limit: int = 100
):
    """Get strategies with their trades and calculated P&L."""
    from ..database.models import Strategy, StrategyTrade, get_session
    from ..services.pnl_calculator import PnLCalculator
    
    try:
        session = get_session()
        
        query = session.query(Strategy)
        if status:
            query = query.filter(Strategy.status == status)
        if source:
            query = query.filter(Strategy.source == source)
        
        strategies = query.order_by(Strategy.created_at.desc()).limit(limit).all()
        
        result = []
        for s in strategies:
            # Calculate aggregate P&L from trades
            total_unrealized_pnl = 0
            total_realized_pnl = 0
            trades_data = []
            
            for trade in s.trades:
                # Recalculate P&L for each trade
                if trade.status == "OPEN" and trade.last_price:
                    pnl_data = PnLCalculator.calculate_position_pnl(
                        instrument_token=trade.instrument_token,
                        quantity=trade.quantity,
                        average_price=float(trade.entry_price),
                        last_price=float(trade.last_price),
                        exchange=trade.exchange
                    )
                    total_unrealized_pnl += pnl_data["pnl"]
                else:
                    total_unrealized_pnl += float(trade.unrealized_pnl or 0)
                
                total_realized_pnl += float(trade.realized_pnl or 0)
                
                trades_data.append({
                    "id": trade.id,
                    "tradingsymbol": trade.tradingsymbol,
                    "instrument_token": trade.instrument_token,
                    "exchange": trade.exchange,
                    "quantity": trade.quantity,
                    "entry_price": float(trade.entry_price),
                    "last_price": float(trade.last_price) if trade.last_price else None,
                    "unrealized_pnl": float(trade.unrealized_pnl or 0),
                    "realized_pnl": float(trade.realized_pnl or 0),
                    "pnl_pct": float(trade.pnl_pct or 0),
                    "status": trade.status,
                    "entry_time": trade.entry_time.isoformat() if trade.entry_time else None
                })
            
            result.append({
                "id": str(s.id),
                "name": s.name,
                "label": s.label,
                "status": s.status,
                "source": s.source or "LIVE",
                "unrealized_pnl": total_unrealized_pnl,
                "realized_pnl": total_realized_pnl,
                "total_pnl": total_unrealized_pnl + total_realized_pnl,
                "trades_count": len(s.trades),
                "trades": trades_data,
                "notes": s.notes,
                "tags": s.tags,
                "created_at": s.created_at.isoformat() if s.created_at else None
            })
        
        return result
    except Exception as e:
        logger.error(f"Failed to fetch strategies: {e}")
        return []


@router.get("/strategies/performance")
async def get_strategy_performance(days: int = 30):
    """Get strategy performance summary."""
    from ..database.repository import Repository
    from datetime import timedelta
    
    try:
        repo = Repository()
        to_date = date.today()
        from_date = to_date - timedelta(days=days)
        
        perf_records = repo.get_strategy_performance(from_date, to_date)
        
        # Also get current aggregates
        strategies_by_type = repo.get_strategies_by_type()
        
        return {
            "period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
            "by_strategy": [
                {
                    "strategy_type": stype,
                    "open_count": data["open_count"],
                    "closed_count": data["closed_count"],
                    "total_pnl": data["total_pnl"],
                    "unrealized_pnl": data["unrealized_pnl"],
                    "win_rate": data["win_rate"]
                }
                for stype, data in strategies_by_type.items()
            ],
            "daily_records": [
                {
                    "date": p.date.isoformat(),
                    "strategy_type": p.strategy_type,
                    "realized_pnl": float(p.realized_pnl or 0),
                    "trades_closed": p.trades_closed,
                    "win_rate": float(p.win_rate or 0)
                }
                for p in perf_records
            ]
        }
    except Exception as e:
        logger.error(f"Failed to fetch strategy performance: {e}")
        return {"period": {}, "by_strategy": [], "daily_records": []}


# ============== Custom Strategy Management ==============

class CreateStrategyRequest(BaseModel):
    name: str
    label: Optional[str] = None
    position_ids: List[str]
    portfolio_id: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class UpdateStrategyPositionsRequest(BaseModel):
    add: Optional[List[str]] = None
    remove: Optional[List[str]] = None


@router.post("/strategies")
async def create_strategy(request: CreateStrategyRequest, req: Request):
    """Create a new strategy from selected positions.
    
    Position IDs are instrument tokens from Kite. We:
    1. Sync positions to broker_positions table
    2. Create StrategyTrade records linking to broker positions
    3. StrategyTrade is the key model for strategy-level P&L tracking
    """
    from ..database.models import Strategy, StrategyTrade, BrokerPosition, get_session
    from .auth import get_access_token
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    from ..services.instrument_cache import instrument_cache
    from ..services.pnl_calculator import PnLCalculator
    
    config = Settings()
    
    try:
        session = get_session()
        
        # Fetch current positions from Kite to get full details
        access_token = get_access_token(req) or config.kite_access_token
        kite = KiteClient(
            api_key=config.kite_api_key,
            access_token=access_token,
            paper_mode=False,
            mock_mode=False
        )
        positions_data = kite.get_positions()
        net_positions = positions_data.get("net", [])
        
        # Create a lookup by instrument_token (as string, since that's what frontend sends)
        kite_positions = {str(p.get("instrument_token")): p for p in net_positions}
        
        # Create strategy first
        strategy = Strategy(
            name=request.name,
            label=request.label,
            portfolio_id=request.portfolio_id,
            notes=request.notes,
            tags=request.tags,
            status="OPEN"
        )
        session.add(strategy)
        session.flush()
        
        # Process each position
        trades_created = 0
        for pos_id in request.position_ids:
            kite_pos = kite_positions.get(pos_id)
            if not kite_pos:
                logger.warning(f"Position {pos_id} not found in Kite positions")
                continue
            
            instrument_token = kite_pos.get("instrument_token", 0)
            exchange = kite_pos.get("exchange", "NFO")
            quantity = kite_pos.get("quantity", 0)
            avg_price = kite_pos.get("average_price", 0)
            last_price = kite_pos.get("last_price", 0)
            
            # Sync to broker_positions table
            existing_bp = session.query(BrokerPosition).filter_by(id=pos_id).first()
            if not existing_bp:
                bp = BrokerPosition(
                    id=pos_id,
                    tradingsymbol=kite_pos.get("tradingsymbol", ""),
                    instrument_token=instrument_token,
                    exchange=exchange,
                    quantity=quantity,
                    average_price=avg_price,
                    last_price=last_price,
                    pnl=kite_pos.get("pnl", 0),
                    product=kite_pos.get("product", "NRML"),
                    source="LIVE"
                )
                session.add(bp)
                session.flush()
            
            # Get instrument info for the trade
            inst_info = instrument_cache.get(instrument_token) or {}
            
            # Calculate P&L
            pnl_data = PnLCalculator.calculate_position_pnl(
                instrument_token=instrument_token,
                quantity=quantity,
                average_price=avg_price,
                last_price=last_price,
                exchange=exchange
            )
            
            # Create StrategyTrade linking to this position
            trade = StrategyTrade(
                strategy_id=strategy.id,
                tradingsymbol=kite_pos.get("tradingsymbol", ""),
                instrument_token=instrument_token,
                exchange=exchange,
                instrument_type=inst_info.get("instrument_type", "FUT"),
                lot_size=inst_info.get("lot_size", 1),
                quantity=quantity,
                entry_price=avg_price,
                last_price=last_price,
                unrealized_pnl=pnl_data["pnl"],
                pnl_pct=pnl_data["pnl_pct"],
                kite_position_id=pos_id,
                source="LIVE",
                status="OPEN"
            )
            session.add(trade)
            trades_created += 1
        
        if trades_created == 0:
            session.rollback()
            raise HTTPException(status_code=400, detail="No valid positions found")
        
        session.commit()
        
        return {
            "id": strategy.id,
            "name": strategy.name,
            "trades_count": trades_created,
            "message": "Strategy created successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/strategies/{strategy_id}/positions")
async def update_strategy_positions(strategy_id: str, request: UpdateStrategyPositionsRequest):
    """Add or remove positions from a strategy."""
    from ..database.models import Strategy, StrategyPosition, get_session
    
    try:
        session = get_session()
        
        strategy = session.query(Strategy).filter_by(id=strategy_id).first()
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Add positions
        if request.add:
            for pos_id in request.add:
                existing = session.query(StrategyPosition).filter_by(
                    strategy_id=strategy_id, position_id=pos_id
                ).first()
                if not existing:
                    sp = StrategyPosition(strategy_id=strategy_id, position_id=pos_id)
                    session.add(sp)
        
        # Remove positions
        if request.remove:
            for pos_id in request.remove:
                session.query(StrategyPosition).filter_by(
                    strategy_id=strategy_id, position_id=pos_id
                ).delete()
        
        session.commit()
        
        return {"message": "Strategy positions updated", "strategy_id": strategy_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update strategy positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategies/{strategy_id}/close")
async def close_strategy(strategy_id: str, reason: str = "MANUAL"):
    """Close a strategy and record realized P&L."""
    from ..database.models import Strategy, get_session
    
    try:
        session = get_session()
        
        strategy = session.query(Strategy).filter_by(id=strategy_id).first()
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        strategy.status = "CLOSED"
        strategy.closed_at = datetime.now()
        strategy.close_reason = reason
        strategy.realized_pnl = strategy.unrealized_pnl  # Move unrealized to realized
        strategy.unrealized_pnl = 0
        
        session.commit()
        
        return {
            "message": "Strategy closed",
            "strategy_id": strategy_id,
            "realized_pnl": float(strategy.realized_pnl or 0)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to close strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies/{strategy_id}")
async def get_strategy_detail(strategy_id: str):
    """Get detailed strategy info with trades."""
    from ..database.models import Strategy, get_session
    from ..services.pnl_calculator import PnLCalculator
    
    try:
        session = get_session()
        
        strategy = session.query(Strategy).filter_by(id=strategy_id).first()
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Calculate aggregate P&L from trades
        total_unrealized_pnl = 0
        total_realized_pnl = 0
        trades_data = []
        
        for trade in strategy.trades:
            # Recalculate P&L for each trade
            if trade.status == "OPEN" and trade.last_price:
                pnl_data = PnLCalculator.calculate_position_pnl(
                    instrument_token=trade.instrument_token,
                    quantity=trade.quantity,
                    average_price=float(trade.entry_price),
                    last_price=float(trade.last_price),
                    exchange=trade.exchange
                )
                total_unrealized_pnl += pnl_data["pnl"]
                trade_pnl = pnl_data["pnl"]
                trade_pnl_pct = pnl_data["pnl_pct"]
            else:
                trade_pnl = float(trade.unrealized_pnl or 0)
                trade_pnl_pct = float(trade.pnl_pct or 0)
                total_unrealized_pnl += trade_pnl
            
            total_realized_pnl += float(trade.realized_pnl or 0)
            
            trades_data.append({
                "id": trade.id,
                "tradingsymbol": trade.tradingsymbol,
                "instrument_token": trade.instrument_token,
                "exchange": trade.exchange,
                "instrument_type": trade.instrument_type,
                "quantity": trade.quantity,
                "entry_price": float(trade.entry_price),
                "last_price": float(trade.last_price) if trade.last_price else None,
                "unrealized_pnl": trade_pnl,
                "realized_pnl": float(trade.realized_pnl or 0),
                "pnl_pct": trade_pnl_pct,
                "status": trade.status,
                "entry_time": trade.entry_time.isoformat() if trade.entry_time else None
            })
        
        return {
            "id": strategy.id,
            "name": strategy.name,
            "label": strategy.label,
            "status": strategy.status,
            "source": strategy.source or "LIVE",
            "unrealized_pnl": total_unrealized_pnl,
            "realized_pnl": total_realized_pnl,
            "total_pnl": total_unrealized_pnl + total_realized_pnl,
            "trades_count": len(strategy.trades),
            "trades": trades_data,
            "notes": strategy.notes,
            "tags": strategy.tags,
            "created_at": strategy.created_at.isoformat() if strategy.created_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get strategy detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== Portfolio Management ==============

class CreatePortfolioRequest(BaseModel):
    name: str
    description: Optional[str] = None


@router.get("/portfolios")
async def get_portfolios():
    """Get all portfolios with aggregate metrics."""
    from ..database.models import Portfolio, get_session
    
    try:
        session = get_session()
        portfolios = session.query(Portfolio).filter_by(is_active=True).all()
        
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "realized_pnl": float(p.realized_pnl or 0),
                "unrealized_pnl": float(p.unrealized_pnl or 0),
                "total_pnl": float((p.realized_pnl or 0) + (p.unrealized_pnl or 0)),
                "strategy_count": len(p.strategies) if p.strategies else 0,
                "is_active": p.is_active
            }
            for p in portfolios
        ]
    except Exception as e:
        logger.error(f"Failed to fetch portfolios: {e}")
        return []


@router.post("/portfolios")
async def create_portfolio(request: CreatePortfolioRequest):
    """Create a new portfolio."""
    from ..database.models import Portfolio, get_session
    
    try:
        session = get_session()
        
        portfolio = Portfolio(
            name=request.name,
            description=request.description
        )
        session.add(portfolio)
        session.commit()
        
        return {
            "id": portfolio.id,
            "name": portfolio.name,
            "message": "Portfolio created successfully"
        }
    except Exception as e:
        logger.error(f"Failed to create portfolio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/portfolios/{portfolio_id}/performance")
async def get_portfolio_performance(portfolio_id: str, days: int = 30):
    """Get historical performance for a portfolio."""
    from ..database.models import Portfolio, PortfolioSnapshot, get_session
    from datetime import timedelta
    
    try:
        session = get_session()
        
        portfolio = session.query(Portfolio).filter_by(id=portfolio_id).first()
        if not portfolio:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        
        to_date = date.today()
        from_date = to_date - timedelta(days=days)
        
        snapshots = session.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.date >= from_date,
            PortfolioSnapshot.date <= to_date
        ).order_by(PortfolioSnapshot.date).all()
        
        return {
            "portfolio_id": portfolio_id,
            "portfolio_name": portfolio.name,
            "period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
            "current": {
                "realized_pnl": float(portfolio.realized_pnl or 0),
                "unrealized_pnl": float(portfolio.unrealized_pnl or 0),
                "total_pnl": float((portfolio.realized_pnl or 0) + (portfolio.unrealized_pnl or 0))
            },
            "daily_snapshots": [
                {
                    "date": s.date.isoformat(),
                    "realized_pnl": float(s.realized_pnl or 0),
                    "unrealized_pnl": float(s.unrealized_pnl or 0),
                    "total_pnl": float(s.total_pnl or 0),
                    "strategy_count": s.strategy_count,
                    "drawdown": float(s.drawdown or 0)
                }
                for s in snapshots
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get portfolio performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== Position Sync ==============

@router.post("/positions/sync")
async def sync_positions(request: Request):
    """Sync positions from broker to database."""
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    from ..database.models import BrokerPosition, get_session
    from .auth import get_access_token
    
    config = Settings()
    access_token = get_access_token(request)
    if not access_token:
        access_token = config.kite_access_token
    
    if not access_token:
        raise HTTPException(status_code=401, detail="No access token")
    
    try:
        kite = KiteClient(
            api_key=config.kite_api_key,
            access_token=access_token,
            paper_mode=False,
            mock_mode=False
        )
        
        positions_data = kite.get_positions()
        net_positions = positions_data.get("net", [])
        
        session = get_session()
        synced_count = 0
        
        for p in net_positions:
            qty = p.get("quantity", 0)
            if qty == 0:
                continue
            
            # Upsert by tradingsymbol
            existing = session.query(BrokerPosition).filter_by(
                tradingsymbol=p.get("tradingsymbol", "")
            ).first()
            
            if existing:
                existing.quantity = qty
                existing.average_price = p.get("average_price", 0)
                existing.last_price = p.get("last_price", 0)
                existing.pnl = p.get("pnl", 0)
            else:
                new_pos = BrokerPosition(
                    tradingsymbol=p.get("tradingsymbol", ""),
                    instrument_token=p.get("instrument_token", 0),
                    exchange=p.get("exchange", "NFO"),
                    quantity=qty,
                    average_price=p.get("average_price", 0),
                    last_price=p.get("last_price", 0),
                    pnl=p.get("pnl", 0),
                    product=p.get("product", ""),
                    source="LIVE"
                )
                session.add(new_pos)
            
            synced_count += 1
        
        session.commit()
        
        return {"message": f"Synced {synced_count} positions", "count": synced_count}
    except Exception as e:
        logger.error(f"Failed to sync positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== Regime ==============

@router.get("/regime/current")
async def get_current_regime(request: Request):
    """Get current market regime."""
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    from ..config.constants import NIFTY_TOKEN
    from ..services.sentinel import Sentinel
    from ..core.data_cache import DataCache
    from .auth import get_access_token
    
    config = Settings()
    
    # Get access token from session
    access_token = get_access_token(request)
    if not access_token:
        # Fall back to config token if no session
        access_token = config.kite_access_token
    
    kite = KiteClient(
        api_key=config.kite_api_key,
        access_token=access_token,
        paper_mode=True
    )
    cache = DataCache(Path("data/cache"))
    
    sentinel = Sentinel(kite, config, cache)
    regime = sentinel.process(NIFTY_TOKEN)
    
    # Build detailed explanation of regime classification
    explanation = _build_regime_explanation(regime)
    
    return {
        "regime": regime.regime.value,
        "confidence": regime.regime_confidence,
        "is_safe": regime.is_safe,
        "metrics": {
            "adx": regime.metrics.adx,
            "rsi": regime.metrics.rsi,
            "iv_percentile": regime.metrics.iv_percentile,
            "realized_vol": regime.metrics.realized_vol,
            "atr": regime.metrics.atr
        },
        "thresholds": {
            "adx_range_bound": 12,
            "adx_trend": 22,
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "rsi_neutral_low": 40,
            "rsi_neutral_high": 60,
            "iv_high": 75,
            "correlation_chaos": 0.5
        },
        "explanation": explanation,
        "safety_reasons": regime.safety_reasons,
        "event_flag": regime.event_flag,
        "event_name": regime.event_name,
        "correlations": regime.correlations,
        "timestamp": regime.timestamp.isoformat()
    }


def _build_regime_explanation(regime) -> dict:
    """Build detailed explanation of how regime was classified."""
    from ..config.thresholds import (
        ADX_RANGE_BOUND, ADX_TREND,
        RSI_OVERSOLD, RSI_OVERBOUGHT, RSI_NEUTRAL_LOW, RSI_NEUTRAL_HIGH,
        IV_HIGH, CORRELATION_CHAOS
    )
    
    steps = []
    metrics = regime.metrics
    
    # Step 1: Event check
    if regime.event_flag:
        steps.append({
            "step": 1,
            "check": "Event Calendar",
            "condition": f"Event '{regime.event_name}' within blackout period",
            "result": "TRIGGERED",
            "impact": "Forces CHAOS regime"
        })
    else:
        steps.append({
            "step": 1,
            "check": "Event Calendar",
            "condition": "No major events within 7-day blackout",
            "result": "PASSED",
            "impact": "Continue to next check"
        })
    
    # Step 2: IV Percentile check
    iv_status = "TRIGGERED" if metrics.iv_percentile > IV_HIGH else "PASSED"
    steps.append({
        "step": 2,
        "check": "IV Percentile",
        "condition": f"IV {metrics.iv_percentile:.1f}% {'>' if metrics.iv_percentile > IV_HIGH else '<='} {IV_HIGH}% threshold",
        "result": iv_status,
        "impact": "Forces CHAOS if IV too high" if iv_status == "TRIGGERED" else "Continue to next check"
    })
    
    # Step 3: Correlation check
    max_corr = max([abs(v) for v in regime.correlations.values()], default=0)
    corr_status = "TRIGGERED" if max_corr > CORRELATION_CHAOS else "PASSED"
    steps.append({
        "step": 3,
        "check": "Correlation Spike",
        "condition": f"Max correlation {max_corr:.2f} {'>' if max_corr > CORRELATION_CHAOS else '<='} {CORRELATION_CHAOS} threshold",
        "result": corr_status,
        "impact": "Forces CHAOS if correlation spike" if corr_status == "TRIGGERED" else "Continue to next check"
    })
    
    # Step 4: ADX check for Range-Bound
    adx_range = metrics.adx < ADX_RANGE_BOUND
    steps.append({
        "step": 4,
        "check": "ADX (Trend Strength)",
        "condition": f"ADX {metrics.adx:.1f} {'<' if adx_range else '>='} {ADX_RANGE_BOUND} (Range-Bound threshold)",
        "result": "LOW" if adx_range else ("HIGH" if metrics.adx > ADX_TREND else "MODERATE"),
        "impact": "Suggests Range-Bound" if adx_range else ("Suggests Trend" if metrics.adx > ADX_TREND else "Suggests Mean-Reversion")
    })
    
    # Step 5: RSI check
    rsi_neutral = RSI_NEUTRAL_LOW <= metrics.rsi <= RSI_NEUTRAL_HIGH
    rsi_extreme = metrics.rsi < RSI_OVERSOLD or metrics.rsi > RSI_OVERBOUGHT
    rsi_label = "NEUTRAL" if rsi_neutral else ("OVERSOLD" if metrics.rsi < RSI_OVERSOLD else ("OVERBOUGHT" if metrics.rsi > RSI_OVERBOUGHT else "MODERATE"))
    steps.append({
        "step": 5,
        "check": "RSI (Momentum)",
        "condition": f"RSI {metrics.rsi:.1f} in range [{RSI_NEUTRAL_LOW}-{RSI_NEUTRAL_HIGH}] neutral, <{RSI_OVERSOLD} oversold, >{RSI_OVERBOUGHT} overbought",
        "result": rsi_label,
        "impact": "Supports Range-Bound" if rsi_neutral else ("Supports Mean-Reversion" if rsi_extreme else "Neutral impact")
    })
    
    # Final decision explanation
    regime_value = regime.regime.value
    if regime_value == "CHAOS":
        decision = "CHAOS triggered by: " + ", ".join(regime.safety_reasons) if regime.safety_reasons else "High uncertainty conditions"
    elif regime_value == "RANGE_BOUND":
        decision = f"Low ADX ({metrics.adx:.1f} < {ADX_RANGE_BOUND}) + Neutral RSI ({metrics.rsi:.1f}) + Moderate IV ({metrics.iv_percentile:.1f}%)"
    elif regime_value == "MEAN_REVERSION":
        decision = f"Moderate ADX ({metrics.adx:.1f}) + Extreme RSI ({metrics.rsi:.1f}) suggests reversal opportunity"
    elif regime_value == "TREND":
        decision = f"High ADX ({metrics.adx:.1f} > {ADX_TREND}) indicates strong directional momentum"
    else:
        decision = "Unable to classify with confidence"
    
    return {
        "steps": steps,
        "decision": decision,
        "summary": f"Regime: {regime_value} with {regime.regime_confidence*100:.0f}% confidence"
    }
