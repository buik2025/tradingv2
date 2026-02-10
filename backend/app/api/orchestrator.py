"""Orchestrator for Trading System v2.0"""

import asyncio
from datetime import datetime, time
from typing import Optional
from pathlib import Path
from loguru import logger

from ..config.settings import Settings
from ..config.constants import NIFTY_TOKEN, MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR
from ..core.kite_client import KiteClient
from ..core.data_cache import DataCache
from ..core.state_manager import StateManager
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
        
        # Initialize components - try DB credentials first
        from ..core.credentials import get_kite_credentials
        creds = get_kite_credentials()
        
        if creds and not creds.get('is_expired'):
            api_key = creds['api_key']
            access_token = creds['access_token']
            logger.info(f"Using DB credentials (user: {creds.get('user_id')})")
        else:
            api_key = config.kite_api_key
            access_token = config.kite_access_token
            logger.info("Using config credentials")
        
        self.kite = KiteClient(
            api_key=api_key,
            access_token=access_token,
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
        
        # 1. Sentinel: Detect regime
        regime = self.sentinel.process(NIFTY_TOKEN)
        logger.info(f"Regime: {regime.regime.value} (safe={regime.is_safe})")
        
        self._log_regime(regime)
        
        # 2. Get current account state
        account = self.treasury.get_account_state()
        
        # 3. Monitor existing positions
        positions = self.executor.get_open_positions()
        if positions:
            tokens = set()
            for pos in positions:
                for leg in pos.legs:
                    tokens.add(leg.instrument_token)
            
            prices = self.kite.get_ltp(list(tokens))
            exit_orders = self.executor.monitor_positions(prices, regime.regime)
            
            for exit_order in exit_orders:
                logger.info(f"Executing exit: {exit_order.exit_reason}")
                result = self.executor.execute_exit(exit_order)
                
                if result.success:
                    self.state_manager.update_pnl(exit_order.realized_pnl)
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
        logger.info(f"Strategist generated {len(proposals)} proposals")
        
        if not proposals:
            logger.info("No proposals generated - check entry window and strategy conditions")
            return
        
        for proposal in proposals:
            logger.info(f"Proposal: {proposal.structure.value} on {proposal.instrument}")
            
            # 6. Treasury: Validate
            approved, signal, reason = self.treasury.process(proposal, account)
            
            if approved and signal:
                logger.info(f"Approved: {reason}")
                
                # 7. Executor: Place order (both live and paper mode)
                result = self.executor.process(signal)
                logger.info(f"Execution ({self.mode.upper()}): {'SUCCESS' if result.success else 'FAILED'}")
            else:
                logger.info(f"Rejected: {reason}")
    
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
