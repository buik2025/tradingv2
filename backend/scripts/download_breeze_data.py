"""
Download comprehensive historical data from ICICI Direct Breeze API.

Breeze API offers:
- 10 years of historical market data
- 1-second OHLCV data
- Historical options and futures data

This script downloads:
1. Index data: NIFTY, BANKNIFTY, FINNIFTY, VIX (1-second intervals)
2. Options data: 10 strikes above and below spot for each expiry

Setup:
1. pip install breeze-connect
2. Get API credentials from https://api.icicidirect.com/apiuser/home
3. Set environment variables:
   - BREEZE_API_KEY
   - BREEZE_API_SECRET
   - BREEZE_SESSION_TOKEN (generated via login flow)

Usage:
    python download_breeze_data.py --all           # Download everything
    python download_breeze_data.py --indices       # Download only indices
    python download_breeze_data.py --options       # Download only options
    python download_breeze_data.py --symbol NIFTY  # Download specific symbol
"""

import os
import sys
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from loguru import logger

try:
    from breeze_connect import BreezeConnect
except ImportError:
    logger.error("breeze-connect not installed. Run: pip install breeze-connect")
    sys.exit(1)


# =============================================================================
# Configuration
# =============================================================================

# Output directories
DATA_DIR = Path(__file__).parent.parent / "data" / "breeze"
INDICES_DIR = DATA_DIR / "indices"
OPTIONS_DIR = DATA_DIR / "options"
FUTURES_DIR = DATA_DIR / "futures"

for d in [DATA_DIR, INDICES_DIR, OPTIONS_DIR, FUTURES_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class Interval(Enum):
    """Available intervals in Breeze API."""
    SECOND_1 = "1second"
    MINUTE_1 = "1minute"
    MINUTE_5 = "5minute"
    MINUTE_30 = "30minute"
    DAY = "1day"


@dataclass
class IndexConfig:
    """Configuration for an index."""
    symbol: str
    exchange: str
    stock_code: str


# Indices to download
INDICES = {
    "NIFTY": IndexConfig(symbol="NIFTY", exchange="NSE", stock_code="NIFTY"),
    "BANKNIFTY": IndexConfig(symbol="BANKNIFTY", exchange="NSE", stock_code="BANKNIFTY"),
    "FINNIFTY": IndexConfig(symbol="FINNIFTY", exchange="NSE", stock_code="FINNIFTY"),
    "VIX": IndexConfig(symbol="INDIAVIX", exchange="NSE", stock_code="INDIAVIX"),
}

# Options configuration
OPTIONS_CONFIG = {
    "NIFTY": {
        "exchange": "NFO",
        "stock_code": "NIFTY",
        "strike_gap": 50,      # Strike price gap
        "lot_size": 25,        # Current lot size (will be 75 from April 2025)
    },
    "BANKNIFTY": {
        "exchange": "NFO",
        "stock_code": "BANKNIFTY",
        "strike_gap": 100,
        "lot_size": 15,
    },
    "FINNIFTY": {
        "exchange": "NFO",
        "stock_code": "FINNIFTY",
        "strike_gap": 50,
        "lot_size": 25,
    },
}

# Rate limiting
RATE_LIMIT_DELAY = 0.5  # seconds between API calls
MAX_RETRIES = 3


# =============================================================================
# Breeze Client Wrapper
# =============================================================================

class BreezeDataDownloader:
    """Wrapper for Breeze API data downloads."""
    
    def __init__(self):
        """Initialize Breeze connection."""
        self.api_key = "8Y622p40400A`67=48C157I9aeq%3997"
        self.api_secret = "W7(193N103431w1y7084250e61Q751l1"
        self.session_token = "54682923"
        # self.api_key = os.getenv("BREEZE_API_KEY")
        # self.api_secret = os.getenv("BREEZE_API_SECRET")
        # self.session_token = os.getenv("BREEZE_SESSION_TOKEN")
        
        if not all([self.api_key, self.api_secret, self.session_token]):
            raise ValueError(
                "Missing Breeze credentials. Set environment variables:\n"
                "  BREEZE_API_KEY\n"
                "  BREEZE_API_SECRET\n"
                "  BREEZE_SESSION_TOKEN\n\n"
                "Get credentials from: https://api.icicidirect.com/apiuser/home"
            )
        
        self.breeze = BreezeConnect(api_key=self.api_key)
        self._connect()
        
    def _connect(self):
        """Establish connection with Breeze API."""
        try:
            self.breeze.generate_session(
                api_secret=self.api_secret,
                session_token=self.session_token
            )
            logger.info("Connected to Breeze API successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Breeze API: {e}")
            raise
    
    def get_spot_price(self, stock_code: str, exchange: str = "NSE") -> float:
        """Get current spot price for an index."""
        try:
            quotes = self.breeze.get_quotes(
                stock_code=stock_code,
                exchange_code=exchange,
                product_type="cash"
            )
            if quotes and quotes.get("Success"):
                return float(quotes["Success"][0].get("ltp", 0))
        except Exception as e:
            logger.warning(f"Could not get spot price for {stock_code}: {e}")
        return 0
    
    def get_expiry_dates(self, stock_code: str, exchange: str = "NFO") -> List[datetime]:
        """Get available expiry dates for options."""
        try:
            # Breeze provides expiry list via option chain
            # We'll generate weekly expiries for the next 3 months
            expiries = []
            today = datetime.now()
            
            # Find next Thursday (weekly expiry for NIFTY)
            days_until_thursday = (3 - today.weekday()) % 7
            if days_until_thursday == 0 and today.hour >= 15:
                days_until_thursday = 7
            
            next_expiry = today + timedelta(days=days_until_thursday)
            
            # Generate next 12 weekly expiries
            for i in range(12):
                expiry_date = next_expiry + timedelta(weeks=i)
                expiries.append(expiry_date)
            
            logger.info(f"Generated {len(expiries)} expiry dates for {stock_code}")
            return expiries
            
        except Exception as e:
            logger.error(f"Error getting expiry dates: {e}")
            return []
    
    def download_historical_data(
        self,
        stock_code: str,
        exchange: str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
        product_type: str = "cash",
        expiry_date: str = None,
        strike_price: str = None,
        right: str = None
    ) -> pd.DataFrame:
        """
        Download historical OHLCV data.
        
        Args:
            stock_code: Symbol (e.g., "NIFTY")
            exchange: Exchange code (NSE, NFO, etc.)
            interval: Time interval (1second, 1minute, 5minute, 30minute, 1day)
            from_date: Start date
            to_date: End date
            product_type: "cash" for equity, "options" for options, "futures" for futures
            expiry_date: Expiry date for F&O (format: "2026-02-27")
            strike_price: Strike price for options
            right: "call" or "put" for options
            
        Returns:
            DataFrame with OHLCV data
        """
        all_data = []
        current_from = from_date
        
        # Chunk by days based on interval
        if interval == "1second":
            chunk_days = 1  # 1 day at a time for 1-second data
        elif interval == "1minute":
            chunk_days = 7
        elif interval == "5minute":
            chunk_days = 30
        else:
            chunk_days = 365
        
        while current_from < to_date:
            current_to = min(current_from + timedelta(days=chunk_days), to_date)
            
            for retry in range(MAX_RETRIES):
                try:
                    params = {
                        "interval": interval,
                        "from_date": current_from.strftime("%Y-%m-%dT07:00:00.000Z"),
                        "to_date": current_to.strftime("%Y-%m-%dT15:30:00.000Z"),
                        "stock_code": stock_code,
                        "exchange_code": exchange,
                        "product_type": product_type,
                    }
                    
                    if expiry_date:
                        params["expiry_date"] = expiry_date
                    if strike_price:
                        params["strike_price"] = strike_price
                    if right:
                        params["right"] = right
                    
                    response = self.breeze.get_historical_data_v2(**params)
                    
                    if response and response.get("Success"):
                        data = response["Success"]
                        if data:
                            df = pd.DataFrame(data)
                            all_data.append(df)
                            logger.debug(
                                f"  {current_from.date()} to {current_to.date()}: "
                                f"{len(df)} bars"
                            )
                    
                    time.sleep(RATE_LIMIT_DELAY)
                    break
                    
                except Exception as e:
                    logger.warning(f"Retry {retry+1}/{MAX_RETRIES} for {stock_code}: {e}")
                    time.sleep(RATE_LIMIT_DELAY * (retry + 1))
            
            current_from = current_to
        
        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            
            # Standardize column names
            column_mapping = {
                "datetime": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            }
            combined = combined.rename(columns=column_mapping)
            
            # Convert date column
            if "date" in combined.columns:
                combined["date"] = pd.to_datetime(combined["date"])
                combined = combined.sort_values("date").drop_duplicates(subset=["date"])
            
            return combined
        
        return pd.DataFrame()
    
    def download_index_data(
        self,
        index_name: str,
        interval: str = "1second",
        days_back: int = 30
    ) -> pd.DataFrame:
        """
        Download index historical data.
        
        Args:
            index_name: Index name (NIFTY, BANKNIFTY, FINNIFTY, VIX)
            interval: Time interval
            days_back: Number of days to download
            
        Returns:
            DataFrame with OHLCV data
        """
        if index_name not in INDICES:
            logger.error(f"Unknown index: {index_name}")
            return pd.DataFrame()
        
        config = INDICES[index_name]
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days_back)
        
        logger.info(f"Downloading {index_name} {interval} data for {days_back} days")
        
        df = self.download_historical_data(
            stock_code=config.stock_code,
            exchange=config.exchange,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            product_type="cash"
        )
        
        if not df.empty:
            logger.info(f"Downloaded {len(df)} bars for {index_name}")
        
        return df
    
    def download_options_data(
        self,
        underlying: str,
        expiry_date: datetime,
        spot_price: float,
        num_strikes: int = 10,
        interval: str = "1second",
        days_back: int = 7
    ) -> Dict[str, pd.DataFrame]:
        """
        Download options data for strikes around spot price.
        
        Args:
            underlying: Underlying symbol (NIFTY, BANKNIFTY, FINNIFTY)
            expiry_date: Option expiry date
            spot_price: Current spot price
            num_strikes: Number of strikes above and below spot
            interval: Time interval
            days_back: Number of days to download
            
        Returns:
            Dictionary with strike -> DataFrame mapping
        """
        if underlying not in OPTIONS_CONFIG:
            logger.error(f"Unknown underlying: {underlying}")
            return {}
        
        config = OPTIONS_CONFIG[underlying]
        strike_gap = config["strike_gap"]
        
        # Calculate ATM strike
        atm_strike = round(spot_price / strike_gap) * strike_gap
        
        # Generate strikes
        strikes = []
        for i in range(-num_strikes, num_strikes + 1):
            strikes.append(atm_strike + (i * strike_gap))
        
        logger.info(
            f"Downloading options for {underlying} expiry {expiry_date.date()}\n"
            f"  Spot: {spot_price}, ATM: {atm_strike}\n"
            f"  Strikes: {strikes[0]} to {strikes[-1]} ({len(strikes)} strikes)"
        )
        
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days_back)
        expiry_str = expiry_date.strftime("%Y-%m-%d")
        
        options_data = {}
        
        for strike in strikes:
            for right in ["call", "put"]:
                option_key = f"{underlying}_{expiry_date.strftime('%Y%m%d')}_{strike}_{right.upper()}"
                
                logger.info(f"  Downloading {option_key}...")
                
                df = self.download_historical_data(
                    stock_code=config["stock_code"],
                    exchange=config["exchange"],
                    interval=interval,
                    from_date=from_date,
                    to_date=to_date,
                    product_type="options",
                    expiry_date=expiry_str,
                    strike_price=str(strike),
                    right=right
                )
                
                if not df.empty:
                    options_data[option_key] = df
                    logger.debug(f"    {len(df)} bars downloaded")
                
                time.sleep(RATE_LIMIT_DELAY)
        
        return options_data
    
    def download_futures_data(
        self,
        underlying: str,
        expiry_date: datetime,
        interval: str = "1second",
        days_back: int = 30
    ) -> pd.DataFrame:
        """
        Download futures data.
        
        Args:
            underlying: Underlying symbol
            expiry_date: Futures expiry date
            interval: Time interval
            days_back: Number of days to download
            
        Returns:
            DataFrame with OHLCV data
        """
        if underlying not in OPTIONS_CONFIG:
            logger.error(f"Unknown underlying: {underlying}")
            return pd.DataFrame()
        
        config = OPTIONS_CONFIG[underlying]
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days_back)
        expiry_str = expiry_date.strftime("%Y-%m-%d")
        
        logger.info(f"Downloading {underlying} futures expiry {expiry_date.date()}")
        
        df = self.download_historical_data(
            stock_code=config["stock_code"],
            exchange=config["exchange"],
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            product_type="futures",
            expiry_date=expiry_str
        )
        
        return df


# =============================================================================
# Data Saving Functions
# =============================================================================

def save_index_data(df: pd.DataFrame, index_name: str, interval: str):
    """Save index data to CSV and Parquet."""
    if df.empty:
        return
    
    base_name = f"{index_name}_{interval}"
    
    # CSV for human readability
    csv_path = INDICES_DIR / f"{base_name}.csv"
    df.to_csv(csv_path, index=False)
    logger.info(f"Saved: {csv_path}")
    
    # Parquet for efficient storage
    parquet_path = INDICES_DIR / f"{base_name}.parquet"
    df.to_parquet(parquet_path, index=False)
    logger.info(f"Saved: {parquet_path}")


def save_options_data(options_data: Dict[str, pd.DataFrame], underlying: str, interval: str):
    """Save options data to Parquet files."""
    if not options_data:
        return
    
    output_dir = OPTIONS_DIR / underlying / interval
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for option_key, df in options_data.items():
        if df.empty:
            continue
        
        parquet_path = output_dir / f"{option_key}.parquet"
        df.to_parquet(parquet_path, index=False)
    
    logger.info(f"Saved {len(options_data)} option files to {output_dir}")


def save_futures_data(df: pd.DataFrame, underlying: str, expiry_date: datetime, interval: str):
    """Save futures data to Parquet."""
    if df.empty:
        return
    
    output_dir = FUTURES_DIR / underlying
    output_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{underlying}_{expiry_date.strftime('%Y%m%d')}_{interval}.parquet"
    parquet_path = output_dir / filename
    df.to_parquet(parquet_path, index=False)
    logger.info(f"Saved: {parquet_path}")


# =============================================================================
# Main Download Functions
# =============================================================================

def download_all_indices(downloader: BreezeDataDownloader, interval: str = "1second", days_back: int = 30):
    """Download all index data."""
    logger.info("=" * 70)
    logger.info(f"DOWNLOADING INDEX DATA ({interval}, {days_back} days)")
    logger.info("=" * 70)
    
    for index_name in INDICES:
        try:
            df = downloader.download_index_data(index_name, interval, days_back)
            save_index_data(df, index_name, interval)
        except Exception as e:
            logger.error(f"Failed to download {index_name}: {e}")
        
        time.sleep(1)


def download_all_options(
    downloader: BreezeDataDownloader,
    interval: str = "1second",
    days_back: int = 7,
    num_expiries: int = 4,
    num_strikes: int = 10
):
    """Download options data for all underlyings."""
    logger.info("=" * 70)
    logger.info(f"DOWNLOADING OPTIONS DATA ({interval}, {days_back} days)")
    logger.info("=" * 70)
    
    for underlying in OPTIONS_CONFIG:
        try:
            # Get spot price
            spot_price = downloader.get_spot_price(underlying)
            if spot_price == 0:
                logger.warning(f"Could not get spot price for {underlying}, using default")
                # Use approximate values
                defaults = {"NIFTY": 23000, "BANKNIFTY": 48000, "FINNIFTY": 23500}
                spot_price = defaults.get(underlying, 23000)
            
            logger.info(f"\n{underlying} spot price: {spot_price}")
            
            # Get expiry dates
            expiries = downloader.get_expiry_dates(underlying)[:num_expiries]
            
            for expiry in expiries:
                try:
                    options_data = downloader.download_options_data(
                        underlying=underlying,
                        expiry_date=expiry,
                        spot_price=spot_price,
                        num_strikes=num_strikes,
                        interval=interval,
                        days_back=days_back
                    )
                    save_options_data(options_data, underlying, interval)
                    
                except Exception as e:
                    logger.error(f"Failed to download options for {underlying} {expiry}: {e}")
                
                time.sleep(2)
                
        except Exception as e:
            logger.error(f"Failed to process {underlying}: {e}")


def download_all_futures(
    downloader: BreezeDataDownloader,
    interval: str = "1second",
    days_back: int = 30,
    num_expiries: int = 3
):
    """Download futures data for all underlyings."""
    logger.info("=" * 70)
    logger.info(f"DOWNLOADING FUTURES DATA ({interval}, {days_back} days)")
    logger.info("=" * 70)
    
    for underlying in OPTIONS_CONFIG:
        try:
            expiries = downloader.get_expiry_dates(underlying)[:num_expiries]
            
            for expiry in expiries:
                try:
                    df = downloader.download_futures_data(
                        underlying=underlying,
                        expiry_date=expiry,
                        interval=interval,
                        days_back=days_back
                    )
                    save_futures_data(df, underlying, expiry, interval)
                    
                except Exception as e:
                    logger.error(f"Failed to download futures for {underlying} {expiry}: {e}")
                
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Failed to process {underlying}: {e}")


def print_summary():
    """Print summary of downloaded data."""
    print("\n" + "=" * 70)
    print("DOWNLOAD SUMMARY")
    print("=" * 70)
    
    print(f"\nData directory: {DATA_DIR}")
    
    # Count files
    for subdir, name in [(INDICES_DIR, "Indices"), (OPTIONS_DIR, "Options"), (FUTURES_DIR, "Futures")]:
        if subdir.exists():
            files = list(subdir.rglob("*.parquet"))
            total_size = sum(f.stat().st_size for f in files) / (1024 * 1024)
            print(f"\n{name}:")
            print(f"  Files: {len(files)}")
            print(f"  Total size: {total_size:.2f} MB")


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Download historical data from ICICI Direct Breeze API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python download_breeze_data.py --all                    # Download everything
  python download_breeze_data.py --indices --days 60      # Download 60 days of index data
  python download_breeze_data.py --options --strikes 15   # Download 15 strikes each side
  python download_breeze_data.py --symbol NIFTY           # Download only NIFTY data

Environment Variables Required:
  BREEZE_API_KEY        - API key from ICICI Direct
  BREEZE_API_SECRET     - API secret
  BREEZE_SESSION_TOKEN  - Session token (from login flow)

Get credentials: https://api.icicidirect.com/apiuser/home
        """
    )
    
    parser.add_argument("--all", "-a", action="store_true", help="Download all data")
    parser.add_argument("--indices", action="store_true", help="Download index data only")
    parser.add_argument("--options", action="store_true", help="Download options data only")
    parser.add_argument("--futures", action="store_true", help="Download futures data only")
    parser.add_argument("--symbol", "-s", help="Download specific symbol only")
    parser.add_argument("--interval", "-i", default="1second", 
                       choices=["1second", "1minute", "5minute", "30minute", "1day"],
                       help="Time interval (default: 1second)")
    parser.add_argument("--days", "-d", type=int, default=30,
                       help="Days of history to download (default: 30)")
    parser.add_argument("--strikes", type=int, default=10,
                       help="Number of strikes above/below spot (default: 10)")
    parser.add_argument("--expiries", type=int, default=4,
                       help="Number of expiries to download (default: 4)")
    
    args = parser.parse_args()
    
    # Initialize downloader
    try:
        downloader = BreezeDataDownloader()
    except ValueError as e:
        logger.error(str(e))
        print("\n" + str(e))
        return
    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        return
    
    # Execute based on arguments
    if args.all:
        download_all_indices(downloader, args.interval, args.days)
        download_all_options(downloader, args.interval, min(args.days, 7), args.expiries, args.strikes)
        download_all_futures(downloader, args.interval, args.days, args.expiries)
    elif args.indices:
        download_all_indices(downloader, args.interval, args.days)
    elif args.options:
        download_all_options(downloader, args.interval, min(args.days, 7), args.expiries, args.strikes)
    elif args.futures:
        download_all_futures(downloader, args.interval, args.days, args.expiries)
    elif args.symbol:
        if args.symbol.upper() in INDICES:
            df = downloader.download_index_data(args.symbol.upper(), args.interval, args.days)
            save_index_data(df, args.symbol.upper(), args.interval)
        elif args.symbol.upper() in OPTIONS_CONFIG:
            spot = downloader.get_spot_price(args.symbol.upper())
            expiries = downloader.get_expiry_dates(args.symbol.upper())[:args.expiries]
            for expiry in expiries:
                options_data = downloader.download_options_data(
                    args.symbol.upper(), expiry, spot, args.strikes, args.interval, args.days
                )
                save_options_data(options_data, args.symbol.upper(), args.interval)
        else:
            logger.error(f"Unknown symbol: {args.symbol}")
            print(f"Available indices: {list(INDICES.keys())}")
            print(f"Available options: {list(OPTIONS_CONFIG.keys())}")
            return
    else:
        parser.print_help()
        return
    
    print_summary()


if __name__ == "__main__":
    main()
