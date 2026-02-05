#!/usr/bin/env python3
"""Initialize PostgreSQL database for Trading System v2.0"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from loguru import logger


def create_database(db_url: str, db_name: str = "trading"):
    """Create the database if it doesn't exist."""
    # Connect to default postgres database to create our database
    base_url = db_url.rsplit('/', 1)[0]
    engine = create_engine(f"{base_url}/postgres", isolation_level="AUTOCOMMIT")
    
    with engine.connect() as conn:
        # Check if database exists
        result = conn.execute(
            text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
        )
        exists = result.fetchone() is not None
        
        if not exists:
            conn.execute(text(f"CREATE DATABASE {db_name}"))
            logger.info(f"Created database: {db_name}")
        else:
            logger.info(f"Database already exists: {db_name}")
    
    engine.dispose()


def init_tables(db_url: str):
    """Initialize all tables."""
    from backend.app.database.models import Base, init_db
    
    init_db(db_url)
    logger.info("All tables created successfully")


def main():
    # Database configuration
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "trading")
    db_user = os.getenv("POSTGRES_USER", "postgres")
    db_password = os.getenv("POSTGRES_PASSWORD", "postgres")
    
    db_url = os.getenv(
        "DATABASE_URL",
        f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    )
    
    logger.info(f"Initializing database at: {db_host}:{db_port}/{db_name}")
    
    try:
        # Create database
        create_database(db_url, db_name)
        
        # Create tables
        init_tables(db_url)
        
        logger.info("Database initialization complete!")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
