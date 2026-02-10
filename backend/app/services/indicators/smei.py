"""SMEI Sentiment Scorer - v2.3 Sentinel Agent

Implements sentiment analysis per Yang (2007) "The Stock Market Emotion Index".
Computes investor psychology cycles via enhanced OBV and CMF.
"""

from typing import Optional
import pandas as pd
import numpy as np
from loguru import logger


class SMEICalculator:
    """
    SMEI (Stock Market Emotion Index) Sentiment Scorer.
    
    Quantifies investor sentiment (bullish/bearish/neutral) using enhanced OBV
    and CMF variants. Output normalized to [-1, 1].
    """
    
    def __init__(self, window: int = 20):
        """
        Args:
            window: Lookback window for SMEI calculation (default 20 days/bars).
        """
        self.window = window
        logger.info(f"SMEICalculator initialized: window={window} bars")
    
    def compute_smei(self, df: pd.DataFrame) -> float:
        """
        Compute SMEI sentiment score.
        
        Formula:
            1. Enhanced OBV = sum[sign(close - open) * volume * (close-open)/(high-low)]
            2. CMF = sum[volume * ((close-low)-(high-close))/(high-low)] / sum(volume)
            3. SMEI = (OBV_norm + CMF) / 2, normalized to [-1, 1]
        
        Args:
            df: OHLCV with columns [open, high, low, close, volume].
                At least `window` rows.
        
        Returns:
            float: SMEI ∈ [-1, 1].
                >0.5: bullish (short-vol ok).
                <-0.5: bearish (directional only).
                [-0.5, 0.5]: neutral.
        """
        if len(df) < self.window:
            logger.debug(f"SMEI: insufficient data ({len(df)} < {self.window}), returning 0")
            return 0.0
        
        # Use last 'window' rows
        lookback = df.iloc[-self.window:].copy()
        
        # Compute enhanced OBV
        obv = self._compute_obv(lookback)
        
        # Compute CMF
        cmf = self._compute_cmf(lookback)
        
        # Combine and normalize
        smei = (obv + cmf) / 2.0
        smei = np.clip(smei, -1.0, 1.0)
        
        return float(smei)
    
    def _compute_obv(self, df: pd.DataFrame) -> float:
        """
        Enhanced OBV with range normalization.
        
        OBV_t = sum[sign(close - open) * volume * (close - open) / (high - low)]
        
        Args:
            df: Lookback window of OHLCV.
        
        Returns:
            float: Normalized OBV ∈ [-1, 1] approximately.
        """
        if len(df) == 0:
            return 0.0
        
        df = df.copy()
        
        # Avoid division by zero
        df['range'] = df['high'] - df['low']
        df['range'] = df['range'].replace(0, 1)
        
        # Close-open direction with range normalization
        df['close_open'] = df['close'] - df['open']
        df['normalized_move'] = df['close_open'] / df['range']
        
        # Sign of move
        df['sign'] = np.sign(df['close_open'])
        df['sign'] = df['sign'].replace(0, 0)  # Neutral if close == open
        
        # Enhanced OBV component
        df['obv_component'] = df['sign'] * df['volume'] * df['normalized_move']
        
        # Sum and normalize
        obv_sum = df['obv_component'].sum()
        volume_sum = df['volume'].sum()
        
        if volume_sum == 0:
            return 0.0
        
        # Normalize by total volume to get [-1, 1]
        obv_normalized = obv_sum / volume_sum if volume_sum > 0 else 0.0
        obv_normalized = np.clip(obv_normalized, -1.0, 1.0)
        
        return float(obv_normalized)
    
    def _compute_cmf(self, df: pd.DataFrame) -> float:
        """
        Chaikin Money Flow (CMF) variant.
        
        MF_t = volume * ((close - low) - (high - close)) / (high - low)
        CMF = sum(MF) / sum(volume), normalized to [-1, 1]
        
        Args:
            df: Lookback window of OHLCV.
        
        Returns:
            float: CMF score ∈ [-1, 1].
        """
        if len(df) == 0:
            return 0.0
        
        df = df.copy()
        
        # Avoid division by zero
        df['range'] = df['high'] - df['low']
        df['range'] = df['range'].replace(0, 1)
        
        # Money flow calculation
        df['money_flow'] = (
            (df['close'] - df['low']) - (df['high'] - df['close'])
        ) / df['range']
        
        # Weight by volume
        df['weighted_mf'] = df['money_flow'] * df['volume']
        
        # Sum and normalize
        mf_sum = df['weighted_mf'].sum()
        volume_sum = df['volume'].sum()
        
        if volume_sum == 0:
            return 0.0
        
        cmf_normalized = mf_sum / volume_sum
        cmf_normalized = np.clip(cmf_normalized, -1.0, 1.0)
        
        return float(cmf_normalized)
    
    def obv(self, df: pd.DataFrame) -> float:
        """
        Compute enhanced OBV for unit tests / inspection.
        
        Args:
            df: OHLCV data.
        
        Returns:
            float: OBV score ∈ [-1, 1].
        """
        if len(df) < self.window:
            return 0.0
        lookback = df.iloc[-self.window:]
        return self._compute_obv(lookback)
    
    def cmf(self, df: pd.DataFrame) -> float:
        """
        Compute CMF for unit tests / inspection.
        
        Args:
            df: OHLCV data.
        
        Returns:
            float: CMF score ∈ [-1, 1].
        """
        if len(df) < self.window:
            return 0.0
        lookback = df.iloc[-self.window:]
        return self._compute_cmf(lookback)
    
    def sentiment_description(self, smei: float) -> str:
        """
        Describe sentiment in plain language.
        
        Args:
            smei: SMEI score ∈ [-1, 1].
        
        Returns:
            str: 'bullish', 'neutral', or 'bearish'.
        """
        if smei > 0.5:
            return "bullish"
        elif smei < -0.5:
            return "bearish"
        else:
            return "neutral"
