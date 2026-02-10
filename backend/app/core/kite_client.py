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
        # Basket margins cache
        self._basket_margin_cache: Dict[str, Dict] = {}
        self._basket_cache_ttl = 300  # seconds
        
        # Instruments cache (refresh once per day)
        self._instruments_cache: Dict[str, pd.DataFrame] = {}
        self._instruments_cache_timestamp: Optional[datetime] = None
        self._instruments_cache_ttl = 3600  # 1 hour
        
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
    
    def refresh_session(self) -> bool:
        """
        Attempt to refresh session from database credentials.
        Returns True if successful.
        """
        try:
            # Import here to avoid circular dependency
            from .credentials import get_kite_credentials
            
            creds = get_kite_credentials()
            if not creds:
                logger.warning("No credentials found in database during refresh")
                return False
                
            if creds.get('is_expired'):
                logger.warning("Database credentials are also expired")
                return False
                
            new_token = creds.get('access_token')
            if not new_token or new_token == self.access_token:
                logger.info("Database has same token, skipping refresh")
                return False
                
            # Update token
            self.access_token = new_token
            if self._kite:
                self._kite.set_access_token(self.access_token)
            
            logger.info(f"Refreshed access token from database (user: {creds.get('user_id')})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to refresh session: {e}")
            return False

    def _retry_request(self, func, *args, **kwargs) -> Any:
        """Execute a request with retry logic."""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except TokenException as e:
                # Token expired - try to refresh from DB
                logger.warning(f"Token expired: {e}. Attempting refresh from DB...")
                if self.refresh_session():
                    continue  # Retry with new token
                
                logger.error(f"Token refresh failed or token invalid: {e}")
                raise TokenExpiredException(str(e))
                
            except Exception as e:
                error_str = str(e).lower()
                # Check for token-related errors in message
                if "api_key" in error_str or "access_token" in error_str or "token" in error_str:
                    logger.warning(f"Token error detected: {e}. Attempting refresh from DB...")
                    if self.refresh_session():
                        continue
                        
                    logger.error(f"Token refresh failed: {e}")
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
            # Get instruments for the underlying (use cached version to avoid rate limits)
            df = self.get_instruments("NFO")
            if df.empty:
                logger.warning("Empty instruments list from cache")
                return pd.DataFrame()
            
            # Filter for options - use .copy() to avoid SettingWithCopyWarning
            df = df[
                (df['name'] == underlying) &
                (df['instrument_type'].isin(['CE', 'PE'])) &
                (df['expiry'] == expiry)
            ].copy()
            
            if strike_range:
                df = df[(df['strike'] >= strike_range[0]) & (df['strike'] <= strike_range[1])].copy()
            
            # Get quotes for all options
            tokens = df['instrument_token'].tolist()
            if tokens:
                quotes = self.get_quote(tokens)
                df.loc[:, 'ltp'] = df['instrument_token'].map(lambda t: quotes.get(t, {}).get('last_price', 0))
                df.loc[:, 'bid'] = df['instrument_token'].map(lambda t: quotes.get(t, {}).get('depth', {}).get('buy', [{}])[0].get('price', 0))
                df.loc[:, 'ask'] = df['instrument_token'].map(lambda t: quotes.get(t, {}).get('depth', {}).get('sell', [{}])[0].get('price', 0))
                df.loc[:, 'oi'] = df['instrument_token'].map(lambda t: quotes.get(t, {}).get('oi', 0))
            
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
            
            # Get current market price
            market_price = price or 0
            if self._kite and not self.mock_mode:
                try:
                    quote = self.get_ltp([self._get_token_for_symbol(tradingsymbol, exchange)])
                    if quote:
                        market_price = list(quote.values())[0]
                except:
                    pass
            
            # Determine fill behavior based on order type
            if order_type == "MARKET":
                # Market orders fill immediately at market price
                fill_price = market_price or price or 0
                status = "COMPLETE"
                filled_quantity = quantity
                pending_quantity = 0
            elif order_type == "LIMIT":
                # Limit orders: check if price is favorable for immediate fill
                # BUY limit fills if market <= limit price
                # SELL limit fills if market >= limit price
                can_fill = False
                if market_price and price:
                    if transaction_type == "BUY" and market_price <= price:
                        can_fill = True
                    elif transaction_type == "SELL" and market_price >= price:
                        can_fill = True
                
                if can_fill:
                    fill_price = price  # Fill at limit price
                    status = "COMPLETE"
                    filled_quantity = quantity
                    pending_quantity = 0
                else:
                    # Order stays open, waiting for price to reach limit
                    fill_price = None
                    status = "OPEN"
                    filled_quantity = 0
                    pending_quantity = quantity
            else:
                # SL, SL-M orders - treat as open for now
                fill_price = None
                status = "OPEN"
                filled_quantity = 0
                pending_quantity = quantity
            
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
                "trigger_price": trigger_price,
                "average_price": fill_price,
                "status": status,
                "filled_quantity": filled_quantity,
                "pending_quantity": pending_quantity,
                "order_timestamp": datetime.now(),
                "tag": tag,
                "instrument_token": self._get_token_for_symbol(tradingsymbol, exchange)
            }
            
            mode = "MOCK" if self.mock_mode else "PAPER"
            status_str = f"@ {fill_price}" if status == "COMPLETE" else f"PENDING @ {price}"
            logger.info(f"[{mode}] ORDER placed: {order_id} - {transaction_type} {quantity} {tradingsymbol} {status_str}")
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
                # For paper orders, check if pending limit orders can now be filled
                self._update_paper_order_status(order_id)
                return [self._paper_orders[order_id]]
            return []
    
    def _update_paper_order_status(self, order_id: str) -> None:
        """
        Update paper order status based on current market price.
        
        For LIMIT orders that are OPEN, check if market price has reached
        the limit price and fill them accordingly.
        """
        if order_id not in self._paper_orders:
            return
        
        order = self._paper_orders[order_id]
        
        # Only process OPEN orders
        if order.get("status") != "OPEN":
            return
        
        order_type = order.get("order_type")
        if order_type not in ["LIMIT", "SL", "SL-M"]:
            return
        
        # Get current market price
        instrument_token = order.get("instrument_token")
        tradingsymbol = order.get("tradingsymbol")
        exchange = order.get("exchange", "NFO")
        
        market_price = None
        if self._kite and not self.mock_mode:
            try:
                quote = self.get_ltp([instrument_token] if instrument_token else [])
                if quote:
                    market_price = list(quote.values())[0]
            except:
                pass
        
        if not market_price:
            return
        
        limit_price = order.get("price")
        trigger_price = order.get("trigger_price")
        transaction_type = order.get("transaction_type")
        
        can_fill = False
        
        if order_type == "LIMIT" and limit_price:
            # BUY limit fills if market <= limit price
            # SELL limit fills if market >= limit price
            if transaction_type == "BUY" and market_price <= limit_price:
                can_fill = True
            elif transaction_type == "SELL" and market_price >= limit_price:
                can_fill = True
        elif order_type in ["SL", "SL-M"] and trigger_price:
            # SL BUY triggers if market >= trigger price
            # SL SELL triggers if market <= trigger price
            if transaction_type == "BUY" and market_price >= trigger_price:
                can_fill = True
            elif transaction_type == "SELL" and market_price <= trigger_price:
                can_fill = True
        
        if can_fill:
            fill_price = limit_price if order_type == "LIMIT" else market_price
            order["status"] = "COMPLETE"
            order["average_price"] = fill_price
            order["filled_quantity"] = order["quantity"]
            order["pending_quantity"] = 0
            logger.info(f"[PAPER] ORDER filled: {order_id} - {transaction_type} {order['quantity']} {tradingsymbol} @ {fill_price}")
        
        try:
            return self._retry_request(self._kite.order_history, order_id)
        except Exception as e:
            logger.error(f"Failed to get order history: {e}")
            return []
    
    def poll_paper_orders(self) -> int:
        """
        Poll all open paper orders and update their status based on market prices.
        
        Returns:
            Number of orders that were filled
        """
        if not (self.mock_mode or self.paper_mode):
            return 0
        
        filled_count = 0
        open_orders = [oid for oid, o in self._paper_orders.items() if o.get("status") == "OPEN"]
        
        for order_id in open_orders:
            old_status = self._paper_orders[order_id].get("status")
            self._update_paper_order_status(order_id)
            if self._paper_orders[order_id].get("status") == "COMPLETE" and old_status == "OPEN":
                filled_count += 1
        
        return filled_count
    
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

    def get_basket_margins(self, basket: dict) -> dict:
        """Get margins for a basket (single payload) with caching and fallbacks.

        Args:
            basket: Dict describing the basket/order payload expected by Kite's
                    basket_order_margins API (list of orders under a key like 'orders').

        Returns:
            Dict with margin details or empty dict on error.
        """
        if not basket:
            return {}

        # Cache key based on stringified basket
        try:
            import json
            key = json.dumps(basket, sort_keys=True)
        except Exception:
            key = str(basket)

        # Check cache
        cached = self._basket_margin_cache.get(key)
        if cached:
            ts = cached.get("_ts")
            if ts and (datetime.now() - ts).seconds < self._basket_cache_ttl:
                return cached.get("value", {})

        if self.mock_mode:
            # Return a conservative mock margin for testing
            resp = {"required_margin": 100000, "details": []}
            self._basket_margin_cache[key] = {"_ts": datetime.now(), "value": resp}
            return resp

        # Prefer `basket_order_margins` if available on Kite SDK
        try:
            if hasattr(self._kite, "basket_order_margins"):
                try:
                    resp = self._retry_request(self._kite.basket_order_margins, basket)
                except Exception as e:
                    logger.warning(f"basket_order_margins failed: {e} - attempting order_margins fallback")
                    orders = basket.get("orders") or basket.get("orders_payload") or []
                    if orders:
                        try:
                            resp = self._retry_request(self._kite.order_margins, orders)
                        except Exception as e2:
                            logger.error(f"order_margins fallback also failed: {e2}")
                            raise
                    else:
                        raise
            else:
                # Fallback: use order_margins with the orders list if present
                orders = basket.get("orders") or basket.get("orders_payload") or []
                if orders:
                    resp = self._retry_request(self._kite.order_margins, orders)
                else:
                    resp = {}

            # Cache and return
            self._basket_margin_cache[key] = {"_ts": datetime.now(), "value": resp}
            return resp

        except TokenException as e:
            logger.warning(f"Token error while fetching basket margins: {e}")
            # Try refresh once via existing logic
            try:
                if self.refresh_session():
                    if hasattr(self._kite, "basket_order_margins"):
                        resp = self._retry_request(self._kite.basket_order_margins, basket)
                        self._basket_margin_cache[key] = {"_ts": datetime.now(), "value": resp}
                        return resp
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Failed to get basket margins: {e}")

        # Final fallback: return empty dict
        return {}
    
    def get_instruments(self, exchange: str = "NFO") -> pd.DataFrame:
        """Get all instruments for an exchange (cached to avoid rate limits)."""
        if self.mock_mode:
            return pd.DataFrame()
        
        # Check cache first
        cache_valid = (
            self._instruments_cache_timestamp and 
            (datetime.now() - self._instruments_cache_timestamp).seconds < self._instruments_cache_ttl and
            exchange in self._instruments_cache and
            not self._instruments_cache[exchange].empty
        )
        
        if cache_valid:
            logger.debug(f"Using cached instruments for {exchange}")
            return self._instruments_cache[exchange]
        
        try:
            logger.info(f"Fetching instruments for {exchange} from API...")
            instruments = self._retry_request(self._kite.instruments, exchange)
            df = pd.DataFrame(instruments)
            
            # Cache the result
            self._instruments_cache[exchange] = df
            self._instruments_cache_timestamp = datetime.now()
            logger.info(f"Cached {len(df)} instruments for {exchange}")
            
            return df
        except Exception as e:
            logger.error(f"Failed to get instruments: {e}")
            # Return cached data if available, even if stale
            if exchange in self._instruments_cache:
                logger.warning(f"Returning stale cached instruments for {exchange}")
                return self._instruments_cache[exchange]
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
