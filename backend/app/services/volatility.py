"""Volatility indicators for Trading System v2.0"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple


def calculate_iv_percentile(
    current_iv: float,
    historical_iv: pd.Series,
    lookback_days: int = 252
) -> float:
    """
    Calculate IV percentile rank over historical period.
    
    Args:
        current_iv: Current implied volatility
        historical_iv: Historical IV series
        lookback_days: Lookback period in trading days
        
    Returns:
        IV percentile (0-100)
    """
    if len(historical_iv) < lookback_days:
        lookback_days = len(historical_iv)
    
    if lookback_days == 0:
        return 50.0  # Default to middle if no history
    
    recent_iv = historical_iv.tail(lookback_days)
    percentile = (recent_iv < current_iv).sum() / len(recent_iv) * 100
    
    return percentile


def calculate_realized_vol(
    close: pd.Series,
    period: int = 20,
    annualize: bool = True,
    trading_days: int = 252
) -> pd.Series:
    """
    Calculate realized (historical) volatility.
    
    Args:
        close: Close prices
        period: Lookback period
        annualize: Whether to annualize the result
        trading_days: Trading days per year for annualization
        
    Returns:
        Realized volatility series
    """
    log_returns = np.log(close / close.shift(1))
    rv = log_returns.rolling(window=period).std()
    
    if annualize:
        rv = rv * np.sqrt(trading_days)
    
    return rv


def calculate_rv_atr_ratio(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    Calculate ratio of Realized Volatility to ATR.
    High ratio may indicate trending conditions.
    
    Args:
        close: Close prices
        high: High prices
        low: Low prices
        period: Calculation period
        
    Returns:
        RV/ATR ratio
    """
    from .technical import calculate_atr
    
    rv = calculate_realized_vol(close, period, annualize=False)
    atr = calculate_atr(high, low, close, period)
    
    # Normalize ATR to percentage terms
    atr_pct = atr / close
    
    # Avoid division by zero
    ratio = rv / atr_pct.replace(0, np.nan)
    
    return ratio


def calculate_skew(
    call_iv: float,
    put_iv: float,
    atm_iv: Optional[float] = None
) -> float:
    """
    Calculate put-call skew.
    
    Args:
        call_iv: OTM call implied volatility
        put_iv: OTM put implied volatility
        atm_iv: ATM implied volatility (optional)
        
    Returns:
        Skew value (positive = put skew, negative = call skew)
    """
    if atm_iv:
        # Normalized skew
        return (put_iv - call_iv) / atm_iv
    else:
        # Simple difference
        return put_iv - call_iv


def calculate_term_structure(
    near_iv: float,
    far_iv: float
) -> float:
    """
    Calculate IV term structure slope.
    
    Args:
        near_iv: Near-term expiry IV
        far_iv: Far-term expiry IV
        
    Returns:
        Term structure ratio (>1 = contango, <1 = backwardation)
    """
    if near_iv == 0:
        return 1.0
    return far_iv / near_iv


def calculate_vix_percentile(
    current_vix: float,
    historical_vix: pd.Series,
    lookback_days: int = 252
) -> float:
    """
    Calculate VIX percentile rank.
    
    Args:
        current_vix: Current VIX value
        historical_vix: Historical VIX series
        lookback_days: Lookback period
        
    Returns:
        VIX percentile (0-100)
    """
    return calculate_iv_percentile(current_vix, historical_vix, lookback_days)


def calculate_correlation(
    series1: pd.Series,
    series2: pd.Series,
    period: int = 20
) -> pd.Series:
    """
    Calculate rolling correlation between two series.
    
    Args:
        series1: First price series
        series2: Second price series
        period: Rolling window
        
    Returns:
        Rolling correlation
    """
    returns1 = series1.pct_change()
    returns2 = series2.pct_change()
    
    return returns1.rolling(window=period).corr(returns2)


def calculate_correlation_matrix(
    price_dict: dict[str, pd.Series],
    period: int = 20
) -> pd.DataFrame:
    """
    Calculate correlation matrix for multiple assets.
    
    Args:
        price_dict: Dictionary of symbol -> price series
        period: Rolling window for correlation
        
    Returns:
        Correlation matrix DataFrame
    """
    returns_df = pd.DataFrame({
        symbol: prices.pct_change()
        for symbol, prices in price_dict.items()
    })
    
    return returns_df.tail(period).corr()


def detect_correlation_spike(
    correlations: pd.Series,
    threshold: float = 0.5,
    lookback: int = 5
) -> bool:
    """
    Detect sudden correlation spike (potential chaos signal).
    
    Args:
        correlations: Rolling correlation series
        threshold: Absolute correlation threshold
        lookback: Number of periods to check
        
    Returns:
        True if correlation spike detected
    """
    recent = correlations.tail(lookback)
    return (abs(recent) > threshold).any()


def calculate_parkinson_vol(
    high: pd.Series,
    low: pd.Series,
    period: int = 20,
    annualize: bool = True,
    trading_days: int = 252
) -> pd.Series:
    """
    Calculate Parkinson volatility estimator (uses high-low range).
    More efficient than close-to-close volatility.
    
    Args:
        high: High prices
        low: Low prices
        period: Lookback period
        annualize: Whether to annualize
        trading_days: Trading days per year
        
    Returns:
        Parkinson volatility
    """
    log_hl = np.log(high / low)
    factor = 1 / (4 * np.log(2))
    
    vol = np.sqrt(factor * (log_hl ** 2).rolling(window=period).mean())
    
    if annualize:
        vol = vol * np.sqrt(trading_days)
    
    return vol


def calculate_garman_klass_vol(
    open_prices: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 20,
    annualize: bool = True,
    trading_days: int = 252
) -> pd.Series:
    """
    Calculate Garman-Klass volatility estimator.
    Uses OHLC data for more efficient estimation.
    
    Args:
        open_prices: Open prices
        high: High prices
        low: Low prices
        close: Close prices
        period: Lookback period
        annualize: Whether to annualize
        trading_days: Trading days per year
        
    Returns:
        Garman-Klass volatility
    """
    log_hl = np.log(high / low)
    log_co = np.log(close / open_prices)
    
    term1 = 0.5 * (log_hl ** 2)
    term2 = (2 * np.log(2) - 1) * (log_co ** 2)
    
    vol = np.sqrt((term1 - term2).rolling(window=period).mean())
    
    if annualize:
        vol = vol * np.sqrt(trading_days)
    
    return vol
