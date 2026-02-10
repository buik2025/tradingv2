# Sentinel v2.3 Design Document

**Purpose**: Define function signatures, config, interfaces, and test cases for v2.3 Sentinel (DC+HMM+SMEI).  
**Status**: Ready for review and implementation.

---

## 1. Architecture Overview

```
Sentinel
├── dc.py          (Directional Change event detector)
├── hmm_helper.py  (2-state HMM trainer/evaluator)
├── smei.py        (SMEI sentiment scorer)
└── sentinel.py    (Main orchestrator: classify(df) → dict)

Integration Points
├── strategy_selector.py  (consumes sentinel output, applies weighted voting)
├── treasury.py           (consumes p_abnormal for regime-adjusted Kelly)
├── monk.py               (backtester: simulates DC events, collects sentinel logs)
└── settings.py           (new config keys)
```

---

## 2. Module: `dc.py` — Directional Change Event Detector

### Class: `DirectionalChange`

```python
class DirectionalChange:
    def __init__(self, theta: float = 0.003):
        """
        Args:
            theta (float): DC threshold (default 0.3% = 0.003).
        """
        self.theta = theta
        self.extrema = []  # [(timestamp, price, is_high)]
        self.dc_events = []  # [(start_ts, end_ts, T, TMV, TAR)]
    
    def compute_dc_events(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect DC events in OHLCV data.
        
        Args:
            df (pd.DataFrame): OHLCV with columns [timestamp, open, high, low, close, volume].
                               Must be sorted by timestamp, 5-min or 1-min bars.
        
        Returns:
            pd.DataFrame: Columns [start_ts, end_ts, T, TMV, TAR, direction].
                          - T: trend_time (seconds or bars between extrema).
                          - TMV: time_to_max_vol (seconds/bars to max volume in trend).
                          - TAR: time_adjusted_return = (P_end - P_start) / P_start / T.
                          - direction: 'up' or 'down'.
        """
        # Algo:
        # 1. Find extrema (local highs/lows) using price reversals > theta.
        # 2. Between extrema, compute T (time span), TMV (max vol timing), TAR (adjusted return).
        # 3. Return events as DataFrame.
        pass
    
    def current_event(self) -> dict | None:
        """
        Return unfinished DC event (if any) or None.
        
        Returns:
            dict: {'start_ts', 'direction', 'T', 'TMV', 'TAR'} or None.
        """
        pass
```

### Config Keys
- `DC_THETA`: 0.003 (0.3% threshold; tunable).
- `DC_MIN_BAR_WINDOW`: 5 (min bars to qualify as DC event; prevents noise).

### Test Cases
- `test_dc_simple_reversal`: Single up/down/up reversal; verify events detected.
- `test_dc_no_event_below_theta`: Noise <theta; no events.
- `test_dc_multiple_events`: Multi-extrema sequence; all events captured.
- Fixture: `backend/tests/fixtures/dc_sample.csv` (5-min NIFTY, 50 rows, includes clear DC event).

---

## 3. Module: `hmm_helper.py` — 2-State HMM Evaluator

### Class: `HMMRegimeClassifier`

```python
class HMMRegimeClassifier:
    def __init__(self, window: int = 20, n_states: int = 2, random_state: int = 42):
        """
        Args:
            window (int): Rolling window for HMM fit (default 20 DC events).
            n_states (int): Always 2 (normal, abnormal).
            random_state (int): For reproducibility.
        """
        self.window = window
        self.n_states = n_states
        self.hmm = None  # Trained GaussianHMM or custom 2-state model.
    
    def fit(self, dc_events_df: pd.DataFrame) -> None:
        """
        Fit HMM on DC events (columns: T, TMV, TAR).
        
        Args:
            dc_events_df (pd.DataFrame): DC events with normalized [T, TMV, TAR] ∈ [0,1].
        
        Side Effect: Updates self.hmm.
        """
        # Use hmmlearn.GaussianHMM or lightweight custom Bayesian model.
        pass
    
    def predict_proba(self, dc_events_df: pd.DataFrame) -> tuple[float, float]:
        """
        Predict P(normal), P(abnormal) for last DC event(s).
        
        Args:
            dc_events_df (pd.DataFrame): Recent DC events (last 3–5 for online tracking).
        
        Returns:
            (p_normal, p_abnormal): Normalized probabilities.
        """
        # Use HMM to score last event; return posteriors.
        pass
    
    def online_update(self, new_event: dict) -> tuple[float, float]:
        """
        Update HMM with single new DC event (online/streaming mode).
        
        Args:
            new_event (dict): {'T', 'TMV', 'TAR'} (normalized).
        
        Returns:
            (p_normal, p_abnormal) after update.
        """
        # Lightweight update for 15-min trading loop (may or may not retrain fully).
        pass
```

### Config Keys
- `HMM_WINDOW`: 20 (rolling window size for fit).
- `HMM_MIN_SAMPLES`: 5 (min DC events before predicting).

### Test Cases
- `test_hmm_fit_normal`: Fit on synthetic normal events; expect p_normal ~0.8+.
- `test_hmm_fit_abnormal`: Fit on synthetic abnormal events; expect p_abnormal ~0.7+.
- `test_hmm_online_update`: Add events one by one; verify probs tracked.

---

## 4. Module: `smei.py` — SMEI Sentiment Scorer

### Class: `SMEICalculator`

```python
class SMEICalculator:
    def __init__(self, window: int = 20):
        """
        Args:
            window (int): Lookback window for SMEI (default 20 days).
        """
        self.window = window
    
    def compute_smei(self, df: pd.DataFrame) -> float:
        """
        Compute SMEI sentiment score.
        
        Args:
            df (pd.DataFrame): OHLCV with columns [open, high, low, close, volume].
                               At least `window` rows.
        
        Returns:
            float: SMEI ∈ [-1, 1].
                   >0.5: bullish (short-vol ok).
                   <-0.5: bearish (directional only).
                   [-0.5, 0.5]: neutral.
        
        Calculation:
            1. Enhanced OBV = sum over window of [sign(close - open) * volume * (close-open)/(high-low)].
            2. CMF = sum over window of [volume * ((close-low)-(high-close))/(high-low)] / sum(volume).
            3. SMEI = (OBV_norm + CMF) / 2, normalized to [-1,1].
        """
        pass
    
    def obv(self, df: pd.DataFrame) -> float:
        """Enhanced OBV (for unit tests)."""
        pass
    
    def cmf(self, df: pd.DataFrame) -> float:
        """CMF variant (for unit tests)."""
        pass
```

### Config Keys
- `SMEI_WINDOW`: 20 (days).
- `SMEI_BULLISH_THRESHOLD`: 0.5.
- `SMEI_BEARISH_THRESHOLD`: -0.5.

### Test Cases
- `test_smei_bullish_trend`: Synthetic data with closes >opens; expect SMEI >0.5.
- `test_smei_bearish_trend`: Synthetic data with closes <opens; expect SMEI <-0.5.
- `test_smei_normalization`: Output always in [-1, 1].

---

## 5. Module: `sentinel.py` — Main Orchestrator

### Class: `Sentinel`

```python
class Sentinel:
    def __init__(self, dc_theta: float = 0.003, hmm_window: int = 20):
        """
        Args:
            dc_theta: DC threshold.
            hmm_window: HMM rolling window.
        """
        self.dc = DirectionalChange(theta=dc_theta)
        self.hmm = HMMRegimeClassifier(window=hmm_window)
        self.smei = SMEICalculator(window=20)
        self.simple_classifier = SimpleRegimeClassifier()  # ADX, IV, RSI, etc.
        self.ml_classifier = MLRegimeClassifier()  # Trained model.
        self.dc_event_buffer = deque(maxlen=5)  # Last 5 DC events.
        self.last_output = {}  # Cache last classification.
    
    def classify(self, df: pd.DataFrame, option_chain: dict | None = None) -> dict:
        """
        Classify regime and compute probabilities.
        
        Args:
            df (pd.DataFrame): OHLCV data (at least 50 rows, 5-min bars ideally).
            option_chain (dict): Optional; used by simple_classifier for IV, Greeks.
        
        Returns:
            dict:
            {
                'regime': 'range_bound' | 'mean_reversion' | 'trend' | 'chaos' | 'abnormal',
                'p_abnormal': float ∈ [0, 1],  # HMM posterior for abnormal state.
                'dc_indicators': {
                    'T': float,
                    'TMV': float,
                    'TAR': float,
                    'direction': 'up' | 'down'
                },
                'smei': float,  # SMEI score.
                'simple_regime': str,  # ADX-based regime.
                'ml_chaos_prob': float,  # P(chaos) from ML.
                'hybrid_vote': {
                    'dc_score': 0.5,      # 50% weight.
                    'simple_score': 0.2,  # 20% weight.
                    'ml_score': 0.2,      # 20% weight.
                    'sentiment_score': 0.1  # 10% weight.
                },
                'confidence': float,  # Min vote agreement score.
                'timestamp': str,
            }
        
        Hybrid Logic:
            - If p_abnormal >0.7 and ≥3 recent DC events confirm: regime='abnormal' → veto short-vol.
            - Else: simple_regime (ADX-based) + ml_chaos_prob + sentiment.
            - regime = 'normal' if hybrid_vote agreement >0.6; else 'abnormal'.
        """
        pass
    
    def alarm_abnormal(self) -> bool:
        """
        Check if recent events trigger abnormal alarm (p_abnormal >0.7 for ≥3 consecutive DC events).
        
        Returns:
            bool: True if alarm triggered.
        """
        pass
    
    def log_event(self) -> dict:
        """
        Return structured log entry for Monk (backtester analysis).
        
        Returns:
            dict: {'timestamp', 'regime', 'p_abnormal', 'dc_indicators', 'smei', 'votes'}.
        """
        pass
```

### Config Keys (in `settings.py`)
```python
# Sentinel
SENTINEL_ENABLED = True
DC_THETA = 0.003  # 0.3%
DC_MIN_BAR_WINDOW = 5
HMM_WINDOW = 20
SMEI_WINDOW = 20
SMEI_BULLISH_THRESHOLD = 0.5
SMEI_BEARISH_THRESHOLD = -0.5
DC_ALARM_P = 0.7  # Threshold for p_abnormal.
DC_ALARM_N = 3  # Num consecutive events for alarm.
SENTIMENT_WEIGHT = 0.1
DC_WEIGHT = 0.5
SIMPLE_WEIGHT = 0.2
ML_WEIGHT = 0.2
```

### Test Cases
- `test_classify_range_bound`: Quiet data, low vol; expect regime='range_bound', p_abnormal <0.3.
- `test_classify_abnormal`: Volatile data with clear DC reversals; expect p_abnormal >0.7.
- `test_alarm_threshold`: ≥3 DC events with p_abnormal >0.7; alarm_abnormal() returns True.
- `test_cache_management`: Multiple calls update dc_event_buffer correctly.

---

## 6. Integration: Changes to Existing Modules

### `strategy_selector.py`

```python
class StrategySelector:
    def __init__(self, sentinel: Sentinel | None = None):
        self.sentinel = sentinel
    
    def should_enter_structure(
        self, 
        option_chain: dict, 
        regime: dict,  # From sentinel.classify()
        position_count: int,
        current_pnl: float | None = None
    ) -> dict:
        """
        Confluence voting with sentinel weighting.
        
        Returns:
            {
                'should_enter': bool,
                'structure': 'strangle' | 'condor' | 'risk_reversal' | 'hedge',
                'reason': str,
                'confluence_score': float,
                'rejections': [str],  # Why rejected (e.g., 'p_abnormal >0.7', 'insufficient_liquidity').
            }
        """
        # NEW: Check p_abnormal from sentinel.
        if regime.get('p_abnormal', 0) > 0.7:
            return {'should_enter': False, 'rejections': ['abnormal_regime_alarm']}
        
        # NEW: Apply weighted voting.
        confluence_score = self._weighted_confluence(regime)
        if confluence_score < 0.5:
            return {'should_enter': False, 'rejections': ['low_confluence']}
        
        # Existing logic: structure selection, liquidity filter, etc.
        pass
    
    def _weighted_confluence(self, regime: dict) -> float:
        """
        Compute weighted confluence from hybrid_vote.
        
        Returns:
            float ∈ [0, 1] (min score for entry ≥0.5).
        """
        # Use regime['hybrid_vote'] and weights from settings.
        pass
```

### `treasury.py` (or new `treasury_service.py`)

```python
class Treasury:
    def allocate(
        self, 
        signals: dict,  # From strategist/strategy_selector.
        sentinel_output: dict,  # From sentinel.classify().
        capital: float,
        rolling_stats: dict,  # {'win_p': 0.65, 'avg_win': 2000, 'avg_loss': 1500}
    ) -> dict:
        """
        Compute Kelly-adjusted position size with regime multiplier.
        
        Returns:
            {
                'size': int,  # Num lots.
                'kelly_f': float,  # Kelly fraction (e.g., 0.012).
                'regime_mult': float,  # 1.0 (normal) or 0.3 (abnormal).
                'effective_f': float,  # kelly_f * regime_mult.
                'margin_pct': float,  # Est margin % of capital.
            }
        """
        # NEW: Regime multiplier.
        regime_mult = 1.0 if sentinel_output.get('regime') != 'abnormal' else 0.3
        
        # Existing: Compute kelly_f from rolling stats.
        kelly_f = self._kelly_fraction(rolling_stats)
        
        # NEW: Apply regime multiplier and contango complement (commodities).
        effective_f = kelly_f * regime_mult
        if signals.get('instrument_type') == 'commodity':
            complement_mult = self._contango_complement()
            effective_f *= complement_mult  # e.g., 1.1x if positive contango.
        
        # Size calculation.
        size = min(int(0.015 * capital * effective_f / signals['target']), 3)
        
        return {
            'size': size,
            'kelly_f': kelly_f,
            'regime_mult': regime_mult,
            'effective_f': effective_f,
        }
    
    def _kelly_fraction(self, rolling_stats: dict) -> float:
        """
        f = (win_p * avg_win - loss_p * avg_loss) / (avg_win * loss_p).
        Capped at 0.5–0.7x to avoid ruin.
        """
        pass
```

### `settings.py` — Add New Keys

```python
# Sentinel Feature Flags & Params
SENTINEL_ENABLED = True
DC_THETA = 0.003
DC_MIN_BAR_WINDOW = 5
HMM_WINDOW = 20
SMEI_WINDOW = 20
DC_ALARM_P = 0.7
DC_ALARM_N = 3
SENTIMENT_WEIGHT = 0.1
DC_WEIGHT = 0.5
SIMPLE_WEIGHT = 0.2
ML_WEIGHT = 0.2

# Sentiment Thresholds
SMEI_BULLISH_THRESHOLD = 0.5
SMEI_BEARISH_THRESHOLD = -0.5
```

### `requirements.txt` — Add Dependencies

```
hmmlearn==0.3.0
scikit-learn>=1.3.0
scipy>=1.10.0
pandas>=1.5.0
numpy>=1.24.0
```

---

## 7. Backtester / Monk Integration

### `monk.py` (or backtester engine)

```python
class Monk:
    def __init__(self, enable_sentinel: bool = False):
        self.enable_sentinel = enable_sentinel
        self.sentinel = Sentinel() if enable_sentinel else None
        self.sentinel_logs = []  # Collect all sentinel outputs for post-analysis.
    
    def backtest(
        self, 
        df: pd.DataFrame,  # OHLCV data.
        rules: dict,  # Trading rules.
        events: list[dict] | None = None,  # DC-injection events (for stress tests).
    ) -> dict:
        """
        Run backtest with optional sentinel regime filtering.
        
        Args:
            events (list[dict]): Inject synthetic DC events for stress testing.
                                 E.g., [{'timestamp': '2026-01-15', 'direction': 'down', 'magnitude': 0.05}].
        
        Returns:
            {
                'sharpe': float,
                'dd': float,
                'win_rate': float,
                'net_return': float,
                'trades': int,
                'sentinel_impact': {
                    'entries_rejected': int,  # How many entries rejected by p_abnormal >0.7.
                    'regimes': {'range_bound': int, 'abnormal': int, ...},
                },
                'sentinel_logs': [...]  # For model evaluation.
            }
        """
        pass
```

---

## 8. CLI Integration

### `run_backtest.py`

```python
parser.add_argument(
    '--enable-sentinel',
    action='store_true',
    help='Enable Sentinel DC/HMM/SMEI in backtest (default disabled for baseline).',
)
parser.add_argument(
    '--dc-theta',
    type=float,
    default=0.003,
    help='DC threshold (default 0.3%).',
)
parser.add_argument(
    '--stress-dc-events',
    action='store_true',
    help='Inject synthetic DC events for stress testing.',
)
```

---

## 9. Test Fixtures

### `backend/tests/fixtures/dc_sample.csv`
5-min NIFTY data (50 rows) with clear DC event (up-down-up reversal >0.3%).

### `backend/tests/fixtures/smei_bullish.csv`
Synthetic OHLCV (50 rows) with closes >opens; expect SMEI >0.5.

### `backend/tests/fixtures/dc_events.json`
Pre-computed DC events for HMM fitting tests.

---

## 10. Acceptance Criteria

- [ ] Sentinel can classify regimes on real NIFTY 5-min data without crashing.
- [ ] p_abnormal correctly identifies volatile regimes (test on 2020 crash / 2022 vol period).
- [ ] StrategySelector rejects entries when p_abnormal >0.7.
- [ ] Treasury scales down sizing (mult 0.3x) in abnormal regimes.
- [ ] Backtest metrics (Sharpe, DD, win rate) match v2.3 expectations (+1.7 Sharpe, <2% DD, 66% wins).
- [ ] No syntax errors; all unit tests pass.
- [ ] CLI accepts `--enable-sentinel` and produces logs.

---

## 11. Implementation Sequence (Recommended)

1. **Week 1**:
   - Implement `dc.py` + `test_dc.py` (DC event detection).
   - Implement `smei.py` + `test_smei.py` (SMEI scoring).
   - Create test fixtures.

2. **Week 2**:
   - Implement `hmm_helper.py` + `test_hmm.py` (HMM 2-state).
   - Implement `sentinel.py` + `test_sentinel.py` (orchestrator).
   - Update `settings.py` with new config keys.

3. **Week 3**:
   - Integrate into `strategy_selector.py` (weighted voting).
   - Integrate into `treasury.py` (regime-adjusted Kelly).
   - Update `requirements.txt`.

4. **Week 4**:
   - Extend `monk.py` for event injection and sentinel logs.
   - Add `--enable-sentinel` CLI flag.
   - Run backtests; validate metrics vs. v2.3 expectations.
   - Docs + changelog.

---

## Next Steps

1. Review this design doc.
2. Approve or request changes (e.g., alternate HMM impl, threshold tweaks).
3. I'll start coding Week 1 tasks.

