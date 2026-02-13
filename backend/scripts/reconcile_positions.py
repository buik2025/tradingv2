#!/usr/bin/env python3
"""
Daily Position Reconciliation Script

Runs after market close to ensure consistency between our database and Kite.

What it does:
1. Fetches current F&O positions from Kite
2. Marks positions in our DB as closed if they're no longer in Kite
3. Logs any discrepancies for review

Usage:
    python scripts/reconcile_positions.py [--dry-run]

Scheduling (crontab -e):
    # After NSE F&O market close (3:35 PM IST)
    35 15 * * 1-5 cd /path/to/tradingv2/backend && /path/to/python scripts/reconcile_positions.py >> logs/cron_reconcile.log 2>&1
    
    # After MCX market close (11:35 PM IST) - optional
    35 23 * * 1-5 cd /path/to/tradingv2/backend && /path/to/python scripts/reconcile_positions.py >> logs/cron_reconcile.log 2>&1

Also triggered automatically:
    - On user login (background task)
    - Via API: POST /api/v1/reconcile
"""

import sys
import argparse
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

from loguru import logger
from app.database.models import BrokerPosition, get_session
from app.core.kite_client import KiteClient
from app.core.credentials import get_kite_credentials

# F&O exchanges we track
FO_EXCHANGES = {"NFO", "MCX", "BFO", "CDS"}


def get_kite_fo_positions() -> dict:
    """Fetch current F&O positions from Kite.
    
    Returns:
        Dict mapping (exchange, tradingsymbol) -> position data
    """
    creds = get_kite_credentials()
    if not creds or not creds.get("access_token"):
        logger.error("No valid Kite credentials found")
        return {}
    
    kite = KiteClient(
        api_key=creds["api_key"],
        access_token=creds["access_token"],
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


def get_db_open_positions() -> list:
    """Get all open positions from our database."""
    session = get_session()
    try:
        positions = session.query(BrokerPosition).filter(
            BrokerPosition.closed_at.is_(None)
        ).all()
        return positions
    finally:
        session.close()


def reconcile(dry_run: bool = False):
    """Run reconciliation between Kite and our database.
    
    Args:
        dry_run: If True, only log what would be done without making changes
    """
    logger.info("=" * 60)
    logger.info(f"Position Reconciliation - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info("=" * 60)
    
    # Get positions from both sources
    kite_positions = get_kite_fo_positions()
    db_positions = get_db_open_positions()
    
    logger.info(f"Kite F&O positions: {len(kite_positions)}")
    logger.info(f"DB open positions: {len(db_positions)}")
    
    # Track stats
    closed_count = 0
    updated_count = 0
    discrepancies = []
    
    session = get_session() if not dry_run else None
    
    try:
        for db_pos in db_positions:
            key = (db_pos.exchange, db_pos.tradingsymbol)
            kite_pos = kite_positions.get(key)
            
            if kite_pos is None:
                # Position not in Kite - mark as closed
                logger.info(f"CLOSE: {db_pos.tradingsymbol} ({db_pos.exchange}) - not in Kite")
                if not dry_run:
                    db_pos.closed_at = datetime.now()
                    session.add(db_pos)
                closed_count += 1
                
            elif kite_pos["quantity"] == 0:
                # Position closed in Kite (qty = 0)
                logger.info(f"CLOSE: {db_pos.tradingsymbol} ({db_pos.exchange}) - qty=0 in Kite")
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
        
        # Check for positions in Kite but not in DB (new positions)
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
        
        if not dry_run and session:
            session.commit()
        
        # Summary
        logger.info("-" * 60)
        logger.info("SUMMARY:")
        logger.info(f"  Positions closed: {closed_count}")
        logger.info(f"  Positions updated: {updated_count}")
        logger.info(f"  Discrepancies found: {len(discrepancies)}")
        
        if discrepancies:
            logger.warning("DISCREPANCIES REQUIRING ATTENTION:")
            for d in discrepancies:
                logger.warning(f"  - {d['symbol']} ({d['exchange']}): DB={d['db_qty']}, Kite={d['kite_qty']}")
        
        logger.info("=" * 60)
        
        return {
            "closed": closed_count,
            "updated": updated_count,
            "discrepancies": discrepancies,
        }
        
    except Exception as e:
        logger.error(f"Reconciliation failed: {e}")
        if session:
            session.rollback()
        raise
    finally:
        if session:
            session.close()


def main():
    parser = argparse.ArgumentParser(description="Reconcile positions between Kite and database")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")
    logger.add(
        "logs/reconciliation_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="1 day",
        retention="30 days"
    )
    
    try:
        result = reconcile(dry_run=args.dry_run)
        
        if result["discrepancies"]:
            sys.exit(1)  # Exit with error if discrepancies found
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
