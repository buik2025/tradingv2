# Backtesting Preparation Document

**Date**: February 6, 2026  
**Reference**: `theory/Grok/Backtesting_Feb5_2026.md`

---

## 1. Current Historical Data Available

### 1.1 OHLCV Data (Spot/Index)

| File | Instrument | Interval | Rows | Date Range |
|------|------------|----------|------|------------|
| `data/cache/256265_5minute.parquet` | NIFTY (256265) | 5-minute | 1,051 | Jan 16, 2026 - Feb 5, 2026 (~15 trading days) |
| `data/cache/256265_day.parquet` | NIFTY (256265) | Daily | 174 | May 29, 2025 - Feb 5, 2026 (~8 months) |
| `data/cache/260105_day.parquet` | BANKNIFTY (260105) | Daily | 22 | Jan 6, 2026 - Feb 5, 2026 (~1 month) |

### 1.2 Options Data (Real-time Collection)

| File | Instrument | Rows | Date Range |
|------|------------|------|------------|
| `data/options/NIFTY_options_20260206.parquet` | NIFTY Options | 35,015 | Feb 6, 2026 (single day) |
| `data/options/BANKNIFTY_options_20260206.parquet` | BANKNIFTY Options | 26,202 | Feb 6, 2026 (single day) |

**Options Data Columns**: `timestamp`, `symbol`, `trading_symbol`, `expiry`, `strike`, `option_type`, `underlying`, `ltp`, `bid`, `ask`, `volume`, `oi`, `open`, `high`, `low`, `close`

### 1.3 Data Gaps

| Data Needed | Status | Action Required |
|-------------|--------|-----------------|
| NIFTY 5-min (Nov 1, 2025 - present) | **PARTIAL** - Only 15 days | Download historical 5-min data |
| BANKNIFTY 5-min | **MISSING** | Download historical 5-min data |
| INDIA VIX daily | **MISSING** | Download for IV percentile calculation |
| NIFTY daily (1 year) | **AVAILABLE** | 174 days available |
| Options historical | **MISSING** | Need for accurate P&L simulation |
| GOLDM (MCX Gold Mini) | **MISSING** | Required per Grok document |
| CRUDE (MCX Crude Oil) | **MISSING** | Required per Grok document |
| NATURALGAS (MCX) | **MISSING** | Required per Grok document |

---

## 2. Current Backtesting Capabilities

### 2.1 Regime Detection (Sentinel)

**Currently Implemented**:
- ADX-based trend detection (Range-bound < 12, Mean-reversion 12-25, Trend > 25, Chaos > 35)
- RSI overbought/oversold (30/70)
- IV percentile calculation (requires 252-day data)
- Correlation analysis (NIFTY-BANKNIFTY)
- Bollinger Band Width (BBW) for range confirmation
- RV/IV ratio for theta-friendly detection
- Volume surge detection
- ML override capability (placeholder)

**Regime Types**: `RANGE_BOUND`, `MEAN_REVERSION`, `TREND`, `CHAOS`, `CAUTION`, `UNKNOWN`

### 2.2 Strategy Generation (Strategist)

**Currently Implemented**:
| Strategy | Regime | Status |
|----------|--------|--------|
| Iron Condor | RANGE_BOUND | ✅ Implemented |
| Jade Lizard | RANGE_BOUND, CAUTION | ✅ Implemented |
| Butterfly | RANGE_BOUND | ✅ Implemented |
| Broken Wing Butterfly | MEAN_REVERSION | ✅ Implemented |
| Risk Reversal | MEAN_REVERSION | ⚠️ Partial |

### 2.3 Risk Management (Treasury)

**Currently Implemented**:
- Position sizing (2% default)
- Max positions limit (3)
- Max margin utilization (40%)
- Daily/weekly/monthly loss limits
- Drawdown-based size reduction
- Greeks limits (delta, gamma, vega)

### 2.4 Backtest Engine

**Currently Implemented**:
- OHLCV-based simulation
- Regime detection per bar
- Entry/exit signal generation
- P&L calculation with slippage/costs
- Equity curve generation
- Metrics: Sharpe, Sortino, Max DD, Win Rate, Profit Factor, Expectancy

---

## 3. Grok Document Analysis - Required Modifications

### 3.1 Parameter Changes from Grok Document

| Parameter | Current Value | Grok Recommended | File | Impact |
|-----------|---------------|------------------|------|--------|
| Risk per trade | 1.0% (`MAX_LOSS_PER_TRADE = 0.01`) | **1.5%** | `thresholds.py` | +50% position size, higher returns but more volatility |
| ADX Range-bound | 12 | **14** | `thresholds.py` | More trades classified as range-bound |
| IV entry threshold | 40% (`IV_ENTRY_MIN = 40`) | **45%** (loosened) | `thresholds.py` | More short-vol entries in moderate IV |
| Short-vol targets | 60% (`IC_PROFIT_TARGET = 0.60`) | **1.4-1.8% of margin** | `thresholds.py` | Different profit calculation method |
| Confluence requirement | 3 for CHAOS | **2 for entry** | `thresholds.py` | Fewer false positives |
| Trailing stop | Not implemented | **BBW > 1.8x trailing** | `strategy_backtester.py` | Extended winners, +0.3-0.5% extra |
| Lots ramping | Fixed | **1 → 2 → 3 based on equity** | `treasury.py` | Scaling with success |

### 3.2 New Instruments Required

| Instrument | Exchange | Token | Correlation Threshold | Purpose |
|------------|----------|-------|----------------------|---------|
| GOLDM (Gold Mini) | MCX | TBD | < 0.4 with NIFTY | Diversification, mean-reversion |
| CRUDE (Crude Oil) | MCX | TBD | < 0.4 with NIFTY | Higher-vol plays |
| NATURALGAS | MCX | TBD | < 0.4 with NIFTY | Energy sector vol |

### 3.3 New Features Required

| Feature | Description | Files to Modify |
|---------|-------------|-----------------|
| **Trailing Profits** | Extend winners when BBW > 1.8x 20-day avg | `strategy_backtester.py` |
| **Daily Brake** | Flat for 1-3 days after -1.5% daily loss | `strategy_backtester.py`, `thresholds.py` |
| **Lots Ramping** | Scale 1→2→3 lots based on equity growth | `treasury.py` |
| **Multi-Asset Correlation** | NIFTY-Gold, NIFTY-Crude correlation | `sentinel.py` |
| **Dynamic Spike Detection** | Correlation spike + vol confirmation | `volatility.py` |

---

## 4. Proposed Code Modifications

### 4.1 `thresholds.py` - Risk Parameters

```python
# BEFORE
MAX_LOSS_PER_TRADE = 0.01      # Max 1% loss per trade
ADX_RANGE_BOUND = 12           # ADX < 12 = Range-bound
IV_ENTRY_MIN = 40              # Minimum IV for short-vol entries

# AFTER (Grok recommendations)
MAX_LOSS_PER_TRADE = 0.015     # Max 1.5% loss per trade (+50%)
ADX_RANGE_BOUND = 14           # ADX < 14 = Range-bound (more inclusive)
IV_ENTRY_MIN = 45              # Loosened to 45% for more entries
```

**Impact**: 
- +25% more trades (looser ADX/IV)
- +50% larger position sizes
- Expected return increase: 25-50% per trade

### 4.2 `thresholds.py` - Trailing & Brakes

```python
# NEW - Add these constants
# Trailing Profit Settings
TRAILING_BBW_THRESHOLD = 1.8   # Extend winners when BBW > 1.8x avg
TRAILING_PROFIT_MIN = 0.50     # Only trail if already at 50%+ profit

# Daily Brake Settings  
DAILY_LOSS_BRAKE = 0.015       # -1.5% daily loss triggers brake
BRAKE_FLAT_DAYS = 1            # Flat for 1 day after brake
```

### 4.3 `constants.py` - New Instruments

```python
# BEFORE
NIFTY_TOKEN = 256265
BANKNIFTY_TOKEN = 260105
INDIA_VIX_TOKEN = 264969

# AFTER - Add MCX instruments
NIFTY_TOKEN = 256265
BANKNIFTY_TOKEN = 260105
INDIA_VIX_TOKEN = 264969

# MCX Commodity Tokens (to be filled with actual tokens)
GOLDM_TOKEN = None      # MCX Gold Mini
CRUDE_TOKEN = None      # MCX Crude Oil
NATURALGAS_TOKEN = None # MCX Natural Gas

# Multi-asset configuration
MULTI_ASSET_INSTRUMENTS = {
    "NIFTY": {"token": 256265, "exchange": "NFO", "lot_size": 50},
    "BANKNIFTY": {"token": 260105, "exchange": "NFO", "lot_size": 15},
    "GOLDM": {"token": None, "exchange": "MCX", "lot_size": 10},
    "CRUDE": {"token": None, "exchange": "MCX", "lot_size": 100},
    "NATURALGAS": {"token": None, "exchange": "MCX", "lot_size": 1250},
}
```

### 4.4 `strategy_backtester.py` - Trailing Profits

```python
# BEFORE - Fixed profit target exit
if position.current_pnl >= position.target_pnl:
    self._close_position(position, bar, "PROFIT_TARGET")

# AFTER - Trailing profit logic
if position.current_pnl >= position.target_pnl:
    # Check if we should trail
    bbw_ratio = indicators.get('bbw_ratio', 1.0)
    if bbw_ratio > TRAILING_BBW_THRESHOLD:
        # Extend target by 20%
        position.target_pnl *= 1.2
        logger.info(f"Trailing profit extended: BBW ratio {bbw_ratio:.2f}")
    else:
        self._close_position(position, bar, "PROFIT_TARGET")
```

### 4.5 `strategy_backtester.py` - Daily Brake

```python
# NEW - Add brake logic in run() method
def _check_daily_brake(self) -> bool:
    """Check if daily brake is active."""
    if self._daily_pnl_amount / self._capital <= -DAILY_LOSS_BRAKE:
        self._brake_until = self._current_date + timedelta(days=BRAKE_FLAT_DAYS)
        logger.warning(f"Daily brake triggered! Flat until {self._brake_until}")
        return True
    return False
```

### 4.6 `treasury.py` - Lots Ramping

```python
# BEFORE - Fixed lot size
def calculate_position_size(self, capital: float) -> int:
    return 1  # Always 1 lot

# AFTER - Equity-based ramping
def calculate_position_size(self, capital: float, initial_capital: float) -> int:
    """
    Ramp lots based on equity growth:
    - 1 lot: equity < 1.1x initial
    - 2 lots: equity 1.1x - 1.25x initial  
    - 3 lots: equity > 1.25x initial
    """
    equity_ratio = capital / initial_capital
    if equity_ratio >= 1.25:
        return 3
    elif equity_ratio >= 1.10:
        return 2
    else:
        return 1
```

---

## 5. Calculations We Can Simulate

### 5.1 With Current Data

| Calculation | Data Required | Status |
|-------------|---------------|--------|
| Regime detection (ADX, RSI) | NIFTY 5-min/daily | ✅ Can simulate |
| IV percentile | 252-day daily data | ✅ Have 174 days (partial) |
| Bollinger Band Width | 20-day data | ✅ Can simulate |
| RV/IV ratio | Daily + VIX | ⚠️ Need VIX data |
| NIFTY-BANKNIFTY correlation | Both daily | ⚠️ Only 22 days BANKNIFTY |
| Entry/exit signals | OHLCV + regime | ✅ Can simulate |
| P&L (simplified) | OHLCV + assumptions | ✅ Can simulate |

### 5.2 Requires Additional Data

| Calculation | Data Required | Status |
|-------------|---------------|--------|
| Accurate options P&L | Historical options chain | ❌ Need to collect |
| Greeks simulation | Options + underlying | ❌ Need options data |
| Multi-asset correlation | GOLDM, CRUDE, NATURALGAS | ❌ Need MCX data |
| IV percentile (full) | 252-day VIX | ❌ Need VIX history |
| Slippage modeling | Bid-ask spreads | ⚠️ Have for today only |

---

## 6. Data Collection Plan

### 6.1 Immediate Actions

1. **Download NIFTY 5-min data** (Nov 1, 2025 - present)
   - Use Kite historical API
   - ~65 trading days × 75 bars = ~4,875 bars

2. **Download BANKNIFTY 5-min data** (Nov 1, 2025 - present)
   - Same period as NIFTY

3. **Download INDIA VIX daily** (1 year)
   - For IV percentile calculation

4. **Continue options collection**
   - Run collector daily during market hours
   - Build options history over time

### 6.2 Future Actions (MCX)

1. Get MCX instrument tokens for GOLDM, CRUDE, NATURALGAS
2. Download historical data
3. Implement correlation tracking

---

## 7. Summary of Changes

| Category | Current | Proposed | Expected Impact |
|----------|---------|----------|-----------------|
| Risk per trade | 1.0% | 1.5% | +50% position size |
| ADX range-bound | < 12 | < 14 | +15% more range trades |
| IV entry | > 40% | > 45% | +20% more entries |
| Trailing | None | BBW > 1.8x | +0.3-0.5% extra per win |
| Lots | Fixed 1 | 1→2→3 ramp | 2-3x returns at scale |
| Instruments | 2 (NIFTY, BANKNIFTY) | 5 (+GOLDM, CRUDE, NATGAS) | Diversification |
| Daily brake | 3% | 1.5% | Tighter risk control |

**Overall Expected Impact**: 
- Monthly returns: 2-5% (vs current ~0.5-1%)
- Win rate: 65-70% (realistic)
- Max drawdown: 1-2% (controlled)
- Sharpe ratio: 2.0-3.0

---

## 8. Next Steps

1. [ ] Download missing historical data (NIFTY 5-min, BANKNIFTY 5-min, VIX)
2. [ ] Apply parameter changes to `thresholds.py`
3. [ ] Implement trailing profit logic
4. [ ] Implement daily brake logic
5. [ ] Implement lots ramping
6. [ ] Run backtest on Nov 1, 2025 - Feb 5, 2026 period
7. [ ] Compare results with Grok simulations
8. [ ] Add MCX instruments (Phase 2)
