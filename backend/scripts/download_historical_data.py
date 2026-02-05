"""
Download deep historical data from Kite for ML training.

Kite API limits:
- Historical data available for last 2000 days (~5.5 years) for daily data
- Intraday data (5min, 15min, etc.) available for last 60 days only
- Rate limit: 3 requests per second

This script downloads:
1. Daily OHLCV for NIFTY, BANKNIFTY, INDIA VIX (max available)
2. 5-minute data for recent 60 days
3. Saves to CSV for ML training
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


# Output directory
DATA_DIR = Path(__file__).parent.parent / "data" / "historical"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Instruments to download
INSTRUMENTS = {
    "NIFTY": NIFTY_TOKEN,
    "BANKNIFTY": BANKNIFTY_TOKEN,
    "INDIAVIX": INDIA_VIX_TOKEN,
}

# Additional indices (if available)
ADDITIONAL_INDICES = {
    "NIFTY_FIN": 257801,  # NIFTY FIN SERVICE
    "NIFTY_IT": 259849,   # NIFTY IT
}


def download_daily_data(kite: KiteClient, token: int, symbol: str, years: int = 5) -> pd.DataFrame:
    """
    Download daily OHLCV data for specified years.
    
    Kite allows ~2000 days of daily data.
    """
    logger.info(f"Downloading daily data for {symbol} ({years} years)")
    
    to_date = datetime.now()
    from_date = to_date - timedelta(days=years * 365)
    
    try:
        df = kite.fetch_historical_data(
            token, 
            INTERVAL_DAY, 
            from_date, 
            to_date
        )
        
        if not df.empty:
            logger.info(f"Downloaded {len(df)} daily bars for {symbol}")
            return df
        else:
            logger.warning(f"No daily data for {symbol}")
            return pd.DataFrame()
            
    except Exception as e:
        logger.error(f"Error downloading daily data for {symbol}: {e}")
        return pd.DataFrame()


def download_intraday_data(
    kite: KiteClient, 
    token: int, 
    symbol: str, 
    interval: str = INTERVAL_5MIN,
    days: int = 60
) -> pd.DataFrame:
    """
    Download intraday OHLCV data.
    
    Kite allows only 60 days of intraday data.
    Need to make multiple requests for different date ranges.
    """
    logger.info(f"Downloading {interval} data for {symbol} ({days} days)")
    
    all_data = []
    to_date = datetime.now()
    
    # Kite allows max 60 days per request for intraday
    # But we need to chunk to avoid timeouts
    chunk_days = 30
    
    current_to = to_date
    remaining_days = days
    
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
                logger.debug(f"Downloaded {len(df)} bars from {current_from.date()} to {current_to.date()}")
            
            # Rate limiting
            time.sleep(0.5)
            
        except Exception as e:
            logger.warning(f"Error fetching chunk: {e}")
        
        current_to = current_from
        remaining_days -= chunk
    
    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        combined = combined.drop_duplicates(subset=['date']).sort_values('date')
        logger.info(f"Downloaded {len(combined)} {interval} bars for {symbol}")
        return combined
    
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


def save_data(df: pd.DataFrame, symbol: str, interval: str):
    """Save data to CSV."""
    if df.empty:
        return
    
    filename = f"{symbol}_{interval}.csv"
    filepath = DATA_DIR / filename
    
    df.to_csv(filepath, index=False)
    logger.info(f"Saved {len(df)} rows to {filepath}")


def main():
    """Main download function."""
    logger.info("=" * 60)
    logger.info("Historical Data Download for ML Training")
    logger.info("=" * 60)
    
    # Initialize Kite client
    settings = Settings()
    kite = KiteClient(settings)
    
    if not kite.is_authenticated():
        logger.error("Kite not authenticated. Please login first.")
        logger.info("Run the main app and complete Kite login, then retry.")
        return
    
    # Download daily data for all instruments
    for symbol, token in INSTRUMENTS.items():
        logger.info(f"\n--- Processing {symbol} ---")
        
        # Daily data (5 years)
        daily_df = download_daily_data(kite, token, symbol, years=5)
        if not daily_df.empty:
            # Calculate regime labels
            daily_df = calculate_regime_labels(daily_df)
            save_data(daily_df, symbol, "daily")
        
        time.sleep(1)  # Rate limiting
        
        # 5-minute data (60 days)
        intraday_df = download_intraday_data(kite, token, symbol, INTERVAL_5MIN, days=60)
        if not intraday_df.empty:
            save_data(intraday_df, symbol, "5min")
        
        time.sleep(1)
    
    # Download additional indices if available
    for symbol, token in ADDITIONAL_INDICES.items():
        logger.info(f"\n--- Processing {symbol} ---")
        try:
            daily_df = download_daily_data(kite, token, symbol, years=3)
            if not daily_df.empty:
                daily_df = calculate_regime_labels(daily_df)
                save_data(daily_df, symbol, "daily")
        except Exception as e:
            logger.warning(f"Could not download {symbol}: {e}")
        
        time.sleep(1)
    
    logger.info("\n" + "=" * 60)
    logger.info("Download complete!")
    logger.info(f"Data saved to: {DATA_DIR}")
    logger.info("=" * 60)
    
    # Print summary
    print("\nDownloaded files:")
    for f in DATA_DIR.glob("*.csv"):
        df = pd.read_csv(f)
        print(f"  {f.name}: {len(df)} rows")


if __name__ == "__main__":
    main()
