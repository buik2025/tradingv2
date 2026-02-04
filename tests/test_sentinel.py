"""Tests for Sentinel agent"""

import pytest
from datetime import datetime, date
import pandas as pd
import numpy as np

from agents.sentinel import Sentinel
from core.kite_client import KiteClient
from config.settings import Settings
from models.regime import RegimeType


@pytest.fixture
def mock_kite():
    """Create mock KiteClient."""
    return KiteClient(api_key="test", access_token="test", mock_mode=True)


@pytest.fixture
def mock_config():
    """Create mock Settings."""
    class MockSettings:
        kite_api_key = "test"
        kite_access_token = "test"
        nifty_token = 256265
        adx_range_bound = 12
        adx_trend = 22
        iv_low = 35
        iv_high = 75
        correlation_threshold = 0.4
        data_dir = "data"
        logs_dir = "logs"
        state_dir = "state"
        models_dir = "data/models"
    return MockSettings()


@pytest.fixture
def sentinel(mock_kite, mock_config):
    """Create Sentinel instance."""
    return Sentinel(mock_kite, mock_config)


class TestSentinel:
    """Test cases for Sentinel agent."""
    
    def test_sentinel_initialization(self, sentinel):
        """Test Sentinel initializes correctly."""
        assert sentinel.name == "Sentinel"
        assert sentinel.kite is not None
    
    def test_process_returns_regime_packet(self, sentinel):
        """Test process returns a RegimePacket."""
        packet = sentinel.process(256265)
        
        assert packet is not None
        assert packet.regime in RegimeType
        assert 0 <= packet.regime_confidence <= 1
        assert packet.metrics is not None
    
    def test_regime_classification_range_bound(self, sentinel):
        """Test range-bound regime classification."""
        from models.regime import RegimeMetrics
        
        metrics = RegimeMetrics(
            adx=8,  # Low ADX
            rsi=50,  # Neutral RSI
            iv_percentile=30,  # Low IV
            realized_vol=0.12,
            atr=100,
            rv_atr_ratio=1.0
        )
        
        regime, confidence = sentinel._classify_regime(
            metrics, event_flag=False, correlations={}
        )
        
        assert regime == RegimeType.RANGE_BOUND
    
    def test_regime_classification_chaos(self, sentinel):
        """Test chaos regime classification."""
        from models.regime import RegimeMetrics
        
        metrics = RegimeMetrics(
            adx=15,
            rsi=50,
            iv_percentile=80,  # High IV triggers chaos
            realized_vol=0.30,
            atr=200,
            rv_atr_ratio=1.5
        )
        
        regime, confidence = sentinel._classify_regime(
            metrics, event_flag=False, correlations={}
        )
        
        assert regime == RegimeType.CHAOS
    
    def test_event_flag_triggers_chaos(self, sentinel):
        """Test that event flag triggers chaos regime."""
        from models.regime import RegimeMetrics
        
        metrics = RegimeMetrics(
            adx=10,
            rsi=50,
            iv_percentile=30,
            realized_vol=0.12,
            atr=100,
            rv_atr_ratio=1.0
        )
        
        regime, confidence = sentinel._classify_regime(
            metrics, event_flag=True, correlations={}
        )
        
        assert regime == RegimeType.CHAOS
    
    def test_add_event(self, sentinel):
        """Test adding events to calendar."""
        sentinel.add_event("RBI Policy", date(2026, 3, 15), "RBI")
        
        assert len(sentinel._events) == 1
        assert sentinel._events[0]["name"] == "RBI Policy"
    
    def test_safety_check(self, sentinel):
        """Test safety check logic."""
        from models.regime import RegimeMetrics
        
        metrics = RegimeMetrics(
            adx=10, rsi=50, iv_percentile=30,
            realized_vol=0.12, atr=100, rv_atr_ratio=1.0
        )
        
        # Safe conditions
        is_safe, reasons = sentinel._safety_check(
            RegimeType.RANGE_BOUND, metrics, False, {}
        )
        assert is_safe
        assert len(reasons) == 0
        
        # Unsafe - chaos regime
        is_safe, reasons = sentinel._safety_check(
            RegimeType.CHAOS, metrics, False, {}
        )
        assert not is_safe
        assert "CHAOS regime detected" in reasons


class TestRegimeMetrics:
    """Test RegimeMetrics model."""
    
    def test_metrics_creation(self):
        """Test creating RegimeMetrics."""
        from models.regime import RegimeMetrics
        
        metrics = RegimeMetrics(
            adx=15.5,
            rsi=45.2,
            iv_percentile=42.0,
            realized_vol=0.18,
            atr=150.5,
            rv_atr_ratio=1.2
        )
        
        assert metrics.adx == 15.5
        assert metrics.rsi == 45.2
        assert metrics.iv_percentile == 42.0


class TestRegimePacket:
    """Test RegimePacket model."""
    
    def test_packet_creation(self):
        """Test creating RegimePacket."""
        from models.regime import RegimePacket, RegimeMetrics
        
        metrics = RegimeMetrics(
            adx=10, rsi=50, iv_percentile=45,
            realized_vol=0.15, atr=100, rv_atr_ratio=1.0
        )
        
        packet = RegimePacket(
            instrument_token=256265,
            symbol="NIFTY",
            regime=RegimeType.RANGE_BOUND,
            regime_confidence=0.85,
            metrics=metrics,
            correlations={},
            approved_universe=["NIFTY"],
            is_safe=True,
            spot_price=22000,
            prev_close=21950,
            day_range_pct=0.008
        )
        
        assert packet.regime == RegimeType.RANGE_BOUND
        assert packet.is_range_bound()
        assert packet.allows_short_vol()
    
    def test_allows_short_vol(self):
        """Test allows_short_vol logic."""
        from models.regime import RegimePacket, RegimeMetrics
        
        metrics = RegimeMetrics(
            adx=10, rsi=50, iv_percentile=45,
            realized_vol=0.15, atr=100, rv_atr_ratio=1.0
        )
        
        # Should allow short vol
        packet = RegimePacket(
            instrument_token=256265,
            symbol="NIFTY",
            regime=RegimeType.RANGE_BOUND,
            regime_confidence=0.85,
            metrics=metrics,
            correlations={},
            approved_universe=["NIFTY"],
            is_safe=True,
            event_flag=False,
            spot_price=22000,
            prev_close=21950,
            day_range_pct=0.008
        )
        
        assert packet.allows_short_vol()
        
        # Should not allow - event flag
        packet.event_flag = True
        assert not packet.allows_short_vol()
