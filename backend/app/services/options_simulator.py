"""
Options Price Simulator for Backtesting

Since historical options data is not available from Kite API for expired contracts,
this module generates synthetic options prices using Black-Scholes model.

This allows backtesting of options strategies using:
1. Historical underlying price (OHLCV)
2. Historical/estimated IV (from VIX or Parkinson volatility)
3. Black-Scholes pricing model

For accurate backtesting, we simulate:
- Strike prices at various deltas (10, 15, 20, 25, 30, 40, 50 delta)
- Both calls and puts
- Greeks (delta, gamma, theta, vega)
- Bid-ask spread simulation
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from loguru import logger


@dataclass
class OptionQuote:
    """Simulated option quote."""
    strike: float
    expiry: date
    option_type: str  # CE or PE
    underlying_price: float
    
    # Prices
    theoretical_price: float
    bid: float
    ask: float
    mid: float
    
    # Greeks
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float
    
    # Metadata
    dte: int  # Days to expiry
    moneyness: float  # strike / spot
    
    @property
    def is_itm(self) -> bool:
        if self.option_type == "CE":
            return self.underlying_price > self.strike
        return self.underlying_price < self.strike
    
    @property
    def is_otm(self) -> bool:
        return not self.is_itm


class BlackScholes:
    """Black-Scholes option pricing model."""
    
    @staticmethod
    def d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate d1 parameter."""
        if T <= 0 or sigma <= 0:
            return 0.0
        return (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    
    @staticmethod
    def d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate d2 parameter."""
        if T <= 0 or sigma <= 0:
            return 0.0
        return BlackScholes.d1(S, K, T, r, sigma) - sigma * np.sqrt(T)
    
    @staticmethod
    def call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate call option price."""
        if T <= 0:
            return max(0, S - K)
        d1 = BlackScholes.d1(S, K, T, r, sigma)
        d2 = BlackScholes.d2(S, K, T, r, sigma)
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    
    @staticmethod
    def put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate put option price."""
        if T <= 0:
            return max(0, K - S)
        d1 = BlackScholes.d1(S, K, T, r, sigma)
        d2 = BlackScholes.d2(S, K, T, r, sigma)
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    
    @staticmethod
    def call_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate call delta."""
        if T <= 0:
            return 1.0 if S > K else 0.0
        return norm.cdf(BlackScholes.d1(S, K, T, r, sigma))
    
    @staticmethod
    def put_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate put delta."""
        if T <= 0:
            return -1.0 if S < K else 0.0
        return norm.cdf(BlackScholes.d1(S, K, T, r, sigma)) - 1
    
    @staticmethod
    def gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate gamma (same for calls and puts)."""
        if T <= 0 or sigma <= 0:
            return 0.0
        d1 = BlackScholes.d1(S, K, T, r, sigma)
        return norm.pdf(d1) / (S * sigma * np.sqrt(T))
    
    @staticmethod
    def vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate vega (same for calls and puts)."""
        if T <= 0:
            return 0.0
        d1 = BlackScholes.d1(S, K, T, r, sigma)
        return S * norm.pdf(d1) * np.sqrt(T) / 100  # Per 1% IV change
    
    @staticmethod
    def call_theta(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate call theta (per day)."""
        if T <= 0:
            return 0.0
        d1 = BlackScholes.d1(S, K, T, r, sigma)
        d2 = BlackScholes.d2(S, K, T, r, sigma)
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) 
                 - r * K * np.exp(-r * T) * norm.cdf(d2))
        return theta / 365  # Per day
    
    @staticmethod
    def put_theta(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate put theta (per day)."""
        if T <= 0:
            return 0.0
        d1 = BlackScholes.d1(S, K, T, r, sigma)
        d2 = BlackScholes.d2(S, K, T, r, sigma)
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) 
                 + r * K * np.exp(-r * T) * norm.cdf(-d2))
        return theta / 365  # Per day


class OptionsSimulator:
    """
    Simulates options chain data for backtesting.
    
    Uses underlying OHLCV data + estimated IV to generate realistic
    options prices and Greeks.
    """
    
    def __init__(
        self,
        risk_free_rate: float = 0.065,  # ~6.5% India risk-free rate
        lot_size: int = 50,  # NIFTY lot size
        strike_interval: int = 50,  # NIFTY strike interval
        bid_ask_spread_pct: float = 0.005,  # 0.5% spread
    ):
        self.risk_free_rate = risk_free_rate
        self.lot_size = lot_size
        self.strike_interval = strike_interval
        self.bid_ask_spread_pct = bid_ask_spread_pct
        self.bs = BlackScholes()
    
    def find_strike_by_delta(
        self,
        spot: float,
        target_delta: float,
        expiry: date,
        current_date: date,
        iv: float,
        option_type: str = "CE"
    ) -> float:
        """
        Find the strike price that gives approximately the target delta.
        
        Args:
            spot: Current underlying price
            target_delta: Target delta (0-1 for calls, -1 to 0 for puts)
            expiry: Option expiry date
            current_date: Current date
            iv: Implied volatility (annualized, e.g., 0.15 for 15%)
            option_type: "CE" for call, "PE" for put
        
        Returns:
            Strike price rounded to strike_interval
        """
        dte = (expiry - current_date).days
        T = max(dte / 365, 1/365)  # Minimum 1 day
        
        # Binary search for strike
        if option_type == "CE":
            # For calls, higher strike = lower delta
            low_strike = spot * 0.85
            high_strike = spot * 1.15
            target = abs(target_delta)
            
            for _ in range(50):
                mid_strike = (low_strike + high_strike) / 2
                delta = self.bs.call_delta(spot, mid_strike, T, self.risk_free_rate, iv)
                
                if abs(delta - target) < 0.001:
                    break
                
                if delta > target:
                    low_strike = mid_strike
                else:
                    high_strike = mid_strike
            
            strike = mid_strike
        else:
            # For puts, lower strike = more negative delta
            low_strike = spot * 0.85
            high_strike = spot * 1.15
            target = -abs(target_delta)
            
            for _ in range(50):
                mid_strike = (low_strike + high_strike) / 2
                delta = self.bs.put_delta(spot, mid_strike, T, self.risk_free_rate, iv)
                
                if abs(delta - target) < 0.001:
                    break
                
                if delta < target:
                    low_strike = mid_strike
                else:
                    high_strike = mid_strike
            
            strike = mid_strike
        
        # Round to strike interval
        return round(strike / self.strike_interval) * self.strike_interval
    
    def get_option_quote(
        self,
        spot: float,
        strike: float,
        expiry: date,
        current_date: date,
        iv: float,
        option_type: str = "CE"
    ) -> OptionQuote:
        """
        Generate a simulated option quote.
        
        Args:
            spot: Current underlying price
            strike: Strike price
            expiry: Option expiry date
            current_date: Current date
            iv: Implied volatility (annualized)
            option_type: "CE" for call, "PE" for put
        
        Returns:
            OptionQuote with price and Greeks
        """
        dte = (expiry - current_date).days
        T = max(dte / 365, 1/365)
        
        # Calculate price
        if option_type == "CE":
            price = self.bs.call_price(spot, strike, T, self.risk_free_rate, iv)
            delta = self.bs.call_delta(spot, strike, T, self.risk_free_rate, iv)
            theta = self.bs.call_theta(spot, strike, T, self.risk_free_rate, iv)
        else:
            price = self.bs.put_price(spot, strike, T, self.risk_free_rate, iv)
            delta = self.bs.put_delta(spot, strike, T, self.risk_free_rate, iv)
            theta = self.bs.put_theta(spot, strike, T, self.risk_free_rate, iv)
        
        gamma = self.bs.gamma(spot, strike, T, self.risk_free_rate, iv)
        vega = self.bs.vega(spot, strike, T, self.risk_free_rate, iv)
        
        # Simulate bid-ask spread (wider for OTM, narrower for ATM)
        moneyness = strike / spot
        spread_multiplier = 1 + abs(1 - moneyness) * 2  # Wider spread for OTM
        spread = price * self.bid_ask_spread_pct * spread_multiplier
        spread = max(spread, 0.5)  # Minimum 0.5 INR spread
        
        bid = max(0.05, price - spread / 2)
        ask = price + spread / 2
        mid = (bid + ask) / 2
        
        return OptionQuote(
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            underlying_price=spot,
            theoretical_price=price,
            bid=bid,
            ask=ask,
            mid=mid,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            iv=iv,
            dte=dte,
            moneyness=moneyness
        )
    
    def get_options_chain(
        self,
        spot: float,
        expiry: date,
        current_date: date,
        iv: float,
        delta_range: List[float] = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
    ) -> Dict[str, List[OptionQuote]]:
        """
        Generate a full options chain at various delta levels.
        
        Args:
            spot: Current underlying price
            expiry: Option expiry date
            current_date: Current date
            iv: Implied volatility
            delta_range: List of delta values to generate strikes for
        
        Returns:
            Dict with 'calls' and 'puts' lists of OptionQuote
        """
        calls = []
        puts = []
        
        for target_delta in delta_range:
            # Call at this delta
            call_strike = self.find_strike_by_delta(
                spot, target_delta, expiry, current_date, iv, "CE"
            )
            calls.append(self.get_option_quote(
                spot, call_strike, expiry, current_date, iv, "CE"
            ))
            
            # Put at this delta
            put_strike = self.find_strike_by_delta(
                spot, target_delta, expiry, current_date, iv, "PE"
            )
            puts.append(self.get_option_quote(
                spot, put_strike, expiry, current_date, iv, "PE"
            ))
        
        return {"calls": calls, "puts": puts}
    
    def simulate_options_data(
        self,
        underlying_data: pd.DataFrame,
        iv_data: Optional[pd.DataFrame] = None,
        expiry_dte: int = 7,  # Weekly expiry
        delta_levels: List[float] = [0.10, 0.15, 0.20, 0.25, 0.30]
    ) -> pd.DataFrame:
        """
        Generate simulated options data from underlying OHLCV.
        
        Args:
            underlying_data: DataFrame with OHLCV data (must have 'close' column)
            iv_data: Optional DataFrame with IV data (uses Parkinson vol if not provided)
            expiry_dte: Days to expiry for simulated options
            delta_levels: Delta levels to simulate
        
        Returns:
            DataFrame with options chain data for each timestamp
        """
        if underlying_data.empty:
            return pd.DataFrame()
        
        # Estimate IV if not provided
        if iv_data is None:
            # Use Parkinson volatility as IV proxy
            log_hl = np.log(underlying_data['high'] / underlying_data['low'])
            parkinson_vol = np.sqrt(1 / (4 * np.log(2)) * (log_hl ** 2))
            iv_series = parkinson_vol.rolling(20).mean() * np.sqrt(252)  # Annualize
            iv_series = iv_series.fillna(0.15)  # Default 15% IV
        else:
            iv_series = iv_data['iv'] if 'iv' in iv_data.columns else iv_data.iloc[:, 0]
        
        records = []
        
        for idx in range(len(underlying_data)):
            row = underlying_data.iloc[idx]
            spot = row['close']
            
            # Get date
            if hasattr(underlying_data.index, 'date'):
                current_date = underlying_data.index[idx].date()
            else:
                current_date = date.today()
            
            # Calculate expiry (next Thursday for NIFTY weekly)
            days_until_thursday = (3 - current_date.weekday()) % 7
            if days_until_thursday == 0:
                days_until_thursday = 7
            expiry = current_date + timedelta(days=max(days_until_thursday, expiry_dte))
            
            # Get IV
            iv = iv_series.iloc[idx] if idx < len(iv_series) else 0.15
            iv = max(0.05, min(1.0, iv))  # Clamp between 5% and 100%
            
            # Generate options chain
            chain = self.get_options_chain(
                spot, expiry, current_date, iv, delta_levels
            )
            
            # Record each option
            timestamp = underlying_data.index[idx]
            
            for call in chain['calls']:
                records.append({
                    'timestamp': timestamp,
                    'underlying': spot,
                    'strike': call.strike,
                    'expiry': call.expiry,
                    'option_type': 'CE',
                    'price': call.mid,
                    'bid': call.bid,
                    'ask': call.ask,
                    'delta': call.delta,
                    'gamma': call.gamma,
                    'theta': call.theta,
                    'vega': call.vega,
                    'iv': call.iv,
                    'dte': call.dte
                })
            
            for put in chain['puts']:
                records.append({
                    'timestamp': timestamp,
                    'underlying': spot,
                    'strike': put.strike,
                    'expiry': put.expiry,
                    'option_type': 'PE',
                    'price': put.mid,
                    'bid': put.bid,
                    'ask': put.ask,
                    'delta': put.delta,
                    'gamma': put.gamma,
                    'theta': put.theta,
                    'vega': put.vega,
                    'iv': put.iv,
                    'dte': put.dte
                })
        
        return pd.DataFrame(records)


def get_weekly_expiry(current_date: date, weeks_ahead: int = 0) -> date:
    """Get NIFTY weekly expiry date (Thursday)."""
    days_until_thursday = (3 - current_date.weekday()) % 7
    if days_until_thursday == 0 and weeks_ahead == 0:
        return current_date
    expiry = current_date + timedelta(days=days_until_thursday + (weeks_ahead * 7))
    return expiry


def get_monthly_expiry(current_date: date) -> date:
    """Get NIFTY monthly expiry date (last Thursday of month)."""
    # Find last day of month
    if current_date.month == 12:
        next_month = date(current_date.year + 1, 1, 1)
    else:
        next_month = date(current_date.year, current_date.month + 1, 1)
    last_day = next_month - timedelta(days=1)
    
    # Find last Thursday
    days_since_thursday = (last_day.weekday() - 3) % 7
    return last_day - timedelta(days=days_since_thursday)


# =============================================================================
# STRESS SCENARIO SIMULATOR
# =============================================================================

@dataclass
class StressScenario:
    """Definition of a market stress scenario."""
    name: str
    description: str
    iv_multiplier: float  # How much IV spikes (e.g., 2.0 = doubles)
    spread_multiplier: float  # How much bid-ask widens
    slippage_pct: float  # Additional slippage on execution
    gamma_acceleration: float  # Extra gamma effect near expiry
    probability: float  # Probability of this scenario occurring


class StressScenarios:
    """Pre-defined stress scenarios based on historical market events."""
    
    # Normal market conditions
    NORMAL = StressScenario(
        name="NORMAL",
        description="Normal market conditions",
        iv_multiplier=1.0,
        spread_multiplier=1.0,
        slippage_pct=0.001,
        gamma_acceleration=1.0,
        probability=0.85
    )
    
    # Moderate stress (earnings, RBI policy, etc.)
    MODERATE_STRESS = StressScenario(
        name="MODERATE_STRESS",
        description="Event day - earnings, policy announcements",
        iv_multiplier=1.3,
        spread_multiplier=2.0,
        slippage_pct=0.005,
        gamma_acceleration=1.5,
        probability=0.10
    )
    
    # High stress (budget day, election results)
    HIGH_STRESS = StressScenario(
        name="HIGH_STRESS",
        description="Major event - budget, elections, global crisis",
        iv_multiplier=1.8,
        spread_multiplier=4.0,
        slippage_pct=0.015,
        gamma_acceleration=2.5,
        probability=0.04
    )
    
    # Extreme stress (flash crash, circuit breaker)
    EXTREME_STRESS = StressScenario(
        name="EXTREME_STRESS",
        description="Flash crash, circuit breaker, black swan",
        iv_multiplier=3.0,
        spread_multiplier=10.0,
        slippage_pct=0.05,
        gamma_acceleration=5.0,
        probability=0.01
    )
    
    # Expiry day gamma blast (last 2 hours of expiry)
    EXPIRY_GAMMA_BLAST = StressScenario(
        name="EXPIRY_GAMMA_BLAST",
        description="Expiry day last 2 hours - gamma explosion",
        iv_multiplier=0.5,  # IV actually drops but gamma explodes
        spread_multiplier=3.0,
        slippage_pct=0.02,
        gamma_acceleration=10.0,  # Gamma goes crazy
        probability=1.0  # Always happens on expiry
    )
    
    @classmethod
    def all_scenarios(cls) -> List[StressScenario]:
        return [cls.NORMAL, cls.MODERATE_STRESS, cls.HIGH_STRESS, 
                cls.EXTREME_STRESS, cls.EXPIRY_GAMMA_BLAST]
    
    @classmethod
    def sample_scenario(cls, is_expiry_day: bool = False, 
                        hours_to_expiry: float = 24) -> StressScenario:
        """Sample a stress scenario based on probabilities."""
        # Expiry day special handling
        if is_expiry_day and hours_to_expiry <= 2:
            return cls.EXPIRY_GAMMA_BLAST
        
        # Random sampling based on probabilities
        r = np.random.random()
        cumulative = 0
        for scenario in [cls.EXTREME_STRESS, cls.HIGH_STRESS, 
                         cls.MODERATE_STRESS, cls.NORMAL]:
            cumulative += scenario.probability
            if r < cumulative:
                return scenario
        return cls.NORMAL


class StressAwareOptionsSimulator(OptionsSimulator):
    """
    Options simulator with stress scenario modeling.
    
    Adds realistic market stress effects:
    - IV spikes during events
    - Bid-ask spread blowouts
    - Execution slippage
    - Gamma acceleration near expiry
    - Liquidity gaps
    """
    
    def __init__(
        self,
        risk_free_rate: float = 0.065,
        lot_size: int = 50,
        strike_interval: int = 50,
        bid_ask_spread_pct: float = 0.005,
        stress_mode: str = "conservative"  # "realistic", "conservative", "worst_case"
    ):
        super().__init__(risk_free_rate, lot_size, strike_interval, bid_ask_spread_pct)
        self.stress_mode = stress_mode
        
        # Stress multipliers based on mode
        self.stress_multipliers = {
            "realistic": 1.0,
            "conservative": 1.5,
            "worst_case": 2.5
        }
    
    def get_stress_adjusted_quote(
        self,
        spot: float,
        strike: float,
        expiry: date,
        current_datetime: datetime,
        base_iv: float,
        option_type: str = "CE",
        scenario: Optional[StressScenario] = None
    ) -> OptionQuote:
        """
        Generate option quote with stress adjustments.
        """
        current_date = current_datetime.date()
        dte = (expiry - current_date).days
        hours_to_expiry = dte * 24 + (15.5 - current_datetime.hour)  # Market closes 3:30 PM
        
        # Determine scenario if not provided
        if scenario is None:
            is_expiry_day = (expiry == current_date)
            scenario = StressScenarios.sample_scenario(is_expiry_day, hours_to_expiry)
        
        # Apply stress multiplier based on mode
        mode_mult = self.stress_multipliers.get(self.stress_mode, 1.0)
        
        # Adjust IV
        stressed_iv = base_iv * scenario.iv_multiplier
        stressed_iv = max(0.05, min(2.0, stressed_iv))  # Clamp 5% to 200%
        
        # Get base quote
        T = max(dte / 365, 1/365)
        
        if option_type == "CE":
            price = self.bs.call_price(spot, strike, T, self.risk_free_rate, stressed_iv)
            delta = self.bs.call_delta(spot, strike, T, self.risk_free_rate, stressed_iv)
            theta = self.bs.call_theta(spot, strike, T, self.risk_free_rate, stressed_iv)
        else:
            price = self.bs.put_price(spot, strike, T, self.risk_free_rate, stressed_iv)
            delta = self.bs.put_delta(spot, strike, T, self.risk_free_rate, stressed_iv)
            theta = self.bs.put_theta(spot, strike, T, self.risk_free_rate, stressed_iv)
        
        # Gamma with acceleration
        base_gamma = self.bs.gamma(spot, strike, T, self.risk_free_rate, stressed_iv)
        stressed_gamma = base_gamma * scenario.gamma_acceleration * mode_mult
        
        vega = self.bs.vega(spot, strike, T, self.risk_free_rate, stressed_iv)
        
        # Stressed bid-ask spread
        moneyness = strike / spot
        otm_factor = 1 + abs(1 - moneyness) * 3  # More OTM = wider spread
        
        base_spread = price * self.bid_ask_spread_pct * otm_factor
        stressed_spread = base_spread * scenario.spread_multiplier * mode_mult
        stressed_spread = max(stressed_spread, 1.0)  # Minimum 1 INR spread
        
        # Near expiry spread explosion
        if hours_to_expiry < 4:
            stressed_spread *= (1 + (4 - hours_to_expiry) * 0.5)
        
        bid = max(0.05, price - stressed_spread / 2)
        ask = price + stressed_spread / 2
        
        # Add slippage to mid price (what you'd actually get)
        slippage = price * scenario.slippage_pct * mode_mult
        execution_price = price + slippage  # Assume buying, so worse price
        
        return OptionQuote(
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            underlying_price=spot,
            theoretical_price=price,
            bid=bid,
            ask=ask,
            mid=execution_price,  # Use execution price as "mid" for conservative estimate
            delta=delta,
            gamma=stressed_gamma,
            theta=theta,
            vega=vega,
            iv=stressed_iv,
            dte=dte,
            moneyness=moneyness
        )
    
    def simulate_position_pnl(
        self,
        entry_quote: OptionQuote,
        exit_spot: float,
        exit_datetime: datetime,
        exit_iv: float,
        position_size: int = 1,  # Number of lots
        is_short: bool = False
    ) -> Dict:
        """
        Simulate P&L for an options position with stress effects.
        
        Returns detailed P&L breakdown including slippage and stress impacts.
        """
        # Get exit quote with stress
        exit_quote = self.get_stress_adjusted_quote(
            spot=exit_spot,
            strike=entry_quote.strike,
            expiry=entry_quote.expiry,
            current_datetime=exit_datetime,
            base_iv=exit_iv,
            option_type=entry_quote.option_type
        )
        
        # Calculate P&L
        if is_short:
            # Short position: profit if price drops
            entry_credit = entry_quote.bid  # Sell at bid
            exit_debit = exit_quote.ask  # Buy back at ask
            pnl_per_unit = entry_credit - exit_debit
        else:
            # Long position: profit if price rises
            entry_debit = entry_quote.ask  # Buy at ask
            exit_credit = exit_quote.bid  # Sell at bid
            pnl_per_unit = exit_credit - entry_debit
        
        total_pnl = pnl_per_unit * position_size * self.lot_size
        
        # Calculate theoretical P&L (without stress)
        theoretical_pnl = (exit_quote.theoretical_price - entry_quote.theoretical_price)
        if is_short:
            theoretical_pnl = -theoretical_pnl
        theoretical_pnl *= position_size * self.lot_size
        
        # Stress impact
        stress_impact = total_pnl - theoretical_pnl
        
        return {
            "entry_price": entry_quote.ask if not is_short else entry_quote.bid,
            "exit_price": exit_quote.bid if not is_short else exit_quote.ask,
            "theoretical_entry": entry_quote.theoretical_price,
            "theoretical_exit": exit_quote.theoretical_price,
            "pnl_per_unit": pnl_per_unit,
            "total_pnl": total_pnl,
            "theoretical_pnl": theoretical_pnl,
            "stress_impact": stress_impact,
            "stress_impact_pct": (stress_impact / abs(theoretical_pnl) * 100) if theoretical_pnl != 0 else 0,
            "entry_iv": entry_quote.iv,
            "exit_iv": exit_quote.iv,
            "entry_delta": entry_quote.delta,
            "exit_delta": exit_quote.delta,
            "gamma_at_exit": exit_quote.gamma
        }
    
    def simulate_iron_condor_stress(
        self,
        spot: float,
        expiry: date,
        current_datetime: datetime,
        iv: float,
        call_sell_delta: float = 0.15,
        call_buy_delta: float = 0.05,
        put_sell_delta: float = 0.15,
        put_buy_delta: float = 0.05,
        lots: int = 1
    ) -> Dict:
        """
        Simulate Iron Condor entry with stress-adjusted pricing.
        
        Returns position details and worst-case scenarios.
        """
        current_date = current_datetime.date()
        
        # Find strikes
        call_sell_strike = self.find_strike_by_delta(spot, call_sell_delta, expiry, current_date, iv, "CE")
        call_buy_strike = self.find_strike_by_delta(spot, call_buy_delta, expiry, current_date, iv, "CE")
        put_sell_strike = self.find_strike_by_delta(spot, put_sell_delta, expiry, current_date, iv, "PE")
        put_buy_strike = self.find_strike_by_delta(spot, put_buy_delta, expiry, current_date, iv, "PE")
        
        # Get quotes for each leg
        call_sell = self.get_stress_adjusted_quote(spot, call_sell_strike, expiry, current_datetime, iv, "CE")
        call_buy = self.get_stress_adjusted_quote(spot, call_buy_strike, expiry, current_datetime, iv, "CE")
        put_sell = self.get_stress_adjusted_quote(spot, put_sell_strike, expiry, current_datetime, iv, "PE")
        put_buy = self.get_stress_adjusted_quote(spot, put_buy_strike, expiry, current_datetime, iv, "PE")
        
        # Calculate net credit (sell at bid, buy at ask)
        net_credit = (call_sell.bid + put_sell.bid - call_buy.ask - put_buy.ask)
        net_credit_per_lot = net_credit * self.lot_size
        
        # Max loss calculations
        call_spread_width = call_buy_strike - call_sell_strike
        put_spread_width = put_sell_strike - put_buy_strike
        max_loss_call = (call_spread_width - net_credit) * self.lot_size * lots
        max_loss_put = (put_spread_width - net_credit) * self.lot_size * lots
        
        # Breakeven points
        upper_breakeven = call_sell_strike + net_credit
        lower_breakeven = put_sell_strike - net_credit
        
        # Net Greeks
        net_delta = (call_sell.delta - call_buy.delta + put_sell.delta - put_buy.delta) * lots
        net_gamma = (-call_sell.gamma + call_buy.gamma - put_sell.gamma + put_buy.gamma) * lots
        net_theta = (-call_sell.theta + call_buy.theta - put_sell.theta + put_buy.theta) * lots
        net_vega = (-call_sell.vega + call_buy.vega - put_sell.vega + put_buy.vega) * lots
        
        return {
            "strategy": "Iron Condor",
            "spot": spot,
            "expiry": expiry,
            "iv": iv,
            "legs": {
                "call_sell": {"strike": call_sell_strike, "premium": call_sell.bid, "delta": call_sell.delta},
                "call_buy": {"strike": call_buy_strike, "premium": call_buy.ask, "delta": call_buy.delta},
                "put_sell": {"strike": put_sell_strike, "premium": put_sell.bid, "delta": put_sell.delta},
                "put_buy": {"strike": put_buy_strike, "premium": put_buy.ask, "delta": put_buy.delta},
            },
            "net_credit": net_credit,
            "net_credit_total": net_credit_per_lot * lots,
            "max_profit": net_credit_per_lot * lots,
            "max_loss_upside": max_loss_call,
            "max_loss_downside": max_loss_put,
            "upper_breakeven": upper_breakeven,
            "lower_breakeven": lower_breakeven,
            "profit_range": upper_breakeven - lower_breakeven,
            "profit_range_pct": (upper_breakeven - lower_breakeven) / spot * 100,
            "greeks": {
                "delta": net_delta,
                "gamma": net_gamma,
                "theta": net_theta,
                "vega": net_vega
            },
            "stress_warning": f"In {self.stress_mode} mode - actual losses may be {self.stress_multipliers[self.stress_mode]}x worse"
        }
