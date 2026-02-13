#!/usr/bin/env python3
"""
Backtest Runner for Trading System v2.0

This script runs backtests using the EXACT SAME trading logic as live/paper trading.
It uses the shared TradingEngine which is also used by the Orchestrator.

Usage:
    python run_backtest.py <data_file> [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--capital N]

Example:
    python run_backtest.py ../data/breeze/indices/NIFTY_1minute.parquet --start 2024-01-01 --capital 500000
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import json

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from loguru import logger

from app.services.backtesting import HistoricalDataClient, load_ohlcv_data
from app.config.settings import Settings
from app.config.constants import NIFTY_TOKEN
from app.core.data_cache import DataCache
from app.core.state_manager import StateManager
from app.core.trading_engine import TradingEngine
from app.services.agents import Sentinel
from app.services.strategies import Strategist
from app.services.execution import Treasury, Executor


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    start_date: date
    end_date: date
    initial_capital: float
    final_capital: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    regime_distribution: Dict[str, int] = field(default_factory=dict)
    equity_curve: List[Dict] = field(default_factory=list)
    trades: List[Dict] = field(default_factory=list)


def run_backtest(
    data_path: str,
    vix_path: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    initial_capital: float = 1000000
) -> BacktestResult:
    """
    Run a backtest using the production trading system.
    
    This uses the EXACT SAME TradingEngine as the live Orchestrator.
    """
    logger.info("=" * 60)
    logger.info("TRADING SYSTEM v2.0 BACKTEST")
    logger.info("Using PRODUCTION trading logic via TradingEngine")
    logger.info("=" * 60)
    
    # Load NIFTY data
    ohlcv_data = load_ohlcv_data(data_path)
    
    # Initialize HistoricalDataClient (mock KiteClient)
    kite = HistoricalDataClient(
        ohlcv_data=ohlcv_data,
        instrument_token=NIFTY_TOKEN,
        symbol="NIFTY",
        initial_capital=initial_capital
    )
    
    # Load VIX data if provided
    if vix_path and Path(vix_path).exists():
        vix_data = load_ohlcv_data(vix_path)
        kite.add_instrument_data(264969, "INDIAVIX", vix_data)
        logger.info(f"Loaded VIX data: {len(vix_data)} records")
    
    # Initialize config and state
    config = Settings()
    # NOTE: Pass None for data_cache to force Sentinel to use HistoricalDataClient
    # instead of reading from disk cache (which has different date ranges)
    state_manager = StateManager(config.state_dir)
    
    # Initialize PRODUCTION agents with historical data client
    # data_cache=None forces Sentinel to fetch from kite (HistoricalDataClient)
    sentinel = Sentinel(kite, config, data_cache=None)
    strategist = Strategist(kite, config)
    strategist.bypass_entry_window = True  # Bypass time check for backtesting
    treasury = Treasury(kite, config, state_manager, paper_mode=True)
    executor = Executor(kite, config, state_manager)
    
    # Initialize TradingEngine - SAME engine used by Orchestrator
    trading_engine = TradingEngine(
        sentinel=sentinel,
        strategist=strategist,
        treasury=treasury,
        executor=executor,
        state_manager=state_manager,
        kite=kite
    )
    
    # Parse dates
    data_start, data_end = kite.get_date_range()
    start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else data_start
    end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else data_end
    
    logger.info(f"Running backtest from {start} to {end}")
    logger.info(f"Initial capital: ₹{initial_capital:,.0f}")
    
    # Reset state
    state_manager.reset_daily()
    
    # Tracking
    trades = []
    equity_curve = []
    regime_history = []
    iteration_count = 0
    
    # Main backtest loop
    for current_date in kite.iterate_dates():
        if current_date < start:
            continue
        if current_date > end:
            break
        
        # Skip weekends
        if current_date.weekday() >= 5:
            continue
        
        iteration_count += 1
        
        try:
            # Reset DC alarm state each day to prevent false positives from accumulating
            sentinel.reset_dc_state()
            
            # Use shared TradingEngine - SAME code as Orchestrator
            result = trading_engine.run_iteration(NIFTY_TOKEN)
            
            # Record regime
            if result.regime:
                regime_history.append({
                    'date': current_date,
                    'regime': result.regime.regime.value,
                    'confidence': result.regime.regime_confidence,
                    'is_safe': result.regime.is_safe,
                    'adx': result.regime.metrics.adx if result.regime.metrics else None,
                    'rsi': result.regime.metrics.rsi if result.regime.metrics else None,
                    'iv_percentile': result.regime.metrics.iv_percentile if result.regime.metrics else None
                })
            
            # Record exits
            for exit_info in result.exits:
                trades.append({
                    'date': str(current_date),
                    'type': 'EXIT',
                    'reason': exit_info['reason'],
                    'pnl': exit_info.get('pnl', 0)
                })
            
            # Record entries
            for entry_info in result.entries:
                trades.append({
                    'date': str(current_date),
                    'type': 'ENTRY',
                    'structure': entry_info['structure'],
                    'instrument': entry_info['instrument'],
                    'regime': entry_info['regime']
                })
            
            # Record equity
            equity = kite._paper_balance
            for pos in kite._paper_positions.values():
                current_price = kite.get_current_bar()['close'] if kite.get_current_bar() else 0
                qty = pos.get('quantity', 0)
                avg_price = pos.get('average_price', 0)
                equity += (current_price - avg_price) * qty
            
            equity_curve.append({
                'date': str(current_date),
                'equity': equity,
                'regime': result.regime.regime.value if result.regime else 'UNKNOWN'
            })
            
            # Progress logging
            if iteration_count % 50 == 0:
                logger.info(f"Day {iteration_count}: {current_date} | Equity: ₹{equity:,.0f}")
                
        except Exception as e:
            logger.error(f"Error on {current_date}: {e}")
            continue
    
    # Calculate results
    final_equity = equity_curve[-1]['equity'] if equity_curve else initial_capital
    total_return = (final_equity - initial_capital) / initial_capital * 100
    
    # Calculate drawdown
    equity_values = [e['equity'] for e in equity_curve]
    peak = initial_capital
    max_dd = 0
    for eq in equity_values:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd
    
    # Calculate Sharpe (simplified)
    if len(equity_values) > 1:
        returns = pd.Series(equity_values).pct_change().dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    else:
        sharpe = 0
    
    # Trade statistics
    entry_trades = [t for t in trades if t['type'] == 'ENTRY']
    exit_trades = [t for t in trades if t['type'] == 'EXIT']
    winning = len([t for t in exit_trades if t.get('pnl', 0) > 0])
    losing = len([t for t in exit_trades if t.get('pnl', 0) < 0])
    
    # Regime distribution
    regime_dist = {}
    for r in regime_history:
        regime = r['regime']
        regime_dist[regime] = regime_dist.get(regime, 0) + 1
    
    result = BacktestResult(
        start_date=start,
        end_date=end,
        initial_capital=initial_capital,
        final_capital=final_equity,
        total_return_pct=total_return,
        total_trades=len(entry_trades),
        winning_trades=winning,
        losing_trades=losing,
        win_rate=winning / max(1, winning + losing) * 100,
        max_drawdown_pct=max_dd,
        sharpe_ratio=sharpe,
        regime_distribution=regime_dist,
        equity_curve=equity_curve,
        trades=trades
    )
    
    return result


def print_results(result: BacktestResult):
    """Print backtest results."""
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Period: {result.start_date} to {result.end_date}")
    print(f"Initial Capital: ₹{result.initial_capital:,.0f}")
    print(f"Final Capital:   ₹{result.final_capital:,.0f}")
    print(f"Total Return:    {result.total_return_pct:+.2f}%")
    print("-" * 40)
    print(f"Total Trades:    {result.total_trades}")
    print(f"Winning Trades:  {result.winning_trades}")
    print(f"Losing Trades:   {result.losing_trades}")
    print(f"Win Rate:        {result.win_rate:.1f}%")
    print("-" * 40)
    print(f"Max Drawdown:    {result.max_drawdown_pct:.2f}%")
    print(f"Sharpe Ratio:    {result.sharpe_ratio:.2f}")
    print("-" * 40)
    print("Regime Distribution:")
    for regime, count in sorted(result.regime_distribution.items()):
        pct = count / sum(result.regime_distribution.values()) * 100
        print(f"  {regime}: {count} days ({pct:.1f}%)")
    print("=" * 60)


def save_results(result: BacktestResult, output_dir: Path):
    """Save backtest results to files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save summary
    summary = {
        'start_date': str(result.start_date),
        'end_date': str(result.end_date),
        'initial_capital': result.initial_capital,
        'final_capital': result.final_capital,
        'total_return_pct': result.total_return_pct,
        'total_trades': result.total_trades,
        'winning_trades': result.winning_trades,
        'losing_trades': result.losing_trades,
        'win_rate': result.win_rate,
        'max_drawdown_pct': result.max_drawdown_pct,
        'sharpe_ratio': result.sharpe_ratio,
        'regime_distribution': result.regime_distribution
    }
    
    with open(output_dir / 'backtest_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    
    # Save equity curve
    pd.DataFrame(result.equity_curve).to_csv(output_dir / 'equity_curve.csv', index=False)
    
    # Save trades
    pd.DataFrame(result.trades).to_csv(output_dir / 'trades.csv', index=False)
    
    logger.info(f"Results saved to {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Run backtest with production trading logic")
    parser.add_argument("data_file", help="Path to OHLCV data file (CSV or Parquet)")
    parser.add_argument("--vix", help="Path to VIX data file", default=None)
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)", default=None)
    parser.add_argument("--end", help="End date (YYYY-MM-DD)", default=None)
    parser.add_argument("--capital", type=float, default=1000000, help="Initial capital")
    parser.add_argument("--output", help="Output directory", default="backtest_results")
    
    args = parser.parse_args()
    
    # Set log level
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    
    # Run backtest
    result = run_backtest(
        data_path=args.data_file,
        vix_path=args.vix,
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.capital
    )
    
    # Print and save results
    print_results(result)
    save_results(result, Path(args.output))


if __name__ == "__main__":
    main()
