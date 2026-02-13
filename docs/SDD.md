# Software Design Document (SDD)
## Trading System v2.5 - Multi-Agent Algorithmic Trading Platform

**Version:** 2.5  
**Date:** February 2026  
**Status:** Active  

---

## Table of Contents
1. [Introduction](#1-introduction)
2. [System Architecture](#2-system-architecture)
3. [Component Design](#3-component-design)
4. [Data Design](#4-data-design)
5. [Interface Design](#5-interface-design)
6. [Algorithm Design](#6-algorithm-design)
7. [Trading Engine Flow](#7-trading-engine-flow)
8. [v2.5 Rulebook Updates](#8-v25-rulebook-updates)
9. [Backtesting Architecture](#9-backtesting-architecture)

---

## 1. Introduction

### 1.1 Purpose
This document describes the software design for Trading System v2.5, detailing the architecture, components, data structures, algorithms, and interfaces. Version 2.5 introduces significant enhancements including sustained trigger counters, Kelly-based sizing, and refined circuit breakers.

### 1.2 Design Goals
1. **Modularity**: Independent, loosely-coupled agents
2. **Testability**: Each component testable in isolation
3. **Configurability**: All parameters externalized
4. **Reliability**: Fault-tolerant with state recovery
5. **Performance**: Sub-second decision latency

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     TRADING SYSTEM v2.0                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [KiteTicker] ──► [CORE WRAPPER] ──► [ORCHESTRATOR]            │
│  [KiteConnect]         │                   │                    │
│                   [DataCache]              │                    │
│                                            ▼                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    AGENT LAYER                           │   │
│  │                                                          │   │
│  │  SENTINEL ──► STRATEGIST ──► TREASURY ──► EXECUTOR      │   │
│  │      │                                        │          │   │
│  │      └────────────► MONK ◄────────────────────┘          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                   │
│  ┌─────────────────────────▼───────────────────────────────┐   │
│  │  [SQLite DB]    [State JSON]    [Log Files]             │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Project Structure

```
trading_v2/
├── .env                          # API keys (from .env.example)
├── requirements.txt              # Dependencies
├── config/
│   ├── settings.py               # Configuration loader
│   ├── constants.py              # System constants
│   └── thresholds.py             # Regime thresholds
├── core/
│   ├── kite_client.py            # KiteConnect wrapper
│   ├── data_cache.py             # Historical data caching
│   ├── logger.py                 # Loguru configuration
│   └── state_manager.py          # State persistence
├── agents/
│   ├── base_agent.py             # Abstract base class
│   ├── sentinel.py               # Regime detection
│   ├── strategist.py             # Signal generation
│   ├── treasury.py               # Risk management
│   ├── executor.py               # Order execution
│   └── monk.py                   # Backtesting & ML
├── models/
│   ├── regime.py                 # RegimePacket
│   ├── trade.py                  # TradeProposal, TradeSignal
│   ├── order.py                  # OrderTicket, ExecutionResult
│   └── position.py               # Position model
├── strategies/
│   ├── iron_condor.py            # Iron Condor
│   ├── jade_lizard.py            # Jade Lizard
│   └── risk_reversal.py          # Risk Reversal
├── indicators/
│   ├── technical.py              # ADX, RSI, ATR
│   └── volatility.py             # IV percentile, RV
├── backtesting/
│   ├── engine.py                 # Backtest engine
│   ├── data_loader.py            # Historical data loader
│   └── metrics.py                # Performance metrics
├── ml/
│   ├── regime_classifier.py      # ML classification
│   └── trainer.py                # Model training
├── database/
│   ├── models.py                 # SQLAlchemy models
│   └── repository.py             # Data access layer
├── tests/                        # Unit tests
├── data/                         # Historical data, ML models
├── logs/                         # Log files
├── state/                        # State persistence
└── main.py                       # Entry point
```

---

## 3. Component Design

### 3.1 KiteClient (`core/kite_client.py`)

```python
class KiteClient:
    """KiteConnect wrapper with retry logic and caching."""
    
    def __init__(self, api_key: str, access_token: str): ...
    def fetch_historical_data(self, token: int, interval: str, 
                              from_date: datetime, to_date: datetime) -> pd.DataFrame: ...
    def get_quote(self, tokens: List[int]) -> Dict: ...
    def get_option_chain(self, symbol: str, expiry: date) -> pd.DataFrame: ...
    def place_order(self, tradingsymbol: str, quantity: int, 
                    transaction_type: str, order_type: str, price: float = None) -> str: ...
    def get_positions(self) -> List[Dict]: ...
    def get_margins(self) -> Dict: ...
```

### 3.2 Sentinel Agent (`agents/sentinel.py`)

```python
class Sentinel(BaseAgent):
    """Market regime detection agent."""
    
    def process(self, instrument_token: int) -> RegimePacket:
        """
        1. Fetch 5-min OHLCV data (20 days)
        2. Calculate: ADX(14), RSI(14), IV percentile, RV/ATR
        3. Check event calendar
        4. Calculate correlations
        5. Classify regime (rules + ML)
        6. Return RegimePacket
        """
        
    def _classify_regime(self, metrics: Dict) -> Tuple[RegimeType, float]:
        """
        Rules:
        - RANGE_BOUND: ADX < 12, IV < 35%, RSI 40-60
        - MEAN_REVERSION: ADX 12-22, RSI < 30 or > 70
        - TREND: ADX > 22
        - CHAOS: IV > 75% or correlation spike > 0.5
        
        ML override if probability > 70%
        """
```

### 3.3 Strategist Agent (`agents/strategist.py`)

```python
class Strategist(BaseAgent):
    """Signal generation agent."""
    
    def process(self, regime_packet: RegimePacket) -> List[TradeProposal]:
        """
        1. Check time restrictions (10 AM - 3 PM)
        2. If RANGE_BOUND: generate short-vol signals
        3. If MEAN_REVERSION: generate directional signals
        4. If TREND/CHAOS: no signals
        """
        
    def _generate_iron_condor(self, option_chain: pd.DataFrame) -> TradeProposal:
        """
        Entry conditions:
        - IV percentile > 40%
        - No events in 7 days
        - Previous day range < 1.2%
        - No gaps > 1.5% in 3 days
        - Entry at T-12 to T-10 days
        
        Structure:
        - Short 25-delta call + Short 25-delta put
        - Long 15-delta call + Long 15-delta put
        
        Exit:
        - Profit: 60% of max profit
        - Stop: 100% of credit collected
        - Time: T-5 days mandatory
        """
```

### 3.4 Treasury Agent (`agents/treasury.py`)

```python
class Treasury(BaseAgent):
    """Risk management agent."""
    
    def process(self, proposal: TradeProposal, 
                account: AccountState) -> Tuple[bool, Order]:
        """
        Checks:
        1. Circuit breakers (flat days, daily/weekly loss)
        2. Position count (max 3)
        3. Margin utilization (max 40%)
        4. Per-trade risk (max 1% of equity)
        5. Greeks limits (delta ±30, gamma ±0.3, vega ±400)
        6. Apply drawdown multiplier
        """
        
    def _get_drawdown_multiplier(self, account: AccountState) -> float:
        """
        - Drawdown >= 15%: 0.0 (stop trading)
        - Drawdown >= 10%: 0.25
        - Drawdown >= 5%: 0.50
        - Otherwise: 1.0
        """
```

### 3.5 Executor Agent (`agents/executor.py`)

```python
class Executor(BaseAgent):
    """Order execution agent."""
    
    def process(self, order: ApprovedOrder) -> ExecutionResult:
        """Place multi-leg orders, wait for fills."""
        
    def monitor_positions(self, positions: List[Position]) -> List[str]:
        """
        Check for:
        - EOD exit (3:15 PM for intraday)
        - Profit target hit
        - Stop loss hit
        - T-5 exit for short vol
        """
        
    def flatten_all(self, reason: str) -> List[ExecutionResult]:
        """Emergency flatten all positions."""
```

### 3.6 Monk Agent (`agents/monk.py`)

```python
class Monk(BaseAgent):
    """Backtesting and ML agent."""
    
    def validate_strategy(self, ruleset: Dict, data_path: str) -> Tuple[bool, Dict]:
        """
        Validation criteria:
        - Sharpe ratio >= 1.0
        - Max drawdown <= 15%
        - Win rate >= 55%
        - Profit factor >= 1.5
        """
        
    def stress_test(self, ruleset: Dict, num_sims: int = 1000) -> Tuple[bool, Dict]:
        """Monte Carlo: fail if drawdown > 20% in > 5% of sims."""
        
    def train_regime_classifier(self, data_path: str) -> RegimeClassifier:
        """Train ML model. Features: IV, ADX, RSI, skew, RV/ATR, OI, corr."""
```

---

## 4. Data Design

### 4.1 Pydantic Models

```python
class RegimePacket(BaseModel):
    timestamp: datetime
    regime: RegimeType  # RANGE_BOUND, MEAN_REVERSION, TREND, CHAOS
    ml_probability: float
    metrics: Dict[str, float]  # adx, rsi, iv_percentile
    event_flag: bool
    correlations: Dict[str, float]
    approved_universe: List[str]
    is_safe: bool

class TradeProposal(BaseModel):
    id: str
    structure: str  # IRON_CONDOR, JADE_LIZARD, etc.
    instrument: str
    legs: List[TradeLeg]
    entry_price: float
    target_pnl: float
    stop_loss: float
    max_loss: float
    required_margin: float
    greeks: Dict[str, float]
    expiry: date

class Position(BaseModel):
    id: str
    strategy_type: str
    legs: List[TradeLeg]
    entry_price: float
    current_pnl: float
    target_pnl: float
    stop_loss: float
    days_to_expiry: int
    is_intraday: bool

class AccountState(BaseModel):
    equity: float
    margin_used: float
    high_watermark: float
    daily_pnl: float
    weekly_pnl: float
    open_positions: List[Position]
    portfolio_greeks: Dict[str, float]
    flat_days_remaining: int
```

### 4.2 Database Schema

```sql
CREATE TABLE trades (
    id TEXT PRIMARY KEY,
    timestamp DATETIME,
    strategy TEXT,
    structure TEXT,
    instrument TEXT,
    regime_at_entry TEXT,
    entry_reason TEXT,
    exit_reason TEXT,
    entry_price REAL,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL,
    margin_used REAL
);

CREATE TABLE positions (
    id TEXT PRIMARY KEY,
    trade_id TEXT REFERENCES trades(id),
    strategy_type TEXT,
    legs TEXT,  -- JSON
    entry_price REAL,
    target_pnl REAL,
    stop_loss REAL,
    expiry DATE,
    status TEXT  -- OPEN, CLOSED
);

CREATE TABLE regime_log (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    regime TEXT,
    ml_probability REAL,
    adx REAL,
    rsi REAL,
    iv_percentile REAL
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    event_name TEXT,
    event_type TEXT,  -- RBI, BUDGET, FED
    start_date DATE,
    end_date DATE,
    blackout_start DATE,
    blackout_end DATE
);
```

---

## 5. Interface Design

### 5.1 Configuration (`config/settings.py`)

```python
class Settings(BaseSettings):
    # API
    kite_api_key: str
    kite_access_token: str
    
    # Tokens
    nifty_token: int = 256265
    india_vix_token: int = 264969
    
    # Thresholds
    adx_range_bound: int = 12
    adx_trend: int = 22
    iv_low: int = 35
    iv_high: int = 75
    correlation_threshold: float = 0.4
    
    # Risk Limits
    max_margin_pct: float = 0.40
    max_loss_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    max_weekly_loss: float = 0.05
    max_positions: int = 3
    
    # Greeks
    max_delta: int = 30
    max_gamma: float = 0.3
    max_vega: int = 400
    
    class Config:
        env_file = ".env"
```

### 5.2 Main Orchestrator and TradingEngine

The system uses a centralized `TradingEngine` that encapsulates all trading logic, ensuring consistency between live trading and backtesting.

**File**: `app/api/orchestrator.py`

```python
class Orchestrator:
    def __init__(self, config: Settings):
        self.kite = KiteClient(config.kite_api_key, config.kite_access_token)
        self.sentinel = Sentinel(self.kite, config)
        self.strategist = Strategist(self.kite, config)
        self.treasury = Treasury(self.kite, config, state_manager)
        self.executor = Executor(self.kite, config)
        
        # v2.5: Centralized TradingEngine
        self.trading_engine = TradingEngine(
            sentinel=self.sentinel,
            strategist=self.strategist,
            treasury=self.treasury,
            executor=self.executor,
            state_manager=state_manager,
            kite=self.kite
        )
        
    async def _run_iteration(self):
        """Single iteration of trading loop."""
        result = self.trading_engine.run_iteration(NIFTY_TOKEN)
        # Log results, update state, notify via WebSocket
```

**File**: `app/core/trading_engine.py`

```python
class TradingEngine:
    """
    Centralized trading logic used by both Orchestrator (live) and Backtest runner.
    Ensures identical decision-making across all modes.
    """
    
    def run_iteration(self, instrument_token: int) -> IterationResult:
        """
        Execute one complete trading iteration.
        
        Steps:
        1. Sentinel: Detect regime
        2. Treasury: Get account state
        3. Executor: Monitor positions for exits
        4. Check entry window (v2.5: 9:30-11:00 IST)
        5. Strategist: Generate proposals (if in window)
        6. Treasury: Validate proposals
        7. Executor: Execute approved signals
        """
        result = IterationResult()
        
        # Step 1: Regime detection
        regime = self.sentinel.process(instrument_token)
        result.regime = regime
        
        # Step 2: Account state
        account = self.treasury.get_account_state()
        
        # Step 3: Monitor exits
        current_prices = self.kite.get_ltp([...])
        exits = self.executor.monitor_positions(current_prices, regime.regime)
        for exit_order in exits:
            self.executor.execute_exit(exit_order)
            result.exits.append(exit_order)
        
        # Step 4: Entry window check (v2.5)
        if not self._in_entry_window():
            result.skip_reason = "Outside entry window"
            return result
        
        # Step 5: Generate proposals
        proposals = self.strategist.process(regime)
        
        # Step 6-7: Validate and execute
        for proposal in proposals:
            approved, signal, reason = self.treasury.process(
                proposal, account, regime.metrics.india_vix, regime.correlations
            )
            if approved:
                exec_result = self.executor.process(signal)
                result.entries.append(exec_result)
        
        return result
```

---

## 6. Algorithm Design

### 6.1 Regime Detection Algorithm (v2.5)

**File**: `app/services/agents/sentinel.py`

```
INPUT: 20 days of 5-min OHLCV data, event calendar, correlations
OUTPUT: RegimePacket (regime, veto_shortvol, warning_state, metrics)

1. Fetch market data:
   - OHLCV from KiteClient
   - India VIX
   - Option chain for IV calculation

2. Calculate indicators:
   - ADX(14), RSI(14), ATR(14)
   - Bollinger Band Width (BBW)
   - IV percentile (20-day rank)
   - RV/IV ratio
   - Volume ratio

3. Check events and correlations:
   - Event calendar (RBI, earnings, expiry)
   - NIFTY/BANKNIFTY correlation

4. Run DC (Directional Change) detection:
   - HMM-based regime classification
   - SMEI sentiment scoring

5. Calculate confluence score:
   - Count chaos triggers (vol spike, corr, ADX, BBW expansion)
   - IF triggers >= 4: CHAOS
   - IF triggers >= 2: CAUTION

6. v2.5: Update sustained trigger counter (Ref L/N):
   - Track consecutive days of chaos triggers
   - IF sustained_days >= 2: veto_shortvol = True
   - IF sustained_days == 1: warning_state = True

7. Apply static regime rules:
   - IF ADX < 14 AND IV < 45% AND 40 <= RSI <= 60: RANGE_BOUND
   - ELIF ADX 14-27 AND (RSI < 35 OR RSI > 65): MEAN_REVERSION
   - ELIF ADX > 27: TREND
   - ELSE: CAUTION

8. ML override (if probability > 0.7)

9. Compute hybrid vote (static + ML + DC)

RETURN RegimePacket(regime, metrics, veto_shortvol, warning_state, sustained_chaos_days)
```

**Regime Thresholds** (`app/config/thresholds.py`):

| Regime | ADX | IV Percentile | RSI | Confluence |
|--------|-----|---------------|-----|------------|
| RANGE_BOUND | < 14 | < 45% | 40-60 | < 2 |
| MEAN_REVERSION | 14-27 | any | < 35 or > 65 | < 2 |
| TREND | > 27 | any | any | < 2 |
| CAUTION | any | any | any | 2-3 |
| CHAOS | any | any | any | ≥ 4 |

### 6.2 Strategy Selection Algorithm (v2.5)

**File**: `app/services/strategies/strategy_selector.py`

```
INPUT: RegimePacket, DTE (optional)
OUTPUT: List[(StructureType, entry_conditions)]

1. Check veto_shortvol flag (v2.5 Ref L/N):
   - IF veto_shortvol = True: return only directional structures (Risk Reversal)

2. Check regime:
   - IF CHAOS: return [] (no entries)

3. v2.5 Ref J - Event Override:
   - IF event_flag = True AND DTE >= 10: allow entry (override blackout)
   - IF event_flag = True AND DTE < 10: return [] (no entry)

4. Map regime to structures:
   | Regime | Allowed Structures |
   |--------|-------------------|
   | RANGE_BOUND | Iron Condor, Butterfly, Jade Lizard, Strangle |
   | CAUTION | Jade Lizard only (hedged) |
   | MEAN_REVERSION | Risk Reversal, BWB |
   | TREND | Risk Reversal, Jade Lizard |

5. v2.5 Ref K - High-IV Boost:
   - IF IV percentile > 50% AND VIX elevated:
     - Boost targets to 1.8-2.2%
     - Tighten adjustment threshold to -0.3%

6. v2.5 Ref M - Skew Check:
   - IF call_IV > put_IV + 5%: favor Risk Reversals

RETURN structures with entry conditions
```

### 6.3 Iron Condor Entry Algorithm (v2.5)

**File**: `app/services/strategies/iron_condor.py`

```
INPUT: RegimePacket, OptionChain
OUTPUT: TradeProposal or None

1. Check entry conditions:
   - regime = RANGE_BOUND
   - IV percentile > 40%
   - No events in next 7 days (or v2.5 event override)
   - Previous day range < 1.2%
   - No gaps > 1.5% in past 3 days
   - v2.5: Entry window 9:30-11:00 IST
   - Days to expiry: 10-12

2. Select strikes (v2.5: delta 30):
   - Find 30-delta call strike (short call)
   - Find 30-delta put strike (short put)
   - Long call = short call + 10 delta width
   - Long put = short put - 10 delta width

3. Verify liquidity:
   - Bid-ask spread <= ₹2 for all strikes
   - OI > 10,000 for all strikes

4. Calculate structure:
   - Net credit = (short_call + short_put) - (long_call + long_put)
   - Max loss = wing_width - net_credit
   - Max profit = net_credit
   - v2.5: Target = 1.5-2.2% (high-IV boost if applicable)
   - Stop = -1% to -2%

5. Build proposal:
   - legs = [short_call, short_put, long_call, long_put]
   - Calculate Greeks (sum of all legs)

RETURN TradeProposal
```

### 6.4 Position Monitoring Algorithm (v2.5)

**File**: `app/services/execution/executor.py` → `monitor_positions()`

```
INPUT: List[Position], current_prices, current_regime
OUTPUT: List[ExitOrder]

FOR each position:
    1. Update P&L from current prices

    2. Check EOD exit (intraday only):
       - IF is_intraday AND time >= 3:15 PM: EXIT

    3. v2.5: Check trailing stop (BBW-based for short-vol):
       - IF trailing_mode = "bbw":
         - IF BBW > 1.8x avg AND profitable: EXIT immediately
         - IF BBW > 1.5x avg AND profitable: lock 60% of gains
         - IF current_pnl < locked_amount: EXIT
       - IF trailing_mode = "atr":
         - Update trailing stop at ±0.5x ATR
         - IF current_pnl <= trailing_stop: EXIT
       - v2.5: Post-adjustment tightening:
         - IF adjustment_count > 0: tighten stop by 75%

    4. Check profit target:
       - IF current_pnl >= target_pnl: EXIT

    5. Check stop loss:
       - IF current_pnl <= stop_loss: EXIT

    6. Check time-based exit:
       - IF days_to_expiry <= exit_dte (default 5): EXIT

    7. Check regime override:
       - IF regime = CHAOS: EXIT all positions

RETURN exit_orders
```

**File**: `app/models/position.py` → `update_trailing_stop()`

### 6.5 Risk Validation Algorithm (v2.5)

**File**: `app/services/execution/treasury.py` → `process()`

```
INPUT: TradeProposal, AccountState, VIX, correlations
OUTPUT: (approved: bool, TradeSignal, reason: str)

1. Check circuit breakers:
   - IF halted (daily/weekly/monthly/chaos): REJECT

2. Check position count:
   - v2.5: Max 2 NIFTY + 1 secondary = 3 total

3. Check margin utilization:
   - v2.5: Max 20% (was 40%)
   - Low-VIX bonus: +10% if VIX < 14

4. Check per-trade risk:
   - Max 2% loss per trade

5. Check Greeks limits:
   - Delta ±50, Gamma ±0.5, Vega ±5000

6. Calculate sizing multipliers:
   a. Drawdown multiplier:
      - 5% DD → 50% size
      - 10% DD → 25% size
      - 15% DD → STOP
   
   b. Streak multiplier:
      - 3 consecutive losers → 50% reduction
      - 5+ wins → cap at 100%
   
   c. Diversification multiplier:
      - IF correlation > 0.3 with existing: 50% reduction
   
   d. v2.5 Kelly multiplier:
      - kelly_f = (win_rate * avg_win - loss_rate * avg_loss) / (avg_win * loss_rate)
      - Apply fractional Kelly (0.5-0.7x)
   
   e. v2.5 Psych cap multiplier:
      - IF drawdown > -2%: force 1 lot
      - IF sentiment < -0.3: force 1 lot
   
   f. v2.5 Warning state multiplier:
      - IF warning_state = True: force 1 lot (~33%)

7. Calculate final multiplier:
   final = dd * streak * diversification * kelly * psych * warning

8. Adjust proposal size and create TradeSignal

RETURN (True, signal, "Approved")
```

### 6.6 Circuit Breaker Algorithm (v2.5)

**File**: `app/services/execution/circuit_breaker.py`

```
Thresholds (v2.5 updates):
- Daily loss: -1.5% → flat 1 day
- Weekly loss: -4% → flat 3 days
- Monthly loss: -8% (v2.5: was -10%) → flat 1 week + Monk audit
- Consecutive losses: 3 → 50% size reduction
- ML loss probability > 0.6 → preemptive halt
- v2.5 Chaos sustained: 2+ days → flat 48 hours

States:
- ACTIVE: Normal trading
- DAILY_HALT: Daily limit hit
- WEEKLY_HALT: Weekly limit hit
- MONTHLY_HALT: Monthly limit hit (requires Monk audit)
- PREEMPTIVE_HALT: ML predicted high loss probability
- CHAOS_HALT: v2.5 sustained chaos triggers

Methods:
- update_equity(new_equity): Recalculate loss percentages
- record_trade(pnl, is_win, ml_loss_prob): Update metrics
- trigger_chaos_halt(sustained_days): v2.5 chaos halt
- is_halted(): Check if trading should stop
- get_size_multiplier(): Return 0.5 if reduction active
```

---

## 7. Trading Engine Flow

### 7.1 Complete Iteration Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    ITERATION START (every minute)               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: SENTINEL - Regime Detection                           │
│  • Fetch market data (OHLCV, IV, VIX)                          │
│  • Calculate indicators (ADX, RSI, ATR, BBW)                   │
│  • Check events, correlations, DC/HMM                          │
│  • v2.5: Update sustained trigger counter                       │
│  • Output: RegimePacket (regime, veto_shortvol, warning_state) │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: TREASURY - Get Account State                          │
│  • Current equity, margin, positions                           │
│  • Drawdown calculation                                        │
│  • Portfolio Greeks                                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: EXECUTOR - Monitor Positions for Exits                │
│  • Update P&L for all positions                                │
│  • Check profit targets, stop losses                           │
│  • v2.5: BBW-based trailing (>1.8x → exit)                     │
│  • v2.5: Post-adjustment 75% tighten                           │
│  • Check time-based exits (DTE ≤ 5)                            │
│  • Check regime change → CHAOS = exit all                      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: TIME CHECK                                             │
│  • v2.5: Entry window 9:30-11:00 IST only                       │
│  • Outside window → skip to end (no new entries)               │
└─────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │ In Entry Window?      │
                    └───────────┬───────────┘
              YES ◄─────────────┴─────────────► NO (skip to end)
                │                               
                ▼                               
┌───────────────────────────────┐               
│  STEP 5: STRATEGY SELECTOR    │               
│  • Map regime → structures    │               
│  • v2.5 Ref J: Event override │               
│  • v2.5 Ref K: High-IV boost  │               
│  • v2.5 Ref M: Skew check     │               
│  • Check veto_shortvol        │               
└───────────────────────────────┘               
                │                               
                ▼                               
┌───────────────────────────────┐               
│  STEP 6: GENERATE PROPOSALS   │               
│  • Fetch option chain         │               
│  • Select strikes (delta 30)  │               
│  • Calculate margin, targets  │               
└───────────────────────────────┘               
                │                               
                ▼                               
┌───────────────────────────────┐               
│  STEP 7: TREASURY VALIDATION  │               
│  • Circuit breaker check      │               
│  • Position count (max 3)     │               
│  • Margin check (max 20%)     │               
│  • Greeks limits              │               
│  • v2.5: Kelly sizing         │               
│  • v2.5: Psych caps           │               
│  • v2.5: Warning state sizing │               
└───────────────────────────────┘               
                │                               
        ┌───────┴───────┐                       
        │ Approved?     │                       
        └───────┬───────┘                       
    YES ◄───────┴───────► NO (reject)           
        │                                       
        ▼                                       
┌───────────────────────────────┐               
│  STEP 8: EXECUTOR             │               
│  • Place orders via Kite      │               
│  • Monitor fills              │               
│  • Create Position object     │               
│  • Record in database         │               
└───────────────────────────────┘               
                │                               
                ▼                               
┌─────────────────────────────────────────────────────────────────┐
│  CIRCUIT BREAKER UPDATE                                         │
│  • Record trade results                                         │
│  • Check daily/weekly/monthly limits                           │
│  • v2.5: Monthly -8% → pause + Monk audit                      │
│  • v2.5: Chaos 2+ days → 48hr halt                             │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                    ┌───────────────────┐
                    │  ITERATION END    │
                    │  Wait for next    │
                    └───────────────────┘
```

### 7.2 Key Files Reference

| Step | Component | File |
|------|-----------|------|
| 1 | Sentinel | `app/services/agents/sentinel.py` |
| 2 | Treasury | `app/services/execution/treasury.py` |
| 3 | Executor | `app/services/execution/executor.py` |
| 4 | Constants | `app/config/constants.py` |
| 5 | StrategySelector | `app/services/strategies/strategy_selector.py` |
| 6 | Strategist | `app/services/strategies/strategist.py` |
| 7 | Treasury | `app/services/execution/treasury.py` |
| 8 | Executor | `app/services/execution/executor.py` |
| CB | CircuitBreaker | `app/services/execution/circuit_breaker.py` |

---

## 8. v2.5 Rulebook Updates

### 8.1 Summary of v2.5 Changes

| Reference | Feature | Description | File |
|-----------|---------|-------------|------|
| Ref J | Event Override | Allow entry during event blackout if DTE ≥ 10 | `strategy_selector.py` |
| Ref K | High-IV Boost | Boost targets to 1.8-2.2% when IV >50%ile | `strategy_selector.py` |
| Ref L | Sustained Trigger | Track consecutive chaos days | `sentinel.py` |
| Ref M | Skew Check | Favor RR when call IV > put IV + 5% | `strategy_selector.py` |
| Ref N | Veto/Warning | 2 days → veto short-vol, 1 day → warning | `sentinel.py`, `regime.py` |
| - | Kelly Sizing | Fractional Kelly (0.5-0.7x) for position sizing | `treasury.py` |
| - | Psych Caps | 1 lot if DD >-2% or sentiment <-0.3 | `treasury.py` |
| - | Max Margin | Reduced from 40% to 20% | `thresholds.py` |
| - | Monthly Brake | Tightened from -10% to -8% | `circuit_breaker.py` |
| - | Chaos Halt | 48hr flat after 2+ days DC abnormal | `circuit_breaker.py` |
| - | BBW Exit | Exit immediately if BBW >1.8x and profitable | `position.py` |
| - | Post-Adj Tighten | 75% tighter stops after adjustment | `position.py` |
| - | Entry Window | Narrowed to 9:30-11:00 IST | `constants.py` |
| - | IC Delta | Changed from 25 to 30 | `thresholds.py` |

### 8.2 Configuration Parameters

**File**: `app/config/thresholds.py`

```python
# v2.5 Risk Limits
MAX_MARGIN_PCT = 0.20              # 20% max margin (was 40%)
IC_SHORT_DELTA = 30                # Delta 30 for IC (was 25)
MAX_MONTHLY_LOSS = 0.08            # -8% monthly brake (was -10%)

# v2.5 Sustained Trigger
SUSTAINED_TRIGGER_DAYS_VETO = 2    # Days for short-vol veto
SUSTAINED_TRIGGER_DAYS_WARNING = 1 # Days for warning state

# v2.5 Event Override
MIN_DTE_EVENT_OVERRIDE = 10        # Min DTE to override event blackout

# v2.5 High-IV Boost
HIGH_IV_BOOST_THRESHOLD = 50       # IV percentile threshold
HIGH_IV_TARGET_MIN = 0.018         # 1.8% target
HIGH_IV_TARGET_MAX = 0.022         # 2.2% target
HIGH_IV_ADJUST_THRESHOLD = -0.003  # -0.3% adjustment threshold

# v2.5 Skew Check
SKEW_THRESHOLD = 0.05              # 5% call/put IV difference

# v2.5 Kelly Sizing
KELLY_FRACTION_MIN = 0.5           # Minimum Kelly fraction
KELLY_FRACTION_MAX = 0.7           # Maximum Kelly fraction

# v2.5 Psych Caps
PSYCH_DRAWDOWN_CAP = -0.02         # -2% drawdown cap
PSYCH_SENTIMENT_CAP = -0.3         # Sentiment threshold

# v2.5 Trailing
TRAILING_BBW_EXIT_THRESHOLD = 1.8  # BBW ratio for immediate exit
TRAILING_BBW_LOCK_THRESHOLD = 1.5  # BBW ratio for profit lock
POST_ADJUSTMENT_TIGHTEN = 0.75     # 75% tighter after adjustment

# v2.5 Circuit Breaker
CHAOS_FLAT_HOURS = 48              # Hours flat after chaos
```

**File**: `app/config/constants.py`

```python
# v2.5 Entry Window (IST)
ENTRY_WINDOW_START_HOUR = 9
ENTRY_WINDOW_START_MINUTE = 30
ENTRY_WINDOW_END_HOUR = 11
ENTRY_WINDOW_END_MINUTE = 0
```

---

## 9. Backtesting Architecture

### 9.1 Unified Backtest Architecture (v2.5)

The backtesting system uses the **same `TradingEngine`** as live trading, ensuring identical decision-making logic.

**Key Components**:
- `TradingEngine`: Shared core logic (same as live)
- `HistoricalDataClient`: KiteClient-compatible interface for historical data
- `OptionsSimulator`: Simulates option pricing and Greeks

**File**: `scripts/run_backtest.py`

```python
def run_backtest(start_date, end_date, initial_capital):
    # Initialize HistoricalDataClient (KiteClient-compatible)
    historical_client = HistoricalDataClient(
        ohlcv_data=load_ohlcv_data(start_date, end_date),
        initial_balance=initial_capital
    )
    
    # Initialize agents with historical client
    sentinel = Sentinel(historical_client, config)
    strategist = Strategist(historical_client, config)
    treasury = Treasury(historical_client, config, state_manager)
    executor = Executor(historical_client, config)
    
    # Create TradingEngine (SAME as live trading)
    trading_engine = TradingEngine(
        sentinel=sentinel,
        strategist=strategist,
        treasury=treasury,
        executor=executor,
        state_manager=state_manager,
        kite=historical_client
    )
    
    # Iterate through each trading day
    for date in trading_days:
        historical_client.set_current_date(date)
        result = trading_engine.run_iteration(NIFTY_TOKEN)
        # Collect results...
    
    return calculate_metrics(trades, equity_curve)
```

**File**: `app/services/backtesting/historical_data_client.py`

```python
class HistoricalDataClient:
    """
    KiteClient-compatible interface for backtesting.
    Simulates all KiteClient methods using historical data.
    """
    
    def fetch_historical_data(self, token, from_date, to_date, interval):
        # Return historical OHLCV up to current simulation date
        
    def get_ltp(self, tokens):
        # Return prices at current simulation timestamp
        
    def get_option_chain(self, symbol, expiry):
        # Use OptionsSimulator to generate option chain
        
    def place_order(self, order):
        # Simulate order fill with slippage
        # Update paper positions and balance
        
    def get_positions(self):
        # Return simulated paper positions
```

### 9.2 Legacy Backtest Engine

```python
class BacktestEngine:
    def run(self, ruleset: Dict, data: pd.DataFrame) -> List[Trade]:
        """
        1. Initialize virtual account
        2. For each timestamp:
           a. Calculate indicators
           b. Detect regime
           c. Check for exits on open positions
           d. Generate signals
           e. Validate against risk limits
           f. Execute virtual trades
        3. Return trade list
        """
        
    def _simulate_fill(self, order: Order, data: pd.DataFrame) -> float:
        """Simulate fill with slippage (0.1-0.5%)."""
        
    def _calculate_costs(self, trade: Trade) -> float:
        """Brokerage (0.03%) + STT + other charges."""
```

### 7.2 Historical Data Loader

```python
class DataLoader:
    def load_from_kite(self, token: int, from_date: date, to_date: date) -> pd.DataFrame:
        """Fetch from KiteConnect API."""
        
    def load_from_cache(self, token: int, interval: str) -> pd.DataFrame:
        """Load from local CSV cache."""
        
    def load_option_chain_historical(self, symbol: str, date: date) -> pd.DataFrame:
        """Load historical option chain (if available)."""
```

### 7.3 Performance Metrics

```python
def calculate_metrics(trades: List[Trade]) -> Dict:
    return {
        'total_return': sum(t.pnl for t in trades),
        'sharpe_ratio': calculate_sharpe(trades),
        'max_drawdown': calculate_max_drawdown(trades),
        'win_rate': len([t for t in trades if t.pnl > 0]) / len(trades),
        'profit_factor': sum(t.pnl for t in trades if t.pnl > 0) / 
                         abs(sum(t.pnl for t in trades if t.pnl < 0)),
        'avg_win': np.mean([t.pnl for t in trades if t.pnl > 0]),
        'avg_loss': np.mean([t.pnl for t in trades if t.pnl < 0]),
        'expectancy': calculate_expectancy(trades)
    }
```

---

## 8. Deployment

### 8.1 Dependencies (`requirements.txt`)

```
kiteconnect>=4.0.0
pandas>=1.5.0
numpy>=1.23.0
ta-lib>=0.4.25
scikit-learn>=1.2.0
pydantic>=1.10.0
python-dotenv>=1.0.0
loguru>=0.7.0
sqlalchemy>=2.0.0
aiosqlite>=0.19.0
pytest>=7.0.0
```

### 8.2 Environment Variables (`.env.example`)

```
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
KITE_ACCESS_TOKEN=your_access_token

# Optional
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 8.3 Running the System

```bash
# Install dependencies
pip install -r requirements.txt

# Run backtests first
python -m backtesting.engine --strategy iron_condor --data data/nifty_2024.csv

# Run in paper trading mode
python main.py --mode paper

# Run live (after validation)
python main.py --mode live
```

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Feb 2026 | System | Initial draft |
| 2.5 | Feb 2026 | System | v2.5 rulebook updates: sustained triggers, Kelly sizing, psych caps, BBW trailing, chaos halt |

---
*End of SDD Document*
