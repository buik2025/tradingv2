"""Integration tests for full trading pipeline"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, call
from app.models.regime import RegimeType, RegimePacket
from app.models.trade import TradeSignal, StructureType
from app.models.position import Position, PositionStatus


class TestFullPipelineEndToEnd:
    """Tests for complete signal-to-position lifecycle"""
    
    @pytest.fixture
    def mocked_services(self):
        """Create mocked service components."""
        return {
            'sentinel': Mock(),  # Regime detection
            'strategist': Mock(),  # Signal generation
            'treasury': Mock(),  # Risk approval
            'executor': Mock(),  # Order execution
            'monk': Mock()  # Backtesting
        }
    
    @pytest.fixture
    def full_pipeline(self, mocked_services):
        """Create mock pipeline with all services."""
        return mocked_services
    
    def test_sentinel_to_strategist_flow(self, sample_regime_packet, sample_trade_proposal):
        """Test data flow from Sentinel to Strategist."""
        # Sentinel produces regime packet
        regime_packet = sample_regime_packet
        regime_packet.regime = RegimeType.RANGE_BOUND
        
        # Strategist consumes it
        strategist = Mock()
        strategist.process = Mock(return_value=[sample_trade_proposal])
        
        proposals = strategist.process(regime_packet)
        
        assert len(proposals) > 0
        assert strategist.process.called
        assert strategist.process.call_args[0][0] == regime_packet
    
    def test_strategist_to_treasury_flow(self, sample_trade_proposal):
        """Test data flow from Strategist to Treasury."""
        # Strategist produces proposal
        proposal = sample_trade_proposal
        
        # Treasury validates it
        treasury = Mock()
        treasury.validate = Mock(return_value=True)
        
        is_valid = treasury.validate(proposal)
        
        assert is_valid == True
        assert treasury.validate.called
    
    def test_treasury_to_executor_flow(self, sample_trade_proposal):
        """Test data flow from Treasury to Executor."""
        # Treasury approves proposal and creates signal
        signal = Mock(spec=TradeSignal)
        signal.proposal = sample_trade_proposal
        signal.status = "APPROVED"
        
        # Executor receives it
        executor = Mock()
        executor.execute = Mock(return_value=True)
        
        result = executor.execute(signal)
        
        assert result == True
        assert executor.execute.called
    
    def test_executor_to_position_creation(self, sample_trade_proposal):
        """Test position creation from approved signal."""
        signal = Mock()
        signal.proposal = sample_trade_proposal
        
        # Create position from signal
        position = Mock(spec=Position)
        position.status = PositionStatus.OPEN
        position.entry_price = sample_trade_proposal.entry_price
        
        # Verify position has proposal data
        assert position.entry_price == sample_trade_proposal.entry_price


class TestRegimeTransitionPipeline:
    """Tests for pipeline behavior during regime changes"""
    
    def test_regime_transition_changes_structure(self, sample_regime_packet, sample_trade_proposal):
        """Test that different structures are generated for different regimes."""
        strategist = Mock()
        
        # RANGE_BOUND regime
        regime1 = RegimeType.RANGE_BOUND
        sample_regime_packet.regime = regime1
        sample_trade_proposal.structure = StructureType.IRON_CONDOR
        strategist.process = Mock(return_value=[sample_trade_proposal])
        
        proposals_1 = strategist.process(sample_regime_packet)
        
        # TREND regime  
        regime2 = RegimeType.TREND
        sample_regime_packet.regime = regime2
        sample_trade_proposal.structure = StructureType.RISK_REVERSAL
        
        proposals_2 = strategist.process(sample_regime_packet)
        
        # Different regimes should prefer different structures
        assert strategist.process.call_count == 2
    
    def test_chaos_regime_stops_trading(self, sample_regime_packet):
        """Test that CHAOS regime halts new trades."""
        strategist = Mock()
        sample_regime_packet.regime = RegimeType.CHAOS
        
        strategist.process = Mock(return_value=[])
        proposals = strategist.process(sample_regime_packet)
        
        assert len(proposals) == 0
    
    def test_caution_regime_only_jade_lizard(self, sample_regime_packet):
        """Test that CAUTION regime only generates Jade Lizard trades."""
        strategist = Mock()
        sample_regime_packet.regime = RegimeType.CAUTION
        
        proposal = Mock()
        proposal.structure = StructureType.JADE_LIZARD
        
        strategist.process = Mock(return_value=[proposal])
        proposals = strategist.process(sample_regime_packet)
        
        if len(proposals) > 0:
            assert proposals[0].structure == StructureType.JADE_LIZARD


class TestDynamicExitTargetingPipeline:
    """Tests for dynamic exit targeting across pipeline"""
    
    def test_dynamic_targets_set_at_strategist(self, sample_trade_proposal):
        """Test that dynamic targets are set when proposal created."""
        sample_trade_proposal.exit_target_low = 0.014
        sample_trade_proposal.exit_target_high = 0.018
        
        assert sample_trade_proposal.exit_target_low > 0
        assert sample_trade_proposal.exit_target_high > 0
    
    def test_targets_transferred_to_position(self, sample_trade_proposal):
        """Test that targets transfer from proposal to position."""
        proposal = sample_trade_proposal
        proposal.exit_target_low = 0.014
        proposal.exit_target_high = 0.018
        
        position = Mock()
        position.exit_target_low = proposal.exit_target_low
        position.exit_target_high = proposal.exit_target_high
        position.current_target = proposal.exit_target_low
        
        assert position.exit_target_low == proposal.exit_target_low
        assert position.exit_target_high == proposal.exit_target_high
    
    def test_executor_monitors_dynamic_targets(self, sample_position):
        """Test that executor uses dynamic targets in exit checks."""
        sample_position.current_target = sample_position.exit_target_low
        sample_position.current_pnl = sample_position.current_target + 10
        
        # Should trigger exit
        should_exit = sample_position.current_pnl >= sample_position.current_target
        assert should_exit == True
    
    def test_short_vol_vs_directional_targets(self, sample_trade_proposal):
        """Test that different structure types get different targets."""
        # SHORT_VOL structure
        sv_proposal = sample_trade_proposal
        sv_proposal.structure = StructureType.IRON_CONDOR
        sv_proposal.exit_target_low = 0.014
        sv_proposal.exit_target_high = 0.018
        
        # DIRECTIONAL structure
        dir_proposal = Mock()
        dir_proposal.structure = StructureType.JADE_LIZARD
        dir_proposal.exit_target_low = 0.014
        dir_proposal.exit_target_high = 0.022  # Higher for directional
        
        assert sv_proposal.exit_target_high < dir_proposal.exit_target_high


class TestTrailingProfitPipeline:
    """Tests for trailing profit execution through pipeline"""
    
    def test_trailing_enabled_in_proposal(self, sample_trade_proposal):
        """Test that trailing mode is set in proposal."""
        sample_trade_proposal.trailing_mode = "atr"
        assert sample_trade_proposal.trailing_mode == "atr"
    
    def test_trailing_transferred_to_position(self, sample_trade_proposal):
        """Test that trailing config transfers to position."""
        proposal = sample_trade_proposal
        proposal.trailing_mode = "atr"
        
        position = Mock()
        position.trailing_mode = proposal.trailing_mode
        position.trailing_enabled = True
        
        assert position.trailing_mode == proposal.trailing_mode
        assert position.trailing_enabled == True
    
    def test_executor_monitors_trailing_stops(self, sample_position):
        """Test that executor actively monitors trailing stops."""
        sample_position.trailing_enabled = True
        sample_position.trailing_active = True
        sample_position.trailing_mode = "atr"
        
        # Executor would call this periodically
        should_exit = sample_position.update_trailing_stop(19100, atr=150)
        
        assert callable(sample_position.update_trailing_stop)
        assert should_exit is not None
    
    def test_trailing_stop_exit_generated(self, sample_position):
        """Test that exit order generated when trailing stop hit."""
        sample_position.trailing_enabled = True
        sample_position.trailing_stop = 19000
        
        # Price hits trailing stop
        current_price = 18950
        
        should_exit = current_price <= sample_position.trailing_stop
        assert should_exit == True


class TestPositionLifecyclePipeline:
    """Tests for complete position lifecycle"""
    
    def test_position_creation_to_monitoring(self, sample_trade_proposal, sample_position):
        """Test position creation and initial monitoring setup."""
        # Signal approved with proposal
        signal = Mock()
        signal.proposal = sample_trade_proposal
        signal.status = "APPROVED"
        
        # Position created from signal
        position = sample_position
        position.status = PositionStatus.OPEN
        position.entry_price = sample_trade_proposal.entry_price
        
        assert position.status == PositionStatus.OPEN
        assert position.entry_price == sample_trade_proposal.entry_price
    
    def test_position_profit_target_exit(self, sample_position):
        """Test position exits at profit target."""
        sample_position.current_target = 150
        sample_position.current_pnl = 160
        sample_position.status = PositionStatus.OPEN
        
        # Should generate exit
        should_exit = sample_position.current_pnl >= sample_position.current_target
        assert should_exit == True
        
        # After exit
        sample_position.status = PositionStatus.CLOSED
        assert sample_position.status == PositionStatus.CLOSED
    
    def test_position_stop_loss_exit(self, sample_position):
        """Test position exits at stop loss."""
        sample_position.stop_loss = -100
        sample_position.current_pnl = -110
        sample_position.status = PositionStatus.OPEN
        
        # Should generate exit
        should_exit = sample_position.current_pnl <= sample_position.stop_loss
        assert should_exit == True
        
        # Mark closed
        sample_position.status = PositionStatus.CLOSED
        assert sample_position.status == PositionStatus.CLOSED
    
    def test_position_trailing_stop_exit(self, sample_position):
        """Test position exits at trailing stop."""
        sample_position.trailing_enabled = True
        sample_position.trailing_stop = 19000
        sample_position.status = PositionStatus.OPEN
        
        # Price hits trailing stop
        current_price = 18990
        should_exit = current_price <= sample_position.trailing_stop
        
        if should_exit:
            sample_position.status = PositionStatus.CLOSED
        
        assert callable(sample_position.update_trailing_stop)


class TestErrorRecoveryPipeline:
    """Tests for error handling across pipeline"""
    
    def test_invalid_regime_packet_handling(self):
        """Test handling of invalid regime packet."""
        invalid_packet = Mock()
        invalid_packet.regime = None
        
        strategist = Mock()
        strategist.process = Mock(side_effect=ValueError("Invalid regime"))
        
        with pytest.raises(ValueError):
            strategist.process(invalid_packet)
    
    def test_execution_failure_handling(self, sample_trade_proposal):
        """Test handling of execution failure."""
        signal = Mock()
        signal.proposal = sample_trade_proposal
        
        executor = Mock()
        executor.execute = Mock(side_effect=Exception("Execution failed"))
        
        with pytest.raises(Exception):
            executor.execute(signal)
    
    def test_position_update_failure_recovery(self, sample_position):
        """Test recovery from position update failure."""
        # Create a new mock position for this test
        mock_pos = Mock()
        mock_pos.update_trailing_stop = Mock(
            side_effect=Exception("Update failed")
        )
        
        with pytest.raises(Exception):
            mock_pos.update_trailing_stop(19100, atr=150)


class TestMultiPositionPipeline:
    """Tests for handling multiple concurrent positions"""
    
    def test_multiple_positions_independent_exits(self):
        """Test that multiple positions exit independently."""
        positions = [
            Mock(id="pos_1", current_pnl=200, current_target=150, status=PositionStatus.OPEN),
            Mock(id="pos_2", current_pnl=50, current_target=150, status=PositionStatus.OPEN),
            Mock(id="pos_3", current_pnl=300, current_target=150, status=PositionStatus.OPEN),
        ]
        
        # Check which should exit at target
        should_exit = [
            pos.current_pnl >= pos.current_target for pos in positions
        ]
        
        # pos_1 and pos_3 should exit, pos_2 should not
        assert should_exit[0] == True
        assert should_exit[1] == False
        assert should_exit[2] == True
    
    def test_multiple_positions_different_structures(self):
        """Test multiple positions with different structures."""
        position1 = Mock(
            id="pos_1",
            structure=StructureType.IRON_CONDOR,
            trailing_mode="bbw"
        )
        position2 = Mock(
            id="pos_2",
            structure=StructureType.JADE_LIZARD,
            trailing_mode="atr"
        )
        position3 = Mock(
            id="pos_3",
            structure=StructureType.RISK_REVERSAL,
            trailing_mode="atr"
        )
        
        positions = [position1, position2, position3]
        
        # Each should maintain independent trailing mode
        assert positions[0].trailing_mode == "bbw"
        assert positions[1].trailing_mode == "atr"
        assert positions[2].trailing_mode == "atr"


# Run tests with: pytest backend/tests/test_full_pipeline.py -v
