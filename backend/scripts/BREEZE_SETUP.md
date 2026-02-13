# ICICI Direct Breeze API - Data Download Setup

## Overview

The Breeze API from ICICI Direct provides:
- **10 years of historical market data**
- **1-second OHLCV data** for indices and stocks
- **Historical options and futures data**

## Prerequisites

### 1. Install breeze-connect

```bash
pip install breeze-connect
```

Or add to requirements.txt:
```
breeze-connect>=1.0.65
```

### 2. Get API Credentials

1. Go to [ICICI Direct API Portal](https://api.icicidirect.com/apiuser/home)
2. Register/Login to your ICICI Direct account
3. Create a new API application
4. Note down:
   - **API Key**
   - **API Secret**

### 3. Generate Session Token

The session token is generated through a login flow. Here's a helper script:

```python
from breeze_connect import BreezeConnect

api_key = "YOUR_API_KEY"
api_secret = "YOUR_API_SECRET"

breeze = BreezeConnect(api_key=api_key)

# This will print the login URL
print(breeze.generate_session(api_secret=api_secret, session_token=""))

# Visit the URL, login, and you'll get a session token in the redirect URL
# The session token is valid for the trading day
```

### 4. Set Environment Variables

Add to your `.env` file:

```bash
# ICICI Direct Breeze API
BREEZE_API_KEY=your_api_key_here
BREEZE_API_SECRET=your_api_secret_here
BREEZE_SESSION_TOKEN=your_session_token_here
```

## Usage

### Download Everything (Indices + Options + Futures)

```bash
cd backend/scripts
python download_breeze_data.py --all
```

### Download Only Indices (1-second data)

```bash
# Download 30 days of 1-second data for NIFTY, BANKNIFTY, FINNIFTY, VIX
python download_breeze_data.py --indices --days 30

# Download 60 days of 5-minute data
python download_breeze_data.py --indices --days 60 --interval 5minute
```

### Download Only Options

```bash
# Download options for 4 expiries, 10 strikes above/below spot
python download_breeze_data.py --options --expiries 4 --strikes 10

# Download 15 strikes each side for 2 expiries
python download_breeze_data.py --options --expiries 2 --strikes 15
```

### Download Specific Symbol

```bash
# Download only NIFTY index data
python download_breeze_data.py --symbol NIFTY --days 30

# Download BANKNIFTY options
python download_breeze_data.py --symbol BANKNIFTY --options
```

### Available Intervals

| Interval | Flag | Max History |
|----------|------|-------------|
| 1 second | `--interval 1second` | ~1 year |
| 1 minute | `--interval 1minute` | ~2 years |
| 5 minute | `--interval 5minute` | ~5 years |
| 30 minute | `--interval 30minute` | ~10 years |
| 1 day | `--interval 1day` | ~10 years |

## Output Structure

Data is saved to `backend/data/breeze/`:

```
data/breeze/
├── indices/
│   ├── NIFTY_1second.csv
│   ├── NIFTY_1second.parquet
│   ├── BANKNIFTY_1second.csv
│   ├── BANKNIFTY_1second.parquet
│   ├── FINNIFTY_1second.csv
│   ├── FINNIFTY_1second.parquet
│   ├── VIX_1second.csv
│   └── VIX_1second.parquet
├── options/
│   ├── NIFTY/
│   │   └── 1second/
│   │       ├── NIFTY_20260213_23000_CALL.parquet
│   │       ├── NIFTY_20260213_23000_PUT.parquet
│   │       └── ...
│   ├── BANKNIFTY/
│   └── FINNIFTY/
└── futures/
    ├── NIFTY/
    │   └── NIFTY_20260227_1second.parquet
    ├── BANKNIFTY/
    └── FINNIFTY/
```

## Data Format

### Index Data (CSV/Parquet)

| Column | Type | Description |
|--------|------|-------------|
| date | datetime | Timestamp |
| open | float | Open price |
| high | float | High price |
| low | float | Low price |
| close | float | Close price |
| volume | int | Volume |

### Options Data (Parquet)

Same columns as index data, with filename containing:
- Underlying (NIFTY, BANKNIFTY, FINNIFTY)
- Expiry date (YYYYMMDD)
- Strike price
- Option type (CALL/PUT)

## Rate Limits

Breeze API has rate limits. The script handles this with:
- 0.5 second delay between API calls
- Automatic retry on failures (3 attempts)
- Chunked downloads for large date ranges

## Troubleshooting

### "Session expired" Error

The session token expires at end of trading day. Generate a new one:
1. Run the session generation script
2. Update `BREEZE_SESSION_TOKEN` in `.env`

### "Invalid API Key" Error

1. Verify API key is correct
2. Check if API subscription is active on ICICI Direct portal

### No Data Returned

1. Check if market was open on requested dates
2. Verify the symbol/strike exists
3. Try a smaller date range

### Rate Limit Exceeded

The script has built-in rate limiting. If you still hit limits:
1. Increase `RATE_LIMIT_DELAY` in the script
2. Download in smaller batches

## Integration with Trading System

The downloaded data can be used for:

1. **Backtesting**: Load parquet files in the backtest engine
2. **ML Training**: Use 1-second data for regime classification
3. **Strategy Development**: Analyze historical options behavior

Example loading data:
```python
import pandas as pd

# Load index data
nifty = pd.read_parquet("data/breeze/indices/NIFTY_1second.parquet")

# Load options data
option = pd.read_parquet("data/breeze/options/NIFTY/1second/NIFTY_20260213_23000_CALL.parquet")
```
