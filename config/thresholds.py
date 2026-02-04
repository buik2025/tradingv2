"""Regime detection and risk thresholds for Trading System v2.0"""

# Regime Detection Thresholds
ADX_RANGE_BOUND = 12       # ADX < 12 = Range-bound
ADX_TREND = 22             # ADX > 22 = Trend
RSI_OVERSOLD = 30          # RSI < 30 = Oversold
RSI_OVERBOUGHT = 70        # RSI > 70 = Overbought
RSI_NEUTRAL_LOW = 40       # RSI 40-60 = Neutral
RSI_NEUTRAL_HIGH = 60

# IV Thresholds
IV_LOW = 35                # IV percentile < 35% = Low vol
IV_HIGH = 75               # IV percentile > 75% = High vol / Chaos
IV_ENTRY_MIN = 40          # Minimum IV for short-vol entries

# Correlation Thresholds
CORRELATION_THRESHOLD = 0.4   # |corr| > 0.4 = Disable secondary
CORRELATION_CHAOS = 0.5       # |corr| > 0.5 = Chaos signal

# ML Thresholds
ML_OVERRIDE_PROBABILITY = 0.7  # ML overrides rules if prob > 70%

# Risk Limits
MAX_MARGIN_PCT = 0.40          # Max 40% margin utilization
MAX_LOSS_PER_TRADE = 0.01      # Max 1% loss per trade
MAX_DAILY_LOSS = 0.03          # Max 3% daily loss
MAX_WEEKLY_LOSS = 0.05         # Max 5% weekly loss
MAX_MONTHLY_LOSS = 0.10        # Max 10% monthly loss
MAX_POSITIONS = 3              # Max concurrent positions

# Greeks Limits
MAX_DELTA = 30                 # Portfolio delta limit
MAX_GAMMA = 0.3                # Portfolio gamma limit
MAX_VEGA = 400                 # Portfolio vega limit

# Drawdown Response
DRAWDOWN_LEVEL_1 = 0.05        # 5% drawdown = 50% size
DRAWDOWN_LEVEL_2 = 0.10        # 10% drawdown = 25% size
DRAWDOWN_LEVEL_3 = 0.15        # 15% drawdown = STOP trading
DRAWDOWN_MULTIPLIER_1 = 0.50
DRAWDOWN_MULTIPLIER_2 = 0.25
DRAWDOWN_MULTIPLIER_3 = 0.0

# Circuit Breaker - Flat Days
FLAT_DAYS_DAILY_LOSS = 1       # 1 flat day after daily loss hit
FLAT_DAYS_WEEKLY_LOSS = 3      # 3 flat days after weekly loss hit
FLAT_DAYS_MONTHLY_LOSS = 5     # 5 flat days after monthly loss hit

# Iron Condor Parameters
IC_SHORT_DELTA = 25            # Short strikes at 25-delta
IC_LONG_DELTA = 15             # Long strikes at 15-delta
IC_PROFIT_TARGET = 0.60        # Exit at 60% of max profit
IC_STOP_LOSS = 1.0             # Stop at 100% of credit (loss = credit)
IC_MIN_DTE = 10                # Minimum days to expiry for entry
IC_MAX_DTE = 12                # Maximum days to expiry for entry
IC_EXIT_DTE = 5                # Mandatory exit at T-5

# Entry Conditions
MAX_PREV_DAY_RANGE = 0.012     # Previous day range < 1.2%
MAX_GAP_PCT = 0.015            # No gaps > 1.5% in 3 days
EVENT_BLACKOUT_DAYS = 7        # No entries within 7 days of event

# Liquidity Filters
MIN_BID_ASK_SPREAD = 2.0       # Max bid-ask spread in INR
MIN_OPEN_INTEREST = 10000      # Minimum OI for strike selection

# Slippage and Costs
SLIPPAGE_PCT = 0.002           # 0.2% slippage assumption
BROKERAGE_PCT = 0.0003         # 0.03% brokerage
