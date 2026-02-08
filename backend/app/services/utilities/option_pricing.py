"""Black-Scholes option pricing for realistic P&L calculations in backtests."""

import math
from datetime import datetime, date
from typing import Optional, Tuple
from scipy.stats import norm


class BlackScholesCalculator:
    """Black-Scholes option pricing model for European options."""
    
    # Risk-free rate (approximate for India)
    DEFAULT_RISK_FREE_RATE = 0.062  # 6.2% per annum
    
    @staticmethod
    def calculate_days_to_expiry(expiry_date: date, current_date: date) -> float:
        """Calculate days to expiry (use 1/252 year fraction for trading days)."""
        days = (expiry_date - current_date).days
        return max(days / 252.0, 0.001)  # Minimum 1 day / 252
    
    @staticmethod
    def call_price(
        underlying: float,
        strike: float,
        ttm: float,  # Time to maturity in years
        volatility: float,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        dividend_yield: float = 0.0
    ) -> float:
        """
        Calculate Black-Scholes call option price.
        
        Args:
            underlying: Current underlying price
            strike: Strike price
            ttm: Time to maturity in years
            volatility: Annualized volatility (as decimal, e.g., 0.20 for 20%)
            risk_free_rate: Risk-free rate (default 6.2%)
            dividend_yield: Dividend yield (default 0%)
            
        Returns:
            Call option price
        """
        if ttm <= 0:
            # At/past expiry, use intrinsic value
            return max(underlying - strike, 0)
        
        # Prevent division by zero with very small volatility
        if volatility < 0.001:
            volatility = 0.001
        
        d1 = (
            math.log(underlying / strike) +
            (risk_free_rate - dividend_yield + 0.5 * volatility ** 2) * ttm
        ) / (volatility * math.sqrt(ttm))
        
        d2 = d1 - volatility * math.sqrt(ttm)
        
        call = (
            underlying * math.exp(-dividend_yield * ttm) * norm.cdf(d1) -
            strike * math.exp(-risk_free_rate * ttm) * norm.cdf(d2)
        )
        
        return max(call, 0)  # Call price can't be negative
    
    @staticmethod
    def put_price(
        underlying: float,
        strike: float,
        ttm: float,
        volatility: float,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        dividend_yield: float = 0.0
    ) -> float:
        """
        Calculate Black-Scholes put option price.
        
        Args:
            underlying: Current underlying price
            strike: Strike price
            ttm: Time to maturity in years
            volatility: Annualized volatility
            risk_free_rate: Risk-free rate (default 6.2%)
            dividend_yield: Dividend yield (default 0%)
            
        Returns:
            Put option price
        """
        if ttm <= 0:
            # At/past expiry, use intrinsic value
            return max(strike - underlying, 0)
        
        # Prevent division by zero with very small volatility
        if volatility < 0.001:
            volatility = 0.001
        
        d1 = (
            math.log(underlying / strike) +
            (risk_free_rate - dividend_yield + 0.5 * volatility ** 2) * ttm
        ) / (volatility * math.sqrt(ttm))
        
        d2 = d1 - volatility * math.sqrt(ttm)
        
        put = (
            strike * math.exp(-risk_free_rate * ttm) * norm.cdf(-d2) -
            underlying * math.exp(-dividend_yield * ttm) * norm.cdf(-d1)
        )
        
        return max(put, 0)  # Put price can't be negative
    
    @staticmethod
    def option_price(
        option_type: str,
        underlying: float,
        strike: float,
        ttm: float,
        volatility: float,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        dividend_yield: float = 0.0
    ) -> float:
        """
        Calculate option price based on type (CALL or PUT).
        
        Args:
            option_type: 'CE' or 'PE' (Call or Put)
            underlying: Current underlying price
            strike: Strike price
            ttm: Time to maturity in years
            volatility: Annualized volatility
            risk_free_rate: Risk-free rate
            dividend_yield: Dividend yield
            
        Returns:
            Option price
        """
        option_type = option_type.upper()
        if option_type in ['CE', 'CALL']:
            return BlackScholesCalculator.call_price(
                underlying, strike, ttm, volatility, risk_free_rate, dividend_yield
            )
        elif option_type in ['PE', 'PUT']:
            return BlackScholesCalculator.put_price(
                underlying, strike, ttm, volatility, risk_free_rate, dividend_yield
            )
        else:
            raise ValueError(f"Invalid option type: {option_type}")
    
    @staticmethod
    def calculate_greeks(
        option_type: str,
        underlying: float,
        strike: float,
        ttm: float,
        volatility: float,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        dividend_yield: float = 0.0
    ) -> dict:
        """
        Calculate option Greeks (Delta, Gamma, Theta, Vega).
        
        Args:
            option_type: 'CE', 'PE', 'CALL', or 'PUT'
            underlying: Current underlying price
            strike: Strike price
            ttm: Time to maturity in years
            volatility: Annualized volatility
            risk_free_rate: Risk-free rate
            dividend_yield: Dividend yield
            
        Returns:
            Dictionary with delta, gamma, theta, vega
        """
        option_type = option_type.upper()
        
        if ttm <= 0:
            # At/past expiry
            if option_type in ['CE', 'CALL']:
                return {"delta": 1.0 if underlying > strike else 0.0, "gamma": 0, "theta": 0, "vega": 0}
            else:
                return {"delta": -1.0 if underlying < strike else 0.0, "gamma": 0, "theta": 0, "vega": 0}
        
        if volatility < 0.001:
            volatility = 0.001
        
        d1 = (
            math.log(underlying / strike) +
            (risk_free_rate - dividend_yield + 0.5 * volatility ** 2) * ttm
        ) / (volatility * math.sqrt(ttm))
        
        d2 = d1 - volatility * math.sqrt(ttm)
        
        # Delta
        if option_type in ['CE', 'CALL']:
            delta = math.exp(-dividend_yield * ttm) * norm.cdf(d1)
        else:  # PUT
            delta = -math.exp(-dividend_yield * ttm) * norm.cdf(-d1)
        
        # Gamma (same for calls and puts)
        gamma = (
            math.exp(-dividend_yield * ttm) * norm.pdf(d1) /
            (underlying * volatility * math.sqrt(ttm))
        )
        
        # Vega (per 1% change in volatility, same for calls and puts)
        vega = (
            underlying * math.exp(-dividend_yield * ttm) * 
            norm.pdf(d1) * math.sqrt(ttm) / 100
        )
        
        # Theta (per day)
        if option_type in ['CE', 'CALL']:
            theta = (
                -underlying * math.exp(-dividend_yield * ttm) * norm.pdf(d1) * volatility / (2 * math.sqrt(ttm)) -
                risk_free_rate * strike * math.exp(-risk_free_rate * ttm) * norm.cdf(d2) +
                dividend_yield * underlying * math.exp(-dividend_yield * ttm) * norm.cdf(d1)
            ) / 252
        else:  # PUT
            theta = (
                -underlying * math.exp(-dividend_yield * ttm) * norm.pdf(d1) * volatility / (2 * math.sqrt(ttm)) +
                risk_free_rate * strike * math.exp(-risk_free_rate * ttm) * norm.cdf(-d2) -
                dividend_yield * underlying * math.exp(-dividend_yield * ttm) * norm.cdf(-d1)
            ) / 252
        
        return {
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "vega": vega
        }


class HistoricalVolatility:
    """Calculate historical volatility from price data."""
    
    @staticmethod
    def calculate_volatility(
        prices: list,
        periods: int = 20  # 20-day historical volatility
    ) -> float:
        """
        Calculate annualized historical volatility from price series.
        
        Args:
            prices: List of prices in chronological order
            periods: Number of periods for lookback (default 20)
            
        Returns:
            Annualized volatility (as decimal)
        """
        if len(prices) < periods + 1:
            return 0.20  # Default to 20% if insufficient data
        
        # Calculate log returns
        returns = []
        for i in range(len(prices) - periods, len(prices)):
            if i > 0 and prices[i] > 0 and prices[i - 1] > 0:
                ret = math.log(prices[i] / prices[i - 1])
                returns.append(ret)
        
        if not returns:
            return 0.20
        
        # Calculate standard deviation of returns
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)
        
        # Annualize (252 trading days per year)
        annualized_vol = std_dev * math.sqrt(252)
        
        # Reasonable bounds
        return max(0.05, min(annualized_vol, 2.0))  # Between 5% and 200%


class OptionPricingEngine:
    """Complete option pricing engine for backtest trades."""
    
    def __init__(self, risk_free_rate: float = 0.062, dividend_yield: float = 0.0):
        """
        Initialize pricing engine.
        
        Args:
            risk_free_rate: Annual risk-free rate (default 6.2%)
            dividend_yield: Annual dividend yield (default 0%)
        """
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield
        self.bs = BlackScholesCalculator()
        self.hv = HistoricalVolatility()
    
    def get_option_price_at_time(
        self,
        option_type: str,
        underlying_price: float,
        strike: float,
        expiry_date: date,
        current_date: date,
        volatility: Optional[float] = None,
        price_history: Optional[list] = None
    ) -> float:
        """
        Get option price at a specific point in time.
        
        Args:
            option_type: 'CE', 'PE', 'CALL', or 'PUT'
            underlying_price: Current underlying price
            strike: Strike price
            expiry_date: Option expiry date
            current_date: Current date for TTM calculation
            volatility: Optional fixed volatility (if None, calculated from history)
            price_history: Optional list of prices for volatility calculation
            
        Returns:
            Option price
        """
        ttm = self.bs.calculate_days_to_expiry(expiry_date, current_date)
        
        # Use provided volatility or calculate from history
        if volatility is None:
            if price_history:
                volatility = self.hv.calculate_volatility(price_history)
            else:
                volatility = 0.20  # Default 20% IV
        
        return self.bs.option_price(
            option_type,
            underlying_price,
            strike,
            ttm,
            volatility,
            self.risk_free_rate,
            self.dividend_yield
        )
    
    def calculate_leg_pnl(
        self,
        leg_type: str,  # 'SHORT_CALL', 'LONG_CALL', 'SHORT_PUT', 'LONG_PUT'
        strike: float,
        expiry_date: date,
        entry_date: date,
        exit_date: date,
        entry_underlying: float,
        exit_underlying: float,
        quantity: int,
        entry_volatility: Optional[float] = None,
        exit_volatility: Optional[float] = None,
        entry_price_history: Optional[list] = None,
        exit_price_history: Optional[list] = None
    ) -> Tuple[float, float, float]:
        """
        Calculate P&L for a single option leg.
        
        Args:
            leg_type: Type of leg (LONG_CALL, SHORT_CALL, LONG_PUT, SHORT_PUT)
            strike: Strike price
            expiry_date: Option expiry date
            entry_date: Trade entry date
            exit_date: Trade exit date
            entry_underlying: Underlying price at entry
            exit_underlying: Underlying price at exit
            quantity: Number of contracts
            entry_volatility: Volatility at entry (optional)
            exit_volatility: Volatility at exit (optional)
            entry_price_history: Price history for entry IV calculation
            exit_price_history: Price history for exit IV calculation
            
        Returns:
            Tuple of (entry_price, exit_price, pnl)
        """
        # Determine option type from leg type
        option_type = 'CALL' if 'CALL' in leg_type else 'PUT'
        is_long = 'LONG' in leg_type
        
        # Calculate option prices using Black-Scholes
        entry_price = self.get_option_price_at_time(
            option_type,
            entry_underlying,
            strike,
            expiry_date,
            entry_date,
            entry_volatility,
            entry_price_history
        )
        
        exit_price = self.get_option_price_at_time(
            option_type,
            exit_underlying,
            strike,
            expiry_date,
            exit_date,
            exit_volatility,
            exit_price_history
        )
        
        # Calculate P&L based on long/short
        price_diff = exit_price - entry_price
        if is_long:
            pnl = price_diff * quantity
        else:  # SHORT
            pnl = -price_diff * quantity  # Short position gains when price falls
        
        return entry_price, exit_price, pnl
