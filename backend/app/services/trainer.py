"""Model training utilities for Trading System v2.0"""

from pathlib import Path
from typing import Dict, Tuple, Optional
import numpy as np
import pandas as pd
from loguru import logger

from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix

from .regime_classifier import RegimeClassifier


class ModelTrainer:
    """
    Trains and validates ML models for regime classification.
    """
    
    def __init__(self, random_state: int = 42):
        self.random_state = random_state
        self.scaler = StandardScaler()
    
    def prepare_features(
        self,
        data: pd.DataFrame,
        feature_cols: Optional[list] = None
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare features and labels from DataFrame.
        
        Args:
            data: DataFrame with features and 'regime' column
            feature_cols: List of feature column names
            
        Returns:
            Tuple of (X, y) arrays
        """
        if feature_cols is None:
            feature_cols = RegimeClassifier.FEATURE_NAMES
        
        # Filter to available columns
        available_cols = [c for c in feature_cols if c in data.columns]
        
        if len(available_cols) < len(feature_cols):
            missing = set(feature_cols) - set(available_cols)
            logger.warning(f"Missing features: {missing}")
        
        X = data[available_cols].values
        
        # Handle labels
        if 'regime' in data.columns:
            # Map regime names to integers
            regime_map = {v: k for k, v in RegimeClassifier.REGIME_MAP.items()}
            y = data['regime'].map(regime_map).values
        elif 'regime_label' in data.columns:
            y = data['regime_label'].values
        else:
            raise ValueError("No regime column found")
        
        # Handle NaN values
        mask = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
        X = X[mask]
        y = y[mask]
        
        return X, y
    
    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        model_type: str = "random_forest",
        hyperparameter_search: bool = False
    ) -> RegimeClassifier:
        """
        Train a regime classifier.
        
        Args:
            X: Feature array
            y: Label array
            model_type: 'random_forest' or 'gradient_boosting'
            hyperparameter_search: Whether to perform grid search
            
        Returns:
            Trained RegimeClassifier
        """
        logger.info(f"Training {model_type} classifier on {len(X)} samples")
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=self.random_state, stratify=y
        )
        
        # Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Create model
        if model_type == "random_forest":
            base_model = RandomForestClassifier(random_state=self.random_state)
            param_grid = {
                'n_estimators': [50, 100, 200],
                'max_depth': [5, 10, 15],
                'min_samples_split': [2, 5, 10]
            }
        else:
            base_model = GradientBoostingClassifier(random_state=self.random_state)
            param_grid = {
                'n_estimators': [50, 100],
                'max_depth': [3, 5, 7],
                'learning_rate': [0.01, 0.1]
            }
        
        # Train
        if hyperparameter_search:
            logger.info("Performing hyperparameter search...")
            grid_search = GridSearchCV(
                base_model, param_grid, cv=5, scoring='accuracy', n_jobs=-1
            )
            grid_search.fit(X_train_scaled, y_train)
            model = grid_search.best_estimator_
            logger.info(f"Best params: {grid_search.best_params_}")
        else:
            model = base_model
            model.set_params(n_estimators=100, max_depth=10)
            model.fit(X_train_scaled, y_train)
        
        # Evaluate
        train_score = model.score(X_train_scaled, y_train)
        test_score = model.score(X_test_scaled, y_test)
        
        logger.info(f"Train accuracy: {train_score:.4f}")
        logger.info(f"Test accuracy: {test_score:.4f}")
        
        # Cross-validation
        cv_scores = cross_val_score(model, X_train_scaled, y_train, cv=5)
        logger.info(f"CV scores: {cv_scores.mean():.4f} (+/- {cv_scores.std() * 2:.4f})")
        
        # Classification report
        y_pred = model.predict(X_test_scaled)
        report = classification_report(y_test, y_pred, target_names=list(RegimeClassifier.REGIME_MAP.values()))
        logger.info(f"\nClassification Report:\n{report}")
        
        return RegimeClassifier(model=model, scaler=self.scaler)
    
    def validate(
        self,
        classifier: RegimeClassifier,
        X: np.ndarray,
        y: np.ndarray
    ) -> Dict:
        """
        Validate a trained classifier.
        
        Returns:
            Dict with validation metrics
        """
        y_pred = classifier.predict(X)
        y_proba = classifier.predict_proba(X)
        
        # Accuracy
        accuracy = (y_pred == y).mean()
        
        # Per-class metrics
        report = classification_report(y, y_pred, output_dict=True)
        
        # Confusion matrix
        cm = confusion_matrix(y, y_pred)
        
        # Average confidence
        confidences = y_proba.max(axis=1)
        avg_confidence = confidences.mean()
        
        return {
            'accuracy': accuracy,
            'avg_confidence': avg_confidence,
            'classification_report': report,
            'confusion_matrix': cm.tolist()
        }
    
    def generate_synthetic_data(
        self,
        n_samples: int = 1000
    ) -> pd.DataFrame:
        """
        Generate synthetic training data for testing.
        
        In production, use actual historical data with labeled regimes.
        """
        np.random.seed(self.random_state)
        
        data = []
        
        for _ in range(n_samples):
            regime = np.random.choice([0, 1, 2, 3], p=[0.3, 0.3, 0.25, 0.15])
            
            if regime == 0:  # RANGE_BOUND
                iv = np.random.uniform(20, 40)
                adx = np.random.uniform(5, 15)
                rsi = np.random.uniform(40, 60)
            elif regime == 1:  # MEAN_REVERSION
                iv = np.random.uniform(30, 50)
                adx = np.random.uniform(12, 22)
                rsi = np.random.choice([np.random.uniform(20, 35), np.random.uniform(65, 80)])
            elif regime == 2:  # TREND
                iv = np.random.uniform(25, 55)
                adx = np.random.uniform(22, 50)
                rsi = np.random.uniform(30, 70)
            else:  # CHAOS
                iv = np.random.uniform(60, 95)
                adx = np.random.uniform(15, 40)
                rsi = np.random.uniform(20, 80)
            
            # Add noise
            iv += np.random.normal(0, 5)
            adx += np.random.normal(0, 2)
            rsi += np.random.normal(0, 5)
            
            data.append({
                'iv_percentile': np.clip(iv, 0, 100),
                'adx': np.clip(adx, 0, 100),
                'rsi': np.clip(rsi, 0, 100),
                'realized_vol': np.random.uniform(0.1, 0.4),
                'rv_atr_ratio': np.random.uniform(0.5, 2.0),
                'skew': np.random.uniform(-0.1, 0.1),
                'oi_change_pct': np.random.uniform(-0.2, 0.2),
                'regime': RegimeClassifier.REGIME_MAP[regime]
            })
        
        return pd.DataFrame(data)
