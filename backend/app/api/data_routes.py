"""
Data Management API routes for Trading System v2.0

Provides endpoints for:
- Options data collector control (start/stop/status)
- Options data file listing
- Data download status
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime, date
from pathlib import Path
from loguru import logger
import subprocess
import signal
import os

router = APIRouter(prefix="/data", tags=["data"])

# Global state for collector process
_collector_process: Optional[subprocess.Popen] = None
_collector_config: Dict = {
    "symbols": [],
    "interval_seconds": 60,
    "start_time": None,
    "collections_today": 0,
    "records_today": 0,
    "errors_today": 0,
    "last_collection": None
}

# Paths
OPTIONS_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "options"
SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"


# ============== Request/Response Models ==============

class CollectorStartRequest(BaseModel):
    """Request to start the options collector."""
    symbols: List[str] = Field(default=["NIFTY", "BANKNIFTY"])
    interval_seconds: int = Field(default=60, ge=30, le=300)


class CollectorStatusResponse(BaseModel):
    """Status of the options collector."""
    running: bool
    symbols: List[str]
    interval_seconds: int
    collections_today: int
    records_today: int
    errors_today: int
    last_collection: Optional[str]
    start_time: Optional[str]


class OptionsFileInfo(BaseModel):
    """Information about an options data file."""
    filename: str
    symbol: str
    date: str
    size_mb: float
    records: int


class OptionsFilesResponse(BaseModel):
    """Response with list of options files."""
    files: List[OptionsFileInfo]
    total_size_mb: float
    total_records: int


# ============== Endpoints ==============

@router.get("/options/collector/status", response_model=CollectorStatusResponse)
async def get_collector_status():
    """Get the current status of the options data collector."""
    global _collector_process, _collector_config
    
    # Check if process is still running
    running = False
    if _collector_process is not None:
        poll = _collector_process.poll()
        running = poll is None
        if not running:
            _collector_process = None
    
    return CollectorStatusResponse(
        running=running,
        symbols=_collector_config.get("symbols", []),
        interval_seconds=_collector_config.get("interval_seconds", 60),
        collections_today=_collector_config.get("collections_today", 0),
        records_today=_collector_config.get("records_today", 0),
        errors_today=_collector_config.get("errors_today", 0),
        last_collection=_collector_config.get("last_collection"),
        start_time=_collector_config.get("start_time")
    )


@router.post("/options/collector/start")
async def start_collector(request: CollectorStartRequest, background_tasks: BackgroundTasks):
    """Start the options data collector."""
    global _collector_process, _collector_config
    
    # Check if already running
    if _collector_process is not None and _collector_process.poll() is None:
        raise HTTPException(
            status_code=400,
            detail="Collector is already running"
        )
    
    # Validate symbols
    valid_symbols = ["NIFTY", "BANKNIFTY"]
    for symbol in request.symbols:
        if symbol.upper() not in valid_symbols:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid symbol: {symbol}. Valid symbols: {valid_symbols}"
            )
    
    # Start collector script
    script_path = SCRIPTS_DIR / "collect_options_data.py"
    if not script_path.exists():
        raise HTTPException(
            status_code=500,
            detail="Collector script not found"
        )
    
    symbols_arg = ",".join(s.upper() for s in request.symbols)
    
    try:
        _collector_process = subprocess.Popen(
            [
                "python", str(script_path),
                "--symbols", symbols_arg,
                "--interval", str(request.interval_seconds)
            ],
            cwd=str(SCRIPTS_DIR.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid  # Create new process group for clean shutdown
        )
        
        _collector_config = {
            "symbols": [s.upper() for s in request.symbols],
            "interval_seconds": request.interval_seconds,
            "start_time": datetime.now().isoformat(),
            "collections_today": 0,
            "records_today": 0,
            "errors_today": 0,
            "last_collection": None
        }
        
        logger.info(f"Started options collector: symbols={symbols_arg}, interval={request.interval_seconds}s")
        
        return {
            "message": "Collector started",
            "symbols": _collector_config["symbols"],
            "interval_seconds": request.interval_seconds,
            "pid": _collector_process.pid
        }
        
    except Exception as e:
        logger.error(f"Failed to start collector: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start collector: {str(e)}"
        )


@router.post("/options/collector/stop")
async def stop_collector():
    """Stop the options data collector."""
    global _collector_process, _collector_config
    
    if _collector_process is None or _collector_process.poll() is not None:
        raise HTTPException(
            status_code=400,
            detail="Collector is not running"
        )
    
    try:
        # Send SIGTERM to process group for graceful shutdown
        os.killpg(os.getpgid(_collector_process.pid), signal.SIGTERM)
        
        # Wait for process to terminate (max 10 seconds)
        try:
            _collector_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # Force kill if not terminated
            os.killpg(os.getpgid(_collector_process.pid), signal.SIGKILL)
            _collector_process.wait()
        
        logger.info("Options collector stopped")
        _collector_process = None
        
        return {
            "message": "Collector stopped",
            "collections_completed": _collector_config.get("collections_today", 0),
            "records_collected": _collector_config.get("records_today", 0)
        }
        
    except Exception as e:
        logger.error(f"Failed to stop collector: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop collector: {str(e)}"
        )


@router.get("/options/files", response_model=OptionsFilesResponse)
async def list_options_files():
    """List all collected options data files."""
    OPTIONS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    files = []
    total_size = 0
    total_records = 0
    
    for filepath in sorted(OPTIONS_DATA_DIR.glob("*.parquet"), reverse=True):
        try:
            # Parse filename: NIFTY_options_20260206.parquet
            parts = filepath.stem.split("_")
            if len(parts) >= 3:
                symbol = parts[0]
                date_str = parts[2]
                
                # Format date
                try:
                    file_date = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
                except:
                    file_date = date_str
                
                # Get file size
                size_bytes = filepath.stat().st_size
                size_mb = size_bytes / (1024 * 1024)
                total_size += size_mb
                
                # Get record count (read parquet metadata)
                try:
                    import pyarrow.parquet as pq
                    parquet_file = pq.ParquetFile(filepath)
                    records = parquet_file.metadata.num_rows
                except:
                    records = 0
                
                total_records += records
                
                files.append(OptionsFileInfo(
                    filename=filepath.name,
                    symbol=symbol,
                    date=file_date,
                    size_mb=round(size_mb, 2),
                    records=records
                ))
                
        except Exception as e:
            logger.warning(f"Error reading options file {filepath}: {e}")
    
    return OptionsFilesResponse(
        files=files,
        total_size_mb=round(total_size, 2),
        total_records=total_records
    )


@router.get("/options/files/{filename}")
async def get_options_file_info(filename: str):
    """Get detailed information about a specific options data file."""
    filepath = OPTIONS_DATA_DIR / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        import pandas as pd
        
        df = pd.read_parquet(filepath)
        
        # Get summary statistics
        info = {
            "filename": filename,
            "size_mb": round(filepath.stat().st_size / (1024 * 1024), 2),
            "records": len(df),
            "columns": list(df.columns),
            "date_range": {
                "start": str(df["timestamp"].min()) if "timestamp" in df.columns else None,
                "end": str(df["timestamp"].max()) if "timestamp" in df.columns else None
            },
            "symbols": df["symbol"].unique().tolist() if "symbol" in df.columns else [],
            "expiries": [str(e) for e in df["expiry"].unique()] if "expiry" in df.columns else [],
            "strike_range": {
                "min": int(df["strike"].min()) if "strike" in df.columns else None,
                "max": int(df["strike"].max()) if "strike" in df.columns else None
            },
            "sample_records": df.head(5).to_dict(orient="records")
        }
        
        return info
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reading file: {str(e)}"
        )
