"""
Historical Data Client for Backtesting

This module provides a KiteClient-compatible interface that serves historical
data instead of live data. This allows the production Orchestrator to run
unchanged during backtesting.

Key Principle: NO trading logic here. We only provide data - the actual
trading decisions use the SAME code as paper/live trading.
"""

from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional, Any, Iterator
import pandas as pd
import numpy as np
from loguru import logger
from pathlib import Path

from ...config.constants import NIFTY_TOKEN, BANKNIFTY_TOKEN, INDIA_VIX_TOKEN


class HistoricalDataClient:
    """
    A KiteClient replacement that serves historical OHLCV data.
    
    This class has the SAME interface as KiteClient but returns
    historical data instead of live data. This allows the production
    Orchestrator to run unchanged during backtesting.
    
    Usage:
        df = pd.read_parquet("NIFTY_1minute.parquet")
        client = HistoricalDataClient(df)
        
        # Use with production Orchestrator
        orchestrator.kite = client
    """
    
    def __init__(
        self,
        ohlcv_data: pd.DataFrame,
        instrument_token: int = NIFTY_TOKEN,
        symbol: str = "NIFTY",
        initial_capital: float = 1000000,
        slippage_pct: float = 0.001
    ):
        """
        Initialize with historical OHLCV data.
        
        Args:
            ohlcv_data: DataFrame with columns [date, open, high, low, close, volume]
            instrument_token: Token for the instrument
            symbol: Symbol name
            initial_capital: Starting capital for paper trading
            slippage_pct: Slippage percentage for order fills
        """
        self.instrument_token = instrument_token
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.slippage_pct = slippage_pct
        
        # Prepare data
        self._data = self._prepare_data(ohlcv_data)
        self._current_idx = 0
        self._current_date: Optional[date] = None
        
        # Simulate KiteClient attributes
        self.paper_mode = True
        self.mock_mode = True
        self.api_key = "backtest"
        self.access_token = "backtest"
        
        # Paper trading state
        self._paper_orders: Dict[str, Dict] = {}
        self._paper_positions: Dict[str, Dict] = {}
        self._paper_balance = initial_capital
        self._order_counter = 0
        
        # Additional instrument data (e.g., VIX)
        self._instrument_data: Dict[int, pd.DataFrame] = {
            instrument_token: self._data
        }
        self._instrument_symbols: Dict[int, str] = {
            instrument_token: symbol
        }
        
        logger.info(f"HistoricalDataClient initialized with {len(self._data)} bars")
        logger.info(f"Date range: {self._data['date'].min()} to {self._data['date'].max()}")
    
    def add_instrument_data(self, token: int, symbol: str, data: pd.DataFrame) -> None:
        """Add data for an additional instrument (e.g., VIX)."""
        prepared = self._prepare_data(data)
        self._instrument_data[token] = prepared
        self._instrument_symbols[token] = symbol
        logger.info(f"Added {symbol} data: {len(prepared)} bars")
    
    def _prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare and validate OHLCV data."""
        df = df.copy()
        
        # Standardize column names
        column_mapping = {
            'datetime': 'date',
            'timestamp': 'date',
            'Date': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume'
        }
        df = df.rename(columns=column_mapping)
        
        # Ensure date column exists and is datetime
        if 'date' not in df.columns:
            raise ValueError("Data must have 'date', 'datetime', or 'timestamp' column")
        df['date'] = pd.to_datetime(df['date'])
        
        # Ensure required columns exist
        required = ['open', 'high', 'low', 'close']
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        # Add volume if missing
        if 'volume' not in df.columns:
            df['volume'] = 0
        
        # Sort by date
        df = df.sort_values('date').reset_index(drop=True)
        
        return df
    
    def set_current_date(self, current_date: date) -> None:
        """Set the current simulation date."""
        self._current_date = current_date
        
        # Find index for this date
        mask = self._data['date'].dt.date <= current_date
        if mask.any():
            self._current_idx = mask.sum() - 1
    
    def get_current_bar(self) -> Optional[Dict]:
        """Get the current bar data."""
        if self._current_idx >= len(self._data):
            return None
        
        row = self._data.iloc[self._current_idx]
        return {
            'date': row['date'],
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': int(row['volume']),
            'instrument_token': self.instrument_token,
            'tradingsymbol': self.symbol
        }
    
    def get_ltp(self) -> float:
        """Get last traded price (close of current bar)."""
        bar = self.get_current_bar()
        return bar['close'] if bar else 0.0
    
    def iterate_dates(self) -> Iterator[date]:
        """Iterate through all unique dates in the data."""
        unique_dates = self._data['date'].dt.date.unique()
        for d in sorted(unique_dates):
            self.set_current_date(d)
            yield d
    
    def get_date_range(self) -> tuple:
        """Get the date range of available data."""
        return (
            self._data['date'].min().date(),
            self._data['date'].max().date()
        )
    
    # =========================================================================
    # KiteClient Interface Methods
    # =========================================================================
    
    def fetch_historical_data(
        self,
        instrument_token: int,
        interval: str,
        from_date: datetime,
        to_date: datetime
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data.
        
        This is called by Sentinel for indicator calculations.
        
        IMPORTANT: In backtest mode, we translate the date range relative to
        the current simulation date. Sentinel calls with datetime.now() but
        we need to return data up to the simulation date.
        """
        if not self._current_date:
            return pd.DataFrame()
        
        # Get data for the requested instrument
        data = self._instrument_data.get(instrument_token, self._data)
        
        # Calculate lookback days from the request
        lookback_days = (to_date.date() - from_date.date()).days
        
        # Translate to simulation date range
        sim_to_date = self._current_date
        sim_from_date = sim_to_date - timedelta(days=lookback_days)
        
        # Filter data for the simulation date range
        mask = (data['date'].dt.date >= sim_from_date) & \
               (data['date'].dt.date <= sim_to_date)
        
        result = data[mask].copy()
        
        # Resample based on interval
        if len(result) > 0:
            if interval == 'day':
                result = result.set_index('date').resample('D').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna().reset_index()
            elif interval == '5minute':
                result = result.set_index('date').resample('5min').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna().reset_index()
        
        return result
    
    def get_ltp(self, tokens: List[int]) -> Dict[int, float]:
        """Get last traded prices for tokens."""
        ltp = self.get_current_bar()['close'] if self.get_current_bar() else 0.0
        return {token: ltp for token in tokens}
    
    def get_quote(self, tokens: List[int]) -> Dict[int, Dict]:
        """Get quotes for tokens."""
        bar = self.get_current_bar()
        if not bar:
            return {}
        
        result = {}
        for token in tokens:
            result[token] = {
                'instrument_token': token,
                'last_price': bar['close'],
                'ohlc': {
                    'open': bar['open'],
                    'high': bar['high'],
                    'low': bar['low'],
                    'close': bar['close']
                },
                'volume': bar['volume'],
                'timestamp': bar['date']
            }
        return result
    
    def get_positions(self) -> Dict[str, List[Dict]]:
        """Get current positions."""
        return {
            'net': list(self._paper_positions.values()),
            'day': []
        }
    
    def get_margins(self) -> Dict[str, Dict]:
        """Get account margins."""
        used_margin = sum(
            abs(p.get('quantity', 0) * p.get('average_price', 0) * 0.15)
            for p in self._paper_positions.values()
        )
        
        return {
            'equity': {
                'net': self._paper_balance,
                'available': {
                    'cash': self._paper_balance - used_margin,
                    'live_balance': self._paper_balance
                },
                'utilised': {
                    'span': used_margin,
                    'exposure': 0
                }
            }
        }
    
    def place_order(
        self,
        tradingsymbol: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MARKET",
        product: str = "NRML",
        price: float = 0,
        **kwargs
    ) -> str:
        """
        Place a simulated order.
        
        Returns order_id.
        """
        self._order_counter += 1
        order_id = f"BT{self._order_counter:06d}"
        
        # Get fill price with slippage
        ltp = self.get_current_bar()['close'] if self.get_current_bar() else 0
        if transaction_type == "BUY":
            fill_price = ltp * (1 + self.slippage_pct)
        else:
            fill_price = ltp * (1 - self.slippage_pct)
        
        # Record order
        self._paper_orders[order_id] = {
            'order_id': order_id,
            'tradingsymbol': tradingsymbol,
            'exchange': exchange,
            'transaction_type': transaction_type,
            'quantity': quantity,
            'order_type': order_type,
            'product': product,
            'price': fill_price,
            'status': 'COMPLETE',
            'filled_quantity': quantity,
            'average_price': fill_price,
            'order_timestamp': datetime.now()
        }
        
        # Update position
        pos_key = f"{exchange}:{tradingsymbol}"
        if pos_key in self._paper_positions:
            pos = self._paper_positions[pos_key]
            if transaction_type == "BUY":
                new_qty = pos['quantity'] + quantity
            else:
                new_qty = pos['quantity'] - quantity
            
            if new_qty == 0:
                del self._paper_positions[pos_key]
            else:
                pos['quantity'] = new_qty
        else:
            qty = quantity if transaction_type == "BUY" else -quantity
            self._paper_positions[pos_key] = {
                'tradingsymbol': tradingsymbol,
                'exchange': exchange,
                'quantity': qty,
                'average_price': fill_price,
                'last_price': fill_price,
                'pnl': 0,
                'instrument_token': self.instrument_token
            }
        
        logger.debug(f"Order: {order_id} {transaction_type} {quantity} {tradingsymbol} @ {fill_price:.2f}")
        return order_id
    
    def modify_order(self, order_id: str, **kwargs) -> str:
        """Modify an order (no-op for backtest)."""
        return order_id
    
    def cancel_order(self, order_id: str, **kwargs) -> str:
        """Cancel an order."""
        if order_id in self._paper_orders:
            self._paper_orders[order_id]['status'] = 'CANCELLED'
        return order_id
    
    def get_orders(self) -> List[Dict]:
        """Get all orders."""
        return list(self._paper_orders.values())
    
    def get_order_history(self, order_id: str) -> List[Dict]:
        """Get order history."""
        if order_id in self._paper_orders:
            return [self._paper_orders[order_id]]
        return []
    
    def get_instruments(self, exchange: str = None) -> pd.DataFrame:
        """Get instruments list (mock with options for backtesting)."""
        current_date = self._current_date or date.today()
        
        # Generate mock instruments including options for the next 3 monthly expiries
        instruments = [{
            'instrument_token': self.instrument_token,
            'tradingsymbol': self.symbol,
            'name': self.symbol,
            'exchange': 'NSE',
            'segment': 'NSE',
            'instrument_type': 'EQ',
            'expiry': None
        }]
        
        # Add options for backtesting - generate 3 monthly expiries
        from calendar import monthrange
        for month_offset in range(1, 4):
            # Calculate expiry (last Thursday of month)
            exp_month = (current_date.month + month_offset - 1) % 12 + 1
            exp_year = current_date.year + (current_date.month + month_offset - 1) // 12
            last_day = monthrange(exp_year, exp_month)[1]
            exp_date = date(exp_year, exp_month, last_day)
            # Find last Thursday
            while exp_date.weekday() != 3:  # Thursday
                exp_date -= timedelta(days=1)
            
            # Generate strikes around current spot
            spot = self.get_current_bar()['close'] if self.get_current_bar() else 22000
            base_strike = round(spot / 50) * 50
            
            for strike_offset in range(-10, 11):  # 21 strikes
                strike = base_strike + strike_offset * 50
                for opt_type in ['CE', 'PE']:
                    instruments.append({
                        'instrument_token': 100000 + len(instruments),
                        'tradingsymbol': f"{self.symbol}{exp_date.strftime('%y%b').upper()}{int(strike)}{opt_type}",
                        'name': self.symbol,
                        'exchange': 'NFO',
                        'segment': 'NFO-OPT',
                        'instrument_type': opt_type,
                        'expiry': exp_date,
                        'strike': strike
                    })
        
        return pd.DataFrame(instruments)
    
    def get_option_chain(self, symbol: str, expiry: date) -> pd.DataFrame:
        """Get option chain (simulated using OptionsSimulator)."""
        from .options_simulator import OptionsSimulator
        
        simulator = OptionsSimulator()
        spot = self.get_current_bar()['close'] if self.get_current_bar() else 0
        current_date = self._current_date or date.today()
        
        # Estimate IV from recent volatility
        hist = self.fetch_historical_data(
            self.instrument_token,
            'day',
            datetime.combine(current_date - timedelta(days=30), time()),
            datetime.combine(current_date, time())
        )
        if len(hist) > 5:
            returns = hist['close'].pct_change().dropna()
            iv = returns.std() * np.sqrt(252)
        else:
            iv = 0.15
        
        chain = simulator.get_options_chain(spot, expiry, current_date, iv)
        
        # Convert to DataFrame format expected by Strategist
        rows = []
        token_counter = 100000
        for quote in chain.get('calls', []) + chain.get('puts', []):
            opt_type = quote.option_type  # 'CE' or 'PE'
            strike_int = int(quote.strike)
            expiry_str = quote.expiry.strftime('%y%b').upper()  # e.g., '24MAR'
            tradingsymbol = f"{symbol}{expiry_str}{strike_int}{opt_type}"
            
            rows.append({
                'strike': quote.strike,
                'expiry': quote.expiry,
                'instrument_type': opt_type,
                'tradingsymbol': tradingsymbol,
                'instrument_token': token_counter,
                'name': symbol,
                'last_price': quote.mid,
                'ltp': quote.mid,
                'bid': quote.bid,
                'ask': quote.ask,
                'iv': quote.iv,
                'delta': quote.delta,
                'gamma': quote.gamma,
                'theta': quote.theta,
                'vega': quote.vega,
                'oi': 10000,  # Simulated OI
                'volume': 1000  # Simulated volume
            })
            token_counter += 1
        
        return pd.DataFrame(rows)


def load_ohlcv_data(file_path: str) -> pd.DataFrame:
    """
    Load OHLCV data from file (CSV or Parquet).
    
    Works with data from any source (Kite, Breeze, etc.)
    as long as it has the required columns.
    """
    path = Path(file_path)
    
    if path.suffix == '.parquet':
        df = pd.read_parquet(path)
    elif path.suffix == '.csv':
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}")
    
    logger.info(f"Loaded {len(df)} rows from {path}")
    return df
