"""Regime detection models for Trading System v2.0"""

from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class RegimeType(str, Enum):
    """Market regime classification."""
    RANGE_BOUND = "RANGE_BOUND"
    MEAN_REVERSION = "MEAN_REVERSION"
    TREND = "TREND"
    CHAOS = "CHAOS"
    UNKNOWN = "UNKNOWN"


class RegimeMetrics(BaseModel):
    """Technical metrics used for regime detection."""
    adx: float = Field(..., description="Average Directional Index (14-period)")
    rsi: float = Field(..., description="Relative Strength Index (14-period)")
    iv_percentile: float = Field(..., description="IV percentile (0-100)")
    realized_vol: float = Field(..., description="Realized volatility")
    atr: float = Field(..., description="Average True Range")
    rv_atr_ratio: float = Field(..., description="RV/ATR ratio")
    skew: Optional[float] = Field(None, description="Put-Call skew")
    oi_change_pct: Optional[float] = Field(None, description="OI change percentage")


class RegimePacket(BaseModel):
    """
    Complete regime assessment packet produced by Sentinel agent.
    Contains all information needed by downstream agents.
    """
    timestamp: datetime = Field(default_factory=datetime.now)
    instrument_token: int = Field(..., description="Instrument token assessed")
    symbol: str = Field(..., description="Symbol name")
    
    # Regime classification
    regime: RegimeType = Field(..., description="Detected market regime")
    regime_confidence: float = Field(..., ge=0, le=1, description="Confidence in regime classification")
    ml_regime: Optional[RegimeType] = Field(None, description="ML-predicted regime")
    ml_probability: float = Field(0.0, ge=0, le=1, description="ML prediction probability")
    
    # Underlying metrics
    metrics: RegimeMetrics = Field(..., description="Technical metrics")
    
    # Event and correlation flags
    event_flag: bool = Field(False, description="True if event within blackout period")
    event_name: Optional[str] = Field(None, description="Name of upcoming event")
    event_days: Optional[int] = Field(None, description="Days until event")
    
    # Correlations with other assets
    correlations: Dict[str, float] = Field(default_factory=dict, description="Correlations with other assets")
    correlation_alert: bool = Field(False, description="True if correlation exceeds threshold")
    
    # Trading universe
    approved_universe: List[str] = Field(default_factory=list, description="Approved instruments for trading")
    disabled_instruments: List[str] = Field(default_factory=list, description="Disabled due to correlation")
    
    # Safety flags
    is_safe: bool = Field(True, description="Overall safety flag for trading")
    safety_reasons: List[str] = Field(default_factory=list, description="Reasons if not safe")
    
    # Price context
    spot_price: float = Field(..., description="Current spot price")
    prev_close: float = Field(..., description="Previous day close")
    day_range_pct: float = Field(..., description="Current day range as percentage")
    gap_pct: float = Field(0.0, description="Gap from previous close")
    
    def is_range_bound(self) -> bool:
        """Check if regime is range-bound (suitable for short-vol)."""
        return self.regime == RegimeType.RANGE_BOUND and self.is_safe
    
    def is_mean_reversion(self) -> bool:
        """Check if regime is mean-reversion (suitable for directional)."""
        return self.regime == RegimeType.MEAN_REVERSION and self.is_safe
    
    def allows_short_vol(self) -> bool:
        """Check if conditions allow short volatility trades."""
        return (
            self.is_range_bound() and
            not self.event_flag and
            self.metrics.iv_percentile >= 40 and
            self.metrics.iv_percentile < 75
        )
    
    def allows_directional(self) -> bool:
        """Check if conditions allow directional trades."""
        return (
            self.is_mean_reversion() and
            not self.event_flag and
            (self.metrics.rsi < 30 or self.metrics.rsi > 70)
        )
