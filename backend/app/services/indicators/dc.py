"""Directional Change (DC) Event Detector - v2.3 Sentinel Agent

Implements event-driven regime detection per Chen/Tsang (2021).
Detects regime shifts via price reversals exceeding threshold θ.
"""

from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
import numpy as np
from loguru import logger


@dataclass
class DCEvent:
    """Single Directional Change event."""
    start_idx: int
    end_idx: int
    start_time: datetime
    end_time: datetime
    start_price: float
    end_price: float
    direction: str  # 'up' or 'down'
    T: float  # Trend time (bars or seconds)
    TMV: float  # Time to max volume (normalized)
    TAR: float  # Time-adjusted return
    max_vol: float  # Max volume in trend


class DirectionalChange:
    """
    Directional Change event detector.
    
    Detects regime changes via threshold θ: price reversal >θ from last extremum
    signals a new regime (opposite direction).
    """
    
    def __init__(self, theta: float = 0.003, min_bar_window: int = 5):
        """
        Args:
            theta: DC threshold (default 0.3% = 0.003).
            min_bar_window: Minimum bars to qualify as DC event (avoid noise).
        """
        self.theta = theta
        self.min_bar_window = min_bar_window
        self.extrema: List[Tuple[int, float, str]] = []  # (index, price, type='high'/'low')
        self.dc_events: List[DCEvent] = []
        self.last_event: Optional[DCEvent] = None
        logger.info(f"DirectionalChange initialized: theta={theta}, min_window={min_bar_window}")
    
    def compute_dc_events(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect DC events in OHLCV data.
        
        Algorithm:
        1. Find extrema (local highs/lows).
        2. Between extrema, detect reversals >theta.
        3. Compute T (trend time), TMV (max vol timing), TAR (adjusted return).
        4. Return events as DataFrame.
        
        Args:
            df: OHLCV with columns [timestamp, open, high, low, close, volume].
                Must be sorted by timestamp, 5-min or 1-min bars preferred.
        
        Returns:
            pd.DataFrame with columns [start_idx, end_idx, start_time, end_time, 
                                       start_price, end_price, direction, T, TMV, TAR].
        """
        if len(df) < self.min_bar_window:
            logger.warning(f"DC: insufficient data ({len(df)} < {self.min_bar_window})")
            return pd.DataFrame()
        
        self.dc_events = []
        self.extrema = []
        
        # Ensure timestamp column exists
        if 'timestamp' not in df.columns:
            df = df.copy()
            df['timestamp'] = pd.to_datetime(df.index if isinstance(df.index, pd.DatetimeIndex) else df.index)
        
        # Find initial extremum (highest high or lowest low in first N bars)
        initial_window = min(10, len(df))
        first_high_idx = df['high'].iloc[:initial_window].idxmax()
        first_low_idx = df['low'].iloc[:initial_window].idxmin()
        
        # Start with whichever comes first
        if df.index.get_loc(first_high_idx) < df.index.get_loc(first_low_idx):
            current_extremum_idx = df.index.get_loc(first_high_idx)
            current_direction = 'down'  # Next event will be a reversal down
        else:
            current_extremum_idx = df.index.get_loc(first_low_idx)
            current_direction = 'up'  # Next event will be a reversal up
        
        current_extremum_price = df.iloc[current_extremum_idx]['high' if current_direction == 'down' else 'low']
        self.extrema.append((current_extremum_idx, current_extremum_price, 'high' if current_direction == 'down' else 'low'))
        
        event_start_idx = current_extremum_idx
        
        # Scan for reversals
        for i in range(current_extremum_idx + 1, len(df)):
            if current_direction == 'down':
                # Looking for low (downtrend)
                candidate_price = df.iloc[i]['low']
                reversal_threshold = current_extremum_price * (1 - self.theta)
                
                if candidate_price <= reversal_threshold:
                    # DC event detected: high → low
                    if i - event_start_idx >= self.min_bar_window:
                        event = self._build_dc_event(df, event_start_idx, i, 'down')
                        self.dc_events.append(event)
                        self.last_event = event
                    
                    # Update state for next event
                    current_extremum_idx = i
                    current_extremum_price = candidate_price
                    current_direction = 'up'
                    event_start_idx = i
                    self.extrema.append((i, candidate_price, 'low'))
            else:
                # Looking for high (uptrend)
                candidate_price = df.iloc[i]['high']
                reversal_threshold = current_extremum_price * (1 + self.theta)
                
                if candidate_price >= reversal_threshold:
                    # DC event detected: low → high
                    if i - event_start_idx >= self.min_bar_window:
                        event = self._build_dc_event(df, event_start_idx, i, 'up')
                        self.dc_events.append(event)
                        self.last_event = event
                    
                    # Update state for next event
                    current_extremum_idx = i
                    current_extremum_price = candidate_price
                    current_direction = 'down'
                    event_start_idx = i
                    self.extrema.append((i, candidate_price, 'high'))
        
        # Convert to DataFrame
        if self.dc_events:
            events_data = [
                {
                    'start_idx': e.start_idx,
                    'end_idx': e.end_idx,
                    'start_time': e.start_time,
                    'end_time': e.end_time,
                    'start_price': e.start_price,
                    'end_price': e.end_price,
                    'direction': e.direction,
                    'T': e.T,
                    'TMV': e.TMV,
                    'TAR': e.TAR,
                    'max_vol': e.max_vol,
                }
                for e in self.dc_events
            ]
            result_df = pd.DataFrame(events_data)
            logger.info(f"DC: detected {len(self.dc_events)} events from {len(df)} bars")
            return result_df
        else:
            logger.debug(f"DC: no events detected in {len(df)} bars")
            return pd.DataFrame()
    
    def _build_dc_event(self, df: pd.DataFrame, start_idx: int, end_idx: int, direction: str) -> DCEvent:
        """Build a DCEvent with computed indicators."""
        start_row = df.iloc[start_idx]
        end_row = df.iloc[end_idx]
        
        start_time = pd.to_datetime(start_row['timestamp'])
        end_time = pd.to_datetime(end_row['timestamp'])
        start_price = start_row['high' if direction == 'down' else 'low']
        end_price = end_row['low' if direction == 'down' else 'high']
        
        # T: Trend time (bars)
        T = end_idx - start_idx
        
        # TAR: Time-adjusted return
        price_change = end_price - start_price
        return_pct = price_change / start_price if start_price != 0 else 0
        TAR = return_pct / T if T > 0 else 0
        
        # TMV: Time to max volume (normalized, 0-1)
        volume_window = df.iloc[start_idx:end_idx + 1]['volume']
        if len(volume_window) > 0 and volume_window.max() > 0:
            max_vol_idx = volume_window.idxmax()
            max_vol_relative_pos = (df.index.get_loc(max_vol_idx) - start_idx) / T if T > 0 else 0
            TMV = np.clip(max_vol_relative_pos, 0, 1)
            max_vol = volume_window.max()
        else:
            TMV = 0.5
            max_vol = 0
        
        return DCEvent(
            start_idx=start_idx,
            end_idx=end_idx,
            start_time=start_time,
            end_time=end_time,
            start_price=start_price,
            end_price=end_price,
            direction=direction,
            T=float(T),
            TMV=float(TMV),
            TAR=float(TAR),
            max_vol=float(max_vol),
        )
    
    def current_event(self) -> Optional[Dict]:
        """
        Return unfinished DC event (last detected event) or None.
        
        Returns:
            dict: {'start_idx', 'direction', 'T', 'TMV', 'TAR'} or None.
        """
        if self.last_event is None:
            return None
        return {
            'start_idx': self.last_event.start_idx,
            'start_time': self.last_event.start_time,
            'direction': self.last_event.direction,
            'T': self.last_event.T,
            'TMV': self.last_event.TMV,
            'TAR': self.last_event.TAR,
        }
    
    def get_last_n_events(self, n: int = 5) -> List[Dict]:
        """
        Return last N DC events as dicts (for HMM input).
        
        Returns:
            List of dicts with {'T', 'TMV', 'TAR'} (normalized to [0,1]).
        """
        if not self.dc_events:
            return []
        
        events = self.dc_events[-n:] if len(self.dc_events) >= n else self.dc_events
        
        # Normalize to [0,1] for HMM
        if events:
            T_vals = [e.T for e in events]
            TMV_vals = [e.TMV for e in events]
            TAR_vals = [e.TAR for e in events]
            
            T_max = max(T_vals) if T_vals else 1
            TAR_range = (max(TAR_vals) - min(TAR_vals)) if TAR_vals and max(TAR_vals) != min(TAR_vals) else 1
            TAR_min = min(TAR_vals) if TAR_vals else 0
            
            normalized = []
            for e in events:
                normalized.append({
                    'T': e.T / T_max if T_max > 0 else 0,
                    'TMV': e.TMV,  # Already in [0,1]
                    'TAR': (e.TAR - TAR_min) / TAR_range if TAR_range > 0 else 0,
                })
            return normalized
        return []
    
    def reset(self):
        """Reset detector state (for backtesting)."""
        self.extrema = []
        self.dc_events = []
        self.last_event = None
