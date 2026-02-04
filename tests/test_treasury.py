"""Tests for Treasury agent"""

import pytest
from datetime import datetime

from agents.treasury import Treasury
from core.kite_client import KiteClient
from models.trade import TradeProposal, TradeLeg, LegType, StructureType
from models.position import AccountState


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
        max_margin_pct = 0.40
        max_loss_per_trade = 0.01
        max_daily_loss = 0.03
        max_weekly_loss = 0.05
        max_positions = 3
        max_delta = 30
        max_gamma = 0.3
        max_vega = 400
        state_dir = "state"
    return MockSettings()


@pytest.fixture
def treasury(mock_kite, mock_config):
    """Create Treasury instance."""
    return Treasury(mock_kite, mock_config)


@pytest.fixture
def sample_account():
    """Create sample account state."""
    return AccountState(
        equity=1000000,
        available_margin=800000,
        used_margin=200000,
        margin_utilization=0.20,
        high_watermark=1000000,
        position_count=1,
        portfolio_greeks={"delta": 10, "gamma": 0.1, "theta": -50, "vega": 100}
    )


@pytest.fixture
def sample_proposal():
    """Create sample trade proposal."""
    from datetime import date
    
    legs = [
        TradeLeg(
            leg_type=LegType.SHORT_CALL,
            tradingsymbol="NIFTY26FEB22500CE",
            instrument_token=12345,
            strike=22500,
            expiry=date(2026, 2, 27),
            option_type="CE",
            quantity=50,
            entry_price=100,
            delta=0.25
        ),
        TradeLeg(
            leg_type=LegType.SHORT_PUT,
            tradingsymbol="NIFTY26FEB21500PE",
            instrument_token=12346,
            strike=21500,
            expiry=date(2026, 2, 27),
            option_type="PE",
            quantity=50,
            entry_price=100,
            delta=-0.25
        ),
    ]
    
    return TradeProposal(
        structure=StructureType.IRON_CONDOR,
        instrument="NIFTY",
        instrument_token=256265,
        legs=legs,
        entry_price=200,
        is_credit=True,
        max_profit=10000,
        max_loss=5000,
        target_pnl=6000,
        stop_loss=-5000,
        risk_reward_ratio=2.0,
        required_margin=50000,
        position_size_pct=0.02,
        greeks={"delta": 0, "gamma": 0.05, "theta": -100, "vega": 50},
        expiry=date(2026, 2, 27),
        days_to_expiry=10,
        regime_at_entry="RANGE_BOUND",
        entry_reason="Test entry"
    )


class TestTreasury:
    """Test cases for Treasury agent."""
    
    def test_treasury_initialization(self, treasury):
        """Test Treasury initializes correctly."""
        assert treasury.name == "Treasury"
    
    def test_approve_valid_proposal(self, treasury, sample_proposal, sample_account):
        """Test approving a valid proposal."""
        approved, signal, reason = treasury.process(sample_proposal, sample_account)
        
        assert approved
        assert signal is not None
        assert signal.structure == StructureType.IRON_CONDOR
    
    def test_reject_max_positions(self, treasury, sample_proposal, sample_account):
        """Test rejecting when max positions reached."""
        sample_account.position_count = 3  # At max
        
        approved, signal, reason = treasury.process(sample_proposal, sample_account)
        
        assert not approved
        assert "Max positions" in reason
    
    def test_reject_margin_exceeded(self, treasury, sample_proposal, sample_account):
        """Test rejecting when margin would be exceeded."""
        sample_account.used_margin = 350000  # 35% used
        sample_proposal.required_margin = 100000  # Would push to 45%
        
        approved, signal, reason = treasury.process(sample_proposal, sample_account)
        
        assert not approved
        assert "margin" in reason.lower()
    
    def test_reject_trade_risk_exceeded(self, treasury, sample_proposal, sample_account):
        """Test rejecting when per-trade risk exceeded."""
        sample_proposal.max_loss = 15000  # 1.5% of equity
        
        approved, signal, reason = treasury.process(sample_proposal, sample_account)
        
        assert not approved
        assert "loss" in reason.lower()
    
    def test_drawdown_multiplier(self, treasury, sample_account):
        """Test drawdown multiplier calculation."""
        # No drawdown
        sample_account.drawdown_pct = 0.02
        mult = treasury._get_drawdown_multiplier(sample_account)
        assert mult == 1.0
        
        # 5% drawdown
        sample_account.drawdown_pct = 0.06
        mult = treasury._get_drawdown_multiplier(sample_account)
        assert mult == 0.50
        
        # 10% drawdown
        sample_account.drawdown_pct = 0.11
        mult = treasury._get_drawdown_multiplier(sample_account)
        assert mult == 0.25
        
        # 15% drawdown - stop trading
        sample_account.drawdown_pct = 0.16
        mult = treasury._get_drawdown_multiplier(sample_account)
        assert mult == 0.0
    
    def test_circuit_breaker_blocks_trading(self, treasury, sample_proposal, sample_account):
        """Test that circuit breaker blocks new trades."""
        sample_account.circuit_breaker_active = True
        sample_account.circuit_breaker_reason = "Daily loss limit"
        
        approved, signal, reason = treasury.process(sample_proposal, sample_account)
        
        assert not approved
        assert "Circuit breaker" in reason
    
    def test_check_loss_limits(self, treasury, sample_account):
        """Test loss limit checking."""
        # No breach
        sample_account.daily_pnl = -20000  # 2%
        breached, reason, flat_days = treasury.check_loss_limits(sample_account)
        assert not breached
        
        # Daily limit breached
        sample_account.daily_pnl = -35000  # 3.5%
        breached, reason, flat_days = treasury.check_loss_limits(sample_account)
        assert breached
        assert flat_days == 1
        
        # Weekly limit breached
        sample_account.daily_pnl = -20000
        sample_account.weekly_pnl = -55000  # 5.5%
        breached, reason, flat_days = treasury.check_loss_limits(sample_account)
        assert breached
        assert flat_days == 3


class TestAccountState:
    """Test AccountState model."""
    
    def test_can_open_position(self):
        """Test can_open_position logic."""
        account = AccountState(
            equity=1000000,
            available_margin=800000,
            used_margin=200000,
            high_watermark=1000000,
            position_count=1
        )
        
        # Should allow
        can_open, reason = account.can_open_position(50000)
        assert can_open
        
        # Max positions
        account.position_count = 3
        can_open, reason = account.can_open_position(50000)
        assert not can_open
        
        # Margin exceeded
        account.position_count = 1
        can_open, reason = account.can_open_position(300000)  # Would be 50%
        assert not can_open
    
    def test_drawdown_calculation(self):
        """Test drawdown calculation."""
        account = AccountState(
            equity=900000,
            available_margin=700000,
            used_margin=200000,
            high_watermark=1000000
        )
        
        account.update_drawdown()
        
        assert account.drawdown == 100000
        assert account.drawdown_pct == 0.10
