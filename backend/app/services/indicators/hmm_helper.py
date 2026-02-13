"""HMM Regime Classifier - v2.3 Sentinel Agent

Implements 2-state Hidden Markov Model for regime classification.
States: Normal (0) and Abnormal (1).
Uses DC event features (T, TMV, TAR) as observations.
"""

from typing import Optional, Tuple, List, Dict
from collections import deque
import numpy as np
import pandas as pd
from loguru import logger

try:
    from hmmlearn.hmm import GaussianHMM
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    logger.warning("hmmlearn not installed. HMM will use simplified Bayesian model.")


class HMMRegimeClassifier:
    """
    2-State Hidden Markov Model for regime classification.
    
    States:
        0 = Normal (stable, predictable market)
        1 = Abnormal (volatile, regime shift in progress)
    
    Features (from DC events):
        - T: Trend time (normalized)
        - TMV: Time to max volume (normalized)
        - TAR: Time-adjusted return (normalized)
    """
    
    def __init__(
        self,
        window: int = 20,
        n_states: int = 2,
        random_state: int = 42,
        min_samples: int = 5
    ):
        """
        Args:
            window: Rolling window for HMM fit (default 20 DC events).
            n_states: Number of states (always 2: normal, abnormal).
            random_state: For reproducibility.
            min_samples: Minimum DC events before predicting.
        """
        self.window = window
        self.n_states = n_states
        self.random_state = random_state
        self.min_samples = min_samples
        
        self.hmm = None
        self._event_buffer: deque = deque(maxlen=window)
        self._is_fitted = False
        
        # Prior probabilities (Bayesian fallback)
        self._prior_normal = 0.7
        self._prior_abnormal = 0.3
        
        # Thresholds for abnormal detection (Bayesian fallback)
        self._abnormal_T_threshold = 0.3  # Short T = abnormal
        self._abnormal_TAR_threshold = 0.7  # High TAR = abnormal
        
        logger.info(f"HMMRegimeClassifier initialized: window={window}, min_samples={min_samples}")
    
    def fit(self, dc_events_df: pd.DataFrame) -> None:
        """
        Fit HMM on DC events.
        
        Args:
            dc_events_df: DC events with columns [T, TMV, TAR] (normalized to [0,1]).
        
        Side Effect: Updates self.hmm and self._is_fitted.
        """
        if len(dc_events_df) < self.min_samples:
            logger.debug(f"HMM: insufficient samples ({len(dc_events_df)} < {self.min_samples})")
            return
        
        # Extract features
        features = dc_events_df[['T', 'TMV', 'TAR']].values
        
        if HMM_AVAILABLE:
            try:
                self.hmm = GaussianHMM(
                    n_components=self.n_states,
                    covariance_type='diag',
                    n_iter=100,
                    random_state=self.random_state
                )
                self.hmm.fit(features)
                self._is_fitted = True
                logger.info(f"HMM fitted on {len(dc_events_df)} DC events")
            except Exception as e:
                logger.warning(f"HMM fit failed: {e}. Using Bayesian fallback.")
                self._is_fitted = False
        else:
            # Bayesian fallback: compute mean/std for each feature
            self._feature_means = features.mean(axis=0)
            self._feature_stds = features.std(axis=0) + 1e-6
            self._is_fitted = True
            logger.info(f"HMM (Bayesian fallback) fitted on {len(dc_events_df)} events")
    
    def predict_proba(self, dc_events_df: pd.DataFrame) -> Tuple[float, float]:
        """
        Predict P(normal), P(abnormal) for last DC event(s).
        
        Args:
            dc_events_df: Recent DC events (last 3-5 for online tracking).
        
        Returns:
            (p_normal, p_abnormal): Normalized probabilities.
        """
        if len(dc_events_df) == 0:
            return self._prior_normal, self._prior_abnormal
        
        features = dc_events_df[['T', 'TMV', 'TAR']].values
        
        if HMM_AVAILABLE and self._is_fitted and self.hmm is not None:
            try:
                # Get posterior probabilities for last observation
                posteriors = self.hmm.predict_proba(features)
                last_posterior = posteriors[-1]
                
                # Determine which state is "abnormal" (higher variance state)
                # Typically state with higher TAR variance is abnormal
                p_state_0 = last_posterior[0]
                p_state_1 = last_posterior[1]
                
                # Heuristic: abnormal state has higher mean TAR
                if hasattr(self.hmm, 'means_'):
                    if self.hmm.means_[1][2] > self.hmm.means_[0][2]:
                        p_abnormal = p_state_1
                    else:
                        p_abnormal = p_state_0
                else:
                    p_abnormal = p_state_1
                
                p_normal = 1.0 - p_abnormal
                return float(p_normal), float(p_abnormal)
                
            except Exception as e:
                logger.warning(f"HMM predict failed: {e}. Using Bayesian fallback.")
        
        # Bayesian fallback
        return self._bayesian_predict(features[-1])
    
    def _bayesian_predict(self, features: np.ndarray) -> Tuple[float, float]:
        """
        Simple Bayesian prediction based on feature thresholds.
        
        Abnormal indicators:
        - Low T (short trend time = rapid reversals)
        - High TAR (large time-adjusted returns)
        - Extreme TMV (volume spike at start or end)
        """
        T, TMV, TAR = features
        
        # Compute abnormal score based on features
        abnormal_score = 0.0
        
        # Short T is abnormal
        if T < self._abnormal_T_threshold:
            abnormal_score += 0.3
        
        # High TAR is abnormal
        if TAR > self._abnormal_TAR_threshold:
            abnormal_score += 0.4
        
        # Extreme TMV (volume spike at start or end) is abnormal
        if TMV < 0.2 or TMV > 0.8:
            abnormal_score += 0.2
        
        # Combine with prior
        p_abnormal = self._prior_abnormal + abnormal_score * (1 - self._prior_abnormal)
        p_abnormal = np.clip(p_abnormal, 0.0, 1.0)
        p_normal = 1.0 - p_abnormal
        
        return float(p_normal), float(p_abnormal)
    
    def online_update(self, new_event: Dict) -> Tuple[float, float]:
        """
        Update HMM with single new DC event (online/streaming mode).
        
        Args:
            new_event: {'T', 'TMV', 'TAR'} (normalized).
        
        Returns:
            (p_normal, p_abnormal) after update.
        """
        # Add to buffer
        self._event_buffer.append(new_event)
        
        # Refit if enough samples
        if len(self._event_buffer) >= self.min_samples:
            events_df = pd.DataFrame(list(self._event_buffer))
            self.fit(events_df)
        
        # Predict on recent events
        if len(self._event_buffer) >= 3:
            recent = pd.DataFrame(list(self._event_buffer)[-5:])
            return self.predict_proba(recent)
        else:
            return self._prior_normal, self._prior_abnormal
    
    def get_state_description(self, p_abnormal: float) -> str:
        """
        Get human-readable state description.
        
        Args:
            p_abnormal: Probability of abnormal state.
        
        Returns:
            str: 'normal', 'elevated', or 'abnormal'.
        """
        if p_abnormal < 0.3:
            return "normal"
        elif p_abnormal < 0.7:
            return "elevated"
        else:
            return "abnormal"
    
    def reset(self) -> None:
        """Reset classifier state (for backtesting)."""
        self._event_buffer.clear()
        self._is_fitted = False
        self.hmm = None
        logger.debug("HMM classifier reset")


class DCAlarmTracker:
    """
    Tracks consecutive DC events for abnormal alarm triggering.
    
    Alarm triggers when p_abnormal > threshold for N consecutive events.
    """
    
    def __init__(
        self,
        p_threshold: float = 0.7,
        n_consecutive: int = 3
    ):
        """
        Args:
            p_threshold: P(abnormal) threshold for alarm (default 0.7).
            n_consecutive: Number of consecutive events to trigger alarm (default 3).
        """
        self.p_threshold = p_threshold
        self.n_consecutive = n_consecutive
        self._consecutive_count = 0
        self._alarm_active = False
        self._history: deque = deque(maxlen=10)
    
    def update(self, p_abnormal: float) -> bool:
        """
        Update tracker with new p_abnormal value.
        
        Args:
            p_abnormal: Current P(abnormal) from HMM.
        
        Returns:
            bool: True if alarm is now active.
        """
        self._history.append(p_abnormal)
        
        if p_abnormal > self.p_threshold:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 0
            self._alarm_active = False
        
        if self._consecutive_count >= self.n_consecutive:
            self._alarm_active = True
            logger.warning(
                f"DC ALARM TRIGGERED: {self._consecutive_count} consecutive events "
                f"with p_abnormal > {self.p_threshold}"
            )
        
        return self._alarm_active
    
    def is_alarm_active(self) -> bool:
        """Check if alarm is currently active."""
        return self._alarm_active
    
    def get_consecutive_count(self) -> int:
        """Get current consecutive count."""
        return self._consecutive_count
    
    def reset(self) -> None:
        """Reset alarm tracker."""
        self._consecutive_count = 0
        self._alarm_active = False
        self._history.clear()
