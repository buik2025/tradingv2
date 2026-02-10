"""Unit tests for SMEI Sentiment Scorer."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path

from backend.app.services.indicators.smei import SMEICalculator


@pytest.fixture
def smei_bullish_df():
    """Load bullish sentiment fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "smei_bullish.csv"
    df = pd.read_csv(fixture_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


@pytest.fixture
def smei_bearish_df():
    """Create synthetic bearish data (closes < opens)."""
    data = {
        'timestamp': pd.date_range('2026-02-01', periods=20, freq='1D'),
        'open': np.linspace(120, 101, 20),
        'high': np.linspace(121, 102, 20),
        'low': np.linspace(119, 100, 20),
        'close': np.linspace(110, 101, 20),
        'volume': np.full(20, 1000000),
    }
    return pd.DataFrame(data)


@pytest.fixture
def smei_neutral_df():
    """Create synthetic neutral data (close ≈ open, balanced)."""
    data = {
        'timestamp': pd.date_range('2026-02-01', periods=20, freq='1D'),
        'open': [100] * 10 + [101] * 10,
        'high': [101] * 10 + [102] * 10,
        'low': [99] * 10 + [100] * 10,
        'close': [100] * 10 + [101] * 10,
        'volume': np.full(20, 1000000),
    }
    return pd.DataFrame(data)


def test_smei_initialization():
    """Test SMEI calculator initialization."""
    calc = SMEICalculator(window=20)
    assert calc.window == 20


def test_smei_bullish_trend(smei_bullish_df):
    """Test SMEI on bullish data (closes > opens)."""
    calc = SMEICalculator(window=20)
    smei = calc.compute_smei(smei_bullish_df)
    
    assert isinstance(smei, float)
    assert -1.0 <= smei <= 1.0, f"SMEI={smei} outside [-1,1]"
    # Bullish data should yield positive SMEI
    assert smei > 0.0, f"Expected bullish SMEI >0, got {smei}"


def test_smei_bearish_trend(smei_bearish_df):
    """Test SMEI on bearish data (closes < opens)."""
    calc = SMEICalculator(window=20)
    smei = calc.compute_smei(smei_bearish_df)
    
    assert isinstance(smei, float)
    assert -1.0 <= smei <= 1.0, f"SMEI={smei} outside [-1,1]"
    # Bearish data should yield negative SMEI
    assert smei < 0.0, f"Expected bearish SMEI <0, got {smei}"


def test_smei_neutral_trend(smei_neutral_df):
    """Test SMEI on neutral/balanced data."""
    calc = SMEICalculator(window=20)
    smei = calc.compute_smei(smei_neutral_df)
    
    assert isinstance(smei, float)
    assert -1.0 <= smei <= 1.0
    # Neutral data should yield SMEI close to 0
    assert -0.3 <= smei <= 0.3, f"Expected neutral SMEI near 0, got {smei}"


def test_smei_normalization():
    """Test that SMEI output is always normalized to [-1, 1]."""
    # Create extreme volatility data
    data = {
        'timestamp': pd.date_range('2026-02-01', periods=30, freq='1D'),
        'open': np.random.uniform(100, 110, 30),
        'high': np.random.uniform(115, 130, 30),
        'low': np.random.uniform(90, 100, 30),
        'close': np.random.uniform(105, 115, 30),
        'volume': np.random.uniform(1000000, 10000000, 30),
    }
    df = pd.DataFrame(data)
    
    calc = SMEICalculator(window=20)
    smei = calc.compute_smei(df)
    
    # Must be in bounds
    assert -1.0 <= smei <= 1.0, f"SMEI={smei} outside normalized range"


def test_smei_insufficient_data():
    """Test handling of insufficient data."""
    calc = SMEICalculator(window=20)
    
    df = pd.DataFrame({
        'timestamp': pd.date_range('2026-02-01', periods=5, freq='1D'),
        'open': [100, 101, 102, 103, 104],
        'high': [101, 102, 103, 104, 105],
        'low': [99, 100, 101, 102, 103],
        'close': [100.5, 101.5, 102.5, 103.5, 104.5],
        'volume': [1000000] * 5,
    })
    
    smei = calc.compute_smei(df)
    # Should return 0.0 or valid fallback, not crash
    assert isinstance(smei, float)
    assert -1.0 <= smei <= 1.0


def test_smei_obv_component(smei_bullish_df):
    """Test OBV component extraction."""
    calc = SMEICalculator(window=20)
    obv = calc.obv(smei_bullish_df)
    
    assert isinstance(obv, float)
    assert -1.0 <= obv <= 1.0
    # Bullish data should have positive OBV
    assert obv >= 0.0, f"Bullish OBV should be ≥0, got {obv}"


def test_smei_cmf_component(smei_bullish_df):
    """Test CMF component extraction."""
    calc = SMEICalculator(window=20)
    cmf = calc.cmf(smei_bullish_df)
    
    assert isinstance(cmf, float)
    assert -1.0 <= cmf <= 1.0


def test_smei_sentiment_description():
    """Test sentiment text description."""
    calc = SMEICalculator(window=20)
    
    assert calc.sentiment_description(0.7) == "bullish"
    assert calc.sentiment_description(-0.7) == "bearish"
    assert calc.sentiment_description(0.0) == "neutral"
    assert calc.sentiment_description(0.3) == "neutral"
    assert calc.sentiment_description(-0.3) == "neutral"


def test_smei_consistency():
    """Test that SMEI is consistent across multiple calls."""
    data = {
        'timestamp': pd.date_range('2026-02-01', periods=25, freq='1D'),
        'open': np.linspace(100, 110, 25),
        'high': np.linspace(101, 111, 25),
        'low': np.linspace(99, 109, 25),
        'close': np.linspace(100.5, 110.5, 25),
        'volume': np.full(25, 1000000),
    }
    df = pd.DataFrame(data)
    
    calc = SMEICalculator(window=20)
    smei1 = calc.compute_smei(df)
    smei2 = calc.compute_smei(df)
    
    # Same input should yield same output
    assert abs(smei1 - smei2) < 1e-6, f"SMEI not consistent: {smei1} vs {smei2}"


def test_smei_zero_volume():
    """Test handling of zero or near-zero volume."""
    data = {
        'timestamp': pd.date_range('2026-02-01', periods=20, freq='1D'),
        'open': np.linspace(100, 110, 20),
        'high': np.linspace(101, 111, 20),
        'low': np.linspace(99, 109, 20),
        'close': np.linspace(100.5, 110.5, 20),
        'volume': np.full(20, 0),  # Zero volume
    }
    df = pd.DataFrame(data)
    
    calc = SMEICalculator(window=20)
    smei = calc.compute_smei(df)
    
    # Should handle gracefully, return 0 or fallback
    assert isinstance(smei, float)
    assert -1.0 <= smei <= 1.0


def test_smei_zero_range():
    """Test handling of zero high-low range (edge case)."""
    data = {
        'timestamp': pd.date_range('2026-02-01', periods=20, freq='1D'),
        'open': [100] * 20,
        'high': [100] * 20,  # high == low
        'low': [100] * 20,
        'close': [100] * 20,
        'volume': np.full(20, 1000000),
    }
    df = pd.DataFrame(data)
    
    calc = SMEICalculator(window=20)
    smei = calc.compute_smei(df)
    
    # Should handle gracefully
    assert isinstance(smei, float)
    assert -1.0 <= smei <= 1.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
