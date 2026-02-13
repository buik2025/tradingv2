"""Regime detection and risk thresholds for Trading System v2.0"""

# Regime Detection Thresholds (Revised per Grok Feb 5 2026 analysis)
ADX_RANGE_BOUND = 12       # ADX < 12 = Range-bound (lowered from 14 for safety)
ADX_MEAN_REVERSION_MAX = 25    # ADX 12-25 = Mean-reversion
ADX_TREND_MIN = 25             # ADX > 25 = Trend
ADX_CHAOS_LEVEL = 60

RSI_NEUTRAL_MIN = 35       # RSI 35-65 = Neutral (widened from 40-60)
RSI_NEUTRAL_MAX = 65
RSI_OVERSOLD = 35          # RSI < 35 = Oversold signal
RSI_OVERBOUGHT = 65        # RSI > 65 = Overbought signal

# IV Thresholds
IV_PERCENTILE_SHORT_VOL = 35   # IV < 35% = Short vol allowed (lowered from 40%)
IV_PERCENTILE_STRANGLE = 15    # IV < 15% = Ultra-low vol (Strangle zone)
IV_PERCENTILE_CHAOS = 75       # IV > 75% = Chaos exclusion
IV_HIGH = 70                     # IV > 70% = High Volatility (Safety check)

# Correlation Thresholds (Differentiated by asset type)
CORRELATION_THRESHOLD = 0.4      # |corr| > 0.4 = Disable secondary
CORRELATION_INTRA_EQUITY = 0.85  # NIFTY-BANKNIFTY-SENSEX (raised to 0.85 - normal range is 0.85-0.95)
CORRELATION_MULTI_ASSET = 0.4    # NIFTY-Gold/Crude
CORRELATION_CHAOS = 0.85         # |corr| > 0.85 = Chaos signal (only with confirmation)

# VIX-based Chaos Dampening (NEW)
VIX_LOW_THRESHOLD = 14           # VIX < 14 = Low vol environment, dampen chaos signals
VIX_HIGH_THRESHOLD = 20          # VIX > 20 = High vol, chaos signals more valid

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

# Risk Limits (v2.5: adjusted margin to 40%)
MAX_MARGIN_PCT = 0.40          # Max 40% margin utilization (relaxed from 20%)
MAX_LOSS_PER_TRADE = 0.015     # Max 1.5% loss per trade (raised from 1% per Grok Feb 5)
MAX_DAILY_LOSS = 0.015         # Max 1.5% daily loss (tightened from 3% per Grok Feb 5)
MAX_WEEKLY_LOSS = 0.05         # Max 5% weekly loss
MAX_MONTHLY_LOSS = 0.08        # Max 8% monthly loss (v2.5: tightened from 10%)
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

# Iron Condor Parameters (v2.5: 30-delta shorts)
IC_SHORT_DELTA = 30            # Short strikes at 30-delta (v2.5)
IC_LONG_DELTA = 15             # Long strikes at 15-delta
IC_PROFIT_TARGET = 0.60        # Exit at 60% of max profit
IC_STOP_LOSS = 1.0             # Stop at 100% of credit (loss = credit)
IC_MIN_DTE = 10                # Minimum days to expiry for entry
IC_MAX_DTE = 45                # Max DTE (widened for monthly)
IC_EXIT_DTE = 5                # Mandatory exit at T-5

# Strangle Strategy (Per tradingv2.md)
STRANGLE_DELTA_TARGET = 0.30   # Target delta for strangles
STRANGLE_PROFIT_TARGET = 0.008 # 0.8% of margin (min)
STRANGLE_PROFIT_TARGET_MAX = 0.01 # 1% of margin (max)

# Risk Reversal Parameters (New)
RR_DELTA_TARGET = 0.25         # 25-delta for directional
RR_PROFIT_TARGET_MIN = 0.014   # 1.4% of margin
RR_PROFIT_TARGET_MAX = 0.022   # 2.2% of margin
RR_STOP_LOSS_MIN = 0.008       # 0.8% of margin
RR_STOP_LOSS_MAX = 0.012       # 1.2% of margin

# Entry Conditions
MAX_PREV_DAY_RANGE = 0.012     # Previous day range < 1.2%
MAX_GAP_PCT = 0.015            # No gaps > 1.5% in 3 days
EVENT_BLACKOUT_DAYS = 7        # No entries within 7 days of event

# Liquidity Filters
MIN_BID_ASK_SPREAD = 5.0       # Max bid-ask spread in INR (relaxed for paper trading)
MIN_OPEN_INTEREST = 1000       # Minimum OI for strike selection (lowered for paper trading)

# Slippage and Costs
SLIPPAGE_PCT = 0.002           # 0.2% slippage assumption
BROKERAGE_PCT = 0.0007         # 0.07% per order (not per trade value)

# Commission and taxes (percentage of turnover). Default 0.08% = 0.0008
COMMISSION_TAX_PCT = 0.0008

# Order-based cost model
# Charges are per ORDER, not per trade value
# If all legs of a strategy are placed in one order, charge once
# Entry order + Exit order = 2 orders per trade
COST_PER_ORDER_PCT = 0.0007    # 0.07% per order

# Trailing Profit Settings (NEW - Grok Feb 5)
TRAILING_BBW_THRESHOLD = 1.8   # Extend winners when BBW > 1.8x 20-day avg
TRAILING_PROFIT_MIN = 0.50     # Only trail if already at 50%+ of target profit
TRAILING_EXTENSION = 1.2       # Extend target by 20% when trailing

# Daily Brake Settings (NEW - Grok Feb 5)
DAILY_LOSS_BRAKE = 0.015       # -1.5% daily loss triggers brake
BRAKE_FLAT_DAYS = 1            # Flat for 1 day after brake triggered

# Lots Ramping Settings (NEW - Grok Feb 5)
LOTS_RAMP_THRESHOLD_1 = 1.10   # 10% equity growth -> 2 lots
LOTS_RAMP_THRESHOLD_2 = 1.25   # 25% equity growth -> 3 lots
MAX_LOTS = 3                   # Maximum lots per position

# Consecutive Losers Settings (Section 6 - v2 rulebook)
CONSECUTIVE_LOSERS_THRESHOLD = 3  # 3 consecutive losers triggers reduction
CONSECUTIVE_LOSERS_REDUCTION = 0.50  # Reduce size by 50%
CONSECUTIVE_LOSERS_FLAT_DAYS = 1  # Flat for 1 day after 3 losers

# Win-Based Sizing Cap (Section 7 - v2 rulebook)
WIN_STREAK_THRESHOLD = 3  # 3 consecutive wins triggers cap
WIN_STREAK_SIZE_CAP = 0.80  # Cap sizing at 80% after win streak

# Low-VIX Margin Bonus (Section 5 - v2 rulebook)
LOW_VIX_THRESHOLD = 14  # VIX < 14 = low volatility
LOW_VIX_MARGIN_BONUS = 0.10  # +10% margin allowance in low-vol

# Correlation-Based Diversification (Section 5 - v2 rulebook)
DIVERSIFICATION_CORR_THRESHOLD = 0.3  # Corr > 0.3 triggers diversification
DIVERSIFICATION_REDUCTION = 0.50  # Halve higher-vol asset size

# Slippage Alert Settings (Section 8 - v2 rulebook)
SLIPPAGE_ALERT_THRESHOLD = 0.005  # >0.5% slippage triggers alert
SLIPPAGE_AUTO_CORRECT_THRESHOLD = 0.01  # >1% slippage triggers auto-correct

# ============== v2.5 Rulebook Additions ==============

# Sustained Trigger Counter (Ref L/N)
SUSTAINED_TRIGGER_DAYS = 2     # Require 2 consecutive days for chaos veto
WARNING_TRIGGER_DAYS = 1       # Single day = WARNING (tighten size)

# Event Override (Ref J)
MIN_DTE_EVENT_OVERRIDE = 10    # Allow entry on event if DTE >= 10

# High-IV Boost (Ref K)
HIGH_IV_BOOST_THRESHOLD = 50   # IV %ile > 50 triggers boost
HIGH_IV_VIX_DELTA = 5          # VIX > avg + 5% triggers boost
HIGH_IV_TARGET_MIN = 0.018     # Boosted target: 1.8%
HIGH_IV_TARGET_MAX = 0.022     # Boosted target: 2.2%
HIGH_IV_ADJUST_THRESHOLD = -0.003  # Tighten adjust to -0.3% on high IV

# Skew Check (Ref M)
SKEW_THRESHOLD = 0.05          # Call IV > Put IV + 5% favors risk-reversals

# Kelly Sizing (v2.5)
KELLY_FRACTION_MIN = 0.5       # Start with 0.5x Kelly
KELLY_FRACTION_MAX = 0.7       # Max 0.7x Kelly
KELLY_DEFAULT_WIN_RATE = 0.60  # Default 60% win rate
KELLY_DEFAULT_WIN_AVG = 0.015  # Default avg win 1.5%
KELLY_DEFAULT_LOSS_AVG = 0.01  # Default avg loss 1.0%

# Psych Caps (v2.5)
PSYCH_DRAWDOWN_CAP = -0.02     # Cap to 1 lot if drawdown > -2%
PSYCH_SENTIMENT_CAP = -0.3     # Cap to 1 lot if sentiment < -0.3
WARNING_SIZE_CAP = 1           # Force 1 lot on warning state

# Chaos Flat Period (v2.5)
CHAOS_FLAT_HOURS = 48          # Flat 48hr after DC abnormal > 2 days

# Short-vol Targets (v2.5)
SHORT_VOL_TARGET_MIN = 0.014   # 1.4% target (low VIX)
SHORT_VOL_TARGET_MAX = 0.018   # 1.8% target (normal)
DIRECTIONAL_TARGET_MIN = 0.014 # 1.4% target
DIRECTIONAL_TARGET_MAX = 0.022 # 2.2% target

# Trailing (v2.5)
TRAILING_ACTIVATE_PCT = 0.50   # Activate at 50% of target
TRAILING_POST_ADJUST_TIGHTEN = 0.75  # Tighten to 75% after adjustment

# Max Concurrent Positions (v2.5)
MAX_NIFTY_POSITIONS = 2        # Max 2 NIFTY positions
MAX_SECONDARY_POSITIONS = 2    # Max 2 secondary positions
MIN_DTE_SHORTS = 3             # Avoid <3 days expiry for shorts
