"""
Strategy Backtester - Full agent-integrated backtesting for Trading System v2.0

This module provides comprehensive backtesting that integrates:
- Sentinel: Regime detection on historical data
- Strategist: Signal generation based on regime
- Treasury: Risk management and position sizing
- Simulated Executor: Virtual order execution with slippage/costs

Supports all strategy types:
- Iron Condor
- Jade Lizard
- Butterfly / Broken Wing Butterfly
- Risk Reversal
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd
import numpy as np
from loguru import logger

from .sentinel import Sentinel
from .strategist import Strategist
from .treasury import Treasury
from .data_loader import DataLoader
from .metrics import calculate_metrics, build_equity_curve, calculate_max_drawdown
from .technical import calculate_adx, calculate_rsi, calculate_atr
from .volatility import calculate_iv_percentile, calculate_realized_vol
from ..config.settings import Settings
from ..config.thresholds import SLIPPAGE_PCT, BROKERAGE_PCT
from ..models.regime import RegimeType, RegimePacket, RegimeMetrics
from ..models.trade import TradeProposal, StructureType


class BacktestMode(str, Enum):
    """Backtest execution mode."""
    QUICK = "quick"           # Fast, simplified simulation
    STANDARD = "standard"     # Full agent integration
    MONTE_CARLO = "monte_carlo"  # Stress testing


@dataclass
class StrategyBacktestConfig:
    """Configuration for strategy backtesting."""
    # Capital & sizing
    initial_capital: float = 1000000
    position_size_pct: float = 0.02
    max_positions: int = 3
    max_margin_pct: float = 0.40
    
    # Strategy selection
    strategies: List[str] = field(default_factory=lambda: ["iron_condor"])
    
    # Asset class: equity, commodity, or multi_asset
    asset_class: str = "equity"
    symbol: str = "NIFTY"
    
    # Time filters
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    
    # Execution assumptions
    slippage_pct: float = SLIPPAGE_PCT
    brokerage_pct: float = BROKERAGE_PCT
    
    # Options simulation
    simulate_theta_decay: bool = True
    simulate_iv_changes: bool = True
    
    # Risk limits
    max_loss_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    stop_on_daily_loss: bool = True
    
    # Monte Carlo settings
    num_simulations: int = 1000
    shuffle_trades: bool = True


@dataclass
class BacktestTrade:
    """Record of a completed backtest trade."""
    id: str
    strategy_type: str
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    max_profit: float
    max_loss: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    holding_days: int
    regime_at_entry: str
    regime_at_exit: str
    legs: List[Dict] = field(default_factory=list)
    costs: float = 0.0
    metadata: Dict = field(default_factory=dict)


@dataclass
class BacktestPosition:
    """Active position during backtest."""
    id: str
    strategy_type: str
    entry_date: datetime
    entry_price: float
    max_profit: float
    max_loss: float
    target_pnl: float
    stop_loss: float
    expiry: date
    regime_at_entry: str
    legs: List[Dict] = field(default_factory=list)
    current_pnl: float = 0.0
    days_held: int = 0


@dataclass
class BacktestResult:
    """Complete backtest results."""
    # Configuration
    config: StrategyBacktestConfig
    
    # Summary metrics
    total_return: float = 0.0
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    
    # Trade stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_holding_days: float = 0.0
    
    # By strategy
    by_strategy: Dict[str, Dict] = field(default_factory=dict)
    
    # By regime
    by_regime: Dict[str, Dict] = field(default_factory=dict)
    
    # Time series
    equity_curve: List[float] = field(default_factory=list)
    drawdown_curve: List[float] = field(default_factory=list)
    daily_pnl: List[Dict] = field(default_factory=list)
    
    # Trade list
    trades: List[BacktestTrade] = field(default_factory=list)
    
    # Regime analysis
    regime_accuracy: float = 0.0
    regime_distribution: Dict[str, int] = field(default_factory=dict)


class StrategyBacktester:
    """
    Full-featured strategy backtester with agent integration.
    
    Usage:
        backtester = StrategyBacktester(config)
        result = backtester.run(data)
    """
    
    def __init__(
        self,
        config: Optional[StrategyBacktestConfig] = None,
        settings: Optional[Settings] = None
    ):
        self.config = config or StrategyBacktestConfig()
        self.settings = settings or Settings()
        
        # State
        self._capital: float = 0
        self._positions: Dict[str, BacktestPosition] = {}
        self._trades: List[BacktestTrade] = []
        self._equity_curve: List[float] = []
        self._daily_pnl: List[Dict] = []
        self._current_date: Optional[date] = None
        self._daily_pnl_amount: float = 0
        
        # Regime tracking
        self._regime_history: List[Dict] = []
        self._current_regime: Optional[RegimeType] = None
        
        # Trade counter
        self._trade_counter: int = 0
    
    def run(
        self,
        ohlcv_data: pd.DataFrame,
        mode: BacktestMode = BacktestMode.STANDARD
    ) -> BacktestResult:
        """
        Run backtest on historical data.
        
        Args:
            ohlcv_data: DataFrame with OHLCV data (datetime index)
            mode: Backtest execution mode
            
        Returns:
            BacktestResult with comprehensive metrics
        """
        logger.info(f"Starting {mode.value} backtest: {len(ohlcv_data)} bars")
        
        self._reset()
        self._capital = self.config.initial_capital
        self._equity_curve = [self._capital]
        
        # Ensure sorted
        ohlcv_data = ohlcv_data.sort_index()
        
        # Filter by date range
        if self.config.start_date:
            ohlcv_data = ohlcv_data[ohlcv_data.index.date >= self.config.start_date]
        if self.config.end_date:
            ohlcv_data = ohlcv_data[ohlcv_data.index.date <= self.config.end_date]
        
        if len(ohlcv_data) < 30:
            logger.warning("Insufficient data for backtest")
            return self._build_result()
        
        # Pre-calculate indicators for the entire dataset
        indicators = self._calculate_all_indicators(ohlcv_data)
        
        # Main backtest loop
        warmup = 30  # Need 30 bars for indicator warmup
        for i in range(warmup, len(ohlcv_data)):
            bar = ohlcv_data.iloc[i]
            bar_date = bar.name.date() if hasattr(bar.name, 'date') else ohlcv_data.index[i].date()
            
            # New day handling
            if self._current_date != bar_date:
                self._on_new_day(bar_date)
            
            # Check daily loss limit
            if self.config.stop_on_daily_loss:
                if self._daily_pnl_amount / self._capital <= -self.config.max_daily_loss:
                    continue
            
            # 1. Detect regime
            regime_packet = self._detect_regime(ohlcv_data.iloc[:i+1], indicators, i)
            self._regime_history.append({
                "date": bar_date,
                "regime": regime_packet.regime.value,
                "confidence": regime_packet.regime_confidence
            })
            self._current_regime = regime_packet.regime
            
            # 2. Check exits for open positions
            self._check_exits(bar, regime_packet)
            
            # 3. Generate and evaluate new signals
            if len(self._positions) < self.config.max_positions:
                self._check_entries(bar, regime_packet, ohlcv_data.iloc[:i+1])
            
            # 4. Update equity curve
            unrealized = self._calculate_unrealized_pnl(bar)
            self._equity_curve.append(self._capital + unrealized)
        
        # Close remaining positions
        if ohlcv_data.empty:
            return self._build_result()
            
        final_bar = ohlcv_data.iloc[-1]
        for pos_id in list(self._positions.keys()):
            self._close_position(pos_id, final_bar, "END_OF_BACKTEST")
        
        return self._build_result()
    
    def run_monte_carlo(
        self,
        ohlcv_data: pd.DataFrame,
        num_simulations: Optional[int] = None
    ) -> Dict:
        """
        Run Monte Carlo stress test.
        
        Shuffles trade order to test strategy robustness.
        """
        num_sims = num_simulations or self.config.num_simulations
        logger.info(f"Running Monte Carlo with {num_sims} simulations")
        
        # First, run standard backtest to get base trades
        base_result = self.run(ohlcv_data, BacktestMode.STANDARD)
        
        if not base_result.trades:
            return {"error": "No trades to simulate", "base_result": base_result}
        
        # Extract trade returns
        returns = [t.pnl_pct for t in base_result.trades]
        
        # Run simulations
        max_drawdowns = []
        final_returns = []
        failures = 0
        max_acceptable_dd = 0.20
        
        for _ in range(num_sims):
            # Shuffle trade order
            sim_returns = np.random.choice(returns, size=len(returns), replace=True)
            
            # Build equity curve
            equity = [self.config.initial_capital]
            for r in sim_returns:
                equity.append(equity[-1] * (1 + r))
            
            # Calculate drawdown
            peak = np.maximum.accumulate(equity)
            drawdown = (peak - np.array(equity)) / peak
            max_dd = np.max(drawdown)
            
            max_drawdowns.append(max_dd)
            final_returns.append((equity[-1] / equity[0]) - 1)
            
            if max_dd > max_acceptable_dd:
                failures += 1
        
        failure_rate = failures / num_sims
        
        return {
            "base_result": base_result,
            "num_simulations": num_sims,
            "failure_rate": failure_rate,
            "passed": failure_rate <= 0.05,
            "avg_max_drawdown": np.mean(max_drawdowns),
            "worst_drawdown": np.max(max_drawdowns),
            "best_drawdown": np.min(max_drawdowns),
            "avg_return": np.mean(final_returns),
            "median_return": np.median(final_returns),
            "return_5th_percentile": np.percentile(final_returns, 5),
            "return_95th_percentile": np.percentile(final_returns, 95),
            "return_std": np.std(final_returns)
        }
    
    def _reset(self) -> None:
        """Reset backtester state."""
        self._capital = 0
        self._positions = {}
        self._trades = []
        self._equity_curve = []
        self._daily_pnl = []
        self._current_date = None
        self._daily_pnl_amount = 0
        self._regime_history = []
        self._current_regime = None
        self._trade_counter = 0
    
    def _on_new_day(self, new_date: date) -> None:
        """Handle new trading day."""
        if self._current_date:
            # Record previous day's P&L
            self._daily_pnl.append({
                "date": self._current_date.isoformat(),
                "pnl": self._daily_pnl_amount,
                "equity": self._capital
            })
        
        self._current_date = new_date
        self._daily_pnl_amount = 0
    
    def _calculate_all_indicators(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Pre-calculate all indicators for efficiency."""
        indicators = {}
        
        # ADX
        indicators['adx'] = calculate_adx(
            data['high'], data['low'], data['close'], period=14
        )
        
        # RSI
        indicators['rsi'] = calculate_rsi(data['close'], period=14)
        
        # ATR
        indicators['atr'] = calculate_atr(
            data['high'], data['low'], data['close'], period=14
        )
        
        # Realized volatility
        indicators['rv'] = calculate_realized_vol(data['close'], period=20)
        
        # IV percentile proxy (using Parkinson vol)
        log_hl = np.log(data['high'] / data['low'])
        vol = np.sqrt(1 / (4 * np.log(2)) * (log_hl ** 2))
        indicators['iv_proxy'] = vol.rolling(252).apply(
            lambda x: (x < x.iloc[-1]).sum() / len(x) * 100 if len(x) > 0 else 50
        )
        
        return indicators
    
    def _detect_regime(
        self,
        data: pd.DataFrame,
        indicators: Dict[str, pd.Series],
        idx: int
    ) -> RegimePacket:
        """Detect regime from indicators at given index."""
        # Get indicator values at current index
        adx = indicators['adx'].iloc[idx] if idx < len(indicators['adx']) else 15.0
        rsi = indicators['rsi'].iloc[idx] if idx < len(indicators['rsi']) else 50.0
        atr = indicators['atr'].iloc[idx] if idx < len(indicators['atr']) else 0.0
        rv = indicators['rv'].iloc[idx] if idx < len(indicators['rv']) else 0.15
        iv_pct = indicators['iv_proxy'].iloc[idx] if idx < len(indicators['iv_proxy']) else 50.0
        
        # Handle NaN values
        adx = float(adx) if not np.isnan(adx) else 15.0
        rsi = float(rsi) if not np.isnan(rsi) else 50.0
        iv_pct = float(iv_pct) if not np.isnan(iv_pct) else 50.0
        rv = float(rv) if not np.isnan(rv) else 0.15
        atr = float(atr) if not np.isnan(atr) else 0.0
        
        # Classify regime
        regime, confidence = self._classify_regime(adx, rsi, iv_pct)
        
        # Get price context
        spot = data['close'].iloc[-1]
        prev_close = data['close'].iloc[-2] if len(data) > 1 else spot
        day_range = (data['high'].iloc[-1] - data['low'].iloc[-1]) / spot
        gap = (data['open'].iloc[-1] - prev_close) / prev_close if prev_close > 0 else 0
        
        metrics = RegimeMetrics(
            adx=adx,
            rsi=rsi,
            iv_percentile=iv_pct,
            realized_vol=rv,
            atr=atr,
            rv_atr_ratio=rv / (atr / spot) if atr > 0 else 1.0
        )
        
        return RegimePacket(
            timestamp=data.index[-1] if hasattr(data.index[-1], 'timestamp') else datetime.now(),
            instrument_token=256265,  # NIFTY token
            symbol="NIFTY",
            regime=regime,
            regime_confidence=confidence,
            metrics=metrics,
            event_flag=False,
            correlations={},
            is_safe=regime not in [RegimeType.CHAOS],
            safety_reasons=[],
            spot_price=spot,
            prev_close=prev_close,
            day_range_pct=day_range,
            gap_pct=gap
        )
    
    def _classify_regime(
        self,
        adx: float,
        rsi: float,
        iv_pct: float
    ) -> Tuple[RegimeType, float]:
        """Classify regime based on indicators."""
        # CHAOS: High IV
        if iv_pct > 75:
            return RegimeType.CHAOS, 0.85
        
        # RANGE_BOUND: Low ADX, neutral RSI
        if adx < 12 and 40 <= rsi <= 60:
            return RegimeType.RANGE_BOUND, 0.80
        
        # MEAN_REVERSION: Moderate ADX, extreme RSI
        if 12 <= adx <= 25 and (rsi < 30 or rsi > 70):
            return RegimeType.MEAN_REVERSION, 0.75
        
        # TREND: High ADX
        if adx > 25:
            return RegimeType.TREND, 0.70
        
        # Default: MEAN_REVERSION
        return RegimeType.MEAN_REVERSION, 0.55
    
    def _check_entries(
        self,
        bar: pd.Series,
        regime: RegimePacket,
        data: pd.DataFrame
    ) -> None:
        """Check for entry signals based on regime and strategy."""
        # Skip if regime not safe
        if not regime.is_safe:
            return
        
        # Check margin utilization
        used_margin = sum(p.max_loss for p in self._positions.values())
        if used_margin / self._capital > self.config.max_margin_pct:
            return
        
        # Generate signals based on regime
        for strategy in self.config.strategies:
            if self._should_enter(strategy, regime, bar):
                self._open_position(strategy, regime, bar)
                break  # One entry per bar
    
    def _should_enter(
        self,
        strategy: str,
        regime: RegimePacket,
        bar: pd.Series
    ) -> bool:
        """Check if strategy should enter based on regime."""
        strategy_lower = strategy.lower()
        
        if strategy_lower == "iron_condor":
            # IC: RANGE_BOUND, IV > 40%
            return (
                regime.regime == RegimeType.RANGE_BOUND and
                regime.metrics.iv_percentile > 40 and
                regime.day_range_pct < 0.012 and
                abs(regime.gap_pct) < 0.015
            )
        
        elif strategy_lower == "jade_lizard":
            # JL: RANGE_BOUND or CAUTION, IV > 35%
            return (
                regime.regime in [RegimeType.RANGE_BOUND, RegimeType.CAUTION] and
                regime.metrics.iv_percentile > 35
            )
        
        elif strategy_lower == "butterfly":
            # Butterfly: RANGE_BOUND, high confidence
            return (
                regime.regime == RegimeType.RANGE_BOUND and
                regime.regime_confidence > 0.75 and
                regime.metrics.iv_percentile > 30
            )
        
        elif strategy_lower == "bwb":
            # BWB: MEAN_REVERSION
            return (
                regime.regime == RegimeType.MEAN_REVERSION and
                (regime.metrics.rsi < 30 or regime.metrics.rsi > 70)
            )
        
        elif strategy_lower == "risk_reversal":
            # RR: MEAN_REVERSION with directional bias
            return (
                regime.regime == RegimeType.MEAN_REVERSION and
                (regime.metrics.rsi < 25 or regime.metrics.rsi > 75)
            )
        
        elif strategy_lower == "range_forward":
            # Range Forward: Mean-reversion at ATR bounds
            # Entry when price deviates > 1.5x ATR from previous close
            atr = regime.metrics.atr
            spot = regime.spot_price
            prev = regime.prev_close
            if atr > 0 and prev > 0:
                deviation = abs(spot - prev) / atr
                return (
                    regime.regime in [RegimeType.RANGE_BOUND, RegimeType.MEAN_REVERSION] and
                    deviation > 1.5 and
                    regime.metrics.adx < 25
                )
            return False
        
        elif strategy_lower == "commodity_mean_reversion":
            # Commodity mean-reversion: For Gold/Crude
            # Entry on extreme RSI with low ADX
            return (
                regime.regime == RegimeType.MEAN_REVERSION and
                (regime.metrics.rsi < 30 or regime.metrics.rsi > 70) and
                regime.metrics.adx < 20
            )
        
        elif strategy_lower == "pairs_trade":
            # Pairs trade: For correlated assets (Gold/Silver, NIFTY/BANKNIFTY)
            # Simplified: Enter on mean-reversion signals
            return (
                regime.regime == RegimeType.MEAN_REVERSION and
                regime.metrics.adx < 25 and
                (regime.metrics.rsi < 35 or regime.metrics.rsi > 65)
            )
        
        elif strategy_lower == "delta_hedge":
            # Delta hedge: Protective position when trending
            return (
                regime.regime == RegimeType.TREND and
                regime.metrics.adx > 25
            )
        
        elif strategy_lower == "protective_put":
            # Protective put: Hedge existing long exposure
            # Enter when IV is low and regime is uncertain
            return (
                regime.metrics.iv_percentile < 40 and
                regime.regime in [RegimeType.MEAN_REVERSION, RegimeType.TREND]
            )
        
        elif strategy_lower == "collar":
            # Collar: Long put + short call for hedged exposure
            return (
                regime.regime in [RegimeType.RANGE_BOUND, RegimeType.CAUTION] and
                regime.metrics.iv_percentile > 30
            )
        
        return False
    
    def _open_position(
        self,
        strategy: str,
        regime: RegimePacket,
        bar: pd.Series
    ) -> None:
        """Open a new position."""
        self._trade_counter += 1
        pos_id = f"BT_{strategy.upper()}_{self._trade_counter}"
        
        # Calculate position parameters based on strategy
        spot = bar['close']
        
        if strategy.lower() == "iron_condor":
            # IC: Credit spread, max profit = credit, max loss = wing width - credit
            credit = spot * 0.005  # ~0.5% credit
            wing_width = spot * 0.02  # 2% wings
            max_profit = credit
            max_loss = wing_width - credit
            target_pnl = max_profit * 0.6
            stop_loss = -credit
            
        elif strategy.lower() == "jade_lizard":
            credit = spot * 0.006
            max_profit = credit
            max_loss = spot * 0.03
            target_pnl = max_profit * 0.5
            stop_loss = -credit * 1.5
            
        elif strategy.lower() == "butterfly":
            debit = spot * 0.002
            max_profit = spot * 0.01
            max_loss = debit
            target_pnl = max_profit * 0.5
            stop_loss = -debit
            
        elif strategy.lower() in ["bwb", "risk_reversal"]:
            debit = spot * 0.003
            max_profit = spot * 0.02
            max_loss = debit
            target_pnl = max_profit * 0.4
            stop_loss = -debit * 1.5
        
        elif strategy.lower() == "range_forward":
            # Range Forward: Directional play with hedge
            # Long underlying + protective option
            debit = spot * 0.004
            max_profit = spot * 0.025  # 2.5% target
            max_loss = spot * 0.01  # 1% max loss with hedge
            target_pnl = max_profit * 0.6
            stop_loss = -max_loss
        
        elif strategy.lower() == "commodity_mean_reversion":
            # Commodity mean-reversion
            debit = spot * 0.002
            max_profit = spot * 0.015
            max_loss = spot * 0.01
            target_pnl = max_profit * 0.5
            stop_loss = -max_loss
        
        elif strategy.lower() == "pairs_trade":
            # Pairs trade: Market neutral
            debit = spot * 0.001  # Low cost due to hedged nature
            max_profit = spot * 0.01
            max_loss = spot * 0.005
            target_pnl = max_profit * 0.5
            stop_loss = -max_loss
        
        elif strategy.lower() == "delta_hedge":
            # Delta hedge: Futures overlay
            debit = spot * 0.001
            max_profit = spot * 0.005  # Small profit from hedge
            max_loss = spot * 0.003
            target_pnl = max_profit * 0.8
            stop_loss = -max_loss
        
        elif strategy.lower() == "protective_put":
            # Protective put: Insurance cost
            debit = spot * 0.003  # Premium paid
            max_profit = spot * 0.02  # Upside from underlying
            max_loss = debit  # Max loss is premium
            target_pnl = max_profit * 0.4
            stop_loss = -debit
        
        elif strategy.lower() == "collar":
            # Collar: Long put + short call
            net_cost = spot * 0.001  # Near zero cost
            max_profit = spot * 0.015  # Capped upside
            max_loss = spot * 0.01  # Limited downside
            target_pnl = max_profit * 0.5
            stop_loss = -max_loss
            debit = net_cost
            
        else:
            return
        
        # Apply position sizing
        size_multiplier = self.config.position_size_pct * self._capital / max_loss
        max_profit *= size_multiplier
        max_loss *= size_multiplier
        target_pnl *= size_multiplier
        stop_loss *= size_multiplier
        
        # Expiry: ~10 days out
        expiry = self._current_date + timedelta(days=10)
        
        position = BacktestPosition(
            id=pos_id,
            strategy_type=strategy,
            entry_date=bar.name if hasattr(bar.name, 'date') else datetime.now(),
            entry_price=spot,
            max_profit=max_profit,
            max_loss=max_loss,
            target_pnl=target_pnl,
            stop_loss=stop_loss,
            expiry=expiry,
            regime_at_entry=regime.regime.value
        )
        
        self._positions[pos_id] = position
        logger.debug(f"Opened {strategy} position: {pos_id}")
    
    def _check_exits(self, bar: pd.Series, regime: RegimePacket) -> None:
        """Check exit conditions for all positions."""
        positions_to_close = []
        
        for pos_id, position in self._positions.items():
            exit_reason = self._get_exit_reason(position, bar, regime)
            if exit_reason:
                positions_to_close.append((pos_id, exit_reason))
        
        for pos_id, reason in positions_to_close:
            self._close_position(pos_id, bar, reason)
    
    def _get_exit_reason(
        self,
        position: BacktestPosition,
        bar: pd.Series,
        regime: RegimePacket
    ) -> Optional[str]:
        """Determine if position should be exited."""
        # Update position P&L
        spot = bar['close']
        entry = position.entry_price
        
        # Simulate P&L based on strategy type
        if position.strategy_type.lower() in ["iron_condor", "jade_lizard"]:
            # Credit strategies: profit from theta decay
            days_held = position.days_held + 1
            theta_decay = position.max_profit * (days_held / 10) * 0.7
            price_impact = (spot - entry) / entry * position.max_loss * 2
            position.current_pnl = theta_decay - abs(price_impact)
        else:
            # Debit strategies
            price_move = (spot - entry) / entry
            position.current_pnl = price_move * position.max_profit
        
        position.days_held += 1
        
        # Check profit target
        if position.current_pnl >= position.target_pnl:
            return "PROFIT_TARGET"
        
        # Check stop loss
        if position.current_pnl <= position.stop_loss:
            return "STOP_LOSS"
        
        # Check expiry
        bar_date = bar.name.date() if hasattr(bar.name, 'date') else self._current_date
        if bar_date and position.expiry and bar_date >= position.expiry - timedelta(days=2):
            return "EXPIRY_EXIT"
        
        # Check regime change to CHAOS
        if regime.regime == RegimeType.CHAOS:
            return "REGIME_CHAOS"
        
        # Time-based exit for short-vol
        if position.strategy_type.lower() in ["iron_condor", "jade_lizard"]:
            if position.days_held >= 8:
                return "TIME_EXIT"
        
        return None
    
    def _close_position(
        self,
        pos_id: str,
        bar: pd.Series,
        reason: str
    ) -> None:
        """Close a position and record the trade."""
        position = self._positions.pop(pos_id)
        
        # Calculate final P&L with costs
        pnl = position.current_pnl
        costs = abs(pnl) * self.config.brokerage_pct * 2
        pnl -= costs
        
        # Apply slippage
        slippage = abs(pnl) * self.config.slippage_pct
        pnl -= slippage
        
        # Update capital
        self._capital += pnl
        self._daily_pnl_amount += pnl
        
        # Calculate P&L percentage
        pnl_pct = pnl / (self.config.initial_capital * self.config.position_size_pct)
        
        # Record trade
        trade = BacktestTrade(
            id=pos_id,
            strategy_type=position.strategy_type,
            entry_date=position.entry_date,
            exit_date=bar.name if hasattr(bar.name, 'date') else datetime.now(),
            entry_price=position.entry_price,
            exit_price=bar['close'],
            max_profit=position.max_profit,
            max_loss=position.max_loss,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            holding_days=position.days_held,
            regime_at_entry=position.regime_at_entry,
            regime_at_exit=self._current_regime.value if self._current_regime else "UNKNOWN",
            costs=costs + slippage
        )
        
        self._trades.append(trade)
        logger.debug(f"Closed {pos_id}: P&L={pnl:.2f} ({reason})")
    
    def _calculate_unrealized_pnl(self, bar: pd.Series) -> float:
        """Calculate unrealized P&L for open positions."""
        return sum(p.current_pnl for p in self._positions.values())
    
    def _build_result(self) -> BacktestResult:
        """Build comprehensive backtest result."""
        result = BacktestResult(config=self.config)
        
        if not self._trades:
            result.equity_curve = self._equity_curve
            return result
        
        # Convert trades to dict format for metrics calculation
        trades_dict = [
            {
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "holding_days": t.holding_days,
                "exit_date": t.exit_date
            }
            for t in self._trades
        ]
        
        # Calculate metrics
        metrics = calculate_metrics(trades_dict, self.config.initial_capital)
        
        # Populate result
        result.total_return = metrics.get("total_return", 0)
        result.total_return_pct = metrics.get("total_return_pct", 0)
        result.sharpe_ratio = metrics.get("sharpe_ratio", 0)
        result.sortino_ratio = metrics.get("sortino_ratio", 0)
        result.max_drawdown = metrics.get("max_drawdown", 0)
        result.max_drawdown_duration = metrics.get("max_drawdown_duration", 0)
        result.win_rate = metrics.get("win_rate", 0)
        result.profit_factor = metrics.get("profit_factor", 0)
        result.avg_win = metrics.get("avg_win", 0)
        result.avg_loss = metrics.get("avg_loss", 0)
        result.expectancy = metrics.get("expectancy", 0)
        result.total_trades = len(self._trades)
        result.winning_trades = len([t for t in self._trades if t.pnl > 0])
        result.losing_trades = len([t for t in self._trades if t.pnl < 0])
        result.avg_holding_days = metrics.get("avg_holding_days", 0)
        
        # By strategy
        for strategy in set(t.strategy_type for t in self._trades):
            strat_trades = [t for t in self._trades if t.strategy_type == strategy]
            strat_pnls = [t.pnl for t in strat_trades]
            wins = [p for p in strat_pnls if p > 0]
            losses = [p for p in strat_pnls if p < 0]
            
            result.by_strategy[strategy] = {
                "total_trades": len(strat_trades),
                "total_pnl": sum(strat_pnls),
                "win_rate": len(wins) / len(strat_trades) if strat_trades else 0,
                "avg_pnl": np.mean(strat_pnls) if strat_pnls else 0,
                "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
            }
        
        # By regime
        for regime in set(t.regime_at_entry for t in self._trades):
            regime_trades = [t for t in self._trades if t.regime_at_entry == regime]
            regime_pnls = [t.pnl for t in regime_trades]
            wins = [p for p in regime_pnls if p > 0]
            
            result.by_regime[regime] = {
                "total_trades": len(regime_trades),
                "total_pnl": sum(regime_pnls),
                "win_rate": len(wins) / len(regime_trades) if regime_trades else 0
            }
        
        # Time series
        result.equity_curve = self._equity_curve
        result.daily_pnl = self._daily_pnl
        result.trades = self._trades
        
        # Drawdown curve
        if self._equity_curve:
            equity = np.array(self._equity_curve)
            peak = np.maximum.accumulate(equity)
            result.drawdown_curve = ((peak - equity) / peak).tolist()
        
        # Regime distribution
        result.regime_distribution = {}
        for entry in self._regime_history:
            regime = entry["regime"]
            result.regime_distribution[regime] = result.regime_distribution.get(regime, 0) + 1
        
        return result
