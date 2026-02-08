"""Fixtures for test suite"""

import pytest
from datetime import datetime, date, timedelta
import pandas as pd
import numpy as np
from pathlib import Path

from app.models.regime import RegimeType, RegimePacket, RegimeMetrics, ConfluenceScore
from app.models.trade import TradeProposal, TradeLeg, LegType, StructureType
from app.models.position import Position, PositionStatus
from app.config.constants import NFO


@pytest.fixture
def sample_option_chain():
    """Create sample option chain data for testing."""
    return pd.DataFrame({
        'strike': [19000, 19100, 19200, 19300, 19400],
        'instrument_type': ['CE', 'CE', 'CE', 'CE', 'CE'],
        'ltp': [500, 400, 300, 200, 100],
        'bid': [498, 398, 298, 198, 98],
        'ask': [502, 402, 302, 202, 102],
        'oi': [100000, 80000, 60000, 40000, 20000],
        'volume': [10000, 8000, 6000, 4000, 2000],
        'tradingsymbol': ['NIFTY26FEB19000CE', 'NIFTY26FEB19100CE', 'NIFTY26FEB19200CE', 'NIFTY26FEB19300CE', 'NIFTY26FEB19400CE'],
        'instrument_token': [1, 2, 3, 4, 5],
        'iv': [0.20, 0.21, 0.22, 0.23, 0.24],
        'greek_delta': [0.65, 0.55, 0.45, 0.35, 0.25],
        'greek_gamma': [0.005, 0.006, 0.007, 0.008, 0.009],
        'greek_theta': [-0.01, -0.012, -0.014, -0.016, -0.018],
        'greek_vega': [5.0, 6.0, 7.0, 8.0, 9.0],
    })


@pytest.fixture
def sample_regime_packet():
    """Create sample regime packet for testing."""
    metrics = RegimeMetrics(
        adx=18.0,
        rsi=45.0,
        iv_percentile=35.0,
        realized_vol=0.18,
        atr=150.0,
        rv_atr_ratio=0.8,
        skew=5.0,
        oi_change_pct=0.5,
        bbw=200.0,
        bbw_ratio=0.75,
        rv_iv_ratio=0.90,
        volume_ratio=1.2
    )
    
    return RegimePacket(
        timestamp=datetime.now(),
        instrument_token=256265985,
        symbol="NIFTY",
        regime=RegimeType.RANGE_BOUND,
        regime_confidence=0.85,
        ml_regime=None,
        ml_probability=0.0,
        metrics=metrics,
        event_flag=False,
        event_name=None,
        event_days=None,
        correlations={"BANKNIFTY": 0.45, "FINNIFTY": 0.38},
        correlation_alert=False,
        approved_universe=["NIFTY", "BANKNIFTY"],
        disabled_instruments=[],
        is_safe=True,
        safety_reasons=[],
        spot_price=19000.0,
        prev_close=19050.0,
        day_range_pct=0.5,
        gap_pct=0.26
    )


@pytest.fixture
def sample_trade_proposal():
    """Create sample trade proposal for testing."""
    legs = [
        TradeLeg(
            leg_type=LegType.SHORT_CALL,
            tradingsymbol="NIFTY26FEB19100CE",
            instrument_token=2,
            exchange=NFO,
            strike=19100,
            expiry=date.today() + timedelta(days=10),
            option_type="CE",
            quantity=50,
            entry_price=400,
            delta=-0.55,
            gamma=-0.006,
            theta=0.012,
            vega=-6.0
        ),
        TradeLeg(
            leg_type=LegType.LONG_CALL,
            tradingsymbol="NIFTY26FEB19200CE",
            instrument_token=3,
            exchange=NFO,
            strike=19200,
            expiry=date.today() + timedelta(days=10),
            option_type="CE",
            quantity=50,
            entry_price=300,
            delta=0.45,
            gamma=0.007,
            theta=-0.014,
            vega=7.0
        ),
    ]
    
    return TradeProposal(
        structure=StructureType.IRON_CONDOR,
        instrument="NIFTY",
        instrument_token=256265985,
        legs=legs,
        entry_price=100,
        is_credit=True,
        max_profit=5000,
        max_loss=-5000,
        target_pnl=2500,
        stop_loss=-1750,
        risk_reward_ratio=1.43,
        required_margin=10000,
        position_size_pct=0.02,
        expiry=date.today() + timedelta(days=10),
        days_to_expiry=10,
        regime_at_entry="RANGE_BOUND",
        entry_reason="Theta decay in low volatility",
        # Phase 1 additions
        exit_target_low=140,
        exit_target_high=180,
        exit_margin_type="margin",
        enable_trailing=True,
        trailing_profit_threshold=0.5,
        trailing_mode="bbw"
    )


@pytest.fixture
def sample_position(sample_trade_proposal):
    """Create sample position for testing."""
    return Position(
        signal_id="test-signal-123",
        strategy_type=StructureType.IRON_CONDOR,
        instrument="NIFTY",
        instrument_token=256265985,
        legs=sample_trade_proposal.legs,
        entry_price=100,
        entry_margin=10000,
        target_pnl=2500,
        stop_loss=-1750,
        max_loss=5000,
        expiry=date.today() + timedelta(days=10),
        days_to_expiry=10,
        exit_dte=5,
        regime_at_entry="RANGE_BOUND",
        entry_reason="Theta decay trade",
        # Phase 1 additions
        exit_target_low=140,
        exit_target_high=180,
        current_target=2500,
        trailing_enabled=True,
        trailing_mode="bbw",
        trailing_threshold=0.5
    )


@pytest.fixture
def sample_ohlcv_data():
    """Create sample OHLCV data for backtesting."""
    dates = pd.date_range(start='2023-01-01', periods=252, freq='D')
    np.random.seed(42)
    
    close = 19000 + np.random.randn(252).cumsum() * 50
    high = close + np.random.rand(252) * 100
    low = close - np.random.rand(252) * 100
    open_prices = close + np.random.randn(252) * 30
    volume = np.random.randint(1000000, 10000000, 252)
    
    return pd.DataFrame({
        'datetime': dates,
        'open': open_prices,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    }).set_index('datetime')


@pytest.fixture
def sample_iv_data():
    """Create sample IV percentile data."""
    dates = pd.date_range(start='2023-01-01', periods=252, freq='D')
    iv_pct = np.random.rand(252) * 100
    
    return pd.DataFrame({
        'datetime': dates,
        'iv_percentile': iv_pct
    }).set_index('datetime')
