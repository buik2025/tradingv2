"""Backtesting and simulation module

Backtesting uses the production Orchestrator with HistoricalDataClient
injecting historical data instead of live data.

Components:
- HistoricalDataClient: KiteClient replacement for historical data
- OptionsSimulator: Black-Scholes pricing for synthetic options
"""

from .options_simulator import OptionsSimulator
from .historical_data_client import HistoricalDataClient, load_ohlcv_data

__all__ = [
    "OptionsSimulator",
    "HistoricalDataClient",
    "load_ohlcv_data",
]
