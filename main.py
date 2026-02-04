"""
Trading System v2.0 - Main Entry Point

Multi-agent algorithmic trading system for Indian markets.
"""

import asyncio
import argparse
from datetime import datetime, time
from typing import Optional
from pathlib import Path
from loguru import logger

from config.settings import Settings
from config.constants import NIFTY_TOKEN, MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR
from core.kite_client import KiteClient
from core.data_cache import DataCache
from core.state_manager import StateManager
from core.logger import setup_logger
from agents.sentinel import Sentinel
from agents.strategist import Strategist
from agents.treasury import Treasury
from agents.executor import Executor
from agents.monk import Monk
from database.repository import Repository
from database.models import RegimeLog


class Orchestrator:
    """
    Main orchestrator for the trading system.
    Coordinates all agents and manages the trading loop.
    """
    
    def __init__(self, config: Settings, mode: str = "paper"):
        self.config = config
        self.mode = mode
        self.running = False
        
        # Initialize components
        self.kite = KiteClient(
            api_key=config.kite_api_key,
            access_token=config.kite_access_token,
            mock_mode=(mode == "paper")
        )
        
        self.data_cache = DataCache(config.data_dir / "cache")
        self.state_manager = StateManager(config.state_dir)
        self.repository = Repository(config.db_path)
        
        # Initialize agents
        self.sentinel = Sentinel(self.kite, config, self.data_cache)
        self.strategist = Strategist(self.kite, config)
        self.treasury = Treasury(self.kite, config, self.state_manager)
        self.executor = Executor(self.kite, config)
        self.monk = Monk(self.kite, config, config.models_dir)
        
        logger.info(f"Orchestrator initialized in {mode.upper()} mode")
    
    async def run(self, interval_seconds: int = 300):
        """
        Main trading loop.
        
        Args:
            interval_seconds: Seconds between iterations (default 5 minutes)
        """
        self.running = True
        logger.info("Starting trading loop")
        
        # Reset daily state
        self.state_manager.reset_daily()
        
        while self.running:
            try:
                # Check if market is open
                if not self._is_market_hours():
                    logger.debug("Outside market hours, waiting...")
                    await asyncio.sleep(60)
                    continue
                
                # Run one iteration
                await self._run_iteration()
                
                # Wait for next iteration
                await asyncio.sleep(interval_seconds)
                
            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                self.running = False
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(60)  # Wait before retry
        
        logger.info("Trading loop stopped")
    
    async def _run_iteration(self):
        """Run one iteration of the trading loop."""
        logger.info(f"=== Iteration at {datetime.now().strftime('%H:%M:%S')} ===")
        
        # 1. Sentinel: Detect regime
        regime = self.sentinel.process(NIFTY_TOKEN)
        logger.info(f"Regime: {regime.regime.value} (safe={regime.is_safe})")
        
        # Log regime to database
        self._log_regime(regime)
        
        # 2. Get current account state
        account = self.treasury.get_account_state()
        
        # 3. Monitor existing positions
        positions = self.executor.get_open_positions()
        if positions:
            # Get current prices
            tokens = set()
            for pos in positions:
                for leg in pos.legs:
                    tokens.add(leg.instrument_token)
            
            prices = self.kite.get_ltp(list(tokens))
            
            # Check for exits
            exit_orders = self.executor.monitor_positions(prices, regime.regime)
            
            for exit_order in exit_orders:
                logger.info(f"Executing exit: {exit_order.exit_reason}")
                result = self.executor.execute_exit(exit_order)
                
                if result.success:
                    # Update state
                    self.state_manager.update_pnl(exit_order.realized_pnl)
                    
                    # Check loss limits
                    limit_hit, reason, flat_days = self.treasury.check_loss_limits(account)
                    if limit_hit:
                        self.treasury.activate_circuit_breaker(reason, flat_days)
        
        # 4. Check if we should generate new signals
        if not regime.is_safe:
            logger.info("Regime not safe, skipping signal generation")
            return
        
        if self.state_manager.is_circuit_breaker_active():
            logger.info("Circuit breaker active, skipping signal generation")
            return
        
        # 5. Strategist: Generate signals
        proposals = self.strategist.process(regime)
        
        for proposal in proposals:
            logger.info(f"Proposal: {proposal.structure.value} on {proposal.instrument}")
            
            # 6. Treasury: Validate
            approved, signal, reason = self.treasury.process(proposal, account)
            
            if approved and signal:
                logger.info(f"Approved: {reason}")
                
                # 7. Executor: Place order
                if self.mode == "live":
                    result = self.executor.process(signal)
                    logger.info(f"Execution: {'SUCCESS' if result.success else 'FAILED'}")
                else:
                    logger.info("[PAPER] Would execute signal")
            else:
                logger.info(f"Rejected: {reason}")
    
    def _is_market_hours(self) -> bool:
        """Check if current time is within market hours."""
        now = datetime.now().time()
        market_open = time(MARKET_OPEN_HOUR, 15)  # 9:15 AM
        market_close = time(MARKET_CLOSE_HOUR, 30)  # 3:30 PM
        
        # Also check if it's a weekday
        if datetime.now().weekday() >= 5:  # Saturday or Sunday
            return False
        
        return market_open <= now <= market_close
    
    def _log_regime(self, regime) -> None:
        """Log regime to database."""
        log = RegimeLog(
            timestamp=regime.timestamp,
            instrument_token=regime.instrument_token,
            symbol=regime.symbol,
            regime=regime.regime.value,
            ml_regime=regime.ml_regime.value if regime.ml_regime else None,
            ml_probability=regime.ml_probability,
            confidence=regime.regime_confidence,
            adx=regime.metrics.adx,
            rsi=regime.metrics.rsi,
            iv_percentile=regime.metrics.iv_percentile,
            realized_vol=regime.metrics.realized_vol,
            event_flag=regime.event_flag,
            is_safe=regime.is_safe,
            spot_price=regime.spot_price,
            day_range_pct=regime.day_range_pct
        )
        self.repository.log_regime(log)
    
    def stop(self):
        """Stop the trading loop."""
        self.running = False
        logger.info("Stop signal sent")
    
    def flatten_all(self, reason: str = "MANUAL"):
        """Emergency flatten all positions."""
        logger.warning(f"FLATTEN ALL: {reason}")
        results = self.executor.flatten_all(reason)
        return results


def run_backtest(config: Settings, strategy: str, data_path: str):
    """Run backtest mode."""
    from backtesting.engine import BacktestEngine, BacktestConfig
    from backtesting.data_loader import DataLoader
    
    logger.info(f"Running backtest for strategy: {strategy}")
    
    # Load data
    loader = DataLoader()
    data = loader.load_from_csv(Path(data_path))
    
    if data.empty:
        logger.error("No data loaded")
        return
    
    # Configure backtest
    bt_config = BacktestConfig(
        initial_capital=1000000,
        position_size_pct=0.02,
        max_positions=3
    )
    
    # Define simple entry/exit signals for demonstration
    def entry_signal(data, idx):
        if idx < 20:
            return None
        
        # Simple mean reversion: RSI oversold
        from indicators.technical import calculate_rsi
        rsi = calculate_rsi(data['close'].iloc[:idx+1], 14)
        
        if rsi.iloc[-1] < 30:
            return {
                "direction": 1,
                "stop_loss": data.iloc[idx]['close'] * 0.98,
                "take_profit": data.iloc[idx]['close'] * 1.02
            }
        return None
    
    def exit_signal(data, idx, position):
        # Exit after 5 days
        if idx - position.metadata.get("entry_idx", 0) >= 5:
            return "TIME_EXIT"
        return None
    
    # Run backtest
    engine = BacktestEngine(bt_config, loader)
    results = engine.run(data, entry_signal, exit_signal)
    
    # Print results
    metrics = results["metrics"]
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Total Trades:    {metrics.get('num_trades', 0)}")
    print(f"Total Return:    {metrics.get('total_return_pct', 0):.2%}")
    print(f"Sharpe Ratio:    {metrics.get('sharpe_ratio', 0):.2f}")
    print(f"Max Drawdown:    {metrics.get('max_drawdown', 0):.2%}")
    print(f"Win Rate:        {metrics.get('win_rate', 0):.2%}")
    print(f"Profit Factor:   {metrics.get('profit_factor', 0):.2f}")
    print("=" * 60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Trading System v2.0")
    parser.add_argument(
        "--mode",
        choices=["paper", "live", "backtest"],
        default="paper",
        help="Trading mode"
    )
    parser.add_argument(
        "--strategy",
        default="iron_condor",
        help="Strategy to run (for backtest)"
    )
    parser.add_argument(
        "--data",
        default="data/nifty_2024.csv",
        help="Data file path (for backtest)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Loop interval in seconds"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Log level"
    )
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = Settings()
        config.ensure_directories()
    except Exception as e:
        print(f"Failed to load configuration: {e}")
        print("Make sure .env file exists with required variables.")
        print("Copy .env.example to .env and fill in your API credentials.")
        return
    
    # Setup logging
    setup_logger(config.logs_dir, args.log_level)
    
    logger.info(f"Trading System v2.0 starting in {args.mode.upper()} mode")
    
    if args.mode == "backtest":
        run_backtest(config, args.strategy, args.data)
    else:
        # Create orchestrator and run
        orchestrator = Orchestrator(config, args.mode)
        
        try:
            asyncio.run(orchestrator.run(args.interval))
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            orchestrator.stop()


if __name__ == "__main__":
    main()
