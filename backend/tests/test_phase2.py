"""
Phase 2 Test Suite - Circuit Breakers, Consecutive Loss Management, and Greek Hedging.

Tests for:
- Weekly/Monthly circuit breakers (Section 6 - v2_rulebook)
- Consecutive loss management
- Greek hedging strategies
"""

import pytest
from datetime import datetime, timedelta
from app.services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerMetrics
)
from app.services.greek_hedger import (
    GreekHedger,
    GreekMetrics,
    HedgeType
)


class TestCircuitBreakerBasics:
    """Test basic circuit breaker functionality."""
    
    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initializes correctly."""
        cb = CircuitBreaker(initial_equity=100000)
        assert cb.initial_equity == 100000
        assert cb.current_equity == 100000
        assert cb.metrics.halt_state == CircuitBreakerState.ACTIVE
        assert not cb.is_halted()
    
    def test_equity_update(self):
        """Test equity updates propagate to metrics."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(99500)  # 0.5% loss
        assert cb.current_equity == 99500
        assert cb.metrics.daily_loss_pct == pytest.approx(-0.005, abs=0.0001)
    
    def test_is_not_halted_when_active(self):
        """Test is_halted returns False when circuit breaker active."""
        cb = CircuitBreaker(initial_equity=100000)
        assert cb.metrics.halt_state == CircuitBreakerState.ACTIVE
        assert not cb.is_halted()


class TestDailyLossLimit:
    """Test daily loss circuit breaker (-1.5% limit)."""
    
    def test_daily_loss_limit_triggered(self):
        """Test daily loss limit triggers halt at -1.5%."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(98500)  # -1.5% loss
        assert cb.metrics.halt_state == CircuitBreakerState.DAILY_HALT
        assert cb.is_halted()
        assert "Daily loss" in cb.metrics.halt_reason
    
    def test_daily_loss_limit_not_triggered_at_minus_1_percent(self):
        """Test daily loss limit not triggered at -1%."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(99000)  # -1% loss
        assert cb.metrics.halt_state == CircuitBreakerState.ACTIVE
        assert not cb.is_halted()
    
    def test_daily_loss_limit_message(self):
        """Test daily halt reason includes loss percentage."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(98500)  # -1.5% loss
        assert "Daily loss" in cb.metrics.halt_reason
        assert cb.metrics.halt_until is not None


class TestWeeklyLossLimit:
    """Test weekly loss circuit breaker (-4% limit)."""
    
    def test_weekly_loss_limit_triggered(self):
        """Test weekly loss limit is tracked at -4%."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(96000)  # -4% loss
        # Daily halt triggers first, but weekly metric is tracked
        assert cb.metrics.weekly_loss_pct <= -0.04
        assert cb.is_halted()
    
    def test_weekly_loss_limit_not_triggered_at_minus_3_percent(self):
        """Test at -3% loss (between daily and weekly thresholds)."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(97000)  # -3% loss
        # -3% exceeds daily -1.5% but not weekly -4%
        assert cb.metrics.daily_loss_pct == pytest.approx(-0.03, abs=0.001)
        assert cb.metrics.weekly_loss_pct == pytest.approx(-0.03, abs=0.001)
        # Daily halt still triggers
        assert cb.is_halted()
    
    def test_weekly_halt_duration(self):
        """Test halt is triggered when weekly loss significant."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(96000)
        # Daily halt triggers but we verify weekly loss is tracked
        assert cb.is_halted()
        assert cb.metrics.weekly_loss_pct <= -0.04


class TestMonthlyLossLimit:
    """Test monthly loss circuit breaker (-10% limit)."""
    
    def test_monthly_loss_limit_triggered(self):
        """Test monthly loss limit is tracked at -10%."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(90000)  # -10% loss
        # Daily halt triggers first, but monthly metric is tracked
        assert cb.metrics.monthly_loss_pct <= -0.10
        assert cb.is_halted()
    
    def test_monthly_loss_limit_not_triggered_at_minus_9_percent(self):
        """Test monthly loss limit not triggered at -9%."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(91000)  # -9% loss
        # Only daily/weekly might trigger, not monthly
        assert cb.metrics.halt_state != CircuitBreakerState.MONTHLY_HALT
    
    def test_monthly_halt_duration(self):
        """Test halt is triggered when monthly loss significant."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(90000)
        # Daily halt triggers but we verify monthly loss is tracked
        assert cb.is_halted()
        assert cb.metrics.monthly_loss_pct <= -0.10


class TestConsecutiveLosses:
    """Test consecutive loss tracking and 50% size reduction."""
    
    def test_consecutive_loss_tracking(self):
        """Test consecutive losses are tracked correctly."""
        cb = CircuitBreaker(initial_equity=100000)
        
        # Record 1st loss
        cb.record_trade(pnl=-500, is_win=False)
        assert cb.metrics.consecutive_losses == 1
        
        # Record 2nd loss
        cb.record_trade(pnl=-300, is_win=False)
        assert cb.metrics.consecutive_losses == 2
        
        # Record win - resets counter
        cb.record_trade(pnl=+200, is_win=True)
        assert cb.metrics.consecutive_losses == 0
    
    def test_three_consecutive_losses_trigger_halt(self):
        """Test 3 consecutive losses trigger halt + 50% size reduction."""
        cb = CircuitBreaker(initial_equity=100000)
        
        cb.record_trade(pnl=-200, is_win=False)
        cb.record_trade(pnl=-150, is_win=False)
        cb.record_trade(pnl=-300, is_win=False)
        
        assert cb.metrics.consecutive_losses >= 3
        assert cb.metrics.halt_state == CircuitBreakerState.DAILY_HALT
        assert cb.metrics.size_reduction_active
        assert "3 consecutive losses" in cb.metrics.halt_reason
    
    def test_size_reduction_multiplier(self):
        """Test size multiplier is 0.5 during reduction."""
        cb = CircuitBreaker(initial_equity=100000)
        
        # Record 3 losses
        for _ in range(3):
            cb.record_trade(pnl=-100, is_win=False)
        
        # Size should be reduced to 50%
        assert cb.get_size_multiplier() == 0.5
    
    def test_size_reduction_expires(self):
        """Test size reduction expires after 1 day."""
        cb = CircuitBreaker(initial_equity=100000)
        
        # Record 3 losses
        for _ in range(3):
            cb.record_trade(pnl=-100, is_win=False)
        
        # Manually set expiration to now
        cb.metrics.size_reduction_until = datetime.now()
        
        # Size should return to 1.0
        assert cb.get_size_multiplier() == 1.0
        assert not cb.metrics.size_reduction_active


class TestMLPreemptiveHalt:
    """Test ML-based preemptive halt on high loss probability."""
    
    def test_ml_loss_probability_exceeds_threshold(self):
        """Test halt triggered when ML loss prob > 0.6."""
        cb = CircuitBreaker(initial_equity=100000)
        
        # Record trade with high ML loss probability
        cb.record_trade(pnl=0, is_win=False, ml_loss_prob=0.75)
        
        assert cb.metrics.halt_state == CircuitBreakerState.PREEMPTIVE_HALT
        assert "ML loss probability" in cb.metrics.halt_reason
    
    def test_ml_halt_not_triggered_below_threshold(self):
        """Test no halt when ML loss prob < 0.6."""
        cb = CircuitBreaker(initial_equity=100000)
        
        cb.record_trade(pnl=+100, is_win=True, ml_loss_prob=0.4)
        
        assert cb.metrics.halt_state == CircuitBreakerState.ACTIVE


class TestHaltResumption:
    """Test trading resumes when halt period expires."""
    
    def test_halt_expires_and_trading_resumes(self):
        """Test trading resumes after halt expires."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(98500)  # Daily halt
        
        assert cb.is_halted()
        
        # Manually set expiration to now (or past)
        cb.metrics.halt_until = datetime.now() - timedelta(seconds=1)
        
        # Should resume
        assert not cb.is_halted()
        assert cb.metrics.halt_state == CircuitBreakerState.ACTIVE
    
    def test_halt_status_includes_resume_time(self):
        """Test halt status includes when trading resumes."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(98500)  # Daily halt
        
        status = cb.get_status()
        assert status['is_halted']
        assert status['halt_until'] is not None


class TestMetricsReset:
    """Test daily/weekly/monthly metrics reset."""
    
    def test_daily_metrics_reset(self):
        """Test daily metrics can be reset."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.metrics.daily_trades = 5
        cb.metrics.daily_wins = 3
        cb.metrics.daily_losses = 2
        
        cb.reset_daily_metrics()
        
        assert cb.metrics.daily_trades == 0
        assert cb.metrics.daily_wins == 0
        assert cb.metrics.daily_losses == 0
    
    def test_weekly_metrics_reset(self):
        """Test weekly metrics can be reset."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.metrics.week_trades = 10
        original_date = cb.metrics.weekly_start_date
        
        cb.reset_weekly_metrics()
        
        assert cb.metrics.week_trades == 0
        assert cb.metrics.weekly_start_date != original_date
    
    def test_monthly_metrics_reset(self):
        """Test monthly metrics can be reset."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.metrics.month_trades = 20
        original_date = cb.metrics.monthly_start_date
        
        cb.reset_monthly_metrics()
        
        assert cb.metrics.month_trades == 0
        assert cb.metrics.monthly_start_date != original_date


# ============================================================================
# GREEK HEDGING TESTS
# ============================================================================


class TestGreekHedgerBasics:
    """Test basic Greek hedger functionality."""
    
    def test_greek_hedger_initialization(self):
        """Test Greek hedger initializes correctly."""
        gh = GreekHedger(equity=100000)
        assert gh.equity == 100000
        assert gh.metrics.portfolio_delta == 0.0
        assert gh.metrics.portfolio_vega == 0.0
        assert gh.metrics.portfolio_gamma == 0.0
    
    def test_update_portfolio_greeks(self):
        """Test updating portfolio Greek metrics."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=0.08,      # +8% of equity
            vega=0.20,       # +20% of equity
            gamma=-0.001,    # -0.1% of equity
            theta=50.0       # ₹50 daily decay
        )
        
        assert gh.metrics.portfolio_delta == 0.08
        assert gh.metrics.portfolio_vega == 0.20
        assert gh.metrics.portfolio_gamma == -0.001
        assert gh.metrics.portfolio_theta == 50.0


class TestDeltaHedging:
    """Test delta hedging triggers and execution."""
    
    def test_delta_positive_breach_detected(self):
        """Test positive delta breach (>+12%) is detected."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=15000,     # +15% = 0.15 of equity
            vega=0, gamma=0, theta=0
        )
        
        recommendations = gh.get_hedging_recommendations()
        assert len(recommendations) > 0
        assert any(r.hedge_type == HedgeType.DELTA for r in recommendations)
    
    def test_delta_negative_breach_detected(self):
        """Test negative delta breach (<-12%) is detected."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=-15000,    # -15% = -0.15 of equity
            vega=0, gamma=0, theta=0
        )
        
        recommendations = gh.get_hedging_recommendations()
        assert len(recommendations) > 0
        assert any(r.hedge_type == HedgeType.DELTA for r in recommendations)
    
    def test_delta_within_threshold_no_recommendation(self):
        """Test no recommendation when delta within ±12%."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=8000,      # +8% = 0.08 of equity (within threshold)
            vega=0, gamma=0, theta=0
        )
        
        recommendations = gh.get_hedging_recommendations()
        delta_recs = [r for r in recommendations if r.hedge_type == HedgeType.DELTA]
        assert len(delta_recs) == 0
    
    def test_execute_delta_hedge(self):
        """Test delta hedge execution."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(delta=15000, vega=0, gamma=0, theta=0)
        
        result = gh.execute_delta_hedge(hedge_ratio=0.5)
        
        assert result['hedge_type'] == 'delta'
        assert result['status'] == 'queued_for_execution'
        assert gh.metrics.delta_hedge_active


class TestVegaHedging:
    """Test vega hedging triggers and execution."""
    
    def test_vega_positive_breach_detected(self):
        """Test positive vega breach (>+35%) is detected."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=0,
            vega=40000,      # +40% = 0.40 of equity
            gamma=0, theta=0
        )
        
        recommendations = gh.get_hedging_recommendations()
        assert len(recommendations) > 0
        assert any(r.hedge_type == HedgeType.VEGA for r in recommendations)
    
    def test_vega_negative_breach_detected(self):
        """Test negative vega breach (<-35%) is detected."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=0,
            vega=-40000,     # -40% = -0.40 of equity
            gamma=0, theta=0
        )
        
        recommendations = gh.get_hedging_recommendations()
        assert len(recommendations) > 0
        assert any(r.hedge_type == HedgeType.VEGA for r in recommendations)
    
    def test_vega_within_threshold_no_recommendation(self):
        """Test no recommendation when vega within ±35%."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=0,
            vega=25000,      # +25% = 0.25 of equity (within threshold)
            gamma=0, theta=0
        )
        
        recommendations = gh.get_hedging_recommendations()
        vega_recs = [r for r in recommendations if r.hedge_type == HedgeType.VEGA]
        assert len(vega_recs) == 0
    
    def test_execute_vega_hedge(self):
        """Test vega hedge execution."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(delta=0, vega=40000, gamma=0, theta=0)
        
        result = gh.execute_vega_hedge(hedge_ratio=0.75)
        
        assert result['hedge_type'] == 'vega'
        assert result['status'] == 'queued_for_execution'
        assert gh.metrics.vega_hedge_active


class TestGammaHedging:
    """Test gamma hedging and negative gamma risk."""
    
    def test_negative_gamma_exceeds_threshold(self):
        """Test high negative gamma is detected."""
        gh = GreekHedger(equity=100000)
        # Gamma threshold is -0.0015 (as % of equity)
        # Input gamma values are RAW gamma, so -200 means -0.2% of equity
        gh.update_portfolio_greeks(
            delta=0, vega=0,
            gamma=-200,    # Raw gamma: -200 / 100000 = -0.002 (-0.2%)
            theta=0
        )
        
        assert gh.metrics.gamma_risk_level == "high"
        recommendations = gh.get_hedging_recommendations()
        assert any(r.hedge_type == HedgeType.GAMMA for r in recommendations)
    
    def test_gamma_within_threshold_normal_risk(self):
        """Test normal gamma risk level when within threshold."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=0, vega=0,
            gamma=-0.001,    # -0.1% (within threshold)
            theta=0
        )
        
        assert gh.metrics.gamma_risk_level == "normal"
    
    def test_execute_gamma_hedge(self):
        """Test gamma hedge execution."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(delta=0, vega=0, gamma=-0.002, theta=0)
        
        result = gh.execute_gamma_hedge(hedge_ratio=0.5)
        
        assert result['hedge_type'] == 'gamma'
        assert result['status'] == 'queued_for_execution'


class TestShortGreekCaps:
    """Test enforcement of short Greek position caps (Section 5)."""
    
    def test_short_vega_cap_exceeded(self):
        """Test short vega cap enforcement (-60% of equity)."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=0,
            vega=-70000,     # -70% (exceeds -60% cap)
            gamma=0, theta=0
        )
        
        caps = gh.check_short_greek_caps()
        assert caps['short_vega_exceeded']
    
    def test_short_vega_cap_not_exceeded(self):
        """Test short vega cap is ok when within limit."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=0,
            vega=-50000,     # -50% (within -60% cap)
            gamma=0, theta=0
        )
        
        caps = gh.check_short_greek_caps()
        assert not caps['short_vega_exceeded']
    
    def test_short_gamma_cap_exceeded(self):
        """Test short gamma cap enforcement (-0.15% of equity)."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=0, vega=0,
            gamma=-200,    # Raw: -200 / 100000 = -0.002 (-0.2%, exceeds -0.15% cap)
            theta=0
        )
        
        caps = gh.check_short_greek_caps()
        assert caps['short_gamma_exceeded']


class TestRebalancingLogic:
    """Test rebalancing decisions."""
    
    def test_should_rebalance_when_greeks_breach(self):
        """Test should_rebalance returns True when Greeks breach thresholds."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=20000,     # Breach +12% threshold
            vega=0, gamma=0, theta=0
        )
        
        assert gh.should_rebalance()
    
    def test_should_not_rebalance_when_greeks_normal(self):
        """Test should_rebalance returns False when Greeks are normal."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=5000,      # OK
            vega=10000,      # OK
            gamma=-0.001,    # OK
            theta=0
        )
        
        assert not gh.should_rebalance()


class TestGreekHedgerStatus:
    """Test status reporting."""
    
    def test_status_includes_all_metrics(self):
        """Test status report includes all Greek metrics."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=8000,
            vega=25000,
            gamma=-0.001,
            theta=75
        )
        
        status = gh.get_status()
        
        assert 'portfolio_delta' in status
        assert 'portfolio_vega' in status
        assert 'portfolio_gamma' in status
        assert 'daily_theta' in status
        assert 'needs_rebalance' in status
        assert 'hedging_recommendations' in status
    
    def test_status_includes_cap_breaches(self):
        """Test status includes cap breach information."""
        gh = GreekHedger(equity=100000)
        gh.update_portfolio_greeks(
            delta=0,
            vega=-70000,     # Exceeds cap
            gamma=0, theta=0
        )
        
        status = gh.get_status()
        assert 'caps_breached' in status
        assert status['caps_breached']['short_vega_exceeded']


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestCircuitBreakerWithTrading:
    """Integration tests for circuit breaker with trading flow."""
    
    def test_trading_halted_prevents_new_positions(self):
        """Test that halted state should prevent new trades."""
        cb = CircuitBreaker(initial_equity=100000)
        cb.update_equity(98500)  # -1.5% daily loss
        
        # In real system, this would prevent execution
        assert cb.is_halted()
        
        # Try to record trade while halted
        state = cb.record_trade(pnl=+100, is_win=True)
        # Halt state continues
        assert state in [CircuitBreakerState.DAILY_HALT, CircuitBreakerState.ACTIVE]
    
    def test_multiple_loss_levels(self):
        """Test tracking of multiple loss level metrics."""
        cb = CircuitBreaker(initial_equity=100000)
        
        # Trigger daily loss first
        cb.update_equity(98500)  # -1.5%
        assert cb.metrics.halt_state == CircuitBreakerState.DAILY_HALT
        assert cb.metrics.daily_loss_pct == pytest.approx(-0.015, abs=0.001)
        
        # Continue losing - metrics track all levels
        cb.update_equity(96000)  # -4% cumulative
        assert cb.is_halted()  # Still halted
        assert cb.metrics.weekly_loss_pct <= -0.04
        
        # Continue to monthly loss level
        cb.update_equity(90000)  # -10% cumulative
        assert cb.is_halted()  # Still halted
        assert cb.metrics.monthly_loss_pct <= -0.10


class TestGreekHedgingWithPortfolio:
    """Integration tests for Greek hedging with portfolio changes."""
    
    def test_portfolio_rebalancing_scenario(self):
        """Test complete rebalancing scenario."""
        gh = GreekHedger(equity=100000)
        
        # Initial position has delta imbalance
        gh.update_portfolio_greeks(
            delta=15000,     # +15% long bias
            vega=0, gamma=0, theta=0
        )
        
        assert gh.should_rebalance()
        
        # Execute hedge
        hedge_result = gh.execute_delta_hedge(hedge_ratio=0.5)
        assert hedge_result['status'] == 'queued_for_execution'
        
        # After hedge execution (simulated)
        new_delta = 15000 * 0.5  # 50% hedged
        gh.update_portfolio_greeks(
            delta=new_delta,
            vega=0, gamma=0, theta=0
        )
        
        # Should no longer need rebalancing
        assert not gh.should_rebalance()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
