"""Tests for HMM Regime Classifier and DC Alarm Tracker - Sentinel v2.3"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from app.services.indicators.hmm_helper import HMMRegimeClassifier, DCAlarmTracker
from app.services.indicators.dc import DirectionalChange
from app.services.indicators.smei import SMEICalculator


class TestHMMRegimeClassifier:
    """Tests for HMMRegimeClassifier."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        hmm = HMMRegimeClassifier()
        assert hmm.window == 20
        assert hmm.n_states == 2
        assert hmm.min_samples == 5
        assert not hmm._is_fitted
    
    def test_init_custom_params(self):
        """Test custom initialization."""
        hmm = HMMRegimeClassifier(window=30, min_samples=10)
        assert hmm.window == 30
        assert hmm.min_samples == 10
    
    def test_predict_proba_no_data(self):
        """Test prediction with no data returns priors."""
        hmm = HMMRegimeClassifier()
        p_normal, p_abnormal = hmm.predict_proba(pd.DataFrame())
        assert p_normal == 0.7
        assert p_abnormal == 0.3
    
    def test_fit_insufficient_samples(self):
        """Test fit with insufficient samples does not fit."""
        hmm = HMMRegimeClassifier(min_samples=5)
        events = pd.DataFrame({
            'T': [0.5, 0.6],
            'TMV': [0.3, 0.4],
            'TAR': [0.1, 0.2]
        })
        hmm.fit(events)
        assert not hmm._is_fitted
    
    def test_fit_sufficient_samples(self):
        """Test fit with sufficient samples."""
        hmm = HMMRegimeClassifier(min_samples=5)
        events = pd.DataFrame({
            'T': [0.5, 0.6, 0.4, 0.7, 0.3, 0.5, 0.6],
            'TMV': [0.3, 0.4, 0.5, 0.3, 0.6, 0.4, 0.5],
            'TAR': [0.1, 0.2, 0.15, 0.25, 0.1, 0.2, 0.15]
        })
        hmm.fit(events)
        assert hmm._is_fitted
    
    def test_predict_proba_normal_events(self):
        """Test prediction on normal (stable) events returns valid probabilities."""
        hmm = HMMRegimeClassifier(min_samples=3)
        # Normal events: moderate T, moderate TMV, low TAR
        events = pd.DataFrame({
            'T': [0.6, 0.7, 0.65, 0.7, 0.6],
            'TMV': [0.4, 0.5, 0.45, 0.5, 0.4],
            'TAR': [0.1, 0.15, 0.12, 0.1, 0.13]
        })
        hmm.fit(events)
        p_normal, p_abnormal = hmm.predict_proba(events)
        # Probabilities should sum to 1 and be valid
        assert p_normal + p_abnormal == pytest.approx(1.0, abs=0.01)
        assert 0 <= p_normal <= 1
        assert 0 <= p_abnormal <= 1
    
    def test_predict_proba_abnormal_events(self):
        """Test prediction on abnormal (volatile) events returns valid probabilities."""
        hmm = HMMRegimeClassifier(min_samples=3)
        # Abnormal events: short T, extreme TMV, high TAR
        events = pd.DataFrame({
            'T': [0.1, 0.15, 0.2, 0.1, 0.15],
            'TMV': [0.9, 0.1, 0.85, 0.05, 0.9],
            'TAR': [0.8, 0.9, 0.85, 0.95, 0.88]
        })
        hmm.fit(events)
        p_normal, p_abnormal = hmm.predict_proba(events)
        # Probabilities should sum to 1 and be valid
        assert p_normal + p_abnormal == pytest.approx(1.0, abs=0.01)
        assert 0 <= p_normal <= 1
        assert 0 <= p_abnormal <= 1
    
    def test_online_update(self):
        """Test online update with new events."""
        hmm = HMMRegimeClassifier(min_samples=3)
        
        # Add events one by one
        for i in range(5):
            event = {'T': 0.5 + i*0.05, 'TMV': 0.4, 'TAR': 0.1 + i*0.02}
            p_normal, p_abnormal = hmm.online_update(event)
        
        # After 5 events, should have predictions
        assert p_normal + p_abnormal == pytest.approx(1.0)
    
    def test_get_state_description(self):
        """Test state description."""
        hmm = HMMRegimeClassifier()
        assert hmm.get_state_description(0.1) == "normal"
        assert hmm.get_state_description(0.5) == "elevated"
        assert hmm.get_state_description(0.8) == "abnormal"
    
    def test_reset(self):
        """Test reset clears state."""
        hmm = HMMRegimeClassifier(min_samples=3)
        events = pd.DataFrame({
            'T': [0.5, 0.6, 0.4, 0.7, 0.3],
            'TMV': [0.3, 0.4, 0.5, 0.3, 0.6],
            'TAR': [0.1, 0.2, 0.15, 0.25, 0.1]
        })
        hmm.fit(events)
        assert hmm._is_fitted
        
        hmm.reset()
        assert not hmm._is_fitted
        assert len(hmm._event_buffer) == 0


class TestDCAlarmTracker:
    """Tests for DCAlarmTracker."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        tracker = DCAlarmTracker()
        assert tracker.p_threshold == 0.7
        assert tracker.n_consecutive == 3
        assert not tracker.is_alarm_active()
    
    def test_init_custom_params(self):
        """Test custom initialization."""
        tracker = DCAlarmTracker(p_threshold=0.8, n_consecutive=5)
        assert tracker.p_threshold == 0.8
        assert tracker.n_consecutive == 5
    
    def test_no_alarm_below_threshold(self):
        """Test no alarm when p_abnormal below threshold."""
        tracker = DCAlarmTracker(p_threshold=0.7, n_consecutive=3)
        
        for _ in range(5):
            alarm = tracker.update(0.5)
        
        assert not alarm
        assert not tracker.is_alarm_active()
    
    def test_alarm_triggers_after_consecutive(self):
        """Test alarm triggers after N consecutive high p_abnormal."""
        tracker = DCAlarmTracker(p_threshold=0.7, n_consecutive=3)
        
        # First two don't trigger
        assert not tracker.update(0.8)
        assert not tracker.update(0.75)
        
        # Third triggers
        assert tracker.update(0.9)
        assert tracker.is_alarm_active()
    
    def test_alarm_resets_on_low_value(self):
        """Test consecutive count resets on low p_abnormal."""
        tracker = DCAlarmTracker(p_threshold=0.7, n_consecutive=3)
        
        tracker.update(0.8)
        tracker.update(0.75)
        assert tracker.get_consecutive_count() == 2
        
        # Low value resets count
        tracker.update(0.5)
        assert tracker.get_consecutive_count() == 0
        assert not tracker.is_alarm_active()
    
    def test_get_consecutive_count(self):
        """Test consecutive count tracking."""
        tracker = DCAlarmTracker(p_threshold=0.7, n_consecutive=3)
        
        tracker.update(0.8)
        assert tracker.get_consecutive_count() == 1
        
        tracker.update(0.75)
        assert tracker.get_consecutive_count() == 2
        
        tracker.update(0.9)
        assert tracker.get_consecutive_count() == 3
    
    def test_reset(self):
        """Test reset clears state."""
        tracker = DCAlarmTracker(p_threshold=0.7, n_consecutive=3)
        
        tracker.update(0.8)
        tracker.update(0.75)
        tracker.update(0.9)
        assert tracker.is_alarm_active()
        
        tracker.reset()
        assert not tracker.is_alarm_active()
        assert tracker.get_consecutive_count() == 0


class TestDirectionalChangeIntegration:
    """Integration tests for DC with HMM."""
    
    @pytest.fixture
    def sample_ohlcv(self):
        """Create sample OHLCV data with clear DC events."""
        np.random.seed(42)
        n_bars = 100
        
        # Create trending then reversing price series
        base_price = 22000
        prices = [base_price]
        
        for i in range(1, n_bars):
            if i < 30:
                # Uptrend
                change = np.random.uniform(0, 50)
            elif i < 50:
                # Downtrend (reversal)
                change = np.random.uniform(-60, 0)
            elif i < 70:
                # Uptrend again
                change = np.random.uniform(0, 40)
            else:
                # Sideways
                change = np.random.uniform(-20, 20)
            prices.append(prices[-1] + change)
        
        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2026-02-10 09:15', periods=n_bars, freq='5min'),
            'open': prices,
            'high': [p + np.random.uniform(10, 30) for p in prices],
            'low': [p - np.random.uniform(10, 30) for p in prices],
            'close': [p + np.random.uniform(-15, 15) for p in prices],
            'volume': [np.random.randint(10000, 50000) for _ in prices]
        })
        return df
    
    def test_dc_detects_events(self, sample_ohlcv):
        """Test DC detector finds events in sample data."""
        dc = DirectionalChange(theta=0.003, min_bar_window=5)
        events_df = dc.compute_dc_events(sample_ohlcv)
        
        # Should detect at least one event
        assert len(events_df) > 0
        
        # Events should have required columns
        assert 'T' in events_df.columns
        assert 'TMV' in events_df.columns
        assert 'TAR' in events_df.columns
        assert 'direction' in events_df.columns
    
    def test_dc_to_hmm_pipeline(self, sample_ohlcv):
        """Test full DC -> HMM pipeline."""
        dc = DirectionalChange(theta=0.003, min_bar_window=5)
        hmm = HMMRegimeClassifier(min_samples=3)
        
        # Detect DC events
        events_df = dc.compute_dc_events(sample_ohlcv)
        
        if len(events_df) >= 3:
            # Get normalized events
            normalized = dc.get_last_n_events(5)
            events_for_hmm = pd.DataFrame(normalized)
            
            # Fit and predict
            hmm.fit(events_for_hmm)
            p_normal, p_abnormal = hmm.predict_proba(events_for_hmm)
            
            assert p_normal + p_abnormal == pytest.approx(1.0)
            assert 0 <= p_normal <= 1
            assert 0 <= p_abnormal <= 1


class TestSMEIIntegration:
    """Integration tests for SMEI."""
    
    @pytest.fixture
    def bullish_ohlcv(self):
        """Create bullish OHLCV data (closes > opens)."""
        n_bars = 30
        df = pd.DataFrame({
            'open': [100 + i for i in range(n_bars)],
            'high': [105 + i for i in range(n_bars)],
            'low': [98 + i for i in range(n_bars)],
            'close': [104 + i for i in range(n_bars)],  # Close > Open
            'volume': [10000 + i*100 for i in range(n_bars)]
        })
        return df
    
    @pytest.fixture
    def bearish_ohlcv(self):
        """Create bearish OHLCV data (closes < opens)."""
        n_bars = 30
        df = pd.DataFrame({
            'open': [100 - i*0.5 for i in range(n_bars)],
            'high': [102 - i*0.5 for i in range(n_bars)],
            'low': [96 - i*0.5 for i in range(n_bars)],
            'close': [97 - i*0.5 for i in range(n_bars)],  # Close < Open
            'volume': [10000 + i*100 for i in range(n_bars)]
        })
        return df
    
    def test_smei_bullish(self, bullish_ohlcv):
        """Test SMEI returns positive for bullish data."""
        smei = SMEICalculator(window=20)
        score = smei.compute_smei(bullish_ohlcv)
        assert score > 0
    
    def test_smei_bearish(self, bearish_ohlcv):
        """Test SMEI returns negative for bearish data."""
        smei = SMEICalculator(window=20)
        score = smei.compute_smei(bearish_ohlcv)
        assert score < 0
    
    def test_smei_normalization(self, bullish_ohlcv):
        """Test SMEI is normalized to [-1, 1]."""
        smei = SMEICalculator(window=20)
        score = smei.compute_smei(bullish_ohlcv)
        assert -1 <= score <= 1
    
    def test_smei_sentiment_description(self):
        """Test sentiment description."""
        smei = SMEICalculator()
        assert smei.sentiment_description(0.7) == "bullish"
        assert smei.sentiment_description(0.0) == "neutral"
        assert smei.sentiment_description(-0.7) == "bearish"
