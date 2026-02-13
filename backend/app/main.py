"""FastAPI application for Trading System v2.0"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger
import sys
import os

# Set default timezone to IST (Indian Standard Time)
os.environ['TZ'] = 'Asia/Kolkata'
try:
    import time
    time.tzset()
except AttributeError:
    pass  # Windows doesn't have tzset

from .api.routes import router
from .api.auth import router as auth_router
from .api.websocket import router as ws_router
from .api.portfolio_routes import router as portfolio_router
from .api.data_routes import router as data_router
from .core.logger import setup_logger
from .services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Trading System v2.0 API starting...")
    
    # Start the reconciliation scheduler
    await start_scheduler()
    logger.info("Reconciliation scheduler started")
    
    yield
    
    # Shutdown
    await stop_scheduler()
    logger.info("Trading System v2.0 API shutting down...")


app = FastAPI(
    title="Trading System v2.0",
    description="Multi-agent algorithmic trading system for Indian markets",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")
app.include_router(portfolio_router, prefix="/api/v1")
app.include_router(data_router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Trading System v2.0",
        "version": "2.0.0",
        "docs": "/docs"
    }
