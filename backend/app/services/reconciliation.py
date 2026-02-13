"""
Position Reconciliation Service

Ensures consistency between our database and Kite positions.
Called on login and after market close.
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger

from ..database.models import BrokerPosition, get_session
from ..core.kite_client import KiteClient
from ..core.credentials import get_kite_credentials

# F&O exchanges we track
FO_EXCHANGES = {"NFO", "MCX", "BFO", "CDS"}


def get_kite_fo_positions(api_key: str, access_token: str) -> Dict:
    """Fetch current F&O positions from Kite.
    
    Returns:
        Dict mapping (exchange, tradingsymbol) -> position data
    """
    kite = KiteClient(
        api_key=api_key,
        access_token=access_token,
        paper_mode=False,
        mock_mode=False
    )
    
    positions_data = kite.get_positions()
    net_positions = positions_data.get("net", [])
    
    result = {}
    for p in net_positions:
        exchange = p.get("exchange", "")
        if exchange not in FO_EXCHANGES:
            continue
        
        qty = p.get("quantity", 0)
        tradingsymbol = p.get("tradingsymbol", "")
        
        key = (exchange, tradingsymbol)
        result[key] = {
            "quantity": qty,
            "average_price": p.get("average_price", 0),
            "last_price": p.get("last_price", 0),
            "pnl": p.get("pnl", 0),
            "instrument_token": p.get("instrument_token", 0),
        }
    
    return result


def run_reconciliation(api_key: str, access_token: str, dry_run: bool = False) -> Dict:
    """Run reconciliation between Kite and our database.
    
    Args:
        api_key: Kite API key
        access_token: Kite access token
        dry_run: If True, only log what would be done without making changes
        
    Returns:
        Dict with reconciliation results
    """
    logger.info(f"Starting position reconciliation (dry_run={dry_run})")
    
    # Get positions from both sources
    try:
        kite_positions = get_kite_fo_positions(api_key, access_token)
    except Exception as e:
        logger.error(f"Failed to fetch Kite positions: {e}")
        return {"error": str(e), "closed": 0, "updated": 0, "discrepancies": []}
    
    session = get_session()
    try:
        db_positions = session.query(BrokerPosition).filter(
            BrokerPosition.closed_at.is_(None),
            BrokerPosition.exchange.in_(FO_EXCHANGES)
        ).all()
        
        logger.info(f"Kite F&O positions: {len(kite_positions)}, DB open positions: {len(db_positions)}")
        
        closed_count = 0
        updated_count = 0
        discrepancies = []
        
        for db_pos in db_positions:
            key = (db_pos.exchange, db_pos.tradingsymbol)
            kite_pos = kite_positions.get(key)
            
            if kite_pos is None or kite_pos["quantity"] == 0:
                # Position not in Kite or closed - mark as closed
                reason = "not in Kite" if kite_pos is None else "qty=0 in Kite"
                logger.info(f"CLOSE: {db_pos.tradingsymbol} ({db_pos.exchange}) - {reason}")
                if not dry_run:
                    db_pos.closed_at = datetime.now()
                    session.add(db_pos)
                closed_count += 1
            else:
                # Position exists - check for quantity mismatch
                if db_pos.quantity != kite_pos["quantity"]:
                    discrepancies.append({
                        "symbol": db_pos.tradingsymbol,
                        "exchange": db_pos.exchange,
                        "db_qty": db_pos.quantity,
                        "kite_qty": kite_pos["quantity"],
                    })
                    logger.warning(
                        f"MISMATCH: {db_pos.tradingsymbol} - "
                        f"DB qty={db_pos.quantity}, Kite qty={kite_pos['quantity']}"
                    )
                
                # Update last price and P&L
                if not dry_run:
                    db_pos.last_price = kite_pos["last_price"]
                    db_pos.pnl = kite_pos["pnl"]
                    session.add(db_pos)
                    updated_count += 1
        
        # Check for positions in Kite but not in DB
        db_keys = {(p.exchange, p.tradingsymbol) for p in db_positions}
        for key, kite_pos in kite_positions.items():
            if key not in db_keys and kite_pos["quantity"] != 0:
                logger.warning(
                    f"NEW IN KITE: {key[1]} ({key[0]}) - "
                    f"qty={kite_pos['quantity']}, not in our DB"
                )
                discrepancies.append({
                    "symbol": key[1],
                    "exchange": key[0],
                    "db_qty": 0,
                    "kite_qty": kite_pos["quantity"],
                    "note": "Position in Kite but not in DB"
                })
        
        if not dry_run:
            session.commit()
        
        logger.info(f"Reconciliation complete: closed={closed_count}, updated={updated_count}, discrepancies={len(discrepancies)}")
        
        return {
            "closed": closed_count,
            "updated": updated_count,
            "discrepancies": discrepancies,
        }
        
    except Exception as e:
        logger.error(f"Reconciliation failed: {e}")
        session.rollback()
        return {"error": str(e), "closed": 0, "updated": 0, "discrepancies": []}
    finally:
        session.close()


async def run_reconciliation_async(api_key: str, access_token: str):
    """Run reconciliation in background (non-blocking).
    
    Called after login to ensure data consistency.
    """
    # Run in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, 
            lambda: run_reconciliation(api_key, access_token, dry_run=False)
        )
        if result.get("discrepancies"):
            logger.warning(f"Reconciliation found {len(result['discrepancies'])} discrepancies")
    except Exception as e:
        logger.error(f"Background reconciliation failed: {e}")
