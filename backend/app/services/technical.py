"""Technical indicators for Trading System v2.0"""

import numpy as np
import pandas as pd
from typing import Optional

try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False


def calculate_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    Calculate Average Directional Index (ADX).
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: Lookback period (default 14)
        
    Returns:
        ADX values
    """
    if TALIB_AVAILABLE:
        return pd.Series(
            talib.ADX(high.values, low.values, close.values, timeperiod=period),
            index=close.index
        )
    
    # Manual calculation if TA-Lib not available
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    plus_di = 100 * pd.Series(plus_dm, index=close.index).rolling(window=period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=close.index).rolling(window=period).mean() / atr
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=period).mean()
    
    return adx


def calculate_rsi(
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    Calculate Relative Strength Index (RSI).
    
    Args:
        close: Close prices
        period: Lookback period (default 14)
        
    Returns:
        RSI values (0-100)
    """
    if TALIB_AVAILABLE:
        return pd.Series(
            talib.RSI(close.values, timeperiod=period),
            index=close.index
        )
    
    # Manual calculation
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    Calculate Average True Range (ATR).
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: Lookback period (default 14)
        
    Returns:
        ATR values
    """
    if TALIB_AVAILABLE:
        return pd.Series(
            talib.ATR(high.values, low.values, close.values, timeperiod=period),
            index=close.index
        )
    
    # Manual calculation
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    return atr


def calculate_ema(
    series: pd.Series,
    period: int
) -> pd.Series:
    """
    Calculate Exponential Moving Average.
    
    Args:
        series: Price series
        period: EMA period
        
    Returns:
        EMA values
    """
    if TALIB_AVAILABLE:
        return pd.Series(
            talib.EMA(series.values, timeperiod=period),
            index=series.index
        )
    
    return series.ewm(span=period, adjust=False).mean()


def calculate_sma(
    series: pd.Series,
    period: int
) -> pd.Series:
    """
    Calculate Simple Moving Average.
    
    Args:
        series: Price series
        period: SMA period
        
    Returns:
        SMA values
    """
    return series.rolling(window=period).mean()


def calculate_bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands.
    
    Args:
        close: Close prices
        period: SMA period
        std_dev: Standard deviation multiplier
        
    Returns:
        Tuple of (upper_band, middle_band, lower_band)
    """
    middle = calculate_sma(close, period)
    std = close.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    
    return upper, middle, lower


def calculate_macd(
    close: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD.
    
    Args:
        close: Close prices
        fast_period: Fast EMA period
        slow_period: Slow EMA period
        signal_period: Signal line period
        
    Returns:
        Tuple of (macd_line, signal_line, histogram)
    """
    if TALIB_AVAILABLE:
        macd, signal, hist = talib.MACD(
            close.values,
            fastperiod=fast_period,
            slowperiod=slow_period,
            signalperiod=signal_period
        )
        return (
            pd.Series(macd, index=close.index),
            pd.Series(signal, index=close.index),
            pd.Series(hist, index=close.index)
        )
    
    fast_ema = calculate_ema(close, fast_period)
    slow_ema = calculate_ema(close, slow_period)
    macd_line = fast_ema - slow_ema
    signal_line = calculate_ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def calculate_stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3
) -> tuple[pd.Series, pd.Series]:
    """
    Calculate Stochastic Oscillator.
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        k_period: %K period
        d_period: %D period
        
    Returns:
        Tuple of (%K, %D)
    """
    if TALIB_AVAILABLE:
        k, d = talib.STOCH(
            high.values, low.values, close.values,
            fastk_period=k_period,
            slowk_period=d_period,
            slowd_period=d_period
        )
        return pd.Series(k, index=close.index), pd.Series(d, index=close.index)
    
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(window=d_period).mean()
    
    return k, d


def detect_gaps(
    open_prices: pd.Series,
    prev_close: pd.Series,
    threshold_pct: float = 0.015
) -> pd.Series:
    """
    Detect price gaps.
    
    Args:
        open_prices: Open prices
        prev_close: Previous close prices
        threshold_pct: Gap threshold (default 1.5%)
        
    Returns:
        Boolean series indicating gaps
    """
    gap_pct = abs(open_prices - prev_close) / prev_close
    return gap_pct > threshold_pct


def calculate_day_range(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series
) -> pd.Series:
    """
    Calculate daily range as percentage of close.
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        
    Returns:
        Range as percentage
    """
    return (high - low) / close


def calculate_bollinger_band_width(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.0
) -> pd.Series:
    """
    Calculate Bollinger Band Width (BBW).
    
    BBW = (Upper Band - Lower Band) / Middle Band
    
    Low BBW indicates range contraction (range-bound market).
    High BBW indicates volatility expansion.
    
    Args:
        close: Close prices
        period: SMA period (default 20)
        std_dev: Standard deviation multiplier (default 2.0)
        
    Returns:
        BBW values (ratio)
    """
    upper, middle, lower = calculate_bollinger_bands(close, period, std_dev)
    bbw = (upper - lower) / middle
    return bbw


def calculate_bbw_percentile(
    close: pd.Series,
    period: int = 20,
    lookback: int = 100
) -> pd.Series:
    """
    Calculate BBW percentile relative to recent history.
    
    Args:
        close: Close prices
        period: BBW calculation period
        lookback: Lookback for percentile calculation
        
    Returns:
        BBW percentile (0-100)
    """
    bbw = calculate_bollinger_band_width(close, period)
    
    def rolling_percentile(x):
        if len(x) < 2:
            return 50.0
        return (x.iloc[:-1] < x.iloc[-1]).sum() / (len(x) - 1) * 100
    
    return bbw.rolling(window=lookback).apply(rolling_percentile, raw=False)


def calculate_bbw_ratio(
    close: pd.Series,
    period: int = 20,
    avg_period: int = 20
) -> pd.Series:
    """
    Calculate BBW ratio vs its moving average.
    
    Ratio < 0.5 = Range contraction (range-bound confirmation)
    Ratio > 1.5 = Vol expansion (potential trend/chaos)
    
    Args:
        close: Close prices
        period: BBW calculation period
        avg_period: Period for BBW average
        
    Returns:
        BBW ratio (current BBW / average BBW)
    """
    bbw = calculate_bollinger_band_width(close, period)
    bbw_avg = bbw.rolling(window=avg_period).mean()
    return bbw / bbw_avg


def calculate_volume_ratio(
    volume: pd.Series,
    period: int = 20
) -> pd.Series:
    """
    Calculate volume ratio vs moving average.
    
    Ratio > 1.5 = Volume surge (potential trend)
    Ratio < 0.8 = Low volume (range confirmation)
    
    Args:
        volume: Volume series
        period: Lookback period for average
        
    Returns:
        Volume ratio
    """
    avg_volume = volume.rolling(window=period).mean()
    return volume / avg_volume


def calculate_price_position_in_range(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    period: int = 20
) -> pd.Series:
    """
    Calculate where current price sits in recent range (0-100).
    
    0 = At period low
    50 = Middle of range
    100 = At period high
    
    Useful for mean-reversion signals.
    
    Args:
        close: Close prices
        high: High prices
        low: Low prices
        period: Lookback period
        
    Returns:
        Position in range (0-100)
    """
    period_high = high.rolling(window=period).max()
    period_low = low.rolling(window=period).min()
    
    position = (close - period_low) / (period_high - period_low) * 100
    return position


def calculate_atr_percentile(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
    lookback: int = 252
) -> pd.Series:
    """
    Calculate ATR percentile relative to historical values.
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: ATR period
        lookback: Lookback for percentile
        
    Returns:
        ATR percentile (0-100)
    """
    atr = calculate_atr(high, low, close, period)
    
    def rolling_percentile(x):
        if len(x) < 2:
            return 50.0
        return (x.iloc[:-1] < x.iloc[-1]).sum() / (len(x) - 1) * 100
    
    return atr.rolling(window=lookback).apply(rolling_percentile, raw=False)
