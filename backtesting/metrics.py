"""Performance metrics for Trading System v2.0 backtesting"""

from typing import Dict, List, Optional
import numpy as np
import pandas as pd


def calculate_metrics(trades: List[Dict], initial_capital: float = 1000000) -> Dict:
    """
    Calculate comprehensive performance metrics from trade list.
    
    Args:
        trades: List of trade dictionaries with pnl, pnl_pct, etc.
        initial_capital: Starting capital
        
    Returns:
        Dictionary of performance metrics
    """
    if not trades:
        return {"error": "No trades to analyze"}
    
    pnls = [t.get("pnl", 0) for t in trades]
    pnl_pcts = [t.get("pnl_pct", 0) for t in trades]
    
    # Basic stats
    total_return = sum(pnls)
    total_return_pct = total_return / initial_capital
    num_trades = len(trades)
    
    # Win/loss analysis
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    win_rate = len(wins) / num_trades if num_trades > 0 else 0
    loss_rate = len(losses) / num_trades if num_trades > 0 else 0
    
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    max_win = max(wins) if wins else 0
    max_loss = min(losses) if losses else 0
    
    # Profit factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Risk metrics
    sharpe = calculate_sharpe(pnl_pcts)
    sortino = calculate_sortino(pnl_pcts)
    
    # Drawdown
    equity_curve = build_equity_curve(pnls, initial_capital)
    max_dd, max_dd_duration = calculate_max_drawdown(equity_curve)
    
    # Expectancy
    expectancy = (win_rate * avg_win) + (loss_rate * avg_loss)
    
    # Recovery factor
    recovery_factor = total_return / (max_dd * initial_capital) if max_dd > 0 else float('inf')
    
    # Calmar ratio (annualized return / max drawdown)
    # Assuming ~252 trading days and average holding period
    avg_holding = np.mean([t.get("holding_days", 1) for t in trades])
    trades_per_year = 252 / avg_holding if avg_holding > 0 else 50
    annualized_return = total_return_pct * (trades_per_year / num_trades) if num_trades > 0 else 0
    calmar = annualized_return / max_dd if max_dd > 0 else float('inf')
    
    return {
        # Returns
        "total_return": total_return,
        "total_return_pct": total_return_pct,
        "annualized_return": annualized_return,
        
        # Trade stats
        "num_trades": num_trades,
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_win": max_win,
        "max_loss": max_loss,
        
        # Risk-adjusted
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "profit_factor": profit_factor,
        "calmar_ratio": calmar,
        "recovery_factor": recovery_factor,
        
        # Drawdown
        "max_drawdown": max_dd,
        "max_drawdown_duration": max_dd_duration,
        
        # Other
        "expectancy": expectancy,
        "avg_holding_days": avg_holding,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss
    }


def calculate_sharpe(returns: List[float], risk_free_rate: float = 0.05, annualize: bool = True) -> float:
    """
    Calculate Sharpe ratio.
    
    Args:
        returns: List of period returns (as decimals)
        risk_free_rate: Annual risk-free rate
        annualize: Whether to annualize the ratio
        
    Returns:
        Sharpe ratio
    """
    if len(returns) < 2:
        return 0.0
    
    returns = np.array(returns)
    excess_returns = returns - (risk_free_rate / 252)  # Daily risk-free
    
    mean_excess = np.mean(excess_returns)
    std_excess = np.std(excess_returns, ddof=1)
    
    if std_excess == 0:
        return 0.0
    
    sharpe = mean_excess / std_excess
    
    if annualize:
        sharpe *= np.sqrt(252)
    
    return float(sharpe)


def calculate_sortino(returns: List[float], risk_free_rate: float = 0.05, annualize: bool = True) -> float:
    """
    Calculate Sortino ratio (uses downside deviation).
    
    Args:
        returns: List of period returns
        risk_free_rate: Annual risk-free rate
        annualize: Whether to annualize
        
    Returns:
        Sortino ratio
    """
    if len(returns) < 2:
        return 0.0
    
    returns = np.array(returns)
    excess_returns = returns - (risk_free_rate / 252)
    
    mean_excess = np.mean(excess_returns)
    
    # Downside deviation (only negative returns)
    downside = excess_returns[excess_returns < 0]
    if len(downside) == 0:
        return float('inf')
    
    downside_std = np.std(downside, ddof=1)
    
    if downside_std == 0:
        return float('inf')
    
    sortino = mean_excess / downside_std
    
    if annualize:
        sortino *= np.sqrt(252)
    
    return float(sortino)


def build_equity_curve(pnls: List[float], initial_capital: float) -> List[float]:
    """Build equity curve from P&L series."""
    equity = [initial_capital]
    for pnl in pnls:
        equity.append(equity[-1] + pnl)
    return equity


def calculate_max_drawdown(equity_curve: List[float]) -> tuple[float, int]:
    """
    Calculate maximum drawdown and its duration.
    
    Args:
        equity_curve: List of equity values
        
    Returns:
        Tuple of (max_drawdown_pct, max_duration_periods)
    """
    equity = np.array(equity_curve)
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak
    
    max_dd = np.max(drawdown)
    
    # Calculate duration
    in_drawdown = drawdown > 0
    max_duration = 0
    current_duration = 0
    
    for is_dd in in_drawdown:
        if is_dd:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0
    
    return float(max_dd), max_duration


def calculate_cagr(initial_value: float, final_value: float, years: float) -> float:
    """Calculate Compound Annual Growth Rate."""
    if initial_value <= 0 or years <= 0:
        return 0.0
    return (final_value / initial_value) ** (1 / years) - 1


def calculate_var(returns: List[float], confidence: float = 0.95) -> float:
    """
    Calculate Value at Risk.
    
    Args:
        returns: List of returns
        confidence: Confidence level (e.g., 0.95 for 95%)
        
    Returns:
        VaR as positive number (potential loss)
    """
    if not returns:
        return 0.0
    
    percentile = (1 - confidence) * 100
    var = np.percentile(returns, percentile)
    return abs(var)


def calculate_cvar(returns: List[float], confidence: float = 0.95) -> float:
    """
    Calculate Conditional Value at Risk (Expected Shortfall).
    
    Args:
        returns: List of returns
        confidence: Confidence level
        
    Returns:
        CVaR as positive number
    """
    if not returns:
        return 0.0
    
    var = calculate_var(returns, confidence)
    returns = np.array(returns)
    tail_losses = returns[returns <= -var]
    
    if len(tail_losses) == 0:
        return var
    
    return abs(np.mean(tail_losses))


def generate_monthly_returns(trades: List[Dict]) -> pd.DataFrame:
    """
    Generate monthly returns table from trades.
    
    Args:
        trades: List of trade dictionaries with dates and pnl
        
    Returns:
        DataFrame with monthly returns
    """
    if not trades:
        return pd.DataFrame()
    
    # Convert to DataFrame
    df = pd.DataFrame(trades)
    
    if 'exit_date' not in df.columns:
        return pd.DataFrame()
    
    df['exit_date'] = pd.to_datetime(df['exit_date'])
    df['year'] = df['exit_date'].dt.year
    df['month'] = df['exit_date'].dt.month
    
    # Aggregate by month
    monthly = df.groupby(['year', 'month'])['pnl'].sum().unstack(fill_value=0)
    
    return monthly
