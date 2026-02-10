"""
Unified Portfolio API Routes for Trading System v2.0

All data returned is fully enriched - frontend should only display.
"""

from fastapi import APIRouter, HTTPException, Request
from typing import List, Optional
from pydantic import BaseModel
from loguru import logger

from ..core.kite_client import KiteClient, TokenExpiredException
from ..config.settings import Settings
from ..services.execution import PortfolioService
from .auth import get_access_token


router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ============== Response Models ==============

class PositionResponse(BaseModel):
    id: str
    tradingsymbol: str
    instrument_token: int
    exchange: str
    quantity: int
    average_price: float
    last_price: float
    close_price: float
    ltp_change: float
    ltp_change_pct: float
    pnl: float
    pnl_pct: float
    product: str  # CNC, NRML, MIS
    source: str   # LIVE, PAPER
    margin_used: float
    margin_pct: float
    pnl_on_margin_pct: float
    # Kite-like categorization fields
    segment: str = "CASH"  # CASH, NFO, MCX, BFO
    instrument_type: str = "EQ"  # EQ, FUT, CE, PE
    underlying: str = ""  # Underlying symbol for derivatives
    expiry: Optional[str] = None  # Expiry date for derivatives
    strike: Optional[float] = None  # Strike price for options
    is_overnight: bool = False
    is_short: bool = False  # True short (derivatives/intraday)
    is_sold_holding: bool = False  # CNC equity sold from holdings
    position_status: str = "OPEN"  # OPEN or CLOSED
    transaction_type: str = "BUY"  # BUY or SELL


class TradeResponse(BaseModel):
    id: str
    tradingsymbol: str
    instrument_token: int
    exchange: str
    instrument_type: Optional[str]
    quantity: int
    entry_price: float
    last_price: Optional[float]
    unrealized_pnl: float
    realized_pnl: float
    pnl_pct: float
    status: str
    entry_time: Optional[str]
    margin_used: float
    margin_pct: float
    pnl_on_margin_pct: float


class StrategyResponse(BaseModel):
    id: str
    name: str
    label: Optional[str]
    status: str
    source: str
    trades_count: int
    trades: List[dict]
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    total_margin: float
    margin_pct: float
    pnl_on_margin_pct: float
    notes: Optional[str]
    tags: Optional[List[str]]
    created_at: Optional[str]


class PortfolioResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    strategy_count: int
    strategies: List[dict]
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    total_margin: float
    margin_pct: float
    pnl_on_margin_pct: float
    is_active: bool


class AccountResponse(BaseModel):
    total_margin: float
    used_margin: float
    available_margin: float
    cash_available: float
    collateral: float
    margin_utilization_pct: float
    available_margin_pct: float


class PositionsDataResponse(BaseModel):
    positions: List[PositionResponse]
    account: AccountResponse
    totals: dict


class StrategiesDataResponse(BaseModel):
    strategies: List[StrategyResponse]
    account: AccountResponse
    totals: dict


class PortfoliosDataResponse(BaseModel):
    portfolios: List[PortfolioResponse]
    account: AccountResponse
    totals: dict


# ============== Helper ==============

def get_portfolio_service(request: Request) -> PortfolioService:
    """Create PortfolioService with authenticated KiteClient."""
    config = Settings()
    access_token = get_access_token(request) or config.kite_access_token
    
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    kite = KiteClient(
        api_key=config.kite_api_key,
        access_token=access_token,
        paper_mode=False,
        mock_mode=False
    )
    return PortfolioService(kite)


# ============== Endpoints ==============

@router.get("/account", response_model=AccountResponse)
async def get_account(request: Request):
    """Get account margin summary."""
    try:
        service = get_portfolio_service(request)
        account = service.get_account_summary()
        return account.to_dict()
    except TokenExpiredException:
        raise HTTPException(status_code=401, detail="Token expired. Please re-login.")
    except Exception as e:
        logger.error(f"Failed to get account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions", response_model=PositionsDataResponse)
async def get_positions(request: Request):
    """
    Get all positions with full margin and P&L data.
    
    Returns positions with:
    - margin_used: Actual margin for this position
    - margin_pct: Position margin as % of total account margin
    - pnl_on_margin_pct: P&L as % of margin used
    """
    try:
        service = get_portfolio_service(request)
        account = service.get_account_summary()
        positions = service.get_positions()
        
        # Sort positions by symbol by default
        positions.sort(key=lambda p: p.tradingsymbol or "")
        
        # Calculate totals
        total_pnl = sum(p.pnl for p in positions)
        total_margin = sum(p.margin_used for p in positions)
        
        return {
            "positions": [p.to_dict() for p in positions],
            "account": account.to_dict(),
            "totals": {
                "pnl": round(total_pnl, 2),
                "margin": round(total_margin, 2),
                "pnl_on_margin_pct": round((total_pnl / total_margin * 100) if total_margin > 0 else 0, 2),
                "count": len(positions)
            }
        }
    except TokenExpiredException:
        raise HTTPException(status_code=401, detail="Token expired. Please re-login.")
    except Exception as e:
        logger.error(f"Failed to get positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies", response_model=StrategiesDataResponse)
async def get_strategies(request: Request):
    """
    Get all strategies with full margin and P&L data.
    
    Each strategy includes:
    - Enriched trades with margin data
    - Aggregated margin and P&L metrics
    """
    from ..database.repository import Repository
    
    try:
        service = get_portfolio_service(request)
        account = service.get_account_summary()
        service.get_positions()  # Load position cache
        
        # Get strategies from database
        repo = Repository()
        strategies_data = repo.get_all_strategies()
        
        strategies = service.get_strategies(strategies_data)
        
        # Calculate totals
        total_pnl = sum(s.total_pnl for s in strategies)
        total_margin = sum(s.total_margin for s in strategies)
        
        return {
            "strategies": [s.to_dict() for s in strategies],
            "account": account.to_dict(),
            "totals": {
                "pnl": round(total_pnl, 2),
                "margin": round(total_margin, 2),
                "pnl_on_margin_pct": round((total_pnl / total_margin * 100) if total_margin > 0 else 0, 2),
                "count": len(strategies)
            }
        }
    except TokenExpiredException:
        raise HTTPException(status_code=401, detail="Token expired. Please re-login.")
    except Exception as e:
        logger.error(f"Failed to get strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/portfolios", response_model=PortfoliosDataResponse)
async def get_portfolios(request: Request):
    """
    Get all portfolios with full margin and P&L data.
    
    Each portfolio includes:
    - Enriched strategies with margin data
    - Aggregated margin and P&L metrics
    """
    from ..database.repository import Repository
    
    try:
        service = get_portfolio_service(request)
        account = service.get_account_summary()
        service.get_positions()  # Load position cache
        
        # Get data from database
        repo = Repository()
        portfolios_data = repo.get_all_portfolios()
        strategies_data = repo.get_all_strategies()
        
        portfolios = service.get_portfolios(portfolios_data, strategies_data)
        
        # Calculate totals
        total_pnl = sum(p.total_pnl for p in portfolios)
        total_margin = sum(p.total_margin for p in portfolios)
        
        return {
            "portfolios": [p.to_dict() for p in portfolios],
            "account": account.to_dict(),
            "totals": {
                "pnl": round(total_pnl, 2),
                "margin": round(total_margin, 2),
                "pnl_on_margin_pct": round((total_pnl / total_margin * 100) if total_margin > 0 else 0, 2),
                "count": len(portfolios)
            }
        }
    except TokenExpiredException:
        raise HTTPException(status_code=401, detail="Token expired. Please re-login.")
    except Exception as e:
        logger.error(f"Failed to get portfolios: {e}")
        raise HTTPException(status_code=500, detail=str(e))
