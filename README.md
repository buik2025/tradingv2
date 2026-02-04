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

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_sentinel.py -v

# Run with coverage
pytest --cov=. tests/
```

## Documentation

- [Software Requirements Specification (SRS)](docs/SRS.md)
- [Software Design Document (SDD)](docs/SDD.md)

## License

Private - All rights reserved.

## Disclaimer

This software is for educational purposes only. Trading involves substantial risk of loss. Past performance is not indicative of future results. Always test thoroughly before live deployment.
