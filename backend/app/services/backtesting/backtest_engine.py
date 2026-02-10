"""Backtest engine for Trading System v2.0"""

from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from loguru import logger

from ..agents import DataLoader
from ...config.thresholds import SLIPPAGE_PCT, BROKERAGE_PCT


@dataclass
class BacktestConfig:
    """Configuration for backtest run."""
    initial_capital: float = 1000000
    position_size_pct: float = 0.02
    max_positions: int = 3
    slippage_pct: float = SLIPPAGE_PCT
    brokerage_pct: float = BROKERAGE_PCT
    
    # Time filters
    entry_start_time: time = time(10, 0)
    entry_end_time: time = time(15, 0)
    
    # Risk limits
    max_loss_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    stop_on_daily_loss: bool = True


@dataclass
class BacktestPosition:
    """Represents an open position during backtest."""
    id: str
    entry_date: datetime
    entry_price: float
    size: float
    direction: int  # 1 for long, -1 for short
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    metadata: Dict = field(default_factory=dict)


@dataclass
class BacktestTrade:
    """Completed trade record."""
    id: str
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    size: float
    direction: int
    pnl: float
    pnl_pct: float
    exit_reason: str
    holding_days: int
    costs: float
    metadata: Dict = field(default_factory=dict)


class BacktestEngine:
    """
    Event-driven backtest engine.
    
    Simulates trading strategy on historical data with realistic
    execution assumptions (slippage, costs, position limits).
    """
    
    def __init__(
        self,
        config: Optional[BacktestConfig] = None,
        data_loader: Optional[DataLoader] = None
    ):
        self.config = config or BacktestConfig()
        self.data_loader = data_loader or DataLoader()
        
        # State
        self._capital: float = 0
        self._positions: Dict[str, BacktestPosition] = {}
        self._trades: List[BacktestTrade] = []
        self._equity_curve: List[float] = []
        self._daily_pnl: float = 0
        self._current_date: Optional[date] = None
        
        # Callbacks
        self._on_bar: Optional[Callable] = None
        self._entry_signal: Optional[Callable] = None
        self._exit_signal: Optional[Callable] = None
    
    def run(
        self,
        data: pd.DataFrame,
        entry_signal: Callable[[pd.DataFrame, int], Optional[Dict]],
        exit_signal: Callable[[pd.DataFrame, int, BacktestPosition], Optional[str]],
        on_bar: Optional[Callable[[pd.DataFrame, int], None]] = None
    ) -> Dict:
        """
        Run backtest on historical data.
        
        Args:
            data: OHLCV DataFrame with datetime index
            entry_signal: Function(data, idx) -> entry_dict or None
            exit_signal: Function(data, idx, position) -> exit_reason or None
            on_bar: Optional callback for each bar
            
        Returns:
            Dict with trades and metrics
        """
        self._reset()
        self._capital = self.config.initial_capital
        self._equity_curve = [self._capital]
        
        self._entry_signal = entry_signal
        self._exit_signal = exit_signal
        self._on_bar = on_bar
        
        logger.info(f"Starting backtest: {len(data)} bars, capital={self._capital}")
        
        # Ensure sorted by date
        data = data.sort_index()
        
        # Main loop
        for i in range(1, len(data)):
            bar = data.iloc[i]
            bar_date = bar.name.date() if hasattr(bar.name, 'date') else data.index[i].date()
            
            # Reset daily P&L on new day
            if self._current_date != bar_date:
                self._daily_pnl = 0
                self._current_date = bar_date
            
            # Check daily loss limit
            if self.config.stop_on_daily_loss:
                if self._daily_pnl / self._capital <= -self.config.max_daily_loss:
                    continue  # Skip trading for the day
            
            # Custom bar callback
            if self._on_bar:
                self._on_bar(data, i)
            
            # Check exits for open positions
            self._check_exits(data, i)
            
            # Check entries
            if len(self._positions) < self.config.max_positions:
                self._check_entries(data, i)
            
            # Update equity curve
            unrealized_pnl = self._calculate_unrealized_pnl(bar)
            self._equity_curve.append(self._capital + unrealized_pnl)
        
        # Close any remaining positions at end
        self._close_all_positions(data, len(data) - 1, "END_OF_DATA")
        
        # Calculate metrics
        metrics = calculate_metrics(
            [self._trade_to_dict(t) for t in self._trades],
            self.config.initial_capital
        )
        
        logger.info(
            f"Backtest complete: {len(self._trades)} trades, "
            f"return={metrics.get('total_return_pct', 0):.2%}, "
            f"sharpe={metrics.get('sharpe_ratio', 0):.2f}"
        )
        
        return {
            "trades": self._trades,
            "metrics": metrics,
            "equity_curve": self._equity_curve,
            "config": self.config
        }
    
    def _reset(self) -> None:
        """Reset engine state."""
        self._capital = 0
        self._positions = {}
        self._trades = []
        self._equity_curve = []
        self._daily_pnl = 0
        self._current_date = None
    
    def _check_entries(self, data: pd.DataFrame, idx: int) -> None:
        """Check for entry signals."""
        signal = self._entry_signal(data, idx)
        
        if signal is None:
            return
        
        bar = data.iloc[idx]
        
        # Calculate position size
        size = self._capital * self.config.position_size_pct
        
        # Check per-trade risk limit
        if signal.get("stop_loss"):
            risk = abs(bar['close'] - signal["stop_loss"]) / bar['close']
            max_risk = self.config.max_loss_per_trade
            if risk > max_risk:
                size = size * (max_risk / risk)
        
        # Apply slippage
        direction = signal.get("direction", 1)
        entry_price = bar['close'] * (1 + self.config.slippage_pct * direction)
        
        # Create position
        position = BacktestPosition(
            id=f"POS_{idx}_{datetime.now().timestamp()}",
            entry_date=bar.name,
            entry_price=entry_price,
            size=size,
            direction=direction,
            stop_loss=signal.get("stop_loss"),
            take_profit=signal.get("take_profit"),
            metadata=signal.get("metadata", {})
        )
        
        self._positions[position.id] = position
        logger.debug(f"Opened position: {position.id} @ {entry_price:.2f}")
    
    def _check_exits(self, data: pd.DataFrame, idx: int) -> None:
        """Check for exit signals on open positions."""
        bar = data.iloc[idx]
        positions_to_close = []
        
        for pos_id, position in self._positions.items():
            exit_reason = None
            
            # Check custom exit signal
            if self._exit_signal:
                exit_reason = self._exit_signal(data, idx, position)
            
            # Check stop loss
            if not exit_reason and position.stop_loss:
                if position.direction == 1 and bar['low'] <= position.stop_loss:
                    exit_reason = "STOP_LOSS"
                elif position.direction == -1 and bar['high'] >= position.stop_loss:
                    exit_reason = "STOP_LOSS"
            
            # Check take profit
            if not exit_reason and position.take_profit:
                if position.direction == 1 and bar['high'] >= position.take_profit:
                    exit_reason = "TAKE_PROFIT"
                elif position.direction == -1 and bar['low'] <= position.take_profit:
                    exit_reason = "TAKE_PROFIT"
            
            if exit_reason:
                positions_to_close.append((pos_id, exit_reason))
        
        # Close positions
        for pos_id, reason in positions_to_close:
            self._close_position(pos_id, data, idx, reason)
    
    def _close_position(
        self,
        pos_id: str,
        data: pd.DataFrame,
        idx: int,
        reason: str
    ) -> None:
        """Close a position and record the trade."""
        position = self._positions.pop(pos_id)
        bar = data.iloc[idx]
        
        # Determine exit price
        if reason == "STOP_LOSS" and position.stop_loss:
            exit_price = position.stop_loss
        elif reason == "TAKE_PROFIT" and position.take_profit:
            exit_price = position.take_profit
        else:
            # Apply slippage (opposite direction)
            exit_price = bar['close'] * (1 - self.config.slippage_pct * position.direction)
        
        # Calculate P&L
        price_change = (exit_price - position.entry_price) * position.direction
        pnl_pct = price_change / position.entry_price
        pnl = position.size * pnl_pct
        
        # Calculate costs
        trade_value = position.size
        costs = trade_value * self.config.brokerage_pct * 2  # Entry + exit
        
        pnl -= costs
        
        # Update capital
        self._capital += pnl
        self._daily_pnl += pnl
        
        # Calculate holding period
        entry_date = position.entry_date
        exit_date = bar.name
        if hasattr(entry_date, 'date'):
            holding_days = (exit_date.date() - entry_date.date()).days
        else:
            holding_days = (exit_date - entry_date).days
        
        # Record trade
        trade = BacktestTrade(
            id=position.id,
            entry_date=position.entry_date,
            exit_date=bar.name,
            entry_price=position.entry_price,
            exit_price=exit_price,
            size=position.size,
            direction=position.direction,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            holding_days=max(holding_days, 1),
            costs=costs,
            metadata=position.metadata
        )
        
        self._trades.append(trade)
        logger.debug(f"Closed position: {pos_id}, P&L={pnl:.2f} ({reason})")
    
    def _close_all_positions(self, data: pd.DataFrame, idx: int, reason: str) -> None:
        """Close all open positions."""
        for pos_id in list(self._positions.keys()):
            self._close_position(pos_id, data, idx, reason)
    
    def _calculate_unrealized_pnl(self, bar: pd.Series) -> float:
        """Calculate unrealized P&L for open positions."""
        unrealized = 0
        for position in self._positions.values():
            price_change = (bar['close'] - position.entry_price) * position.direction
            unrealized += position.size * (price_change / position.entry_price)
        return unrealized
    
    def _trade_to_dict(self, trade: BacktestTrade) -> Dict:
        """Convert BacktestTrade to dictionary."""
        return {
            "id": trade.id,
            "entry_date": trade.entry_date,
            "exit_date": trade.exit_date,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "size": trade.size,
            "direction": trade.direction,
            "pnl": trade.pnl,
            "pnl_pct": trade.pnl_pct,
            "exit_reason": trade.exit_reason,
            "holding_days": trade.holding_days,
            "costs": trade.costs
        }
    
    def get_trades_df(self) -> pd.DataFrame:
        """Get trades as DataFrame."""
        return pd.DataFrame([self._trade_to_dict(t) for t in self._trades])
    
    def get_equity_curve_df(self) -> pd.DataFrame:
        """Get equity curve as DataFrame."""
        return pd.DataFrame({"equity": self._equity_curve})


def run_quick_backtest(
    data: pd.DataFrame,
    entry_condition: Callable[[pd.DataFrame], pd.Series],
    exit_condition: Callable[[pd.DataFrame], pd.Series],
    initial_capital: float = 1000000,
    position_size_pct: float = 0.02
) -> Dict:
    """
    Quick vectorized backtest for simple strategies.
    
    Args:
        data: OHLCV DataFrame
        entry_condition: Function returning boolean Series for entries
        exit_condition: Function returning boolean Series for exits
        initial_capital: Starting capital
        position_size_pct: Position size as % of capital
        
    Returns:
        Dict with trades and metrics
    """
    entries = entry_condition(data)
    exits = exit_condition(data)
    
    trades = []
    in_position = False
    entry_idx = None
    entry_price = None
    
    for i in range(len(data)):
        if not in_position and entries.iloc[i]:
            in_position = True
            entry_idx = i
            entry_price = data.iloc[i]['close']
        
        elif in_position and exits.iloc[i]:
            exit_price = data.iloc[i]['close']
            pnl_pct = (exit_price - entry_price) / entry_price
            pnl = initial_capital * position_size_pct * pnl_pct
            
            trades.append({
                "entry_date": data.index[entry_idx],
                "exit_date": data.index[i],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "holding_days": i - entry_idx,
                "exit_reason": "SIGNAL"
            })
            
            in_position = False
    
    metrics = calculate_metrics(trades, initial_capital)
    
    return {
        "trades": trades,
        "metrics": metrics
    }
