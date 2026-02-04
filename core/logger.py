"""Logging configuration using Loguru for Trading System v2.0"""

import sys
from pathlib import Path
from loguru import logger
from typing import Optional


def setup_logger(
    log_dir: Path = Path("logs"),
    log_level: str = "INFO",
    rotation: str = "10 MB",
    retention: str = "30 days"
) -> None:
    """
    Configure Loguru logger with file and console handlers.
    
    Args:
        log_dir: Directory for log files
        log_level: Minimum log level
        rotation: When to rotate log files
        retention: How long to keep old logs
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Remove default handler
    logger.remove()
    
    # Console handler with colors
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        colorize=True
    )
    
    # Main log file
    logger.add(
        log_dir / "trading_{time:YYYY-MM-DD}.log",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation=rotation,
        retention=retention,
        compression="gz"
    )
    
    # Error-only log file
    logger.add(
        log_dir / "errors_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation=rotation,
        retention=retention,
        compression="gz"
    )
    
    # Trade log (INFO and above, filtered for trade events)
    logger.add(
        log_dir / "trades_{time:YYYY-MM-DD}.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
        rotation="1 day",
        retention="90 days",
        filter=lambda record: "TRADE" in record["message"] or "ORDER" in record["message"]
    )
    
    logger.info("Logger initialized")


def get_logger(name: Optional[str] = None):
    """
    Get a logger instance, optionally bound to a specific name.
    
    Args:
        name: Optional name to bind to the logger
        
    Returns:
        Logger instance
    """
    if name:
        return logger.bind(name=name)
    return logger
