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


def calculate_rv_iv_ratio(
    close: pd.Series,
    current_iv: float,
    period: int = 20
) -> float:
    """
    Calculate Realized Volatility / Implied Volatility ratio.
    
    RV/IV < 0.8 = Vol overpriced, theta-friendly (short-vol opportunity)
    RV/IV < 0.7 = Strong short-vol signal
    RV/IV > 1.2 = Vol underpriced, avoid short-vol
    
    Args:
        close: Close prices
        current_iv: Current implied volatility (annualized, as decimal e.g., 0.15 for 15%)
        period: Period for RV calculation
        
    Returns:
        RV/IV ratio
    """
    rv = calculate_realized_vol(close, period, annualize=True)
    current_rv = rv.iloc[-1] if not rv.empty else 0
    
    if current_iv == 0:
        return 1.0
    
    return current_rv / current_iv


def calculate_rv_iv_ratio_series(
    close: pd.Series,
    iv_series: pd.Series,
    period: int = 20
) -> pd.Series:
    """
    Calculate RV/IV ratio as a time series.
    
    Args:
        close: Close prices
        iv_series: Implied volatility series (annualized)
        period: Period for RV calculation
        
    Returns:
        RV/IV ratio series
    """
    rv = calculate_realized_vol(close, period, annualize=True)
    
    # Align indices
    aligned_rv, aligned_iv = rv.align(iv_series, join='inner')
    
    # Avoid division by zero
    ratio = aligned_rv / aligned_iv.replace(0, np.nan)
    
    return ratio


def calculate_intraday_rv(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> float:
    """
    Calculate intraday realized volatility using ATR.
    
    Useful for comparing against IV to detect theta-friendly conditions.
    
    Args:
        high: High prices (intraday bars)
        low: Low prices (intraday bars)
        close: Close prices (intraday bars)
        period: ATR period
        
    Returns:
        Intraday RV as annualized percentage
    """
    from .technical import calculate_atr
    
    atr = calculate_atr(high, low, close, period)
    current_atr = atr.iloc[-1] if not atr.empty else 0
    current_close = close.iloc[-1] if not close.empty else 1
    
    # Convert ATR to percentage
    atr_pct = current_atr / current_close
    
    # Annualize (assuming 5-min bars, ~75 bars per day, 252 trading days)
    # For daily bars, use sqrt(252)
    annualized = atr_pct * np.sqrt(252)
    
    return annualized


def detect_correlation_spike_dynamic(
    correlations: pd.Series,
    lookback: int = 20,
    std_threshold: float = 1.0
) -> Tuple[bool, float]:
    """
    Detect correlation spike relative to historical average.
    
    More sophisticated than absolute threshold - triggers only on
    sudden spikes above historical norm.
    
    Args:
        correlations: Rolling correlation series
        lookback: Lookback for historical average
        std_threshold: Number of std devs above mean to trigger
        
    Returns:
        Tuple of (spike_detected, current_z_score)
    """
    if len(correlations) < lookback:
        return False, 0.0
    
    recent = correlations.tail(lookback)
    current = correlations.iloc[-1]
    
    mean_corr = recent.mean()
    std_corr = recent.std()
    
    if std_corr == 0:
        return False, 0.0
    
    z_score = (abs(current) - abs(mean_corr)) / std_corr
    
    spike_detected = z_score > std_threshold
    
    return spike_detected, z_score


def calculate_vol_regime_score(
    iv_percentile: float,
    rv_iv_ratio: float,
    bbw_ratio: float,
    volume_ratio: float
) -> Tuple[str, float]:
    """
    Calculate comprehensive volatility regime score.
    
    Combines multiple vol metrics into a single regime assessment.
    
    Args:
        iv_percentile: IV percentile (0-100)
        rv_iv_ratio: RV/IV ratio
        bbw_ratio: BBW ratio vs average
        volume_ratio: Volume ratio vs average
        
    Returns:
        Tuple of (regime_label, confidence)
    """
    score = 0.0
    
    # IV percentile contribution (low IV = range-bound)
    if iv_percentile < 25:
        score += 2.0  # Strong range signal
    elif iv_percentile < 35:
        score += 1.0  # Moderate range signal
    elif iv_percentile > 75:
        score -= 2.0  # Chaos signal
    elif iv_percentile > 50:
        score -= 0.5  # Mild trend signal
    
    # RV/IV ratio contribution (low = theta-friendly)
    if rv_iv_ratio < 0.7:
        score += 1.5  # Strong theta opportunity
    elif rv_iv_ratio < 0.8:
        score += 1.0  # Theta-friendly
    elif rv_iv_ratio > 1.2:
        score -= 1.5  # Vol underpriced
    
    # BBW ratio contribution (low = range contraction)
    if bbw_ratio < 0.5:
        score += 1.5  # Strong range contraction
    elif bbw_ratio < 0.8:
        score += 0.5  # Mild contraction
    elif bbw_ratio > 1.5:
        score -= 1.5  # Vol expansion
    
    # Volume ratio contribution (low = no trend fuel)
    if volume_ratio < 0.8:
        score += 0.5  # Low participation
    elif volume_ratio > 1.5:
        score -= 1.0  # Volume surge
    
    # Determine regime
    if score >= 3.0:
        return "RANGE_BOUND", min(0.95, 0.5 + score * 0.1)
    elif score >= 1.0:
        return "MEAN_REVERSION", min(0.85, 0.5 + score * 0.1)
    elif score <= -3.0:
        return "CHAOS", min(0.95, 0.5 + abs(score) * 0.1)
    elif score <= -1.0:
        return "TREND", min(0.85, 0.5 + abs(score) * 0.1)
    else:
        return "UNCERTAIN", 0.5
