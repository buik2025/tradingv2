"""
Background Scheduler for Trading System

Handles automatic tasks like:
- Position reconciliation after market close
- Reconciliation on startup if market already closed

Market Hours (IST):
- NSE F&O: 9:15 AM - 3:30 PM
- MCX: 9:00 AM - 11:30 PM (normal) / 11:55 PM (extended)
"""

import asyncio
from datetime import datetime, time, timedelta
from typing import Optional, Callable
import pytz
from loguru import logger

from .reconciliation import run_reconciliation
from ..core.credentials import get_kite_credentials
from ..config.settings import Settings

IST = pytz.timezone('Asia/Kolkata')

# Market close times (IST)
NSE_CLOSE = time(15, 30)  # 3:30 PM
MCX_CLOSE = time(23, 55)  # 11:55 PM (extended hours)

# Reconciliation delay after market close (minutes)
RECONCILE_DELAY_MINUTES = 5


class ReconciliationScheduler:
    """Schedules automatic position reconciliation."""
    
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_nse_reconcile: Optional[datetime] = None
        self._last_mcx_reconcile: Optional[datetime] = None
    
    async def start(self):
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler already running")
            return
        
        self._running = True
        logger.info("Starting reconciliation scheduler")
        
        # Check if we need to reconcile on startup
        await self._check_startup_reconcile()
        
        # Start the scheduling loop
        self._task = asyncio.create_task(self._schedule_loop())
    
    async def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Reconciliation scheduler stopped")
    
    async def _check_startup_reconcile(self):
        """Check if we should reconcile on startup (market already closed today)."""
        now = datetime.now(IST)
        today = now.date()
        weekday = now.weekday()
        
        # Skip weekends
        if weekday >= 5:
            logger.info("Weekend - skipping startup reconciliation")
            return
        
        current_time = now.time()
        
        # Check NSE: If after 3:35 PM and haven't reconciled today
        nse_reconcile_time = time(15, 35)
        if current_time >= nse_reconcile_time:
            if not self._last_nse_reconcile or self._last_nse_reconcile.date() < today:
                logger.info("NSE market closed - running startup reconciliation")
                await self._run_reconciliation("NSE")
                self._last_nse_reconcile = now
        
        # Check MCX: If after 11:59 PM (or next day before 9 AM)
        mcx_reconcile_time = time(23, 59)
        if current_time >= mcx_reconcile_time or current_time < time(9, 0):
            if not self._last_mcx_reconcile or self._last_mcx_reconcile.date() < today:
                logger.info("MCX market closed - running startup reconciliation")
                await self._run_reconciliation("MCX")
                self._last_mcx_reconcile = now
    
    async def _schedule_loop(self):
        """Main scheduling loop - checks every minute for reconciliation triggers."""
        while self._running:
            try:
                now = datetime.now(IST)
                today = now.date()
                weekday = now.weekday()
                current_time = now.time()
                
                # Skip weekends
                if weekday < 5:
                    # NSE reconciliation at 3:35 PM
                    nse_trigger = time(15, 35)
                    if (current_time >= nse_trigger and 
                        current_time < time(15, 40) and
                        (not self._last_nse_reconcile or self._last_nse_reconcile.date() < today)):
                        logger.info("Triggering scheduled NSE reconciliation")
                        await self._run_reconciliation("NSE")
                        self._last_nse_reconcile = now
                    
                    # MCX reconciliation at 11:59 PM
                    mcx_trigger = time(23, 59)
                    if (current_time >= mcx_trigger and
                        (not self._last_mcx_reconcile or self._last_mcx_reconcile.date() < today)):
                        logger.info("Triggering scheduled MCX reconciliation")
                        await self._run_reconciliation("MCX")
                        self._last_mcx_reconcile = now
                
                # Sleep for 1 minute before next check
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(60)
    
    async def _run_reconciliation(self, market: str):
        """Run reconciliation in background."""
        try:
            creds = get_kite_credentials()
            if not creds or not creds.get("access_token"):
                logger.warning(f"No valid credentials for {market} reconciliation - skipping")
                return
            
            config = Settings()
            
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: run_reconciliation(
                    api_key=config.kite_api_key,
                    access_token=creds["access_token"],
                    dry_run=False
                )
            )
            
            logger.info(
                f"{market} reconciliation complete: "
                f"closed={result.get('closed', 0)}, "
                f"updated={result.get('updated', 0)}, "
                f"discrepancies={len(result.get('discrepancies', []))}"
            )
            
            if result.get("discrepancies"):
                for d in result["discrepancies"]:
                    logger.warning(f"  Discrepancy: {d}")
                    
        except Exception as e:
            logger.error(f"{market} reconciliation failed: {e}")


# Global scheduler instance
_scheduler: Optional[ReconciliationScheduler] = None


def get_scheduler() -> ReconciliationScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = ReconciliationScheduler()
    return _scheduler


async def start_scheduler():
    """Start the global scheduler."""
    scheduler = get_scheduler()
    await scheduler.start()


async def stop_scheduler():
    """Stop the global scheduler."""
    global _scheduler
    if _scheduler:
        await _scheduler.stop()
        _scheduler = None
