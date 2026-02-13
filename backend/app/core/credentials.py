"""
Kite Credentials Manager

Provides access to Kite API credentials stored in PostgreSQL.
Can be used by any script (collector, backtester, etc.) to get valid credentials.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from loguru import logger
import os

from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker


# Database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/trading"
)


class CredentialsManager:
    """
    Manages Kite API credentials stored in PostgreSQL.
    
    Usage:
        from app.core.credentials import get_kite_credentials
        
        creds = get_kite_credentials()
        if creds:
            api_key = creds['api_key']
            access_token = creds['access_token']
    """
    
    def __init__(self, db_url: str = None):
        self.db_url = db_url or DATABASE_URL
        self._engine = None
        self._Session = None
    
    def _get_session(self):
        """Get database session."""
        if self._engine is None:
            self._engine = create_engine(self.db_url)
            self._Session = sessionmaker(bind=self._engine)
        return self._Session()
    
    def save_credentials(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        user_id: str = None,
        user_name: str = None,
        email: str = None,
        broker: str = "ZERODHA"
    ) -> bool:
        """
        Save Kite credentials to database.
        Replaces any existing credentials (only keeps latest).
        
        Returns True if successful.
        """
        from ..database.models import KiteCredentials, Base
        
        session = self._get_session()
        try:
            # Ensure table exists
            Base.metadata.create_all(self._engine)
            
            # Delete old credentials
            session.query(KiteCredentials).delete()
            
            # Kite tokens expire at 6 AM next day
            now = datetime.now()
            if now.hour >= 6:
                expires_at = (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
            else:
                expires_at = now.replace(hour=6, minute=0, second=0, microsecond=0)
            
            # Create new credentials with encryption
            creds = KiteCredentials(
                api_key=api_key,
                user_id=user_id,
                user_name=user_name,
                email=email,
                broker=broker,
                created_at=now,
                expires_at=expires_at,
                is_valid=True
            )
            # Use setter methods to encrypt sensitive data
            creds.set_api_secret(api_secret)
            creds.set_access_token(access_token)
            session.add(creds)
            session.commit()
            
            logger.info(f"Saved Kite credentials for user: {user_id}, expires: {expires_at}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
            session.rollback()
            return False
        finally:
            session.close()
    
    def get_credentials(self) -> Optional[Dict[str, Any]]:
        """
        Get the latest valid Kite credentials.
        
        Returns dict with api_key, api_secret, access_token, user_id, etc.
        Returns None if no valid credentials found.
        """
        from ..database.models import KiteCredentials, Base
        
        session = self._get_session()
        try:
            # Ensure table exists
            Base.metadata.create_all(self._engine)
            
            # Get latest credentials
            creds = session.query(KiteCredentials).order_by(
                desc(KiteCredentials.created_at)
            ).first()
            
            if not creds:
                logger.warning("No Kite credentials found in database")
                return None
            
            # Check if expired
            now = datetime.now()
            if creds.expires_at and now > creds.expires_at:
                logger.warning(f"Kite credentials expired at {creds.expires_at}")
                return {
                    "api_key": creds.api_key,
                    "api_secret": creds.get_api_secret(),
                    "access_token": creds.get_access_token(),
                    "user_id": creds.user_id,
                    "user_name": creds.user_name,
                    "email": creds.email,
                    "broker": creds.broker,
                    "created_at": creds.created_at.isoformat() if creds.created_at else None,
                    "expires_at": creds.expires_at.isoformat() if creds.expires_at else None,
                    "is_valid": False,
                    "is_expired": True
                }
            
            return {
                "api_key": creds.api_key,
                "api_secret": creds.get_api_secret(),
                "access_token": creds.get_access_token(),
                "user_id": creds.user_id,
                "user_name": creds.user_name,
                "email": creds.email,
                "broker": creds.broker,
                "created_at": creds.created_at.isoformat() if creds.created_at else None,
                "expires_at": creds.expires_at.isoformat() if creds.expires_at else None,
                "is_valid": creds.is_valid,
                "is_expired": False
            }
            
        except Exception as e:
            logger.error(f"Failed to get credentials: {e}")
            return None
        finally:
            session.close()
    
    def invalidate_credentials(self) -> bool:
        """Mark current credentials as invalid."""
        from ..database.models import KiteCredentials
        
        session = self._get_session()
        try:
            session.query(KiteCredentials).update({"is_valid": False})
            session.commit()
            logger.info("Invalidated Kite credentials")
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate credentials: {e}")
            session.rollback()
            return False
        finally:
            session.close()


# Singleton instance
_credentials_manager: Optional[CredentialsManager] = None


def get_credentials_manager() -> CredentialsManager:
    """Get the singleton credentials manager."""
    global _credentials_manager
    if _credentials_manager is None:
        _credentials_manager = CredentialsManager()
    return _credentials_manager


def get_kite_credentials() -> Optional[Dict[str, Any]]:
    """
    Convenience function to get Kite credentials.
    
    Usage:
        from app.core.credentials import get_kite_credentials
        
        creds = get_kite_credentials()
        if creds and not creds.get('is_expired'):
            kite = KiteClient(
                api_key=creds['api_key'],
                access_token=creds['access_token']
            )
    """
    return get_credentials_manager().get_credentials()


def save_kite_credentials(
    api_key: str,
    api_secret: str,
    access_token: str,
    user_id: str = None,
    user_name: str = None,
    email: str = None
) -> bool:
    """Convenience function to save Kite credentials."""
    return get_credentials_manager().save_credentials(
        api_key=api_key,
        api_secret=api_secret,
        access_token=access_token,
        user_id=user_id,
        user_name=user_name,
        email=email
    )
