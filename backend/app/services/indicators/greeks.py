"""Greeks calculation using Black-Scholes model for Trading System v2.0"""

import numpy as np
from scipy.stats import norm
from typing import Dict, Optional
from datetime import date
from loguru import logger


class GreeksCalculator:
    """
    Calculate option Greeks using Black-Scholes model.
    
    Greeks calculated:
    - Delta: Rate of change of option price with respect to underlying price
    - Gamma: Rate of change of delta with respect to underlying price
    - Theta: Rate of change of option price with respect to time (per day)
    - Vega: Rate of change of option price with respect to volatility (per 1% change)
    - Rho: Rate of change of option price with respect to interest rate (less used)
    """
    
    def __init__(self, risk_free_rate: float = 0.065):
        """
        Initialize Greeks calculator.
        
        Args:
            risk_free_rate: Annual risk-free rate (default: 6.5% for India)
        """
        self.risk_free_rate = risk_free_rate
    
    def calculate_all(
        self,
        spot_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        option_type: str,
        risk_free_rate: Optional[float] = None
    ) -> Dict[str, float]:
        """
        Calculate all Greeks for an option.
        
        Args:
            spot_price: Current price of underlying
            strike: Strike price of option
            time_to_expiry: Time to expiry in years
            volatility: Implied volatility (annualized, e.g., 0.20 for 20%)
            option_type: 'CE' for call or 'PE' for put
            risk_free_rate: Override risk-free rate (optional)
            
        Returns:
            Dict with delta, gamma, theta, vega, rho
        """
        if time_to_expiry <= 0:
            return self._expired_greeks(spot_price, strike, option_type)
        
        if volatility <= 0:
            logger.warning(f"Invalid volatility: {volatility}, using default 0.20")
            volatility = 0.20
        
        r = risk_free_rate if risk_free_rate is not None else self.risk_free_rate
        
        # Calculate d1 and d2
        d1 = self._calculate_d1(spot_price, strike, time_to_expiry, volatility, r)
        d2 = d1 - volatility * np.sqrt(time_to_expiry)
        
        # Calculate Greeks
        delta = self._calculate_delta(d1, option_type)
        gamma = self._calculate_gamma(spot_price, d1, time_to_expiry, volatility)
        theta = self._calculate_theta(
            spot_price, strike, d1, d2, time_to_expiry, volatility, r, option_type
        )
        vega = self._calculate_vega(spot_price, d1, time_to_expiry)
        rho = self._calculate_rho(strike, d2, time_to_expiry, r, option_type)
        
        return {
            "delta": float(delta),
            "gamma": float(gamma),
            "theta": float(theta),
            "vega": float(vega),
            "rho": float(rho)
        }

# --- utility methods ---
    def calculate_time_to_expiry(self, expiry_date: date) -> float:
        """Calculate time to expiry in years."""
        today = date.today()
        days_to_expiry = (expiry_date - today).days

        if days_to_expiry < 0:
            return 0.0

        # Use trading days approximation (calendar days / 365)
        return days_to_expiry / 365.0

    def _calculate_d1(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float
    ) -> float:
        """Calculate d1 parameter for Black-Scholes."""
        return (
            (np.log(spot / strike) + 
             (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) /
            (volatility * np.sqrt(time_to_expiry))
        )
    
    def _calculate_delta(self, d1: float, option_type: str) -> float:
        """
        Calculate delta.
        
        Call delta: N(d1)
        Put delta: N(d1) - 1
        """
        if option_type.upper() in ['CE', 'CALL']:
            return norm.cdf(d1)
        else:  # PE, PUT
            return norm.cdf(d1) - 1
    
    def _calculate_gamma(
        self,
        spot: float,
        d1: float,
        time_to_expiry: float,
        volatility: float
    ) -> float:
        """
        Calculate gamma (same for calls and puts).
        
        Gamma = N'(d1) / (S * σ * sqrt(T))
        """
        return norm.pdf(d1) / (spot * volatility * np.sqrt(time_to_expiry))
    
    def _calculate_theta(
        self,
        spot: float,
        strike: float,
        d1: float,
        d2: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float,
        option_type: str
    ) -> float:
        """
        Calculate theta (time decay per day).
        
        Returns theta in rupees per day (divide annual by 365).
        """
        first_term = -(spot * norm.pdf(d1) * volatility) / (2 * np.sqrt(time_to_expiry))
        
        if option_type.upper() in ['CE', 'CALL']:
            second_term = -risk_free_rate * strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(d2)
            theta_annual = first_term + second_term
        else:  # PE, PUT
            second_term = risk_free_rate * strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(-d2)
            theta_annual = first_term + second_term
        
        # Convert to per-day theta
        return theta_annual / 365.0
    
    def _calculate_vega(
        self,
        spot: float,
        d1: float,
        time_to_expiry: float
    ) -> float:
        """
        Calculate vega (sensitivity to 1% change in volatility).
        
        Vega = S * N'(d1) * sqrt(T) / 100
        
        Same for calls and puts.
        Returns vega per 1% change in IV.
        """
        return (spot * norm.pdf(d1) * np.sqrt(time_to_expiry)) / 100.0
    
    def _calculate_rho(
        self,
        strike: float,
        d2: float,
        time_to_expiry: float,
        risk_free_rate: float,
        option_type: str
    ) -> float:
        """
        Calculate rho (sensitivity to 1% change in interest rate).
        
        Returns rho per 1% change in rate.
        """
        if option_type.upper() in ['CE', 'CALL']:
            return (strike * time_to_expiry * 
                    np.exp(-risk_free_rate * time_to_expiry) * 
                    norm.cdf(d2)) / 100.0
        else:  # PE, PUT
            return -(strike * time_to_expiry * 
                     np.exp(-risk_free_rate * time_to_expiry) * 
                     norm.cdf(-d2)) / 100.0
    
    def _expired_greeks(
        self,
        spot: float,
        strike: float,
        option_type: str
    ) -> Dict[str, float]:
        """Return Greeks for expired options (all zero except delta)."""
        if option_type.upper() in ['CE', 'CALL']:
            delta = 1.0 if spot > strike else 0.0
        else:
            delta = -1.0 if spot < strike else 0.0
        
        return {
            "delta": delta,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0
        }


# Backward-compatible functional wrapper
def calculate_greeks(
    spot_price: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    option_type: str,
    risk_free_rate: float = 0.065,
) -> Dict[str, float]:
    """Functional wrapper to calculate Greeks (for existing imports)."""
    calculator = GreeksCalculator(risk_free_rate=risk_free_rate)
    return calculator.calculate_all(
        spot_price=spot_price,
        strike=strike,
        time_to_expiry=time_to_expiry,
        volatility=volatility,
        option_type=option_type,
        risk_free_rate=risk_free_rate,
    )


def validate_and_calculate_greeks(
    spot_price: float,
    strike: float,
    expiry_date: date,
    volatility: float,
    option_type: str,
    chain_greeks: Optional[Dict[str, float]] = None,
    calculator: Optional[GreeksCalculator] = None
) -> Dict[str, float]:
    """
    Validate option chain Greeks or calculate them if missing/invalid.
    
    Priority:
    1. Use chain Greeks if all are present and valid
    2. Calculate using Black-Scholes if chain Greeks are missing
    3. Fallback to hardcoded defaults if calculation fails
    
    Args:
        spot_price: Current underlying price
        strike: Strike price
        expiry_date: Expiry date
        volatility: Implied volatility (0-1 scale)
        option_type: 'CE' or 'PE'
        chain_greeks: Greeks from option chain (optional)
        calculator: GreeksCalculator instance (optional, will create if needed)
        
    Returns:
        Dict with validated/calculated Greeks
    """
    if calculator is None:
        calculator = GreeksCalculator()
    
    # Try to use chain Greeks if available
    if chain_greeks and _are_greeks_valid(chain_greeks):
        logger.debug("Using Greeks from option chain")
        return chain_greeks
    
    # Calculate Greeks using Black-Scholes
    try:
        time_to_expiry = calculator.calculate_time_to_expiry(expiry_date)
        
        if time_to_expiry <= 0:
            logger.warning("Option expired, using expired Greeks")
            return calculator._expired_greeks(spot_price, strike, option_type)
        
        greeks = calculator.calculate_all(
            spot_price=spot_price,
            strike=strike,
            time_to_expiry=time_to_expiry,
            volatility=volatility,
            option_type=option_type
        )
        
        logger.debug(f"Calculated Greeks: delta={greeks['delta']:.3f}, theta={greeks['theta']:.2f}")
        return greeks
        
    except Exception as e:
        logger.error(f"Greeks calculation failed: {e}, using fallback values")
        return _fallback_greeks(spot_price, strike, option_type)


def _are_greeks_valid(greeks: Dict[str, float]) -> bool:
    """Check if Greeks from option chain are valid."""
    required = ['delta', 'gamma', 'theta', 'vega']
    
    # Check all required Greeks are present
    if not all(k in greeks for k in required):
        return False
    
    # Check values are not zero/None/NaN
    for key in required:
        value = greeks.get(key)
        if value is None or np.isnan(value):
            return False
    
    # Validate delta is in reasonable range
    delta = greeks['delta']
    if not (-1.1 <= delta <= 1.1):  # Allow small margin for numerical errors
        return False
    
    # Gamma should be positive
    gamma = greeks['gamma']
    if gamma < 0:
        return False
    
    return True


def _fallback_greeks(spot_price: float, strike: float, option_type: str) -> Dict[str, float]:
    """
    Generate fallback Greeks based on moneyness.
    
    Better than hardcoded 0.25 delta - estimates based on ITM/ATM/OTM status.
    """
    moneyness = spot_price / strike
    
    if option_type.upper() in ['CE', 'CALL']:
        # Call delta: 0.9 (deep ITM) to 0.1 (deep OTM)
        if moneyness > 1.05:  # ITM
            delta = 0.70
        elif moneyness > 0.98:  # ATM
            delta = 0.50
        else:  # OTM
            delta = 0.25
    else:  # Put
        # Put delta: -0.9 (deep ITM) to -0.1 (deep OTM)
        if moneyness < 0.95:  # ITM
            delta = -0.70
        elif moneyness < 1.02:  # ATM
            delta = -0.50
        else:  # OTM
            delta = -0.25
    
    # Gamma highest at ATM
    gamma = 0.02 if 0.98 <= moneyness <= 1.02 else 0.01
    
    # Theta approximation (negative for long positions)
    theta = -5.0 if 0.98 <= moneyness <= 1.02 else -2.0
    
    # Vega approximation
    vega = 15.0 if 0.98 <= moneyness <= 1.02 else 8.0
    
    logger.warning(f"Using fallback Greeks: delta={delta}, moneyness={moneyness:.3f}")
    
    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": 0.5
    }
