"""Historical data loader for Trading System v2.0 backtesting"""

from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Dict, List
import pandas as pd
from loguru import logger

from ..core.kite_client import KiteClient


class DataLoader:
    """
    Loads historical data for backtesting from various sources.
    Supports KiteConnect API, CSV files, and cached data.
    """
    
    def __init__(
        self,
        kite: Optional[KiteClient] = None,
        cache_dir: Path = Path("data/cache")
    ):
        self.kite = kite
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def load_ohlcv(
        self,
        instrument_token: int,
        from_date: date,
        to_date: date,
        interval: str = "day",
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Load OHLCV data for an instrument.
        
        Args:
            instrument_token: Instrument token
            from_date: Start date
            to_date: End date
            interval: Data interval (minute, 5minute, 15minute, day)
            use_cache: Whether to use/update cache
            
        Returns:
            DataFrame with OHLCV data
        """
        cache_file = self._get_cache_path(instrument_token, interval)
        
        # Try cache first
        if use_cache and cache_file.exists():
            cached = self._load_from_cache(cache_file, from_date, to_date)
            if cached is not None and not cached.empty:
                logger.debug(f"Loaded {len(cached)} rows from cache")
                return cached
        
        # Fetch from API
        if self.kite:
            df = self._fetch_from_kite(instrument_token, from_date, to_date, interval)
            
            if use_cache and not df.empty:
                self._save_to_cache(df, cache_file)
            
            return df
        
        logger.warning("No data source available")
        return pd.DataFrame()
    
    def load_from_csv(
        self,
        file_path: Path,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> pd.DataFrame:
        """
        Load data from CSV file.
        
        Expected columns: date, open, high, low, close, volume
        """
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(file_path, parse_dates=['date'])
            
            if 'date' in df.columns:
                df.set_index('date', inplace=True)
            
            # Filter by date range
            if from_date:
                df = df[df.index.date >= from_date]
            if to_date:
                df = df[df.index.date <= to_date]
            
            logger.info(f"Loaded {len(df)} rows from {file_path}")
            return df
            
        except Exception as e:
            logger.error(f"Failed to load CSV: {e}")
            return pd.DataFrame()
    
    def load_option_chain_historical(
        self,
        underlying: str,
        trade_date: date,
        expiry: date
    ) -> pd.DataFrame:
        """
        Load historical option chain data.
        
        Note: Historical option chain data is typically not available
        from standard APIs. This would need a specialized data provider.
        """
        # Check for cached option chain data
        cache_file = self.cache_dir / f"options/{underlying}_{trade_date}_{expiry}.parquet"
        
        if cache_file.exists():
            return pd.read_parquet(cache_file)
        
        logger.warning(f"Historical option chain not available for {underlying} on {trade_date}")
        return pd.DataFrame()
    
    def load_vix_data(
        self,
        from_date: date,
        to_date: date
    ) -> pd.DataFrame:
        """Load India VIX historical data."""
        from ..config.constants import INDIA_VIX_TOKEN
        return self.load_ohlcv(INDIA_VIX_TOKEN, from_date, to_date, "day")
    
    def load_multiple_instruments(
        self,
        tokens: Dict[str, int],
        from_date: date,
        to_date: date,
        interval: str = "day"
    ) -> Dict[str, pd.DataFrame]:
        """
        Load data for multiple instruments.
        
        Args:
            tokens: Dict of name -> token
            from_date: Start date
            to_date: End date
            interval: Data interval
            
        Returns:
            Dict of name -> DataFrame
        """
        data = {}
        for name, token in tokens.items():
            df = self.load_ohlcv(token, from_date, to_date, interval)
            if not df.empty:
                data[name] = df
            else:
                logger.warning(f"No data for {name} (token={token})")
        
        return data
    
    def _fetch_from_kite(
        self,
        token: int,
        from_date: date,
        to_date: date,
        interval: str
    ) -> pd.DataFrame:
        """Fetch data from KiteConnect API."""
        try:
            # KiteConnect has limits on date range per request
            # For minute data: max 60 days
            # For day data: max 2000 days
            
            max_days = 60 if "minute" in interval else 2000
            
            all_data = []
            current_from = datetime.combine(from_date, datetime.min.time())
            final_to = datetime.combine(to_date, datetime.max.time())
            
            while current_from < final_to:
                current_to = min(
                    current_from + timedelta(days=max_days),
                    final_to
                )
                
                df = self.kite.fetch_historical_data(
                    token, interval, current_from, current_to
                )
                
                if not df.empty:
                    all_data.append(df)
                
                current_from = current_to + timedelta(days=1)
            
            if all_data:
                combined = pd.concat(all_data)
                combined = combined[~combined.index.duplicated(keep='last')]
                return combined.sort_index()
            
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Failed to fetch from Kite: {e}")
            return pd.DataFrame()
    
    def _get_cache_path(self, token: int, interval: str) -> Path:
        """Get cache file path for instrument."""
        return self.cache_dir / f"{token}_{interval}.parquet"
    
    def _load_from_cache(
        self,
        cache_file: Path,
        from_date: date,
        to_date: date
    ) -> Optional[pd.DataFrame]:
        """Load data from cache file."""
        try:
            df = pd.read_parquet(cache_file)
            
            # Filter to requested range
            if isinstance(df.index, pd.DatetimeIndex):
                df = df[(df.index.date >= from_date) & (df.index.date <= to_date)]
            
            return df
            
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            return None
    
    def _save_to_cache(self, df: pd.DataFrame, cache_file: Path) -> None:
        """Save data to cache file."""
        try:
            # Merge with existing cache if present
            if cache_file.exists():
                existing = pd.read_parquet(cache_file)
                df = pd.concat([existing, df])
                df = df[~df.index.duplicated(keep='last')]
                df = df.sort_index()
            
            df.to_parquet(cache_file)
            logger.debug(f"Saved {len(df)} rows to cache")
            
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
    
    def clear_cache(self, token: Optional[int] = None) -> None:
        """Clear cached data."""
        if token:
            for f in self.cache_dir.glob(f"{token}_*.parquet"):
                f.unlink()
                logger.info(f"Removed cache: {f}")
        else:
            for f in self.cache_dir.glob("*.parquet"):
                f.unlink()
            logger.info("Cleared all cache")
    
    def get_cache_info(self) -> Dict:
        """Get information about cached data."""
        files = list(self.cache_dir.glob("*.parquet"))
        total_size = sum(f.stat().st_size for f in files)
        
        return {
            "num_files": len(files),
            "total_size_mb": total_size / (1024 * 1024),
            "files": [f.name for f in files]
        }
