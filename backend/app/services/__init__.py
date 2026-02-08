"""
Services module - Trading system core services organized by domain

Submodules:
  - strategies: Option trading strategies and signal generation
  - indicators: Technical analysis and market metrics
  - execution: Trade execution and risk management
  - backtesting: Simulation and performance analysis
  - agents: Autonomous trading agents
  - utilities: Helper services and utilities
"""

# Re-export for backward compatibility
from .strategies import (
    StrategySelector,
    Strategist,
    IronCondorStrategy,
    JadeLizardStrategy,
    IronButterflyStrategy,
    BrokenWingButterflyStrategy,
    RiskReversalStrategy,
    StrangleStrategy,
)

from .indicators import (
    calculate_adx,
    calculate_rsi,
    calculate_atr,
    calculate_realized_vol,
    calculate_iv_percentile,
    calculate_greeks,
    GreekCalculator,
    calculate_sharpe,
    calculate_sortino,
    RegimeClassifier,
)

from .execution import (
    Executor,
    Treasury,
    CircuitBreaker,
    GreekHedger,
    PortfolioService,
)

from .backtesting import (
    StrategyBacktester,
    BacktestMode,
    BacktestResult,
    DataLoader,
    OptionsSimulator,
    PnLCalculator,
)

from .agents import (
    BaseAgent,
    Sentinel,
    Monk,
    ModelTrainer,
    TradingEngine,
)

from .utilities import (
    InstrumentCache,
    OptionPricingModel,
    black_scholes,
)

__all__ = [
    "StrategySelector",
    "Strategist",
    "IronCondorStrategy",
    "JadeLizardStrategy",
    "IronButterflyStrategy",
    "BrokenWingButterflyStrategy",
    "RiskReversalStrategy",
    "StrangleStrategy",
    "calculate_adx",
    "calculate_rsi",
    "calculate_atr",
    "calculate_realized_vol",
    "calculate_iv_percentile",
    "calculate_greeks",
    "GreekCalculator",
    "calculate_sharpe",
    "calculate_sortino",
    "RegimeClassifier",
    "Executor",
    "Treasury",
    "CircuitBreaker",
    "GreekHedger",
    "PortfolioService",
    "StrategyBacktester",
    "BacktestMode",
    "BacktestResult",
    "DataLoader",
    "OptionsSimulator",
    "PnLCalculator",
    "BaseAgent",
    "Sentinel",
    "Monk",
    "ModelTrainer",
    "TradingEngine",
    "InstrumentCache",
    "OptionPricingModel",
    "black_scholes",
]
