# v2 Rulebook Gap Analysis - Implementation vs Theory

**Date:** February 6, 2026  
**Status:** Comprehensive Analysis Complete  
**Focus:** Agents, Live Trading, and Backtesting

---

## Executive Summary

The trading system has a **solid architectural foundation** with all 5 core agents implemented and functioning. However, significant **gaps exist between the v2 rulebook requirements and actual implementation**, particularly in:

1. **Strategy Coverage**: ~40% of allowed structures implemented
2. **Risk Management**: Thresholds exist but no enforcement during live execution
3. **Live Trading**: Paper mode only, no real broker integration readiness
4. **Backtesting**: Framework exists but incomplete metrics and no stress testing
5. **Monitoring & Observability**: Minimal logging/metrics for production
6. **Testing & Validation**: Zero unit test coverage for critical logic

---

## Section-by-Section Gap Analysis

### Section 1: Allowed Instruments and Universe

**Rulebook Requirements:**
- NIFTY index options (weekly/monthly, 20-35 delta)
- Commodities: Goldm, Silverm, Crude, NaturalGas (gated by corr < |0.4|)
- Top 10 NIFTY 50 stocks (corr < |0.6|)
- Daily Sentinel checks: liquidity/OI (>10x size), correlations, events
- Max 4 underlyings concurrent

**Current Implementation Status:**

| Component | Status | Gap |
|-----------|--------|-----|
| **NIFTY index options** | ✅ Implemented | None - basic NIFTY/BANKNIFTY trading working |
| **Commodities (Gold/Silver)** | ❌ Not implemented | No connection to MCX data; missing lot size mappings |
| **Crude/NaturalGas** | ❌ Not implemented | Zero code for energy commodities |
| **Top 10 NIFTY 50** | ❌ Partial | Static list in config, no dynamic correlation filtering |
| **Liquidity checks** | ⚠️ Partial | IV/OI thresholds exist but not enforced at entry |
| **Correlation matrix** | ✅ Implemented | Works for NIFTY/BANKNIFTY, missing commodity correlations |
| **Event calendar** | ❌ Not implemented | Empty list; no NSE holiday or earnings integration |
| **Max 4 underlyings** | ⚠️ Partial | Position count limit exists but no underlying diversity check |

**Key Gaps:**
1. **Commodities Data Missing**: No MCX integration → Can't trade Goldm, Silverm, Crude, NaturalGas per rulebook
2. **Event Calendar Empty**: System ignores RBI decisions, earnings announcements, market holidays
3. **Dynamic Universe**: No runtime instrument filtering based on correlation; static config only
4. **Liquidity Enforcement**: Bid/ask spread and OI checks in thresholds but not enforced in order placement

**Impact:** Cannot execute ~40% of intended diversification strategy; vulnerable to illiquid execution.

---

### Section 2: Position Structures and Trade Types

**Rulebook Structures Required:**

| Structure | Max Count | Current Status | Gap |
|-----------|-----------|-----------------|-----|
| **Iron Condor** | 3/day | ✅ Implemented | Complete |
| **Jade Lizard** | Part of 3 | ⚠️ Partial | Class exists, not integrated into Strategist flow |
| **Butterfly** | Part of 3 | ⚠️ Partial | File exists (`butterfly.py`), not integrated |
| **Broken-Wing Butterfly** | Part of 3 | ⚠️ Partial | File exists, untested, no mean-reversion trigger |
| **Credit Spread** | Part of 3 | ❌ Not implemented | No dedicated implementation |
| **Calendar Spread** | Part of 3 | ❌ Not implemented | No implementation |
| **Diagonal Spread** | - | ❌ Not implemented | No implementation |
| **Naked Strangle** | Part of 3 | ⚠️ Partial | File exists (`strangle.py`), disabled by default |
| **Conditional Naked Strangle** | Max 2 days | ❌ Not implemented | No IV < 15th percentile enforcement |
| **Risk Reversal** | 4/day | ⚠️ Partial | File exists, integration needs testing |
| **Debit Spreads** | - | ❌ Not implemented | No implementation |
| **Ratio Spreads** | For hedging | ❌ Not implemented | No implementation |

**Code Review Findings:**

```python
# From strategist.py - Only Iron Condor reliably integrated
if "naked_strangle" in self.enabled_strategies:
    strangle_proposal = self._generate_strangle(regime_packet)
    # But disabled by default, untested

# Jade Lizard exists but never called
self._jade_lizard = JadeLizardStrategy(lot_size=50)
# No _generate_jade_lizard() method exists

# Butterfly exists but no regime trigger
self._butterfly = ButterflyStrategy(lot_size=50)
# No method calls to this class
```

**Critical Gaps:**
1. **50% of Structures Not Implemented**: Calendar, Diagonal, Debit spreads missing
2. **40% Partial Implementation**: Jade Lizard, Butterfly, BWB, Strangle exist but not integrated
3. **No Regime-Specific Triggers**: Structures not automatically selected per regime
4. **No Time-Based Constraints**: Conditional Naked Strangle (max 2 days) not enforced

**Impact:** System locked to Iron Condor only; cannot adapt to different regime conditions per rulebook.

---

### Section 3: Regime Detection and Filters

**Rulebook Requirements:**
- Range-bound: ADX < 14, IV < 45%, ML prob > 0.7
- Mean-reversion: ADX 14-27, RSI < 35 or > 65
- Trend: ADX > 27
- Chaos: ≥4 triggers (vol spike + corr + ADX + BBW expansion)
- ML classifier with >85% accuracy
- Multi-asset metrics with corr gating

**Current Implementation Status:**

| Metric | Rulebook | Implementation | Gap |
|--------|----------|-----------------|-----|
| **ADX Range-Bound** | < 14 | 14 (matching) | ✅ Correct |
| **ADX Trend** | > 27 | 22 (too low) | ⚠️ False positives |
| **RSI Oversold** | < 35 | 30 (matching) | ✅ Correct |
| **RSI Overbought** | > 65 | 70 (close) | ✅ Acceptable |
| **Confluence Requirement** | ≥4 for CHAOS | 3 triggers | ⚠️ Still vulnerable |
| **BBW Metric** | < 0.5x avg for range | ✅ Calculated | ✅ Implemented |
| **RV/IV Ratio** | < 0.8 for theta | ✅ Calculated | ✅ Implemented |
| **ML Classifier** | > 85% accuracy | None trained | ❌ Missing |
| **Event Blackout** | Ban around events | ✅ Logic exists | ⚠️ No events in calendar |
| **ML CHAOS Override** | > 0.85 prob | 0.90 threshold | ⚠️ Different threshold |

**Code Review:**

```python
# thresholds.py
ADX_RANGE_BOUND = 14  # ✅ Correct
ADX_MEAN_REVERSION_MAX = 22  # ❌ Should be 25-27
ADX_TREND_MIN = 22  # ❌ Should be 27

# ML classifier not trained
self.ml_classifier = ml_classifier  # Passed as None in production
if ml_classifier and ml_probability > ML_OVERRIDE_PROBABILITY:
    # Code path never executed without trained model
```

**Critical Gaps:**
1. **ADX Trend Threshold Too Low**: 22 vs required 27 → causes false TREND classifications
2. **No Trained ML Model**: Zero code to train/load classifier; all ML logic inactive
3. **Confluence at 3 Not 4**: CHAOS triggers only require 3 confluence, not ≥4 per rulebook
4. **No Mean-Reversion Regime**: System has CAUTION but no specific MEAN_REVERSION entry logic
5. **Event Calendar Empty**: Event blackout checks have no actual events

**Impact:** Regime misclassification rate unknown; ML safety nets not active; false positives undetected.

---

### Section 4: Entry and Exit Rules

**Rulebook Requirements:**
- Confluence ≥2 metrics for entry (ATR, RSI, skew)
- No entries last 30 min session
- Short-vol exit: 1.4-1.8% margin or regime shift/35% loss
- Directional exit: 1.4-2.2% or 0.8-1.2% loss/regime change
- Hedging triggers: Net delta >±12% or vega >±35%
- Multi-asset: Corr check; exit if spike > |0.5|

**Current Implementation Status:**

| Component | Status | Gap |
|-----------|--------|-----|
| **Confluence ≥2** | ✅ Implemented | Working in Sentinel |
| **No entries last 30 min** | ✅ Implemented | Entry window 9:15-15:00 |
| **Short-vol targets (1.4-1.8%)** | ⚠️ Partial | Fixed at 60% max profit, not dynamic |
| **Regime change exit** | ⚠️ Partial | Logic exists, untested in live mode |
| **Delta hedging (>±12%)** | ❌ Not implemented | No auto-hedge logic |
| **Vega hedging (>±35%)** | ❌ Not implemented | Greeks tracked but no hedging engine |
| **Correlation exit** | ⚠️ Partial | Alert generated but no auto-exit |
| **Multi-leg order atomicity** | ⚠️ Partial | Rollback logic exists but untested |

**Code Issues:**

```python
# From strategist.py - no confluence enforcement at leg level
def _generate_iron_condor(self, regime_packet: RegimePacket) -> Optional[TradeProposal]:
    # Checks regime but NOT individual signal confluence

# From executor.py - no delta hedging
def process(self, signal: TradeSignal) -> ExecutionResult:
    # Places orders but no Greeks monitoring
    # No auto-hedge on delta breach

# No vega limit enforcement
# Treasury checks Greeks but only for position limits, not dynamic hedging
```

**Critical Gaps:**
1. **No Dynamic Exit Targets**: All exits at fixed 60% profit, not 1.4-1.8% range
2. **No Auto-Hedging**: Vega/Delta hedging rules not implemented
3. **No Correlation Exit**: Alert exists but trade not forced to close
4. **No Mean-Reversion Confirmation**: RSI/ATR confluence not verified per entry
5. **No Trailing Profit Logic**: Rulebook Section 11 (trailing) not integrated with exits

**Impact:** Cannot adapt exit timing; no hedge protection; vulnerability to Greeks breaches.

---

### Section 5: Sizing and Allocation Rules

**Rulebook Requirements:**
- Max margin 20% equity
- Max open positions 5
- Diversification: if corr > |0.3|, halve higher-vol asset
- Risk 1.5% per trade
- Lots ramp 1-3 (scale by ML prob > 0.8)
- Greeks caps: short vega < -60% equity, gamma < -0.15%
- +10% margin in low-vol
- -50% if daily loss -1%

**Current Implementation Status:**

| Parameter | Rulebook | Code | Status |
|-----------|----------|------|--------|
| **Max margin %** | 20% | 20% | ✅ Correct |
| **Max positions** | 5 | 5 | ✅ Correct |
| **Risk per trade** | 1.5% | 1.5% | ✅ Correct |
| **Lots ramping** | 1-3 | 3 max | ✅ Implemented |
| **ML threshold for ramp** | > 0.8 | No ML check | ❌ Missing |
| **Vega cap** | -60% equity | No cap | ⚠️ Only position limit |
| **Gamma cap** | -0.15% | No cap | ⚠️ Only position limit |
| **Low-vol bonus** | +10% margin | Not implemented | ❌ Missing |
| **Daily loss reduction** | -50% after -1% | ⚠️ Brake mechanism | Partial |
| **Diversification rule** | Corr > 0.3 | Not implemented | ❌ Missing |

**Code Review:**

```python
# From treasury.py - only basic limits
MAX_LOSS_PER_TRADE = 0.015  # 1.5% ✅
MAX_DAILY_LOSS = 0.015  # 1.5%
MAX_VEGA = -0.6  # Greeks cap only at position level

# From strategy_backtester.py - lots ramping works
def _calculate_lots(self) -> int:
    equity_ratio = self._capital / self._initial_capital
    if equity_ratio >= 1.25: return 3  # ✅ Works
    elif equity_ratio >= 1.10: return 2
    return 1
# BUT: No ML probability check

# Missing: Low-vol bonus, diversification enforcement
```

**Critical Gaps:**
1. **No ML-Based Ramping**: Lots ramp by equity, not ML confidence (0.8 threshold)
2. **Missing Vega/Gamma Allocation**: Greeks limits only on position count, not portfolio Greeks
3. **No Low-VIX Margin Bonus**: +10% in low-vol not implemented
4. **No Diversification Enforcement**: Corr > 0.3 check not in position sizing
5. **Loss Multiplier Incomplete**: Brake exists but -50% size reduction post-loss not enforced

**Impact:** Over-allocated in uncertain conditions; under-allocated in favorable conditions; Greeks exposure uncapped.

---

### Section 6: Risk Management and Brakes

**Rulebook Brakes:**
- Daily -1.5% → flatten/rest day
- Weekly -4% → flat 3 days
- Monthly -10% → flat 1 week + review
- Chaos/trend >2 days → flat 1 day + ML confirm
- 3 consecutive losers → flat 1 day + 50% size reduction
- ML prob loss >0.6 → preemptive flatten

**Current Implementation Status:**

| Brake | Rulebook | Implementation | Status |
|-------|----------|-----------------|--------|
| **Daily -1.5%** | Flatten + rest | `_trigger_brake()` exists | ✅ Implemented |
| **Weekly -4%** | Flat 3 days | Not implemented | ❌ Missing |
| **Monthly -10%** | Flat 1 week | Not implemented | ❌ Missing |
| **Chaos >2 days** | Flat 1 day | Not implemented | ❌ Missing |
| **3 consecutive losers** | Flat 1 day + 50% | Not implemented | ❌ Missing |
| **ML loss probability** | > 0.6 → preemptive | Not implemented | ❌ Missing |
| **Greeks breach** | Auto-hedge/flatten | Alerts only | ⚠️ No execution |

**Code Review:**

```python
# From strategy_backtester.py - only daily brake
def _trigger_brake(self, current_date: date) -> None:
    from ..config.thresholds import BRAKE_FLAT_DAYS
    self._brake_until = current_date + timedelta(days=BRAKE_FLAT_DAYS)
    # ✅ Works for daily

# Missing: Weekly/monthly tracking, consecutive loss logic, ML loss prediction
```

**Critical Gaps:**
1. **No Weekly/Monthly Brakes**: System only stops after daily loss; no cumulative protection
2. **No Consecutive Loss Logic**: 3 losers → 50% reduction not implemented
3. **No ML Loss Prediction**: No model to predict high-loss probability trades
4. **No Regime-Based Brakes**: CHAOS >2 days → forced halt not implemented
5. **No Greeks Breach Flattening**: Only alerts, no auto-action

**Impact:** Exposed to multi-day drawdown cascades; no circuit breaker protection beyond daily.

---

### Section 7: Ban List and Prohibited Behaviors

**Rulebook Bans:**
- Unlimited risk structures
- Naked near-expiry
- Averaging/martingale
- >4 legs without risk < 1.2% margin
- Discretionary overrides
- Revenge sizing
- Holding >max time
- Cycling/revenge patterns → ban structure for week
- Over-sizing post-win → cap at 80%

**Current Implementation:**

| Ban | Status | Notes |
|-----|--------|-------|
| **Unlimited risk** | ✅ Enforced | Max loss defined for all trades |
| **Naked near-expiry** | ⚠️ Partial | No expiry proximity check |
| **Averaging/martingale** | ✅ Excluded | Not in strategy set |
| **>4 legs without risk cap** | ⚠️ Partial | Max legs = 4 but no margin check |
| **Discretionary overrides** | ✅ No manual override in code | Backend only |
| **Revenge sizing** | ❌ Not detected | No behavior analysis |
| **Cycling detection** | ❌ Not implemented | No pattern tracking |
| **Post-win over-sizing** | ❌ Not implemented | No win streak detection |

**Critical Gaps:**
1. **No Behavioral Monitoring**: Revenge sizing, cycling patterns not detected
2. **No Temporal Constraints**: No "max holding time" enforcement
3. **No Near-Expiry Checks**: Can trade options near expiry
4. **No Win-Based Sizing Cap**: 80% cap after wins not enforced
5. **No Pattern Recognition**: ML doesn't detect revenge trading

**Impact:** Cannot prevent behavioral blunders; system could over-trade after wins.

---

### Section 8: Monitoring and Adjustment Protocols

**Rulebook Requirements:**
- Real-time Sentinel: P&L/Greeks/slippage monitoring (>0.5% → alert/auto-correct)
- EOD/Weekly review: Win rate >60%, Sharpe >1.0, regime accuracy >80%
- ML anomaly prob >0.6 → review
- Adjustments only: 4 weeks positive + backtest >10% edge
- Separation: Research vs live
- Audit logs weekly

**Current Implementation:**

| Component | Status | Gap |
|-----------|--------|-----|
| **Real-time P&L monitoring** | ⚠️ Partial | WebSocket updates exist |
| **Greeks tracking** | ✅ Implemented | Per-position Greeks calculated |
| **Slippage detection** | ❌ Not implemented | No order fill vs expected tracking |
| **EOD review metrics** | ⚠️ Partial | Logged but no automated alerts |
| **Win rate threshold** | ❌ Not checked | No auto-review trigger |
| **Regime accuracy tracking** | ⚠️ Partial | Logged but no validation |
| **ML anomaly detection** | ❌ Not implemented | No ML model to detect anomalies |
| **Adjustment approval gate** | ❌ Not implemented | No "4 weeks positive" check |
| **Audit logs** | ✅ Implemented | Loguru logs to file |
| **Research vs live separation** | ⚠️ Partial | Paper mode exists but no backtest separation |

**Code Issues:**

```python
# From routes.py - WebSocket exists but limited
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocketConnection):
    # Broadcasts P&L but no slippage alerts

# No slippage calculation
# No automated win rate review
# No "4 weeks positive" gate for adjustments

# Missing: ML anomaly detection, Monk integration
```

**Critical Gaps:**
1. **No Slippage Alerts**: >0.5% difference not detected
2. **No Automated Adjustment Gates**: 4-week positive curve not validated
3. **No Win Rate Auto-Review**: No trigger at 60% threshold
4. **No ML Anomaly Detection**: No model to flag suspicious trades
5. **No Monk Integration**: Backtest validation not enforced before changes

**Impact:** Cannot catch execution issues; system could accept rule changes without validation.

---

### Section 9: Backtesting and Validation Requirements

**Rulebook Metrics:**
- Data: 5+ years NSE/MCX, tick/5-min bars, include costs/slippage
- Metrics: Return >10% annualized, Sharpe >1.0, DD < 15%, WR 55-65%, PF >1.5
- Process: 70/30 in/out-sample, 1000 Monte Carlo sims, stress (vol +50%, gaps)
- ML validation: Accuracy >75%, F1 >0.7; retrain quarterly
- Pass: All metrics on out-sample + stress

**Current Implementation:**

| Requirement | Status | Gap |
|-------------|--------|-----|
| **5+ years data** | ⚠️ Partial | Download capability exists, not validated |
| **Tick/5-min bars** | ✅ Implemented | 5-min data collected |
| **Include costs/slippage** | ⚠️ Partial | Brokerage exists; slippage not modeled |
| **Return >10% annualized** | ✅ Backtested | Recent sims show 196% on edge case |
| **Sharpe >1.0** | ⚠️ Varies | 0.23-11.4 range; inconsistent |
| **Drawdown <15%** | ✅ Achieved | Most runs <0.44% |
| **Win rate 55-65%** | ⚠️ Varies | 42-99% range; no consistent distribution |
| **Profit factor >1.5** | ✅ Mostly achieved | 1.73-4.17 range |
| **70/30 split** | ⚠️ Partial | No explicit split validation |
| **1000 Monte Carlo** | ❌ Not implemented | No stress testing framework |
| **Stress vol +50%** | ❌ Not implemented | No perturbation tests |
| **ML validation** | ❌ Not implemented | No classifier trained/validated |
| **Quarterly retrain** | ❌ Not implemented | No automation for model updates |

**Code Review:**

```python
# From monk.py - framework exists but incomplete
def validate_strategy(
    self, ruleset: Dict, data: pd.DataFrame,
    initial_capital: float = 1000000
) -> Tuple[bool, Dict]:
    # Runs backtest but missing:
    trades = self._run_backtest(ruleset, data, initial_capital)
    # - 70/30 split enforcement
    # - stress test
    # - ML validation

def stress_test(self, ...):
    # Framework exists but never called in production
    # No perturbation logic implemented
```

**Critical Gaps:**
1. **No Out-of-Sample Validation**: 70/30 split not enforced; all runs on same data
2. **No Monte Carlo Stress Tests**: No perturbation of prices/volatility
3. **No ML Model Validation**: Classifier never trained; F1 score never calculated
4. **No Quarterly Retrain Scheduling**: No automation for model updates
5. **No Slippage Modeling**: Costs included but execution slippage not modeled

**Impact:** Backtest results unreliable; over-fit to historical data; unknown generalization error.

---

### Section 10: Agent Integration Mapping

**Rulebook Flow:**
```
Sentinel (regime + metrics) 
  ↓
Strategist (trade proposals)
  ↓
Treasury (risk approval)
  ↓
Executor (order placement)
  ↓
Monk (backtesting/learning)
```

**Current Implementation Status:**

| Agent | Implemented | Status | Gap |
|-------|-------------|--------|-----|
| **Sentinel** | ✅ Complete | Regime detection working | Minor ML integration |
| **Strategist** | ⚠️ Partial | Iron Condor only; other structures disabled | 50% coverage |
| **Treasury** | ✅ Complete | Risk limits enforced | Missing Greeks-based hedging |
| **Executor** | ⚠️ Partial | Paper trading works; live untested | No live execution readiness |
| **Monk** | ⚠️ Partial | Framework exists; backtesting incomplete | No validation gate enforcement |

**Integration Issues:**

```python
# Example flow (strategist.py)
def process(self, regime_packet: RegimePacket) -> List[TradeProposal]:
    proposals = []
    
    if regime_packet.regime == RegimeType.CHAOS:
        return proposals  # ✅ Works
    
    if regime_packet.regime == RegimeType.RANGE_BOUND:
        # Only Iron Condor tries
        ic_proposal = self._generate_iron_condor(regime_packet)
        # ❌ Jade Lizard method _generate_jade_lizard() doesn't exist
        # ❌ Butterfly/Strangle not called
        
    # ❌ MEAN_REVERSION not specifically handled
    # ❌ CAUTION only generates Jade Lizard but method missing
```

**Critical Gaps:**
1. **Strategist-Monk Loop Broken**: No feedback from Monk to adjust Strategist rules
2. **No Dynamic Structure Selection**: All regimes default to Iron Condor
3. **Incomplete Method Implementations**: jade_lizard generator missing
4. **No Live Execution Path**: Executor only has paper mode
5. **No Post-Trade Learning**: Monk validates but results not fed back

**Impact:** System can't adapt; same strategy regardless of regime; no automated learning.

---

### Section 11: Trailing Profit Rules

**Rulebook Specifications:**
- Start at >50% target profit
- ATR-based for directional (±0.5x ATR, update every 15 min)
- BBW for short-vol (>1.8x avg → exit if profitable)
- Monitor range; lock 50-70% on expansion
- Disable on regime shift/Greeks breach
- Buffer for slippage (0.1%)

**Current Implementation Status:**

| Component | Status | Gap |
|-----------|--------|-----|
| **50% profit threshold** | ✅ Constant defined | `TRAILING_PROFIT_MIN = 0.50` |
| **ATR-based trailing** | ❌ Not implemented | Only fixed target extension |
| **15-min update cycle** | ❌ Not implemented | No recurring update |
| **BBW expansion trigger** | ⚠️ Partial | Threshold defined (1.8x) but not used |
| **50-70% profit lock** | ❌ Not implemented | No partial exit logic |
| **Regime shift disable** | ❌ Not implemented | No regime-change monitoring in execution |
| **Greeks breach disable** | ❌ Not implemented | No Greeks-based exit trigger |
| **Slippage buffer 0.1%** | ❌ Not implemented | No buffer applied |

**Code Review:**

```python
# From strategy_backtester.py
TRAILING_BBW_THRESHOLD = 1.8  # Defined but not used
TRAILING_PROFIT_MIN = 0.50     # Defined but not used
TRAILING_EXTENSION = 1.2       # Defined but not used

def _should_trail_profit(self, position, regime) -> bool:
    # Framework exists but minimal logic
    # Only checks profit threshold, not ATR or 15-min updates
    if position.current_pnl >= position.target_pnl * 0.5:
        return True  # Too simplistic
    return False
```

**Critical Gaps:**
1. **No ATR-Based Trailing**: Static extension not dynamic ATR-based
2. **No Time-Based Updates**: Single check at exit, not every 15 min
3. **No Partial Profit Locking**: Can't lock 50-70% and let rest run
4. **No Regime-Change Monitoring**: Doesn't check regime in real-time
5. **No Slippage Buffer**: No 0.1% protection zone

**Impact:** Trailing profits sub-optimal; missed extension opportunities; no adaptive defense.

---

## Critical Implementation Gaps Summary

### By Priority

#### P0 - BLOCKING (Prevent Live Trading)

| Gap | Impact | Effort |
|-----|--------|--------|
| **Event Calendar Empty** | No market holiday/earnings protection | 2-3 days |
| **Commodities Not Integrated** | Can't diversify per Section 1 | 3-5 days |
| **Live Broker Integration** | Executor only in paper mode | 5-7 days |
| **ML Classifier Not Trained** | Regime ML safety net inactive | 3-4 days |
| **No Unit Test Coverage** | Critical logic unvalidated | 5-7 days |
| **Credentials Not Encrypted** | Security risk for live trading | 2-3 days |
| **No Out-of-Sample Backtesting** | Results unreliable; over-fit | 3-4 days |

#### P1 - DEGRADED (Live but Limited)

| Gap | Impact | Effort |
|-----|--------|--------|
| **50% of Structures Disabled** | Limited strategy diversity | 3-4 days |
| **No Dynamic Exit Targeting** | Fixed 60% vs 1.4-1.8% range | 2-3 days |
| **Weekly/Monthly Brakes Missing** | No cumulative loss protection | 2-3 days |
| **No Greeks-Based Hedging** | Delta/Vega limits only on position count | 4-5 days |
| **No Behavioral Monitoring** | Can't detect revenge trading | 2-3 days |
| **Trailing Profits Non-Functional** | Missing Section 11 rules | 2-3 days |
| **No Slippage Alerts** | Can't detect execution issues | 2-3 days |
| **Regime Accuracy Unchecked** | Unknown false positive rate | 2-3 days |

#### P2 - ENHANCEMENT (Operational)

| Gap | Impact | Effort |
|-----|--------|--------|
| **No Observability Dashboard** | Hard to monitor system | 3-4 days |
| **API Resilience Missing** | Failures cascade | 2-3 days |
| **No Audit Trail** | Compliance risk | 2-3 days |
| **ML Anomaly Detection Absent** | Can't flag suspicious patterns | 3-4 days |
| **No Quarterly Retrain** | Models decay over time | 2-3 days |

---

## Implementation Roadmap

### Phase 0 (Foundation Fixes) - 2-3 weeks

**Goals:** Unblock live trading safety

1. **Event Calendar** (2-3 days)
   - Integrate NSE calendar (yoptions or pandas.tseries.holiday)
   - Add earnings calendar
   - Create events_calendar.json
   - Test blackout logic

2. **ML Classifier Training** (3-4 days)
   - Collect historical regime labels
   - Engineer features: [IV_rank, ADX, RSI, skew, RV/ATR, BBW, volume]
   - Train RandomForest with cross-validation
   - Validate >75% accuracy on out-sample
   - Deploy to Sentinel

3. **Credentials Encryption** (2-3 days)
   - Add Fernet encryption to KiteCredentials
   - Migrate existing data
   - Update `.env` handling
   - Add startup validation

4. **Unit Tests Framework** (3-4 days)
   - Write tests for Sentinel regime classification
   - Write tests for Treasury risk validation
   - Write tests for Greeks calculations
   - Target >80% coverage on core logic
   - Set up CI/CD in GitHub Actions

5. **Out-of-Sample Backtesting** (3-4 days)
   - Implement 70/30 split validation in Monk
   - Add stress test framework
   - Run 1000 Monte Carlo simulations
   - Document results

### Phase 1 (Strategy Expansion) - 2-3 weeks

**Goals:** Implement 50% of missing structures

1. **Integrate Missing Structures** (4-5 days)
   - Implement `_generate_jade_lizard()` method
   - Implement `_generate_butterfly()` method
   - Implement `_generate_broken_wing_butterfly()` method
   - Implement `_generate_strangle()` fully
   - Add regime-specific structure selection

2. **Dynamic Exit Targeting** (2-3 days)
   - Replace fixed 60% with 1.4-1.8% margin targets
   - Implement short-vol vs directional logic
   - Add regime-based exit multipliers

3. **Trailing Profit Execution** (2-3 days)
   - Implement ATR-based trailing
   - Add 15-min update cycle
   - Implement partial profit locking (50-70%)
   - Add regime/Greeks change checks

### Phase 2 (Risk Management) - 2-3 weeks

**Goals:** Comprehensive brake system

1. **Weekly/Monthly Brakes** (2-3 days)
   - Track cumulative weekly loss
   - Trigger 3-day flat at -4%
   - Track cumulative monthly loss
   - Trigger 1-week flat at -10%

2. **Consecutive Loss Logic** (2-3 days)
   - Track win/loss streak
   - Trigger 50% reduction after 3 consecutive losses
   - Reset on winning trade

3. **Greeks-Based Hedging** (4-5 days)
   - Implement vega hedge on breach >±35%
   - Implement delta hedge on breach >±12%
   - Auto-structure hedges with offsets
   - Monitor and unwind when neutral

4. **Behavioral Monitoring** (3-4 days)
   - Track revenge trading patterns
   - Detect cycling (repeated same-direction trades)
   - Cap sizing at 80% after wins
   - ML anomaly detection for suspicious trades

### Phase 3 (Live Trading Readiness) - 2-3 weeks

**Goals:** Operational excellence

1. **Live Broker Integration** (4-5 days)
   - Full KiteConnect integration
   - Multi-leg order execution
   - Position tracking from broker
   - Daily P&L reconciliation

2. **Observability & Monitoring** (3-4 days)
   - Prometheus metrics
   - Grafana dashboards
   - Correlation IDs for request tracing
   - Performance alerts (>100ms operations)

3. **Commodities Integration** (3-4 days)
   - MCX data connection
   - Correlation gating (<0.4 with NIFTY)
   - Lot size mapping for Gold/Silver/Crude/Gas
   - Universe testing

4. **Documentation & Runbooks** (2-3 days)
   - Deployment guide
   - Emergency flatten procedures
   - Troubleshooting guide
   - On-call runbook

---

## Detailed Implementation Checklist

### Sentinel Agent

- [ ] Train ML classifier with historical data
- [ ] Fix ADX thresholds (trend = 27, not 22)
- [ ] Integrate event calendar
- [ ] Implement 4-trigger CHAOS requirement (not 3)
- [ ] Add mean-reversion specific regime logic
- [ ] Test regime accuracy on historical data

### Strategist Agent

- [ ] Implement `_generate_jade_lizard()` method
- [ ] Implement `_generate_butterfly()` method
- [ ] Implement `_generate_broken_wing_butterfly()` method
- [ ] Fully integrate StrangleStrategy
- [ ] Add regime-specific structure routing
- [ ] Implement dynamic profit targets by structure
- [ ] Add skew divergence signals (>20% threshold)
- [ ] Implement RSI extreme confirmation

### Treasury Agent

- [ ] Implement weekly loss tracking
- [ ] Implement monthly loss tracking
- [ ] Add consecutive loss counter
- [ ] Implement vega hedge triggering (>±35%)
- [ ] Implement delta hedge triggering (>±12%)
- [ ] Add diversification enforcement (corr >0.3)
- [ ] Implement low-VIX margin bonus (+10%)
- [ ] Add ML-based lot ramping (0.8 threshold)

### Executor Agent

- [ ] Implement live broker order placement
- [ ] Add order fill tracking from broker
- [ ] Implement position reconciliation
- [ ] Add slippage detection (>0.5% alert)
- [ ] Implement regime-change exit logic
- [ ] Add Greeks-based exit triggers
- [ ] Implement emergency flatten
- [ ] Add failure recovery/rollback

### Monk Agent

- [ ] Implement 70/30 split validation
- [ ] Build Monte Carlo stress test framework
- [ ] Add perturbation tests (vol +50%, gaps)
- [ ] Implement ML classifier training pipeline
- [ ] Add quarterly retrain scheduling
- [ ] Create validation gate for rule changes
- [ ] Implement backtesting metrics dashboard

### Data & Infrastructure

- [ ] Integrate NSE holiday calendar
- [ ] Create earnings event calendar
- [ ] Integrate MCX commodity data
- [ ] Implement credentials encryption
- [ ] Set up `.env` validation
- [ ] Add comprehensive logging (correlation IDs)
- [ ] Create Prometheus metrics exporter
- [ ] Build Grafana dashboards

### Testing & Quality

- [ ] Write Sentinel regime tests (20+ tests)
- [ ] Write Treasury risk tests (15+ tests)
- [ ] Write Executor order tests (10+ tests)
- [ ] Write Greeks calculation tests (25+ tests)
- [ ] Integration tests for full pipeline (5+ tests)
- [ ] Achieve >80% code coverage
- [ ] Set up GitHub Actions CI/CD

### Documentation

- [ ] Create deployment runbook
- [ ] Document environment variables
- [ ] Create troubleshooting guide
- [ ] Write ML model update procedure
- [ ] Create on-call runbook
- [ ] Document rule changes process

---

## Estimated Timeline

| Phase | Duration | Blockers | Owner |
|-------|----------|----------|-------|
| **Phase 0** | 2-3 weeks | None | Engineering |
| **Phase 1** | 2-3 weeks | Phase 0 complete | Engineering |
| **Phase 2** | 2-3 weeks | Phase 1 complete | Risk/Engineering |
| **Phase 3** | 2-3 weeks | Phase 2 complete | Ops/Engineering |
| **Total** | ~8-12 weeks | - | - |

**Go/No-Go Criteria Before Live:**
- [ ] All P0 gaps resolved
- [ ] Unit test coverage >80%
- [ ] Backtest metrics passed on out-sample
- [ ] ML classifier accuracy >75%
- [ ] Event calendar fully populated
- [ ] Manual trade execution tested end-to-end
- [ ] Drawdown protection verified
- [ ] Emergency procedures tested

---

## Conclusion

The trading system has a **strong architectural foundation** but **significant gaps remain before production readiness**. The implementation covers ~60% of the v2 rulebook with core agents functional but features disabled.

**Key findings:**
1. **Agents working**: All 5 agents exist and partially functional
2. **Strategy limited**: Iron Condor only; 50% of structures disabled
3. **Risk controls incomplete**: Daily brakes work; weekly/monthly missing
4. **Regime detection fragile**: ML not trained; event calendar empty
5. **Live trading not ready**: Paper mode only; no encryption/validation
6. **Backtesting unreliable**: No out-of-sample validation; no stress tests

**Recommendation:** Complete Phase 0 (event calendar, ML training, encryption, tests) before any live trading. This work will take 2-3 weeks and is non-negotiable for safety.

---

**Document Generated:** February 6, 2026  
**Next Review:** After Phase 0 completion  
**Owner:** Engineering / Risk Management
