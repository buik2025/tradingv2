"""
Credentials Encryption Module - Secure storage for API secrets.

Uses Fernet symmetric encryption for:
- API secrets
- Access tokens
- Other sensitive credentials

Requires ENCRYPTION_KEY environment variable (32-byte hex string).
Generate with: openssl rand -hex 32
"""

import os
import base64
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


class CredentialsEncryption:
    """
    Handles encryption and decryption of sensitive credentials.
    
    Usage:
        encryption = CredentialsEncryption()
        
        # Encrypt
        encrypted = encryption.encrypt("my_secret_api_key")
        
        # Decrypt
        decrypted = encryption.decrypt(encrypted)
    """
    
    ENV_KEY_NAME = "ENCRYPTION_KEY"
    
    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize encryption with key from environment or parameter.
        
        Args:
            encryption_key: Optional 32-byte hex string. If not provided,
                           reads from ENCRYPTION_KEY environment variable.
        
        Raises:
            EncryptionError: If no valid encryption key is available.
        """
        key = encryption_key or os.getenv(self.ENV_KEY_NAME)
        
        if not key:
            # In development, generate a temporary key with warning
            logger.warning(
                f"No {self.ENV_KEY_NAME} found. Using temporary key. "
                "Set ENCRYPTION_KEY in .env for production!"
            )
            key = Fernet.generate_key().decode()
            self._is_temporary = True
        else:
            self._is_temporary = False
        
        try:
            # Convert hex key to Fernet-compatible base64 key
            if len(key) == 64:  # 32-byte hex string
                key_bytes = bytes.fromhex(key)
                fernet_key = base64.urlsafe_b64encode(key_bytes)
            elif len(key) == 44:  # Already base64 encoded
                fernet_key = key.encode()
            else:
                raise EncryptionError(
                    f"Invalid key length. Expected 64 hex chars or 44 base64 chars, got {len(key)}"
                )
            
            self._fernet = Fernet(fernet_key)
            
        except Exception as e:
            raise EncryptionError(f"Failed to initialize encryption: {e}")
    
    @property
    def is_temporary_key(self) -> bool:
        """Check if using a temporary (non-persistent) key."""
        return self._is_temporary
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a string.
        
        Args:
            plaintext: String to encrypt
            
        Returns:
            Base64-encoded encrypted string
            
        Raises:
            EncryptionError: If encryption fails
        """
        if not plaintext:
            return ""
        
        try:
            encrypted = self._fernet.encrypt(plaintext.encode())
            return encrypted.decode()
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}")
    
    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a string.
        
        Args:
            ciphertext: Base64-encoded encrypted string
            
        Returns:
            Decrypted plaintext string
            
        Raises:
            EncryptionError: If decryption fails (wrong key or corrupted data)
        """
        if not ciphertext:
            return ""
        
        try:
            decrypted = self._fernet.decrypt(ciphertext.encode())
            return decrypted.decode()
        except InvalidToken:
            raise EncryptionError(
                "Decryption failed: Invalid token. "
                "This may indicate wrong encryption key or corrupted data."
            )
        except Exception as e:
            raise EncryptionError(f"Decryption failed: {e}")
    
    def is_encrypted(self, value: str) -> bool:
        """
        Check if a value appears to be encrypted.
        
        Args:
            value: String to check
            
        Returns:
            True if value looks like Fernet-encrypted data
        """
        if not value or len(value) < 50:
            return False
        
        # Fernet tokens start with 'gAAAAA' (base64 of version + timestamp)
        return value.startswith('gAAAAA')


# Singleton instance
_encryption_instance: Optional[CredentialsEncryption] = None


def get_encryption() -> CredentialsEncryption:
    """Get singleton encryption instance."""
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = CredentialsEncryption()
    return _encryption_instance


def encrypt_credential(plaintext: str) -> str:
    """Convenience function to encrypt a credential."""
    return get_encryption().encrypt(plaintext)


def decrypt_credential(ciphertext: str) -> str:
    """Convenience function to decrypt a credential."""
    return get_encryption().decrypt(ciphertext)
