# Unified Paper & Live Trading Design

## Overview

The trading platform uses a **unified execution flow** for both paper and live trading. The only distinction is at the order placement level - paper orders are simulated while live orders go to the broker API. All other components (regime detection, strategy generation, risk management, position persistence) work identically for both modes.

## Architecture

```
                    Orchestrator
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
        Sentinel    Strategist    Treasury
     (Regime Det)  (Proposals)   (Risk Mgmt)
            │            │            │
            └────────────┼────────────┘
                         ▼
                     Executor
                         │
                    ┌────▼────┐
                    │ _place_order │ ──► KiteClient.place_order()
                    └────┬────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
   paper_mode=True                  paper_mode=False
        │                                 │
   Simulate order                   Call broker API
   (LIMIT may stay OPEN)            (Real order_id)
        │                                 │
        └────────────────┬────────────────┘
                         │
                    ┌────▼────┐
                    │ _wait_for_fills │ ──► Polls order status
                    └────┬────┘
                         │
                    ┌────▼────┐
                    │ _persist_position │ ──► DB: Portfolio + Strategy + BrokerPositions
                    └─────────┘
```

## Mode Configuration

The `KiteClient` class supports three modes:

| Mode | `paper_mode` | `mock_mode` | Market Data | Orders |
|------|--------------|-------------|-------------|--------|
| **Live** | `False` | `False` | Real API | Real broker API |
| **Paper** | `True` | `False` | Real API | Simulated |
| **Mock** | `True`/`False` | `True` | Mocked | Simulated |

## Unified Components

### Shared Logic (Both Paper & Live)

| Component | Location | Description |
|-----------|----------|-------------|
| Regime Detection | `Sentinel` | VIX, ADX, correlation analysis |
| Strategy Generation | `Strategist` | Trade proposals based on regime |
| Risk Management | `Treasury` | Position sizing, margin checks |
| Order Ticket Creation | `Executor._create_order_ticket()` | Unified order creation |
| Position Creation | `Executor._create_position()` | Unified position tracking |
| Position Persistence | `Executor._persist_position()` | DB with Strategy/Portfolio |
| Slippage Tracking | `Executor._track_slippage()` | Monitors fill quality |
| Market Data | `KiteClient` | Quotes, LTP, historical data |
| Option Chain | `KiteClient.get_option_chain()` | Real API for both |
| Margin Calculation | `KiteClient.get_basket_margins()` | Real API for both |

### Mode-Specific Logic

| Aspect | Paper Mode | Live Mode |
|--------|------------|-----------|
| Order Placement | Simulated in `_paper_orders` dict | Real broker API call |
| Order Fill | Based on market price simulation | Real broker confirmation |
| Order ID Format | `PAPER_YYYYMMDDHHMMSS_SYMBOL` | Broker-assigned ID |
| Position Source | `source="PAPER"` | `source="LIVE"` |
| Portfolio | "Paper Trading" | "Live Trading" |
| Margin Tracking | Simulated via StateManager | Real from broker |

## Order Simulation (Paper Mode)

### Order Types

**MARKET Orders**
- Fill immediately at current market price
- Status: `COMPLETE`

**LIMIT Orders**
- Check if price is favorable for immediate fill:
  - BUY limit fills if `market_price <= limit_price`
  - SELL limit fills if `market_price >= limit_price`
- If favorable: Fill at limit price, status `COMPLETE`
- If not favorable: Stay `OPEN`, wait for price to reach limit

**SL/SL-M Orders**
- Stay `OPEN` until trigger price is hit:
  - SL BUY triggers if `market_price >= trigger_price`
  - SL SELL triggers if `market_price <= trigger_price`

### Order Polling

```python
# Poll all open paper orders and update status
kite.poll_paper_orders()

# Or poll specific order via get_order_history
history = kite.get_order_history(order_id)
```

The `_update_paper_order_status()` method checks current market prices and fills orders when conditions are met.

## Database Persistence

### Structure

When a trade is executed (paper or live), the following records are created:

```
Portfolio (Paper Trading / Live Trading)
  └── Strategy (JADE_LIZARD - NIFTY)
        └── StrategyPosition links
              ├── BrokerPosition (NIFTY26FEB24900PE, SHORT PUT)
              ├── BrokerPosition (NIFTY26FEB26200CE, SHORT CALL)
              └── BrokerPosition (NIFTY26FEB26300CE, LONG CALL)
```

### Tables

| Table | Purpose |
|-------|---------|
| `portfolios` | Groups strategies (Paper Trading, Live Trading) |
| `strategies` | Individual strategy instances with P&L tracking |
| `broker_positions` | Individual position legs with entry/exit data |
| `strategy_positions` | Many-to-many link between strategies and positions |

### Source Field

The `source` field in `strategies` and `broker_positions` distinguishes:
- `"PAPER"` - Simulated trades
- `"LIVE"` - Real broker trades

## API Endpoints

### Positions API

`GET /api/v1/portfolio/positions`

Returns both live positions (from Kite API) and paper positions (from database):

```json
{
  "positions": [
    {
      "tradingsymbol": "NIFTY26FEB24900PE",
      "quantity": -50,
      "source": "PAPER",
      "pnl": 1250.00,
      ...
    },
    {
      "tradingsymbol": "RELIANCE",
      "quantity": 100,
      "source": "LIVE",
      "pnl": 500.00,
      ...
    }
  ]
}
```

### Strategies API

`GET /api/v1/portfolio/strategies`

Returns all open strategies with their linked positions.

## Usage

### Starting Paper Trading

```python
from app.core.kite_client import KiteClient
from app.services.execution.executor import Executor

kite = KiteClient(
    api_key="your_api_key",
    access_token="your_access_token",
    paper_mode=True  # Enable paper trading
)

executor = Executor(kite, settings)
result = executor.process(approved_signal)
# Position persisted to DB with source="PAPER"
```

### Starting Live Trading

```python
kite = KiteClient(
    api_key="your_api_key",
    access_token="your_access_token",
    paper_mode=False  # Enable live trading
)

executor = Executor(kite, settings)
result = executor.process(approved_signal)
# Real order placed, position persisted with source="LIVE"
```

## Files Modified

| File | Changes |
|------|---------|
| `executor.py` | Unified `_persist_position()` for both modes |
| `kite_client.py` | Limit order simulation, `poll_paper_orders()` |
| `portfolio_service.py` | `_get_db_positions(source)` with source filter |

## Future Enhancements

1. **Partial Fills**: Simulate partial order fills for large orders
2. **Slippage Simulation**: Add configurable slippage for paper orders
3. **Order Book Simulation**: Simulate order book depth for realistic fills
4. **Position Reconciliation**: Sync DB positions with broker on startup
