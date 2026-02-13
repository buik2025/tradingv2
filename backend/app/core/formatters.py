"""
Common formatters for consistent decimal precision across the platform.
All currency and percentage values should use these formatters.
"""

from typing import Union


def format_currency(value: Union[float, int, None], decimals: int = 2) -> float:
    """
    Format a currency value with specified decimal places.
    
    Args:
        value: The numeric value to format
        decimals: Number of decimal places (default: 2)
    
    Returns:
        Rounded float value
    """
    if value is None:
        return 0.0
    return round(float(value), decimals)


def format_percent(value: Union[float, int, None], decimals: int = 2) -> float:
    """
    Format a percentage value with specified decimal places.
    
    Args:
        value: The numeric value to format
        decimals: Number of decimal places (default: 2)
    
    Returns:
        Rounded float value
    """
    if value is None:
        return 0.0
    return round(float(value), decimals)


def format_price(value: Union[float, int, None], decimals: int = 2) -> float:
    """
    Format a price value with specified decimal places.
    
    Args:
        value: The numeric value to format
        decimals: Number of decimal places (default: 2)
    
    Returns:
        Rounded float value
    """
    if value is None:
        return 0.0
    return round(float(value), decimals)


def format_quantity(value: Union[float, int, None]) -> int:
    """
    Format a quantity value as integer.
    
    Args:
        value: The numeric value to format
    
    Returns:
        Integer value
    """
    if value is None:
        return 0
    return int(value)
