#!/usr/bin/env python3
"""
Download historical data for backtesting.

Downloads NIFTY, BANKNIFTY, and VIX data from Kite API.
Saves to data/cache/ as parquet files.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from datetime import datetime, timedelta, date
from pathlib import Path
import pandas as pd
from loguru import logger

from app.core.kite_client import KiteClient
from app.core.credentials import get_kite_credentials
from app.config.settings import Settings
from app.config.constants import (
    NIFTY_TOKEN, BANKNIFTY_TOKEN, INDIA_VIX_TOKEN,
    GOLDM_TOKEN, SILVERM_TOKEN, CRUDE_TOKEN, NATURALGAS_TOKEN
)


# Configuration
INSTRUMENTS = {
    "NIFTY": {"token": NIFTY_TOKEN, "intervals": ["minute", "5minute", "day"]},
    "BANKNIFTY": {"token": BANKNIFTY_TOKEN, "intervals": ["minute", "5minute", "day"]},
    "INDIAVIX": {"token": INDIA_VIX_TOKEN, "intervals": ["day"]},
    # MCX Commodities
    "GOLDM": {"token": GOLDM_TOKEN, "intervals": ["minute", "5minute", "day"]},
    "SILVERM": {"token": SILVERM_TOKEN, "intervals": ["minute", "5minute", "day"]},
    "CRUDE": {"token": CRUDE_TOKEN, "intervals": ["minute", "5minute", "day"]},
    "NATURALGAS": {"token": NATURALGAS_TOKEN, "intervals": ["minute", "5minute", "day"]},
}

# Date range for backtesting (Nov 1, 2025 to present)
START_DATE = date(2025, 11, 1)
END_DATE = date.today()

# Output directories
CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
HIST_DIR = Path(__file__).parent.parent / "data" / "historical"


def get_kite_client() -> KiteClient:
    """Get authenticated Kite client."""
    # Try database credentials first
    creds = get_kite_credentials()
    if creds and not creds.get('is_expired'):
        logger.info(f"Using database credentials (user: {creds.get('user_id')})")
        return KiteClient(
            api_key=creds['api_key'],
            access_token=creds['access_token'],
            paper_mode=False
        )
    
    # Fall back to settings
    settings = Settings()
    logger.info("Using settings credentials")
    return KiteClient(
        api_key=settings.kite_api_key,
        access_token=settings.kite_access_token,
        paper_mode=False
    )


def download_data(kite: KiteClient, symbol: str, token: int, interval: str, 
                  start_date: date, end_date: date) -> pd.DataFrame:
    """
    Download historical data in chunks.
    
    Kite API limits:
    - day: 2000 days per request
    - 5minute: 100 days per request
    """
    logger.info(f"Downloading {symbol} ({interval}) from {start_date} to {end_date}")
    
    # Chunk size based on interval (Kite API limits)
    if interval == "day":
        chunk_days = 365
    elif interval in ["60minute", "30minute"]:
        chunk_days = 60
    elif interval == "minute":
        chunk_days = 7  # 1-min data: max ~7 days per request
    else:  # 5minute, 15minute
        chunk_days = 30
    
    all_data = []
    current_end = datetime.combine(end_date, datetime.max.time())
    target_start = datetime.combine(start_date, datetime.min.time())
    
    while current_end > target_start:
        chunk_start = max(current_end - timedelta(days=chunk_days), target_start)
        
        try:
            df = kite.fetch_historical_data(
                instrument_token=token,
                interval=interval,
                from_date=chunk_start,
                to_date=current_end
            )
            
            if not df.empty:
                all_data.append(df)
                logger.debug(f"  {chunk_start.date()} to {current_end.date()}: {len(df)} bars")
            
            time.sleep(0.4)  # Rate limiting
            
        except Exception as e:
            logger.warning(f"  Chunk error: {e}")
            time.sleep(1)
        
        current_end = chunk_start - timedelta(seconds=1)
    
    if all_data:
        combined = pd.concat(all_data)
        combined = combined[~combined.index.duplicated(keep='first')]
        combined = combined.sort_index()
        logger.info(f"  Total: {len(combined)} bars")
        return combined
    
    logger.warning(f"  No data downloaded for {symbol} ({interval})")
    return pd.DataFrame()


def save_data(df: pd.DataFrame, symbol: str, token: int, interval: str):
    """Save data to parquet and CSV."""
    if df.empty:
        return
    
    # Ensure directories exist
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save parquet (for backtester)
    parquet_path = CACHE_DIR / f"{token}_{interval}.parquet"
    df.to_parquet(parquet_path)
    logger.info(f"  Saved: {parquet_path}")
    
    # Save CSV (for reference)
    csv_path = HIST_DIR / f"{symbol}_{interval}.csv"
    df.to_csv(csv_path)
    logger.info(f"  Saved: {csv_path}")


def main():
    """Main download function."""
    logger.info("=" * 60)
    logger.info("HISTORICAL DATA DOWNLOAD FOR BACKTESTING")
    logger.info(f"Date range: {START_DATE} to {END_DATE}")
    logger.info("=" * 60)
    
    # Get Kite client
    try:
        kite = get_kite_client()
    except Exception as e:
        logger.error(f"Failed to initialize Kite client: {e}")
        logger.error("Please login via the frontend Profile page first.")
        return
    
    # Download each instrument
    for symbol, config in INSTRUMENTS.items():
        token = config["token"]
        
        for interval in config["intervals"]:
            try:
                df = download_data(kite, symbol, token, interval, START_DATE, END_DATE)
                save_data(df, symbol, token, interval)
            except Exception as e:
                logger.error(f"Failed to download {symbol} ({interval}): {e}")
            
            time.sleep(0.5)  # Rate limiting between instruments
    
    logger.info("=" * 60)
    logger.info("DOWNLOAD COMPLETE")
    logger.info("=" * 60)
    
    # Summary
    logger.info("\nDownloaded files:")
    for f in sorted(CACHE_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(f)
            logger.info(f"  {f.name}: {len(df)} rows, {df.index.min()} to {df.index.max()}")
        except Exception as e:
            logger.info(f"  {f.name}: Error reading - {e}")


if __name__ == "__main__":
    main()
