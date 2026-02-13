"""Orchestrator for Trading System v2.0

The Orchestrator coordinates all agents and manages the trading loop.
It uses TradingEngine for the core trading logic, which is shared with
the backtest runner to ensure consistent behavior.
"""

import asyncio
from datetime import datetime, time
from typing import Optional
from pathlib import Path
from loguru import logger

from ..config.settings import Settings
from ..config.constants import NIFTY_TOKEN, MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR
from ..core.kite_client import KiteClient
from ..core.kite_provider import get_kite_client
from ..core.data_cache import DataCache
from ..core.state_manager import StateManager
from ..core.trading_engine import TradingEngine
from ..services.agents import Sentinel, Monk
from ..services.strategies import Strategist
from ..services.execution import Treasury, Executor
from ..database.repository import Repository
from ..database.models import RegimeLog


class Orchestrator:
    """
    Main orchestrator for the trading system.
    Coordinates all agents and manages the trading loop.
    """
    
    def __init__(self, config: Settings, mode: str = "paper"):
        self.config = config
        self.mode = mode
        self.running = False
        self.last_regime = None  # Track last regime for status reporting
        
        # Get KiteClient from provider (uses DB credentials, cached for the day)
        self.kite = get_kite_client(paper_mode=(mode == "paper"))
        if not self.kite:
            # Fallback to config credentials if provider fails
            logger.warning("KiteClientProvider failed, using config credentials")
            self.kite = KiteClient(
                api_key=config.kite_api_key,
                access_token=config.kite_access_token,
                paper_mode=(mode == "paper"),
                mock_mode=False
            )
        
        self.data_cache = DataCache(config.data_dir / "cache")
        self.state_manager = StateManager(config.state_dir)
        self.repository = Repository()  # Uses PostgreSQL from DATABASE_URL
        
        # Initialize agents - share state_manager for consistent margin tracking
        self.sentinel = Sentinel(self.kite, config, self.data_cache)
        self.strategist = Strategist(self.kite, config)
        self.treasury = Treasury(self.kite, config, self.state_manager, paper_mode=(mode == "paper"))
        self.executor = Executor(self.kite, config, self.state_manager)
        self.monk = Monk(self.kite, config, config.models_dir)
        
        # Initialize TradingEngine with all agents
        # This is the SAME engine used by backtest runner
        self.trading_engine = TradingEngine(
            sentinel=self.sentinel,
            strategist=self.strategist,
            treasury=self.treasury,
            executor=self.executor,
            state_manager=self.state_manager,
            kite=self.kite
        )
        
        logger.info(f"Orchestrator initialized in {mode.upper()} mode")
    
    async def run(self, interval_seconds: int = 30):
        """Main trading loop."""
        self.running = True
        logger.info(f"Starting trading loop (interval={interval_seconds}s)")
        
        try:
            self.state_manager.reset_daily()
        except Exception as e:
            logger.error(f"Failed to reset daily state: {e}")
        
        iteration_count = 0
        while self.running:
            try:
                is_market = self._is_market_hours()
                if not is_market:
                    logger.debug("Outside market hours, waiting...")
                    await asyncio.sleep(60)
                    continue
                
                iteration_count += 1
                logger.info(f"Starting iteration #{iteration_count}")
                await self._run_iteration()
                logger.info(f"Completed iteration #{iteration_count}, sleeping {interval_seconds}s")
                await asyncio.sleep(interval_seconds)
                
            except asyncio.CancelledError:
                logger.info("Trading loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in main loop iteration #{iteration_count}: {e}", exc_info=True)
                await asyncio.sleep(60)
        
        logger.info(f"Trading loop stopped after {iteration_count} iterations")
    
    async def _run_iteration(self):
        """Run one iteration of the trading loop."""
        logger.info(f"=== Iteration at {datetime.now().strftime('%H:%M:%S')} ===")
        
        # Use shared TradingEngine for the core trading logic
        # This is the SAME code path used by backtest runner
        result = self.trading_engine.run_iteration(NIFTY_TOKEN)
        
        # Log regime to database (Orchestrator-specific)
        if result.regime:
            self.last_regime = result.regime  # Track for status reporting
            logger.info(f"Regime: {result.regime.regime.value} (safe={result.regime.is_safe})")
            self._log_regime(result.regime)
        
        # Log results
        for exit_info in result.exits:
            logger.info(f"Exit: {exit_info['reason']} P&L: {exit_info.get('pnl', 0):.2f}")
        
        for entry_info in result.entries:
            logger.info(f"Entry: {entry_info['structure']} on {entry_info['instrument']}")
            logger.info(f"Execution ({self.mode.upper()}): SUCCESS")
        
        if result.skipped_reason:
            logger.info(result.skipped_reason)
    
    def _is_market_hours(self) -> bool:
        """Check if current time is within market hours."""
        now = datetime.now().time()
        market_open = time(MARKET_OPEN_HOUR, 15)
        market_close = time(MARKET_CLOSE_HOUR, 30)
        
        if datetime.now().weekday() >= 5:
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
        return self.executor.flatten_all(reason)
