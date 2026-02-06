#!/usr/bin/env python3
"""
Run backtest with current or modified settings.

Usage:
    python scripts/run_backtest.py [--baseline]
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import date
from pathlib import Path
import pandas as pd
from loguru import logger

from app.services.strategy_backtester import StrategyBacktester, StrategyBacktestConfig, BacktestMode
from app.config.constants import NIFTY_TOKEN


def load_data(token: int, interval: str = "5minute") -> pd.DataFrame:
    """Load historical data from cache."""
    cache_dir = Path(__file__).parent.parent / "data" / "cache"
    path = cache_dir / f"{token}_{interval}.parquet"
    
    if not path.exists():
        logger.error(f"Data file not found: {path}")
        return pd.DataFrame()
    
    df = pd.read_parquet(path)
    logger.info(f"Loaded {len(df)} bars from {path.name}")
    logger.info(f"Date range: {df.index.min()} to {df.index.max()}")
    return df


def run_backtest(config: StrategyBacktestConfig, data: pd.DataFrame) -> dict:
    """Run backtest and return results."""
    backtester = StrategyBacktester(config)
    result = backtester.run(data, BacktestMode.STANDARD)
    
    return {
        "total_return_pct": result.total_return_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "sortino_ratio": result.sortino_ratio,
        "max_drawdown": result.max_drawdown,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "expectancy": result.expectancy,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "avg_holding_days": result.avg_holding_days,
        "by_strategy": result.by_strategy,
        "by_regime": result.by_regime,
        "trades": result.trades,
    }


def print_results(results: dict, title: str = "BACKTEST RESULTS"):
    """Print formatted results."""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)
    
    print(f"\n📊 Performance Metrics:")
    print(f"   Total Return:     {results['total_return_pct']:>8.2f}%")
    print(f"   Sharpe Ratio:     {results['sharpe_ratio']:>8.2f}")
    print(f"   Sortino Ratio:    {results['sortino_ratio']:>8.2f}")
    print(f"   Max Drawdown:     {results['max_drawdown']:>8.2f}%")
    
    print(f"\n📈 Trade Statistics:")
    print(f"   Total Trades:     {results['total_trades']:>8}")
    print(f"   Winning Trades:   {results['winning_trades']:>8}")
    print(f"   Losing Trades:    {results['losing_trades']:>8}")
    print(f"   Win Rate:         {results['win_rate']:>8.1f}%")
    print(f"   Profit Factor:    {results['profit_factor']:>8.2f}")
    print(f"   Expectancy:       {results['expectancy']:>8.2f}%")
    print(f"   Avg Hold Days:    {results['avg_holding_days']:>8.1f}")
    
    if results['by_strategy']:
        print(f"\n📋 By Strategy:")
        for strategy, stats in results['by_strategy'].items():
            print(f"   {strategy}: {stats.get('trades', 0)} trades, {stats.get('return_pct', 0):.2f}% return")
    
    if results['by_regime']:
        print(f"\n🎯 By Regime:")
        for regime, stats in results['by_regime'].items():
            print(f"   {regime}: {stats.get('trades', 0)} trades, {stats.get('return_pct', 0):.2f}% return")
    
    if results['trades']:
        print(f"\n📝 Recent Trades (last 10):")
        for trade in results['trades'][-10:]:
            pnl_sign = "+" if trade.pnl >= 0 else ""
            print(f"   {trade.entry_date.date()} | {trade.strategy_type:15} | {pnl_sign}{trade.pnl_pct:.2f}% | {trade.exit_reason}")
    
    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Run backtest")
    parser.add_argument("--baseline", action="store_true", help="Run with baseline (current) settings")
    parser.add_argument("--interval", default="5minute", help="Data interval (minute, 5minute, day)")
    parser.add_argument("--capital", type=float, default=1000000, help="Initial capital")
    args = parser.parse_args()
    
    # Load data
    data = load_data(NIFTY_TOKEN, args.interval)
    if data.empty:
        logger.error("No data available for backtest")
        return
    
    # Configure backtest
    config = StrategyBacktestConfig(
        initial_capital=args.capital,
        position_size_pct=0.02,
        max_positions=3,
        strategies=["iron_condor", "jade_lizard", "butterfly", "naked_strangle"],
        symbol="NIFTY",
        start_date=date(2025, 11, 1),
        end_date=date(2026, 2, 6),
        max_loss_per_trade=0.015,  # 1.5% - updated per Grok
        max_daily_loss=0.015,      # 1.5% - updated per Grok
    )
    
    title = "BASELINE BACKTEST (Current Settings)" if args.baseline else "BACKTEST RESULTS"
    
    # Run backtest
    logger.info(f"Running backtest: {config.start_date} to {config.end_date}")
    results = run_backtest(config, data)
    
    # Print results
    print_results(results, title)
    
    return results


if __name__ == "__main__":
    main()
