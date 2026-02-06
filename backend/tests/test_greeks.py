"""Unit tests for Greeks calculation module"""

import pytest
from datetime import date, timedelta
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.greeks import (
    GreeksCalculator,
    validate_and_calculate_greeks,
    _are_greeks_valid,
    _fallback_greeks
)


class TestGreeksCalculator:
    """Test suite for GreeksCalculator class."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.calculator = GreeksCalculator(risk_free_rate=0.065)
    
    def test_atm_call_greeks(self):
        """Test Greeks calculation for ATM call option."""
        greeks = self.calculator.calculate_all(
            spot_price=19000,
            strike=19000,
            time_to_expiry=10/365,  # 10 days
            volatility=0.20,
            option_type='CE'
        )
        
        # ATM call should have delta around 0.5
        assert 0.45 <= greeks['delta'] <= 0.55
        
        # Gamma should be positive
        assert greeks['gamma'] > 0
        
        # Theta should be negative (time decay)
        assert greeks['theta'] < 0
        
        # Vega should be positive
        assert greeks['vega'] > 0
    
    def test_otm_put_greeks(self):
        """Test Greeks calculation for OTM put option."""
        greeks = self.calculator.calculate_all(
            spot_price=19000,
            strike=18500,  # OTM put
            time_to_expiry=10/365,
            volatility=0.20,
            option_type='PE'
        )
        
        # OTM put should have delta between -0.5 and 0
        assert -0.5 <= greeks['delta'] <= 0
        
        # Gamma should be positive
        assert greeks['gamma'] > 0
        
        # Vega should be positive
        assert greeks['vega'] > 0
    
    def test_itm_call_greeks(self):
        """Test Greeks calculation for ITM call option."""
        greeks = self.calculator.calculate_all(
            spot_price=19000,
            strike=18500,  # ITM call
            time_to_expiry=10/365,
            volatility=0.20,
            option_type='CE'
        )
        
        # ITM call should have high delta
        assert greeks['delta'] > 0.6
    
    def test_expired_option(self):
        """Test Greeks for expired option."""
        greeks = self.calculator.calculate_all(
            spot_price=19000,
            strike=18500,
            time_to_expiry=0,  # Expired
            volatility=0.20,
            option_type='CE'
        )
        
        # ITM expired call: delta = 1
        assert greeks['delta'] == 1.0
        
        # All other Greeks should be zero
        assert greeks['gamma'] == 0.0
        assert greeks['theta'] == 0.0
        assert greeks['vega'] == 0.0
    
    def test_time_to_expiry_calculation(self):
        """Test time to expiry calculation."""
        today = date.today()
        expiry = today + timedelta(days=10)
        
        tte = self.calculator.calculate_time_to_expiry(expiry)
        
        # Should be approximately 10/365
        assert abs(tte - 10/365) < 0.01
    
    def test_negative_volatility_handling(self):
        """Test handling of invalid volatility."""
        greeks = self.calculator.calculate_all(
            spot_price=19000,
            strike=19000,
            time_to_expiry=10/365,
            volatility=-0.10,  # Invalid
            option_type='CE'
        )
        
        # Should still return valid Greeks (uses default 0.20)
        assert 0.45 <= greeks['delta'] <= 0.55


class TestValidateAndCalculateGreeks:
    """Test suite for validate_and_calculate_greeks function."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.calculator = GreeksCalculator()
        self.expiry = date.today() + timedelta(days=10)
    
    def test_uses_valid_chain_greeks(self):
        """Test that valid chain Greeks are used as-is."""
        chain_greeks = {
            'delta': 0.52,
            'gamma': 0.015,
            'theta': -4.5,
            'vega': 12.0
        }
        
        result = validate_and_calculate_greeks(
            spot_price=19000,
            strike=19000,
            expiry_date=self.expiry,
            volatility=0.20,
            option_type='CE',
            chain_greeks=chain_greeks,
            calculator=self.calculator
        )
        
        # Should use chain Greeks
        assert result['delta'] == 0.52
        assert result['gamma'] == 0.015
    
    def test_calculates_when_chain_greeks_invalid(self):
        """Test that Greeks are calculated when chain data is invalid."""
        chain_greeks = {
            'delta': None,  # Invalid
            'gamma': 0.015,
            'theta': -4.5,
            'vega': 12.0
        }
        
        result = validate_and_calculate_greeks(
            spot_price=19000,
            strike=19000,
            expiry_date=self.expiry,
            volatility=0.20,
            option_type='CE',
            chain_greeks=chain_greeks,
            calculator=self.calculator
        )
        
        # Should calculate Greeks (ATM call delta ~0.5)
        assert 0.45 <= result['delta'] <= 0.55
    
    def test_fallback_on_calculation_error(self):
        """Test fallback Greeks when calculation fails."""
        # Create invalid scenario (will trigger fallback)
        result = validate_and_calculate_greeks(
            spot_price=19000,
            strike=19000,
            expiry_date=date.today() - timedelta(days=1),  # Past expiry
            volatility=0.20,
            option_type='CE',
            chain_greeks=None,
            calculator=self.calculator
        )
        
        # Should still return valid Greeks
        assert 'delta' in result
        assert 'gamma' in result
        assert 'theta' in result
        assert 'vega' in result


class TestAreGreeksValid:
    """Test suite for _are_greeks_valid function."""
    
    def test_valid_greeks(self):
        """Test that valid Greeks pass validation."""
        greeks = {
            'delta': 0.50,
            'gamma': 0.015,
            'theta': -4.5,
            'vega': 12.0
        }
        
        assert _are_greeks_valid(greeks) is True
    
    def test_missing_required_greek(self):
        """Test that missing Greeks fail validation."""
        greeks = {
            'delta': 0.50,
            'gamma': 0.015,
            # Missing theta and vega
        }
        
        assert _are_greeks_valid(greeks) is False
    
    def test_none_values(self):
        """Test that None values fail validation."""
        greeks = {
            'delta': None,
            'gamma': 0.015,
            'theta': -4.5,
            'vega': 12.0
        }
        
        assert _are_greeks_valid(greeks) is False
    
    def test_invalid_delta_range(self):
        """Test that delta outside [-1, 1] fails validation."""
        greeks = {
            'delta': 1.5,  # Invalid
            'gamma': 0.015,
            'theta': -4.5,
            'vega': 12.0
        }
        
        assert _are_greeks_valid(greeks) is False
    
    def test_negative_gamma(self):
        """Test that negative gamma fails validation."""
        greeks = {
            'delta': 0.50,
            'gamma': -0.015,  # Invalid (should be positive)
            'theta': -4.5,
            'vega': 12.0
        }
        
        assert _are_greeks_valid(greeks) is False


class TestFallbackGreeks:
    """Test suite for _fallback_greeks function."""
    
    def test_itm_call_fallback(self):
        """Test fallback Greeks for ITM call."""
        greeks = _fallback_greeks(
            spot_price=19000,
            strike=18000,  # ITM
            option_type='CE'
        )
        
        # ITM call should have high delta
        assert greeks['delta'] > 0.6
    
    def test_otm_put_fallback(self):
        """Test fallback Greeks for OTM put."""
        greeks = _fallback_greeks(
            spot_price=19000,
            strike=18000,  # OTM put
            option_type='PE'
        )
        
        # OTM put should have low negative delta
        assert -0.3 <= greeks['delta'] < 0
    
    def test_atm_fallback(self):
        """Test fallback Greeks for ATM option."""
        greeks = _fallback_greeks(
            spot_price=19000,
            strike=19000,  # ATM
            option_type='CE'
        )
        
        # ATM should have moderate delta and higher gamma
        assert 0.4 <= greeks['delta'] <= 0.6
        assert greeks['gamma'] > 0.015
