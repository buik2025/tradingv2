"""
Train ML classifier for regime detection.

Uses historical data to train a RandomForest classifier that can
predict market regimes based on technical indicators.

Features:
- IV percentile
- ADX
- RSI
- Realized volatility
- RV/ATR ratio
- BBW ratio
- Volume ratio

Labels:
0 = RANGE_BOUND
1 = MEAN_REVERSION
2 = TREND
3 = CHAOS
"""

import os
import sys
from pathlib import Path
import pickle
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from loguru import logger
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
import warnings
warnings.filterwarnings('ignore')

# Paths
DATA_DIR = Path(__file__).parent.parent / "data" / "historical"
MODELS_DIR = Path(__file__).parent.parent / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)


def load_training_data() -> pd.DataFrame:
    """Load and combine all historical data for training."""
    all_data = []
    
    # Load daily data files
    for csv_file in DATA_DIR.glob("*_daily.csv"):
        logger.info(f"Loading {csv_file.name}")
        df = pd.read_csv(csv_file)
        df['symbol'] = csv_file.stem.replace('_daily', '')
        all_data.append(df)
    
    if not all_data:
        logger.error("No training data found. Run download_historical_data.py first.")
        return pd.DataFrame()
    
    combined = pd.concat(all_data, ignore_index=True)
    logger.info(f"Loaded {len(combined)} total rows")
    
    return combined


def prepare_features(df: pd.DataFrame) -> tuple:
    """
    Prepare feature matrix and labels for training.
    
    Returns:
        Tuple of (X, y, feature_names)
    """
    # Required columns
    feature_cols = [
        'iv_percentile',
        'adx',
        'rsi',
        'realized_vol',
        'atr_pct',
        'day_range_pct',
        'gap_pct'
    ]
    
    # Check for required columns
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        logger.warning(f"Missing columns: {missing}")
        feature_cols = [c for c in feature_cols if c in df.columns]
    
    # Filter valid rows
    df_clean = df.dropna(subset=feature_cols + ['regime_label'])
    df_clean = df_clean[df_clean['regime_label'] >= 0]  # Remove unknown labels
    
    logger.info(f"Clean data: {len(df_clean)} rows")
    
    # Extract features and labels
    X = df_clean[feature_cols].values
    y = df_clean['regime_label'].values
    
    return X, y, feature_cols


def train_random_forest(X_train, y_train, X_test, y_test) -> tuple:
    """Train Random Forest classifier with hyperparameter tuning."""
    logger.info("Training Random Forest classifier...")
    
    # Grid search for best parameters
    param_grid = {
        'n_estimators': [50, 100, 200],
        'max_depth': [5, 10, 15, None],
        'min_samples_split': [2, 5, 10],
        'min_samples_leaf': [1, 2, 4]
    }
    
    rf = RandomForestClassifier(random_state=42, n_jobs=-1)
    
    # Use smaller grid for faster training
    quick_grid = {
        'n_estimators': [100, 200],
        'max_depth': [10, 15],
        'min_samples_split': [5],
        'min_samples_leaf': [2]
    }
    
    grid_search = GridSearchCV(
        rf, quick_grid, cv=5, scoring='accuracy', n_jobs=-1, verbose=1
    )
    grid_search.fit(X_train, y_train)
    
    best_rf = grid_search.best_estimator_
    logger.info(f"Best RF params: {grid_search.best_params_}")
    
    # Evaluate
    train_score = best_rf.score(X_train, y_train)
    test_score = best_rf.score(X_test, y_test)
    
    logger.info(f"RF Train accuracy: {train_score:.4f}")
    logger.info(f"RF Test accuracy: {test_score:.4f}")
    
    return best_rf, test_score


def train_gradient_boosting(X_train, y_train, X_test, y_test) -> tuple:
    """Train Gradient Boosting classifier."""
    logger.info("Training Gradient Boosting classifier...")
    
    gb = GradientBoostingClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        random_state=42
    )
    gb.fit(X_train, y_train)
    
    train_score = gb.score(X_train, y_train)
    test_score = gb.score(X_test, y_test)
    
    logger.info(f"GB Train accuracy: {train_score:.4f}")
    logger.info(f"GB Test accuracy: {test_score:.4f}")
    
    return gb, test_score


def train_logistic_regression(X_train, y_train, X_test, y_test) -> tuple:
    """Train Logistic Regression classifier."""
    logger.info("Training Logistic Regression classifier...")
    
    lr = LogisticRegression(
        multi_class='multinomial',
        solver='lbfgs',
        max_iter=1000,
        random_state=42
    )
    lr.fit(X_train, y_train)
    
    train_score = lr.score(X_train, y_train)
    test_score = lr.score(X_test, y_test)
    
    logger.info(f"LR Train accuracy: {train_score:.4f}")
    logger.info(f"LR Test accuracy: {test_score:.4f}")
    
    return lr, test_score


class RegimeClassifierWrapper:
    """Wrapper class for regime classifier with scaler."""
    
    def __init__(self, classifier, scaler, feature_names):
        self.classifier = classifier
        self.scaler = scaler
        self.feature_names = feature_names
        self.regime_map = {
            0: "RANGE_BOUND",
            1: "MEAN_REVERSION",
            2: "TREND",
            3: "CHAOS"
        }
    
    def predict(self, X):
        """Predict regime labels."""
        X_scaled = self.scaler.transform(X)
        return self.classifier.predict(X_scaled)
    
    def predict_proba(self, X):
        """Predict regime probabilities."""
        X_scaled = self.scaler.transform(X)
        return self.classifier.predict_proba(X_scaled)
    
    def predict_regime(self, features_dict: dict) -> tuple:
        """
        Predict regime from feature dictionary.
        
        Args:
            features_dict: Dict with feature names as keys
            
        Returns:
            Tuple of (regime_name, probability)
        """
        X = np.array([[features_dict.get(f, 0) for f in self.feature_names]])
        X_scaled = self.scaler.transform(X)
        
        pred = self.classifier.predict(X_scaled)[0]
        proba = self.classifier.predict_proba(X_scaled)[0]
        
        regime_name = self.regime_map.get(pred, "UNKNOWN")
        confidence = proba[pred]
        
        return regime_name, confidence


def evaluate_model(model, X_test, y_test, scaler):
    """Detailed model evaluation."""
    X_scaled = scaler.transform(X_test)
    y_pred = model.predict(X_scaled)
    
    print("\n" + "=" * 60)
    print("CLASSIFICATION REPORT")
    print("=" * 60)
    
    regime_names = ['RANGE_BOUND', 'MEAN_REVERSION', 'TREND', 'CHAOS']
    print(classification_report(y_test, y_pred, target_names=regime_names))
    
    print("\nCONFUSION MATRIX")
    print("-" * 40)
    cm = confusion_matrix(y_test, y_pred)
    print(pd.DataFrame(cm, index=regime_names, columns=regime_names))
    
    # Per-class accuracy
    print("\nPER-CLASS ACCURACY")
    print("-" * 40)
    for i, name in enumerate(regime_names):
        mask = y_test == i
        if mask.sum() > 0:
            acc = (y_pred[mask] == i).mean()
            print(f"  {name}: {acc:.2%} ({mask.sum()} samples)")


def main():
    """Main training function."""
    logger.info("=" * 60)
    logger.info("Regime Classifier Training")
    logger.info("=" * 60)
    
    # Load data
    df = load_training_data()
    if df.empty:
        return
    
    # Prepare features
    X, y, feature_names = prepare_features(df)
    if len(X) == 0:
        logger.error("No valid training data")
        return
    
    # Print class distribution
    print("\nClass distribution:")
    for i, name in enumerate(['RANGE_BOUND', 'MEAN_REVERSION', 'TREND', 'CHAOS']):
        count = (y == i).sum()
        pct = count / len(y) * 100
        print(f"  {name}: {count} ({pct:.1f}%)")
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    
    logger.info(f"Train size: {len(X_train)}, Test size: {len(X_test)}")
    
    # Scale features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train multiple models
    models = {}
    
    # Random Forest
    rf_model, rf_score = train_random_forest(X_train_scaled, y_train, X_test_scaled, y_test)
    models['random_forest'] = (rf_model, rf_score)
    
    # Gradient Boosting
    gb_model, gb_score = train_gradient_boosting(X_train_scaled, y_train, X_test_scaled, y_test)
    models['gradient_boosting'] = (gb_model, gb_score)
    
    # Logistic Regression
    lr_model, lr_score = train_logistic_regression(X_train_scaled, y_train, X_test_scaled, y_test)
    models['logistic_regression'] = (lr_model, lr_score)
    
    # Select best model
    best_name = max(models, key=lambda k: models[k][1])
    best_model, best_score = models[best_name]
    
    logger.info(f"\nBest model: {best_name} (accuracy: {best_score:.4f})")
    
    # Detailed evaluation
    evaluate_model(best_model, X_test, y_test, scaler)
    
    # Cross-validation
    print("\n" + "=" * 60)
    print("CROSS-VALIDATION (5-fold)")
    print("=" * 60)
    cv_scores = cross_val_score(best_model, X_train_scaled, y_train, cv=5)
    print(f"CV Scores: {cv_scores}")
    print(f"CV Mean: {cv_scores.mean():.4f} (+/- {cv_scores.std() * 2:.4f})")
    
    # Feature importance (for tree-based models)
    if hasattr(best_model, 'feature_importances_'):
        print("\nFEATURE IMPORTANCE")
        print("-" * 40)
        importances = best_model.feature_importances_
        for name, imp in sorted(zip(feature_names, importances), key=lambda x: -x[1]):
            print(f"  {name}: {imp:.4f}")
    
    # Wrap and save model
    wrapped_model = RegimeClassifierWrapper(best_model, scaler, feature_names)
    
    model_path = MODELS_DIR / "regime_classifier.pkl"
    with open(model_path, 'wb') as f:
        pickle.dump(wrapped_model, f)
    
    logger.info(f"\nModel saved to: {model_path}")
    
    # Save training metadata
    metadata = {
        'trained_at': datetime.now().isoformat(),
        'model_type': best_name,
        'accuracy': best_score,
        'cv_mean': cv_scores.mean(),
        'feature_names': feature_names,
        'train_size': len(X_train),
        'test_size': len(X_test),
        'class_distribution': {
            'RANGE_BOUND': int((y == 0).sum()),
            'MEAN_REVERSION': int((y == 1).sum()),
            'TREND': int((y == 2).sum()),
            'CHAOS': int((y == 3).sum())
        }
    }
    
    import json
    metadata_path = MODELS_DIR / "regime_classifier_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"Metadata saved to: {metadata_path}")
    
    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print(f"Model: {best_name}")
    print(f"Accuracy: {best_score:.2%}")
    print(f"Saved to: {model_path}")


if __name__ == "__main__":
    main()
