"""Monk Agent - Backtesting and ML for Trading System v2.0"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import pickle
import pandas as pd
import numpy as np
from loguru import logger

from .base_agent import BaseAgent
from ...core.kite_client import KiteClient
from ...config.settings import Settings


class Monk(BaseAgent):
    """
    Backtesting and ML agent.
    
    Responsibilities:
    - Validate strategies through backtesting
    - Train and maintain ML models
    - Run Monte Carlo stress tests
    - Calculate performance metrics
    - Provide strategy validation before live deployment
    """
    
    def __init__(
        self,
        kite: KiteClient,
        config: Settings,
        models_dir: Optional[Path] = None
    ):
        super().__init__(kite, config, name="Monk")
        self.models_dir = models_dir or Path("data/models")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._regime_classifier = None
    
    def process(self, *args, **kwargs) -> Any:
        """Monk doesn't have a standard process loop - use specific methods."""
        raise NotImplementedError("Use specific Monk methods: validate_strategy, train_classifier, etc.")
    
    def validate_strategy(
        self,
        ruleset: Dict,
        data: pd.DataFrame,
        initial_capital: float = 1000000
    ) -> Tuple[bool, Dict]:
        """
        Validate a strategy through backtesting.
        
        Args:
            ruleset: Strategy rules and parameters
            data: Historical OHLCV data
            initial_capital: Starting capital
            
        Returns:
            Tuple of (passed_validation, metrics_dict)
        """
        self.logger.info(f"Validating strategy: {ruleset.get('name', 'unnamed')}")
        
        # Run backtest
        trades = self._run_backtest(ruleset, data, initial_capital)
        
        if not trades:
            return False, {"error": "No trades generated"}
        
        # Calculate metrics
        metrics = self._calculate_metrics(trades, initial_capital)
        
        # Validation criteria
        passed = (
            metrics["sharpe_ratio"] >= 1.0 and
            metrics["max_drawdown"] <= 0.15 and
            metrics["win_rate"] >= 0.55 and
            metrics["profit_factor"] >= 1.5
        )
        
        self.logger.info(
            f"Validation {'PASSED' if passed else 'FAILED'}: "
            f"Sharpe={metrics['sharpe_ratio']:.2f}, "
            f"MaxDD={metrics['max_drawdown']:.1%}, "
            f"WinRate={metrics['win_rate']:.1%}"
        )
        
        return passed, metrics
    
    def stress_test(
        self,
        ruleset: Dict,
        data: pd.DataFrame,
        num_simulations: int = 1000,
        max_acceptable_dd: float = 0.20,
        failure_threshold: float = 0.05
    ) -> Tuple[bool, Dict]:
        """
        Run Monte Carlo stress test.
        
        Args:
            ruleset: Strategy rules
            data: Historical data
            num_simulations: Number of Monte Carlo simulations
            max_acceptable_dd: Maximum acceptable drawdown
            failure_threshold: Max percentage of sims that can fail
            
        Returns:
            Tuple of (passed, results_dict)
        """
        self.logger.info(f"Running stress test with {num_simulations} simulations")
        
        # Get base trades from backtest
        base_trades = self._run_backtest(ruleset, data, 1000000)
        if not base_trades:
            return False, {"error": "No base trades"}
        
        # Extract trade returns
        returns = [t["pnl_pct"] for t in base_trades]
        
        # Monte Carlo simulation
        failures = 0
        max_drawdowns = []
        final_returns = []
        
        for _ in range(num_simulations):
            # Shuffle trade order
            sim_returns = np.random.choice(returns, size=len(returns), replace=True)
            
            # Calculate equity curve
            equity = [1.0]
            for r in sim_returns:
                equity.append(equity[-1] * (1 + r))
            
            # Calculate drawdown
            peak = np.maximum.accumulate(equity)
            drawdown = (peak - equity) / peak
            max_dd = np.max(drawdown)
            
            max_drawdowns.append(max_dd)
            final_returns.append(equity[-1] - 1)
            
            if max_dd > max_acceptable_dd:
                failures += 1
        
        failure_rate = failures / num_simulations
        passed = failure_rate <= failure_threshold
        
        results = {
            "num_simulations": num_simulations,
            "failure_rate": failure_rate,
            "avg_max_drawdown": np.mean(max_drawdowns),
            "worst_drawdown": np.max(max_drawdowns),
            "avg_return": np.mean(final_returns),
            "median_return": np.median(final_returns),
            "return_5th_percentile": np.percentile(final_returns, 5),
            "return_95th_percentile": np.percentile(final_returns, 95),
            "passed": passed
        }
        
        self.logger.info(
            f"Stress test {'PASSED' if passed else 'FAILED'}: "
            f"failure_rate={failure_rate:.1%}, "
            f"avg_dd={results['avg_max_drawdown']:.1%}"
        )
        
        return passed, results
    
    def train_regime_classifier(
        self,
        data: pd.DataFrame,
        labels: pd.Series,
        save_path: Optional[Path] = None
    ) -> Any:
        """
        Train ML model for regime classification.
        
        Args:
            data: Feature data (IV, ADX, RSI, etc.)
            labels: Regime labels
            save_path: Path to save trained model
            
        Returns:
            Trained classifier
        """
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split, cross_val_score
        from sklearn.preprocessing import StandardScaler
        
        self.logger.info("Training regime classifier")
        
        # Prepare features
        feature_cols = ['iv_percentile', 'adx', 'rsi', 'realized_vol', 'rv_atr_ratio']
        X = data[feature_cols].values
        y = labels.values
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Train classifier
        classifier = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=5,
            random_state=42
        )
        classifier.fit(X_train_scaled, y_train)
        
        # Evaluate
        train_score = classifier.score(X_train_scaled, y_train)
        test_score = classifier.score(X_test_scaled, y_test)
        cv_scores = cross_val_score(classifier, X_train_scaled, y_train, cv=5)
        
        self.logger.info(
            f"Classifier trained: train_acc={train_score:.2%}, "
            f"test_acc={test_score:.2%}, cv_mean={cv_scores.mean():.2%}"
        )
        
        # Create wrapper with scaler
        class RegimeClassifier:
            def __init__(self, clf, scaler):
                self.classifier = clf
                self.scaler = scaler
            
            def predict(self, X):
                X_scaled = self.scaler.transform(X)
                return self.classifier.predict(X_scaled)
            
            def predict_proba(self, X):
                X_scaled = self.scaler.transform(X)
                return self.classifier.predict_proba(X_scaled)
        
        wrapped_classifier = RegimeClassifier(classifier, scaler)
        
        # Save model
        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'wb') as f:
                pickle.dump(wrapped_classifier, f)
            self.logger.info(f"Model saved to {save_path}")
        
        self._regime_classifier = wrapped_classifier
        return wrapped_classifier
    
    def load_regime_classifier(self, model_path: Path) -> Any:
        """Load a trained regime classifier."""
        with open(model_path, 'rb') as f:
            self._regime_classifier = pickle.load(f)
        self.logger.info(f"Loaded classifier from {model_path}")
        return self._regime_classifier
    
    def _run_backtest(
        self,
        ruleset: Dict,
        data: pd.DataFrame,
        initial_capital: float
    ) -> List[Dict]:
        """
        Run backtest simulation.
        
        This is a simplified backtest engine. For production,
        use the full BacktestEngine class.
        """
        trades = []
        capital = initial_capital
        position = None
        
        # Ensure data is sorted by date
        if 'date' in data.columns:
            data = data.sort_values('date')
        else:
            data = data.sort_index()
        
        strategy_type = ruleset.get("type", "iron_condor")
        entry_conditions = ruleset.get("entry", {})
        exit_conditions = ruleset.get("exit", {})
        
        for i in range(20, len(data)):  # Start after warmup period
            row = data.iloc[i]
            
            if position is None:
                # Check entry conditions
                if self._check_entry_conditions(data.iloc[:i+1], entry_conditions):
                    # Simulate entry
                    entry_price = row['close']
                    position = {
                        "entry_idx": i,
                        "entry_price": entry_price,
                        "entry_date": row.name if isinstance(row.name, datetime) else data.index[i],
                        "size": capital * 0.02  # 2% position size
                    }
            else:
                # Check exit conditions
                exit_reason = self._check_exit_conditions(
                    data.iloc[:i+1], position, exit_conditions
                )
                
                if exit_reason:
                    # Simulate exit
                    exit_price = row['close']
                    pnl = (exit_price - position["entry_price"]) / position["entry_price"]
                    pnl_amount = position["size"] * pnl
                    
                    trades.append({
                        "entry_date": position["entry_date"],
                        "exit_date": row.name if isinstance(row.name, datetime) else data.index[i],
                        "entry_price": position["entry_price"],
                        "exit_price": exit_price,
                        "pnl": pnl_amount,
                        "pnl_pct": pnl,
                        "exit_reason": exit_reason,
                        "holding_days": i - position["entry_idx"]
                    })
                    
                    capital += pnl_amount
                    position = None
        
        return trades
    
    def _check_entry_conditions(self, data: pd.DataFrame, conditions: Dict) -> bool:
        """Check if entry conditions are met."""
        if data.empty:
            return False
        
        # Simple example conditions
        recent = data.tail(20)
        
        # Check volatility (using range as proxy)
        avg_range = ((recent['high'] - recent['low']) / recent['close']).mean()
        if avg_range > conditions.get("max_range", 0.02):
            return False
        
        # Check trend (ADX proxy using directional movement)
        if len(recent) < 14:
            return False
        
        return True
    
    def _check_exit_conditions(
        self,
        data: pd.DataFrame,
        position: Dict,
        conditions: Dict
    ) -> Optional[str]:
        """Check if exit conditions are met."""
        current_price = data.iloc[-1]['close']
        entry_price = position["entry_price"]
        
        pnl_pct = (current_price - entry_price) / entry_price
        
        # Profit target
        if pnl_pct >= conditions.get("profit_target", 0.02):
            return "PROFIT_TARGET"
        
        # Stop loss
        if pnl_pct <= -conditions.get("stop_loss", 0.01):
            return "STOP_LOSS"
        
        # Time-based exit
        holding_days = len(data) - position["entry_idx"]
        if holding_days >= conditions.get("max_holding_days", 10):
            return "TIME_EXIT"
        
        return None
    
    def _calculate_metrics(self, trades: List[Dict], initial_capital: float) -> Dict:
        """Calculate performance metrics from trades."""
        if not trades:
            return {}
        
        pnls = [t["pnl"] for t in trades]
        pnl_pcts = [t["pnl_pct"] for t in trades]
        
        # Basic metrics
        total_return = sum(pnls)
        total_return_pct = total_return / initial_capital
        
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        win_rate = len(wins) / len(pnls) if pnls else 0
        
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
        
        # Sharpe ratio (annualized)
        if len(pnl_pcts) > 1:
            returns_std = np.std(pnl_pcts)
            avg_return = np.mean(pnl_pcts)
            sharpe = (avg_return / returns_std) * np.sqrt(252) if returns_std > 0 else 0
        else:
            sharpe = 0
        
        # Max drawdown
        equity_curve = [initial_capital]
        for pnl in pnls:
            equity_curve.append(equity_curve[-1] + pnl)
        
        peak = np.maximum.accumulate(equity_curve)
        drawdown = (peak - equity_curve) / peak
        max_drawdown = np.max(drawdown)
        
        # Expectancy
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        
        return {
            "total_trades": len(trades),
            "total_return": total_return,
            "total_return_pct": total_return_pct,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "expectancy": expectancy,
            "avg_holding_days": np.mean([t["holding_days"] for t in trades])
        }
    
    def generate_report(self, metrics: Dict, trades: List[Dict]) -> str:
        """Generate a text report of backtest results."""
        report = []
        report.append("=" * 60)
        report.append("BACKTEST REPORT")
        report.append("=" * 60)
        report.append("")
        report.append("PERFORMANCE METRICS")
        report.append("-" * 40)
        report.append(f"Total Trades:      {metrics.get('total_trades', 0)}")
        report.append(f"Total Return:      {metrics.get('total_return_pct', 0):.2%}")
        report.append(f"Win Rate:          {metrics.get('win_rate', 0):.2%}")
        report.append(f"Profit Factor:     {metrics.get('profit_factor', 0):.2f}")
        report.append(f"Sharpe Ratio:      {metrics.get('sharpe_ratio', 0):.2f}")
        report.append(f"Max Drawdown:      {metrics.get('max_drawdown', 0):.2%}")
        report.append(f"Avg Win:           {metrics.get('avg_win', 0):.2f}")
        report.append(f"Avg Loss:          {metrics.get('avg_loss', 0):.2f}")
        report.append(f"Expectancy:        {metrics.get('expectancy', 0):.2f}")
        report.append(f"Avg Holding Days:  {metrics.get('avg_holding_days', 0):.1f}")
        report.append("")
        report.append("VALIDATION STATUS")
        report.append("-" * 40)
        
        checks = [
            ("Sharpe >= 1.0", metrics.get('sharpe_ratio', 0) >= 1.0),
            ("Max DD <= 15%", metrics.get('max_drawdown', 1) <= 0.15),
            ("Win Rate >= 55%", metrics.get('win_rate', 0) >= 0.55),
            ("Profit Factor >= 1.5", metrics.get('profit_factor', 0) >= 1.5)
        ]
        
        for check_name, passed in checks:
            status = "✓ PASS" if passed else "✗ FAIL"
            report.append(f"{check_name}: {status}")
        
        report.append("")
        report.append("=" * 60)
        
        return "\n".join(report)
