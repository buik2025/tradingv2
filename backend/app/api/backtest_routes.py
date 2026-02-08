"""
Backtest API routes for Trading System v2.0

Provides endpoints for:
- Running strategy backtests
- Monte Carlo stress testing
- Downloading historical data
- Viewing backtest results
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from pathlib import Path
from loguru import logger
import pandas as pd

router = APIRouter(prefix="/backtest", tags=["backtest"])


# ============== Request/Response Models ==============

class StrategyBacktestRequest(BaseModel):
    """Request for running a strategy backtest."""
    # Data source
    data_file: Optional[str] = None
    symbol: str = "NIFTY"
    asset_class: str = Field(default="equity", description="equity, commodity, or multi_asset")
    
    # Date range for backtest
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    interval: str = Field(default="day", description="day, 5minute, 15minute, 60minute")
    
    # Strategy selection
    strategies: List[str] = Field(default=["iron_condor"])
    
    # Capital & sizing
    initial_capital: float = Field(default=1000000, ge=100000)
    position_size_pct: float = Field(default=0.02, ge=0.01, le=0.10)
    max_positions: int = Field(default=3, ge=1, le=10)
    
    # Risk limits
    max_margin_pct: float = Field(default=0.40, ge=0.1, le=0.8)
    max_loss_per_trade: float = Field(default=0.01, ge=0.005, le=0.05)
    max_daily_loss: float = Field(default=0.03, ge=0.01, le=0.10)
    
    # Execution assumptions
    slippage_pct: float = Field(default=0.001, ge=0, le=0.01)
    brokerage_pct: float = Field(default=0.0003, ge=0, le=0.01)
    commission_tax_pct: float = Field(default=0.0008, ge=0, le=0.01, description="Commission and tax as decimal (0.0008 = 0.08pct)")


class MonteCarloRequest(BaseModel):
    """Request for Monte Carlo stress test."""
    data_file: Optional[str] = None
    symbol: str = "NIFTY"
    strategies: List[str] = Field(default=["iron_condor"])
    initial_capital: float = Field(default=1000000)
    num_simulations: int = Field(default=1000, ge=100, le=10000)


class TradeResult(BaseModel):
    """Single trade result."""
    id: str
    strategy_type: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    holding_days: int
    regime_at_entry: str
    regime_at_exit: str


class StrategyMetrics(BaseModel):
    """Metrics for a single strategy."""
    total_trades: int
    total_pnl: float
    win_rate: float
    avg_pnl: float
    profit_factor: float


class RegimeMetrics(BaseModel):
    """Metrics by regime."""
    total_trades: int
    total_pnl: float
    win_rate: float


class BacktestResponse(BaseModel):
    """Complete backtest response."""
    # Summary
    total_return: float
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_duration: int
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    expectancy: float
    
    # Trade stats
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_holding_days: float
    
    # Breakdown
    by_strategy: Dict[str, StrategyMetrics]
    by_regime: Dict[str, RegimeMetrics]
    
    # Time series (sampled for response size)
    equity_curve: List[float]
    drawdown_curve: List[float]
    
    # Regime distribution
    regime_distribution: Dict[str, int]
    
    # Trades (limited)
    trades: List[TradeResult]


class MonteCarloResponse(BaseModel):
    """Monte Carlo stress test response."""
    # Base backtest summary
    base_total_return_pct: float
    base_sharpe_ratio: float
    base_max_drawdown: float
    base_total_trades: int
    
    # Monte Carlo results
    num_simulations: int
    passed: bool
    failure_rate: float
    avg_max_drawdown: float
    worst_drawdown: float
    best_drawdown: float
    avg_return: float
    median_return: float
    return_5th_percentile: float
    return_95th_percentile: float
    return_std: float


class DataDownloadRequest(BaseModel):
    """Request for downloading historical data."""
    symbol: str = Field(default="NIFTY", description="Symbol to download (NIFTY, BANKNIFTY, GOLD, CRUDE, SILVER, or ALL)")
    interval: str = Field(default="day", description="day, 60minute, 15minute, 5minute, or ALL")
    max_days: Optional[int] = Field(default=None, description="Override max days (uses API limits if not specified)")


class DataFileInfo(BaseModel):
    """Information about a data file."""
    filename: str
    size_kb: float
    rows: Optional[int] = None
    date_range: Optional[str] = None


# ============== Endpoints ==============

@router.post("/run", response_model=BacktestResponse)
async def run_strategy_backtest(request: StrategyBacktestRequest):
    """
    Run a comprehensive strategy backtest.
    
    Integrates all agents (Sentinel, Strategist, Treasury) to simulate
    realistic trading with regime detection and risk management.
    """
    from ..services.strategy_backtester import (
        StrategyBacktester, StrategyBacktestConfig, BacktestMode
    )
    from ..services.data_loader import DataLoader
    
    # Load data - auto-download if not available
    data = await _load_backtest_data(
        data_file=request.data_file,
        symbol=request.symbol,
        start_date=request.start_date,
        end_date=request.end_date,
        interval=request.interval
    )
    if data.empty:
        raise HTTPException(
            status_code=400, 
            detail=f"No data available for {request.symbol}. Please ensure you have historical data or check your Kite API credentials."
        )
    
    # Configure backtest
    config = StrategyBacktestConfig(
        initial_capital=request.initial_capital,
        position_size_pct=request.position_size_pct,
        max_positions=request.max_positions,
        max_margin_pct=request.max_margin_pct,
        strategies=request.strategies,
        asset_class=request.asset_class,
        symbol=request.symbol,
        start_date=request.start_date,
        end_date=request.end_date,
        slippage_pct=request.slippage_pct,
        brokerage_pct=request.brokerage_pct,
        commission_tax_pct=request.commission_tax_pct,
        max_loss_per_trade=request.max_loss_per_trade,
        max_daily_loss=request.max_daily_loss
    )
    
    # Run backtest
    backtester = StrategyBacktester(config)
    result = backtester.run(data, BacktestMode.STANDARD)
    
    # Sample equity curve for response (max 500 points)
    equity_sampled = _sample_series(result.equity_curve, 500)
    drawdown_sampled = _sample_series(result.drawdown_curve, 500)
    
    # Convert trades to response format (limit to 100)
    trades_response = [
        TradeResult(
            id=t.id,
            strategy_type=t.strategy_type,
            entry_date=t.entry_date.isoformat() if hasattr(t.entry_date, 'isoformat') else str(t.entry_date),
            exit_date=t.exit_date.isoformat() if hasattr(t.exit_date, 'isoformat') else str(t.exit_date),
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            pnl=t.pnl,
            pnl_pct=t.pnl_pct,
            exit_reason=t.exit_reason,
            holding_days=t.holding_days,
            regime_at_entry=t.regime_at_entry,
            regime_at_exit=t.regime_at_exit
        )
        for t in result.trades[:100]
    ]
    
    # Convert strategy metrics
    by_strategy = {
        k: StrategyMetrics(**v) for k, v in result.by_strategy.items()
    }
    
    # Convert regime metrics
    by_regime = {
        k: RegimeMetrics(**v) for k, v in result.by_regime.items()
    }
    
    return BacktestResponse(
        total_return=result.total_return,
        total_return_pct=result.total_return_pct,
        sharpe_ratio=result.sharpe_ratio,
        sortino_ratio=result.sortino_ratio,
        max_drawdown=result.max_drawdown,
        max_drawdown_duration=result.max_drawdown_duration,
        win_rate=result.win_rate,
        profit_factor=result.profit_factor,
        avg_win=result.avg_win,
        avg_loss=result.avg_loss,
        expectancy=result.expectancy,
        total_trades=result.total_trades,
        winning_trades=result.winning_trades,
        losing_trades=result.losing_trades,
        avg_holding_days=result.avg_holding_days,
        by_strategy=by_strategy,
        by_regime=by_regime,
        equity_curve=equity_sampled,
        drawdown_curve=drawdown_sampled,
        regime_distribution=result.regime_distribution,
        trades=trades_response
    )


@router.post("/monte-carlo", response_model=MonteCarloResponse)
async def run_monte_carlo(request: MonteCarloRequest):
    """
    Run Monte Carlo stress test on a strategy.
    
    Shuffles trade order to test strategy robustness under
    different market sequences.
    """
    from ..services.strategy_backtester import (
        StrategyBacktester, StrategyBacktestConfig
    )
    
    # Load data
    data = await _load_backtest_data(request.data_file, request.symbol)
    if data.empty:
        raise HTTPException(status_code=400, detail="No data available")
    
    # Configure
    config = StrategyBacktestConfig(
        initial_capital=request.initial_capital,
        strategies=request.strategies,
        num_simulations=request.num_simulations
    )
    
    # Run Monte Carlo
    backtester = StrategyBacktester(config)
    mc_result = backtester.run_monte_carlo(data, request.num_simulations)
    
    if "error" in mc_result:
        raise HTTPException(status_code=400, detail=mc_result["error"])
    
    base = mc_result["base_result"]
    
    return MonteCarloResponse(
        base_total_return_pct=base.total_return_pct,
        base_sharpe_ratio=base.sharpe_ratio,
        base_max_drawdown=base.max_drawdown,
        base_total_trades=base.total_trades,
        num_simulations=mc_result["num_simulations"],
        passed=mc_result["passed"],
        failure_rate=mc_result["failure_rate"],
        avg_max_drawdown=mc_result["avg_max_drawdown"],
        worst_drawdown=mc_result["worst_drawdown"],
        best_drawdown=mc_result["best_drawdown"],
        avg_return=mc_result["avg_return"],
        median_return=mc_result["median_return"],
        return_5th_percentile=mc_result["return_5th_percentile"],
        return_95th_percentile=mc_result["return_95th_percentile"],
        return_std=mc_result["return_std"]
    )


@router.get("/strategies")
async def get_available_strategies():
    """Get list of available strategies for backtesting."""
    return {
        "strategies": [
            # Short Volatility Strategies
            {
                "id": "iron_condor",
                "name": "Iron Condor",
                "description": "Neutral strategy for range-bound markets. Sells OTM call and put spreads.",
                "regime": "RANGE_BOUND",
                "risk_profile": "Defined risk, limited profit",
                "category": "short_vol",
                "asset_class": "equity"
            },
            {
                "id": "jade_lizard",
                "name": "Jade Lizard",
                "description": "Bullish-neutral strategy. Short put + short call spread.",
                "regime": "RANGE_BOUND, CAUTION",
                "risk_profile": "Defined risk on upside, unlimited on downside",
                "category": "short_vol",
                "asset_class": "equity"
            },
            {
                "id": "butterfly",
                "name": "Iron Butterfly",
                "description": "Neutral strategy expecting low volatility. ATM short straddle + OTM wings.",
                "regime": "RANGE_BOUND",
                "risk_profile": "Defined risk, higher reward than IC",
                "category": "short_vol",
                "asset_class": "equity"
            },
            # Directional Strategies
            {
                "id": "bwb",
                "name": "Broken Wing Butterfly",
                "description": "Directional butterfly with skewed risk. For mean-reversion plays.",
                "regime": "MEAN_REVERSION",
                "risk_profile": "Asymmetric risk/reward",
                "category": "directional",
                "asset_class": "equity"
            },
            {
                "id": "risk_reversal",
                "name": "Risk Reversal",
                "description": "Directional strategy. Long call + short put (or vice versa).",
                "regime": "MEAN_REVERSION",
                "risk_profile": "Unlimited profit, defined risk",
                "category": "directional",
                "asset_class": "equity"
            },
            {
                "id": "range_forward",
                "name": "Range Forward",
                "description": "Mean-reversion at ATR bounds with protective hedge. Entry when price deviates >1.5x ATR.",
                "regime": "RANGE_BOUND, MEAN_REVERSION",
                "risk_profile": "Defined risk with hedge",
                "category": "directional",
                "asset_class": "equity, commodity"
            },
            # Commodity Strategies
            {
                "id": "commodity_mean_reversion",
                "name": "Commodity Mean Reversion",
                "description": "Mean-reversion strategy for Gold/Crude. Entry on extreme RSI with low ADX.",
                "regime": "MEAN_REVERSION",
                "risk_profile": "Defined risk",
                "category": "directional",
                "asset_class": "commodity"
            },
            {
                "id": "pairs_trade",
                "name": "Pairs Trade",
                "description": "Market-neutral strategy for correlated assets (Gold/Silver, NIFTY/BANKNIFTY).",
                "regime": "MEAN_REVERSION",
                "risk_profile": "Low risk, market neutral",
                "category": "directional",
                "asset_class": "multi_asset"
            },
            # Hedging Strategies
            {
                "id": "delta_hedge",
                "name": "Delta Hedge",
                "description": "Futures overlay to neutralize portfolio delta during trends.",
                "regime": "TREND",
                "risk_profile": "Protective, reduces directional exposure",
                "category": "hedge",
                "asset_class": "equity, commodity"
            },
            {
                "id": "protective_put",
                "name": "Protective Put",
                "description": "Long put to hedge existing long exposure. Best when IV is low.",
                "regime": "MEAN_REVERSION, TREND",
                "risk_profile": "Insurance cost, unlimited upside",
                "category": "hedge",
                "asset_class": "equity, commodity"
            },
            {
                "id": "collar",
                "name": "Collar",
                "description": "Long put + short call for hedged exposure with capped upside.",
                "regime": "RANGE_BOUND, CAUTION",
                "risk_profile": "Near zero cost, limited risk and reward",
                "category": "hedge",
                "asset_class": "equity"
            }
        ]
    }


@router.post("/data/download")
async def download_data_endpoint(request: DataDownloadRequest, background_tasks: BackgroundTasks):
    """
    Download historical data for backtesting.
    
    Supports:
    - Single symbol or ALL symbols
    - Single interval or ALL intervals
    - Maximum available data per Kite API limits
    """
    from ..config.constants import NIFTY_TOKEN, BANKNIFTY_TOKEN, INDIA_VIX_TOKEN
    
    # All supported instruments
    all_instruments = {
        "NIFTY": NIFTY_TOKEN,
        "BANKNIFTY": BANKNIFTY_TOKEN,
        "INDIAVIX": INDIA_VIX_TOKEN,
        "GOLD": 53505799,
        "SILVER": 53505031,
        "CRUDE": 53496327,
    }
    
    # Max days per interval (Kite limits)
    interval_max_days = {
        "day": 2000,
        "60minute": 400,
        "15minute": 200,
        "5minute": 100,
        "minute": 60,  # 1-minute data - ~60 days max
    }
    
    all_intervals = ["day", "60minute", "15minute", "5minute", "minute"]
    
    # Determine which symbols to download
    if request.symbol.upper() == "ALL":
        symbols_to_download = list(all_instruments.keys())
    else:
        symbol = request.symbol.upper()
        if symbol not in all_instruments:
            raise HTTPException(
                status_code=400, 
                detail=f"Unknown symbol: {request.symbol}. Available: {list(all_instruments.keys())} or ALL"
            )
        symbols_to_download = [symbol]
    
    # Determine which intervals to download
    if request.interval.upper() == "ALL":
        intervals_to_download = all_intervals
    else:
        if request.interval not in interval_max_days:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown interval: {request.interval}. Available: {all_intervals} or ALL"
            )
        intervals_to_download = [request.interval]
    
    # Schedule downloads
    download_count = 0
    for symbol in symbols_to_download:
        token = all_instruments[symbol]
        for interval in intervals_to_download:
            max_days = request.max_days or interval_max_days[interval]
            background_tasks.add_task(
                _download_data_task,
                symbol,
                token,
                max_days,
                interval
            )
            download_count += 1
    
    return {
        "message": f"Download started for {len(symbols_to_download)} symbol(s) x {len(intervals_to_download)} interval(s)",
        "symbols": symbols_to_download,
        "intervals": intervals_to_download,
        "total_downloads": download_count,
        "status": "processing"
    }


@router.get("/data/files", response_model=List[DataFileInfo])
async def list_data_files():
    """List available data files for backtesting."""
    data_dir = Path("data")
    cache_dir = Path("data/cache")
    
    files = []
    
    # Check main data directory
    if data_dir.exists():
        for f in data_dir.glob("*.csv"):
            info = _get_file_info(f)
            if info:
                files.append(info)
    
    # Check cache directory
    if cache_dir.exists():
        for f in cache_dir.glob("*.parquet"):
            info = _get_file_info(f)
            if info:
                files.append(info)
    
    return files


# ============== Helper Functions ==============

async def _load_backtest_data(
    data_file: Optional[str],
    symbol: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    interval: str = "day"
) -> pd.DataFrame:
    """Load data for backtesting from file or cache. Auto-downloads if not available."""
    from ..services.data_loader import DataLoader
    from ..config.constants import NIFTY_TOKEN, BANKNIFTY_TOKEN
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    
    loader = DataLoader()
    
    # Symbol to token mapping
    tokens = {
        "NIFTY": NIFTY_TOKEN, 
        "BANKNIFTY": BANKNIFTY_TOKEN,
        "GOLD": 53505799,  # MCX Gold
        "CRUDE": 53496327,  # MCX Crude
        "SILVER": 53505031,  # MCX Silver
    }
    token = tokens.get(symbol.upper(), NIFTY_TOKEN)
    
    # Try specific file first (if user selected one)
    if data_file and data_file not in ["", "Auto-detect", "auto-detect"]:
        possible_paths = [
            Path("data") / data_file,
            Path("data/cache") / data_file,
            Path(data_file),
        ]
        
        for path in possible_paths:
            if path.exists():
                logger.info(f"Loading data from specified file: {path}")
                df = _load_dataframe(path)
                if not df.empty:
                    return _filter_by_date(df, start_date, end_date)
        logger.warning(f"Specified file not found: {data_file}")
    
    # Auto-detect: Try to load from cache by symbol and interval
    logger.info(f"Auto-detecting data for {symbol} ({interval})...")
    cache_file = Path("data/cache") / f"{token}_{interval}.parquet"
    if cache_file.exists():
        logger.info(f"Found cached data: {cache_file}")
        df = _load_dataframe(cache_file)
        if not df.empty:
            filtered = _filter_by_date(df, start_date, end_date)
            if not filtered.empty:
                logger.info(f"Using {len(filtered)} rows from cache")
                return filtered
    
    # Try other intervals in cache
    for alt_interval in ["day", "5minute", "15minute", "60minute"]:
        if alt_interval != interval:
            cache_file = Path("data/cache") / f"{token}_{alt_interval}.parquet"
            if cache_file.exists():
                logger.info(f"Found alternative cached data: {cache_file}")
                df = _load_dataframe(cache_file)
                if not df.empty:
                    filtered = _filter_by_date(df, start_date, end_date)
                    if not filtered.empty:
                        logger.info(f"Using cached {alt_interval} data ({len(filtered)} rows) instead of {interval}")
                        return filtered
    
    # No cached data - try to download from Kite API
    logger.info(f"No cached data found for {symbol}. Attempting to download from Kite API...")
    
    try:
        config = Settings()
        if not config.kite_access_token:
            logger.warning("No Kite access token configured")
            return pd.DataFrame()
        
        kite = KiteClient(
            api_key=config.kite_api_key,
            access_token=config.kite_access_token,
            paper_mode=False
        )
        
        # Determine date range
        to_dt = datetime.combine(end_date or date.today(), datetime.max.time())
        from_dt = datetime.combine(
            start_date or (date.today() - timedelta(days=365)), 
            datetime.min.time()
        )
        
        # Map interval to Kite format
        interval_map = {
            "day": "day",
            "5minute": "5minute", 
            "15minute": "15minute",
            "60minute": "60minute"
        }
        kite_interval = interval_map.get(interval, "day")
        
        logger.info(f"Downloading {symbol} data from {from_dt.date()} to {to_dt.date()} ({kite_interval})")
        
        df = kite.fetch_historical_data(token, kite_interval, from_dt, to_dt)
        
        if not df.empty:
            # Cache the data
            cache_dir = Path("data/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = cache_dir / f"{token}_{interval}.parquet"
            df.to_parquet(cache_path)
            logger.info(f"Cached {len(df)} rows to {cache_path}")
            
            return _filter_by_date(df, start_date, end_date)
    
    except Exception as e:
        logger.error(f"Failed to download data: {e}")
    
    return pd.DataFrame()


def _load_dataframe(path: Path) -> pd.DataFrame:
    """Load a dataframe from file and ensure datetime index."""
    try:
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path)
        
        # Ensure datetime index
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
        elif not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        
        return df
    except Exception as e:
        logger.error(f"Failed to load {path}: {e}")
        return pd.DataFrame()


def _filter_by_date(df: pd.DataFrame, start_date: Optional[date], end_date: Optional[date]) -> pd.DataFrame:
    """Filter dataframe by date range."""
    if df.empty:
        return df
    
    if start_date:
        df = df[df.index.date >= start_date]
    if end_date:
        df = df[df.index.date <= end_date]
    
    return df


async def _download_data_task(symbol: str, token: int, max_days: int, interval: str):
    """
    Background task to download historical data and save to cache.
    
    Downloads in chunks to handle large date ranges and saves both CSV and Parquet.
    """
    from ..core.kite_client import KiteClient
    from ..config.settings import Settings
    import time as time_module
    
    logger.info(f"Starting download: {symbol} ({interval}) - max {max_days} days")
    
    try:
        config = Settings()
        kite = KiteClient(
            api_key=config.kite_api_key,
            access_token=config.kite_access_token,
            paper_mode=False
        )
        
        # Chunk size depends on interval
        if interval == "day":
            chunk_days = 365
        elif interval == "60minute":
            chunk_days = 60
        else:
            chunk_days = 30
        
        all_data = []
        to_dt = datetime.now()
        remaining_days = max_days
        
        while remaining_days > 0:
            chunk = min(chunk_days, remaining_days)
            from_dt = to_dt - timedelta(days=chunk)
            
            try:
                df = kite.fetch_historical_data(
                    token, interval,
                    from_dt,
                    to_dt
                )
                
                if not df.empty:
                    all_data.append(df)
                    logger.debug(f"  {symbol} {interval}: {from_dt.date()} to {to_dt.date()} - {len(df)} bars")
                
                time_module.sleep(0.4)  # Rate limiting
                
            except Exception as e:
                logger.warning(f"Chunk error {symbol} {interval}: {e}")
                time_module.sleep(1)
            
            to_dt = from_dt
            remaining_days -= chunk
        
        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            if 'date' in combined.columns:
                combined = combined.drop_duplicates(subset=['date']).sort_values('date')
            
            # Save to cache as Parquet (for backtester)
            cache_dir = Path("data/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            parquet_path = cache_dir / f"{token}_{interval}.parquet"
            df_save = combined.copy()
            if 'date' in df_save.columns:
                df_save['date'] = pd.to_datetime(df_save['date'])
                df_save = df_save.set_index('date')
            df_save.to_parquet(parquet_path)
            
            # Also save CSV for reference
            hist_dir = Path("data/historical")
            hist_dir.mkdir(parents=True, exist_ok=True)
            csv_path = hist_dir / f"{symbol}_{interval}.csv"
            combined.to_csv(csv_path, index=False)
            
            logger.info(f"Downloaded {symbol} ({interval}): {len(combined)} rows saved to {parquet_path}")
        else:
            logger.warning(f"No data downloaded for {symbol} ({interval})")
            
    except Exception as e:
        logger.error(f"Data download failed for {symbol} ({interval}): {e}")


def _get_file_info(file_path: Path) -> Optional[DataFileInfo]:
    """Get information about a data file."""
    try:
        size_kb = file_path.stat().st_size / 1024
        
        # Try to get row count and date range
        rows = None
        date_range = None
        
        if file_path.suffix == ".csv":
            df = pd.read_csv(file_path, nrows=1)
            # Count rows efficiently
            with open(file_path) as f:
                rows = sum(1 for _ in f) - 1  # Subtract header
        elif file_path.suffix == ".parquet":
            df = pd.read_parquet(file_path)
            rows = len(df)
            if not df.empty and hasattr(df.index, 'min'):
                date_range = f"{df.index.min()} to {df.index.max()}"
        
        return DataFileInfo(
            filename=file_path.name,
            size_kb=round(size_kb, 2),
            rows=rows,
            date_range=date_range
        )
    except Exception:
        return DataFileInfo(filename=file_path.name, size_kb=0)


def _sample_series(data: List[float], max_points: int) -> List[float]:
    """Sample a series to reduce size while preserving shape."""
    if len(data) <= max_points:
        return data
    
    step = len(data) / max_points
    indices = [int(i * step) for i in range(max_points)]
    return [data[i] for i in indices if i < len(data)]
