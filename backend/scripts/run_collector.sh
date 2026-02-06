#!/bin/bash
#
# Options Data Collector Runner Script
# 
# This script runs the options data collector as a background process
# independent of the trading platform.
#
# Usage:
#   ./run_collector.sh start    - Start collector in background
#   ./run_collector.sh stop     - Stop collector
#   ./run_collector.sh status   - Check if running
#   ./run_collector.sh logs     - Tail the log file
#   ./run_collector.sh restart  - Restart collector
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COLLECTOR_SCRIPT="$SCRIPT_DIR/collect_options_data.py"
PID_FILE="$PROJECT_DIR/state/collector.pid"
LOG_FILE="$PROJECT_DIR/logs/collector.log"

# Ensure directories exist
mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$PROJECT_DIR/state"
mkdir -p "$PROJECT_DIR/data/options"

# Activate virtual environment if exists
if [ -f "$PROJECT_DIR/../venv/bin/activate" ]; then
    source "$PROJECT_DIR/../venv/bin/activate"
elif [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

# Set Python path
export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"

start_collector() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Collector is already running (PID: $PID)"
            return 1
        fi
    fi
    
    echo "Starting options data collector..."
    cd "$PROJECT_DIR"
    
    # Run in background with nohup
    nohup python3 "$COLLECTOR_SCRIPT" --symbols NIFTY,BANKNIFTY --interval 60 >> "$LOG_FILE" 2>&1 &
    
    PID=$!
    echo $PID > "$PID_FILE"
    
    sleep 2
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Collector started successfully (PID: $PID)"
        echo "Logs: $LOG_FILE"
    else
        echo "Failed to start collector. Check logs: $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_collector() {
    if [ ! -f "$PID_FILE" ]; then
        echo "Collector is not running (no PID file)"
        return 0
    fi
    
    PID=$(cat "$PID_FILE")
    
    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo "Collector is not running (stale PID file)"
        rm -f "$PID_FILE"
        return 0
    fi
    
    echo "Stopping collector (PID: $PID)..."
    
    # Send SIGTERM for graceful shutdown
    kill -TERM "$PID" 2>/dev/null
    
    # Wait up to 30 seconds for graceful shutdown
    for i in {1..30}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            echo "Collector stopped gracefully"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done
    
    # Force kill if still running
    echo "Force killing collector..."
    kill -9 "$PID" 2>/dev/null
    rm -f "$PID_FILE"
    echo "Collector stopped"
}

status_collector() {
    if [ ! -f "$PID_FILE" ]; then
        echo "Collector is NOT running (no PID file)"
        return 1
    fi
    
    PID=$(cat "$PID_FILE")
    
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Collector is RUNNING (PID: $PID)"
        
        # Show some stats from log
        if [ -f "$LOG_FILE" ]; then
            echo ""
            echo "Recent activity:"
            tail -5 "$LOG_FILE"
        fi
        return 0
    else
        echo "Collector is NOT running (stale PID file)"
        rm -f "$PID_FILE"
        return 1
    fi
}

show_logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "No log file found at: $LOG_FILE"
    fi
}

case "$1" in
    start)
        start_collector
        ;;
    stop)
        stop_collector
        ;;
    restart)
        stop_collector
        sleep 2
        start_collector
        ;;
    status)
        status_collector
        ;;
    logs)
        show_logs
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start collector in background"
        echo "  stop    - Stop collector gracefully"
        echo "  restart - Restart collector"
        echo "  status  - Check if collector is running"
        echo "  logs    - Tail the collector log file"
        exit 1
        ;;
esac
