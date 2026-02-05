"""KiteConnect API wrapper for Trading System v2.0"""

import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
import pandas as pd
from loguru import logger

try:
    from kiteconnect import KiteConnect, KiteTicker
    from kiteconnect.exceptions import TokenException, DataException
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False
    TokenException = Exception  # Fallback
    DataException = Exception
    logger.warning("kiteconnect not installed, using mock mode")


class TokenExpiredException(Exception):
    """Raised when Kite access token is expired or invalid."""
    pass


class KiteClient:
    """
    KiteConnect wrapper with retry logic, rate limiting, and caching.
    
    Modes:
    - paper_mode=False: Live trading - real data AND real orders
    - paper_mode=True: Paper trading - real data but simulated orders
    - mock_mode=True: Full mock - no API calls at all (for testing)
    """
    
    def __init__(
        self,
        api_key: str,
        access_token: str = "",
        paper_mode: bool = True,
        mock_mode: bool = False,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        self.api_key = api_key
        self.access_token = access_token
        self.paper_mode = paper_mode  # Use real data, simulate orders
        self.mock_mode = mock_mode or not KITE_AVAILABLE  # Full mock, no API
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        self._kite: Optional[KiteConnect] = None
        self._ticker: Optional[KiteTicker] = None
        self._quote_cache: Dict[int, Dict] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl = 5  # seconds
        
        # Paper orders tracking
        self._paper_orders: Dict[str, Dict] = {}
        self._paper_positions: Dict[str, Dict] = {}
        
        if not self.mock_mode and KITE_AVAILABLE:
            self._init_kite()
            mode_str = "PAPER" if self.paper_mode else "LIVE"
            logger.info(f"KiteClient initialized in {mode_str} mode with real API")
        else:
            logger.info("KiteClient initialized in MOCK mode (no API)")
    
    def _init_kite(self) -> None:
        """Initialize KiteConnect instance."""
        try:
            self._kite = KiteConnect(api_key=self.api_key)
            if self.access_token:
                self._kite.set_access_token(self.access_token)
                logger.info("KiteConnect initialized with access token")
            else:
                logger.warning("KiteConnect initialized without access token")
        except Exception as e:
            logger.error(f"Failed to initialize KiteConnect: {e}")
            self.mock_mode = True
    
    def get_login_url(self) -> str:
        """Get the login URL for generating access token."""
        if self._kite:
            return self._kite.login_url()
        return f"https://kite.zerodha.com/connect/login?api_key={self.api_key}"
    
    def generate_session(self, request_token: str, api_secret: str) -> Dict:
        """Generate session from request token."""
        if self.mock_mode:
            return {"access_token": "mock_token"}
        
        try:
            data = self._kite.generate_session(request_token, api_secret=api_secret)
            self.access_token = data["access_token"]
            self._kite.set_access_token(self.access_token)
            logger.info("Session generated successfully")
            return data
        except Exception as e:
            logger.error(f"Failed to generate session: {e}")
            raise
    
    def _retry_request(self, func, *args, **kwargs) -> Any:
        """Execute a request with retry logic."""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except TokenException as e:
                # Token expired - don't retry, raise immediately
                logger.error(f"Token expired or invalid: {e}")
                raise TokenExpiredException(str(e))
            except Exception as e:
                error_str = str(e).lower()
                # Check for token-related errors in message
                if "api_key" in error_str or "access_token" in error_str or "token" in error_str:
                    logger.error(f"Token error detected: {e}")
                    raise TokenExpiredException(str(e))
                
                last_error = e
                logger.warning(f"Request failed (attempt {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
        
        logger.error(f"Request failed after {self.max_retries} attempts: {last_error}")
        raise last_error
    
    def fetch_historical_data(
        self,
        instrument_token: int,
        interval: str,
        from_date: datetime,
        to_date: datetime,
        continuous: bool = False
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data.
        
        Args:
            instrument_token: Instrument token
            interval: Candle interval (minute, 5minute, 15minute, day, etc.)
            from_date: Start date
            to_date: End date
            continuous: Whether to fetch continuous data for F&O
            
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        if self.mock_mode:
            return self._mock_historical_data(from_date, to_date, interval)
        
        try:
            data = self._retry_request(
                self._kite.historical_data,
                instrument_token,
                from_date,
                to_date,
                interval,
                continuous=continuous
            )
            
            df = pd.DataFrame(data)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
            
            logger.debug(f"Fetched {len(df)} candles for token {instrument_token}")
            return df
            
        except Exception as e:
            logger.error(f"Failed to fetch historical data: {e}")
            return pd.DataFrame()
    
    def get_quote(self, instruments: list) -> Dict:
        """
        Get real-time quotes for instruments.
        
        Args:
            instruments: List of instrument tokens (int) or symbols (str like "NSE:NIFTY 50")
            
        Returns:
            Dict mapping instrument key to quote data
        """
        if not instruments:
            return {}
        
        # Check if instruments are strings (symbols) or ints (tokens)
        if isinstance(instruments[0], str):
            # Already in symbol format (e.g., "NSE:NIFTY 50")
            instrument_keys = instruments
        else:
            # Convert tokens to exchange:token format
            instrument_keys = [f"NSE:{token}" if token < 1000000 else f"NFO:{token}" 
                             for token in instruments]
        
        # Check cache for token-based requests
        if not isinstance(instruments[0], str) and self._is_cache_valid():
            cached = {t: self._quote_cache[t] for t in instruments if t in self._quote_cache}
            if len(cached) == len(instruments):
                return cached
        
        if self.mock_mode:
            return self._mock_quotes(instruments)
        
        try:
            quotes = self._retry_request(self._kite.quote, instrument_keys)
            
            # For symbol-based requests, return as-is with symbol keys
            if isinstance(instruments[0], str):
                return quotes
            
            # For token-based requests, parse and cache
            result = {}
            for key, data in quotes.items():
                token = data.get("instrument_token")
                if token:
                    result[token] = data
                    self._quote_cache[token] = data
            
            self._cache_timestamp = datetime.now()
            return result
            
        except Exception as e:
            logger.error(f"Failed to get quotes: {e}")
            return {}
    
    def get_ltp(self, instrument_tokens: List[int]) -> Dict[int, float]:
        """Get last traded price for instruments."""
        quotes = self.get_quote(instrument_tokens)
        return {token: data.get("last_price", 0.0) for token, data in quotes.items()}
    
    def get_option_chain(
        self,
        underlying: str,
        expiry: date,
        strike_range: Optional[tuple] = None
    ) -> pd.DataFrame:
        """
        Get option chain for an underlying.
        
        Args:
            underlying: Underlying symbol (NIFTY, BANKNIFTY)
            expiry: Expiry date
            strike_range: Optional (min_strike, max_strike) tuple
            
        Returns:
            DataFrame with option chain data
        """
        if self.mock_mode:
            return self._mock_option_chain(underlying, expiry)
        
        try:
            # Get instruments for the underlying
            instruments = self._kite.instruments("NFO")
            df = pd.DataFrame(instruments)
            
            # Filter for options
            df = df[
                (df['name'] == underlying) &
                (df['instrument_type'].isin(['CE', 'PE'])) &
                (df['expiry'] == expiry)
            ]
            
            if strike_range:
                df = df[(df['strike'] >= strike_range[0]) & (df['strike'] <= strike_range[1])]
            
            # Get quotes for all options
            tokens = df['instrument_token'].tolist()
            if tokens:
                quotes = self.get_quote(tokens)
                df['ltp'] = df['instrument_token'].map(lambda t: quotes.get(t, {}).get('last_price', 0))
                df['bid'] = df['instrument_token'].map(lambda t: quotes.get(t, {}).get('depth', {}).get('buy', [{}])[0].get('price', 0))
                df['ask'] = df['instrument_token'].map(lambda t: quotes.get(t, {}).get('depth', {}).get('sell', [{}])[0].get('price', 0))
                df['oi'] = df['instrument_token'].map(lambda t: quotes.get(t, {}).get('oi', 0))
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to get option chain: {e}")
            return pd.DataFrame()
    
    def place_order(
        self,
        tradingsymbol: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MARKET",
        product: str = "NRML",
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        tag: Optional[str] = None
    ) -> str:
        """
        Place an order.
        
        Args:
            tradingsymbol: Trading symbol
            exchange: Exchange (NSE, NFO, MCX)
            transaction_type: BUY or SELL
            quantity: Order quantity
            order_type: MARKET, LIMIT, SL, SL-M
            product: MIS (intraday) or NRML (overnight)
            price: Limit price (for LIMIT orders)
            trigger_price: Trigger price (for SL orders)
            tag: Order tag for tracking
            
        Returns:
            Order ID
        """
        # Paper mode or mock mode - simulate order
        if self.mock_mode or self.paper_mode:
            order_id = f"PAPER_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{tradingsymbol}"
            
            # Get current price for paper fill
            fill_price = price
            if order_type == "MARKET" and self._kite and not self.mock_mode:
                try:
                    quote = self.get_ltp([self._get_token_for_symbol(tradingsymbol, exchange)])
                    if quote:
                        fill_price = list(quote.values())[0]
                except:
                    fill_price = price or 0
            
            # Track paper order
            self._paper_orders[order_id] = {
                "order_id": order_id,
                "tradingsymbol": tradingsymbol,
                "exchange": exchange,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "order_type": order_type,
                "product": product,
                "price": price,
                "average_price": fill_price,
                "status": "COMPLETE",
                "filled_quantity": quantity,
                "pending_quantity": 0,
                "order_timestamp": datetime.now(),
                "tag": tag
            }
            
            mode = "MOCK" if self.mock_mode else "PAPER"
            logger.info(f"[{mode}] ORDER placed: {order_id} - {transaction_type} {quantity} {tradingsymbol} @ {fill_price}")
            return order_id
        
        # Live mode - real order
        try:
            order_params = {
                "tradingsymbol": tradingsymbol,
                "exchange": exchange,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "order_type": order_type,
                "product": product,
                "variety": "regular"
            }
            
            if price:
                order_params["price"] = price
            if trigger_price:
                order_params["trigger_price"] = trigger_price
            if tag:
                order_params["tag"] = tag
            
            order_id = self._retry_request(self._kite.place_order, **order_params)
            logger.info(f"[LIVE] ORDER placed: {order_id} - {transaction_type} {quantity} {tradingsymbol}")
            return order_id
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            raise
    
    def _get_token_for_symbol(self, tradingsymbol: str, exchange: str) -> int:
        """Get instrument token for a trading symbol."""
        # This is a simplified lookup - in production, maintain a symbol->token map
        return 0
    
    def modify_order(
        self,
        order_id: str,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        order_type: Optional[str] = None
    ) -> str:
        """Modify an existing order."""
        if self.mock_mode or self.paper_mode:
            if order_id in self._paper_orders:
                if quantity:
                    self._paper_orders[order_id]["quantity"] = quantity
                if price:
                    self._paper_orders[order_id]["price"] = price
            mode = "MOCK" if self.mock_mode else "PAPER"
            logger.info(f"[{mode}] ORDER modified: {order_id}")
            return order_id
        
        try:
            params = {"order_id": order_id, "variety": "regular"}
            if quantity:
                params["quantity"] = quantity
            if price:
                params["price"] = price
            if trigger_price:
                params["trigger_price"] = trigger_price
            if order_type:
                params["order_type"] = order_type
            
            return self._retry_request(self._kite.modify_order, **params)
        except Exception as e:
            logger.error(f"Failed to modify order: {e}")
            raise
    
    def cancel_order(self, order_id: str) -> str:
        """Cancel an order."""
        if self.mock_mode or self.paper_mode:
            if order_id in self._paper_orders:
                self._paper_orders[order_id]["status"] = "CANCELLED"
            mode = "MOCK" if self.mock_mode else "PAPER"
            logger.info(f"[{mode}] ORDER cancelled: {order_id}")
            return order_id
        
        try:
            return self._retry_request(self._kite.cancel_order, variety="regular", order_id=order_id)
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            raise
    
    def get_orders(self) -> List[Dict]:
        """Get all orders for the day."""
        if self.mock_mode or self.paper_mode:
            return list(self._paper_orders.values())
        
        try:
            return self._retry_request(self._kite.orders)
        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
            return []
    
    def get_order_history(self, order_id: str) -> List[Dict]:
        """Get order history for a specific order."""
        if self.mock_mode or self.paper_mode:
            if order_id in self._paper_orders:
                return [self._paper_orders[order_id]]
            return []
        
        try:
            return self._retry_request(self._kite.order_history, order_id)
        except Exception as e:
            logger.error(f"Failed to get order history: {e}")
            return []
    
    def get_positions(self) -> Dict[str, List[Dict]]:
        """Get all positions (day and net)."""
        if self.mock_mode or self.paper_mode:
            # Build positions from paper orders
            positions = []
            for order in self._paper_orders.values():
                if order["status"] == "COMPLETE":
                    positions.append({
                        "tradingsymbol": order["tradingsymbol"],
                        "exchange": order["exchange"],
                        "quantity": order["quantity"] if order["transaction_type"] == "BUY" else -order["quantity"],
                        "average_price": order["average_price"],
                        "product": order["product"],
                        "pnl": 0  # Would need current price to calculate
                    })
            return {"day": positions, "net": positions}
        
        try:
            return self._retry_request(self._kite.positions)
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return {"day": [], "net": []}
    
    def get_holdings(self) -> List[Dict]:
        """Get holdings."""
        if self.mock_mode or self.paper_mode:
            return []  # Paper trading doesn't have holdings
        
        try:
            return self._retry_request(self._kite.holdings)
        except Exception as e:
            logger.error(f"Failed to get holdings: {e}")
            return []
    
    def get_margins(self) -> Dict:
        """Get account margins."""
        if self.mock_mode:
            return {
                "equity": {
                    "available": {"cash": 1000000, "live_balance": 1000000},
                    "utilised": {"debits": 0}
                }
            }
        # Paper mode still fetches real margins for realistic simulation
        
        try:
            return self._retry_request(self._kite.margins)
        except Exception as e:
            logger.error(f"Failed to get margins: {e}")
            return {}
    
    def get_order_margins(self, orders: list) -> list:
        """Calculate margins for a list of orders.
        
        Args:
            orders: List of order dicts with keys:
                - exchange: NSE, NFO, MCX, etc.
                - tradingsymbol: Trading symbol
                - transaction_type: BUY or SELL
                - variety: regular, amo, etc.
                - product: NRML, MIS, CNC
                - order_type: MARKET, LIMIT
                - quantity: Number of shares/lots
                - price: Price (for LIMIT orders)
        
        Returns:
            List of margin details for each order
        """
        if self.mock_mode or not orders:
            return []
        
        try:
            return self._retry_request(self._kite.order_margins, orders)
        except Exception as e:
            logger.error(f"Failed to get order margins: {e}")
            return []
    
    def get_instruments(self, exchange: str = "NFO") -> pd.DataFrame:
        """Get all instruments for an exchange."""
        if self.mock_mode:
            return pd.DataFrame()
        
        try:
            instruments = self._retry_request(self._kite.instruments, exchange)
            return pd.DataFrame(instruments)
        except Exception as e:
            logger.error(f"Failed to get instruments: {e}")
            return pd.DataFrame()
    
    def _is_cache_valid(self) -> bool:
        """Check if quote cache is still valid."""
        if not self._cache_timestamp:
            return False
        return (datetime.now() - self._cache_timestamp).seconds < self._cache_ttl
    
    def _mock_historical_data(
        self,
        from_date: datetime,
        to_date: datetime,
        interval: str
    ) -> pd.DataFrame:
        """Generate mock historical data for testing."""
        import numpy as np
        
        # Determine frequency
        freq_map = {
            "minute": "1min",
            "5minute": "5min",
            "15minute": "15min",
            "day": "1D"
        }
        freq = freq_map.get(interval, "5min")
        
        # Generate date range
        dates = pd.date_range(start=from_date, end=to_date, freq=freq)
        dates = dates[dates.dayofweek < 5]  # Remove weekends
        
        if len(dates) == 0:
            return pd.DataFrame()
        
        # Generate random walk prices
        np.random.seed(42)
        base_price = 22000  # NIFTY-like
        returns = np.random.normal(0, 0.001, len(dates))
        prices = base_price * np.exp(np.cumsum(returns))
        
        df = pd.DataFrame({
            'open': prices * (1 + np.random.uniform(-0.002, 0.002, len(dates))),
            'high': prices * (1 + np.random.uniform(0, 0.005, len(dates))),
            'low': prices * (1 - np.random.uniform(0, 0.005, len(dates))),
            'close': prices,
            'volume': np.random.randint(100000, 1000000, len(dates))
        }, index=dates)
        
        return df
    
    def _mock_quotes(self, instrument_tokens: List[int]) -> Dict[int, Dict]:
        """Generate mock quotes for testing."""
        import numpy as np
        
        result = {}
        for token in instrument_tokens:
            base_price = 22000 if token == 256265 else 100  # NIFTY or option
            price = base_price * (1 + np.random.uniform(-0.01, 0.01))
            
            result[token] = {
                "instrument_token": token,
                "last_price": price,
                "ohlc": {
                    "open": price * 0.999,
                    "high": price * 1.005,
                    "low": price * 0.995,
                    "close": price
                },
                "depth": {
                    "buy": [{"price": price * 0.999, "quantity": 100}],
                    "sell": [{"price": price * 1.001, "quantity": 100}]
                },
                "oi": 1000000,
                "volume": 500000
            }
        
        return result
    
    def _mock_option_chain(self, underlying: str, expiry: date) -> pd.DataFrame:
        """Generate mock option chain for testing."""
        import numpy as np
        
        # Generate strikes around ATM
        atm = 22000 if underlying == "NIFTY" else 48000
        strikes = list(range(atm - 1000, atm + 1000, 50))
        
        rows = []
        for strike in strikes:
            for opt_type in ['CE', 'PE']:
                # Simple mock pricing
                if opt_type == 'CE':
                    intrinsic = max(0, atm - strike)
                else:
                    intrinsic = max(0, strike - atm)
                
                time_value = 50 + np.random.uniform(0, 100)
                ltp = intrinsic + time_value
                
                rows.append({
                    'tradingsymbol': f"{underlying}{expiry.strftime('%y%b').upper()}{strike}{opt_type}",
                    'instrument_token': hash(f"{underlying}{strike}{opt_type}") % 10000000,
                    'strike': strike,
                    'instrument_type': opt_type,
                    'expiry': expiry,
                    'ltp': ltp,
                    'bid': ltp * 0.99,
                    'ask': ltp * 1.01,
                    'oi': np.random.randint(10000, 500000)
                })
        
        return pd.DataFrame(rows)
