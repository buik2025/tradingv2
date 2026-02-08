# Trading System v2.0

Multi-agent algorithmic trading system for Indian markets (NSE/MCX) using KiteConnect API.

## Overview

This system implements a rule-based, multi-agent architecture for automated options trading with strict risk management and regime detection.

### Core Agents

| Agent | Responsibility |
|-------|---------------|
| **Sentinel** | Market regime detection (RANGE_BOUND, MEAN_REVERSION, TREND, CHAOS) |
| **Strategist** | Signal generation (Iron Condor, Jade Lizard, Risk Reversal) |
| **Treasury** | Risk management (margin, position limits, circuit breakers) |
| **Executor** | Order placement and position monitoring |
| **Monk** | Backtesting, ML training, strategy validation |

### Key Features

- **Regime-based trading**: Only trades in appropriate market conditions
- **Defined-risk structures**: Iron Condors, Jade Lizards, Risk Reversals
- **Strict risk management**: 40% max margin, 1% max loss per trade, circuit breakers
- **Drawdown response**: Automatic position sizing reduction
- **Backtesting**: Full historical validation before live deployment
- **ML integration**: Optional regime classification enhancement

## Installation

```bash
# Clone repository
cd tradingv2

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env with your KiteConnect credentials
```

## Configuration

Edit `.env` file with your credentials:

```
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
KITE_ACCESS_TOKEN=your_access_token
```

## Usage

### Paper Trading (Default)

```bash
python main.py --mode paper
```

### Backtesting

```bash
python main.py --mode backtest --strategy iron_condor --data data/nifty_2024.csv
```

### Live Trading

⚠️ **Only run live after thorough backtesting and paper trading validation**

```bash
python main.py --mode live
```

### Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--mode` | paper | Trading mode: paper, live, backtest |
| `--strategy` | iron_condor | Strategy for backtest |
| `--data` | data/nifty_2024.csv | Data file for backtest |
| `--interval` | 300 | Loop interval in seconds |
| `--log-level` | INFO | Log level |

## Project Structure

```
trading_v2/
├── config/           # Configuration and thresholds
├── core/             # KiteClient, DataCache, Logger
├── agents/           # Sentinel, Strategist, Treasury, Executor, Monk
├── models/           # Pydantic data models
├── strategies/       # Strategy implementations
├── indicators/       # Technical indicators
├── backtesting/      # Backtest engine
├── ml/               # ML regime classifier
├── database/         # SQLAlchemy models and repository
├── tests/            # Unit tests
├── data/             # Historical data and ML models
├── logs/             # Log files
├── state/            # State persistence
└── main.py           # Entry point
```

## Risk Management

### Position Limits
- Max 3 concurrent positions
- Max 40% margin utilization
- Max 1% loss per trade

### Circuit Breakers
- 3% daily loss → 1 flat day
- 5% weekly loss → 3 flat days
- 10% monthly loss → 5 flat days

### Drawdown Response
| Drawdown | Position Size |
|----------|---------------|
| < 5% | 100% |
| 5-10% | 50% |
| 10-15% | 25% |
| > 15% | STOP |

## Regime Detection

| Regime | Conditions | Allowed Strategies |
|--------|------------|-------------------|
| RANGE_BOUND | ADX < 12, IV < 35%, RSI 40-60 | Iron Condor, Jade Lizard |
| MEAN_REVERSION | ADX 12-22, RSI < 30 or > 70 | Risk Reversal, Intraday Fade |
| TREND | ADX > 22 | None (wait) |
| CHAOS | IV > 75%, events, correlation spike | None (flatten) |

## Testing

### Phase 1 Test Suite (100 Tests - All Passing ✓)

Phase 1 comprehensive test suite validates:
- **Dynamic Exit Targeting** (Section 4 of v2_rulebook)
- **Trailing Profit Execution** (Section 11 of v2_rulebook)
- **Structure Integration** (6 strategies integrated)
- **Regime-based routing** (5 regimes across 4 services)

#### Quick Start: Run All Tests with Report

```bash
# Run tests with comprehensive reporting
python3 backend/tests/run_tests_with_report.py

# Output includes:
#   - 100 test execution results
#   - Phase 1 implementation validation
#   - Coverage by category
#   - Recommendations for Phase 2
#   - Saved to: TEST_REPORT.md
```

#### Standard pytest Commands

```bash
# Run all tests
cd backend && pytest tests/ -v

# Run specific test file
pytest tests/test_models.py -v

# Run specific test class
pytest tests/test_models.py::TestTradeProposalModel -v

# Run specific test
pytest tests/test_models.py::TestTradeProposalModel::test_trade_proposal_creation -v

# Run with coverage report
pytest tests/ --cov=app --cov-report=html

# Run with detailed output
pytest tests/ -vv --tb=long

# Run in quiet mode
pytest tests/ -q
```

#### Test Files Overview

| File | Tests | Purpose |
|------|-------|---------|
| `conftest.py` | 7 fixtures | Shared test data (regimes, proposals, positions) |
| `test_models.py` | 25 tests | TradeProposal, TradeLeg, Position models with Phase 1 features |
| `test_strategist.py` | 20 tests | Strategist service (structure selection, dynamic targets) |
| `test_executor.py` | 10 tests | Executor service (signal processing, position management) |
| `test_full_pipeline.py` | 25 tests | End-to-end integration (Sentinel→Strategist→Treasury→Executor) |
| `test_greeks.py` | 15 tests | Greeks calculation (existing, preserved from v1) |

#### Phase 1 Features Tested

**Dynamic Exit Targeting**
```python
# TradeProposal now includes:
proposal.exit_target_low = 0.014      # 1.4% for SHORT_VOL
proposal.exit_target_high = 0.018     # 1.8% for SHORT_VOL
proposal.exit_margin_type = "margin"
low, high = proposal.get_dynamic_target(entry_margin=10000)
```

**Trailing Profit Execution**
```python
# Position now includes:
position.trailing_enabled = True
position.trailing_mode = "atr"        # or "bbw"
position.trailing_profit_threshold = 0.5  # 50% of target
should_exit = position.update_trailing_stop(current_price, atr=150)
```

**Regime-based Structure Selection**
```
RANGE_BOUND     → Strangle → Butterfly → Iron Condor
MEAN_REVERSION  → Risk Reversal → BWB → Strangle
TREND           → Risk Reversal → Jade Lizard
CHAOS           → No trades
CAUTION         → Jade Lizard only
```

## Testing

Comprehensive test suite with **146 tests** validating Phase 1 and Phase 2 implementations:
- **Phase 1** (100 tests): Dynamic exit targeting, trailing profit, structure integration
- **Phase 2** (46 tests): Circuit breakers, consecutive loss management, Greek hedging

### Quick Start

Generate and view detailed test report:

```bash
# Create detailed test report (saves to test_reports/)
python3 backend/tests/generate_test_report.py

# View latest report
cat test_reports/test_report_latest.md

# View timestamped reports
ls test_reports/test_report_*.md
```

### Run Tests

```bash
# From backend directory
cd backend

# Run all tests with detailed output
python3 -m pytest tests/ -v

# Run with minimal output
python3 -m pytest tests/ -q

# Run specific test file
python3 -m pytest tests/test_phase2.py -v

# Run with coverage report
python3 -m pytest tests/ --cov=app --cov-report=html
```

### Test Reports

Test reports are automatically generated and saved to `test_reports/`:

- **`test_report_latest.md`** - Most recent test execution  
- **`test_report_YYYYMMDD_HHMMSS.md`** - Timestamped historical reports

Each report includes:
- ✅ Summary statistics (tests passed, duration, pass rate)
- ✅ Detailed test breakdown by category
- ✅ Phase 1 and Phase 2 features validated
- ✅ Implementation guidance and next steps

### Test Coverage by Phase

#### Phase 1 Tests (100 tests)

**Models (25 tests)** - TradeProposal, Position, TradeLeg
- Dynamic exit targets (1.4-1.8% SHORT_VOL, 1.4-2.2% DIRECTIONAL)
- Trailing profit activation and updates
- Greeks calculation and aggregation

**Services (30 tests)** - Strategist, Executor
- Signal generation with regime-based routing
- Structure selection (6 strategies, 5 regimes)
- Order execution and position monitoring
- Dynamic target handling

**Integration (25 tests)** - End-to-end pipeline
- Sentinel→Strategist→Treasury→Executor flows
- Regime transitions and dynamic routing
- Position lifecycle from creation to exit
- Multi-position management and error recovery

**Greeks (15 tests)** - Utilities
- ATM/OTM/ITM Greeks calculations
- Fallback and validation logic

#### Phase 2 Tests (46 tests)

**Circuit Breakers (13 tests)**
- Daily loss limit (-1.5% equity) with 1-day halt
- Weekly loss limit (-4% equity) with 3-day halt
- Monthly loss limit (-10% equity) with 7-day halt
- Consecutive loss tracking (3 losers → 50% size reduction)
- ML-based preemptive halt (loss prob > 0.6)

**Consecutive Loss Management (5 tests)**
- Consecutive loss counter tracking
- Size reduction multiplier (0.5× when active)
- Size reduction expiration (1 day)

**Greek Hedging (28 tests)**
- **Delta hedging**: ±12% threshold detection and rebalancing
- **Vega hedging**: ±35% threshold detection and rebalancing
- **Gamma hedging**: -0.15% threshold for negative gamma risk
- **Short Greek caps**: Short vega (-60%), short gamma (-0.15%)
- **Rebalancing logic**: Automatic detection and execution

### Test Organization

```
backend/tests/
├── conftest.py                    # Pytest fixtures (Phase 1)
├── test_models.py                 # 25 tests - Models
├── test_strategist.py             # 20 tests - Signal generation
├── test_executor.py               # 10 tests - Order execution
├── test_full_pipeline.py          # 25 tests - End-to-end flows
├── test_greeks.py                 # 15 tests - Greeks calculations
├── test_phase2.py                 # 46 tests - Circuit breakers & hedging
└── generate_test_report.py        # Report generator (executable)
```

### Test Metrics

| Phase | Tests | Pass Rate | Duration |
|-------|-------|-----------|----------|
| **Phase 1** | 100 | 100% ✅ | ~1.0s |
| **Phase 2** | 46 | 100% ✅ | ~0.9s |
| **Total** | 146 | 100% ✅ | ~1.9s |

### Advanced Testing

```bash
# Run tests matching pattern
python3 -m pytest tests/ -k "circuit" -v

# Generate coverage report (opens in browser)
python3 -m pytest tests/ --cov=app --cov-report=html
open htmlcov/index.html  # macOS

# Run with detailed failure info
python3 -m pytest tests/ -vv --tb=long

# Stop on first failure
python3 -m pytest tests/ -x

# Drop into debugger on failure
python3 -m pytest tests/ --pdb
```

### Continuous Integration

To run tests in CI/CD pipeline:

```bash
#!/bin/bash
cd backend
python3 -m pytest tests/ -q

# Check exit code
if [ $? -eq 0 ]; then
    echo "✓ All 146 tests passed"
    python3 tests/generate_test_report.py
else
    echo "✗ Tests failed"
    exit 1
fi
```

### Troubleshooting

```bash
# Tests fail with import errors - install dependencies
cd backend && pip install -r requirements.txt

# Check Python path
export PYTHONPATH=/Users/vwe/Work/experiments/tradingv2:$PYTHONPATH

# List available fixtures
python3 -m pytest tests/ --fixtures

# Run tests with more verbose output
python3 -m pytest tests/ -vv --tb=short
```

## Documentation

- [Software Requirements Specification (SRS)](docs/SRS.md)
- [Software Design Document (SDD)](docs/SDD.md)

## License

Private - All rights reserved.

## Disclaimer

This software is for educational purposes only. Trading involves substantial risk of loss. Past performance is not indicative of future results. Always test thoroughly before live deployment.
