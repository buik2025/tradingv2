#!/usr/bin/env python3
"""
Run backtest with current settings.

Supports Phase 2 features (Circuit Breaker + Greek Hedger):
- Without Phase 2: python scripts/run_backtest.py (default, respects entry window)
- With Phase 2: python scripts/run_backtest.py --phase2 (bypasses entry window, enables circuit breaker tracking)
- Baseline: python scripts/run_backtest.py --baseline (Phase 1 reference)

Usage:
    python scripts/run_backtest.py [--phase2] [--baseline] [--capital 1000000] [--interval 5minute]
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


def print_results(results: dict, title: str = "BACKTEST RESULTS", initial_capital: float = 1000000):
    """Print formatted results in Indian Rupees (INR)."""
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)
    
    # Capital and returns in INR
    final_capital = initial_capital * (1 + results['total_return_pct'] / 100)
    total_return_inr = final_capital - initial_capital
    
    print(f"\n💰 Capital:")
    print(f"   Initial Capital:  ₹{initial_capital:>14,.0f}")
    print(f"   Final Capital:    ₹{final_capital:>14,.0f}")
    print(f"   Total P&L:        ₹{total_return_inr:>14,.0f}")
    
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
    
    # Phase 2: Circuit Breaker Status (if enabled)
    if results.get('circuit_breaker_status'):
        cb = results['circuit_breaker_status']
        print(f"\n🛑 Circuit Breaker (Phase 2):")
        print(f"   Halt State:       {cb.get('state', 'N/A'):>15}")
        print(f"   Daily Loss:       {cb.get('daily_loss_pct', '0.00%'):>15}")
        print(f"   Weekly Loss:      {cb.get('weekly_loss_pct', '0.00%'):>15}")
        print(f"   Monthly Loss:     {cb.get('monthly_loss_pct', '0.00%'):>15}")
        print(f"   Consecutive Loss: {cb.get('consecutive_losses', 0):>7}")
        print(f"   Size Multiplier:  {cb.get('size_multiplier', 1.0):>8.2f}x")
    
    if results['by_strategy']:
        print(f"\n📋 By Strategy:")
        for strategy, stats in results['by_strategy'].items():
            print(f"   {strategy}: {stats.get('trades', 0)} trades, {stats.get('return_pct', 0):.2f}% return")
    
    if results['by_regime']:
        print(f"\n🎯 By Regime:")
        for regime, stats in results['by_regime'].items():
            print(f"   {regime}: {stats.get('trades', 0)} trades, {stats.get('return_pct', 0):.2f}% return")
    
    if results['trades']:
        print(f"\n📝 Recent Trades (last 15):")
        print(f"   {'Entry Date':<12} {'Strategy':<18} {'P&L':<8} {'Exit Reason':<20}")
        print(f"   {'-'*70}")
        for trade in results['trades'][-15:]:
            pnl_sign = "+" if trade.pnl >= 0 else ""
            entry_date = trade.entry_date.date() if hasattr(trade.entry_date, 'date') else trade.entry_date
            print(f"   {str(entry_date):<12} {trade.strategy_type:<18} {pnl_sign}{trade.pnl_pct:>6.2f}% {trade.exit_reason:<20}")
    
    print("\n" + "=" * 70)


def main():
    """
    Run backtest with flexible configuration.
    
    Modes:
    - Default: Phase 1 with strict entry window (9:20-15:00 IST)
    - --phase2: Phase 1 + Phase 2 features, bypasses entry window for full testing
    - --baseline: Phase 1 reference run for comparison
    """
    parser = argparse.ArgumentParser(description="Run backtest with optional Phase 2 features")
    parser.add_argument("--phase2", action="store_true", help="Enable Phase 2 (Circuit Breaker + Greek Hedger)")
    parser.add_argument("--baseline", action="store_true", help="Run with baseline (Phase 1) settings")
    parser.add_argument("--interval", default="minute", help="Data interval (minute, 5minute, day)")
    parser.add_argument("--capital", type=float, default=1000000, help="Initial capital")
    parser.add_argument("--position-size", type=float, default=0.02, help="Position size")
    parser.add_argument("--commission-tax-pct", type=float, default=0.0008, help="Commission and tax")
    parser.add_argument("--start-date", default="2025-11-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="2026-02-05", help="End date (YYYY-MM-DD)")
    args = parser.parse_args()
    
    # Load data
    data = load_data(NIFTY_TOKEN, args.interval)
    if data.empty:
        logger.error("No data available for backtest")
        return
    
    # Parse date range
    from datetime import datetime
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    
    # Configure backtest
    config = StrategyBacktestConfig(
        initial_capital=args.capital,
        position_size_pct=args.position_size,
        max_positions=3,
        strategies=["iron_condor", "jade_lizard", "butterfly", "naked_strangle"],
        symbol="NIFTY",
        start_date=start_date,
        end_date=end_date,
        max_loss_per_trade=0.015,  # 1.5% - per v2_rulebook
        max_daily_loss=0.015,       # 1.5% - per v2_rulebook
        commission_tax_pct=args.commission_tax_pct,
    )
    
    # Determine title and configuration
    if args.baseline:
        title = "BASELINE BACKTEST (Phase 1 - Reference)"
        phase2_enabled = False
        entry_window_bypass = False
    elif args.phase2:
        title = "BACKTEST WITH PHASE 2 (Circuit Breaker + Greek Hedger)"
        phase2_enabled = True
        entry_window_bypass = True  # Bypass to test full data range
    else:
        title = "STANDARD BACKTEST (Phase 1 with Entry Window)"
        phase2_enabled = True  # Phase 2 integrated but not emphasized
        entry_window_bypass = False  # Respect market hours
    
    # Log configuration
    logger.info(f"Backtest Mode: {title}")
    logger.info(f"Phase 2 Enabled: {phase2_enabled}")
    logger.info(f"Entry Window Bypass: {entry_window_bypass}")
    logger.info(f"Date Range: {config.start_date} to {config.end_date}")
    logger.info(f"Capital: ₹{config.initial_capital:,.0f} | Position Size: {config.position_size_pct*100:.1f}%")
    logger.info(f"Commission & Tax: {args.commission_tax_pct*100:.3f}%")
    
    # Run backtest
    backtester = StrategyBacktester(config)
    
    # Configure strategist for entry window bypass if Phase 2
    if entry_window_bypass:
        backtester.strategist.bypass_entry_window = True
    
    result = backtester.run(data, BacktestMode.STANDARD)
    
    results = {
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
        "circuit_breaker_status": backtester.circuit_breaker.get_status() if phase2_enabled else None,
    }
    
    # Print results
    print_results(results, title, initial_capital=args.capital)
    
    # Generate comprehensive report with trade legs
    generate_backtest_report(result, config, results, title, args.commission_tax_pct, phase2_enabled)
    
    return results


def generate_backtest_report(result, config: StrategyBacktestConfig, results: dict, title: str, commission_tax_pct: float, phase2_enabled: bool):
    """Generate comprehensive backtest report with trade legs for pre-live verification.
    
    This report documents:
    - Configuration and parameters used
    - Summary metrics (returns, ratios, drawdown, etc)
    - All trades with entry/exit details and legs breakdown
    - Performance by strategy and regime
    - Pre-live deployment verification checklist
    """
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(__file__).parent.parent / "data" / "cache" / f"backtest_report_{ts}.md"
    
    initial_capital = config.initial_capital
    final_capital = initial_capital * (1 + results['total_return_pct'] / 100)
    total_pnl = final_capital - initial_capital
    
    with open(report_path, "w") as f:
        # Header
        f.write(f"# {title}\n\n")
        f.write(f"**Generated:** {datetime.now().isoformat()}\n\n")
        f.write(f"**Purpose:** Pre-live deployment verification of backtest strategy and trade legs\n\n")
        
        # Configuration
        f.write("## Configuration\n\n")
        f.write(f"- **Date Range:** {config.start_date} to {config.end_date}\n")
        f.write(f"- **Initial Capital:** ₹{initial_capital:,.0f}\n")
        f.write(f"- **Position Size:** {config.position_size_pct*100:.1f}% per trade\n")
        f.write(f"- **Commission & Tax:** {commission_tax_pct*100:.3f}% of turnover\n")
        f.write(f"- **Data:** NIFTY 1-minute bars\n")
        f.write(f"- **Strategies:** {', '.join(config.strategies).upper()}\n")
        f.write(f"- **Phase 2 (Circuit Breaker + Greek Hedger):** {'Enabled' if phase2_enabled else 'Disabled'}\n")
        f.write(f"- **Risk Limits:** 1.5% max daily loss, 1.5% max per-trade loss\n\n")
        
        # Summary Metrics
        f.write("## Summary Metrics\n\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"|--------|-------|\n")
        f.write(f"| Final Capital | ₹{final_capital:,.0f} |\n")
        f.write(f"| Total P&L | ₹{total_pnl:,.0f} |\n")
        f.write(f"| Return | {results['total_return_pct']:.2f}% |\n")
        f.write(f"| Total Trades | {results['total_trades']} |\n")
        f.write(f"| Winning Trades | {results['winning_trades']} |\n")
        f.write(f"| Losing Trades | {results['losing_trades']} |\n")
        f.write(f"| Win Rate | {results['win_rate']:.1f}% |\n")
        f.write(f"| Profit Factor | {results['profit_factor']:.2f} |\n")
        f.write(f"| Expectancy | {results['expectancy']:.2f}% |\n")
        f.write(f"| Avg Holding Days | {results['avg_holding_days']:.1f} |\n")
        f.write(f"| Sharpe Ratio | {results['sharpe_ratio']:.2f} |\n")
        f.write(f"| Sortino Ratio | {results['sortino_ratio']:.2f} |\n")
        f.write(f"| Max Drawdown | {results['max_drawdown']:.2f}% |\n\n")
        
        # Trade Structure Legend
        f.write("## Trade Structure Reference\n\n")
        f.write("### Strategy Leg Specifications\n\n")
        f.write("**Jade Lizard (3 legs):**\n")
        f.write("- Sell Call (short-term, higher strike)\n")
        f.write("- Sell Put (short-term, lower strike)\n")
        f.write("- Buy Put (long-term protection, lowest strike)\n\n")
        
        f.write("**Iron Condor (4 legs):**\n")
        f.write("- Sell Call (short strike)\n")
        f.write("- Buy Call (long strike, higher)\n")
        f.write("- Sell Put (short strike)\n")
        f.write("- Buy Put (long strike, lower)\n\n")
        
        f.write("**Butterfly (3 legs):**\n")
        f.write("- Sell 2x ATM Options\n")
        f.write("- Buy OTM Call\n")
        f.write("- Buy OTM Put\n\n")
        
        f.write("**Naked Strangle (2 legs):**\n")
        f.write("- Sell Call (OTM)\n")
        f.write("- Sell Put (OTM)\n\n")
        
        # Trade Details
        f.write("## All Trades\n\n")
        
        for idx, trade in enumerate(results['trades'], 1):
            f.write(f"### Trade #{idx}: {trade.strategy_type.upper()}\n\n")
            
            # Capital & margin tracking
            f.write(f"**Capital Before:** ₹{trade.capital_before:,.2f}\n\n")
            f.write(f"**Capital After:** ₹{trade.capital_after:,.2f}\n\n")
            f.write(f"**Margin Blocked:** ₹{getattr(trade, 'margin_blocked', 0):,.0f}\n\n")
            f.write(f"**Free Capital Before:** ₹{getattr(trade, 'free_capital_before', 0):,.0f}\n\n")
            f.write(f"**Free Capital After:** ₹{getattr(trade, 'free_capital_after', 0):,.0f}\n\n")
            
            f.write(f"**Entry Date/Time:** {trade.entry_date}\n\n")
            f.write(f"**Exit Date/Time:** {trade.exit_date}\n\n")
            f.write(f"**Entry Price:** ₹{trade.entry_price:,.2f}\n\n")
            f.write(f"**Exit Price:** ₹{trade.exit_price:,.2f}\n\n")
            f.write(f"**P&L:** ₹{trade.pnl:+,.2f} ({trade.pnl_pct:+.2f}%)\n\n")
            f.write(f"**Execution Costs:** ₹{trade.costs:,.2f}\n\n")
            # Holding: number of bars (interval-dependent). Also show human-readable duration
            holding_bars = getattr(trade, 'holding_days', 0)
            duration_str = ''
            try:
                entry_dt = trade.entry_date
                exit_dt = trade.exit_date
                if isinstance(entry_dt, str):
                    from datetime import datetime as _dt
                    entry_dt = _dt.fromisoformat(entry_dt)
                if isinstance(exit_dt, str):
                    from datetime import datetime as _dt
                    exit_dt = _dt.fromisoformat(exit_dt)
                delta = exit_dt - entry_dt
                secs = max(0, delta.total_seconds())
                if secs < 60:
                    duration_str = f"{int(secs)}s"
                elif secs < 3600:
                    duration_str = f"{secs/60:.1f}m"
                elif secs < 86400:
                    duration_str = f"{secs/3600:.1f}h"
                else:
                    duration_str = f"{secs/86400:.1f}d"
            except Exception:
                duration_str = ''
            f.write(f"**Holding:** {holding_bars} bars{' (~' + duration_str + ')' if duration_str else ''}\n\n")
            f.write(f"**Exit Reason:** {trade.exit_reason}\n\n")
            f.write(f"**Market Regime:** {trade.regime_at_entry} → {trade.regime_at_exit}\n\n")
            f.write(f"**Max Profit:** ₹{trade.max_profit:,.2f}\n\n")
            f.write(f"**Max Loss:** ₹{trade.max_loss:,.2f}\n\n")
            
            # Legs with proper pricing
            if trade.legs:
                f.write("**Trade Legs (Black-Scholes Priced):**\n\n")
                for leg_idx, leg in enumerate(trade.legs, 1):
                    leg_type = leg.get('type', 'UNKNOWN')
                    strike = leg.get('strike', 'N/A')
                    side = leg.get('side', 'N/A')
                    qty = leg.get('quantity', 1)
                    entry = leg.get('entry_price', 0)
                    exit_p = leg.get('exit_price', 0)
                    leg_pnl = leg.get('pnl', 0)
                    expiry = leg.get('expiry', 'N/A')
                    pnl_per_contract = leg.get('pnl_per_contract', 0)
                    
                    f.write(f"- **Leg {leg_idx}:** {leg_type.upper()} @ ₹{strike} | Expiry: {expiry} | Qty: {qty} | Side: {side}\n")
                    f.write(f"  - Entry Price: ₹{entry:.2f} | Exit Price: ₹{exit_p:.2f}\n")
                    f.write(f"  - P&L: ₹{leg_pnl:+,.2f} (₹{pnl_per_contract:+,.2f} per contract)\n\n")
            else:
                # Describe expected structure
                f.write("**Expected Legs:**\n\n")
                strategy_lower = trade.strategy_type.lower()
                if "jade_lizard" in strategy_lower:
                    f.write("- Leg 1: SELL CALL (short-term, higher strike)\n")
                    f.write("- Leg 2: SELL PUT (short-term, lower strike)\n")
                    f.write("- Leg 3: BUY PUT (long-term protection, lowest strike)\n")
                elif "iron_condor" in strategy_lower:
                    f.write("- Leg 1: SELL CALL (short strike)\n")
                    f.write("- Leg 2: BUY CALL (long strike, higher)\n")
                    f.write("- Leg 3: SELL PUT (short strike)\n")
                    f.write("- Leg 4: BUY PUT (long strike, lower)\n")
                elif "butterfly" in strategy_lower:
                    f.write("- Leg 1: SELL 2x ATM OPTIONS\n")
                    f.write("- Leg 2: BUY OTM CALL\n")
                    f.write("- Leg 3: BUY OTM PUT\n")
                elif "strangle" in strategy_lower:
                    f.write("- Leg 1: SELL CALL (OTM)\n")
                    f.write("- Leg 2: SELL PUT (OTM)\n")
                f.write("\n")
            
            f.write("---\n\n")
        
        # Performance by Strategy
        f.write("## Performance by Strategy\n\n")
        f.write("| Strategy | Trades | Total P&L | Win Rate | Profit Factor |\n")
        f.write("|----------|--------|-----------|----------|---------------|\n")
        for strategy, stats in results['by_strategy'].items():
            trades = stats.get('total_trades', 0)
            pnl = stats.get('total_pnl', 0)
            wr = stats.get('win_rate', 0) * 100
            pf = stats.get('profit_factor', 0)
            f.write(f"| {strategy.upper()} | {trades} | ₹{pnl:+,.0f} | {wr:.1f}% | {pf:.2f} |\n")
        f.write("\n")
        
        # Performance by Regime
        f.write("## Performance by Regime\n\n")
        f.write("| Regime | Trades | Total P&L | Win Rate | Profit Factor |\n")
        f.write("|--------|--------|-----------|----------|---------------|\n")
        for regime, stats in results['by_regime'].items():
            trades = stats.get('total_trades', 0)
            pnl = stats.get('total_pnl', 0)
            wr = stats.get('win_rate', 0) * 100
            pf = stats.get('profit_factor', 0)
            f.write(f"| {regime} | {trades} | ₹{pnl:+,.0f} | {wr:.1f}% | {pf:.2f} |\n")
        f.write("\n")
        
        # Verification Checklist
        f.write("## Pre-Live Deployment Verification Checklist\n\n")
        f.write("- [ ] **Trade Recording:** All trades properly recorded with entry/exit dates and prices\n")
        f.write("- [ ] **Leg Details:** Each trade leg (strike, side, quantity) documented for verification\n")
        f.write("- [ ] **P&L Accuracy:** All P&L calculations independently verified\n")
        f.write("- [ ] **Commission Applied:** Commission and tax costs correctly deducted from P&L\n")
        f.write("- [ ] **Risk Limits:** Circuit breaker properly enforces daily/weekly loss limits\n")
        f.write("- [ ] **Regime Detection:** Market regime classification working correctly\n")
        f.write("- [ ] **Strategy Execution:** All strategies executing trades within specifications\n")
        f.write("- [ ] **Position Sizing:** Position sizes consistent with configured % allocation\n")
        f.write("- [ ] **Exit Reasons:** All exit conditions (profit target, time exit, stop loss) functioning\n")
        f.write("- [ ] **No Errors:** Zero unexpected errors in execution logs\n")
        f.write("- [ ] **Performance Meets Expectations:** Results align with backtest objectives\n")
        f.write("- [ ] **Ready for Live Deployment:** All systems validated and operational\n\n")
        
        # Footer
        f.write("---\n\n")
        f.write("*This report was auto-generated for compliance and pre-live verification.*\n")
        f.write("*Do not modify. Preserve as evidence of testing before live trading.*\n")
    
    logger.info(f"Comprehensive backtest report written: {report_path}")
    print(f"\n📄 Backtest report generated: {report_path}\n")


if __name__ == "__main__":
    main()
