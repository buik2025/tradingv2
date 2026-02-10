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
import os

from ..agents import Sentinel, DataLoader
from ..strategies import Strategist
from ..execution import Treasury
from ..agents.metrics import calculate_metrics, build_equity_curve, calculate_max_drawdown
from ..indicators.technical import calculate_adx, calculate_rsi, calculate_atr
from ..indicators.volatility import calculate_iv_percentile, calculate_realized_vol
from ..execution.circuit_breaker import CircuitBreaker
from ..execution.greek_hedger import GreekHedger
from ...config.settings import Settings
from ...config.thresholds import SLIPPAGE_PCT, BROKERAGE_PCT, COMMISSION_TAX_PCT
from ...models.regime import RegimeType, RegimePacket, RegimeMetrics
from ...models.trade import TradeProposal, StructureType


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
    commission_tax_pct: float = COMMISSION_TAX_PCT
    
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
    capital_before: float = 0.0  # Total capital available before entering trade
    capital_after: float = 0.0  # Total capital after trade closes
    margin_blocked: float = 0.0  # Margin blocked during trade
    free_capital_before: float = 0.0  # Free capital (not blocked) before trade
    free_capital_after: float = 0.0  # Free capital after trade closes


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
    proposal: Optional[Any] = None  # Store TradeProposal for leg details
    margin_blocked: float = 0.0  # Margin blocked for this position


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

        # Initialize strategist for proposal generation
        from ..services.strategist import Strategist
        from ..core.kite_client import KiteClient
        from ..core.credentials import get_kite_credentials
        
        # PRODUCTION MODE: Load real Kite credentials from database. No mock fallback.
        creds = get_kite_credentials()
        if not creds or creds.get('is_expired'):
            raise RuntimeError(
                "Backtester requires valid Kite credentials in database. "
                "No mock client fallback in production mode. "
                "Store credentials via: save_kite_credentials(api_key, api_secret, access_token, user_id)"
            )
        
        # Initialize real Kite client from DB credentials
        kite_client = KiteClient(
            api_key=creds.get('api_key'),
            access_token=creds.get('access_token'),
            paper_mode=True,  # Always use paper_mode for backtesting
            mock_mode=False
        )
        logger.info(f"Backtester initialized with real Kite client (user: {creds.get('user_id')})")
        
        # Use real Kite client for strategist
        self.strategist = Strategist(
            kite=kite_client, 
            config=self.settings, 
            enabled_strategies=self.config.strategies,
            bypass_entry_window=True  # Allow trading anytime in backtest
        )
        
        # Phase 2: Risk management services
        self.circuit_breaker = CircuitBreaker(initial_equity=self.config.initial_capital)
        self.greek_hedger = GreekHedger(equity=self.config.initial_capital)
        
        # State
        self._capital: float = 0
        self._margin_blocked: float = 0  # Total margin currently blocked
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
        
        # NEW: Brake system (Grok Feb 5)
        self._brake_until: Optional[date] = None
        self._brakes_triggered: int = 0
        
        # NEW: Lots ramping tracking
        self._initial_capital: float = 0
    
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
        self._initial_capital = self.config.initial_capital  # For lots ramping
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
            
            # Check daily loss limit and brake system
            if self.config.stop_on_daily_loss:
                if self._daily_pnl_amount / self._capital <= -self.config.max_daily_loss:
                    # NEW: Trigger brake (Grok Feb 5)
                    if self._brake_until is None or bar_date > self._brake_until:
                        self._trigger_brake(bar_date)
                    continue
            
            # NEW: Check if brake is active (Grok Feb 5)
            if self._brake_until and bar_date <= self._brake_until:
                continue  # Skip trading during brake period
            
            # Phase 2: Check circuit breaker halt
            if self.circuit_breaker.is_halted():
                cb_status = self.circuit_breaker.get_status()
                logger.debug(f"Circuit breaker halt active: {cb_status['state']}")
                continue  # Skip trading during halt
            
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
        self._brake_until = None
        self._brakes_triggered = 0
        self._initial_capital = 0
    
    def _trigger_brake(self, current_date: date) -> None:
        """Trigger daily brake after loss limit hit (Grok Feb 5)."""
        from ..config.thresholds import BRAKE_FLAT_DAYS
        self._brake_until = current_date + timedelta(days=BRAKE_FLAT_DAYS)
        self._brakes_triggered += 1
        logger.warning(f"BRAKE TRIGGERED! Flat until {self._brake_until} (brake #{self._brakes_triggered})")
    
    def _calculate_lots(self) -> int:
        """Calculate position lots based on equity growth (Grok Feb 5)."""
        from ..config.thresholds import LOTS_RAMP_THRESHOLD_1, LOTS_RAMP_THRESHOLD_2, MAX_LOTS
        
        if self._initial_capital <= 0:
            return 1
        
        equity_ratio = self._capital / self._initial_capital
        
        if equity_ratio >= LOTS_RAMP_THRESHOLD_2:
            return min(3, MAX_LOTS)
        elif equity_ratio >= LOTS_RAMP_THRESHOLD_1:
            return min(2, MAX_LOTS)
        else:
            return 1
    
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
        """Classify regime based on indicators (updated per Grok Feb 5)."""
        from ..config.thresholds import ADX_RANGE_BOUND, ADX_TREND_MIN, IV_PERCENTILE_CHAOS
        
        # CHAOS: Very high IV (>75%) AND high ADX (>35)
        ADX_CHAOS = 35
        if iv_pct > IV_PERCENTILE_CHAOS and adx > ADX_CHAOS:
            return RegimeType.CHAOS, 0.85
        
        # RANGE_BOUND: Low ADX (<14), any RSI (relaxed from neutral only)
        if adx < ADX_RANGE_BOUND:
            return RegimeType.RANGE_BOUND, 0.80
        
        # MEAN_REVERSION: Moderate ADX (14-25), extreme RSI
        if ADX_RANGE_BOUND <= adx <= ADX_TREND_MIN and (rsi < 30 or rsi > 70):
            return RegimeType.MEAN_REVERSION, 0.75
        
        # TREND: High ADX (>25)
        if adx > ADX_TREND_MIN:
            return RegimeType.TREND, 0.70
        
        # CAUTION: Moderate ADX with neutral RSI
        if ADX_RANGE_BOUND <= adx <= ADX_TREND_MIN:
            return RegimeType.CAUTION, 0.60
        
        # Default: RANGE_BOUND (more permissive for trading)
        return RegimeType.RANGE_BOUND, 0.55
    
    def _execute_proposal(
        self,
        proposal: TradeProposal,
        regime: RegimePacket,
        bar: pd.Series
    ) -> None:
        """Execute a trade proposal from strategist."""
        self._trade_counter += 1
        pos_id = f"BT_{proposal.structure}_{self._trade_counter}"
        
        # Apply position sizing with lots ramping (Grok Feb 5)
        lots = self._calculate_lots()
        position_size_pct = self.config.position_size_pct
        
        # Phase 2: Apply circuit breaker size reduction if triggered
        cb_size_multiplier = self.circuit_breaker.get_size_multiplier()
        
        # Calculate size multiplier based on lots and position size
        size_multiplier = position_size_pct * self._capital / proposal.max_loss * lots * cb_size_multiplier
        
        # Calculate margin requirement for this strategy
        spot = bar['close']
        margin_required = self._calculate_margin_requirement(proposal.structure.lower(), spot, lots)
        free_capital = self._capital - self._margin_blocked
        
        # Check if we have enough free capital for the margin requirement
        if margin_required > free_capital:
            logger.debug(f"Insufficient free capital for {pos_id}: need ₹{margin_required:,.0f}, have ₹{free_capital:,.0f}")
            return
        
        # Translate leg quantities from lots -> contracts using kite instrument lot sizes
        try:
            instruments = self.strategist.kite.get_instruments('NFO')
            lot_map = {str(int(row.get('instrument_token'))): int(row.get('lot_size')) if row.get('lot_size') is not None else int(row.get('lot_size', 1)) for _, row in instruments.iterrows()}
        except Exception:
            # Fallback: use default lot 50 if kite not available
            lot_map = {}

        # Adjust quantities on proposal legs to be actual contracts (lot_size * lots)
        for leg in proposal.legs:
            try:
                # prefer tradingsymbol-based lookup if available
                ts = getattr(leg, 'tradingsymbol', None)
                lot_size = None
                if ts and not instruments.empty:
                    # try to find by tradingsymbol
                    match = instruments[instruments['tradingsymbol'] == ts]
                    if not match.empty:
                        lot_size = int(match.iloc[0].get('lot_size', 50))
                # fallback to token map
                if lot_size is None:
                    token = getattr(leg, 'instrument_token', None)
                    if token is not None and str(int(token)) in lot_map:
                        lot_size = lot_map[str(int(token))]
                if lot_size is None:
                    lot_size = getattr(leg, 'quantity', 50)

                # set quantity = lot_size * lots
                leg.quantity = int(lot_size) * int(lots)
            except Exception:
                # ignore and leave provided quantity
                continue

        # Save required margin into proposal for audit
        try:
            proposal.required_margin = margin_required
        except Exception:
            pass
        
        # Create backtest position from proposal
        position = BacktestPosition(
            id=pos_id,
            strategy_type=proposal.structure.lower(),
            entry_date=bar.name if hasattr(bar.name, 'date') else datetime.now(),
            entry_price=bar['close'],
            max_profit=proposal.max_profit * size_multiplier,
            max_loss=proposal.max_loss * size_multiplier,
            target_pnl=proposal.target_pnl * size_multiplier,
            stop_loss=proposal.stop_loss * size_multiplier,
            expiry=proposal.expiry,
            regime_at_entry=regime.regime.value,
            proposal=proposal,  # Store proposal for leg details
            margin_blocked=margin_required  # Track blocked margin
        )
        
        # Block the margin
        self._margin_blocked += margin_required
        
        self._positions[pos_id] = position
        logger.debug(f"Executed proposal {pos_id}: {proposal.structure} at {bar['close']:.2f}, margin blocked: ₹{margin_required:,.0f}")

    
    def _check_entries(
        self,
        bar: pd.Series,
        regime: RegimePacket,
        data: pd.DataFrame
    ) -> None:
        """Check for entry signals using strategist."""
        # Skip if regime not safe
        if not regime.is_safe:
            return
        
        # Check if we're at max positions
        if len(self._positions) >= self.config.max_positions:
            return
        
        # Check margin utilization based on blocked margin
        free_capital = self._capital - self._margin_blocked
        margin_utilization = self._margin_blocked / self._capital
        if margin_utilization > self.config.max_margin_pct:  # 40% max margin by default
            logger.debug(f"Max margin utilization reached: {margin_utilization:.1%} > {self.config.max_margin_pct:.1%}")
            return

        
        # Use strategist to generate proposals
        proposals = self.strategist.process(regime)
        
        # Execute the best proposal (if any)
        for proposal in proposals[:1]:  # Take only the best one
            self._execute_proposal(proposal, regime, bar)
            break  # One entry per bar
    
    def _calculate_margin_requirement(self, strategy: str, spot: float, num_lots: int = 1) -> float:
        """
        Calculate margin requirement for a strategy based on legs and lot size.
        
        Margin per short leg (NIFTY options): ~₹1.8L per lot
        Long legs reduce margin due to protection.
        
        Returns: Total margin blocked for this position in rupees
        """
        # Base margin per short leg per lot (NIFTY standard)
        margin_per_short_leg = 180000  # ₹1.8L per lot
        
        strategy_lower = strategy.lower()

        # Attempt to use live Kite margins if credentials are present in DB
        try:
            from ..core.credentials import get_kite_credentials
            from ..core.kite_client import KiteClient

            creds = get_kite_credentials()
            if creds and not creds.get('is_expired'):
                # Initialize Kite client with DB credentials (paper_mode True)
                kite = KiteClient(api_key=creds.get('api_key'), access_token=creds.get('access_token'), paper_mode=True, mock_mode=False)

                # Try to find a representative tradingsymbol and lot size from instruments
                try:
                    instruments = kite.get_instruments('NFO')
                    lot_size = None
                    sample_symbol = None
                    if hasattr(instruments, 'iterrows'):
                        for _, row in instruments.iterrows():
                            # Prefer NIFTY options
                            name = row.get('name') or row.get('tradingsymbol')
                            if isinstance(name, str) and 'NIFTY' in str(name).upper():
                                lot_size = int(row.get('lot_size') or row.get('lot')) if row.get('lot_size') or row.get('lot') else None
                                sample_symbol = row.get('tradingsymbol')
                                break

                    # Build a simple basket payload based on strategy short leg count
                    if sample_symbol and lot_size:
                        orders = []
                        short_legs = 1
                        if strategy_lower == 'iron_condor':
                            short_legs = 2
                        elif strategy_lower == 'jade_lizard':
                            short_legs = 2
                        elif strategy_lower == 'butterfly':
                            short_legs = 1
                        elif strategy_lower in ['bwb', 'risk_reversal']:
                            short_legs = 1

                        qty = int(lot_size * num_lots)
                        for i in range(short_legs):
                            orders.append({
                                'exchange': 'NFO',
                                'tradingsymbol': sample_symbol,
                                'transaction_type': 'SELL',
                                'quantity': qty,
                                'order_type': 'MARKET',
                                'product': 'NRML'
                            })

                        basket = {'orders': orders}
                        resp = kite.get_basket_margins(basket)
                        # Parse common response shapes
                        if isinstance(resp, dict):
                            if 'required_margin' in resp:
                                return float(resp.get('required_margin') or 0.0)
                            if 'data' in resp and isinstance(resp['data'], dict) and 'required_margin' in resp['data']:
                                return float(resp['data']['required_margin'] or 0.0)
                            # Some APIs return list of margins
                            if 'details' in resp and isinstance(resp['details'], list):
                                total = 0.0
                                for d in resp['details']:
                                    total += float(d.get('required_margin') or 0.0)
                                if total > 0:
                                    return total

                except Exception as e:
                    logger.debug(f"Kite margins attempt failed, falling back to heuristic: {e}")
        except Exception:
            # Any failure in credential lookup or kite init - ignore and use heuristic
            pass
        
        if strategy_lower == "iron_condor":
            # IC: 2 short legs (1 PUT + 1 CALL)
            # Long legs provide protection, reduce requirement
            margin = margin_per_short_leg * 2 * num_lots * 0.9  # 10% reduction for long protection
            return margin
        
        elif strategy_lower == "jade_lizard":
            # JL: 2 short legs (1 PUT + 1 CALL) + 1 long leg
            # Long leg reduces margin significantly
            margin = margin_per_short_leg * 2 * num_lots * 0.8  # 20% reduction
            return margin
        
        elif strategy_lower == "butterfly":
            # Butterfly: Net credit spread, lower margin
            margin = margin_per_short_leg * 0.6 * num_lots  # 40% of standard
            return margin
        
        elif strategy_lower in ["bwb", "risk_reversal"]:
            # Broken Wing / Risk Reversal: Some short exposure
            margin = margin_per_short_leg * 1.5 * num_lots * 0.85
            return margin
        
        elif strategy_lower == "range_forward":
            # Range Forward: Directional hedge, lower margin
            margin = margin_per_short_leg * 0.5 * num_lots
            return margin
        
        else:
            # Default: Assume 1 short leg equivalent
            margin = margin_per_short_leg * num_lots
            return margin
    
    def _should_enter(
        self,
        strategy: str,
        regime: RegimePacket,
        bar: pd.Series
    ) -> bool:
        """
        Check if strategy should enter based on regime.
        
        Uses unified StrategySelector from v2 rulebook to ensure
        backtester and live trading use identical entry rules.
        """
        from .strategy_selector import StrategySelector
        from ..models.trade import StructureType
        
        # Map strategy string to StructureType
        structure_map = {
            'iron_condor': StructureType.IRON_CONDOR,
            'jade_lizard': StructureType.JADE_LIZARD,
            'butterfly': StructureType.BUTTERFLY,
            'bwb': StructureType.BROKEN_WING_BUTTERFLY,
            'broken_wing_butterfly': StructureType.BROKEN_WING_BUTTERFLY,
            'risk_reversal': StructureType.RISK_REVERSAL,
            'naked_strangle': StructureType.NAKED_STRANGLE,
        }
        
        structure = structure_map.get(strategy.lower())
        if not structure:
            logger.warning(f"Unknown strategy in _should_enter: {strategy}")
            return False
        
        # Get all suitable structures for current regime
        suitable = StrategySelector.get_suitable_structures(regime)
        
        # Check if this structure is suitable and meets entry conditions
        for struct, conditions in suitable:
            if struct == structure:
                should_enter, reason = StrategySelector.should_enter_structure(
                    structure, regime, conditions
                )
                if should_enter:
                    logger.debug(f"Entry check {strategy}: PASS - {reason}")
                else:
                    logger.debug(f"Entry check {strategy}: FAIL - {reason}")
                return should_enter
        
        logger.debug(f"Strategy {strategy} not suitable for regime {regime.regime}")
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
        
        # Apply position sizing with lots ramping (Grok Feb 5)
        lots = self._calculate_lots()
        size_multiplier = self.config.position_size_pct * self._capital / max_loss * lots
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
        elif position.strategy_type.lower() == "naked_strangle":
            # Strangle: profit from theta decay, but sensitive to directional moves
            days_held = position.days_held + 1
            theta_decay = position.max_profit * (days_held / 10) * 0.8  # Higher theta for naked options
            
            # Calculate directional impact (strangle is more sensitive to direction)
            # If spot moves significantly in either direction, losses increase
            move_pct = abs(spot - entry) / entry
            if move_pct > 0.05:  # 5% move starts hurting
                directional_loss = position.max_loss * (move_pct - 0.05) * 3  # Accelerating losses
                position.current_pnl = theta_decay - directional_loss
            else:
                position.current_pnl = theta_decay
        else:
            # Debit strategies
            price_move = (spot - entry) / entry
            position.current_pnl = price_move * position.max_profit
        
        position.days_held += 1
        
        # Check profit target with trailing logic (Grok Feb 5)
        if position.current_pnl >= position.target_pnl:
            # NEW: Check if we should trail instead of exit
            if self._should_trail_profit(position, regime):
                # Extend target by 20%
                from ..config.thresholds import TRAILING_EXTENSION
                position.target_pnl *= TRAILING_EXTENSION
                logger.debug(f"Trailing profit for {position.id}: new target {position.target_pnl:.2f}")
                return None  # Don't exit yet
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
    
    def _should_trail_profit(self, position: BacktestPosition, regime: RegimePacket) -> bool:
        """
        Check if position should trail profit instead of exiting (Grok Feb 5).
        
        Trail when:
        - BBW > 1.8x 20-day average (vol expansion favorable for continuation)
        - Already at 50%+ of target profit
        - Regime is still favorable (RANGE_BOUND or MEAN_REVERSION)
        """
        from ..config.thresholds import TRAILING_BBW_THRESHOLD, TRAILING_PROFIT_MIN
        
        # Only trail if at minimum profit threshold
        if position.current_pnl < position.target_pnl * TRAILING_PROFIT_MIN:
            return False
        
        # Only trail in favorable regimes
        if regime.regime not in [RegimeType.RANGE_BOUND, RegimeType.MEAN_REVERSION]:
            return False
        
        # Check BBW ratio (use ADX as proxy if BBW not available)
        # Lower ADX = more range-bound = better for trailing short-vol
        if regime.metrics.adx < 20:
            return True
        
        return False
    
    def _close_position(
        self,
        pos_id: str,
        bar: pd.Series,
        reason: str
    ) -> None:
        """Close a position and record the trade."""
        position = self._positions.pop(pos_id)
        
        # Release the blocked margin
        self._margin_blocked -= position.margin_blocked
        
        # Order-based costs (Realistic Zerodha/NSE model)
        pnl = position.current_pnl
        
        # 1. Brokerage: Flat 20 Rs per order (Entry + Exit = 40)
        # 2. Charges: ~0.053% of PREMIUM turnover (NSE + STT)
        # 3. Commission & taxes: 0.08% of turnover (per user request)

        flat_brokerage = 40  # 20 entry + 20 exit

        # Estimate turnover based on max_profit (approx premium collected/paid)
        # This is a simplification, but much better than Notional on Spot
        turnover = position.max_profit * 2  # Buy + Sell
        charges = turnover * 0.00053

        # Commission and taxes (configured percentage)
        commission_tax = turnover * self.config.commission_tax_pct

        order_costs = flat_brokerage + charges + commission_tax
        if position.strategy_type.lower() in ["iron_condor", "jade_lizard"]:
            # Complex strategies have more legs, so higher brokerage
            order_costs += 40  # Extra legs
            
        pnl -= order_costs
        
        # Apply slippage
        slippage = abs(pnl) * self.config.slippage_pct
        pnl -= slippage
        
        costs = order_costs + slippage
        
        # Update capital
        self._capital += pnl
        self._daily_pnl_amount += pnl
        
        # Calculate P&L percentage relative to margin blocked (used capital)
        if position.margin_blocked and position.margin_blocked > 0:
            pnl_pct = (pnl / position.margin_blocked) * 100.0
        else:
            # Fallback to percentage of initial capital
            pnl_pct = (pnl / self.config.initial_capital) * 100.0
        
        # Extract legs from proposal with proper option pricing
        trade_legs = []
        if position.proposal and hasattr(position.proposal, 'legs'):
            try:
                from .option_pricing import OptionPricingEngine
                
                # Initialize pricing engine
                pricing_engine = OptionPricingEngine()
                
                # Get entry and exit dates
                entry_date = position.entry_date.date() if hasattr(position.entry_date, 'date') else position.entry_date
                exit_date = bar.name.date() if hasattr(bar.name, 'date') else datetime.now().date() if isinstance(bar.name, datetime) else bar.name
                
                for leg in position.proposal.legs:
                    try:
                        # Use Black-Scholes to calculate option prices
                        entry_price, exit_price, leg_pnl = pricing_engine.calculate_leg_pnl(
                            leg_type=leg.leg_type.value,
                            strike=leg.strike,
                            expiry_date=position.proposal.expiry,
                            entry_date=entry_date,
                            exit_date=exit_date,
                            entry_underlying=position.entry_price,
                            exit_underlying=bar['close'],
                            quantity=leg.quantity,
                            entry_volatility=0.20,  # Default 20% IV
                            exit_volatility=0.20
                        )
                        
                        trade_legs.append({
                            'type': leg.leg_type.value,
                            'strike': leg.strike,
                            'side': 'long' if leg.is_long else 'short',
                            'option_type': leg.option_type,
                            'quantity': leg.quantity,
                            'expiry': position.proposal.expiry.isoformat() if hasattr(position.proposal.expiry, 'isoformat') else str(position.proposal.expiry),
                            'entry_price': round(entry_price, 2),  # Option price at entry
                            'exit_price': round(exit_price, 2),     # Option price at exit
                            'pnl': round(leg_pnl, 2),               # Individual leg P&L
                            'pnl_per_contract': round(leg_pnl / leg.quantity, 2) if leg.quantity > 0 else 0.0
                        })
                    except Exception as e:
                        # Fallback if pricing fails
                        logger.debug(f"Option pricing failed for leg {leg.leg_type}: {str(e)}")
                        trade_legs.append({
                            'type': leg.leg_type.value,
                            'strike': leg.strike,
                            'side': 'long' if leg.is_long else 'short',
                            'option_type': leg.option_type,
                            'quantity': leg.quantity,
                            'expiry': position.proposal.expiry.isoformat() if hasattr(position.proposal.expiry, 'isoformat') else str(position.proposal.expiry),
                            'entry_price': leg.entry_price,
                            'exit_price': 0.0,  # Unknown
                            'pnl': 0.0,
                            'note': 'Pricing calculation failed'
                        })
            except Exception as e:
                logger.warning(f"Failed to import or use option pricing: {str(e)}")
                # Fallback to simple leg recording
                for leg in position.proposal.legs:
                    trade_legs.append({
                        'type': leg.leg_type.value,
                        'strike': leg.strike,
                        'side': 'long' if leg.is_long else 'short',
                        'option_type': leg.option_type,
                        'quantity': leg.quantity,
                        'expiry': position.proposal.expiry.isoformat() if hasattr(position.proposal.expiry, 'isoformat') else str(position.proposal.expiry),
                        'entry_price': leg.entry_price,
                        'exit_price': 0.0,
                        'pnl': 0.0
                    })
        
        # Store capital before this trade for tracking
        capital_before = self._capital - pnl  # Reverse the P&L to get capital before
        capital_after = self._capital
        free_capital_before = capital_before - (self._margin_blocked + position.margin_blocked)  # Before margin release
        free_capital_after = capital_after - self._margin_blocked  # After margin release
        
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
            legs=trade_legs,
            costs=costs + slippage,
            capital_before=capital_before,
            capital_after=capital_after,
            margin_blocked=position.margin_blocked,
            free_capital_before=free_capital_before,
            free_capital_after=free_capital_after
        )
        
        self._trades.append(trade)
        
        # Phase 2: Record trade with circuit breaker (track losses, check halt conditions)
        is_win = pnl > 0
        ml_loss_prob = 0.1 if pnl < 0 else 0.05  # Simple mock: 10% if losing, 5% if winning
        self.circuit_breaker.record_trade(pnl, is_win, ml_loss_prob)
        
        # Update equity for circuit breaker
        self.circuit_breaker.update_equity(self._capital)
        
        cb_status = self.circuit_breaker.get_status()
        logger.debug(f"Closed {pos_id}: P&L={pnl:.2f} ({reason}) | CB: {cb_status['state']}")
    
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
        
        # CRITICAL FIX: Use actual equity change instead of trade-based calculation
        # The equity change accounts for all costs, slippage, and compound effects
        actual_total_return = self._capital - self.config.initial_capital
        actual_total_return_pct = (actual_total_return / self.config.initial_capital) * 100
        
        # Populate result
        result.total_return = actual_total_return  # Use actual equity change
        result.total_return_pct = actual_total_return_pct  # Use actual return %
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

        # Export trades to CSV for external evaluation
        try:
            out_dir = os.path.join(os.getcwd(), 'backend', 'data', 'cache')
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = os.path.join(out_dir, f"backtest_trades_{ts}.csv")
            df_trades = pd.DataFrame([
                {
                    'id': t.id,
                    'strategy_type': t.strategy_type,
                    'entry_date': t.entry_date,
                    'exit_date': t.exit_date,
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'pnl': t.pnl,
                    'pnl_pct': t.pnl_pct,
                    'holding_days': t.holding_days,
                    'exit_reason': t.exit_reason,
                    'regime_at_entry': t.regime_at_entry,
                    'regime_at_exit': t.regime_at_exit,
                    'costs': t.costs,
                    'capital_before': t.capital_before,
                    'capital_after': t.capital_after,
                    'capital_consumed': t.capital_before - t.capital_after,
                    'margin_blocked': t.margin_blocked,
                    'free_capital_before': t.free_capital_before,
                    'free_capital_after': t.free_capital_after
                }
                for t in self._trades
            ])
            df_trades.to_csv(csv_path, index=False)
            logger.info(f"Wrote backtest trades CSV: {csv_path}")
        except Exception:
            logger.exception("Failed to write trades CSV")
        
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
