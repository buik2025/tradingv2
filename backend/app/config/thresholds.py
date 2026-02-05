"""Regime detection and risk thresholds for Trading System v2.0"""

# Regime Detection Thresholds (Revised per Feb 5 2026 analysis)
ADX_RANGE_BOUND = 12       # ADX < 12 = Range-bound (low trend strength)
ADX_MEAN_REVERSION = 25    # ADX 12-25 = Mean-reversion zone (mild/noisy trends)
ADX_TREND = 25             # ADX > 25 = Trend (raised from 22)
ADX_CHAOS = 35             # ADX > 35 + vol spike = Chaos

RSI_OVERSOLD = 30          # RSI < 30 = Oversold
RSI_OVERBOUGHT = 70        # RSI > 70 = Overbought
RSI_NEUTRAL_LOW = 40       # RSI 40-60 = Neutral
RSI_NEUTRAL_HIGH = 60
RSI_EXTREME_LOW = 25       # RSI < 25 = Strong oversold for reversion
RSI_EXTREME_HIGH = 75      # RSI > 75 = Strong overbought for reversion

# IV Thresholds
IV_LOW = 35                # IV percentile < 35% = Low vol
IV_HIGH = 75               # IV percentile > 75% = High vol / Chaos
IV_ENTRY_MIN = 40          # Minimum IV for short-vol entries
IV_LOW_VOL_BONUS = 25      # IV < 25% = Override mild ADX/corr triggers

# Correlation Thresholds (Differentiated by asset type)
CORRELATION_THRESHOLD = 0.4      # |corr| > 0.4 = Disable secondary
CORRELATION_INTRA_EQUITY = 0.5   # NIFTY-BANKNIFTY-SENSEX (raised from 0.3)
CORRELATION_MULTI_ASSET = 0.4    # NIFTY-Gold/Crude
CORRELATION_CHAOS = 0.5          # |corr| > 0.5 = Chaos signal (only with confirmation)

# Confluence Requirements (NEW - prevents false positives)
MIN_CHAOS_TRIGGERS = 3           # Require 3+ triggers for CHAOS classification
MIN_CAUTION_TRIGGERS = 2         # 2 triggers = CAUTION (allow hedged trades)
REGIME_PERSISTENCE_MINUTES = 15  # Require 15 min confirmation before regime change

# Bollinger Band Width Thresholds (NEW)
BBW_RANGE_BOUND = 0.5            # BBW < 0.5x 20-day avg = Range confirmation
BBW_EXPANSION = 1.5              # BBW > 1.5x 20-day avg = Vol expansion

# RV/IV Ratio Thresholds (NEW)
RV_IV_THETA_FRIENDLY = 0.8       # RV < 0.8x IV = Vol overpriced, theta-friendly
RV_IV_STRONG_THETA = 0.7         # RV < 0.7x IV = Strong short-vol signal

# Volume Thresholds (NEW)
VOLUME_SURGE = 1.5               # Volume > 1.5x avg = Potential trend
VOLUME_LOW = 0.8                 # Volume < 0.8x avg = Range confirmation
OI_SURGE = 1.5                   # OI > 1.5x avg = Regime shift signal

# ML Thresholds
ML_OVERRIDE_PROBABILITY = 0.7    # ML overrides rules if prob > 70%
ML_CHAOS_PROBABILITY = 0.85      # Require 85% prob for CHAOS (raised from 70%)
ML_CAUTION_PROBABILITY = 0.75    # 75-85% prob = CAUTION mode

# Risk Limits
MAX_MARGIN_PCT = 0.40          # Max 40% margin utilization
MAX_LOSS_PER_TRADE = 0.01      # Max 1% loss per trade
MAX_DAILY_LOSS = 0.03          # Max 3% daily loss
MAX_WEEKLY_LOSS = 0.05         # Max 5% weekly loss
MAX_MONTHLY_LOSS = 0.10        # Max 10% monthly loss
MAX_POSITIONS = 10             # Max concurrent positions multiple strategies can have multiple positions. Aggregate margin requirement can be capped here to restrict position sizes.

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
