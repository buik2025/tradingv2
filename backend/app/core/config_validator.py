"""
Configuration Validator - Fail-fast validation for required environment variables.

Ensures all critical configuration is present before the application starts.
"""

import os
import sys
from typing import List, Tuple, Optional
from loguru import logger


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


# Required environment variables with descriptions
REQUIRED_VARS = [
    ("KITE_API_KEY", "KiteConnect API key from Zerodha developer console"),
    ("KITE_API_SECRET", "KiteConnect API secret from Zerodha developer console"),
]

# Required for production only
PRODUCTION_REQUIRED_VARS = [
    ("DATABASE_URL", "PostgreSQL connection string"),
    ("ENCRYPTION_KEY", "32-byte hex string for credential encryption (generate with: openssl rand -hex 32)"),
]

# Optional but recommended
RECOMMENDED_VARS = [
    ("KITE_ACCESS_TOKEN", "KiteConnect access token (obtained via OAuth)"),
    ("TELEGRAM_BOT_TOKEN", "Telegram bot token for alerts"),
    ("TELEGRAM_CHAT_ID", "Telegram chat ID for alerts"),
]


def validate_config(
    strict: bool = False,
    production: bool = False
) -> Tuple[bool, List[str]]:
    """
    Validate that all required environment variables are set.
    
    Args:
        strict: If True, raise exception on missing vars. If False, return status.
        production: If True, also check production-required vars.
        
    Returns:
        Tuple of (is_valid, list of missing variable names)
        
    Raises:
        ConfigurationError: If strict=True and variables are missing
    """
    missing = []
    warnings = []
    
    # Check required vars
    for var_name, description in REQUIRED_VARS:
        value = os.getenv(var_name)
        if not value:
            missing.append(var_name)
            logger.error(f"Missing required env var: {var_name} - {description}")
    
    # Check production vars
    if production:
        for var_name, description in PRODUCTION_REQUIRED_VARS:
            value = os.getenv(var_name)
            if not value:
                missing.append(var_name)
                logger.error(f"Missing production env var: {var_name} - {description}")
    
    # Check recommended vars (warnings only)
    for var_name, description in RECOMMENDED_VARS:
        value = os.getenv(var_name)
        if not value:
            warnings.append(var_name)
            logger.warning(f"Recommended env var not set: {var_name} - {description}")
    
    is_valid = len(missing) == 0
    
    if not is_valid and strict:
        raise ConfigurationError(
            f"Missing required environment variables: {', '.join(missing)}. "
            f"Please set these in your .env file or environment."
        )
    
    return is_valid, missing


def validate_encryption_key() -> bool:
    """
    Validate that ENCRYPTION_KEY is properly formatted.
    
    Returns:
        True if valid, False otherwise
    """
    key = os.getenv("ENCRYPTION_KEY")
    
    if not key:
        logger.warning("ENCRYPTION_KEY not set - using temporary key (not for production)")
        return False
    
    # Check length (should be 64 hex chars = 32 bytes)
    if len(key) == 64:
        try:
            bytes.fromhex(key)
            return True
        except ValueError:
            logger.error("ENCRYPTION_KEY is not valid hex")
            return False
    elif len(key) == 44:
        # Base64 encoded key
        return True
    else:
        logger.error(f"ENCRYPTION_KEY has wrong length: {len(key)} (expected 64 hex or 44 base64)")
        return False


def validate_database_url() -> bool:
    """
    Validate that DATABASE_URL is properly formatted.
    
    Returns:
        True if valid, False otherwise
    """
    url = os.getenv("DATABASE_URL")
    
    if not url:
        logger.warning("DATABASE_URL not set - using default (not for production)")
        return False
    
    # Basic validation
    if not url.startswith(("postgresql://", "postgres://", "sqlite://")):
        logger.error("DATABASE_URL must start with postgresql://, postgres://, or sqlite://")
        return False
    
    return True


def get_trading_mode() -> str:
    """
    Get the current trading mode.
    
    Returns:
        'paper' or 'live'
    """
    mode = os.getenv("TRADING_MODE", "paper").lower()
    if mode not in ("paper", "live"):
        logger.warning(f"Invalid TRADING_MODE '{mode}', defaulting to 'paper'")
        return "paper"
    return mode


def is_production() -> bool:
    """Check if running in production mode."""
    return get_trading_mode() == "live"


def startup_validation() -> None:
    """
    Run all startup validations.
    
    Called during application startup to ensure configuration is valid.
    Fails fast if critical configuration is missing.
    """
    logger.info("Running startup configuration validation...")
    
    production = is_production()
    
    # Validate required vars
    is_valid, missing = validate_config(strict=False, production=production)
    
    if not is_valid:
        if production:
            # In production, fail immediately
            logger.critical(f"Missing required configuration: {missing}")
            sys.exit(1)
        else:
            # In development, warn but continue
            logger.warning(
                f"Missing configuration: {missing}. "
                "Some features may not work. Set these in .env for full functionality."
            )
    
    # Validate encryption key
    if production and not validate_encryption_key():
        logger.critical("Invalid or missing ENCRYPTION_KEY for production")
        sys.exit(1)
    
    # Validate database URL
    if production and not validate_database_url():
        logger.critical("Invalid or missing DATABASE_URL for production")
        sys.exit(1)
    
    logger.info(f"Configuration validation complete. Mode: {get_trading_mode()}")


def print_config_template() -> None:
    """Print a template .env file with all required variables."""
    print("# Trading System v2.0 Configuration")
    print("# Copy this to .env and fill in your values")
    print()
    print("# === REQUIRED ===")
    for var_name, description in REQUIRED_VARS:
        print(f"# {description}")
        print(f"{var_name}=")
        print()
    
    print("# === PRODUCTION REQUIRED ===")
    for var_name, description in PRODUCTION_REQUIRED_VARS:
        print(f"# {description}")
        print(f"{var_name}=")
        print()
    
    print("# === OPTIONAL ===")
    for var_name, description in RECOMMENDED_VARS:
        print(f"# {description}")
        print(f"# {var_name}=")
        print()
    
    print("# Trading mode: 'paper' or 'live'")
    print("TRADING_MODE=paper")


if __name__ == "__main__":
    # When run directly, print config template
    print_config_template()
