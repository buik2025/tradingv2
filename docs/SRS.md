# Software Requirements Specification (SRS)
## Trading System v2.0 - Multi-Agent Algorithmic Trading Platform

**Version:** 1.0  
**Date:** February 2026  
**Status:** Draft  

---

## Table of Contents
1. [Introduction](#1-introduction)
2. [Overall Description](#2-overall-description)
3. [System Features & Functional Requirements](#3-system-features--functional-requirements)
4. [External Interface Requirements](#4-external-interface-requirements)
5. [Non-Functional Requirements](#5-non-functional-requirements)
6. [Data Requirements](#6-data-requirements)
7. [Appendices](#7-appendices)

---

## 1. Introduction

### 1.1 Purpose
This document specifies the software requirements for Trading System v2.0, a multi-agent, automated trading system for the Indian Stock Market (NSE/MCX). The system eliminates discretionary intervention by strictly adhering to regime-based logic with defined-risk structures.

### 1.2 Scope
Trading System v2.0 will:
- Detect market regimes (Range-Bound, Mean-Reversion, Trend, Chaos) using technical indicators and ML classifiers
- Generate trade signals for defined-risk option structures (Iron Condors, Jade Lizards, Risk Reversals)
- Enforce strict risk management with position-level and portfolio-level limits
- Execute trades via KiteConnect API (Zerodha)
- Provide backtesting capabilities for strategy validation
- Support paper trading mode for system validation

### 1.3 Definitions, Acronyms, and Abbreviations

| Term | Definition |
|------|------------|
| ADX | Average Directional Index - trend strength indicator |
| ATR | Average True Range - volatility measure |
| DTE | Days to Expiry |
| IV | Implied Volatility |
| OI | Open Interest |
| RSI | Relative Strength Index |
| VIX | Volatility Index (India VIX for NSE) |
| Greeks | Delta, Gamma, Theta, Vega - option risk measures |
| Iron Condor | Option strategy: short strangle + long wings |
| Jade Lizard | Option strategy: short put + short strangle |
| Risk Reversal | Option strategy: long call + short put (or vice versa) |

### 1.4 References
- KiteConnect API Documentation: https://kite.trade/docs/pykiteconnect/v4/
- NSE F&O Segment Specifications
- MCX Commodity Futures Specifications

### 1.5 Overview
The system follows a multi-agent architecture with five core agents:
- **Sentinel**: Market data ingestion and regime detection
- **Strategist**: Signal generation and structure selection
- **Treasury**: Risk management and position sizing
- **Executor**: Order placement and position monitoring
- **Monk**: Backtesting, validation, and ML model training

---

## 2. Overall Description

### 2.1 Product Perspective
Trading System v2.0 is a standalone application that interfaces with:
- Zerodha KiteConnect API for market data and order execution
- Local/cloud database for trade logging and state persistence
- ML models for regime classification

### 2.2 Product Functions
1. **Real-time Market Regime Detection** - Classify market into actionable regimes
2. **Automated Signal Generation** - Generate trade signals based on regime and rules
3. **Risk-First Position Sizing** - Calculate position sizes within risk limits
4. **Multi-Leg Order Execution** - Place and manage complex option structures
5. **Circuit Breaker Enforcement** - Auto-flatten on loss limits
6. **Backtesting & Validation** - Validate strategies on historical data
7. **Trade Journaling** - Log all trades with entry/exit reasons

### 2.3 User Classes and Characteristics
| User Class | Description | Frequency |
|------------|-------------|-----------|
| Trader (Primary) | Monitors system, reviews alerts, approves adjustments | Daily |
| Research-Self | Designs/modifies rules (monthly only) | Monthly |
| Audit-Self | Reviews performance, proposes parameter changes | Weekly |

### 2.4 Operating Environment
- **OS**: Linux/macOS/Windows
- **Runtime**: Python 3.10+
- **Broker**: Zerodha (KiteConnect API)
- **Market Hours**: NSE 9:15 AM - 3:30 PM IST, MCX varies by commodity
- **Network**: Stable internet connection with <100ms latency to broker

### 2.5 Design and Implementation Constraints
- Must use KiteConnect API (no direct exchange access)
- Historical data limited to what KiteConnect provides (F&O data availability)
- Order types limited to broker-supported types
- Rate limits: KiteConnect API rate limits apply
- No high-frequency trading (min 5-second intervals between orders)

### 2.6 Assumptions and Dependencies
- Valid Zerodha account with F&O trading enabled
- KiteConnect API subscription active
- Access token refreshed daily (manual or automated TOTP)
- Sufficient account margin for intended position sizes
- Historical data available for backtesting (minimum 2 months)

---

## 3. System Features & Functional Requirements

### 3.1 Agent: Sentinel ("The Eyes")

#### 3.1.1 FR-SEN-01: Data Ingestion
**Priority**: High  
**Description**: Fetch real-time and historical market data for approved instruments.

| Requirement ID | Description |
|----------------|-------------|
| FR-SEN-01.1 | Fetch 5-minute OHLCV candles for NIFTY 50 index via `kite.historical_data()` |
| FR-SEN-01.2 | Fetch 5-minute OHLCV candles for approved commodities (Gold, Silver, Crude) |
| FR-SEN-01.3 | Fetch real-time quotes via `kite.quote()` for active instruments |
| FR-SEN-01.4 | Fetch complete option chain with Greeks via `kite.instruments()` |
| FR-SEN-01.5 | Fetch India VIX real-time value |
| FR-SEN-01.6 | Support WebSocket streaming via KiteTicker for live data |
| FR-SEN-01.7 | Cache historical data locally to minimize API calls |

#### 3.1.2 FR-SEN-02: Regime Classification
**Priority**: High  
**Description**: Classify market into one of four regimes using technical indicators and ML.

| Requirement ID | Description |
|----------------|-------------|
| FR-SEN-02.1 | Calculate ADX (14-period) on 5-min bars |
| FR-SEN-02.2 | Calculate RSI (14-period) on 5-min bars |
| FR-SEN-02.3 | Calculate IV Percentile (20-day rolling rank) |
| FR-SEN-02.4 | Calculate Realized Volatility (5-min RV vs 20-day ATR) |
| FR-SEN-02.5 | Calculate Put/Call Skew divergence from historical average |
| FR-SEN-02.6 | Classify regime based on rules: |
| | - **RANGE_BOUND**: ADX < 12, IV percentile < 35%, RSI 40-60 |
| | - **MEAN_REVERSION**: ADX 12-22, RSI < 30 or > 70 |
| | - **TREND**: ADX > 22 or price breakout > 10 min |
| | - **CHAOS**: IV percentile > 75% or correlation spike > 0.5 |
| FR-SEN-02.7 | Run ML classifier (Logistic Regression/K-Means) for probabilistic regime |
| FR-SEN-02.8 | Override static rules if ML probability > 70% |

#### 3.1.3 FR-SEN-03: Correlation Gate
**Priority**: High  
**Description**: Monitor cross-asset correlations to prevent correlated blowups.

| Requirement ID | Description |
|----------------|-------------|
| FR-SEN-03.1 | Calculate 20-day rolling correlation between NIFTY and each commodity |
| FR-SEN-03.2 | Flag commodity as UNSAFE if correlation > |0.4| |
| FR-SEN-03.3 | Flag stock as UNSAFE if correlation with NIFTY > |0.6| |
| FR-SEN-03.4 | Disable multi-asset trading if any correlation > |0.5| intraday |

#### 3.1.4 FR-SEN-04: Event Calendar Integration
**Priority**: High  
**Description**: Maintain event calendar and enforce blackout windows.

| Requirement ID | Description |
|----------------|-------------|
| FR-SEN-04.1 | Maintain list of major events (RBI policy, Union Budget, Fed meetings, earnings) |
| FR-SEN-04.2 | Flag EVENT_RISK = true if within T-2 to T+1 days of major event |
| FR-SEN-04.3 | Block new short-vol positions during event windows |
| FR-SEN-04.4 | Auto-flatten 30 min before major events if exposure > 10% margin |

#### 3.1.5 FR-SEN-05: Universe Filtering
**Priority**: Medium  
**Description**: Filter approved instruments based on liquidity and correlation.

| Requirement ID | Description |
|----------------|-------------|
| FR-SEN-05.1 | Check liquidity: Average daily volume > 20x position size |
| FR-SEN-05.2 | Check OI: Open Interest > 10x max lots |
| FR-SEN-05.3 | Output approved universe list with reasons |
| FR-SEN-05.4 | Max concurrent underlyings: 1 index + up to 3 commodities/stocks |

---

### 3.2 Agent: Strategist ("The Brain")

#### 3.2.1 FR-STR-01: Signal Generation
**Priority**: High  
**Description**: Generate trade signals based on regime and entry rules.

| Requirement ID | Description |
|----------------|-------------|
| FR-STR-01.1 | In RANGE_BOUND regime, generate short-vol signals (Iron Condor, Jade Lizard) |
| FR-STR-01.2 | In MEAN_REVERSION regime, generate directional signals (Risk Reversal, Debit Spread) |
| FR-STR-01.3 | In TREND regime, generate only hedged trend-follow or no signal |
| FR-STR-01.4 | In CHAOS regime, generate FLATTEN_ALL signal |
| FR-STR-01.5 | Require minimum 3 metrics aligning for entry (e.g., ADX + RSI + skew) |
| FR-STR-01.6 | No entries in last 30 min of session (after 3:00 PM IST for NSE) |

#### 3.2.2 FR-STR-02: Option Chain Analysis
**Priority**: High  
**Description**: Select optimal strikes based on delta and structure requirements.

| Requirement ID | Description |
|----------------|-------------|
| FR-STR-02.1 | Fetch option chain with Greeks for target expiry |
| FR-STR-02.2 | Select short legs at 20-35 delta for Iron Condors |
| FR-STR-02.3 | Select long wings at 10-15 delta wider than short legs |
| FR-STR-02.4 | Verify bid-ask spread ≤ ₹2 for selected strikes |
| FR-STR-02.5 | Verify OI > 10,000 contracts at selected strikes |
| FR-STR-02.6 | Calculate max profit, max loss, and breakeven points |

#### 3.2.3 FR-STR-03: Structure Selection
**Priority**: High  
**Description**: Select appropriate option structure based on regime and conditions.

| Requirement ID | Description |
|----------------|-------------|
| FR-STR-03.1 | **Iron Condor**: Default for RANGE_BOUND, IV percentile > 40% |
| FR-STR-03.2 | **Jade Lizard**: For neutral-bullish bias in low vol |
| FR-STR-03.3 | **Butterfly**: For pinpointing low-vol sweet spots |
| FR-STR-03.4 | **Risk Reversal**: For MEAN_REVERSION with directional bias |
| FR-STR-03.5 | **Debit Spread**: For defined-risk directional plays |
| FR-STR-03.6 | **Calendar Spread**: For vol/theta play across expiries |

#### 3.2.4 FR-STR-04: Entry Conditions
**Priority**: High  
**Description**: Define precise entry conditions for each strategy.

**Iron Condor Entry (FR-STR-04.1)**:
- IV percentile > 40% (not selling cheap vol)
- No events in next 7 days
- Previous day's range < 1.2%
- No overnight gap > 1.5% in past 3 days
- Account equity above high watermark - 5%
- Entry at T-12 to T-10 days before weekly expiry

**Intraday Mean Reversion Entry (FR-STR-04.2)**:
- `is_range_day()` returns True
- Time between 10:00 AM - 2:00 PM IST
- Price at 5-min Bollinger Band extreme (2 std dev) OR at yesterday's high/low with rejection
- No intraday news pending in next 2 hours
- Max 2 active intraday positions

#### 3.2.5 FR-STR-05: Exit Conditions
**Priority**: High  
**Description**: Define precise exit conditions for each strategy.

**Iron Condor Exit (FR-STR-05.1)**:
- **Profit Target**: Exit at 60% of max profit
- **Stop Loss**: Exit if loss reaches 100% of credit collected
- **Time Exit**: Close at T-5 days regardless of P&L
- **Regime Override**: Exit if India VIX spikes > 20% intraday
- **Gap Override**: Exit at open if NIFTY gaps > 2% overnight

**Intraday Exit (FR-STR-05.2)**:
- **Profit Target**: 1.5% of margin deployed
- **Stop Loss**: 1% of account
- **Time Exit**: All positions closed by 3:15 PM IST
- **Regime Change**: Exit if price breaks yesterday's high/low by 0.3%

---

### 3.3 Agent: Treasury ("The Vault")

#### 3.3.1 FR-TRE-01: Position-Level Risk Limits
**Priority**: Critical  
**Description**: Enforce per-position risk limits.

| Requirement ID | Description |
|----------------|-------------|
| FR-TRE-01.1 | Max loss per trade: 1-2% of account equity |
| FR-TRE-01.2 | Max margin per position: 10-15% of account equity |
| FR-TRE-01.3 | Reject trade if position risk exceeds limits |
| FR-TRE-01.4 | Calculate position Greeks and enforce limits: |
| | - Net Delta: ±30 per ₹1Cr account |
| | - Net Gamma: ±0.3 per ₹1Cr account |
| | - Net Vega: ±400 per ₹1Cr account |

#### 3.3.2 FR-TRE-02: Portfolio-Level Risk Limits
**Priority**: Critical  
**Description**: Enforce portfolio-wide risk limits.

| Requirement ID | Description |
|----------------|-------------|
| FR-TRE-02.1 | Total margin utilization: Max 40% of account equity |
| FR-TRE-02.2 | Max simultaneous positions: 3 (1 short-vol + 2 intraday) |
| FR-TRE-02.3 | Max daily loss: 3% of account → STOP all trading rest of day |
| FR-TRE-02.4 | Max weekly loss: 5% of account → Flat for rest of week |
| FR-TRE-02.5 | Max monthly loss: 10% of account → Full audit, 2-week break |

#### 3.3.3 FR-TRE-03: Circuit Breakers
**Priority**: Critical  
**Description**: Automatic position flattening on limit breaches.

| Requirement ID | Description |
|----------------|-------------|
| FR-TRE-03.1 | Trigger FLATTEN_ALL if daily P&L < -1.5% of equity |
| FR-TRE-03.2 | Trigger FLATTEN_ALL if weekly P&L < -4% of equity |
| FR-TRE-03.3 | Trigger FLATTEN_ALL if regime = CHAOS for > 2 days |
| FR-TRE-03.4 | After 3 consecutive losing trades (> 0.5% each), flat for 1 day |
| FR-TRE-03.5 | Enforce flat period: No signals from Strategist during flat days |

#### 3.3.4 FR-TRE-04: Position Sizing
**Priority**: High  
**Description**: Calculate appropriate position sizes.

| Requirement ID | Description |
|----------------|-------------|
| FR-TRE-04.1 | Base risk per trade: 0.5-1% of equity |
| FR-TRE-04.2 | Calculate lots: `lots = floor(risk / (stop_loss × lot_value))` |
| FR-TRE-04.3 | Scale by ML confidence: +1 lot if prob > 0.8, -1 if < 0.7 |
| FR-TRE-04.4 | Reduce size by 50% if in drawdown (equity < peak - 5%) |
| FR-TRE-04.5 | Reduce size by 75% if in deep drawdown (equity < peak - 10%) |
| FR-TRE-04.6 | STOP all trading if equity < peak - 15% |

#### 3.3.5 FR-TRE-05: Drawdown Response Protocol
**Priority**: High  
**Description**: Automated size reduction during drawdowns.

```
IF current_equity < peak_equity × 0.95:  # -5% from peak
    position_size_multiplier = 0.5

IF current_equity < peak_equity × 0.90:  # -10% from peak
    position_size_multiplier = 0.25

IF current_equity < peak_equity × 0.85:  # -15% from peak
    STOP_ALL_TRADING()
    SEND_ALERT("15% drawdown - mandatory 30-day break")
```

---

### 3.4 Agent: Executor ("The Hands")

#### 3.4.1 FR-EXE-01: Order Placement
**Priority**: High  
**Description**: Place orders via KiteConnect API.

| Requirement ID | Description |
|----------------|-------------|
| FR-EXE-01.1 | Place multi-leg orders using `kite.place_order()` |
| FR-EXE-01.2 | Use LIMIT orders for short-vol entries (never market) |
| FR-EXE-01.3 | Use MARKET orders for stop-loss exits |
| FR-EXE-01.4 | Support bracket orders with target and stop-loss |
| FR-EXE-01.5 | Handle partial fills: Cancel if < 50% filled in 5 min |
| FR-EXE-01.6 | Log all order details (order_id, status, fill_price, timestamp) |

#### 3.4.2 FR-EXE-02: Position Monitoring
**Priority**: High  
**Description**: Monitor open positions for exit triggers.

| Requirement ID | Description |
|----------------|-------------|
| FR-EXE-02.1 | Poll positions every 1 minute during market hours |
| FR-EXE-02.2 | Calculate real-time P&L for each position |
| FR-EXE-02.3 | Check profit target hit → Execute exit |
| FR-EXE-02.4 | Check stop-loss hit → Execute exit |
| FR-EXE-02.5 | Check time-based exit (T-5 days, 3:15 PM) → Execute exit |
| FR-EXE-02.6 | Check regime change from Sentinel → Execute exit if required |

#### 3.4.3 FR-EXE-03: EOD Processing
**Priority**: High  
**Description**: End-of-day position management.

| Requirement ID | Description |
|----------------|-------------|
| FR-EXE-03.1 | Auto-square off all intraday positions at 3:15 PM IST |
| FR-EXE-03.2 | Log daily P&L summary |
| FR-EXE-03.3 | Update high watermark if equity increased |
| FR-EXE-03.4 | Check weekly/monthly loss limits |
| FR-EXE-03.5 | Generate daily trade report |

#### 3.4.4 FR-EXE-04: Hedging & Adjustments
**Priority**: Medium  
**Description**: Execute defensive hedges when triggered.

| Requirement ID | Description |
|----------------|-------------|
| FR-EXE-04.1 | Add delta hedge if net delta > ±15% of limit |
| FR-EXE-04.2 | Add vega hedge if net vega > ±40% of limit |
| FR-EXE-04.3 | No discretionary adjustments - only predefined rules |
| FR-EXE-04.4 | Auto-roll short leg if breached by 50% |

---

### 3.5 Agent: Monk ("The Sage")

#### 3.5.1 FR-MON-01: Backtesting Engine
**Priority**: High  
**Description**: Validate strategies on historical data.

| Requirement ID | Description |
|----------------|-------------|
| FR-MON-01.1 | Load historical data (min 2 months, ideally 2+ years) |
| FR-MON-01.2 | Simulate trades based on ruleset |
| FR-MON-01.3 | Include realistic costs (brokerage 0.03%, slippage 0.1-0.5%) |
| FR-MON-01.4 | Calculate performance metrics: |
| | - Net return (target > 10% annualized) |
| | - Sharpe ratio (target > 1.0) |
| | - Max drawdown (target < 15%) |
| | - Win rate (target > 55% directional, > 65% short-vol) |
| | - Profit factor (target > 1.5) |
| FR-MON-01.5 | Support out-of-sample validation (70/30 split) |
| FR-MON-01.6 | Support walk-forward optimization |

#### 3.5.2 FR-MON-02: Stress Testing
**Priority**: High  
**Description**: Test strategies under extreme conditions.

| Requirement ID | Description |
|----------------|-------------|
| FR-MON-02.1 | Monte Carlo simulation (1,000 runs with randomized vol spikes) |
| FR-MON-02.2 | What-if scenarios (+50% IV, correlated crashes) |
| FR-MON-02.3 | Fail validation if drawdown > 20% in > 5% of simulations |
| FR-MON-02.4 | Test against historical regime shifts (2020 crash, 2022 inflation) |

#### 3.5.3 FR-MON-03: ML Model Training
**Priority**: Medium  
**Description**: Train and maintain ML classifiers for regime detection.

| Requirement ID | Description |
|----------------|-------------|
| FR-MON-03.1 | Train Logistic Regression for binary range/trend classification |
| FR-MON-03.2 | Train K-Means (3-4 clusters) for regime clustering |
| FR-MON-03.3 | Features: [IV_rank, ADX, RSI, skew_div, RV/ATR_ratio, OI_change, corr] |
| FR-MON-03.4 | Validate: Accuracy > 75%, F1-score > 0.7 on out-of-sample |
| FR-MON-03.5 | Retrain quarterly or after 10% drawdown |
| FR-MON-03.6 | Cap threshold changes to ±5% per retrain |

#### 3.5.4 FR-MON-04: Trade Journaling
**Priority**: High  
**Description**: Log all trades with detailed metadata.

| Requirement ID | Description |
|----------------|-------------|
| FR-MON-04.1 | Log: Strategy, regime, entry/exit reason, P&L, emotional state |
| FR-MON-04.2 | Generate weekly performance report |
| FR-MON-04.3 | Identify patterns (losing on Mondays? After gaps?) |
| FR-MON-04.4 | Flag rule violations |
| FR-MON-04.5 | Calculate regime classification accuracy |

---

### 3.6 Ban List (Prohibited Behaviors)

#### 3.6.1 FR-BAN-01: Permanently Banned Structures
| Requirement ID | Description |
|----------------|-------------|
| FR-BAN-01.1 | Naked short strangles/straddles within T-5 days of expiry |
| FR-BAN-01.2 | Naked short options near events (within T-2 to T+1 days) |
| FR-BAN-01.3 | Unlimited risk setups without hedges |
| FR-BAN-01.4 | Complex structures > 4 legs without defined risk < 0.8% equity |

#### 3.6.2 FR-BAN-02: Permanently Banned Behaviors
| Requirement ID | Description |
|----------------|-------------|
| FR-BAN-02.1 | Discretionary overnight holds (must meet ADX/ML criteria) |
| FR-BAN-02.2 | Averaging into losing positions (martingale) |
| FR-BAN-02.3 | Ignoring regime filters |
| FR-BAN-02.4 | Trading during flat periods |
| FR-BAN-02.5 | More than 5 trades per day |
| FR-BAN-02.6 | Margin utilization > 40% of account |

---

## 4. External Interface Requirements

### 4.1 User Interfaces
| Interface | Description |
|-----------|-------------|
| UI-01 | CLI dashboard showing current regime, positions, P&L |
| UI-02 | Web dashboard (optional) for monitoring |
| UI-03 | Alert notifications (email/SMS/Telegram) for critical events |
| UI-04 | Trade journal viewer |

### 4.2 Hardware Interfaces
- Standard computing hardware (no specialized requirements)
- Reliable internet connection (min 10 Mbps)

### 4.3 Software Interfaces

| Interface | Description |
|-----------|-------------|
| SI-01 | KiteConnect REST API for orders, positions, quotes |
| SI-02 | KiteTicker WebSocket for real-time streaming |
| SI-03 | SQLite/PostgreSQL for trade logging |
| SI-04 | File system for historical data cache |

### 4.4 Communication Interfaces
| Interface | Description |
|-----------|-------------|
| CI-01 | HTTPS for KiteConnect API |
| CI-02 | WSS for KiteTicker WebSocket |
| CI-03 | SMTP for email alerts |
| CI-04 | Telegram Bot API for instant alerts |

---

## 5. Non-Functional Requirements

### 5.1 Performance Requirements
| Requirement ID | Description |
|----------------|-------------|
| NFR-PERF-01 | Processing loop (Data → Decision → Order) < 2 seconds |
| NFR-PERF-02 | Regime detection calculation < 500ms |
| NFR-PERF-03 | Order placement latency < 1 second |
| NFR-PERF-04 | Support 100+ concurrent option chain fetches |
| NFR-PERF-05 | Backtest 1 year of data in < 5 minutes |

### 5.2 Reliability Requirements
| Requirement ID | Description |
|----------------|-------------|
| NFR-REL-01 | Auto-reconnect on KiteTicker disconnect (max 3 retries) |
| NFR-REL-02 | Persist state to recover from crashes |
| NFR-REL-03 | Graceful degradation if data feed delayed |
| NFR-REL-04 | 99.9% uptime during market hours |

### 5.3 Security Requirements
| Requirement ID | Description |
|----------------|-------------|
| NFR-SEC-01 | API keys loaded from .env, never hardcoded |
| NFR-SEC-02 | Access token encrypted at rest |
| NFR-SEC-03 | Audit log of all system actions |
| NFR-SEC-04 | No sensitive data in logs |

### 5.4 Maintainability Requirements
| Requirement ID | Description |
|----------------|-------------|
| NFR-MAIN-01 | Modular agent architecture for independent updates |
| NFR-MAIN-02 | Configuration-driven parameters (no hardcoded thresholds) |
| NFR-MAIN-03 | Comprehensive logging with log levels |
| NFR-MAIN-04 | Unit test coverage > 80% |

### 5.5 Portability Requirements
| Requirement ID | Description |
|----------------|-------------|
| NFR-PORT-01 | Run on Linux, macOS, Windows |
| NFR-PORT-02 | Docker containerization support |
| NFR-PORT-03 | No platform-specific dependencies |

---

## 6. Data Requirements

### 6.1 Historical Data Requirements
| Data Type | Source | Granularity | Retention |
|-----------|--------|-------------|-----------|
| NIFTY OHLCV | KiteConnect | 5-min | 2+ years |
| Option Chain | KiteConnect | Daily | 1 year |
| India VIX | KiteConnect | 5-min | 1 year |
| MCX Commodities | KiteConnect | 5-min | 1 year |
| Event Calendar | Manual/API | Daily | Rolling 1 year |

### 6.2 Real-Time Data Requirements
| Data Type | Source | Frequency |
|-----------|--------|-----------|
| NIFTY Spot | KiteTicker | Tick |
| Option Quotes | KiteTicker | Tick |
| India VIX | KiteTicker | Tick |
| Account Balance | KiteConnect | On-demand |
| Positions | KiteConnect | 1-min polling |

### 6.3 Derived Data
| Data Type | Calculation | Frequency |
|-----------|-------------|-----------|
| ADX (14) | TA-Lib | Every 5-min bar |
| RSI (14) | TA-Lib | Every 5-min bar |
| IV Percentile | 20-day rolling rank | Daily |
| Correlation Matrix | 20-day rolling | Daily |
| Greeks | Black-Scholes | Real-time |

---

## 7. Appendices

### 7.1 Approved Instruments

**Tier 1 (Primary)**:
- NIFTY 50 Index Options (Weekly/Monthly expiry)
- Lot size: 25 (current) / 65 (from Jan 2026)

**Tier 2 (Conditional - correlation gated)**:
- MCX Goldm (100 grams/lot)
- MCX Silverm (5 kg/lot)
- MCX CrudeOil (100 barrels/lot)
- Top 10 NIFTY 50 stocks by liquidity

**Permanently Excluded**:
- BankNifty, FinNifty (until NIFTY strategies proven 12+ months)
- Mid/small-cap stocks
- Crypto, Forex

### 7.2 Regime Classification Thresholds

| Regime | ADX | IV Percentile | RSI | Other |
|--------|-----|---------------|-----|-------|
| RANGE_BOUND | < 12 | < 35% | 40-60 | ML prob > 0.7 |
| MEAN_REVERSION | 12-22 | 35-70% | < 30 or > 70 | ML prob > 0.65 |
| TREND | > 22 | Any | Any | Breakout > 10 min |
| CHAOS | Any | > 75% | Any | Corr spike > 0.5 |

### 7.3 Position Sizing Table

| Account Size | Max Margin | Max Loss/Trade | Max Lots |
|--------------|------------|----------------|----------|
| ₹25L | ₹10L (40%) | ₹25K (1%) | 2 |
| ₹50L | ₹20L (40%) | ₹50K (1%) | 4 |
| ₹1Cr | ₹40L (40%) | ₹1L (1%) | 8 |

### 7.4 Glossary
- **High Watermark**: Peak account equity value
- **Flat Period**: Mandatory no-trading period after loss limits
- **Regime**: Market classification driving strategy selection
- **Circuit Breaker**: Automatic position flattening trigger

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Feb 2026 | System | Initial draft |

---
*End of SRS Document*
