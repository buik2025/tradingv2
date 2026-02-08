"""Unit tests for Trade and Position models"""

import pytest
from datetime import date, datetime, timedelta
from app.models.trade import TradeProposal, TradeLeg, LegType, StructureType
from app.models.position import Position, PositionStatus


class TestTradeProposalModel:
    """Tests for TradeProposal model (Phase 1)"""
    
    def test_trade_proposal_creation(self, sample_trade_proposal):
        """Test creating a trade proposal with all fields."""
        assert sample_trade_proposal.structure == StructureType.IRON_CONDOR
        assert sample_trade_proposal.instrument == "NIFTY"
        assert sample_trade_proposal.is_credit is True
        assert sample_trade_proposal.max_profit == 5000
        assert sample_trade_proposal.max_loss == -5000  # Max loss should be negative
    
    def test_exit_target_fields(self, sample_trade_proposal):
        """Test dynamic exit target fields (Phase 1)."""
        # Verify exit target fields exist and are set
        assert hasattr(sample_trade_proposal, 'exit_target_low')
        assert hasattr(sample_trade_proposal, 'exit_target_high')
        assert sample_trade_proposal.exit_target_low == 140
        assert sample_trade_proposal.exit_target_high == 180
        assert sample_trade_proposal.exit_margin_type == "margin"
    
    def test_trailing_fields(self, sample_trade_proposal):
        """Test trailing profit fields (Phase 1)."""
        assert sample_trade_proposal.enable_trailing is True
        assert sample_trade_proposal.trailing_profit_threshold == 0.5
        assert sample_trade_proposal.trailing_mode == "bbw"
    
    def test_get_dynamic_target_margin_type(self, sample_trade_proposal):
        """Test get_dynamic_target() with margin type."""
        sample_trade_proposal.exit_margin_type = "margin"
        sample_trade_proposal.exit_target_low = 0.014
        sample_trade_proposal.exit_target_high = 0.018
        
        low, high = sample_trade_proposal.get_dynamic_target(entry_margin=10000)
        assert low == 10000 * 0.014  # 140
        assert high == 10000 * 0.018  # 180
    
    def test_get_dynamic_target_percentage_type(self, sample_trade_proposal):
        """Test get_dynamic_target() with percentage type."""
        sample_trade_proposal.exit_margin_type = "percentage"
        sample_trade_proposal.exit_target_low = 0.5
        sample_trade_proposal.exit_target_high = 0.7
        
        low, high = sample_trade_proposal.get_dynamic_target(entry_margin=10000)
        assert low == 5000 * 0.5  # 50% of max profit
        assert high == 5000 * 0.7  # 70% of max profit
    
    def test_calculate_greeks(self, sample_trade_proposal):
        """Test Greeks aggregation."""
        greeks = sample_trade_proposal.calculate_greeks()
        
        # Should aggregate across all legs
        assert 'delta' in greeks
        assert 'gamma' in greeks
        assert 'theta' in greeks
        assert 'vega' in greeks
        
        # Verify greeks is populated
        assert sample_trade_proposal.greeks == greeks
    
    def test_legs_structure(self, sample_trade_proposal):
        """Test that legs are properly structured."""
        assert len(sample_trade_proposal.legs) == 2
        assert sample_trade_proposal.legs[0].leg_type == LegType.SHORT_CALL
        assert sample_trade_proposal.legs[1].leg_type == LegType.LONG_CALL
    
    def test_risk_reward_ratio(self, sample_trade_proposal):
        """Test risk/reward calculation."""
        assert sample_trade_proposal.risk_reward_ratio > 0
        assert sample_trade_proposal.max_profit > 0
        assert sample_trade_proposal.max_loss < 0


class TestTradeLegModel:
    """Tests for TradeLeg model"""
    
    def test_leg_creation(self):
        """Test creating a trade leg."""
        leg = TradeLeg(
            leg_type=LegType.SHORT_CALL,
            tradingsymbol="NIFTY26FEB19100CE",
            instrument_token=2,
            strike=19100,
            expiry=date.today() + timedelta(days=10),
            option_type="CE",
            quantity=50,
            entry_price=400
        )
        
        assert leg.is_short is True
        assert leg.is_long is False
        assert leg.strike == 19100
        assert leg.quantity == 50
    
    def test_leg_pnl_long(self):
        """Test P&L calculation for long leg."""
        leg = TradeLeg(
            leg_type=LegType.LONG_CALL,
            tradingsymbol="NIFTY26FEB19100CE",
            instrument_token=2,
            strike=19100,
            expiry=date.today() + timedelta(days=10),
            option_type="CE",
            quantity=50,
            entry_price=100,
            current_price=150
        )
        
        # Long: profit when price goes up
        assert leg.pnl == (150 - 100) * 50  # 2500
    
    def test_leg_pnl_short(self):
        """Test P&L calculation for short leg."""
        leg = TradeLeg(
            leg_type=LegType.SHORT_PUT,
            tradingsymbol="NIFTY26FEB18900PE",
            instrument_token=4,
            strike=18900,
            expiry=date.today() + timedelta(days=10),
            option_type="PE",
            quantity=50,
            entry_price=150,
            current_price=100
        )
        
        # Short: profit when price goes down
        assert leg.pnl == -(100 - 150) * 50  # 2500


class TestPositionModel:
    """Tests for Position model (Phase 1)"""
    
    def test_position_creation(self, sample_position):
        """Test creating a position."""
        assert sample_position.strategy_type == StructureType.IRON_CONDOR
        assert sample_position.status == PositionStatus.OPEN
        assert sample_position.current_pnl == 0.0
    
    def test_exit_target_fields(self, sample_position):
        """Test dynamic exit target fields (Phase 1)."""
        assert sample_position.exit_target_low == 140
        assert sample_position.exit_target_high == 180
        assert sample_position.current_target == 2500
    
    def test_trailing_fields(self, sample_position):
        """Test trailing profit fields (Phase 1)."""
        assert sample_position.trailing_enabled is True
        assert sample_position.trailing_mode == "bbw"
        assert sample_position.trailing_active is False
        assert sample_position.trailing_threshold == 0.5
        assert sample_position.trailing_stop is None
    
    def test_should_exit_profit_not_reached(self, sample_position):
        """Test profit exit when target not reached."""
        sample_position.current_pnl = 1000
        sample_position.current_target = 2500
        assert sample_position.should_exit_profit() is False
    
    def test_should_exit_profit_reached(self, sample_position):
        """Test profit exit when target reached."""
        sample_position.current_pnl = 2500
        sample_position.current_target = 2500
        assert sample_position.should_exit_profit() is True
    
    def test_should_exit_profit_exceeded(self, sample_position):
        """Test profit exit when target exceeded."""
        sample_position.current_pnl = 3000
        sample_position.current_target = 2500
        assert sample_position.should_exit_profit() is True
    
    def test_should_exit_stop_not_hit(self, sample_position):
        """Test stop loss when not hit."""
        sample_position.current_pnl = -500
        sample_position.stop_loss = -1750
        assert sample_position.should_exit_stop() is False
    
    def test_should_exit_stop_hit(self, sample_position):
        """Test stop loss when hit."""
        sample_position.current_pnl = -1750
        sample_position.stop_loss = -1750
        assert sample_position.should_exit_stop() is True
    
    def test_update_pnl(self, sample_position):
        """Test P&L update calculation."""
        # Short call at 400, long call at 300 = 100 credit
        # If short call moves to 350 and long call to 280:
        current_prices = {2: 350, 3: 280}  # Token to price mapping
        
        sample_position.update_pnl(current_prices)
        assert sample_position.current_pnl > 0
    
    def test_trailing_activation_atr_mode(self, sample_position):
        """Test trailing stop activation in ATR mode."""
        sample_position.trailing_mode = "atr"
        sample_position.current_target = 1000
        sample_position.current_pnl = 500  # 50% of target
        
        # Simulate activation
        result = sample_position.update_trailing_stop(
            current_price=19100,
            atr=150
        )
        
        assert sample_position.trailing_active is True
        assert result is False  # Should not exit yet
    
    def test_trailing_atr_stop_update(self, sample_position):
        """Test ATR-based trailing stop update."""
        sample_position.trailing_mode = "atr"
        sample_position.trailing_active = True
        sample_position.trailing_threshold = 0.5
        sample_position.current_target = 1000
        sample_position.current_pnl = 600
        
        # First update
        sample_position.update_trailing_stop(current_price=19100, atr=150)
        stop1 = sample_position.trailing_stop
        
        # Price moves up, new stop should be higher
        sample_position.update_trailing_stop(current_price=19200, atr=150)
        stop2 = sample_position.trailing_stop
        
        assert stop2 >= stop1
    
    def test_trailing_bbw_profit_locking(self, sample_position):
        """Test BBW-based profit locking."""
        sample_position.trailing_mode = "bbw"
        sample_position.trailing_active = True
        sample_position.current_target = 1000
        sample_position.current_pnl = 800  # 80% of target
        
        # BBW expansion triggers profit lock
        sample_position.update_trailing_stop(
            current_price=19100,
            bbw_ratio=1.9  # > 1.8 threshold
        )
        
        # Should lock 60% of target
        expected_lock = 1000 * 0.6
        assert sample_position.trailing_stop == expected_lock
    
    def test_trailing_exit_trigger(self, sample_position):
        """Test trailing stop exit trigger."""
        sample_position.trailing_mode = "atr"
        sample_position.trailing_active = True
        sample_position.current_pnl = 400
        sample_position.trailing_stop = 500  # Stop set higher than P&L
        
        result = sample_position.update_trailing_stop(
            current_price=19100,
            atr=150
        )
        
        assert result is True  # Should exit
    
    def test_trailing_disabled(self, sample_position):
        """Test that trailing is skipped when disabled."""
        sample_position.trailing_enabled = False
        sample_position.current_pnl = 1000  # Enough to activate
        
        result = sample_position.update_trailing_stop(
            current_price=19100,
            atr=150
        )
        
        assert result is False
        assert sample_position.trailing_active is False
    
    def test_update_greeks(self, sample_position):
        """Test Greeks aggregation in position."""
        greeks = sample_position.update_greeks()
        
        assert 'delta' in greeks
        assert 'gamma' in greeks
        assert 'theta' in greeks
        assert 'vega' in greeks


class TestPositionExitLogic:
    """Tests for exit logic interactions"""
    
    def test_dynamic_target_vs_fixed_target(self, sample_position):
        """Test that current_target overrides target_pnl."""
        sample_position.target_pnl = 2000  # Old fixed target
        sample_position.current_target = 2500  # New dynamic target
        sample_position.current_pnl = 2400
        
        # Should use current_target for exit check
        assert sample_position.should_exit_profit() is False
        
        sample_position.current_pnl = 2500
        assert sample_position.should_exit_profit() is True
    
    def test_trailing_priority_over_profit_target(self, sample_position):
        """Test that trailing exit checked before normal exit."""
        # This is tested at executor level, but verify position supports it
        sample_position.trailing_enabled = True
        sample_position.trailing_mode = "atr"
        sample_position.trailing_active = True
        sample_position.trailing_stop = 100  # Set stop lower than current
        sample_position.current_pnl = 150  # Between stop and target
        sample_position.current_target = 2500
        
        # Trailing should trigger
        trailing_result = sample_position.update_trailing_stop(
            current_price=19100,
            atr=150
        )
        
        # But normal exit should not
        profit_result = sample_position.should_exit_profit()
        
        assert trailing_result is True
        assert profit_result is False


# Run tests with: pytest backend/tests/test_models.py -v
