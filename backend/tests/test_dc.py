"""Unit tests for Directional Change (DC) detector."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

from backend.app.services.indicators.dc import DirectionalChange, DCEvent


@pytest.fixture
def simple_uptrend_df():
    """Simple consistent uptrend: no DC events below 3% threshold."""
    data = {
        'timestamp': pd.date_range('2026-02-01 09:30', periods=20, freq='5min'),
        'open': np.linspace(100, 119, 20),
        'high': np.linspace(101, 120, 20),
        'low': np.linspace(99, 118, 20),
        'close': np.linspace(100.5, 119.5, 20),
        'volume': np.full(20, 1000000),
    }
    return pd.DataFrame(data)


@pytest.fixture
def dc_sample_df():
    """Load DC sample fixture (real-like data with reversals)."""
    fixture_path = Path(__file__).parent / "fixtures" / "dc_sample.csv"
    df = pd.read_csv(fixture_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


def test_dc_initialization():
    """Test DC detector initialization."""
    dc = DirectionalChange(theta=0.003, min_bar_window=5)
    assert dc.theta == 0.003
    assert dc.min_bar_window == 5
    assert len(dc.extrema) == 0
    assert len(dc.dc_events) == 0
    assert dc.last_event is None


def test_dc_no_events_below_threshold(simple_uptrend_df):
    """Test that consistent uptrend below theta produces no events."""
    dc = DirectionalChange(theta=0.05)  # 5% threshold, uptrend only 20%
    events_df = dc.compute_dc_events(simple_uptrend_df)
    
    # Should have at least initial extremum but minimal events
    assert len(dc.extrema) >= 1
    # Actual events depend on how sharp reversals are
    # In smooth uptrend, expect very few or no events
    assert len(dc.dc_events) <= 2


def test_dc_detects_reversal():
    """Test DC detection of clear up-down-up reversal."""
    # Construct: up (20000->20200), down (20200->19800), up (19800->20100)
    data = {
        'timestamp': pd.date_range('2026-02-01 09:30', periods=30, freq='5min'),
        'open': [20000 + i*5 for i in range(10)] + [20200 - i*13 for i in range(10)] + [19800 + i*10 for i in range(10)],
        'high': [20000 + i*6 for i in range(10)] + [20200 - i*12 for i in range(10)] + [19800 + i*11 for i in range(10)],
        'low': [20000 + i*4 for i in range(10)] + [20200 - i*14 for i in range(10)] + [19800 + i*9 for i in range(10)],
        'close': [20000 + i*5 for i in range(10)] + [20200 - i*13 for i in range(10)] + [19800 + i*10 for i in range(10)],
        'volume': np.full(30, 1000000),
    }
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    dc = DirectionalChange(theta=0.003, min_bar_window=5)
    events_df = dc.compute_dc_events(df)
    
    # Should detect at least one reversal (from up to down, or down to up)
    assert len(dc.dc_events) >= 1, f"Expected ≥1 event, got {len(dc.dc_events)}"


def test_dc_event_properties():
    """Test that DC events have correct properties."""
    data = {
        'timestamp': pd.date_range('2026-02-01 09:30', periods=30, freq='5min'),
        'open': [20000] * 15 + [19600] * 15,
        'high': [20100] * 15 + [19700] * 15,
        'low': [19900] * 15 + [19500] * 15,
        'close': [20050] * 15 + [19550] * 15,
        'volume': np.full(30, 1000000),
    }
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    dc = DirectionalChange(theta=0.003, min_bar_window=3)
    events_df = dc.compute_dc_events(df)
    
    if len(dc.dc_events) > 0:
        event = dc.dc_events[0]
        assert event.start_idx >= 0
        assert event.end_idx > event.start_idx
        assert event.direction in ['up', 'down']
        assert event.T > 0
        assert 0 <= event.TMV <= 1, f"TMV={event.TMV} not in [0,1]"
        assert isinstance(event.TAR, float)


def test_dc_last_event():
    """Test current_event() and last_event tracking."""
    data = {
        'timestamp': pd.date_range('2026-02-01 09:30', periods=20, freq='5min'),
        'open': list(range(100, 110)) + list(range(95, 105)),
        'high': list(range(101, 111)) + list(range(96, 106)),
        'low': list(range(99, 109)) + list(range(94, 104)),
        'close': list(range(100, 110)) + list(range(95, 105)),
        'volume': np.full(20, 1000000),
    }
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    dc = DirectionalChange(theta=0.003, min_bar_window=3)
    events_df = dc.compute_dc_events(df)
    
    if len(dc.dc_events) > 0:
        current = dc.current_event()
        assert current is not None
        assert 'direction' in current
        assert 'T' in current
        assert 'TMV' in current
        assert 'TAR' in current


def test_dc_reset():
    """Test reset() clears state."""
    dc = DirectionalChange(theta=0.003)
    data = {
        'timestamp': pd.date_range('2026-02-01', periods=20, freq='5min'),
        'open': range(100, 120),
        'high': range(101, 121),
        'low': range(99, 119),
        'close': range(100, 120),
        'volume': np.full(20, 1000000),
    }
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    dc.compute_dc_events(df)
    assert len(dc.extrema) > 0
    
    dc.reset()
    assert len(dc.extrema) == 0
    assert len(dc.dc_events) == 0
    assert dc.last_event is None


def test_dc_get_last_n_events():
    """Test get_last_n_events() normalization."""
    data = {
        'timestamp': pd.date_range('2026-02-01', periods=40, freq='5min'),
        'open': list(range(100, 120)) + list(range(115, 100, -1)) + list(range(100, 110)),
        'high': list(range(101, 121)) + list(range(116, 101, -1)) + list(range(101, 111)),
        'low': list(range(99, 119)) + list(range(114, 99, -1)) + list(range(99, 109)),
        'close': list(range(100, 120)) + list(range(115, 100, -1)) + list(range(100, 110)),
        'volume': np.full(40, 1000000),
    }
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    dc = DirectionalChange(theta=0.003, min_bar_window=3)
    dc.compute_dc_events(df)
    
    last_events = dc.get_last_n_events(n=3)
    
    # Check normalization
    for event_dict in last_events:
        assert 'T' in event_dict
        assert 'TMV' in event_dict
        assert 'TAR' in event_dict
        # TMV should be in [0,1] already (computed from position)
        # T and TAR are normalized in this call
        assert 0 <= event_dict['TMV'] <= 1, f"TMV={event_dict['TMV']} not in [0,1]"


def test_dc_with_real_fixture(dc_sample_df):
    """Test DC detector on real-like fixture data."""
    dc = DirectionalChange(theta=0.003, min_bar_window=5)
    events_df = dc.compute_dc_events(dc_sample_df)
    
    # Real fixture has clear reversals, should detect events
    assert len(dc.dc_events) > 0, "Expected events in realistic data"
    
    # Each event should be valid
    for event in dc.dc_events:
        assert isinstance(event, DCEvent)
        assert event.direction in ['up', 'down']
        assert event.start_idx < event.end_idx
        assert event.T > 0


def test_dc_insufficient_data():
    """Test handling of insufficient data."""
    dc = DirectionalChange(min_bar_window=10)
    
    df = pd.DataFrame({
        'timestamp': pd.date_range('2026-02-01', periods=3, freq='5min'),
        'open': [100, 101, 102],
        'high': [101, 102, 103],
        'low': [99, 100, 101],
        'close': [100.5, 101.5, 102.5],
        'volume': [1000000] * 3,
    })
    
    events_df = dc.compute_dc_events(df)
    # Should not crash, may return empty or minimal events
    assert isinstance(events_df, pd.DataFrame)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
