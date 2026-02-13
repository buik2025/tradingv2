"""
Unified Portfolio Service for Trading System v2.0

Consolidates all position, strategy, and portfolio data enrichment logic.
Frontend should only display data returned by this service - no calculations.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from loguru import logger

from ...core.kite_client import KiteClient
from ...config.settings import Settings
from ...database.repository import Repository
from ...database.models import BrokerPosition
from ..utilities import PnLCalculator


@dataclass
class EnrichedPosition:
    """Position with all calculated fields."""
    id: str
    tradingsymbol: str
    instrument_token: int
    exchange: str
    quantity: int
    average_price: float
    last_price: float
    close_price: float  # Previous day close
    ltp_change: float   # LTP - close_price
    ltp_change_pct: float  # % change from previous close
    pnl: float
    pnl_pct: float
    product: str  # CNC, NRML, MIS
    source: str   # LIVE, PAPER
    margin_used: float
    margin_pct: float  # % of total margin
    pnl_on_margin_pct: float
    # Additional Kite-like fields
    segment: str = "CASH"  # CASH, NFO, MCX, BFO
    instrument_type: str = "EQ"  # EQ, FUT, CE, PE
    underlying: str = ""  # Underlying symbol for derivatives
    expiry: Optional[str] = None  # Expiry date for derivatives
    strike: Optional[float] = None  # Strike price for options
    is_overnight: bool = False  # Overnight position
    is_short: bool = False  # True short position (derivatives/intraday)
    is_sold_holding: bool = False  # CNC equity sold from holdings (not true short)
    position_status: str = "OPEN"  # OPEN or CLOSED (sold holdings are CLOSED)
    transaction_type: str = "BUY"  # BUY or SELL (for display)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EnrichedTrade:
    """Trade within a strategy with margin data."""
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
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EnrichedStrategy:
    """Strategy with aggregated margin and P&L data."""
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
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EnrichedPortfolio:
    """Portfolio with aggregated strategy data."""
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
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AccountSummary:
    """Account margin summary."""
    total_margin: float
    used_margin: float
    available_margin: float
    cash_available: float
    collateral: float
    margin_utilization_pct: float  # Used margin as % of total
    available_margin_pct: float    # Available margin as % of total
    
    def to_dict(self) -> dict:
        return asdict(self)


class PortfolioService:
    """
    Unified service for all portfolio-related data.
    
    All business logic for calculating margins, P&L percentages, and
    aggregations lives here. Frontend should only display returned data.
    """
    
    def __init__(self, kite: KiteClient):
        self.kite = kite
        self._position_cache: Dict[int, EnrichedPosition] = {}
        self._account: Optional[AccountSummary] = None
        self._repository = Repository()
    
    def get_account_summary(self) -> AccountSummary:
        """Get account margin summary."""
        margins = self.kite.get_margins()
        
        equity = margins.get("equity", {})
        commodity = margins.get("commodity", {})
        
        equity_net = equity.get("net", 0)
        commodity_net = commodity.get("net", 0)
        
        equity_utilised = equity.get("utilised", {})
        commodity_utilised = commodity.get("utilised", {})
        
        equity_used = (
            equity_utilised.get("span", 0) + 
            equity_utilised.get("exposure", 0) + 
            equity_utilised.get("delivery", 0)
        )
        commodity_used = (
            commodity_utilised.get("span", 0) + 
            commodity_utilised.get("exposure", 0) + 
            commodity_utilised.get("delivery", 0)
        )
        
        total_available = equity_net + commodity_net
        total_used = equity_used + commodity_used
        total_margin = total_available + total_used
        
        cash = equity.get("available", {}).get("cash", 0) + commodity.get("available", {}).get("cash", 0)
        collateral = equity.get("available", {}).get("collateral", 0) + commodity.get("available", {}).get("collateral", 0)
        
        self._account = AccountSummary(
            total_margin=round(total_margin, 2),
            used_margin=round(total_used, 2),
            available_margin=round(total_available, 2),
            cash_available=round(cash, 2),
            collateral=round(collateral, 2),
            margin_utilization_pct=round((total_used / total_margin * 100) if total_margin > 0 else 0, 2),
            available_margin_pct=round((total_available / total_margin * 100) if total_margin > 0 else 0, 2)
        )
        return self._account
    
    def get_positions(self) -> List[EnrichedPosition]:
        """Get all F&O positions with margin and P&L calculations.
        
        Filters to F&O exchanges only (NFO, MCX, BFO, CDS).
        Equity positions (NSE, BSE) are excluded.
        """
        # F&O exchanges only
        FO_EXCHANGES = {"NFO", "MCX", "BFO", "CDS"}
        
        # Ensure we have account data
        if not self._account:
            self.get_account_summary()
        
        total_margin = self._account.total_margin if self._account else 1
        
        positions_data = self.kite.get_positions()
        net_positions = positions_data.get("net", [])
        
        # Filter to F&O only
        net_positions = [p for p in net_positions if p.get("exchange", "") in FO_EXCHANGES]
        
        # Get margin for each position
        margin_lookup = self._calculate_position_margins(net_positions)
        
        result = []
        for p in net_positions:
            qty = p.get("quantity", 0)
            
            instrument_token = p.get("instrument_token", 0)
            tradingsymbol = p.get("tradingsymbol", "")
            exchange = p.get("exchange", "")
            avg_price = p.get("average_price", 0)
            last_price = p.get("last_price", 0)
            pnl = p.get("pnl", 0)
            product = p.get("product", "NRML")
            
            # Get margin from lookup or estimate
            position_margin = margin_lookup.get(tradingsymbol, 0)
            if position_margin == 0 and qty != 0:
                position_margin = self._estimate_margin(tradingsymbol, exchange, qty, last_price, avg_price, product)
            
            # Calculate percentages
            pnl_pct = (pnl / (avg_price * abs(qty)) * 100) if avg_price and qty else 0
            margin_pct = (position_margin / total_margin * 100) if total_margin > 0 else 0
            pnl_on_margin_pct = (pnl / position_margin * 100) if position_margin > 0 else 0
            
            # Calculate LTP change from previous close
            close_price = p.get("close_price", 0)
            ltp_change = last_price - close_price if close_price else 0
            ltp_change_pct = (ltp_change / close_price * 100) if close_price else 0
            
            # Parse instrument details for derivatives
            segment = p.get("segment", self._get_segment(exchange))
            instrument_type, underlying, expiry, strike = self._parse_tradingsymbol(tradingsymbol, exchange)
            is_overnight = p.get("overnight_quantity", 0) != 0
            
            # Determine position status:
            # qty == 0: position was closed today (intraday closed)
            # CNC equity with negative qty: sold holding (closed)
            # Otherwise: open position
            is_closed_today = (qty == 0)
            is_sold_holding = (product == "CNC" and instrument_type == "EQ" and qty < 0)
            is_short = (qty < 0 and not is_sold_holding)
            
            enriched = EnrichedPosition(
                id=str(instrument_token),
                tradingsymbol=tradingsymbol,
                instrument_token=instrument_token,
                exchange=exchange,
                quantity=qty,
                average_price=round(avg_price, 2),
                last_price=round(last_price, 2),
                close_price=round(close_price, 2),
                ltp_change=round(ltp_change, 2),
                ltp_change_pct=round(ltp_change_pct, 2),
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 2),
                product=product,
                source="LIVE",
                margin_used=round(position_margin, 2),
                margin_pct=round(margin_pct, 2),
                pnl_on_margin_pct=round(pnl_on_margin_pct, 2),
                segment=segment,
                instrument_type=instrument_type,
                underlying=underlying,
                expiry=expiry,
                strike=strike,
                is_overnight=is_overnight,
                is_short=is_short,
                is_sold_holding=is_sold_holding,
                position_status="CLOSED" if (is_sold_holding or is_closed_today) else "OPEN",
                transaction_type="SELL" if (is_short or is_sold_holding) else "BUY"
            )
            result.append(enriched)
            self._position_cache[instrument_token] = enriched
        
        # Also fetch paper positions from database (PAPER source only)
        # Live positions from DB are not fetched here since they come from Kite API above
        db_positions = self._get_db_positions(total_margin, source="PAPER")
        result.extend(db_positions)
        
        return result
    
    def get_strategies(self, strategies_data: List[dict]) -> List[EnrichedStrategy]:
        """
        Enrich strategies with margin and P&L data.
        
        Args:
            strategies_data: Raw strategy data from database
        """
        # Ensure positions are loaded
        if not self._position_cache:
            self.get_positions()
        
        total_margin = self._account.total_margin if self._account else 1
        
        result = []
        for strategy in strategies_data:
            trades = strategy.get("trades", [])
            enriched_trades, totals = self._enrich_trades(trades, total_margin)
            
            enriched = EnrichedStrategy(
                id=strategy.get("id", ""),
                name=strategy.get("name", ""),
                label=strategy.get("label"),
                status=strategy.get("status", "OPEN"),
                source=strategy.get("source", "MANUAL"),
                trades_count=len(trades),
                trades=[t.to_dict() for t in enriched_trades],
                unrealized_pnl=round(totals["unrealized_pnl"], 2),
                realized_pnl=round(strategy.get("realized_pnl", 0), 2),
                total_pnl=round(totals["unrealized_pnl"] + strategy.get("realized_pnl", 0), 2),
                total_margin=round(totals["margin"], 2),
                margin_pct=round(totals["margin_pct"], 2),
                pnl_on_margin_pct=round(totals["pnl_on_margin_pct"], 2),
                notes=strategy.get("notes"),
                tags=strategy.get("tags"),
                created_at=strategy.get("created_at")
            )
            result.append(enriched)
        
        return result
    
    def get_portfolios(self, portfolios_data: List[dict], strategies_data: List[dict]) -> List[EnrichedPortfolio]:
        """
        Enrich portfolios with strategy and margin data.
        
        Args:
            portfolios_data: Raw portfolio data from database
            strategies_data: Raw strategy data from database
        """
        # Ensure positions are loaded
        if not self._position_cache:
            self.get_positions()
        
        total_margin = self._account.total_margin if self._account else 1
        
        # If no portfolios, create virtual "All Strategies" portfolio
        if not portfolios_data:
            enriched_strategies = self.get_strategies(strategies_data)
            
            total_unrealized = sum(s.unrealized_pnl for s in enriched_strategies)
            total_realized = sum(s.realized_pnl for s in enriched_strategies)
            total_strat_margin = sum(s.total_margin for s in enriched_strategies)
            total_margin_pct = sum(s.margin_pct for s in enriched_strategies)
            
            return [EnrichedPortfolio(
                id="all",
                name="All Strategies",
                description="All trading strategies",
                strategy_count=len(enriched_strategies),
                strategies=[s.to_dict() for s in enriched_strategies],
                unrealized_pnl=round(total_unrealized, 2),
                realized_pnl=round(total_realized, 2),
                total_pnl=round(total_unrealized + total_realized, 2),
                total_margin=round(total_strat_margin, 2),
                margin_pct=round(total_margin_pct, 2),
                pnl_on_margin_pct=round((total_unrealized / total_strat_margin * 100) if total_strat_margin > 0 else 0, 2),
                is_active=True
            )]
        
        result = []
        for portfolio in portfolios_data:
            portfolio_id = portfolio.get("id", "")
            portfolio_strategies = [s for s in strategies_data if s.get("portfolio_id") == portfolio_id]
            enriched_strategies = self.get_strategies(portfolio_strategies)
            
            total_unrealized = sum(s.unrealized_pnl for s in enriched_strategies)
            total_realized = sum(s.realized_pnl for s in enriched_strategies)
            total_strat_margin = sum(s.total_margin for s in enriched_strategies)
            total_margin_pct = sum(s.margin_pct for s in enriched_strategies)
            
            enriched = EnrichedPortfolio(
                id=portfolio_id,
                name=portfolio.get("name", ""),
                description=portfolio.get("description"),
                strategy_count=len(enriched_strategies),
                strategies=[s.to_dict() for s in enriched_strategies],
                unrealized_pnl=round(total_unrealized, 2),
                realized_pnl=round(portfolio.get("realized_pnl", 0), 2),
                total_pnl=round(total_unrealized + portfolio.get("realized_pnl", 0), 2),
                total_margin=round(total_strat_margin, 2),
                margin_pct=round(total_margin_pct, 2),
                pnl_on_margin_pct=round((total_unrealized / total_strat_margin * 100) if total_strat_margin > 0 else 0, 2),
                is_active=portfolio.get("is_active", True)
            )
            result.append(enriched)
        
        return result
    
    def _enrich_trades(self, trades: List[dict], total_margin: float) -> tuple:
        """Enrich trades with position data."""
        enriched = []
        totals = {"margin": 0, "margin_pct": 0, "unrealized_pnl": 0, "pnl_on_margin_pct": 0}
        
        for trade in trades:
            token = trade.get("instrument_token", 0)
            pos = self._position_cache.get(token)
            
            margin_used = pos.margin_used if pos else 0
            margin_pct = pos.margin_pct if pos else 0
            last_price = pos.last_price if pos else trade.get("last_price")
            unrealized_pnl = pos.pnl if pos else trade.get("unrealized_pnl", 0)
            pnl_on_margin_pct = (unrealized_pnl / margin_used * 100) if margin_used > 0 else 0
            
            totals["margin"] += margin_used
            totals["margin_pct"] += margin_pct
            totals["unrealized_pnl"] += unrealized_pnl
            
            enriched.append(EnrichedTrade(
                id=trade.get("id", ""),
                tradingsymbol=trade.get("tradingsymbol", ""),
                instrument_token=token,
                exchange=trade.get("exchange", ""),
                instrument_type=trade.get("instrument_type"),
                quantity=trade.get("quantity", 0),
                entry_price=round(trade.get("entry_price", 0), 2),
                last_price=round(last_price, 2) if last_price else 0.0,
                unrealized_pnl=round(unrealized_pnl, 2),
                realized_pnl=round(trade.get("realized_pnl", 0), 2),
                pnl_pct=round(trade.get("pnl_pct", 0), 2),
                status=trade.get("status", "OPEN"),
                entry_time=trade.get("entry_time"),
                margin_used=round(margin_used, 2),
                margin_pct=round(margin_pct, 2),
                pnl_on_margin_pct=round(pnl_on_margin_pct, 2)
            ))
        
        if totals["margin"] > 0:
            totals["pnl_on_margin_pct"] = totals["unrealized_pnl"] / totals["margin"] * 100
        
        return enriched, totals
    
    def _calculate_position_margins(self, positions: List[dict]) -> Dict[str, float]:
        """Calculate margins for positions using Kite API."""
        orders_for_margin = []
        
        for p in positions:
            qty = p.get("quantity", 0)
            if qty == 0:
                continue
            
            orders_for_margin.append({
                "exchange": p.get("exchange", ""),
                "tradingsymbol": p.get("tradingsymbol", ""),
                "transaction_type": "SELL" if qty < 0 else "BUY",
                "variety": "regular",
                "product": p.get("product", "NRML"),
                "order_type": "MARKET",
                "quantity": abs(qty),
                "price": 0
            })
        
        margin_lookup = {}
        try:
            if orders_for_margin:
                results = self.kite.get_order_margins(orders_for_margin)
                for i, order in enumerate(orders_for_margin):
                    if i < len(results):
                        margin_lookup[order["tradingsymbol"]] = results[i].get("total", 0)
        except Exception as e:
            logger.warning(f"Failed to get order margins: {e}")
        
        return margin_lookup
    
    def _get_position_margin_from_api(self, tradingsymbol: str, exchange: str, qty: int, product: str) -> float:
        """
        Get actual margin for a position using Kite order_margins API.
        
        Args:
            tradingsymbol: Trading symbol
            exchange: Exchange (NFO, MCX, etc.)
            qty: Position quantity (negative for short)
            product: Product type (NRML, MIS, etc.)
            
        Returns:
            Margin amount or 0 if API call fails
        """
        if qty == 0:
            return 0.0
        
        try:
            order = {
                "exchange": exchange,
                "tradingsymbol": tradingsymbol,
                "transaction_type": "SELL" if qty < 0 else "BUY",
                "variety": "regular",
                "product": product,
                "order_type": "MARKET",
                "quantity": abs(qty),
                "price": 0
            }
            
            margin_results = self.kite.get_order_margins([order])
            if margin_results and len(margin_results) > 0:
                total_margin = margin_results[0].get("total", 0)
                if total_margin > 0:
                    return total_margin
                    
        except Exception as e:
            logger.debug(f"Failed to get margin from API for {tradingsymbol}: {e}")
        
        return 0.0
    
    def _estimate_margin(self, symbol: str, exchange: str, qty: int, ltp: float, avg_price: float, product: str) -> float:
        """Fallback margin estimation when API fails."""
        notional = abs(qty) * ltp
        
        if exchange == "MCX":
            multiplier = PnLCalculator._get_mcx_multiplier(symbol)
            notional = abs(qty) * ltp * multiplier
            return notional * 0.05
        elif exchange == "NFO":
            if "PE" in symbol or "CE" in symbol:
                if qty < 0:  # Short option
                    return notional * 0.15
                else:  # Long option
                    return abs(qty) * avg_price
            else:  # Futures
                return notional * 0.12
        else:
            return notional * (0.20 if product == "MIS" else 1.0)
    
    def _get_segment(self, exchange: str) -> str:
        """Get segment from exchange."""
        segment_map = {
            "NSE": "CASH",
            "BSE": "CASH",
            "NFO": "NFO",
            "BFO": "BFO",
            "MCX": "MCX",
            "CDS": "CDS"
        }
        return segment_map.get(exchange, "CASH")
    
    def _parse_tradingsymbol(self, tradingsymbol: str, exchange: str) -> tuple:
        """
        Parse tradingsymbol to extract instrument details.
        
        Returns:
            (instrument_type, underlying, expiry, strike)
        """
        import re
        
        # Default values for equity
        if exchange in ("NSE", "BSE"):
            return ("EQ", tradingsymbol, None, None)
        
        # NFO/MCX derivatives parsing
        # Examples: NIFTY26FEB24900PE, NIFTY26FEBFUT, GOLDM26MARFUT
        
        # Option pattern: SYMBOL + YYMMM + STRIKE + CE/PE
        option_match = re.match(r'^([A-Z]+)(\d{2}[A-Z]{3})(\d+)(CE|PE)$', tradingsymbol)
        if option_match:
            underlying = option_match.group(1)
            expiry = option_match.group(2)
            strike = float(option_match.group(3))
            opt_type = option_match.group(4)
            return (opt_type, underlying, expiry, strike)
        
        # Future pattern: SYMBOL + YYMMM + FUT
        future_match = re.match(r'^([A-Z]+)(\d{2}[A-Z]{3})FUT$', tradingsymbol)
        if future_match:
            underlying = future_match.group(1)
            expiry = future_match.group(2)
            return ("FUT", underlying, expiry, None)
        
        # MCX future pattern: SYMBOLMYYMMM (e.g., GOLDM26MAR)
        mcx_match = re.match(r'^([A-Z]+)(\d{2}[A-Z]{3})$', tradingsymbol)
        if mcx_match and exchange == "MCX":
            underlying = mcx_match.group(1)
            expiry = mcx_match.group(2)
            return ("FUT", underlying, expiry, None)
        
        # Fallback
        return ("EQ", tradingsymbol, None, None)
    
    def _get_db_positions(self, total_margin: float, source: str = None) -> List[EnrichedPosition]:
        """
        Fetch positions from database and enrich them.
        
        Args:
            total_margin: Total margin for percentage calculations
            source: Filter by source ("PAPER", "LIVE", or None for all)
        """
        result = []
        
        try:
            with self._repository._get_session() as session:
                # Get positions that are not closed
                query = session.query(BrokerPosition).filter(
                    BrokerPosition.closed_at.is_(None)
                )
                if source:
                    query = query.filter(BrokerPosition.source == source)
                
                db_positions = query.all()
                
                if not db_positions:
                    return result
                
                # Get LTP for DB positions
                tokens = [p.instrument_token for p in db_positions]
                ltp_data = {}
                try:
                    if tokens:
                        ltp_data = self.kite.get_ltp(tokens)
                except Exception as e:
                    logger.warning(f"Failed to get LTP for DB positions: {e}")
                
                for p in db_positions:
                    qty = p.quantity
                    avg_price = float(p.average_price) if p.average_price else 0
                    
                    # Get LTP from API or use average price
                    # get_ltp returns {token: price} so use token as key
                    last_price = ltp_data.get(p.instrument_token, avg_price)
                    if last_price == 0:
                        last_price = avg_price
                    
                    # Calculate P&L
                    if qty > 0:  # Long position
                        pnl = (last_price - avg_price) * qty
                    else:  # Short position
                        pnl = (avg_price - last_price) * abs(qty)
                    
                    # Calculate LTP change from avg price (for paper positions)
                    ltp_change = last_price - avg_price
                    ltp_change_pct = ((last_price - avg_price) / avg_price * 100) if avg_price else 0
                    
                    # Get margin from Kite API for accurate calculation
                    position_margin = self._get_position_margin_from_api(
                        p.tradingsymbol, p.exchange, qty, p.product or "NRML"
                    )
                    if position_margin == 0:
                        # Fallback to estimation if API fails
                        position_margin = self._estimate_margin(
                            p.tradingsymbol, p.exchange, qty, last_price, avg_price, p.product or "NRML"
                        )
                    
                    # Calculate percentages
                    pnl_pct = (pnl / (avg_price * abs(qty)) * 100) if avg_price and qty else 0
                    margin_pct = (position_margin / total_margin * 100) if total_margin > 0 else 0
                    pnl_on_margin_pct = (pnl / position_margin * 100) if position_margin > 0 else 0
                    
                    # Parse instrument details
                    segment = self._get_segment(p.exchange)
                    instrument_type, underlying, expiry, strike = self._parse_tradingsymbol(p.tradingsymbol, p.exchange)
                    
                    is_short = qty < 0
                    pos_source = p.source or "LIVE"
                    
                    enriched = EnrichedPosition(
                        id=p.id,
                        tradingsymbol=p.tradingsymbol,
                        instrument_token=p.instrument_token,
                        exchange=p.exchange,
                        quantity=qty,
                        average_price=round(avg_price, 2),
                        last_price=round(last_price, 2),
                        close_price=round(avg_price, 2),
                        ltp_change=round(ltp_change, 2),
                        ltp_change_pct=round(ltp_change_pct, 2),
                        pnl=round(pnl, 2),
                        pnl_pct=round(pnl_pct, 2),
                        product=p.product or "NRML",
                        source=pos_source,
                        margin_used=round(position_margin, 2),
                        margin_pct=round(margin_pct, 2),
                        pnl_on_margin_pct=round(pnl_on_margin_pct, 2),
                        segment=segment,
                        instrument_type=instrument_type,
                        underlying=underlying,
                        expiry=expiry,
                        strike=strike,
                        is_overnight=False,
                        is_short=is_short,
                        is_sold_holding=False,
                        position_status="OPEN",
                        transaction_type="SELL" if is_short else "BUY"
                    )
                    result.append(enriched)
                    
        except Exception as e:
            logger.error(f"Failed to fetch DB positions: {e}")
        
        return result
