# Software Design Document (SDD)
## Trading System v2.0 - Multi-Agent Algorithmic Trading Platform

**Version:** 1.0  
**Date:** February 2026  
**Status:** Draft  

---

## Table of Contents
1. [Introduction](#1-introduction)
2. [System Architecture](#2-system-architecture)
3. [Component Design](#3-component-design)
4. [Data Design](#4-data-design)
5. [Interface Design](#5-interface-design)
6. [Algorithm Design](#6-algorithm-design)
7. [Backtesting Architecture](#7-backtesting-architecture)

---

## 1. Introduction

### 1.1 Purpose
This document describes the software design for Trading System v2.0, detailing the architecture, components, data structures, algorithms, and interfaces.

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

### 5.2 Main Orchestrator (`main.py`)

```python
class Orchestrator:
    def __init__(self, config: Settings):
        self.kite = KiteClient(config.kite_api_key, config.kite_access_token)
        self.sentinel = Sentinel(self.kite, config)
        self.strategist = Strategist(self.kite, config)
        self.treasury = Treasury(self.kite, config)
        self.executor = Executor(self.kite, config)
        self.monk = Monk(self.kite, config)
        
    async def run(self):
        """Main loop: every 5 minutes during market hours."""
        while True:
            if not self._is_market_hours():
                await asyncio.sleep(60)
                continue
                
            # 1. Sentinel: Detect regime
            regime = self.sentinel.process(NIFTY_TOKEN)
            
            # 2. Monitor existing positions
            exits = self.executor.monitor_positions(positions)
            for exit in exits:
                self.executor.execute_exit(exit)
                
            # 3. Strategist: Generate signals
            proposals = self.strategist.process(regime)
            
            # 4. Treasury: Validate
            for proposal in proposals:
                approved, order = self.treasury.process(proposal, account)
                if approved:
                    # 5. Executor: Place order
                    self.executor.process(order)
                    
            await asyncio.sleep(300)  # 5 minutes
```

---

## 6. Algorithm Design

### 6.1 Regime Detection Algorithm

```
INPUT: 20 days of 5-min OHLCV data
OUTPUT: RegimeType, ML probability

1. Calculate indicators:
   - ADX(14) on 5-min bars
   - RSI(14) on 5-min bars
   - IV percentile (20-day rank of current IV)
   - RV/ATR ratio
   - Put/Call skew divergence

2. Check CHAOS conditions (highest priority):
   - IF event_flag = true: return CHAOS
   - IF IV percentile > 75%: return CHAOS
   - IF any correlation > |0.5|: return CHAOS

3. Run ML classifier:
   - Features: [IV_rank, ADX, RSI, skew, RV/ATR, OI_change, corr]
   - Get predicted regime and probability

4. Apply static rules:
   - IF ADX < 12 AND IV < 35% AND 40 <= RSI <= 60: RANGE_BOUND
   - ELIF 12 <= ADX <= 22: MEAN_REVERSION
   - ELSE: TREND

5. ML override:
   - IF ML probability > 0.7: use ML regime
   - ELSE: use static regime

RETURN (regime, ml_probability)
```

### 6.2 Iron Condor Entry Algorithm

```
INPUT: RegimePacket, OptionChain
OUTPUT: TradeProposal or None

1. Check entry conditions:
   - regime = RANGE_BOUND
   - IV percentile > 40%
   - No events in next 7 days
   - Previous day range < 1.2%
   - No gaps > 1.5% in past 3 days
   - Current time between 10 AM - 3 PM
   - Days to expiry: 10-12

2. Select strikes:
   - Find 25-delta call strike (short call)
   - Find 25-delta put strike (short put)
   - Long call = short call + 10 delta width
   - Long put = short put - 10 delta width

3. Verify liquidity:
   - Bid-ask spread <= ₹2 for all strikes
   - OI > 10,000 for all strikes

4. Calculate structure:
   - Net credit = (short_call + short_put) - (long_call + long_put)
   - Max loss = wing_width - net_credit
   - Max profit = net_credit
   - Target = 60% of max profit
   - Stop = 100% of credit (loss = credit)

5. Build proposal:
   - legs = [short_call, short_put, long_call, long_put]
   - Calculate Greeks (sum of all legs)

RETURN TradeProposal
```

### 6.3 Position Monitoring Algorithm

```
INPUT: List[Position]
OUTPUT: List[ExitAction]

FOR each position:
    1. Check EOD exit (intraday only):
       - IF is_intraday AND time >= 3:15 PM: EXIT

    2. Check profit target:
       - IF current_pnl >= target_pnl: EXIT

    3. Check stop loss:
       - IF current_pnl <= stop_loss: EXIT

    4. Check time-based exit (short vol):
       - IF strategy = SHORT_VOL AND days_to_expiry <= 5: EXIT

    5. Check regime override:
       - IF regime changed to CHAOS: EXIT

RETURN exit_actions
```

---

## 7. Backtesting Architecture

### 7.1 Backtest Engine

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

---
*End of SDD Document*
