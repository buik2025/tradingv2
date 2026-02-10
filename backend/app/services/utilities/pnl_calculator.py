"""P&L Calculator Service.

Provides accurate P&L calculations for:
- Equity (stocks)
- Futures
- Options (CE/PE)

Uses lot sizes and multipliers from instrument cache.
Backend is the source of truth for all P&L calculations.
"""

from typing import Dict, List, Optional, Any
from decimal import Decimal
from loguru import logger

from .instrument_cache import instrument_cache


class PnLCalculator:
    """Calculate P&L for positions and strategies.
    
    Key concepts:
    - For equity: P&L = (LTP - avg_price) * quantity
    - For NFO F&O: Kite returns quantity in actual units, P&L = (LTP - avg) * quantity
    - For MCX: Kite returns quantity in LOTS, P&L = (LTP - avg) * quantity * multiplier
    
    MCX Multipliers (units per lot) - NOT provided by Kite API:
    - GOLDM: 10 grams per lot
    - SILVERM: 5 kg per lot  
    - GOLD: 100 grams per lot
    - SILVER: 30 kg per lot
    - CRUDEOIL: 100 barrels per lot
    - NATURALGAS: 1250 mmBtu per lot
    """
    
    # MCX commodity multipliers (units per lot)
    # These are NOT provided by Kite's instrument master
    MCX_MULTIPLIERS = {
        "GOLDM": 10,       # 10 grams per lot
        "GOLD": 100,       # 100 grams per lot
        "SILVERM": 5,      # 5 kg per lot
        "SILVER": 30,      # 30 kg per lot
        "CRUDEOIL": 100,   # 100 barrels per lot
        "NATURALGAS": 1250, # 1250 mmBtu per lot
        "COPPER": 2500,    # 2500 kg per lot
        "ZINC": 5000,      # 5000 kg per lot
        "LEAD": 5000,      # 5000 kg per lot
        "ALUMINIUM": 5000, # 5000 kg per lot
        "NICKEL": 1500,    # 1500 kg per lot
    }
    
    @staticmethod
    def _get_mcx_multiplier(tradingsymbol: str) -> int:
        """Get MCX multiplier for a commodity symbol.
        
        Extracts the base commodity name from tradingsymbol and returns multiplier.
        E.g., GOLDM26MARFUT -> GOLDM -> 10
        """
        # Extract base commodity name (before expiry/strike info)
        for commodity, multiplier in PnLCalculator.MCX_MULTIPLIERS.items():
            if tradingsymbol.startswith(commodity):
                return multiplier
        
        # Default to 1 if unknown commodity
        logger.warning(f"Unknown MCX commodity: {tradingsymbol}, using multiplier=1")
        return 1
    
    @staticmethod
    def calculate_position_pnl(
        instrument_token: int,
        quantity: int,
        average_price: float,
        last_price: float,
        exchange: str = "NFO"
    ) -> Dict[str, float]:
        """Calculate P&L for a single position.
        
        Args:
            instrument_token: Kite instrument token
            quantity: Position quantity (positive for long, negative for short)
            average_price: Entry average price
            last_price: Current market price (LTP)
            exchange: Exchange (NSE, NFO, MCX, etc.)
            
        Returns:
            Dict with pnl, pnl_pct, and metadata
        """
        if quantity == 0 or average_price == 0:
            return {
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "investment": 0.0,
                "current_value": 0.0,
                "lot_size": 1,
                "multiplier": 1,
                "instrument_type": "EQ"
            }
        
        # Get instrument info
        inst = instrument_cache.get(instrument_token)
        lot_size = inst.get("lot_size", 1) if inst else 1
        inst_type = inst.get("instrument_type", "EQ") if inst else "EQ"
        tradingsymbol = inst.get("tradingsymbol", "") if inst else ""
        
        # Determine multiplier based on exchange
        # MCX: Kite's lot_size=1, but actual multiplier depends on commodity
        # NFO/NSE: quantity is in actual units
        if exchange == "MCX":
            # MCX multipliers (units per lot) - Kite doesn't provide these
            multiplier = PnLCalculator._get_mcx_multiplier(tradingsymbol)
        else:
            # NFO/NSE returns quantity in actual units
            multiplier = 1
        
        # Calculate P&L
        pnl = (last_price - average_price) * quantity * multiplier
        
        # Calculate investment value (for P&L %)
        investment = average_price * abs(quantity) * multiplier
        
        # P&L percentage
        pnl_pct = (pnl / investment * 100) if investment > 0 else 0.0
        
        # Current value
        current_value = last_price * quantity * multiplier
        
        return {
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "investment": round(investment, 2),
            "current_value": round(current_value, 2),
            "lot_size": lot_size,
            "multiplier": multiplier,
            "instrument_type": inst_type
        }
    
    @staticmethod
    def calculate_strategy_pnl(positions: List[Dict]) -> Dict[str, float]:
        """Calculate aggregate P&L for a strategy (multiple positions).
        
        Args:
            positions: List of position dicts with pnl already calculated
            
        Returns:
            Dict with total_pnl, total_pnl_pct, position_count
        """
        if not positions:
            return {
                "total_pnl": 0.0,
                "total_pnl_pct": 0.0,
                "total_investment": 0.0,
                "position_count": 0
            }
        
        total_pnl = sum(p.get("pnl", 0) for p in positions)
        total_investment = sum(p.get("investment", 0) for p in positions)
        
        total_pnl_pct = (total_pnl / total_investment * 100) if total_investment > 0 else 0.0
        
        return {
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "total_investment": round(total_investment, 2),
            "position_count": len(positions)
        }
    
    @staticmethod
    def update_position_with_ltp(
        position: Dict,
        last_price: float
    ) -> Dict:
        """Update a position dict with new LTP and recalculate P&L.
        
        Args:
            position: Position dict with instrument_token, quantity, average_price
            last_price: New LTP
            
        Returns:
            Updated position dict with new pnl values
        """
        instrument_token = position.get("instrument_token", 0)
        quantity = position.get("quantity", 0)
        average_price = position.get("average_price", 0)
        exchange = position.get("exchange", "NFO")
        
        pnl_data = PnLCalculator.calculate_position_pnl(
            instrument_token=instrument_token,
            quantity=quantity,
            average_price=average_price,
            last_price=last_price,
            exchange=exchange
        )
        
        return {
            **position,
            "last_price": last_price,
            "pnl": pnl_data["pnl"],
            "pnl_pct": pnl_data["pnl_pct"],
            "investment": pnl_data["investment"],
            "current_value": pnl_data["current_value"]
        }


# Convenience functions
def calculate_pnl(
    instrument_token: int,
    quantity: int,
    average_price: float,
    last_price: float,
    exchange: str = "NFO"
) -> Dict[str, float]:
    """Calculate P&L for a position."""
    return PnLCalculator.calculate_position_pnl(
        instrument_token, quantity, average_price, last_price, exchange
    )


def calculate_strategy_pnl(positions: List[Dict]) -> Dict[str, float]:
    """Calculate aggregate P&L for a strategy."""
    return PnLCalculator.calculate_strategy_pnl(positions)
