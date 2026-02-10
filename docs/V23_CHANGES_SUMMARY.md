# v2.3 Implementation: What Will Change — At-a-Glance

## File Change Matrix

| File/Module | Change Type | Impact | Status |
|---|---|---|---|
| **New Files** | | | |
| `backend/app/services/sentinel.py` | **Create** | Core Sentinel orchestrator (DC+HMM+SMEI classifier) | Not started |
| `backend/app/services/dc.py` | **Create** | Directional Change event detector | Not started |
| `backend/app/services/hmm_helper.py` | **Create** | 2-state HMM trainer/predictor | Not started |
| `backend/app/services/smei.py` | **Create** | SMEI sentiment scorer | Not started |
| `backend/tests/test_sentinel.py` | **Create** | Unit tests for Sentinel | Not started |
| `backend/tests/test_dc.py` | **Create** | Unit tests for DC | Not started |
| `backend/tests/test_smei.py` | **Create** | Unit tests for SMEI | Not started |
| `backend/tests/test_hmm.py` | **Create** | Unit tests for HMM | Not started |
| `backend/tests/fixtures/dc_sample.csv` | **Create** | Test data: 5-min NIFTY with DC event | Not started |
| `backend/tests/fixtures/smei_bullish.csv` | **Create** | Test data: bullish sentiment | Not started |
| `docs/SENTINEL.md` | **Create** | User guide & interpretation (p_abnormal, hybrid vote) | Not started |
| `docs/SENTINEL_DESIGN.md` | **Created** ✅ | This design doc | ✅ Complete |
| **Modified Files** | | | |
| `backend/app/services/strategy_selector.py` | **Edit** | Add Sentinel acceptance, weighted confluence voting | Not started |
| `backend/app/services/strategist.py` | **Minor** | Pass sentinel output to StrategySelector | Not started |
| `backend/app/services/treasury.py` | **Edit** | Implement regime-adjusted Kelly + contango complement | Not started |
| `backend/app/services/portfolio_service.py` | **Minor** | Log sentinel regime multipliers in position metadata | Not started |
| `backend/app/config/settings.py` | **Edit** | Add 11 new config keys (SENTINEL_*, DC_*, HMM_*, SMEI_*) | Not started |
| `backend/app/config/thresholds.py` | **Minor** | Reference new sentinel thresholds (read-only) | Not started |
| `backend/app/core/kite_client.py` | **Minor** | Ensure OHLCV feed includes 5-min bars for DC | Not started |
| `backend/app/api/backtest_routes.py` | **Minor** | Expose sentinel metrics in backtest response | Not started |
| `backend/scripts/run_backtest.py` | **Edit** | Add `--enable-sentinel` and `--dc-theta` CLI flags | Not started |
| `backend/requirements.txt` | **Edit** | Add hmmlearn, scipy, scikit-learn | Not started |
| `backend/app/services/backtesting/monk.py` | **Edit** | Integrate sentinel, support DC event injection, log sentinel votes | Not started |
| `backend/app/services/__init__.py` | **Minor** | Export Sentinel class for reorg compat | Not started |
| **Reorganization-Related** | | | |
| Import updates across `backend/app/services/*` | **Post-Reorg** | Ensure all imports reflect subpackage structure | Pending |

---

## Key Behavioral Changes

### 1. **Regime Classification**
- **Before**: Simple ADX/IV/RSI metrics → regime string.
- **After**: DC events + HMM + simple + ML + sentiment → weighted hybrid vote + p_abnormal probability.

### 2. **Entry Filtering**
- **Before**: Confluence ≥2 (e.g., ATR + RSI).
- **After**: Confluence ≥2 **+ check p_abnormal**; if >0.7, reject short-vol entries.

### 3. **Position Sizing**
- **Before**: 1.5% risk × Kelly fraction (capped 0.5–0.7x).
- **After**: 1.5% risk × Kelly × **regime multiplier** (normal=1.0, abnormal=0.3) × **contango complement** (commodities, 1.0–1.1x).

### 4. **Backtest Output**
- **Before**: Sharpe, DD, win rate, trade list.
- **After**: **+ sentinel metrics** (p_abnormal by date, regime breakdown, entries rejected by alarm, hybrid vote scores).

---

## Config Changes Summary

### New Settings (in `settings.py`)

```python
# Sentinel Feature Flags
SENTINEL_ENABLED = True  # Toggle Sentinel on/off

# Directional Change
DC_THETA = 0.003  # 0.3% threshold
DC_MIN_BAR_WINDOW = 5  # Min bars to qualify as event

# HMM
HMM_WINDOW = 20  # Rolling window for fit
HMM_MIN_SAMPLES = 5  # Min events before predicting

# SMEI
SMEI_WINDOW = 20  # Days for SMEI calc
SMEI_BULLISH_THRESHOLD = 0.5
SMEI_BEARISH_THRESHOLD = -0.5

# Sentinel Alarms & Voting
DC_ALARM_P = 0.7  # p_abnormal threshold for alarm
DC_ALARM_N = 3  # Consecutive events for alarm
SENTIMENT_WEIGHT = 0.1
DC_WEIGHT = 0.5
SIMPLE_WEIGHT = 0.2
ML_WEIGHT = 0.2
```

---

## Expected Metrics Uplift (from v2.3 rulebook)

| Metric | v2.1 | v2.3 | Improvement |
|---|---|---|---|
| Sharpe Ratio | 1.4–1.5 | 1.7+ | +6–14% |
| Max Drawdown | <2.5% | <2% | Better tail risk |
| Win Rate | 60–62% | 66% | +4–6pp |
| False Alarm Reduction (vs. ADX alone) | — | 60% | Fewer choppy entries |
| DC Shift Preemption | — | 1–4 days earlier | Faster exits |

---

## Effort Estimate

| Task | Effort | Duration |
|---|---|---|
| DC detector + tests | 3 d | 1 week |
| SMEI + tests | 2 d | 3 days |
| HMM helper + tests | 3 d | 1 week |
| Sentinel orchestrator + tests | 3 d | 1 week |
| Integration (StrategySelector, Treasury) | 3 d | 1 week |
| Backtest extension + CLI | 2 d | 3 days |
| Fixtures, docs, cleanup, compile | 2 d | 3 days |
| **Total** | **~18 d** | **~4–5 weeks** |

---

## Dependencies to Install

```bash
pip install hmmlearn==0.3.0 scikit-learn>=1.3.0 scipy>=1.10.0 pandas>=1.5.0 numpy>=1.24.0
```

---

## Risk & Mitigation

| Risk | Mitigation |
|---|---|
| HMM overfitting on small sample | Use rolling window; online updates; test on out-of-sample data |
| DC false positives in low-vol | Tunable theta (0.3% can adjust); min window filter |
| SMEI lagging in extreme regime shifts | Hybrid voting (DC 50%, SMEI 10%) reduces single-indicator risk |
| Performance regression | Baseline backtest v2.1 in parallel; gate rollout to paper trading first |
| Data quality issues (5-min bars unavailable) | Fallback to 1-min aggregation or simple ADX-only mode if SENTINEL_ENABLED=False |

---

## Success Criteria

- ✅ All unit tests pass (DC, SMEI, HMM, Sentinel).
- ✅ Backtest on 5+ years NSE data: Sharpe >1.6, DD <2%, win >65%.
- ✅ No import regressions post-reorganization.
- ✅ CLI accepts `--enable-sentinel` without errors.
- ✅ Sentinel logs structured; Monk analysis produces expected regime breakdowns.
- ✅ Paper trading validation: 2 weeks of live regimes match backtest regime distribution.

