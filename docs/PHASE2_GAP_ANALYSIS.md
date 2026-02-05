# Phase 2 Gap Analysis: Theory vs Implementation

**Status: IMPLEMENTED** ✅ (Feb 5, 2026)

## Executive Summary

The platform has a solid foundation with all 5 agents implemented (Sentinel, Strategist, Treasury, Executor, Monk). The false positive CHAOS classification (Feb 5, 2026) has been addressed with comprehensive improvements to regime detection, including confluence scoring, new metrics (BBW, RV/IV), and expanded strategy support.

---

## Current Implementation Status

### ✅ Implemented (Working)

| Component | Theory Section | Status | Notes |
|-----------|---------------|--------|-------|
| **Sentinel Agent** | Section 3, 10 | ✅ Complete | Regime detection with ADX, RSI, IV, correlations |
| **Strategist Agent** | Section 2, 4, 10 | ✅ Partial | Iron Condor generation working |
| **Treasury Agent** | Section 5, 6, 10 | ✅ Complete | Risk limits, circuit breakers, drawdown multipliers |
| **Executor Agent** | Section 4, 10 | ✅ Partial | Order placement framework exists |
| **Monk Agent** | Section 9, 10 | ✅ Partial | Backtesting and ML training framework |
| **Dashboard UI** | - | ✅ Complete | Positions, Strategies, Portfolios, Regime display |
| **WebSocket Updates** | - | ✅ Complete | Real-time P&L, positions |
| **Margin Tracking** | - | ✅ Complete | Per-position margin with percentages |

### ✅ Critical Gaps (RESOLVED)

| Gap | Resolution | Files Modified |
|-----|------------|----------------|
| **Regime False Positives** | Confluence scoring requires 3+ triggers for CHAOS | `sentinel.py`, `thresholds.py` |
| **No Confluence Requirement** | Added `ConfluenceScore` model with trigger tracking | `regime.py`, `sentinel.py` |
| **Correlation Threshold Too Low** | Raised to 0.5 for intra-equity, dynamic detection | `thresholds.py` |
| **Missing BBW/RV Metrics** | Added BBW, BBW ratio, RV/IV ratio calculations | `technical.py`, `volatility.py` |
| **No ML Model Trained** | Created training scripts with RandomForest/GB | `scripts/train_regime_classifier.py` |

### ✅ Partial Implementations (RESOLVED)

| Component | Resolution | Files Modified |
|-----------|------------|----------------|
| **Strategist** | Integrated Jade Lizard, Butterfly, BWB strategies | `strategist.py`, `butterfly.py` |
| **CAUTION Regime** | Added intermediate regime for hedged trades only | `regime.py`, `strategist.py` |
| **Entry Signals** | Added BBW ratio, volume ratio, RV/IV checks | `sentinel.py` |
| **Monk Training** | Created ML training pipeline with cross-validation | `scripts/train_regime_classifier.py` |

### ⚠️ Remaining Enhancements (Future)

| Component | Gap | Theory Reference |
|-----------|-----|-----------------|
| **Event Calendar** | Empty list, needs real event data | Section 3 |
| **Multi-Asset** | Commodities disabled, no Gold/Silver integration | Section 1 |
| **Risk-Reversals** | Not yet implemented | Section 2 |

---

## Detailed Gap Analysis

### 1. Regime Detection (Critical - Today's Issue)

**Current Implementation** (`thresholds.py`):
```python
ADX_RANGE_BOUND = 12       # ADX < 12 = Range-bound
ADX_TREND = 22             # ADX > 22 = Trend
CORRELATION_CHAOS = 0.5    # |corr| > 0.5 = Chaos
IV_HIGH = 75               # IV > 75% = Chaos
```

**Today's Metrics** (Feb 5, 2026):
- ADX: 24.5 (> 22 → triggered TREND/CHAOS)
- Correlation: 0.91 (> 0.5 → triggered CHAOS)
- IV %ile: 26% (< 75% → PASSED)
- RSI: 38.3 (neutral → PASSED)
- VIX: 12.17 (low → should favor short-vol)

**Problem**: Single triggers (ADX or correlation) force CHAOS without confluence.

**Proposed Fix** (from Nifty_Feb5_2026.md):
```python
# Revised thresholds
ADX_RANGE_BOUND = 12
ADX_MEAN_REVERSION = 25    # NEW: 12-25 = mean-reversion
ADX_TREND = 25             # Raised from 22
ADX_CHAOS = 35             # NEW: ADX > 35 + vol spike = chaos

# Correlation - differentiate intra-equity vs multi-asset
CORRELATION_INTRA_EQUITY = 0.5   # NIFTY-BANKNIFTY (was 0.3)
CORRELATION_MULTI_ASSET = 0.4   # NIFTY-Gold

# Confluence requirement
MIN_CHAOS_TRIGGERS = 3     # NEW: Require 3+ triggers for CHAOS
```

### 2. Missing Metrics for Range Confirmation

**Not Implemented**:
- **Bollinger Band Width (BBW)**: Low BBW confirms range contraction
- **RV/IV Ratio**: If RV < 0.8×IV, vol is overpriced → theta-friendly
- **Volume Profile**: Low volume confirms no trend fuel

**Implementation Location**: `backend/app/services/sentinel.py`

### 3. ML Classifier Not Active

**Current State**:
```python
# In Sentinel.__init__
self.ml_classifier = ml_classifier  # Passed as None

# In Sentinel.process
ml_regime, ml_probability = self._ml_classify(metrics) if self.ml_classifier else (None, 0.0)
```

**Gap**: No trained model, no feature engineering for regime classification.

**Required**:
1. Collect labeled regime data (historical)
2. Train classifier with features: [IV_rank, ADX, RSI, skew, RV/ATR, BBW, volume_ratio]
3. Deploy model to Sentinel

### 4. Strategy Structures Missing

**Implemented**:
- ✅ Iron Condor (`strategist.py`, `iron_condor.py`)

**Not Implemented** (per Section 2):
- ❌ Jade Lizard (file exists but not integrated)
- ❌ Butterflies (balanced, broken-wing)
- ❌ Risk-Reversals (for directional mean-reversion)
- ❌ Diagonals (vol skew exploitation)
- ❌ Conditional Naked Strangles (low-VIX only)

### 5. Entry/Exit Rules Incomplete

**Current** (`strategist.py`):
- Entry: Regime check + IV check + event check + gap check
- Exit: Profit target (60% max profit) or stop loss

**Missing** (per Section 4):
- Skew divergence signals (>20% for fade entries)
- RSI extreme confirmation (< 30 or > 70 for mean-reversion)
- Volume surge detection
- Time-based exit (mandatory at T-5 DTE)
- Regime change exit

---

## Phase 2 Roadmap

### Phase 2A: Fix Regime Detection (1-2 days)

1. **Update Thresholds**
   - Raise ADX trend threshold to 25
   - Implement confluence scoring (3+ triggers for CHAOS)
   - Differentiate correlation thresholds by asset type

2. **Add New Metrics**
   - Bollinger Band Width calculation
   - RV/IV ratio
   - Volume change detection

3. **Regime Persistence**
   - Require 15-30 min confirmation before regime change
   - Add "CAUTION" intermediate state

### Phase 2B: Train ML Classifier (2-3 days)

1. **Data Collection**
   - Export historical regime classifications
   - Label correct regimes manually for training set

2. **Feature Engineering**
   - Add BBW, RV/IV, volume to feature vector
   - Normalize features

3. **Model Training**
   - Use Monk agent to train RandomForest/LogisticRegression
   - Validate on out-of-sample data
   - Deploy to Sentinel

### Phase 2C: Expand Strategies (1 week)

1. **Integrate Jade Lizard** for CAUTION regime
2. **Add Butterflies** for low-vol pinning
3. **Implement Risk-Reversals** for directional mean-reversion
4. **Add Conditional Strangles** for VIX < 12

### Phase 2D: Live Paper Trading (2 weeks)

1. **Enable Signal Generation** (no execution)
2. **Track Hypothetical P&L**
3. **Validate Regime Accuracy** (target > 85%)
4. **Tune Thresholds** based on results

---

## Immediate Action Items

### Today (P0 - Critical)

1. [ ] Update `thresholds.py` with revised ADX/correlation values
2. [ ] Add confluence scoring to `sentinel.py`
3. [ ] Add BBW calculation to `technical.py`
4. [ ] Add RV/IV ratio to `volatility.py`
5. [ ] Update regime explanation to show confluence score

### This Week (P1 - Important)

1. [ ] Create regime labeling tool for historical data
2. [ ] Train initial ML classifier
3. [ ] Add "CAUTION" regime state
4. [ ] Integrate Jade Lizard for CAUTION regime

### Next Week (P2 - Enhancement)

1. [ ] Add event calendar data source
2. [ ] Implement butterflies and risk-reversals
3. [ ] Start paper trading validation

---

## Success Metrics for Phase 2

| Metric | Current | Target |
|--------|---------|--------|
| Regime Accuracy | ~70% (estimated) | > 85% |
| False CHAOS Rate | ~20% | < 10% |
| Missed Range Days | High | < 5% |
| ML Classifier Accuracy | N/A | > 75% |
| Paper Trade Win Rate | N/A | > 60% |

---

## Files to Modify

| File | Changes |
|------|---------|
| `backend/app/config/thresholds.py` | Add new thresholds, confluence requirements |
| `backend/app/services/sentinel.py` | Add BBW, RV/IV, confluence scoring |
| `backend/app/services/technical.py` | Add BBW calculation |
| `backend/app/services/volatility.py` | Add RV/IV ratio |
| `backend/app/models/regime.py` | Add CAUTION regime, confluence_score |
| `frontend/src/types/index.ts` | Add confluence_score to Regime type |
| `frontend/src/components/dashboard/RegimeCard.tsx` | Display confluence score |

---

*Document created: Feb 5, 2026*
*Based on: theory/Grok/tradingv2.md, theory/Grok/Nifty_Feb5_2026.md*
