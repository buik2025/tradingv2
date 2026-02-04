"""ML Regime Classifier for Trading System v2.0"""

from pathlib import Path
from typing import Optional, Tuple, List
import pickle
import numpy as np
from loguru import logger


class RegimeClassifier:
    """
    Machine learning classifier for market regime detection.
    Wraps sklearn model with preprocessing.
    """
    
    FEATURE_NAMES = [
        'iv_percentile',
        'adx',
        'rsi',
        'realized_vol',
        'rv_atr_ratio',
        'skew',
        'oi_change_pct'
    ]
    
    REGIME_MAP = {
        0: "RANGE_BOUND",
        1: "MEAN_REVERSION",
        2: "TREND",
        3: "CHAOS"
    }
    
    def __init__(self, model=None, scaler=None):
        self.model = model
        self.scaler = scaler
        self._is_fitted = model is not None
    
    @classmethod
    def load(cls, model_path: Path) -> "RegimeClassifier":
        """Load a trained classifier from file."""
        with open(model_path, 'rb') as f:
            data = pickle.load(f)
        
        if isinstance(data, dict):
            return cls(model=data['model'], scaler=data['scaler'])
        else:
            # Legacy format
            return data
    
    def save(self, model_path: Path) -> None:
        """Save the classifier to file."""
        model_path.parent.mkdir(parents=True, exist_ok=True)
        with open(model_path, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'scaler': self.scaler
            }, f)
        logger.info(f"Model saved to {model_path}")
    
    def predict(self, features: np.ndarray) -> np.ndarray:
        """
        Predict regime from features.
        
        Args:
            features: Array of shape (n_samples, n_features)
            
        Returns:
            Array of regime predictions (integers)
        """
        if not self._is_fitted:
            raise ValueError("Model not fitted")
        
        if self.scaler:
            features = self.scaler.transform(features)
        
        return self.model.predict(features)
    
    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """
        Predict regime probabilities.
        
        Args:
            features: Array of shape (n_samples, n_features)
            
        Returns:
            Array of shape (n_samples, n_classes) with probabilities
        """
        if not self._is_fitted:
            raise ValueError("Model not fitted")
        
        if self.scaler:
            features = self.scaler.transform(features)
        
        return self.model.predict_proba(features)
    
    def predict_regime(self, features: np.ndarray) -> Tuple[str, float]:
        """
        Predict regime with name and confidence.
        
        Args:
            features: Array of shape (1, n_features) for single prediction
            
        Returns:
            Tuple of (regime_name, probability)
        """
        prediction = self.predict(features)[0]
        probabilities = self.predict_proba(features)[0]
        
        regime_name = self.REGIME_MAP.get(prediction, "UNKNOWN")
        confidence = probabilities[prediction]
        
        return regime_name, float(confidence)
    
    def get_feature_importance(self) -> Optional[dict]:
        """Get feature importance if available."""
        if not self._is_fitted:
            return None
        
        if hasattr(self.model, 'feature_importances_'):
            importances = self.model.feature_importances_
            return dict(zip(self.FEATURE_NAMES, importances))
        
        return None
