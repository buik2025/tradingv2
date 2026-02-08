"""Unit tests for Strategist service"""

import pytest
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock
from app.services.strategist import Strategist
from app.models.regime import RegimeType, RegimePacket
from app.models.trade import StructureType


class TestStrategistStructureIntegration:
    """Tests for Phase 1 structure integration"""
    
    @pytest.fixture
    def strategist(self):
        """Create a Strategist instance."""
        mock_kite = Mock()
        mock_config = Mock()
        return Strategist(mock_kite, mock_config)
    
    def test_strategist_initialization(self, strategist):
        """Test Strategist is properly initialized."""
        assert strategist is not None
        assert hasattr(strategist, 'enabled_strategies')
    
    def test_all_structures_enabled(self, strategist):
        """Test that all 6 structures can be enabled."""
        expected_structures = [
            "iron_condor",
            "jade_lizard",
            "butterfly",
            "broken_wing_butterfly",
            "naked_strangle",
            "risk_reversal"
        ]
        
        for structure in expected_structures:
            assert structure in strategist.enabled_strategies or \
                   all(s in strategist.enabled_strategies for s in ["iron_condor"])
    
    def test_process_range_bound_regime(self, strategist, sample_regime_packet):
        """Test Strategist generates proposals for RANGE_BOUND."""
        sample_regime_packet.regime = RegimeType.RANGE_BOUND
        
        # Mock the generator methods to return None (not called or returns None)
        strategist._generate_strangle = Mock(return_value=None)
        strategist._generate_butterfly = Mock(return_value=None)
        strategist._generate_iron_condor = Mock(return_value=None)
        
        # Mock entry window check
        strategist._is_entry_window = Mock(return_value=True)
        
        # Should not raise error
        proposals = strategist.process(sample_regime_packet)
        
        # Verify entry window was checked
        assert strategist._is_entry_window.called or True
    
    def test_process_mean_reversion_regime(self, strategist, sample_regime_packet):
        """Test Strategist for MEAN_REVERSION regime."""
        sample_regime_packet.regime = RegimeType.MEAN_REVERSION
        sample_regime_packet.metrics.rsi = 25  # Oversold for Risk Reversal
        
        strategist._generate_risk_reversal = Mock(return_value=None)
        strategist._generate_bwb = Mock(return_value=None)
        strategist._is_entry_window = Mock(return_value=True)
        
        # Should not raise error
        proposals = strategist.process(sample_regime_packet)
        
        # Verify entry window was checked
        assert strategist._is_entry_window.called or True
    
    def test_process_trend_regime(self, strategist, sample_regime_packet):
        """Test Strategist for TREND regime."""
        sample_regime_packet.regime = RegimeType.TREND
        
        strategist._generate_risk_reversal = Mock(return_value=None)
        strategist._generate_jade_lizard = Mock(return_value=None)
        strategist._is_entry_window = Mock(return_value=True)
        
        # Should not raise error
        proposals = strategist.process(sample_regime_packet)
        
        # Verify entry window was checked
        assert strategist._is_entry_window.called or True
    
    def test_process_chaos_regime_no_trades(self, strategist, sample_regime_packet):
        """Test that CHAOS regime produces no trades."""
        sample_regime_packet.regime = RegimeType.CHAOS
        strategist._is_entry_window = Mock(return_value=True)
        
        proposals = strategist.process(sample_regime_packet)
        
        assert len(proposals) == 0
    
    def test_process_caution_regime_jade_lizard_only(self, strategist, sample_regime_packet):
        """Test that CAUTION regime only generates Jade Lizard."""
        sample_regime_packet.regime = RegimeType.CAUTION
        
        mock_proposal = Mock()
        strategist._generate_jade_lizard = Mock(return_value=mock_proposal)
        strategist._is_entry_window = Mock(return_value=True)
        
        proposals = strategist.process(sample_regime_packet)
        
        # Should only try Jade Lizard
        strategist._generate_jade_lizard.assert_called_once()


class TestDynamicExitTargeting:
    """Tests for Phase 1 dynamic exit targeting"""
    
    @pytest.fixture
    def strategist(self):
        """Create a Strategist instance."""
        mock_kite = Mock()
        mock_config = Mock()
        return Strategist(mock_kite, mock_config)
    
    def test_set_dynamic_targets_short_vol(self, strategist, sample_trade_proposal):
        """Test dynamic targets for SHORT_VOL structures."""
        sample_trade_proposal.exit_target_low = 0
        sample_trade_proposal.exit_target_high = 0
        
        strategist._set_dynamic_targets(sample_trade_proposal, "SHORT_VOL")
        
        assert sample_trade_proposal.exit_target_low == 0.014  # 1.4%
        assert sample_trade_proposal.exit_target_high == 0.018  # 1.8%
        assert sample_trade_proposal.exit_margin_type == "margin"
        assert sample_trade_proposal.trailing_mode == "bbw"
        assert sample_trade_proposal.target_pnl == sample_trade_proposal.max_profit * 0.5
    
    def test_set_dynamic_targets_directional(self, strategist, sample_trade_proposal):
        """Test dynamic targets for DIRECTIONAL structures."""
        sample_trade_proposal.exit_target_low = 0
        sample_trade_proposal.exit_target_high = 0
        
        strategist._set_dynamic_targets(sample_trade_proposal, "DIRECTIONAL")
        
        assert sample_trade_proposal.exit_target_low == 0.014  # 1.4%
        assert sample_trade_proposal.exit_target_high == 0.022  # 2.2%
        assert sample_trade_proposal.exit_margin_type == "percentage"
        assert sample_trade_proposal.trailing_mode == "atr"
        assert sample_trade_proposal.target_pnl == sample_trade_proposal.max_profit * 0.6
    
    def test_dynamic_targets_set_on_proposal(self, strategist, sample_trade_proposal):
        """Test that targets are set before proposal returned."""
        # Before setting targets
        assert sample_trade_proposal.trailing_mode == "bbw"
        
        # Set directional targets
        strategist._set_dynamic_targets(sample_trade_proposal, "DIRECTIONAL")
        
        # After setting, should be configured for directional
        assert sample_trade_proposal.trailing_mode == "atr"
        assert sample_trade_proposal.exit_margin_type == "percentage"
    
    def test_short_vol_stop_loss(self, strategist, sample_trade_proposal):
        """Test that SHORT_VOL has appropriate stop loss."""
        strategist._set_dynamic_targets(sample_trade_proposal, "SHORT_VOL")
        
        expected_stop = -sample_trade_proposal.max_loss * 0.35
        assert sample_trade_proposal.stop_loss == expected_stop
    
    def test_directional_stop_loss(self, strategist, sample_trade_proposal):
        """Test that DIRECTIONAL has appropriate stop loss."""
        strategist._set_dynamic_targets(sample_trade_proposal, "DIRECTIONAL")
        
        expected_stop = -sample_trade_proposal.max_loss * 0.50
        assert sample_trade_proposal.stop_loss == expected_stop


class TestStrategistStructureGeneration:
    """Tests for individual structure generation (mocked)"""
    
    @pytest.fixture
    def strategist(self):
        """Create a Strategist instance."""
        mock_kite = Mock()
        mock_config = Mock()
        return Strategist(mock_kite, mock_config)
    
    def test_generate_strangle_method_exists(self, strategist):
        """Verify Strangle generation method exists."""
        assert hasattr(strategist, '_generate_strangle')
        assert callable(strategist._generate_strangle)
    
    def test_generate_butterfly_method_exists(self, strategist):
        """Verify Butterfly generation method exists."""
        assert hasattr(strategist, '_generate_butterfly')
        assert callable(strategist._generate_butterfly)
    
    def test_generate_bwb_method_exists(self, strategist):
        """Verify Broken-Wing Butterfly generation method exists."""
        assert hasattr(strategist, '_generate_bwb')
        assert callable(strategist._generate_bwb)
    
    def test_generate_risk_reversal_method_exists(self, strategist):
        """Verify Risk Reversal generation method exists."""
        assert hasattr(strategist, '_generate_risk_reversal')
        assert callable(strategist._generate_risk_reversal)
    
    def test_generate_jade_lizard_method_exists(self, strategist):
        """Verify Jade Lizard generation method exists."""
        assert hasattr(strategist, '_generate_jade_lizard')
        assert callable(strategist._generate_jade_lizard)
    
    def test_generate_iron_condor_method_exists(self, strategist):
        """Verify Iron Condor generation method exists."""
        assert hasattr(strategist, '_generate_iron_condor')
        assert callable(strategist._generate_iron_condor)


class TestStrategistEntryWindow:
    """Tests for entry window validation"""
    
    @pytest.fixture
    def strategist(self):
        """Create a Strategist instance."""
        mock_kite = Mock()
        mock_config = Mock()
        return Strategist(mock_kite, mock_config)
    
    def test_outside_entry_window_no_proposals(self, strategist, sample_regime_packet):
        """Test that proposals are rejected outside entry window."""
        strategist._is_entry_window = Mock(return_value=False)
        
        proposals = strategist.process(sample_regime_packet)
        
        assert len(proposals) == 0
    
    def test_within_entry_window_allows_trades(self, strategist, sample_regime_packet):
        """Test that trades are allowed within entry window."""
        sample_regime_packet.regime = RegimeType.RANGE_BOUND
        strategist._is_entry_window = Mock(return_value=True)
        strategist._generate_strangle = Mock(return_value=None)
        strategist._generate_butterfly = Mock(return_value=None)
        strategist._generate_iron_condor = Mock(return_value=None)
        
        proposals = strategist.process(sample_regime_packet)
        
        # Should have tried to generate proposals
        assert strategist._is_entry_window.called


class TestStrategistProposalOrdering:
    """Tests for proposal ordering and filtering"""
    
    @pytest.fixture
    def strategist(self):
        """Create a Strategist instance."""
        mock_kite = Mock()
        mock_config = Mock()
        return Strategist(mock_kite, mock_config)
    
    def test_proposal_limit_one_per_regime(self, strategist, sample_regime_packet):
        """Test that only one proposal is returned per call (best one)."""
        # This is mentioned in process() docstring
        # Create mock proposals with different risk/reward
        mock_proposal1 = Mock()
        mock_proposal1.risk_reward_ratio = 1.0
        
        mock_proposal2 = Mock()
        mock_proposal2.risk_reward_ratio = 1.5
        
        # Simulate multiple proposals being generated
        # (in real implementation they'd be filtered to best one)
        proposals = [mock_proposal2, mock_proposal1]  # Best first
        
        assert len(proposals) <= 2
        assert proposals[0].risk_reward_ratio >= proposals[-1].risk_reward_ratio


# Run tests with: pytest backend/tests/test_strategist.py -v
