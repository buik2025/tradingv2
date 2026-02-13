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
            "trading_day_start": None,
            # Trade history for consecutive losers/winners (Section 6/7)
            "recent_trade_results": [],  # List of recent trade P&L results
            "consecutive_losers": 0,
            "consecutive_winners": 0,
            "losers_reduction_active": False,
            "win_streak_cap_active": False,
            # Slippage tracking (Section 8)
            "slippage_alerts": [],  # Recent slippage alerts
            "total_slippage_today": 0.0
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
    
    def record_trade_result(self, pnl: float, trade_id: str = None) -> Dict[str, Any]:
        """
        Record a trade result and update consecutive win/loss tracking.
        
        Section 6: 3 consecutive losers → 50% reduction + 1 flat day
        Section 7: Win streak → cap sizing at 80%
        
        Returns:
            Dict with current streak info and any triggered actions
        """
        from ..config.thresholds import (
            CONSECUTIVE_LOSERS_THRESHOLD, CONSECUTIVE_LOSERS_FLAT_DAYS,
            WIN_STREAK_THRESHOLD
        )
        
        result = {
            "trade_id": trade_id,
            "pnl": pnl,
            "timestamp": datetime.now().isoformat(),
            "is_winner": pnl > 0
        }
        
        # Add to recent results (keep last 10)
        recent = self._state.get("recent_trade_results", [])
        recent.append(result)
        if len(recent) > 10:
            recent = recent[-10:]
        self._state["recent_trade_results"] = recent
        
        # Update consecutive counters
        if pnl > 0:
            # Winner
            self._state["consecutive_winners"] = self._state.get("consecutive_winners", 0) + 1
            self._state["consecutive_losers"] = 0
            self._state["losers_reduction_active"] = False
        else:
            # Loser
            self._state["consecutive_losers"] = self._state.get("consecutive_losers", 0) + 1
            self._state["consecutive_winners"] = 0
            self._state["win_streak_cap_active"] = False
        
        actions = {}
        
        # Check for 3 consecutive losers
        if self._state["consecutive_losers"] >= CONSECUTIVE_LOSERS_THRESHOLD:
            self._state["losers_reduction_active"] = True
            self.activate_circuit_breaker(
                f"{CONSECUTIVE_LOSERS_THRESHOLD} consecutive losers",
                CONSECUTIVE_LOSERS_FLAT_DAYS
            )
            actions["consecutive_losers_triggered"] = True
            actions["flat_days"] = CONSECUTIVE_LOSERS_FLAT_DAYS
            logger.warning(f"CONSECUTIVE LOSERS: {self._state['consecutive_losers']} losers, activating 50% reduction")
        
        # Check for win streak cap
        if self._state["consecutive_winners"] >= WIN_STREAK_THRESHOLD:
            self._state["win_streak_cap_active"] = True
            actions["win_streak_cap_triggered"] = True
            logger.info(f"WIN STREAK: {self._state['consecutive_winners']} wins, capping size at 80%")
        
        self.save()
        
        return {
            "consecutive_losers": self._state["consecutive_losers"],
            "consecutive_winners": self._state["consecutive_winners"],
            "losers_reduction_active": self._state["losers_reduction_active"],
            "win_streak_cap_active": self._state["win_streak_cap_active"],
            "actions": actions
        }
    
    def get_sizing_multiplier(self) -> float:
        """
        Get position sizing multiplier based on consecutive win/loss state.
        
        Returns:
            Multiplier to apply to position size (0.5 for losers, 0.8 for win cap)
        """
        from ..config.thresholds import (
            CONSECUTIVE_LOSERS_REDUCTION, WIN_STREAK_SIZE_CAP
        )
        
        if self._state.get("losers_reduction_active", False):
            return CONSECUTIVE_LOSERS_REDUCTION
        
        if self._state.get("win_streak_cap_active", False):
            return WIN_STREAK_SIZE_CAP
        
        return 1.0
    
    def get_trade_stats(self) -> Dict[str, float]:
        """
        v2.5: Get trade statistics for Kelly sizing calculation.
        
        Returns:
            Dict with win_rate, avg_win_pct, avg_loss_pct
        """
        recent_trades = self._state.get("recent_trade_results", [])
        
        if not recent_trades or len(recent_trades) < 5:
            # Not enough data, return defaults
            return {
                "win_rate": 0.55,  # Default 55% win rate
                "avg_win_pct": 0.015,  # Default 1.5% avg win
                "avg_loss_pct": 0.01,  # Default 1% avg loss
                "trade_count": len(recent_trades)
            }
        
        wins = [t for t in recent_trades if t > 0]
        losses = [t for t in recent_trades if t < 0]
        
        win_rate = len(wins) / len(recent_trades) if recent_trades else 0.5
        avg_win_pct = sum(wins) / len(wins) if wins else 0.015
        avg_loss_pct = abs(sum(losses) / len(losses)) if losses else 0.01
        
        return {
            "win_rate": win_rate,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
            "trade_count": len(recent_trades)
        }
    
    def record_slippage(self, expected_price: float, actual_price: float, 
                        tradingsymbol: str, order_id: str = None) -> Dict[str, Any]:
        """
        Record slippage and generate alerts if threshold exceeded.
        
        Section 8: >0.5% slippage → alert/auto-correct
        
        Returns:
            Dict with slippage info and alert status
        """
        from ..config.thresholds import (
            SLIPPAGE_ALERT_THRESHOLD, SLIPPAGE_AUTO_CORRECT_THRESHOLD
        )
        
        if expected_price == 0:
            return {"slippage_pct": 0, "alert": False}
        
        slippage_pct = abs(actual_price - expected_price) / expected_price
        
        alert_data = {
            "timestamp": datetime.now().isoformat(),
            "tradingsymbol": tradingsymbol,
            "order_id": order_id,
            "expected_price": expected_price,
            "actual_price": actual_price,
            "slippage_pct": slippage_pct,
            "alert_level": None
        }
        
        # Update daily slippage total
        self._state["total_slippage_today"] = self._state.get("total_slippage_today", 0) + slippage_pct
        
        # Check thresholds
        if slippage_pct >= SLIPPAGE_AUTO_CORRECT_THRESHOLD:
            alert_data["alert_level"] = "CRITICAL"
            logger.error(
                f"SLIPPAGE CRITICAL: {tradingsymbol} slippage {slippage_pct:.2%} "
                f"(expected={expected_price:.2f}, actual={actual_price:.2f})"
            )
        elif slippage_pct >= SLIPPAGE_ALERT_THRESHOLD:
            alert_data["alert_level"] = "WARNING"
            logger.warning(
                f"SLIPPAGE WARNING: {tradingsymbol} slippage {slippage_pct:.2%} "
                f"(expected={expected_price:.2f}, actual={actual_price:.2f})"
            )
        
        # Store alert if threshold exceeded
        if alert_data["alert_level"]:
            alerts = self._state.get("slippage_alerts", [])
            alerts.append(alert_data)
            if len(alerts) > 50:  # Keep last 50 alerts
                alerts = alerts[-50:]
            self._state["slippage_alerts"] = alerts
            self.save()
        
        return {
            "slippage_pct": slippage_pct,
            "alert": alert_data["alert_level"] is not None,
            "alert_level": alert_data["alert_level"],
            "total_slippage_today": self._state["total_slippage_today"]
        }
    
    def reset_slippage_daily(self) -> None:
        """Reset daily slippage tracking."""
        self._state["total_slippage_today"] = 0.0
        self.save()
