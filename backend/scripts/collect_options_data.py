#!/usr/bin/env python3
"""
Production Options Data Collector for Backtesting

Collects 1-minute options chain data during market hours for reliable backtesting.
Run this script at 9:15 AM IST and let it run until market close.

Features:
- 1-minute interval data collection
- All strikes ±20 from ATM (covers 10-delta to 50-delta)
- Current week, next week, and monthly expiry
- Full depth: LTP, bid, ask, volume, OI
- Automatic recovery on errors
- Daily file rotation
- Memory-efficient batch processing

Usage:
    # Start at market open (9:15 AM)
    python scripts/collect_options_data.py
    
    # Or with specific options
    python scripts/collect_options_data.py --symbols NIFTY,BANKNIFTY --interval 60

Data saved to: backend/data/options/
"""

import os
import sys
import time
import signal
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import threading
import queue

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from loguru import logger

from app.core.kite_client import KiteClient
from app.config.settings import Settings
from app.config.constants import NIFTY_TOKEN, BANKNIFTY_TOKEN
from app.core.credentials import get_kite_credentials

# Configure logging
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.add(
    LOG_DIR / "options_collector_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO"
)

# Output directory
OPTIONS_DATA_DIR = Path(__file__).parent.parent / "data" / "options"
OPTIONS_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Instruments to collect
INSTRUMENTS = {
    "NIFTY": {
        "token": NIFTY_TOKEN,
        "spot_symbol": "NSE:NIFTY 50",
        "exchange": "NFO",
        "lot_size": 50,
        "strike_interval": 50,
        "num_strikes": 20,  # ±20 strikes from ATM
    },
    "BANKNIFTY": {
        "token": BANKNIFTY_TOKEN,
        "spot_symbol": "NSE:NIFTY BANK",
        "exchange": "NFO",
        "lot_size": 15,
        "strike_interval": 100,
        "num_strikes": 15,  # ±15 strikes from ATM
    },
}

# Market timing (IST)
MARKET_OPEN = (9, 15)   # 9:15 AM
MARKET_CLOSE = (15, 30)  # 3:30 PM

# Global flag for graceful shutdown
shutdown_flag = threading.Event()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Shutdown signal received. Finishing current collection...")
    shutdown_flag.set()


def get_weekly_expiry(current_date: date, weeks_ahead: int = 0) -> date:
    """Get weekly expiry date (Thursday)."""
    days_until_thursday = (3 - current_date.weekday()) % 7
    if days_until_thursday == 0 and weeks_ahead == 0:
        return current_date
    elif days_until_thursday == 0:
        days_until_thursday = 7
    return current_date + timedelta(days=days_until_thursday + (weeks_ahead * 7))


def get_monthly_expiry(current_date: date) -> date:
    """Get monthly expiry date (last Thursday of month)."""
    if current_date.month == 12:
        next_month = date(current_date.year + 1, 1, 1)
    else:
        next_month = date(current_date.year, current_date.month + 1, 1)
    last_day = next_month - timedelta(days=1)
    days_since_thursday = (last_day.weekday() - 3) % 7
    return last_day - timedelta(days=days_since_thursday)


def get_expiries_to_collect(current_date: date) -> List[date]:
    """Get all expiries we should collect data for."""
    expiries = set()
    
    # Current week expiry
    expiries.add(get_weekly_expiry(current_date, 0))
    
    # Next week expiry
    expiries.add(get_weekly_expiry(current_date, 1))
    
    # Week after next (for far OTM options)
    expiries.add(get_weekly_expiry(current_date, 2))
    
    # Monthly expiry
    expiries.add(get_monthly_expiry(current_date))
    
    # Next month's expiry
    next_month = current_date.replace(day=28) + timedelta(days=4)
    expiries.add(get_monthly_expiry(next_month))
    
    return sorted(list(expiries))


def get_strikes_around_spot(spot: float, strike_interval: int, num_strikes: int = 20) -> List[int]:
    """Get strike prices around the spot price."""
    atm_strike = round(spot / strike_interval) * strike_interval
    return [atm_strike + i * strike_interval for i in range(-num_strikes, num_strikes + 1)]


def build_option_symbol(symbol: str, expiry: date, strike: int, opt_type: str) -> str:
    """
    Build Kite trading symbol for an option.
    
    Format: NIFTY26FEB25500CE (SYMBOL + YY + MON + STRIKE + TYPE)
    Note: Day is NOT included in the symbol format for NFO options
    """
    month_str = expiry.strftime("%b").upper()
    year_str = expiry.strftime("%y")
    
    return f"{symbol}{year_str}{month_str}{strike}{opt_type}"


def is_market_hours() -> bool:
    """Check if current time is within market hours."""
    now = datetime.now()
    
    # Check if weekday
    if now.weekday() >= 5:
        return False
    
    market_open = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
    market_close = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0, microsecond=0)
    
    return market_open <= now <= market_close


def wait_for_market_open():
    """Wait until market opens."""
    while not shutdown_flag.is_set():
        now = datetime.now()
        
        # Check if weekend
        if now.weekday() >= 5:
            next_monday = now + timedelta(days=(7 - now.weekday()))
            next_open = next_monday.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
            wait_seconds = (next_open - now).total_seconds()
            logger.info(f"Weekend. Market opens Monday at {next_open}. Waiting {wait_seconds/3600:.1f} hours...")
            time.sleep(min(wait_seconds, 3600))  # Sleep max 1 hour at a time
            continue
        
        market_open = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
        market_close = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0, microsecond=0)
        
        if now < market_open:
            wait_seconds = (market_open - now).total_seconds()
            logger.info(f"Market opens at {market_open.strftime('%H:%M')}. Waiting {wait_seconds/60:.1f} minutes...")
            time.sleep(min(wait_seconds, 60))
        elif now > market_close:
            # Wait for next day
            next_open = (now + timedelta(days=1)).replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
            wait_seconds = (next_open - now).total_seconds()
            logger.info(f"Market closed. Next open at {next_open}. Waiting...")
            time.sleep(min(wait_seconds, 3600))
        else:
            # Market is open
            return True
    
    return False


class OptionsDataCollector:
    """
    Production-grade options data collector.
    
    Collects options chain data at specified intervals and saves to parquet files.
    On startup, fetches historical 1-minute data from market open (9:15 AM) to current time.
    """
    
    def __init__(
        self,
        symbols: List[str],
        interval_seconds: int = 60,
        batch_size: int = 50
    ):
        self.symbols = symbols
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        
        # Initialize Kite client - try database credentials first, then fall back to settings
        creds = get_kite_credentials()
        if creds and not creds.get("is_expired"):
            logger.info(f"Using credentials from database (user: {creds.get('user_id')}, expires: {creds.get('expires_at')})")
            self.kite = KiteClient(
                api_key=creds["api_key"],
                access_token=creds["access_token"],
                paper_mode=False
            )
        else:
            logger.warning("No valid credentials in database, falling back to .env settings")
            settings = Settings()
            self.kite = KiteClient(
                api_key=settings.kite_api_key,
                access_token=settings.kite_access_token,
                paper_mode=False
            )
        
        # Data buffers (write to disk periodically)
        self.buffers: Dict[str, List[dict]] = {s: [] for s in symbols}
        self.buffer_lock = threading.Lock()
        
        # Track if historical backfill is done
        self.historical_backfill_done = False
        
        # Statistics
        self.stats = {
            "collections": 0,
            "records": 0,
            "errors": 0,
            "historical_records": 0,
            "start_time": None
        }
    
    def get_spot_prices(self) -> Dict[str, float]:
        """Get current spot prices for all symbols."""
        spot_symbols = [INSTRUMENTS[s]["spot_symbol"] for s in self.symbols]
        
        try:
            quotes = self.kite.get_quote(spot_symbols)
            if not quotes:
                return {}
            
            result = {}
            for symbol in self.symbols:
                spot_symbol = INSTRUMENTS[symbol]["spot_symbol"]
                if spot_symbol in quotes:
                    result[symbol] = quotes[spot_symbol].get("last_price", 0)
            
            return result
        except Exception as e:
            logger.error(f"Failed to get spot prices: {e}")
            return {}
    
    def get_option_instrument_tokens_batch(self, symbol: str, options_list: List[Tuple[date, int, str]]) -> Dict[str, int]:
        """
        Get instrument tokens for multiple options in batches.
        
        Args:
            symbol: NIFTY or BANKNIFTY
            options_list: List of (expiry, strike, opt_type) tuples
            
        Returns:
            Dict mapping trading_symbol to instrument_token
        """
        exchange = INSTRUMENTS[symbol]["exchange"]
        tokens = {}
        
        # Build all symbols
        all_symbols = []
        for expiry, strike, opt_type in options_list:
            trading_symbol = build_option_symbol(symbol, expiry, strike, opt_type)
            all_symbols.append((f"{exchange}:{trading_symbol}", trading_symbol))
        
        # Fetch in batches of 50
        for i in range(0, len(all_symbols), self.batch_size):
            batch = all_symbols[i:i + self.batch_size]
            batch_keys = [s[0] for s in batch]
            
            try:
                quotes = self.kite.get_quote(batch_keys)
                if quotes:
                    for full_symbol, trading_symbol in batch:
                        if full_symbol in quotes:
                            token = quotes[full_symbol].get("instrument_token")
                            if token:
                                tokens[trading_symbol] = token
                
                # Rate limiting between batches
                time.sleep(0.4)
                
            except Exception as e:
                logger.warning(f"Batch token fetch error: {e}")
                time.sleep(1)
        
        logger.info(f"  Got {len(tokens)} instrument tokens for {symbol}")
        return tokens
    
    def fetch_historical_options_data(self, symbol: str, spot_price: float) -> List[dict]:
        """
        Fetch historical 1-minute options data from market open to now.
        
        This is called on startup to backfill data from 9:15 AM.
        """
        config = INSTRUMENTS[symbol]
        exchange = config["exchange"]
        strike_interval = config["strike_interval"]
        num_strikes = config["num_strikes"]
        
        today = date.today()
        now = datetime.now()
        
        # Market open time today
        market_open = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
        
        # If before market open, nothing to backfill
        if now < market_open:
            logger.info(f"Before market open, no historical data to fetch for {symbol}")
            return []
        
        # Get expiries and strikes
        expiries = get_expiries_to_collect(today)
        strikes = get_strikes_around_spot(spot_price, strike_interval, num_strikes)
        
        logger.info(f"Fetching historical options data for {symbol} from {market_open.strftime('%H:%M')} to {now.strftime('%H:%M')}")
        logger.info(f"  Expiries: {len(expiries)}, Strikes: {len(strikes)}, Options: {len(expiries) * len(strikes) * 2}")
        
        # First, get all instrument tokens in batches (much faster than one-by-one)
        options_list = []
        for expiry in expiries:
            for strike in strikes:
                for opt_type in ["CE", "PE"]:
                    options_list.append((expiry, strike, opt_type))
        
        logger.info(f"  Fetching instrument tokens for {len(options_list)} options...")
        tokens_map = self.get_option_instrument_tokens_batch(symbol, options_list)
        
        all_records = []
        options_processed = 0
        options_total = len(options_list)
        
        for expiry, strike, opt_type in options_list:
            options_processed += 1
            
            trading_symbol = build_option_symbol(symbol, expiry, strike, opt_type)
            token = tokens_map.get(trading_symbol)
            
            if token is None:
                continue
            
            try:
                # Fetch 1-minute historical data
                df = self.kite.fetch_historical_data(
                    instrument_token=token,
                    interval="minute",
                    from_date=market_open,
                    to_date=now
                )
                
                if df.empty:
                    continue
                
                # Convert to records
                for idx, row in df.iterrows():
                    all_records.append({
                        "timestamp": idx.to_pydatetime(),
                        "symbol": symbol,
                        "trading_symbol": trading_symbol,
                        "expiry": expiry,
                        "strike": strike,
                        "option_type": opt_type,
                        "underlying": spot_price,
                        "ltp": row.get("close", 0),
                        "bid": 0,
                        "bid_qty": 0,
                        "ask": 0,
                        "ask_qty": 0,
                        "volume": row.get("volume", 0),
                        "oi": 0,
                        "oi_day_high": 0,
                        "oi_day_low": 0,
                        "open": row.get("open", 0),
                        "high": row.get("high", 0),
                        "low": row.get("low", 0),
                        "close": row.get("close", 0),
                        "last_trade_time": None,
                    })
                
                # Progress logging
                if options_processed % 50 == 0:
                    logger.info(f"  Historical fetch progress: {options_processed}/{options_total} options, {len(all_records)} records")
                
                # Rate limiting - be conservative to avoid rate limits
                time.sleep(0.5)
                
            except Exception as e:
                logger.debug(f"Error fetching historical for {trading_symbol}: {e}")
                self.stats["errors"] += 1
            
            # Check for shutdown
            if shutdown_flag.is_set():
                logger.info("Shutdown requested during historical fetch")
                return all_records
        
        logger.info(f"Historical fetch complete for {symbol}: {len(all_records)} records from {options_processed} options")
        return all_records
    
    def backfill_historical_data(self):
        """
        Backfill historical data from market open to current time.
        Called once on startup.
        """
        if self.historical_backfill_done:
            return
        
        logger.info("=" * 60)
        logger.info("STARTING HISTORICAL DATA BACKFILL")
        logger.info("Fetching 1-minute options data from 9:15 AM to now...")
        logger.info("=" * 60)
        
        # Get current spot prices
        spot_prices = self.get_spot_prices()
        if not spot_prices:
            logger.warning("Could not get spot prices for historical backfill")
            self.historical_backfill_done = True
            return
        
        total_historical_records = 0
        
        for symbol in self.symbols:
            if symbol not in spot_prices:
                continue
            
            spot = spot_prices[symbol]
            logger.info(f"Backfilling {symbol} (spot: {spot:.2f})")
            
            records = self.fetch_historical_options_data(symbol, spot)
            
            if records:
                with self.buffer_lock:
                    self.buffers[symbol].extend(records)
                total_historical_records += len(records)
                
                # Save immediately
                self.save_buffer(symbol, force=True)
            
            if shutdown_flag.is_set():
                break
        
        self.stats["historical_records"] = total_historical_records
        self.historical_backfill_done = True
        
        logger.info("=" * 60)
        logger.info(f"HISTORICAL BACKFILL COMPLETE: {total_historical_records} records")
        logger.info("=" * 60)
    
    def collect_options_chain(self, symbol: str, spot_price: float) -> List[dict]:
        """Collect full options chain for a symbol."""
        config = INSTRUMENTS[symbol]
        exchange = config["exchange"]
        strike_interval = config["strike_interval"]
        num_strikes = config["num_strikes"]
        
        today = date.today()
        timestamp = datetime.now()
        
        # Get expiries and strikes
        expiries = get_expiries_to_collect(today)
        strikes = get_strikes_around_spot(spot_price, strike_interval, num_strikes)
        
        records = []
        
        # Build list of all option symbols to fetch
        option_symbols = []
        symbol_info = []  # Track (expiry, strike, opt_type) for each symbol
        
        for expiry in expiries:
            for strike in strikes:
                for opt_type in ["CE", "PE"]:
                    trading_symbol = build_option_symbol(symbol, expiry, strike, opt_type)
                    option_symbols.append(f"{exchange}:{trading_symbol}")
                    symbol_info.append((expiry, strike, opt_type, trading_symbol))
        
        # Fetch quotes in batches
        for i in range(0, len(option_symbols), self.batch_size):
            batch = option_symbols[i:i + self.batch_size]
            batch_info = symbol_info[i:i + self.batch_size]
            
            try:
                quotes = self.kite.get_quote(batch)
                
                if not quotes:
                    logger.debug(f"Empty quotes response for batch starting at {i}")
                    continue
                
                if quotes:
                    for j, full_symbol in enumerate(batch):
                        if full_symbol in quotes:
                            q = quotes[full_symbol]
                            expiry, strike, opt_type, trading_symbol = batch_info[j]
                            
                            # Get depth data
                            depth = q.get("depth", {})
                            buy_depth = depth.get("buy", [{}])
                            sell_depth = depth.get("sell", [{}])
                            
                            records.append({
                                "timestamp": timestamp,
                                "symbol": symbol,
                                "trading_symbol": trading_symbol,
                                "expiry": expiry,
                                "strike": strike,
                                "option_type": opt_type,
                                "underlying": spot_price,
                                "ltp": q.get("last_price", 0),
                                "bid": buy_depth[0].get("price", 0) if buy_depth else 0,
                                "bid_qty": buy_depth[0].get("quantity", 0) if buy_depth else 0,
                                "ask": sell_depth[0].get("price", 0) if sell_depth else 0,
                                "ask_qty": sell_depth[0].get("quantity", 0) if sell_depth else 0,
                                "volume": q.get("volume", 0),
                                "oi": q.get("oi", 0),
                                "oi_day_high": q.get("oi_day_high", 0),
                                "oi_day_low": q.get("oi_day_low", 0),
                                "open": q.get("ohlc", {}).get("open", 0),
                                "high": q.get("ohlc", {}).get("high", 0),
                                "low": q.get("ohlc", {}).get("low", 0),
                                "close": q.get("ohlc", {}).get("close", 0),
                                "last_trade_time": q.get("last_trade_time"),
                            })
                
                # Rate limiting between batches
                time.sleep(0.35)  # ~3 requests per second
                
            except Exception as e:
                logger.warning(f"Batch fetch error: {e}")
                self.stats["errors"] += 1
                time.sleep(1)
        
        return records
    
    def save_buffer(self, symbol: str, force: bool = False):
        """Save buffered data to parquet file."""
        with self.buffer_lock:
            buffer = self.buffers[symbol]
            
            # Save if buffer is large enough or forced
            if len(buffer) < 1000 and not force:
                return
            
            if not buffer:
                return
            
            df = pd.DataFrame(buffer)
            self.buffers[symbol] = []
        
        # Save to daily file
        today = date.today()
        filename = f"{symbol}_options_{today.strftime('%Y%m%d')}.parquet"
        filepath = OPTIONS_DATA_DIR / filename
        
        try:
            if filepath.exists():
                existing = pd.read_parquet(filepath)
                df = pd.concat([existing, df], ignore_index=True)
            
            df.to_parquet(filepath, index=False)
            logger.info(f"Saved {len(df)} records to {filepath}")
            
        except Exception as e:
            logger.error(f"Failed to save data: {e}")
            # Put data back in buffer
            with self.buffer_lock:
                self.buffers[symbol].extend(df.to_dict('records'))
    
    def run_collection_cycle(self):
        """Run one collection cycle for all symbols."""
        cycle_start = time.time()
        
        # Get spot prices
        spot_prices = self.get_spot_prices()
        if not spot_prices:
            logger.warning("Could not get spot prices, skipping cycle")
            return
        
        # Collect options for each symbol
        total_records = 0
        for symbol in self.symbols:
            if symbol not in spot_prices:
                continue
            
            spot = spot_prices[symbol]
            logger.info(f"Collecting {symbol} options (spot: {spot:.2f})")
            
            records = self.collect_options_chain(symbol, spot)
            
            if records:
                with self.buffer_lock:
                    self.buffers[symbol].extend(records)
                total_records += len(records)
                
                # Save if buffer is large
                self.save_buffer(symbol)
        
        # Update stats
        self.stats["collections"] += 1
        self.stats["records"] += total_records
        
        cycle_time = time.time() - cycle_start
        logger.info(f"Cycle complete: {total_records} records in {cycle_time:.1f}s")
    
    def run(self):
        """Main collection loop."""
        logger.info("=" * 60)
        logger.info("OPTIONS DATA COLLECTOR STARTED")
        logger.info(f"Symbols: {self.symbols}")
        logger.info(f"Interval: {self.interval_seconds} seconds")
        logger.info(f"Output: {OPTIONS_DATA_DIR}")
        logger.info("=" * 60)
        
        self.stats["start_time"] = datetime.now()
        
        # Register signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        while not shutdown_flag.is_set():
            # Wait for market to open
            if not is_market_hours():
                logger.info("Outside market hours")
                if not wait_for_market_open():
                    break
                continue
            
            # On first run during market hours, backfill historical data from 9:15 AM
            if not self.historical_backfill_done:
                try:
                    self.backfill_historical_data()
                except Exception as e:
                    logger.error(f"Historical backfill error: {e}")
                    self.stats["errors"] += 1
                    self.historical_backfill_done = True  # Don't retry on error
            
            # Run real-time collection
            try:
                self.run_collection_cycle()
            except Exception as e:
                logger.error(f"Collection error: {e}")
                self.stats["errors"] += 1
            
            # Wait for next interval
            next_collection = datetime.now() + timedelta(seconds=self.interval_seconds)
            while datetime.now() < next_collection and not shutdown_flag.is_set():
                time.sleep(1)
        
        # Final save
        logger.info("Saving remaining data...")
        for symbol in self.symbols:
            self.save_buffer(symbol, force=True)
        
        # Print stats
        runtime = (datetime.now() - self.stats["start_time"]).total_seconds() / 60
        logger.info("=" * 60)
        logger.info("COLLECTION COMPLETE")
        logger.info(f"Runtime: {runtime:.1f} minutes")
        logger.info(f"Historical records: {self.stats['historical_records']}")
        logger.info(f"Real-time collections: {self.stats['collections']}")
        logger.info(f"Real-time records: {self.stats['records']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Collect options chain data for backtesting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Collect NIFTY options every 1 minute (default)
    python collect_options_data.py
    
    # Collect both NIFTY and BANKNIFTY
    python collect_options_data.py --symbols NIFTY,BANKNIFTY
    
    # Collect every 30 seconds
    python collect_options_data.py --interval 30
        """
    )
    parser.add_argument(
        "--symbols", "-s", 
        default="NIFTY,BANKNIFTY",
        help="Comma-separated symbols to collect (default: NIFTY,BANKNIFTY)"
    )
    parser.add_argument(
        "--interval", "-i", 
        type=int, 
        default=60,
        help="Collection interval in seconds (default: 60)"
    )
    
    args = parser.parse_args()
    
    # Parse symbols
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    
    # Validate symbols
    for symbol in symbols:
        if symbol not in INSTRUMENTS:
            logger.error(f"Unknown symbol: {symbol}")
            logger.info(f"Available symbols: {list(INSTRUMENTS.keys())}")
            return
    
    # Create and run collector
    collector = OptionsDataCollector(
        symbols=symbols,
        interval_seconds=args.interval
    )
    
    collector.run()


if __name__ == "__main__":
    main()
