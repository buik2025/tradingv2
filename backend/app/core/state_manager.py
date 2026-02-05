"""State persistence manager for Trading System v2.0"""

import json
from pathlib import Path
from datetime import datetime, date
from typing import Any, Dict, Optional
from loguru import logger


class StateManager:
    """Manages persistent state for the trading system."""
    
    def __init__(self, state_dir: Path = Path("state")):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "system_state.json"
        self._state: Dict[str, Any] = self._load_state()
        
    def _load_state(self) -> Dict[str, Any]:
        """Load state from file or return default state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    state = json.load(f)
                logger.info(f"Loaded state from {self.state_file}")
                return state
            except Exception as e:
                logger.error(f"Failed to load state: {e}")
        
        return self._default_state()
    
    def _default_state(self) -> Dict[str, Any]:
        """Return default system state."""
        return {
            "last_updated": None,
            "high_watermark": 0.0,
            "daily_pnl": 0.0,
            "weekly_pnl": 0.0,
            "monthly_pnl": 0.0,
            "flat_days_remaining": 0,
            "last_regime": None,
            "open_position_ids": [],
            "circuit_breaker_active": False,
            "circuit_breaker_reason": None,
            "trading_day_start": None
        }
    
    def save(self) -> None:
        """Persist current state to file."""
        self._state["last_updated"] = datetime.now().isoformat()
        try:
            with open(self.state_file, "w") as f:
                json.dump(self._state, f, indent=2, default=str)
            logger.debug("State saved")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a state value."""
        return self._state.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a state value and persist."""
        self._state[key] = value
        self.save()
    
    def update(self, updates: Dict[str, Any]) -> None:
        """Update multiple state values at once."""
        self._state.update(updates)
        self.save()
    
    def reset_daily(self) -> None:
        """Reset daily counters (call at start of each trading day)."""
        today = date.today().isoformat()
        if self._state.get("trading_day_start") != today:
            self._state["daily_pnl"] = 0.0
            self._state["trading_day_start"] = today
            
            # Decrement flat days
            if self._state["flat_days_remaining"] > 0:
                self._state["flat_days_remaining"] -= 1
                if self._state["flat_days_remaining"] == 0:
                    self._state["circuit_breaker_active"] = False
                    self._state["circuit_breaker_reason"] = None
                    logger.info("Flat days completed, circuit breaker deactivated")
            
            self.save()
            logger.info(f"Daily state reset for {today}")
    
    def reset_weekly(self) -> None:
        """Reset weekly counters (call at start of each week)."""
        self._state["weekly_pnl"] = 0.0
        self.save()
        logger.info("Weekly state reset")
    
    def reset_monthly(self) -> None:
        """Reset monthly counters (call at start of each month)."""
        self._state["monthly_pnl"] = 0.0
        self.save()
        logger.info("Monthly state reset")
    
    def activate_circuit_breaker(self, reason: str, flat_days: int) -> None:
        """Activate circuit breaker with specified flat days."""
        self._state["circuit_breaker_active"] = True
        self._state["circuit_breaker_reason"] = reason
        self._state["flat_days_remaining"] = flat_days
        self.save()
        logger.warning(f"Circuit breaker activated: {reason}, flat days: {flat_days}")
    
    def is_circuit_breaker_active(self) -> bool:
        """Check if circuit breaker is active."""
        return self._state.get("circuit_breaker_active", False)
    
    def update_pnl(self, pnl: float) -> None:
        """Update PnL counters."""
        self._state["daily_pnl"] = self._state.get("daily_pnl", 0.0) + pnl
        self._state["weekly_pnl"] = self._state.get("weekly_pnl", 0.0) + pnl
        self._state["monthly_pnl"] = self._state.get("monthly_pnl", 0.0) + pnl
        self.save()
    
    def update_high_watermark(self, equity: float) -> None:
        """Update high watermark if current equity is higher."""
        current_hwm = self._state.get("high_watermark", 0.0)
        if equity > current_hwm:
            self._state["high_watermark"] = equity
            self.save()
            logger.info(f"New high watermark: {equity}")
