# Strategy-Based Position Tracking

## Overview

The Trading System v2.0 provides a **flexible, user-defined strategy framework** for tracking positions and measuring performance. Unlike traditional systems with fixed strategy types, this platform allows:

- **Dynamic strategy creation** from any combination of positions
- **Runtime adjustments** to group/regroup positions
- **Portfolio-level P&L tracking** for decision making
- **Custom strategy naming** and categorization

This document describes the architecture for strategy-based position tracking and performance measurement.

## Critical Architecture Decisions

### Backend is Source of Truth

**All P&L calculations happen in the backend.** The frontend only displays data.

This is essential because:
1. Multiple strategies may have positions in the same instrument
2. Kite aggregates all positions for an instrument into one (undesired for strategy tracking)
3. Correct P&L calculation requires lot sizes, multipliers from instrument master

### Trade-Based vs Position-Based Tracking

| Aspect | Kite Positions | Strategy Trades |
|--------|---------------|-----------------|
| Granularity | Aggregated by instrument | Individual trades |
| Same instrument | Single combined position | Separate per strategy |
| P&L source | Kite's calculation | Backend calculation |
| Use case | Positions tab (broker view) | Strategies tab (strategy view) |

### P&L Calculation

```python
# For all instrument types (EQ, FUT, CE, PE):
# Kite returns quantity in actual units (not lots)
P&L = (last_price - average_price) * quantity

# P&L % calculation:
investment = average_price * abs(quantity)
pnl_pct = (pnl / investment) * 100
```

The `InstrumentCache` stores lot sizes and multipliers from Kite's instrument master for reference.

## Core Philosophy

### Flexibility First

This platform does NOT enforce fixed strategy types. Instead:

1. **A Strategy** = Any user-defined combination of positions that together form a trading thesis
2. **A Portfolio** = A collection of strategies with aggregate P&L tracking
3. **Positions** = Individual legs that can be freely combined into strategies

### Key Principles

- Orders are NOT strictly tied to predefined strategy templates
- Users can combine existing positions into custom strategies at any time
- Strategy groupings can be adjusted based on market conditions
- Performance is tracked at both strategy and portfolio levels
- Decisions are made based on portfolio-level P&L

## Hierarchy

```
Portfolio
├── Total P&L (realized + unrealized)
├── Risk metrics (margin, drawdown)
└── Strategies[]
    ├── Strategy A (user-defined name)
    │   ├── id: unique identifier
    │   ├── name: "NIFTY Feb Iron Condor" (user-defined)
    │   ├── description: optional notes
    │   ├── positions: List[Position]
    │   │   ├── Position 1: NIFTY 23500 PE SELL
    │   │   ├── Position 2: NIFTY 23400 PE BUY
    │   │   ├── Position 3: NIFTY 24000 CE SELL
    │   │   └── Position 4: NIFTY 24100 CE BUY
    │   ├── entry_value: net credit/debit at creation
    │   ├── current_pnl: aggregate P&L
    │   └── status: OPEN | CLOSED | PARTIAL
    │
    ├── Strategy B (another grouping)
    │   └── ...
    │
    └── Ungrouped Positions (not yet assigned to a strategy)
        ├── Position X
        └── Position Y
```

## Strategy Types (Optional Labels)

While the system is flexible, users may optionally label strategies with common patterns for analysis:

| Label | Description | Typical Structure |
|-------|-------------|-------------------|
| `IRON_CONDOR` | Neutral, range-bound | 4 legs |
| `JADE_LIZARD` | Bullish bias | 3 legs |
| `BUTTERFLY` | Low-cost neutral | 3 legs |
| `SPREAD` | Directional | 2 legs |
| `CUSTOM` | User-defined | Any |
| `ADJUSTMENT` | Runtime modification | Variable |

**Note**: These are labels for categorization only, not enforced structures.

## Data Model

### Database Schema (PostgreSQL)

#### `portfolios` Table
Top-level container for strategies.

```sql
CREATE TABLE portfolios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    
    -- P&L tracking
    realized_pnl DECIMAL(14, 2) DEFAULT 0,
    unrealized_pnl DECIMAL(14, 2) DEFAULT 0,
    
    -- Risk metrics
    total_margin DECIMAL(14, 2) DEFAULT 0,
    high_watermark DECIMAL(14, 2) DEFAULT 0,
    max_drawdown DECIMAL(14, 2) DEFAULT 0,
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### `strategies` Table
User-defined strategy groupings. A strategy is a flexible combination of positions.

```sql
CREATE TABLE strategies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID REFERENCES portfolios(id),
    
    -- User-defined naming
    name VARCHAR(200) NOT NULL,
    description TEXT,
    label VARCHAR(50),  -- Optional: IRON_CONDOR, SPREAD, CUSTOM, etc.
    
    -- Underlying (optional - can span multiple underlyings)
    primary_instrument VARCHAR(50),
    
    -- P&L tracking
    entry_value DECIMAL(14, 2) DEFAULT 0,  -- Net value at strategy creation
    current_value DECIMAL(14, 2) DEFAULT 0,
    realized_pnl DECIMAL(14, 2) DEFAULT 0,
    unrealized_pnl DECIMAL(14, 2) DEFAULT 0,
    
    -- Risk parameters (optional)
    target_pnl DECIMAL(14, 2),
    stop_loss DECIMAL(14, 2),
    
    -- Greeks (aggregate, calculated from positions)
    delta DECIMAL(10, 4) DEFAULT 0,
    gamma DECIMAL(10, 6) DEFAULT 0,
    theta DECIMAL(10, 4) DEFAULT 0,
    vega DECIMAL(10, 4) DEFAULT 0,
    
    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',  -- OPEN, CLOSED, PARTIAL
    source VARCHAR(10) DEFAULT 'PAPER',  -- PAPER or LIVE
    
    -- Context
    notes TEXT,
    tags VARCHAR(200)[],  -- Array of user-defined tags
    
    -- Exit info
    closed_at TIMESTAMPTZ,
    close_reason VARCHAR(100),
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### `positions` Table
Individual positions (broker-level). Can belong to zero or more strategies.

```sql
CREATE TABLE positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Broker info
    tradingsymbol VARCHAR(100) NOT NULL,
    instrument_token INTEGER NOT NULL,
    exchange VARCHAR(10) DEFAULT 'NFO',
    
    -- Position details
    quantity INTEGER NOT NULL,
    average_price DECIMAL(12, 2) NOT NULL,
    last_price DECIMAL(12, 2),
    pnl DECIMAL(14, 2) DEFAULT 0,
    
    -- Option details (if applicable)
    strike DECIMAL(12, 2),
    expiry DATE,
    option_type VARCHAR(2),  -- CE or PE
    underlying VARCHAR(50),
    
    -- Transaction
    transaction_type VARCHAR(4),  -- BUY or SELL
    product VARCHAR(10),  -- NRML, MIS, etc.
    
    -- Source
    source VARCHAR(10) DEFAULT 'LIVE',  -- LIVE or PAPER
    broker_order_id VARCHAR(50),
    
    -- Timestamps
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### `strategy_positions` Table
Many-to-many relationship between strategies and positions.

```sql
CREATE TABLE strategy_positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    position_id UUID NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    
    -- When this position was added to the strategy
    added_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Optional: quantity allocated to this strategy (for partial allocation)
    allocated_quantity INTEGER,
    
    UNIQUE(strategy_id, position_id)
);
```

#### `portfolio_snapshots` Table
Daily snapshots for portfolio-level tracking.

```sql
CREATE TABLE portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    portfolio_id UUID REFERENCES portfolios(id),
    date DATE NOT NULL,
    
    -- P&L
    realized_pnl DECIMAL(14, 2) DEFAULT 0,
    unrealized_pnl DECIMAL(14, 2) DEFAULT 0,
    total_pnl DECIMAL(14, 2) DEFAULT 0,
    
    -- Metrics
    strategy_count INTEGER DEFAULT 0,
    position_count INTEGER DEFAULT 0,
    
    -- Risk
    margin_used DECIMAL(14, 2) DEFAULT 0,
    high_watermark DECIMAL(14, 2) DEFAULT 0,
    drawdown DECIMAL(14, 2) DEFAULT 0,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(portfolio_id, date)
);
```

## UI Views

The frontend has **three separate pages** for positions, strategies, and portfolios, plus a **Dashboard** for overview. Each page includes:
- **Account Summary Bar**: Total margin, used margin, available margin, cash available
- **Real-time WebSocket updates**: Live P&L updates from Kite ticker
- **Margin tracking**: Per-position, per-strategy, and per-portfolio margin data

### Header Component
The header is displayed on all pages and includes:

| Component | Description |
|-----------|-------------|
| **Live Indices** | Real-time quotes for configurable indices (NIFTY 50, SENSEX, BANK NIFTY, etc.) |
| **Market Status** | Shows "CLOSED" badge when market is not trading (based on `last_trade_time`) |
| **Trading Mode** | PAPER or LIVE badge |
| **Trading Status** | RUNNING or STOPPED badge |
| **Index Settings** | Configure which indices to display |
| **User Menu** | Logout option |

**Indices Configuration**:
- Users can add/remove indices from the header display
- Available indices: NIFTY 50, SENSEX, BANK NIFTY, NIFTY FIN, NIFTY IT, MIDCAP 50, INDIA VIX
- Selection persisted in localStorage
- Updates every 2 seconds

### Dashboard Page (`/dashboard`)
Overview of trading activity with key metrics.

| Metric | Description |
|--------|-------------|
| **Daily P&L** | Total unrealized P&L from all positions (real-time via WebSocket) |
| **Open Positions** | Count of active positions |
| **Win Rate** | Weighted average win rate across all strategy types |
| **Margin Used** | Current margin utilization percentage |

Also displays:
- **Market Regime Card**: Current regime (Trending/Ranging/Chaos), confidence, safety status, ADX/RSI/IV metrics
- **Quick Actions**: Start/Stop trading, Flatten all positions

### Account Summary Component
Displayed at the top of each page:

| Total Margin | Used Margin | Available Margin | Cash Available |
|--------------|-------------|------------------|----------------|
| ₹25,00,000 | ₹8,50,000 (34%) | ₹16,50,000 | ₹12,00,000 |

### Positions Page (`/dashboard/positions`)
Shows all individual positions with margin tracking.

| Symbol | Exchange | Qty | Avg Price | LTP | P&L | P&L % | Margin | P&L/Margin |
|--------|----------|-----|-----------|-----|-----|-------|--------|------------|
| NIFTY 23500 PE | NFO | -260 | ₹146 | ₹90 | ₹14,615 | +38.5% | ₹85,000 (10%) | +17.2% |
| NIFTY 23400 CE | NFO | 260 | ₹156 | ₹28 | -₹33,235 | -82.1% | ₹72,000 (8.5%) | -46.2% |
| GOLDM26MARFUT | MCX | 2 | ₹1,73,036 | ₹1,50,600 | -₹4,48,720 | -13.0% | ₹35,000 (4.1%) | -1282% |

**Column Layout**:
- **P&L %**: Percentage change from entry price (colored green/red)
- **Margin**: Shows margin amount with margin % of total in parentheses below

**Features**:
- Select positions to create strategies
- Sort by any column (including P&L %)
- Filter by exchange
- Search by symbol
- Real-time P&L updates via WebSocket

### Strategies Page (`/dashboard/strategies`)
Shows user-defined strategies with aggregated margin and P&L.

**Strategy Header Metrics**: Unrealized P&L → P&L % → Margin (with %) → P&L/Margin

**Expanded Trades Table**:
| Symbol | Exchange | Qty | Entry | LTP | P&L | P&L % | Margin | P&L/Margin |
|--------|----------|-----|-------|-----|-----|-------|--------|------------|
| NIFTY 23500 PE | NFO | -260 | ₹146 | ₹90 | ₹14,615 | +17.2% | ₹85,000 (10%) | +17.2% |

**Column Layout**:
- **P&L %**: Percentage P&L on margin (colored green/red)
- **Margin**: Shows margin amount with margin % of total in smaller text below

**Features**:
- Expandable to show individual trades with full details
- Close strategy button
- Margin rollup from positions (sum of trade margins)
- Real-time P&L updates via WebSocket
- Click strategy from Portfolios page to auto-expand and highlight

### Portfolios Page (`/dashboard/portfolios`)
Shows portfolios with strategy rollup.

**Portfolio Header Metrics**: Unrealized P&L → P&L % → Margin (with %) → P&L/Margin

**Expanded Strategies Table**:
| Strategy | Trades | Unrealized | P&L % | Margin | P&L/Margin |
|----------|--------|------------|-------|--------|------------|
| NIFTY Range Forward | 2 | -₹13,250 | -8.4% | ₹1,57,000 (18%) | -8.4% |

**Column Layout**:
- **P&L %**: Percentage P&L on margin (colored green/red)
- **Margin**: Shows margin amount with margin % of total in smaller text below

**Features**:
- Create new portfolios
- Expandable to show strategies with click-through to Strategies page
- Margin rollup from strategies (sum of strategy margins)
- Real-time P&L updates via WebSocket
- Virtual "All Strategies" portfolio when no portfolios exist

## API Endpoints

### Account & Margins

#### GET `/api/v1/account/summary`
Returns account summary with margin data.

```json
{
  "total_margin": 2500000,
  "used_margin": 850000,
  "available_margin": 1650000,
  "cash_available": 1200000,
  "collateral": 300000,
  "intraday_payin": 0,
  "margin_utilization_pct": 34.0,
  "segments": {
    "equity": { "available": 1500000, "used": 750000, "cash": 1000000 },
    "commodity": { "available": 150000, "used": 100000, "cash": 200000 }
  }
}
```

### Positions

#### GET `/api/v1/positions`
Returns all positions from broker (synced).

#### GET `/api/v1/positions/with-margins`
Returns positions with margin data for each position.

```json
{
  "positions": [
    {
      "id": "12345678",
      "tradingsymbol": "NIFTY2621025500PE",
      "instrument_token": 12345678,
      "exchange": "NFO",
      "quantity": -260,
      "average_price": 146,
      "last_price": 90,
      "pnl": 14615,
      "pnl_pct": 38.49,
      "product": "NRML",
      "source": "LIVE",
      "margin_used": 85000,
      "margin_pct": 10.0,
      "pnl_on_margin_pct": 17.2
    }
  ],
  "account": {
    "total_margin": 2500000,
    "used_margin": 850000,
    "available_margin": 1650000,
    "margin_utilization_pct": 34.0
  },
  "total_position_margin": 750000
}
```

#### POST `/api/v1/positions/sync`
Sync positions from broker to database.

### Strategies

#### GET `/api/v1/strategies`
Returns all user-defined strategies.

#### POST `/api/v1/strategies`
Create a new strategy from selected positions.

```json
{
  "name": "Feb NIFTY Iron Condor",
  "label": "IRON_CONDOR",
  "position_ids": ["uuid1", "uuid2", "uuid3", "uuid4"],
  "portfolio_id": "portfolio-uuid",
  "notes": "Weekly expiry play"
}
```

#### PUT `/api/v1/strategies/{id}/positions`
Add or remove positions from a strategy.

```json
{
  "add": ["position-uuid-5"],
  "remove": ["position-uuid-2"]
}
```

#### POST `/api/v1/strategies/{id}/close`
Close a strategy and record realized P&L.

### Portfolios

#### GET `/api/v1/portfolios`
Returns all portfolios with aggregate metrics.

#### GET `/api/v1/portfolios/{id}/performance`
Returns historical performance for a portfolio.

```json
{
  "portfolio_id": "uuid",
  "period": {"from": "2026-01-01", "to": "2026-02-05"},
  "total_pnl": 45000,
  "realized_pnl": 30000,
  "unrealized_pnl": 15000,
  "win_rate": 0.68,
  "daily_snapshots": [...]
}
```

### GET `/api/v1/strategies/performance`
Returns historical performance by strategy type.

### Indices

#### POST `/api/v1/indices/quotes`
Returns live quotes for multiple indices with market status.

**Request**:
```json
{
  "symbols": ["NSE:NIFTY 50", "BSE:SENSEX", "NSE:NIFTY BANK"]
}
```

**Response**:
```json
{
  "quotes": [
    {
      "symbol": "NSE:NIFTY 50",
      "name": "NIFTY 50",
      "last_price": 23150.50,
      "change": -142.30,
      "change_pct": -0.61,
      "market_open": true,
      "last_trade_time": "2026-02-05T15:29:59"
    }
  ]
}
```

**Market Status Detection**:
- `market_open` is determined by checking if `last_trade_time` is within the last 5 minutes
- This avoids hardcoding market hours and works across all exchanges (NSE, BSE, MCX)
- Automatically handles holidays and special trading sessions

**Available Indices**:
| Symbol | Name |
|--------|------|
| `NSE:NIFTY 50` | NIFTY 50 |
| `BSE:SENSEX` | SENSEX |
| `NSE:NIFTY BANK` | BANK NIFTY |
| `NSE:NIFTY FIN SERVICE` | NIFTY FIN |
| `NSE:NIFTY IT` | NIFTY IT |
| `NSE:NIFTY MIDCAP 50` | MIDCAP 50 |
| `NSE:INDIA VIX` | INDIA VIX |

### Regime

#### GET `/api/v1/regime/current`
Returns current market regime from Sentinel service with detailed explanation.

```json
{
  "regime": "CHAOS",
  "confidence": 0.85,
  "is_safe": false,
  "metrics": {
    "adx": 24.5,
    "rsi": 38.3,
    "iv_percentile": 78,
    "realized_vol": 0.18,
    "atr": 125.5
  },
  "thresholds": {
    "adx_range_bound": 12,
    "adx_trend": 22,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "rsi_neutral_low": 40,
    "rsi_neutral_high": 60,
    "iv_high": 75,
    "correlation_chaos": 0.5
  },
  "explanation": {
    "steps": [
      {"step": 1, "check": "Event Calendar", "condition": "No major events within 7-day blackout", "result": "PASSED", "impact": "Continue to next check"},
      {"step": 2, "check": "IV Percentile", "condition": "IV 78.0% > 75% threshold", "result": "TRIGGERED", "impact": "Forces CHAOS if IV too high"},
      {"step": 3, "check": "Correlation Spike", "condition": "Max correlation 0.35 <= 0.5 threshold", "result": "PASSED", "impact": "Continue to next check"},
      {"step": 4, "check": "ADX (Trend Strength)", "condition": "ADX 24.5 >= 12 (Range-Bound threshold)", "result": "HIGH", "impact": "Suggests Trend"},
      {"step": 5, "check": "RSI (Momentum)", "condition": "RSI 38.3 in range [40-60] neutral, <30 oversold, >70 overbought", "result": "MODERATE", "impact": "Neutral impact"}
    ],
    "decision": "CHAOS triggered by: IV percentile too high: 78.0%",
    "summary": "Regime: CHAOS with 85% confidence"
  },
  "safety_reasons": ["CHAOS regime detected", "IV percentile too high: 78.0%"],
  "event_flag": false,
  "event_name": null,
  "correlations": {"BANKNIFTY": 0.35}
}
```

**Regime Classification Logic**:

The Sentinel agent classifies market regime using a priority-based rule system:

| Priority | Regime | Conditions |
|----------|--------|------------|
| 1 (Highest) | **CHAOS** | Event within 7-day blackout OR IV percentile > 75% OR Correlation spike > 0.5 |
| 2 | **RANGE_BOUND** | ADX < 12 AND IV < 75% AND RSI between 40-60 (neutral) |
| 3 | **MEAN_REVERSION** | ADX 12-22 AND (RSI < 30 oversold OR RSI > 70 overbought) |
| 4 | **TREND** | ADX > 22 (strong directional momentum) |

**Classification Steps (evaluated in order)**:

1. **Event Calendar Check**: Major events (RBI policy, budget, FOMC) trigger 7-day blackout → CHAOS
2. **IV Percentile Check**: IV > 75th percentile indicates high uncertainty → CHAOS  
3. **Correlation Spike Check**: Cross-asset correlation > 0.5 signals contagion → CHAOS
4. **ADX Analysis**: Measures trend strength (< 12 = range, 12-22 = moderate, > 22 = trend)
5. **RSI Analysis**: Momentum indicator (< 30 oversold, 40-60 neutral, > 70 overbought)

**Dashboard Display**:
- Expandable regime card shows step-by-step classification
- Each step shows: check name, condition evaluated, result (PASSED/TRIGGERED), impact
- Color-coded results: green (safe), red (triggered), yellow (moderate)
- Safety concerns listed when regime is UNSAFE

## Performance Tracking

Performance is tracked at **multiple levels**:

### Portfolio Level (Decision Making)
- **Total P&L**: Sum of all strategy P&Ls
- **Drawdown**: Current drawdown from high watermark
- **Margin Utilization**: % of available margin used
- **Risk Metrics**: Used for position sizing and circuit breakers

### Strategy Level (Analysis)
- **Unrealized P&L**: Current mark-to-market
- **Realized P&L**: Closed position profits/losses
- **Win Rate**: % of profitable strategies (when closed)

### Position Level (Execution)
- **Individual P&L**: Per-position tracking
- **Greeks**: Delta, gamma, theta, vega

### Metrics Tracked

- **Win Rate**: % of profitable strategies
- **Profit Factor**: Gross profit / Gross loss
- **Average Win/Loss**: Mean P&L for winning/losing strategies
- **Max Drawdown**: Largest peak-to-trough decline
- **Sharpe Ratio**: Risk-adjusted returns
- **Average Holding Period**: Days from entry to exit

## Custom Strategy Creation

### Runtime Adjustments

Users can combine existing positions into custom strategies at any time:

1. **Select positions** from the Positions view
2. **Create strategy** with custom name and optional label
3. **Assign to portfolio** for aggregate tracking
4. **Add notes/tags** for future reference

### Use Cases

- **Grouping related positions**: Combine legs of an iron condor
- **Tracking adjustments**: Group original position with adjustment trades
- **Research tracking**: Tag strategies for later analysis
- **Risk management**: Group positions by underlying for exposure tracking

### Future Phases

- **AI-assisted grouping**: Suggest strategy groupings based on position characteristics
- **Automatic labeling**: Detect common patterns (spreads, condors, etc.)
- **Strategy templates**: Save and reuse common structures
- **Performance attribution**: Analyze which strategy types perform best in which regimes

## Real-Time Updates (WebSocket)

### Architecture

```
Kite WebSocket Ticker (live prices from broker)
         ↓
Backend WebSocket Hub (/api/v1/ws/prices)
         ↓
    ┌────┴────────────┐
    ↓                 ↓
Positions      →   Strategies   →   Portfolios
(per-leg P&L)     (aggregate)      (aggregate)
         ↓
Frontend WebSocket Client
         ↓
UI Updates (real-time)
```

### WebSocket Endpoint

**URL**: `ws://localhost:8173/api/v1/ws/prices`

**Message Types**:

| Type | Direction | Description |
|------|-----------|-------------|
| `initial_state` | Server → Client | Full state on connect |
| `price_update` | Server → Client | Position/strategy/portfolio updates |
| `heartbeat` | Server → Client | Keep-alive (every 30s) |
| `ping` | Client → Server | Client heartbeat |
| `pong` | Server → Client | Response to ping |

**Initial State Payload**:
```json
{
  "type": "initial_state",
  "data": {
    "positions": [...],
    "strategies": [...],
    "portfolios": [...],
    "timestamp": "2026-02-05T11:52:00.000Z"
  }
}
```

**Price Update Payload**:
```json
{
  "type": "price_update",
  "data": {
    "positions": [{"id": "...", "last_price": 100.5, "pnl": 500}],
    "strategies": [{"id": "...", "unrealized_pnl": 1500}],
    "portfolios": [{"id": "...", "total_pnl": 5000}],
    "timestamp": "2026-02-05T11:52:01.000Z"
  }
}
```

### P&L Cascade

When a price update is received:

1. **Position P&L**: Calculated by `PnLCalculator` in backend
2. **Strategy P&L**: Sum of all linked trade P&Ls (from `StrategyTrade` table)
3. **Portfolio P&L**: Sum of all strategy P&Ls

Updates cascade automatically through the hierarchy.

### Key Services

| Service | Purpose |
|---------|---------|
| `InstrumentCache` | Caches lot sizes, multipliers from Kite instrument master |
| `PnLCalculator` | Calculates P&L for positions (backend source of truth) |
| `KiteTickerManager` | Single WebSocket connection to Kite for live prices |

### Fallback Behavior

- **WebSocket connected**: Real-time updates (sub-second)
- **WebSocket disconnected**: Polling fallback (3-second interval)

UI shows connection status badge: **Live** (green) or **Polling** (gray)

## Implementation Notes

### Syncing with Broker

1. Fetch positions from KiteConnect API
2. Upsert positions in database by `tradingsymbol`
3. Update `last_price` and `pnl` for each position
4. Recalculate aggregate P&L for strategies and portfolios
5. Store daily snapshots for historical tracking

### Paper vs Live

- **PAPER**: Simulated orders, real market data
- **LIVE**: Real orders placed with broker

Both are stored in the same tables with `source` field for differentiation.

### Position-Strategy Relationship

- A position can belong to **zero or one** strategy (ungrouped or grouped)
- A strategy can have **one or more** positions
- Positions can be **moved** between strategies
- Closing a strategy does NOT automatically close positions (user choice)

## Configuration

Database connection in `.env`:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trading
```

Or individual settings:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=trading
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
```
