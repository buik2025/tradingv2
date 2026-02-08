"""Instrument cache for lot sizes, multipliers, and other instrument data.

Fetches and caches instrument master data from Kite for accurate P&L calculations.
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from loguru import logger


class InstrumentCache:
    """Cache for instrument master data from Kite.
    
    Stores:
    - lot_size: Number of units per lot (for F&O)
    - tick_size: Minimum price movement
    - multiplier: Price multiplier (e.g., for currency futures)
    - instrument_type: EQ, FUT, CE, PE
    - exchange: NSE, NFO, MCX, etc.
    - expiry: Expiry date for derivatives
    - strike: Strike price for options
    - underlying: Underlying instrument token
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._cache: Dict[int, Dict[str, Any]] = {}  # instrument_token -> data
        self._symbol_to_token: Dict[str, int] = {}  # tradingsymbol -> token
        self._cache_file = Path(os.getenv("DATA_DIR", "data")) / "instruments_cache.json"
        self._last_refresh: Optional[datetime] = None
        self._refresh_interval = timedelta(hours=6)  # Refresh every 6 hours
        
        # Load from disk if available
        self._load_from_disk()
        logger.info(f"InstrumentCache initialized with {len(self._cache)} instruments")
    
    def _load_from_disk(self):
        """Load cached instruments from disk."""
        try:
            if self._cache_file.exists():
                with open(self._cache_file, 'r') as f:
                    data = json.load(f)
                    self._cache = {int(k): v for k, v in data.get("instruments", {}).items()}
                    self._symbol_to_token = data.get("symbol_to_token", {})
                    last_refresh = data.get("last_refresh")
                    if last_refresh:
                        self._last_refresh = datetime.fromisoformat(last_refresh)
                    logger.info(f"Loaded {len(self._cache)} instruments from cache")
        except Exception as e:
            logger.warning(f"Failed to load instrument cache: {e}")
    
    def _save_to_disk(self):
        """Save instruments to disk."""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_file, 'w') as f:
                json.dump({
                    "instruments": {str(k): v for k, v in self._cache.items()},
                    "symbol_to_token": self._symbol_to_token,
                    "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None
                }, f)
            logger.info(f"Saved {len(self._cache)} instruments to cache")
        except Exception as e:
            logger.warning(f"Failed to save instrument cache: {e}")
    
    def refresh_from_kite(self, kite_client) -> bool:
        """Refresh instrument data from Kite API.
        
        Args:
            kite_client: KiteConnect client instance
            
        Returns:
            True if refresh successful
        """
        try:
            # Check if refresh needed
            if self._last_refresh and datetime.now() - self._last_refresh < self._refresh_interval:
                if len(self._cache) > 0:
                    logger.debug("Instrument cache is fresh, skipping refresh")
                    return True
            
            logger.info("Refreshing instrument cache from Kite...")
            
            # Get the underlying KiteConnect instance
            # Support both KiteClient wrapper and raw KiteConnect
            kite = getattr(kite_client, '_kite', None) or getattr(kite_client, 'kite', None) or kite_client
            
            if not kite or not hasattr(kite, 'instruments'):
                logger.warning("Invalid kite client, cannot refresh instruments")
                return False
            
            # Fetch instruments for relevant exchanges
            exchanges = ["NSE", "NFO", "MCX", "CDS", "BFO", "BSE"]
            
            for exchange in exchanges:
                try:
                    instruments = kite.instruments(exchange)
                    for inst in instruments:
                        token = inst.get("instrument_token")
                        if token:
                            self._cache[token] = {
                                "tradingsymbol": inst.get("tradingsymbol"),
                                "name": inst.get("name"),
                                "exchange": inst.get("exchange"),
                                "segment": inst.get("segment"),
                                "instrument_type": inst.get("instrument_type"),
                                "lot_size": inst.get("lot_size", 1),
                                "tick_size": inst.get("tick_size", 0.05),
                                "expiry": inst.get("expiry").isoformat() if inst.get("expiry") else None,
                                "strike": float(inst.get("strike", 0)),
                                "underlying": inst.get("underlying_token"),
                            }
                            self._symbol_to_token[inst.get("tradingsymbol")] = token
                    
                    logger.info(f"Loaded {len(instruments)} instruments from {exchange}")
                except Exception as e:
                    logger.warning(f"Failed to fetch instruments for {exchange}: {e}")
            
            self._last_refresh = datetime.now()
            self._save_to_disk()
            
            logger.info(f"Instrument cache refreshed: {len(self._cache)} total instruments")
            return True
            
        except Exception as e:
            logger.error(f"Failed to refresh instrument cache: {e}")
            return False
    
    def get(self, instrument_token: int) -> Optional[Dict[str, Any]]:
        """Get instrument data by token."""
        return self._cache.get(instrument_token)
    
    def get_by_symbol(self, tradingsymbol: str, exchange: str = None) -> Optional[Dict[str, Any]]:
        """Get instrument data by trading symbol."""
        token = self._symbol_to_token.get(tradingsymbol)
        if token:
            return self._cache.get(token)
        return None
    
    def get_lot_size(self, instrument_token: int) -> int:
        """Get lot size for an instrument (1 for equity)."""
        inst = self._cache.get(instrument_token)
        if inst:
            return inst.get("lot_size", 1)
        return 1
    
    def get_instrument_type(self, instrument_token: int) -> str:
        """Get instrument type: EQ, FUT, CE, PE."""
        inst = self._cache.get(instrument_token)
        if inst:
            return inst.get("instrument_type", "EQ")
        return "EQ"
    
    def is_derivative(self, instrument_token: int) -> bool:
        """Check if instrument is a derivative (F&O)."""
        inst_type = self.get_instrument_type(instrument_token)
        return inst_type in ["FUT", "CE", "PE"]
    
    def get_multiplier(self, instrument_token: int) -> float:
        """Get price multiplier for P&L calculation.
        
        For most instruments this is lot_size.
        For some (like currency futures) there may be additional multipliers.
        """
        inst = self._cache.get(instrument_token)
        if not inst:
            return 1.0
        
        lot_size = inst.get("lot_size", 1)
        
        # MCX commodities have specific multipliers
        exchange = inst.get("exchange", "")
        if exchange == "MCX":
            # MCX lot sizes are already in the lot_size field
            return float(lot_size)
        
        # F&O lot sizes
        if inst.get("instrument_type") in ["FUT", "CE", "PE"]:
            return float(lot_size)
        
        # Equity - no multiplier
        return 1.0


# Global instance
instrument_cache = InstrumentCache()
