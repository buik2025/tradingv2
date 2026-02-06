"""
Download comprehensive historical data from Kite for backtesting.

Kite API limits:
- Daily data: ~2000 days (~5.5 years)
- 60-minute data: ~400 days
- 15-minute data: ~200 days  
- 5-minute data: ~100 days
- 3-minute data: ~100 days
- Rate limit: 3 requests per second

This script downloads MAXIMUM available data for:
1. All major instruments (NIFTY, BANKNIFTY, INDIA VIX, Gold, Crude, Silver)
2. All time intervals (day, 60min, 15min, 5min)
3. Saves to both CSV (historical/) and Parquet (cache/) for backtesting
"""

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from loguru import logger

from app.core.kite_client import KiteClient
from app.config.settings import Settings
from app.config.constants import (
    NIFTY_TOKEN, BANKNIFTY_TOKEN, INDIA_VIX_TOKEN,
    INTERVAL_5MIN, INTERVAL_15MIN, INTERVAL_DAY
)


# Output directories
DATA_DIR = Path(__file__).parent.parent / "data" / "historical"
CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# All instruments to download for backtesting
INSTRUMENTS = {
    # Equity Indices
    "NIFTY": {"token": NIFTY_TOKEN, "exchange": "NSE", "type": "index"},
    "BANKNIFTY": {"token": BANKNIFTY_TOKEN, "exchange": "NSE", "type": "index"},
    "INDIAVIX": {"token": INDIA_VIX_TOKEN, "exchange": "NSE", "type": "index"},
    # Commodities (MCX)
    "GOLD": {"token": 53505799, "exchange": "MCX", "type": "commodity"},
    "SILVER": {"token": 53505031, "exchange": "MCX", "type": "commodity"},
    "CRUDE": {"token": 53496327, "exchange": "MCX", "type": "commodity"},
}

# Maximum days available per interval (Kite limits)
INTERVAL_MAX_DAYS = {
    "day": 2000,       # ~5.5 years
    "60minute": 400,   # ~13 months
    "15minute": 200,   # ~6.5 months
    "5minute": 100,    # ~3 months
}

# All intervals to download
INTERVALS = ["day", "60minute", "15minute", "5minute"]


def download_data(
    kite: KiteClient, 
    token: int, 
    symbol: str, 
    interval: str,
    max_days: int
) -> pd.DataFrame:
    """
    Download OHLCV data for specified interval and duration.
    
    Handles chunking for large date ranges to avoid API limits.
    """
    logger.info(f"Downloading {interval} data for {symbol} (max {max_days} days)")
    
    all_data = []
    to_date = datetime.now()
    
    # Chunk size depends on interval
    if interval == "day":
        chunk_days = 365  # 1 year chunks for daily
    elif interval == "60minute":
        chunk_days = 60   # 2 months for hourly
    else:
        chunk_days = 30   # 1 month for smaller intervals
    
    current_to = to_date
    remaining_days = max_days
    
    while remaining_days > 0:
        chunk = min(chunk_days, remaining_days)
        current_from = current_to - timedelta(days=chunk)
        
        try:
            df = kite.fetch_historical_data(
                token,
                interval,
                current_from,
                current_to
            )
            
            if not df.empty:
                all_data.append(df)
                logger.debug(f"  {current_from.date()} to {current_to.date()}: {len(df)} bars")
            
            # Rate limiting - 3 req/sec max
            time.sleep(0.4)
            
        except Exception as e:
            logger.warning(f"Error fetching {current_from.date()} to {current_to.date()}: {e}")
            time.sleep(1)  # Extra delay on error
        
        current_to = current_from
        remaining_days -= chunk
    
    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        # Handle both 'date' column and index
        if 'date' in combined.columns:
            combined = combined.drop_duplicates(subset=['date']).sort_values('date')
        else:
            combined = combined[~combined.index.duplicated(keep='first')].sort_index()
        logger.info(f"Downloaded {len(combined)} {interval} bars for {symbol}")
        return combined
    
    logger.warning(f"No data downloaded for {symbol} ({interval})")
    return pd.DataFrame()


def calculate_regime_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate regime labels for ML training based on historical data.
    
    Labels:
    0 = RANGE_BOUND (low ADX, low vol)
    1 = MEAN_REVERSION (moderate ADX, extreme RSI)
    2 = TREND (high ADX)
    3 = CHAOS (high vol, gaps)
    """
    from app.services.technical import calculate_adx, calculate_rsi, calculate_atr
    from app.services.volatility import calculate_realized_vol
    
    if len(df) < 30:
        return df
    
    # Calculate indicators
    df = df.copy()
    
    # ADX
    adx = calculate_adx(df['high'], df['low'], df['close'], period=14)
    df['adx'] = adx
    
    # RSI
    rsi = calculate_rsi(df['close'], period=14)
    df['rsi'] = rsi
    
    # ATR
    atr = calculate_atr(df['high'], df['low'], df['close'], period=14)
    df['atr'] = atr
    df['atr_pct'] = atr / df['close']
    
    # Realized vol
    rv = calculate_realized_vol(df['close'], period=20, annualize=True)
    df['realized_vol'] = rv
    
    # Gap percentage
    df['gap_pct'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1)
    
    # Day range
    df['day_range_pct'] = (df['high'] - df['low']) / df['close']
    
    # IV percentile proxy (using Parkinson vol)
    import numpy as np
    log_hl = np.log(df['high'] / df['low'])
    parkinson_vol = np.sqrt(1 / (4 * np.log(2)) * (log_hl ** 2))
    df['parkinson_vol'] = parkinson_vol
    df['iv_percentile'] = parkinson_vol.rolling(252).apply(
        lambda x: (x < x.iloc[-1]).sum() / len(x) * 100 if len(x) > 1 else 50
    )
    
    # Label regimes based on rules
    def label_regime(row):
        if pd.isna(row['adx']) or pd.isna(row['rsi']):
            return -1  # Unknown
        
        adx = row['adx']
        rsi = row['rsi']
        iv_pct = row.get('iv_percentile', 50)
        gap = abs(row.get('gap_pct', 0))
        day_range = row.get('day_range_pct', 0.01)
        
        # CHAOS: High vol or large gaps
        if iv_pct > 75 or gap > 0.02 or day_range > 0.025:
            return 3
        
        # RANGE_BOUND: Low ADX, neutral RSI
        if adx < 12 and 40 <= rsi <= 60:
            return 0
        
        # MEAN_REVERSION: Moderate ADX, extreme RSI
        if 12 <= adx <= 25 and (rsi < 30 or rsi > 70):
            return 1
        
        # TREND: High ADX
        if adx > 25:
            return 2
        
        # Default to MEAN_REVERSION
        return 1
    
    df['regime_label'] = df.apply(label_regime, axis=1)
    
    return df


def save_data(df: pd.DataFrame, token: int, symbol: str, interval: str):
    """Save data to both CSV (historical/) and Parquet (cache/) for backtesting."""
    if df.empty:
        return
    
    # Ensure date column exists and is datetime
    if 'date' not in df.columns and isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
    
    # Save to historical/ as CSV (human readable)
    csv_filename = f"{symbol}_{interval}.csv"
    csv_path = DATA_DIR / csv_filename
    df.to_csv(csv_path, index=False)
    logger.info(f"Saved CSV: {csv_path} ({len(df)} rows)")
    
    # Save to cache/ as Parquet (for backtester) - use token in filename
    parquet_filename = f"{token}_{interval}.parquet"
    parquet_path = CACHE_DIR / parquet_filename
    
    # Set date as index for parquet (backtester expects this)
    df_parquet = df.copy()
    if 'date' in df_parquet.columns:
        df_parquet = df_parquet.set_index('date')
    df_parquet.to_parquet(parquet_path)
    logger.info(f"Saved Parquet: {parquet_path}")


def main():
    """Main download function - downloads ALL data for ALL instruments and intervals."""
    logger.info("=" * 70)
    logger.info("COMPREHENSIVE HISTORICAL DATA DOWNLOAD FOR BACKTESTING")
    logger.info("=" * 70)
    
    # Initialize Kite client
    settings = Settings()
    
    try:
        kite = KiteClient(
            api_key=settings.kite_api_key,
            access_token=settings.kite_access_token,
            paper_mode=False
        )
    except Exception as e:
        logger.error(f"Failed to initialize Kite client: {e}")
        logger.info("Please ensure KITE_API_KEY and KITE_ACCESS_TOKEN are set in .env")
        return
    
    # Summary tracking
    download_summary = []
    
    # Download ALL intervals for ALL instruments
    for symbol, info in INSTRUMENTS.items():
        token = info["token"]
        exchange = info["exchange"]
        inst_type = info["type"]
        
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing: {symbol} ({exchange}, {inst_type})")
        logger.info(f"Token: {token}")
        logger.info(f"{'='*50}")
        
        for interval in INTERVALS:
            max_days = INTERVAL_MAX_DAYS[interval]
            
            logger.info(f"\n--- {symbol} / {interval} (max {max_days} days) ---")
            
            try:
                df = download_data(kite, token, symbol, interval, max_days)
                
                if not df.empty:
                    # Calculate regime labels for daily data
                    if interval == "day":
                        try:
                            df = calculate_regime_labels(df)
                        except Exception as e:
                            logger.warning(f"Could not calculate regime labels: {e}")
                    
                    # Save to both CSV and Parquet
                    save_data(df, token, symbol, interval)
                    
                    # Track for summary
                    date_range = "N/A"
                    if 'date' in df.columns:
                        date_range = f"{df['date'].min().date()} to {df['date'].max().date()}"
                    elif isinstance(df.index, pd.DatetimeIndex):
                        date_range = f"{df.index.min().date()} to {df.index.max().date()}"
                    
                    download_summary.append({
                        "symbol": symbol,
                        "interval": interval,
                        "rows": len(df),
                        "date_range": date_range
                    })
                else:
                    logger.warning(f"No data for {symbol} ({interval})")
                    
            except Exception as e:
                logger.error(f"Failed to download {symbol} ({interval}): {e}")
            
            # Rate limiting between requests
            time.sleep(1)
        
        # Extra delay between instruments
        time.sleep(2)
    
    # Print summary
    logger.info("\n" + "=" * 70)
    logger.info("DOWNLOAD COMPLETE!")
    logger.info("=" * 70)
    
    print("\n" + "=" * 70)
    print("DOWNLOAD SUMMARY")
    print("=" * 70)
    print(f"\nHistorical data saved to: {DATA_DIR}")
    print(f"Cache data saved to: {CACHE_DIR}")
    print("\nDownloaded files:")
    print("-" * 70)
    print(f"{'Symbol':<12} {'Interval':<12} {'Rows':<10} {'Date Range'}")
    print("-" * 70)
    
    for item in download_summary:
        print(f"{item['symbol']:<12} {item['interval']:<12} {item['rows']:<10} {item['date_range']}")
    
    print("-" * 70)
    print(f"Total: {len(download_summary)} files downloaded")
    
    # List cache files
    print("\nCache files (for backtester):")
    for f in sorted(CACHE_DIR.glob("*.parquet")):
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name}: {size_mb:.2f} MB")


def download_single(symbol: str, interval: str = None):
    """Download data for a single instrument (utility function)."""
    if symbol.upper() not in INSTRUMENTS:
        print(f"Unknown symbol: {symbol}")
        print(f"Available: {list(INSTRUMENTS.keys())}")
        return
    
    settings = Settings()
    kite = KiteClient(
        api_key=settings.kite_api_key,
        access_token=settings.kite_access_token,
        paper_mode=False
    )
    
    info = INSTRUMENTS[symbol.upper()]
    token = info["token"]
    
    intervals = [interval] if interval else INTERVALS
    
    for intv in intervals:
        max_days = INTERVAL_MAX_DAYS.get(intv, 100)
        df = download_data(kite, token, symbol.upper(), intv, max_days)
        if not df.empty:
            if intv == "day":
                df = calculate_regime_labels(df)
            save_data(df, token, symbol.upper(), intv)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Download historical data for backtesting")
    parser.add_argument("--symbol", "-s", help="Download single symbol (e.g., NIFTY)")
    parser.add_argument("--interval", "-i", help="Specific interval (day, 60minute, 15minute, 5minute)")
    parser.add_argument("--all", "-a", action="store_true", help="Download all instruments and intervals")
    
    args = parser.parse_args()
    
    if args.symbol:
        download_single(args.symbol, args.interval)
    else:
        main()
