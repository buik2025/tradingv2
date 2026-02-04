"""Data caching layer for Trading System v2.0"""

import pickle
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any
import pandas as pd
from loguru import logger


class DataCache:
    """
    Caches historical data to reduce API calls and improve performance.
    Supports both CSV and pickle formats.
    """
    
    def __init__(self, cache_dir: Path = Path("data/cache")):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: Dict[str, pd.DataFrame] = {}
        self._cache_metadata: Dict[str, Dict[str, Any]] = {}
    
    def _get_cache_key(
        self,
        instrument_token: int,
        interval: str,
        from_date: date,
        to_date: date
    ) -> str:
        """Generate a unique cache key."""
        return f"{instrument_token}_{interval}_{from_date}_{to_date}"
    
    def _get_file_path(self, instrument_token: int, interval: str) -> Path:
        """Get the file path for cached data."""
        return self.cache_dir / f"{instrument_token}_{interval}.parquet"
    
    def get(
        self,
        instrument_token: int,
        interval: str,
        from_date: date,
        to_date: date
    ) -> Optional[pd.DataFrame]:
        """
        Get cached data if available and complete.
        
        Args:
            instrument_token: Instrument token
            interval: Data interval
            from_date: Start date
            to_date: End date
            
        Returns:
            DataFrame if cache hit, None otherwise
        """
        cache_key = self._get_cache_key(instrument_token, interval, from_date, to_date)
        
        # Check memory cache first
        if cache_key in self._memory_cache:
            logger.debug(f"Memory cache hit: {cache_key}")
            return self._memory_cache[cache_key]
        
        # Check file cache
        file_path = self._get_file_path(instrument_token, interval)
        if file_path.exists():
            try:
                df = pd.read_parquet(file_path)
                
                # Filter to requested date range
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                    df = df[(df['date'].dt.date >= from_date) & (df['date'].dt.date <= to_date)]
                elif df.index.name == 'date' or isinstance(df.index, pd.DatetimeIndex):
                    df = df[(df.index.date >= from_date) & (df.index.date <= to_date)]
                
                if not df.empty:
                    self._memory_cache[cache_key] = df
                    logger.debug(f"File cache hit: {file_path}")
                    return df
                    
            except Exception as e:
                logger.warning(f"Failed to read cache file {file_path}: {e}")
        
        return None
    
    def put(
        self,
        instrument_token: int,
        interval: str,
        data: pd.DataFrame,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> None:
        """
        Store data in cache.
        
        Args:
            instrument_token: Instrument token
            interval: Data interval
            data: DataFrame to cache
            from_date: Start date (for cache key)
            to_date: End date (for cache key)
        """
        if data.empty:
            return
        
        # Determine date range from data if not provided
        if from_date is None or to_date is None:
            if 'date' in data.columns:
                dates = pd.to_datetime(data['date'])
            else:
                dates = data.index
            from_date = from_date or dates.min().date()
            to_date = to_date or dates.max().date()
        
        cache_key = self._get_cache_key(instrument_token, interval, from_date, to_date)
        
        # Store in memory cache
        self._memory_cache[cache_key] = data
        
        # Append to file cache
        file_path = self._get_file_path(instrument_token, interval)
        try:
            if file_path.exists():
                existing = pd.read_parquet(file_path)
                # Merge and deduplicate
                combined = pd.concat([existing, data])
                if 'date' in combined.columns:
                    combined = combined.drop_duplicates(subset=['date'])
                else:
                    combined = combined[~combined.index.duplicated(keep='last')]
                combined.to_parquet(file_path)
            else:
                data.to_parquet(file_path)
            
            logger.debug(f"Cached data to {file_path}")
            
        except Exception as e:
            logger.warning(f"Failed to write cache file {file_path}: {e}")
    
    def invalidate(
        self,
        instrument_token: Optional[int] = None,
        interval: Optional[str] = None
    ) -> None:
        """
        Invalidate cache entries.
        
        Args:
            instrument_token: Specific token to invalidate (None = all)
            interval: Specific interval to invalidate (None = all)
        """
        # Clear memory cache
        if instrument_token is None and interval is None:
            self._memory_cache.clear()
            logger.info("Cleared all memory cache")
        else:
            keys_to_remove = []
            for key in self._memory_cache:
                if instrument_token and str(instrument_token) not in key:
                    continue
                if interval and interval not in key:
                    continue
                keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self._memory_cache[key]
            logger.info(f"Cleared {len(keys_to_remove)} memory cache entries")
        
        # Clear file cache
        if instrument_token is None and interval is None:
            for file in self.cache_dir.glob("*.parquet"):
                file.unlink()
            logger.info("Cleared all file cache")
        else:
            pattern = f"{instrument_token or '*'}_{interval or '*'}.parquet"
            for file in self.cache_dir.glob(pattern):
                file.unlink()
                logger.debug(f"Removed cache file: {file}")
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache statistics."""
        file_count = len(list(self.cache_dir.glob("*.parquet")))
        total_size = sum(f.stat().st_size for f in self.cache_dir.glob("*.parquet"))
        
        return {
            "memory_entries": len(self._memory_cache),
            "file_entries": file_count,
            "total_size_mb": total_size / (1024 * 1024),
            "cache_dir": str(self.cache_dir)
        }


class IndicatorCache:
    """Caches computed indicators to avoid recalculation."""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._cache: Dict[str, Any] = {}
        self._access_order: list = []
    
    def _make_key(self, name: str, params: Dict) -> str:
        """Create a cache key from indicator name and parameters."""
        param_str = "_".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{name}_{param_str}"
    
    def get(self, name: str, params: Dict) -> Optional[Any]:
        """Get cached indicator value."""
        key = self._make_key(name, params)
        if key in self._cache:
            # Move to end of access order (LRU)
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None
    
    def put(self, name: str, params: Dict, value: Any) -> None:
        """Store indicator value in cache."""
        key = self._make_key(name, params)
        
        # Evict oldest if at capacity
        if len(self._cache) >= self.max_size and key not in self._cache:
            oldest = self._access_order.pop(0)
            del self._cache[oldest]
        
        self._cache[key] = value
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
    
    def clear(self) -> None:
        """Clear all cached indicators."""
        self._cache.clear()
        self._access_order.clear()
