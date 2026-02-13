"""
KiteClientProvider - THE SINGLE SOURCE OF TRUTH for KiteClient instances.

This is the ONLY way to get a KiteClient in the application. It:
1. Manages credentials from the database
2. Caches KiteClient instances for the trading day
3. Validates credentials both locally and via Kite API
4. Handles token expiry and refresh

Usage:
    from app.core.kite_provider import get_kite_client
    
    # Get the shared KiteClient instance
    kite = get_kite_client()  # Returns KiteClient in live mode
    kite = get_kite_client(paper_mode=True)  # Returns KiteClient in paper mode
"""

from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any
from loguru import logger
import threading

from .kite_client import KiteClient
from .credentials import get_kite_credentials, save_kite_credentials


class KiteClientProvider:
    """
    THE SINGLE SOURCE OF TRUTH for KiteClient instances.
    
    This singleton provider:
    1. Gets credentials from PostgreSQL database
    2. Caches KiteClient instances (live and paper) for the trading day
    3. Validates credentials using local expiry check AND Kite API profile call
    4. Automatically invalidates on token expiry
    5. Provides the initial client after OAuth login
    
    IMPORTANT: All code should use get_kite_client() to obtain a KiteClient.
    Never instantiate KiteClient directly.
    """
    
    _instance: Optional['KiteClientProvider'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._live_client: Optional[KiteClient] = None
        self._paper_client: Optional[KiteClient] = None
        self._credentials: Optional[Dict[str, Any]] = None
        self._credentials_date: Optional[date] = None
        self._expires_at: Optional[datetime] = None
        self._last_api_validation: Optional[datetime] = None
        self._api_validation_interval = timedelta(minutes=5)  # Check API every 5 mins
        self._client_lock = threading.Lock()
        self._initialized = True
        
        logger.info("KiteClientProvider initialized - THE SINGLE SOURCE for KiteClient")
    
    def _is_locally_valid(self) -> bool:
        """
        Check if credentials are valid based on local expiry time.
        
        Returns True if credentials exist and haven't expired locally.
        """
        if not self._credentials:
            return False
        
        # Check explicit expiry flag
        if self._credentials.get('is_expired', True):
            return False
        
        # Check expiry timestamp
        if self._expires_at:
            now = datetime.now()
            if now >= self._expires_at:
                logger.warning(f"Credentials expired at {self._expires_at}")
                self._credentials['is_expired'] = True
                return False
        
        return True
    
    def _validate_with_kite_api(self, client: KiteClient) -> bool:
        """
        Validate credentials by calling Kite API (profile endpoint).
        
        This is the definitive check - if Kite API rejects the token,
        it's invalid regardless of local expiry time.
        
        Returns True if the token is valid with Kite.
        """
        if client.mock_mode:
            return True  # Mock mode doesn't need API validation
        
        # Rate limit API validation checks
        now = datetime.now()
        if self._last_api_validation:
            if now - self._last_api_validation < self._api_validation_interval:
                return True  # Skip if recently validated
        
        try:
            # Use Kite's profile() method to validate token
            # This is a lightweight call that confirms token validity
            if hasattr(client, '_kite') and client._kite:
                profile = client._kite.profile()
                if profile and profile.get('user_id'):
                    self._last_api_validation = now
                    logger.debug(f"Kite API validation successful for user: {profile.get('user_id')}")
                    return True
        except Exception as e:
            error_str = str(e).lower()
            if 'token' in error_str or 'api_key' in error_str or 'access_token' in error_str:
                logger.error(f"Kite API token validation failed: {e}")
                self._invalidate_credentials()
                return False
            # Other errors (network, etc.) - don't invalidate, just log
            logger.warning(f"Kite API validation check failed (non-token error): {e}")
        
        return True  # Assume valid if we can't check (network issues, etc.)
    
    def _invalidate_credentials(self) -> None:
        """Mark credentials as invalid and clear cached clients."""
        if self._credentials:
            self._credentials['is_expired'] = True
        self._live_client = None
        self._paper_client = None
        self._last_api_validation = None
        logger.warning("Credentials invalidated - clients cleared")
    
    def _refresh_credentials(self) -> bool:
        """
        Refresh credentials from database if needed.
        
        Returns True if valid credentials are available.
        """
        today = date.today()
        
        # Check if we already have valid credentials for today
        if self._credentials_date == today and self._is_locally_valid():
            return True
        
        # New day or no credentials - fetch from database
        logger.info("Fetching Kite credentials from database...")
        creds = get_kite_credentials()
        
        if not creds:
            logger.error("No Kite credentials found in database")
            return False
        
        # Parse expiry time
        expires_at_str = creds.get('expires_at')
        if expires_at_str:
            try:
                if isinstance(expires_at_str, str):
                    self._expires_at = datetime.fromisoformat(expires_at_str)
                elif isinstance(expires_at_str, datetime):
                    self._expires_at = expires_at_str
            except:
                self._expires_at = None
        
        # Check if already expired
        if creds.get('is_expired', True):
            logger.warning(f"Kite credentials expired at {creds.get('expires_at')}")
            self._credentials = creds
            self._credentials_date = today
            return False
        
        self._credentials = creds
        self._credentials_date = today
        self._last_api_validation = None  # Reset API validation on new credentials
        logger.info(f"Loaded valid Kite credentials for user: {creds.get('user_id')}, expires: {self._expires_at}")
        return True
    
    def _create_client(self, paper_mode: bool = False, mock_mode: bool = False) -> Optional[KiteClient]:
        """Create a new KiteClient instance with current credentials."""
        if not self._credentials:
            if not self._refresh_credentials():
                logger.error("Cannot create KiteClient - no valid credentials")
                return None
        
        api_key = self._credentials.get('api_key')
        access_token = self._credentials.get('access_token')
        
        if not api_key or not access_token:
            logger.error("Invalid credentials - missing api_key or access_token")
            return None
        
        try:
            client = KiteClient(
                api_key=api_key,
                access_token=access_token,
                paper_mode=paper_mode,
                mock_mode=mock_mode
            )
            mode = "MOCK" if mock_mode else ("PAPER" if paper_mode else "LIVE")
            logger.info(f"Created KiteClient in {mode} mode")
            return client
        except Exception as e:
            logger.error(f"Failed to create KiteClient: {e}")
            return None
    
    def get_client(self, paper_mode: bool = False, mock_mode: bool = False, skip_api_check: bool = False) -> Optional[KiteClient]:
        """
        Get a KiteClient instance.
        
        This is THE ONLY way to get a KiteClient in the application.
        
        Performs:
        1. Local validity check (expiry time)
        2. Kite API validity check (profile call) - unless skip_api_check=True
        3. Returns cached instance or creates new one
        
        Args:
            paper_mode: If True, returns a paper trading client
            mock_mode: If True, returns a mock client (for testing)
            skip_api_check: If True, skip Kite API validation (for performance)
            
        Returns:
            KiteClient instance or None if credentials are unavailable/invalid
        """
        with self._client_lock:
            # Step 1: Refresh credentials from DB if needed
            if not self._refresh_credentials():
                logger.error("No valid credentials available")
                return None
            
            # Step 2: Check local validity
            if not self._is_locally_valid():
                logger.error("Credentials failed local validity check")
                return None
            
            # Step 3: Check if we need to recreate clients (new day)
            today = date.today()
            if self._credentials_date != today:
                logger.info("New trading day - recreating KiteClient instances")
                self._live_client = None
                self._paper_client = None
                self._last_api_validation = None
            
            # Step 4: Get or create the appropriate client
            if mock_mode:
                # Mock clients are always created fresh
                return self._create_client(paper_mode=paper_mode, mock_mode=True)
            
            if paper_mode:
                if self._paper_client is None:
                    self._paper_client = self._create_client(paper_mode=True)
                client = self._paper_client
            else:
                if self._live_client is None:
                    self._live_client = self._create_client(paper_mode=False)
                client = self._live_client
            
            # Step 5: Validate with Kite API (unless skipped)
            if client and not skip_api_check and not mock_mode:
                if not self._validate_with_kite_api(client):
                    logger.error("Credentials failed Kite API validation")
                    return None
            
            return client
    
    def set_credentials_from_login(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        user_id: str = None,
        user_name: str = None,
        email: str = None
    ) -> Optional[KiteClient]:
        """
        Set credentials after OAuth login and return the new client.
        
        This should be called from the OAuth callback after successful login.
        It saves credentials to database and creates the initial KiteClient.
        
        Args:
            api_key: Kite API key
            api_secret: Kite API secret
            access_token: Access token from OAuth
            user_id: Kite user ID
            user_name: User's name
            email: User's email
            
        Returns:
            The newly created KiteClient or None on failure
        """
        with self._client_lock:
            # Save to database
            success = save_kite_credentials(
                api_key=api_key,
                api_secret=api_secret,
                access_token=access_token,
                user_id=user_id,
                user_name=user_name,
                email=email
            )
            
            if not success:
                logger.error("Failed to save credentials to database")
                return None
            
            # Clear cached state to force refresh
            self._credentials = None
            self._credentials_date = None
            self._live_client = None
            self._paper_client = None
            self._last_api_validation = None
            
            # Refresh from database and create client
            if self._refresh_credentials():
                client = self._create_client(paper_mode=False)
                if client:
                    self._live_client = client
                    # Validate immediately
                    if self._validate_with_kite_api(client):
                        logger.info(f"Login successful - KiteClient created for user: {user_id}")
                        return client
                    else:
                        logger.error("Login credentials failed API validation")
                        return None
            
            return None
    
    def invalidate(self) -> None:
        """Invalidate all cached clients and credentials."""
        with self._client_lock:
            self._live_client = None
            self._paper_client = None
            self._credentials = None
            self._credentials_date = None
            self._expires_at = None
            self._last_api_validation = None
            logger.info("Invalidated all cached KiteClient instances and credentials")
    
    def get_credentials_info(self) -> Dict[str, Any]:
        """Get information about current credentials (for debugging/status)."""
        with self._client_lock:
            self._refresh_credentials()
            
            if not self._credentials:
                return {"status": "no_credentials"}
            
            return {
                "status": "valid" if self._is_locally_valid() else "expired",
                "user_id": self._credentials.get('user_id'),
                "created_at": self._credentials.get('created_at'),
                "expires_at": str(self._expires_at) if self._expires_at else None,
                "is_expired": self._credentials.get('is_expired', True),
                "has_live_client": self._live_client is not None,
                "has_paper_client": self._paper_client is not None,
                "last_api_validation": str(self._last_api_validation) if self._last_api_validation else None
            }


# Module-level singleton instance
_provider: Optional[KiteClientProvider] = None


def get_kite_provider() -> KiteClientProvider:
    """Get the singleton KiteClientProvider instance."""
    global _provider
    if _provider is None:
        _provider = KiteClientProvider()
    return _provider


def get_kite_client(paper_mode: bool = False, mock_mode: bool = False, skip_api_check: bool = False) -> Optional[KiteClient]:
    """
    THE ONLY WAY to get a KiteClient instance in the application.
    
    This function:
    1. Gets credentials from database
    2. Validates locally (expiry time)
    3. Validates with Kite API (profile call)
    4. Returns cached or new client
    
    Args:
        paper_mode: If True, returns a paper trading client
        mock_mode: If True, returns a mock client (for testing)
        skip_api_check: If True, skip Kite API validation (for performance)
        
    Returns:
        KiteClient instance or None if credentials are unavailable/invalid
        
    Usage:
        from app.core.kite_provider import get_kite_client
        
        # Get live trading client
        kite = get_kite_client()
        
        # Get paper trading client
        kite = get_kite_client(paper_mode=True)
        
        # Skip API check for high-frequency calls
        kite = get_kite_client(skip_api_check=True)
    """
    return get_kite_provider().get_client(
        paper_mode=paper_mode, 
        mock_mode=mock_mode,
        skip_api_check=skip_api_check
    )


def set_kite_credentials_from_login(
    api_key: str,
    api_secret: str,
    access_token: str,
    user_id: str = None,
    user_name: str = None,
    email: str = None
) -> Optional[KiteClient]:
    """
    Set credentials after OAuth login and get the new client.
    
    This should be called from the OAuth callback after successful login.
    It saves credentials to database and creates the initial KiteClient.
    
    Args:
        api_key: Kite API key
        api_secret: Kite API secret
        access_token: Access token from OAuth
        user_id: Kite user ID
        user_name: User's name
        email: User's email
        
    Returns:
        The newly created KiteClient or None on failure
    """
    return get_kite_provider().set_credentials_from_login(
        api_key=api_key,
        api_secret=api_secret,
        access_token=access_token,
        user_id=user_id,
        user_name=user_name,
        email=email
    )


def invalidate_kite_clients() -> None:
    """Invalidate all cached KiteClient instances and credentials."""
    get_kite_provider().invalidate()


def get_kite_credentials_status() -> Dict[str, Any]:
    """Get current credentials status for debugging/monitoring."""
    return get_kite_provider().get_credentials_info()
