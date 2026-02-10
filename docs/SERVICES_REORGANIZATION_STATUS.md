# Services Directory Reorganization Status & Issues

**Date**: February 8, 2026  
**Current State**: PARTIALLY REORGANIZED WITH DUPLICATES

---

## Current Structure

```
backend/app/services/
├── __init__.py (re-exports)
├── ROOT LEVEL (LEGACY - SHOULD BE REMOVED):
│   ├── butterfly.py              ← DUPLICATE in strategies/
│   ├── iron_condor.py            ← DUPLICATE in strategies/
│   ├── jade_lizard.py            ← DUPLICATE in strategies/
│   ├── risk_reversal.py          ← DUPLICATE in strategies/
│   ├── strangle.py               ← DUPLICATE in strategies/
│   ├── strategist.py             ← DUPLICATE in strategies/
│   ├── strategy_backtester.py    ← DUPLICATE in backtesting/
│   ├── dc.py                     ← NEW (needs placement)
│   └── smei.py                   ← NEW (needs placement)
│
├── strategies/                   ✅ (Core structures)
│   ├── __init__.py
│   ├── strategist.py
│   ├── strategy_selector.py
│   ├── butterfly.py
│   ├── iron_condor.py
│   ├── jade_lizard.py
│   ├── risk_reversal.py
│   └── strangle.py
│
├── indicators/                   ✅ (Analysis & regime detection)
│   ├── __init__.py
│   ├── technical.py              (ADX, RSI, ATR, BBW, etc.)
│   ├── greeks.py
│   ├── regime_classifier.py      (SimpleRegimeClassifier)
│   ├── volatility.py
│   └── metrics.py
│
├── agents/                       ✅ (v2 Agent framework)
│   ├── __init__.py
│   ├── base_agent.py
│   ├── sentinel.py               (OLD - will be replaced/refactored)
│   ├── engine.py
│   ├── monk.py
│   └── trainer.py
│
├── execution/                    ✅ (Risk & order management)
│   ├── __init__.py
│   ├── executor.py
│   ├── treasury.py
│   ├── portfolio_service.py
│   ├── circuit_breaker.py
│   └── greek_hedger.py
│
├── backtesting/                  ✅ (Backtester engine)
│   ├── __init__.py
│   ├── strategy_backtester.py
│   ├── data_loader.py
│   ├── options_simulator.py
│   └── pnl_calculator.py
│
└── utilities/                    ✅ (Support utilities)
    ├── __init__.py
    ├── instrument_cache.py
    └── option_pricing.py
```

---

## Issues Identified

### 1. **CRITICAL: Duplicate Files in Root**
Files exist in BOTH root and subfolders:
- `butterfly.py` — exists at root AND in `strategies/`
- `iron_condor.py` — exists at root AND in `strategies/`
- `jade_lizard.py` — exists at root AND in `strategies/`
- `risk_reversal.py` — exists at root AND in `strategies/`
- `strangle.py` — exists at root AND in `strategies/`
- `strategist.py` — exists at root AND in `strategies/`
- `strategy_backtester.py` — exists at root AND in `backtesting/`

**Cause**: Earlier reorganization moved files to subfolders but left originals at root.  
**Impact**: Import paths are broken; code uses mix of root and subfolder imports.  
**Risk**: Silent failures, hard-to-trace bugs, confusion.

### 2. **NEW FILES IN ROOT (Not Yet Organized)**
- `dc.py` (DirectionalChange detector) — just created
- `smei.py` (SMEI sentiment scorer) — just created

**Where should they go?**
- **Option A**: `indicators/` — They are analysis indicators
- **Option B**: New `sentinel/` subfolder — They are part of Sentinel system
- **Recommended**: `indicators/` initially; can be refactored if needed later

### 3. **Existing `agents/sentinel.py` vs. v2.3 Sentinel**
- Current `agents/sentinel.py` — exists but is likely old v2.0 code
- v2.3 Sentinel — new orchestrator using DC+HMM+SMEI (to be created)

**Decision**: 
- Rename existing `agents/sentinel.py` → `agents/sentinel_v2.py` (backup)
- Create new `sentinel.py` (v2.3 orchestrator) in `indicators/` or new `sentinel/` package

---

## Cleanup Plan

### Phase 1: Remove Root Duplicates
1. **Move root strategy files → strategies/**  (if different from subfolder versions)
2. **Delete root copies** of: `butterfly.py`, `iron_condor.py`, `jade_lizard.py`, `risk_reversal.py`, `strangle.py`
3. **Move root `strategist.py` → strategies/** (if different)
4. **Move root `strategy_backtester.py` → backtesting/** (if different)
5. **Verify imports** across codebase point to new locations

### Phase 2: Organize New v2.3 Files
1. **Move `dc.py` → indicators/**
2. **Move `smei.py` → indicators/**
3. **Create `indicators/__init__.py`** to export both

### Phase 3: Implement Sentinel v2.3
1. Create `sentinel.py` (new v2.3 orchestrator) in `indicators/` or create `sentinel/` package
2. Rename old `agents/sentinel.py` → `agents/sentinel_v2.py` (archive)
3. Update `indicators/__init__.py` to export `Sentinel`

### Phase 4: Update All Imports
1. Update all import paths across backend to use subpackage structure
2. Run syntax/import checks
3. Test backtester runs

---

## File Size Comparison (Detect if Truly Duplicated)

| File | Root Size | Subfolder Size | Status |
|---|---|---|---|
| `butterfly.py` | 17K | 17K | Likely identical |
| `iron_condor.py` | 11K | 11K | Likely identical |
| `jade_lizard.py` | 8.3K | 8.3K | Likely identical |
| `risk_reversal.py` | 11K | 11K | Likely identical |
| `strangle.py` | 12K | 12K | Likely identical |
| `strategist.py` | 29K | ? | Need to check |
| `strategy_backtester.py` | 56K | ? | Need to check |

---

## Recommendations

1. **Immediate** (before continuing with v2.3):
   - Verify which version of each file is "canonical" (root or subfolder)
   - Delete root duplicates
   - Update imports across codebase
   - Run full syntax check

2. **This Session**:
   - Clean up root directory completely
   - Move `dc.py` and `smei.py` to `indicators/`
   - Prepare for Sentinel v2.3 creation

3. **Next Session**:
   - Implement Sentinel v2.3 orchestrator
   - Run backtests to validate no import regressions

---

## Expected Outcome (Post-Cleanup)

```
backend/app/services/
├── __init__.py (single source of re-exports)
├── strategies/           (strategy structures + strategist)
├── indicators/           (DC, SMEI, regime, greeks, technical, volatility)
├── agents/              (base agent, engine, monk, trainer)
├── execution/           (executor, treasury, portfolio, brakes, hedging)
├── backtesting/         (strategy_backtester, data_loader, simulator, pnl)
└── utilities/           (cache, pricing)

NO files at root level except __init__.py (re-exports only)
```

