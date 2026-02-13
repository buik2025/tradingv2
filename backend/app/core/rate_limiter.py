"""API Rate Limit Manager for Trading System v2.0

Tracks API call frequency, implements call budgeting, and provides
adaptive polling to stay within KiteConnect API limits.

KiteConnect Limits (as of 2026):
- Historical Data: 3 requests/second, 200 requests/minute
- Quote API: 1 request/second
- Order API: 10 requests/second
- WebSocket: 3000 instruments max
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, List, Callable
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import time
import threading
from loguru import logger


class APIEndpoint(str, Enum):
    """KiteConnect API endpoints with rate limits."""
    HISTORICAL = "historical"
    QUOTE = "quote"
    ORDER = "order"
    POSITIONS = "positions"
    HOLDINGS = "holdings"
    MARGINS = "margins"
    INSTRUMENTS = "instruments"
    OTHER = "other"


@dataclass
class RateLimitConfig:
    """Rate limit configuration for an endpoint."""
    requests_per_second: float
    requests_per_minute: int
    burst_limit: int = 5  # Max burst requests
    warning_threshold: float = 0.8  # Warn at 80% usage


# Default rate limits per endpoint
DEFAULT_LIMITS: Dict[APIEndpoint, RateLimitConfig] = {
    APIEndpoint.HISTORICAL: RateLimitConfig(
        requests_per_second=3.0,
        requests_per_minute=200,
        burst_limit=5
    ),
    APIEndpoint.QUOTE: RateLimitConfig(
        requests_per_second=1.0,
        requests_per_minute=60,
        burst_limit=2
    ),
    APIEndpoint.ORDER: RateLimitConfig(
        requests_per_second=10.0,
        requests_per_minute=600,
        burst_limit=10
    ),
    APIEndpoint.POSITIONS: RateLimitConfig(
        requests_per_second=1.0,
        requests_per_minute=60,
        burst_limit=2
    ),
    APIEndpoint.HOLDINGS: RateLimitConfig(
        requests_per_second=1.0,
        requests_per_minute=60,
        burst_limit=2
    ),
    APIEndpoint.MARGINS: RateLimitConfig(
        requests_per_second=1.0,
        requests_per_minute=60,
        burst_limit=2
    ),
    APIEndpoint.INSTRUMENTS: RateLimitConfig(
        requests_per_second=0.1,  # Very limited
        requests_per_minute=10,
        burst_limit=1
    ),
    APIEndpoint.OTHER: RateLimitConfig(
        requests_per_second=1.0,
        requests_per_minute=60,
        burst_limit=3
    ),
}


@dataclass
class RateLimitStats:
    """Statistics for rate limit tracking."""
    endpoint: APIEndpoint
    calls_last_second: int = 0
    calls_last_minute: int = 0
    calls_today: int = 0
    last_call_time: Optional[datetime] = None
    rate_limited_count: int = 0
    avg_response_time_ms: float = 0.0
    
    # Usage percentages
    second_usage_pct: float = 0.0
    minute_usage_pct: float = 0.0


class RateLimitExceeded(Exception):
    """Raised when rate limit would be exceeded."""
    def __init__(self, endpoint: APIEndpoint, wait_seconds: float):
        self.endpoint = endpoint
        self.wait_seconds = wait_seconds
        super().__init__(f"Rate limit exceeded for {endpoint.value}. Wait {wait_seconds:.2f}s")


class APIRateLimiter:
    """
    API Rate Limiter with sliding window tracking.
    
    Features:
    - Per-endpoint rate limiting
    - Sliding window for accurate tracking
    - Adaptive polling intervals
    - Usage warnings before hitting limits
    - Thread-safe
    """
    
    def __init__(
        self,
        limits: Optional[Dict[APIEndpoint, RateLimitConfig]] = None,
        daily_budget: int = 50000,  # Total daily API calls budget
        alert_callback: Optional[Callable[[str, float], None]] = None
    ):
        """
        Args:
            limits: Custom rate limits per endpoint
            daily_budget: Total daily API call budget
            alert_callback: Callback for rate limit warnings (message, usage_pct)
        """
        self.limits = limits or DEFAULT_LIMITS
        self.daily_budget = daily_budget
        self.alert_callback = alert_callback
        
        # Sliding windows for each endpoint (timestamps of calls)
        self._call_windows: Dict[APIEndpoint, deque] = {
            ep: deque(maxlen=1000) for ep in APIEndpoint
        }
        
        # Daily call counter
        self._daily_calls: Dict[APIEndpoint, int] = {ep: 0 for ep in APIEndpoint}
        self._daily_reset_date: datetime = datetime.now().date()
        
        # Response time tracking
        self._response_times: Dict[APIEndpoint, deque] = {
            ep: deque(maxlen=100) for ep in APIEndpoint
        }
        
        # Lock for thread safety
        self._lock = threading.Lock()
        
        logger.info(f"APIRateLimiter initialized: daily_budget={daily_budget}")
    
    def _reset_daily_if_needed(self) -> None:
        """Reset daily counters if new day."""
        today = datetime.now().date()
        if today > self._daily_reset_date:
            with self._lock:
                self._daily_calls = {ep: 0 for ep in APIEndpoint}
                self._daily_reset_date = today
                logger.info("Daily rate limit counters reset")
    
    def _get_calls_in_window(self, endpoint: APIEndpoint, window_seconds: float) -> int:
        """Count calls within a time window."""
        now = datetime.now()
        cutoff = now - timedelta(seconds=window_seconds)
        
        window = self._call_windows[endpoint]
        count = sum(1 for ts in window if ts > cutoff)
        return count
    
    def can_call(self, endpoint: APIEndpoint) -> tuple[bool, float]:
        """
        Check if an API call is allowed.
        
        Args:
            endpoint: The API endpoint to check
            
        Returns:
            Tuple of (allowed, wait_seconds)
        """
        self._reset_daily_if_needed()
        
        config = self.limits.get(endpoint, self.limits[APIEndpoint.OTHER])
        
        with self._lock:
            # Check per-second limit
            calls_last_second = self._get_calls_in_window(endpoint, 1.0)
            if calls_last_second >= config.requests_per_second:
                wait = 1.0 - (datetime.now() - self._call_windows[endpoint][-1]).total_seconds()
                return False, max(0.1, wait)
            
            # Check per-minute limit
            calls_last_minute = self._get_calls_in_window(endpoint, 60.0)
            if calls_last_minute >= config.requests_per_minute:
                oldest_in_minute = min(
                    (ts for ts in self._call_windows[endpoint] 
                     if ts > datetime.now() - timedelta(seconds=60)),
                    default=datetime.now()
                )
                wait = 60.0 - (datetime.now() - oldest_in_minute).total_seconds()
                return False, max(0.1, wait)
            
            # Check daily budget
            total_daily = sum(self._daily_calls.values())
            if total_daily >= self.daily_budget:
                return False, 3600.0  # Wait an hour
        
        return True, 0.0
    
    def record_call(
        self,
        endpoint: APIEndpoint,
        response_time_ms: Optional[float] = None
    ) -> None:
        """
        Record an API call.
        
        Args:
            endpoint: The API endpoint called
            response_time_ms: Response time in milliseconds
        """
        self._reset_daily_if_needed()
        
        now = datetime.now()
        
        with self._lock:
            self._call_windows[endpoint].append(now)
            self._daily_calls[endpoint] += 1
            
            if response_time_ms is not None:
                self._response_times[endpoint].append(response_time_ms)
        
        # Check for warnings
        self._check_usage_warnings(endpoint)
    
    def _check_usage_warnings(self, endpoint: APIEndpoint) -> None:
        """Check and emit usage warnings."""
        config = self.limits.get(endpoint, self.limits[APIEndpoint.OTHER])
        
        # Check minute usage
        calls_last_minute = self._get_calls_in_window(endpoint, 60.0)
        minute_usage = calls_last_minute / config.requests_per_minute
        
        if minute_usage >= config.warning_threshold:
            msg = f"API rate limit warning: {endpoint.value} at {minute_usage:.0%} of minute limit"
            logger.warning(msg)
            if self.alert_callback:
                self.alert_callback(msg, minute_usage)
        
        # Check daily usage
        total_daily = sum(self._daily_calls.values())
        daily_usage = total_daily / self.daily_budget
        
        if daily_usage >= 0.8:
            msg = f"Daily API budget warning: {daily_usage:.0%} used ({total_daily}/{self.daily_budget})"
            logger.warning(msg)
            if self.alert_callback:
                self.alert_callback(msg, daily_usage)
    
    def wait_if_needed(self, endpoint: APIEndpoint) -> float:
        """
        Wait if rate limit would be exceeded.
        
        Args:
            endpoint: The API endpoint to call
            
        Returns:
            Seconds waited (0 if no wait needed)
        """
        allowed, wait_seconds = self.can_call(endpoint)
        
        if not allowed:
            logger.debug(f"Rate limit: waiting {wait_seconds:.2f}s for {endpoint.value}")
            time.sleep(wait_seconds)
            return wait_seconds
        
        return 0.0
    
    def acquire(self, endpoint: APIEndpoint, blocking: bool = True) -> bool:
        """
        Acquire permission to make an API call.
        
        Args:
            endpoint: The API endpoint to call
            blocking: If True, wait until allowed. If False, return immediately.
            
        Returns:
            True if call is allowed, False if not (only when blocking=False)
            
        Raises:
            RateLimitExceeded: If blocking=False and limit exceeded
        """
        allowed, wait_seconds = self.can_call(endpoint)
        
        if allowed:
            return True
        
        if blocking:
            time.sleep(wait_seconds)
            return True
        else:
            raise RateLimitExceeded(endpoint, wait_seconds)
    
    def get_stats(self, endpoint: Optional[APIEndpoint] = None) -> Dict[str, RateLimitStats]:
        """
        Get rate limit statistics.
        
        Args:
            endpoint: Specific endpoint or None for all
            
        Returns:
            Dict of endpoint -> stats
        """
        self._reset_daily_if_needed()
        
        endpoints = [endpoint] if endpoint else list(APIEndpoint)
        stats = {}
        
        for ep in endpoints:
            config = self.limits.get(ep, self.limits[APIEndpoint.OTHER])
            
            calls_second = self._get_calls_in_window(ep, 1.0)
            calls_minute = self._get_calls_in_window(ep, 60.0)
            
            response_times = list(self._response_times[ep])
            avg_response = sum(response_times) / len(response_times) if response_times else 0.0
            
            window = self._call_windows[ep]
            last_call = window[-1] if window else None
            
            stats[ep.value] = RateLimitStats(
                endpoint=ep,
                calls_last_second=calls_second,
                calls_last_minute=calls_minute,
                calls_today=self._daily_calls[ep],
                last_call_time=last_call,
                rate_limited_count=0,  # TODO: track this
                avg_response_time_ms=avg_response,
                second_usage_pct=calls_second / config.requests_per_second if config.requests_per_second else 0,
                minute_usage_pct=calls_minute / config.requests_per_minute if config.requests_per_minute else 0
            )
        
        return stats
    
    def get_recommended_interval(self, endpoint: APIEndpoint) -> float:
        """
        Get recommended polling interval based on current usage.
        
        Args:
            endpoint: The API endpoint
            
        Returns:
            Recommended interval in seconds
        """
        config = self.limits.get(endpoint, self.limits[APIEndpoint.OTHER])
        
        # Base interval from rate limit
        base_interval = 1.0 / config.requests_per_second
        
        # Check current usage
        calls_minute = self._get_calls_in_window(endpoint, 60.0)
        minute_usage = calls_minute / config.requests_per_minute
        
        # Increase interval if approaching limits
        if minute_usage > 0.9:
            return base_interval * 3.0
        elif minute_usage > 0.7:
            return base_interval * 2.0
        elif minute_usage > 0.5:
            return base_interval * 1.5
        
        return base_interval
    
    def get_daily_usage_summary(self) -> Dict:
        """Get daily usage summary."""
        self._reset_daily_if_needed()
        
        total = sum(self._daily_calls.values())
        
        return {
            "date": self._daily_reset_date.isoformat(),
            "total_calls": total,
            "budget": self.daily_budget,
            "usage_pct": total / self.daily_budget if self.daily_budget else 0,
            "remaining": self.daily_budget - total,
            "by_endpoint": {ep.value: count for ep, count in self._daily_calls.items()}
        }


# Global rate limiter instance
_rate_limiter: Optional[APIRateLimiter] = None


def get_rate_limiter() -> APIRateLimiter:
    """Get or create global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = APIRateLimiter()
    return _rate_limiter


def rate_limited(endpoint: APIEndpoint):
    """
    Decorator to apply rate limiting to a function.
    
    Usage:
        @rate_limited(APIEndpoint.HISTORICAL)
        def fetch_historical_data(...):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            limiter = get_rate_limiter()
            limiter.acquire(endpoint, blocking=True)
            
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed_ms = (time.time() - start) * 1000
                limiter.record_call(endpoint, elapsed_ms)
        
        return wrapper
    return decorator
