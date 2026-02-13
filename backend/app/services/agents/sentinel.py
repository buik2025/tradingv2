"""Sentinel Agent - Market Regime Detection for Trading System v2.0"""

from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from loguru import logger

from .base_agent import BaseAgent
from ...core.kite_client import KiteClient
from ...core.data_cache import DataCache
from ...config.settings import Settings
from ..utilities.event_calendar import EventCalendar, get_event_calendar
from ...config.constants import (
    NIFTY_TOKEN, BANKNIFTY_TOKEN, INDIA_VIX_TOKEN,
    INTERVAL_5MIN, INTERVAL_DAY, REGIME_LOOKBACK_DAYS
)
from ...config.thresholds import (
    ADX_RANGE_BOUND, ADX_MEAN_REVERSION_MAX, ADX_TREND_MIN, ADX_CHAOS_LEVEL,
    RSI_OVERSOLD, RSI_OVERBOUGHT, RSI_NEUTRAL_MIN, RSI_NEUTRAL_MAX,
    IV_PERCENTILE_SHORT_VOL, IV_PERCENTILE_STRANGLE, IV_PERCENTILE_CHAOS,
    IV_HIGH,
    CORRELATION_THRESHOLD, CORRELATION_CHAOS, CORRELATION_INTRA_EQUITY,
    ML_OVERRIDE_PROBABILITY, ML_CHAOS_PROBABILITY, EVENT_BLACKOUT_DAYS,
    MIN_CHAOS_TRIGGERS, MIN_CAUTION_TRIGGERS,
    BBW_RANGE_BOUND, BBW_EXPANSION,
    RV_IV_THETA_FRIENDLY, RV_IV_STRONG_THETA,
    VOLUME_SURGE, VOLUME_LOW,
    VIX_LOW_THRESHOLD, VIX_HIGH_THRESHOLD,
    # v2.5 thresholds
    SUSTAINED_TRIGGER_DAYS, WARNING_TRIGGER_DAYS
)
from ...models.regime import RegimeType, RegimePacket, RegimeMetrics, ConfluenceScore
from ..indicators.technical import (
    calculate_adx, calculate_rsi, calculate_atr, calculate_day_range,
    calculate_bollinger_band_width, calculate_bbw_ratio, calculate_volume_ratio
)
from ..indicators.volatility import (
    calculate_iv_percentile, calculate_realized_vol, 
    calculate_correlation, detect_correlation_spike,
    calculate_rv_iv_ratio, detect_correlation_spike_dynamic
)
from ..indicators.dc import DirectionalChange
from ..indicators.smei import SMEICalculator
from ..indicators.hmm_helper import HMMRegimeClassifier, DCAlarmTracker
from collections import deque


class Sentinel(BaseAgent):
    """
    Market regime detection agent.
    
    Responsibilities:
    - Fetch and process market data
    - Calculate technical indicators (ADX, RSI, ATR)
    - Calculate volatility metrics (IV percentile, RV)
    - Detect correlations between assets
    - Check event calendar for blackout periods
    - Classify market regime using rules and ML
    - Produce RegimePacket for downstream agents
    """
    
    # v2.3 Config constants
    DC_THETA = 0.003  # 0.3% threshold for DC events
    DC_MIN_BAR_WINDOW = 5
    HMM_WINDOW = 20
    SMEI_WINDOW = 20
    DC_ALARM_P = 0.7  # Threshold for p_abnormal
    DC_ALARM_N = 3  # Consecutive events for alarm
    
    # Hybrid voting weights
    DC_WEIGHT = 0.5
    SIMPLE_WEIGHT = 0.2
    ML_WEIGHT = 0.2
    SENTIMENT_WEIGHT = 0.1
    
    def __init__(
        self,
        kite: KiteClient,
        config: Settings,
        data_cache: Optional[DataCache] = None,
        ml_classifier: Optional[object] = None
    ):
        super().__init__(kite, config, name="Sentinel")
        # If data_cache is explicitly None, don't create one (for backtesting)
        # This forces fetching from kite (HistoricalDataClient) instead of disk
        self.data_cache = data_cache
        self.ml_classifier = ml_classifier
        
        # Event calendar - now uses EventCalendar service
        self._event_calendar = get_event_calendar()
        
        # Correlation tracking
        self._correlation_assets = {
            "NIFTY": NIFTY_TOKEN,
            "BANKNIFTY": BANKNIFTY_TOKEN,
        }
        
        # v2.3: DC, HMM, SMEI components
        self._dc = DirectionalChange(theta=self.DC_THETA, min_bar_window=self.DC_MIN_BAR_WINDOW)
        self._hmm = HMMRegimeClassifier(window=self.HMM_WINDOW)
        self._smei = SMEICalculator(window=self.SMEI_WINDOW)
        self._dc_alarm = DCAlarmTracker(p_threshold=self.DC_ALARM_P, n_consecutive=self.DC_ALARM_N)
        self._dc_event_buffer: deque = deque(maxlen=5)
        self._last_output: Dict = {}
        
        # v2.5: Sustained trigger counter (Ref L/N)
        self._chaos_trigger_days: int = 0
        self._last_chaos_date: Optional[datetime] = None
    
    def process(self, instrument_token: int = NIFTY_TOKEN) -> RegimePacket:
        """
        Main regime detection process.
        
        Args:
            instrument_token: Token to analyze (default: NIFTY)
            
        Returns:
            RegimePacket with complete regime assessment
        """
        self.logger.info(f"Processing regime detection for token {instrument_token}")
        
        # 1. Fetch market data
        ohlcv_5min = self._fetch_ohlcv(instrument_token, INTERVAL_5MIN, REGIME_LOOKBACK_DAYS)
        ohlcv_daily = self._fetch_ohlcv(instrument_token, INTERVAL_DAY, 252)  # 1 year for IV percentile
        
        if ohlcv_5min.empty:
            self.logger.warning("No data available, returning UNKNOWN regime")
            return self._create_unknown_packet(instrument_token)
        
        # 2. Calculate technical indicators
        metrics = self._calculate_metrics(ohlcv_5min, ohlcv_daily)
        
        # 3. Get current price context
        spot_price = ohlcv_5min['close'].iloc[-1]
        prev_close = ohlcv_daily['close'].iloc[-2] if len(ohlcv_daily) > 1 else spot_price
        day_high = ohlcv_5min['high'].max()  # Today's high from 5min data
        day_low = ohlcv_5min['low'].min()
        day_range_pct = (day_high - day_low) / spot_price
        gap_pct = (ohlcv_5min['open'].iloc[0] - prev_close) / prev_close if prev_close > 0 else 0
        
        # 4. Check events
        event_flag, event_name, event_days = self._check_events()
        
        # 5. Calculate correlations
        correlations = self._calculate_correlations(instrument_token)
        correlation_alert = any(abs(v) > CORRELATION_THRESHOLD for v in correlations.values())
        
        # 6. v2.3: DC event detection
        dc_indicators, p_abnormal = self._compute_dc_analysis(ohlcv_5min)
        
        # 7. v2.3: SMEI sentiment score
        smei_score = self._smei.compute_smei(ohlcv_daily)
        
        # 8. Classify regime with confluence scoring (simple classifier)
        regime, confidence, confluence = self._classify_regime(metrics, event_flag, correlations)
        
        # 9. ML override (if available) - require higher prob for CHAOS
        ml_regime, ml_probability = self._ml_classify(metrics) if self.ml_classifier else (None, 0.0)
        if ml_regime and ml_probability > ML_OVERRIDE_PROBABILITY:
            if ml_regime == RegimeType.CHAOS and ml_probability < ML_CHAOS_PROBABILITY:
                self.logger.info(f"ML CHAOS below threshold: {ml_probability:.2f} < {ML_CHAOS_PROBABILITY}")
            else:
                self.logger.info(f"ML override: {ml_regime} (prob={ml_probability:.2f})")
                regime = ml_regime
                confidence = ml_probability
        
        # 10. v2.3: Hybrid voting with DC/HMM/SMEI
        hybrid_vote = self._compute_hybrid_vote(
            p_abnormal=p_abnormal,
            simple_regime=regime,
            ml_chaos_prob=ml_probability if ml_regime == RegimeType.CHAOS else 0.0,
            smei_score=smei_score
        )
        
        # 11. v2.3: Check DC alarm (p_abnormal > 0.7 for 3+ consecutive events)
        dc_alarm_active = self._dc_alarm.update(p_abnormal)
        if dc_alarm_active:
            self.logger.warning(f"DC ALARM ACTIVE: p_abnormal={p_abnormal:.2f}, overriding to CHAOS")
            regime = RegimeType.CHAOS
            confidence = p_abnormal
        
        # 12. Determine approved universe
        approved_universe, disabled = self._get_approved_universe(correlations)
        
        # 13. Safety check (updated for confluence and DC alarm)
        is_safe, safety_reasons = self._safety_check(regime, metrics, event_flag, correlations, confluence)
        if dc_alarm_active:
            is_safe = False
            safety_reasons.append("DC alarm active: abnormal regime detected")
        
        # 14. v2.5: Sustained trigger counter (Ref L/N)
        veto_shortvol = False
        warning_state = False
        sustained_chaos_days = self._update_sustained_trigger_counter(
            regime, confluence, dc_alarm_active
        )
        
        # v2.5: Apply sustained trigger logic
        if sustained_chaos_days >= SUSTAINED_TRIGGER_DAYS:
            # 2+ consecutive days = full CHAOS veto
            veto_shortvol = True
            if regime not in [RegimeType.CHAOS, RegimeType.CAUTION]:
                regime = RegimeType.CAUTION
                safety_reasons.append(f"v2.5: Sustained chaos triggers ({sustained_chaos_days} days)")
            self.logger.warning(f"v2.5: VETO SHORT-VOL - {sustained_chaos_days} consecutive chaos days")
        elif sustained_chaos_days == WARNING_TRIGGER_DAYS:
            # Single day = WARNING (tighten size, don't veto)
            warning_state = True
            safety_reasons.append("v2.5: Warning state - single-day chaos trigger")
            self.logger.info(f"v2.5: WARNING STATE - single-day chaos trigger")
        
        # 15. Build and return packet with v2.5 fields
        packet = RegimePacket(
            timestamp=datetime.now(),
            instrument_token=instrument_token,
            symbol=self._get_symbol(instrument_token),
            regime=regime,
            regime_confidence=confidence,
            ml_regime=ml_regime,
            ml_probability=ml_probability,
            metrics=metrics,
            event_flag=event_flag,
            event_name=event_name,
            event_days=event_days,
            correlations=correlations,
            correlation_alert=correlation_alert,
            approved_universe=approved_universe,
            disabled_instruments=disabled,
            is_safe=is_safe,
            safety_reasons=safety_reasons,
            veto_shortvol=veto_shortvol,
            warning_state=warning_state,
            sustained_chaos_days=sustained_chaos_days,
            confluence=confluence,
            spot_price=spot_price,
            prev_close=prev_close,
            day_range_pct=day_range_pct,
            gap_pct=gap_pct
        )
        
        self.logger.info(f"Regime: {regime.value} (confidence={confidence:.2f}), safe={is_safe}")
        return packet
    
    def _fetch_ohlcv(
        self,
        token: int,
        interval: str,
        lookback_days: int
    ) -> pd.DataFrame:
        """Fetch OHLCV data with caching."""
        to_date = datetime.now()
        from_date = to_date - timedelta(days=lookback_days)
        
        # Try cache first (if cache is available)
        if self.data_cache is not None:
            cached = self.data_cache.get(token, interval, from_date.date(), to_date.date())
            if cached is not None and not cached.empty:
                return cached
        
        # Fetch from API (or HistoricalDataClient in backtest mode)
        df = self.kite.fetch_historical_data(token, interval, from_date, to_date)
        
        if not df.empty and self.data_cache is not None:
            self.data_cache.put(token, interval, df, from_date.date(), to_date.date())
        
        return df
    
    def _calculate_metrics(
        self,
        ohlcv_5min: pd.DataFrame,
        ohlcv_daily: pd.DataFrame
    ) -> RegimeMetrics:
        """Calculate all technical metrics including new BBW and RV/IV."""
        # ADX on 5-min data
        adx = calculate_adx(
            ohlcv_5min['high'],
            ohlcv_5min['low'],
            ohlcv_5min['close'],
            period=14
        )
        current_adx = adx.iloc[-1] if not adx.empty else 15.0
        
        # RSI on 5-min data
        rsi = calculate_rsi(ohlcv_5min['close'], period=14)
        current_rsi = rsi.iloc[-1] if not rsi.empty else 50.0
        
        # ATR on 5-min data
        atr = calculate_atr(
            ohlcv_5min['high'],
            ohlcv_5min['low'],
            ohlcv_5min['close'],
            period=14
        )
        current_atr = atr.iloc[-1] if not atr.empty else 0.0
        
        # Realized volatility on daily data
        rv = calculate_realized_vol(ohlcv_daily['close'], period=20, annualize=True)
        current_rv = rv.iloc[-1] if not rv.empty else 0.15
        
        # IV percentile using actual India VIX data
        iv_percentile, india_vix = self._calculate_iv_percentile(ohlcv_daily)
        
        # RV/ATR ratio
        rv_atr_ratio = current_rv / (current_atr / ohlcv_5min['close'].iloc[-1]) if current_atr > 0 else 1.0
        
        # NEW: Bollinger Band Width ratio
        bbw = calculate_bollinger_band_width(ohlcv_5min['close'], period=20)
        current_bbw = bbw.iloc[-1] if not bbw.empty else 0.02
        bbw_ratio = calculate_bbw_ratio(ohlcv_5min['close'], period=20, avg_period=20)
        current_bbw_ratio = bbw_ratio.iloc[-1] if not bbw_ratio.empty else 1.0
        
        # NEW: RV/IV ratio (vol overpriced if < 0.8)
        iv_decimal = iv_percentile / 100 * 0.3  # Convert percentile to approx IV
        rv_iv_ratio = current_rv / iv_decimal if iv_decimal > 0 else 1.0
        
        # NEW: Volume ratio
        volume_ratio = 1.0
        if 'volume' in ohlcv_5min.columns:
            vol_ratio = calculate_volume_ratio(ohlcv_5min['volume'], period=20)
            volume_ratio = vol_ratio.iloc[-1] if not vol_ratio.empty else 1.0
        
        return RegimeMetrics(
            adx=float(current_adx) if not np.isnan(current_adx) else 15.0,
            rsi=float(current_rsi) if not np.isnan(current_rsi) else 50.0,
            iv_percentile=iv_percentile,
            india_vix=india_vix,
            realized_vol=float(current_rv) if not np.isnan(current_rv) else 0.15,
            atr=float(current_atr) if not np.isnan(current_atr) else 0.0,
            rv_atr_ratio=float(rv_atr_ratio) if not np.isnan(rv_atr_ratio) else 1.0,
            skew=None,
            oi_change_pct=None,
            bbw=float(current_bbw) if not np.isnan(current_bbw) else 0.02,
            bbw_ratio=float(current_bbw_ratio) if not np.isnan(current_bbw_ratio) else 1.0,
            rv_iv_ratio=float(rv_iv_ratio) if not np.isnan(rv_iv_ratio) else 1.0,
            volume_ratio=float(volume_ratio) if not np.isnan(volume_ratio) else 1.0
        )
    
    def _calculate_iv_percentile(self, ohlcv_daily: pd.DataFrame) -> Tuple[float, Optional[float]]:
        """
        Calculate IV percentile/rank using actual India VIX data.
        
        Uses IV Rank formula which is more commonly used by platforms like Sensibull:
        IV Rank = (Current - 52wk Low) / (52wk High - 52wk Low) × 100
        
        This gives a more intuitive reading:
        - Low IV Rank (< 30%) = IV is near yearly lows, good for buying options
        - High IV Rank (> 70%) = IV is near yearly highs, good for selling options
        
        Returns:
            Tuple of (iv_percentile, current_vix_value)
        """
        try:
            # Fetch India VIX historical data (1 year for percentile calculation)
            vix_data = self._fetch_ohlcv(INDIA_VIX_TOKEN, INTERVAL_DAY, 252)
            
            if vix_data.empty or len(vix_data) < 20:
                self.logger.warning("Insufficient VIX data, falling back to proxy calculation")
                return self._calculate_iv_percentile_proxy(ohlcv_daily), None
            
            # Use VIX close prices
            vix_closes = vix_data['close']
            current_vix = float(vix_closes.iloc[-1])
            
            # Calculate IV Rank (more intuitive than percentile)
            # IV Rank = (Current - 52wk Low) / (52wk High - 52wk Low) × 100
            vix_low = float(vix_closes.min())
            vix_high = float(vix_closes.max())
            
            if vix_high - vix_low > 0:
                iv_rank = (current_vix - vix_low) / (vix_high - vix_low) * 100
            else:
                iv_rank = 50.0
            
            self.logger.debug(f"India VIX: {current_vix:.2f}, Range: {vix_low:.2f}-{vix_high:.2f}, IV Rank: {iv_rank:.1f}%")
            
            iv_rank_val = float(iv_rank) if not np.isnan(iv_rank) else 50.0
            return iv_rank_val, current_vix
            
        except Exception as e:
            self.logger.warning(f"Failed to calculate VIX-based IV percentile: {e}, using proxy")
            return self._calculate_iv_percentile_proxy(ohlcv_daily), None
    
    def _calculate_iv_percentile_proxy(self, ohlcv_daily: pd.DataFrame) -> float:
        """
        Fallback: Calculate IV percentile using Parkinson volatility as proxy.
        Used when India VIX data is unavailable.
        """
        if len(ohlcv_daily) < 20:
            return 50.0
        
        # Use Parkinson volatility as IV proxy
        log_hl = np.log(ohlcv_daily['high'] / ohlcv_daily['low'])
        vol = np.sqrt(1 / (4 * np.log(2)) * (log_hl ** 2))
        
        current_vol = vol.iloc[-1]
        percentile = (vol < current_vol).sum() / len(vol) * 100
        
        return float(percentile) if not np.isnan(percentile) else 50.0
    
    def _classify_regime(
        self,
        metrics: RegimeMetrics,
        event_flag: bool,
        correlations: Dict[str, float]
    ) -> Tuple[RegimeType, float, ConfluenceScore]:
        """
        Classify market regime using confluence-based logic.
        
        Key change: Require 3+ triggers for CHAOS to prevent false positives.
        2 triggers = CAUTION (allow hedged trades only).
        
        VIX-aware: High ADX with low VIX = TREND, not CHAOS.
        
        Priority:
        1. CHAOS (3+ triggers)
        2. CAUTION (2 triggers)
        3. RANGE_BOUND (low ADX + low BBW + neutral RSI)
        4. MEAN_REVERSION (moderate ADX + extreme RSI)
        5. TREND (high ADX)
        """
        confluence = ConfluenceScore()
        
        # Get current VIX level for context-aware chaos detection
        # Low VIX (<14) dampens chaos signals - market is calm even if trending
        # Use IV percentile as proxy: IV%ile < 70% generally means VIX is reasonable
        # IV%ile 63% with VIX at 12 is a calm trending market
        is_low_vix_environment = metrics.iv_percentile < IV_PERCENTILE_CHAOS  # < 75%
        
        # === CHAOS TRIGGERS (negative score) ===
        
        # 1. Event blackout
        confluence.add_trigger(
            name="Event Blackout",
            triggered=event_flag,
            value=1.0 if event_flag else 0.0,
            threshold=1.0,
            direction="equals",
            weight=2.0,
            is_chaos=True
        )
        
        # 2. IV percentile > 75%
        confluence.add_trigger(
            name="IV Percentile",
            triggered=metrics.iv_percentile > IV_PERCENTILE_CHAOS,
            value=metrics.iv_percentile,
            threshold=IV_PERCENTILE_CHAOS,
            direction="above",
            weight=1.5,
            is_chaos=True
        )
        
        # 3. Correlation spike (use higher threshold for intra-equity pairs like NIFTY-BANKNIFTY)
        # NIFTY-BANKNIFTY normally correlate at 0.85-0.95, so only trigger on extreme (>0.95)
        max_corr = max([abs(v) for v in correlations.values()], default=0)
        # Only trigger chaos if correlation exceeds 0.95 (truly abnormal) OR >0.85 with high VIX
        CORR_EXTREME_THRESHOLD = 0.95  # Truly abnormal correlation
        corr_chaos_triggered = max_corr > CORR_EXTREME_THRESHOLD or (
            max_corr > CORRELATION_INTRA_EQUITY and not is_low_vix_environment
        )
        confluence.add_trigger(
            name="Correlation Spike",
            triggered=corr_chaos_triggered,
            value=max_corr,
            threshold=CORR_EXTREME_THRESHOLD,
            direction="above",
            weight=1.0,
            is_chaos=True
        )
        
        # 4. ADX trigger for chaos - BUT only if VIX is also high
        # High ADX + Low VIX = clean TREND, not chaos
        # High ADX + High VIX = potential chaos/whipsaw
        # ADX_CHAOS_LEVEL = 35
        adx_chaos_triggered = metrics.adx > ADX_CHAOS_LEVEL and not is_low_vix_environment
        confluence.add_trigger(
            name="ADX Chaos",
            triggered=adx_chaos_triggered,
            value=metrics.adx,
            threshold=ADX_CHAOS_LEVEL,
            direction="above",
            weight=1.5,
            is_chaos=True
        )
        
        # 5. BBW expansion (vol expansion)
        bbw_ratio = metrics.bbw_ratio or 1.0
        confluence.add_trigger(
            name="BBW Expansion",
            triggered=bbw_ratio > BBW_EXPANSION,
            value=bbw_ratio,
            threshold=BBW_EXPANSION,
            direction="above",
            weight=1.0,
            is_chaos=True
        )
        
        # 6. Volume surge
        volume_ratio = metrics.volume_ratio or 1.0
        confluence.add_trigger(
            name="Volume Surge",
            triggered=volume_ratio > VOLUME_SURGE,
            value=volume_ratio,
            threshold=VOLUME_SURGE,
            direction="above",
            weight=0.5,
            is_chaos=True
        )
        
        # === RANGE-BOUND TRIGGERS (positive score) ===
        
        # 1. Low ADX
        confluence.add_trigger(
            name="Low ADX",
            triggered=metrics.adx < ADX_RANGE_BOUND,
            value=metrics.adx,
            threshold=ADX_RANGE_BOUND,
            direction="below",
            weight=1.5,
            is_range=True
        )
        
        # 2. Low BBW (range contraction)
        confluence.add_trigger(
            name="BBW Contraction",
            triggered=bbw_ratio < BBW_RANGE_BOUND,
            value=bbw_ratio,
            threshold=BBW_RANGE_BOUND,
            direction="below",
            weight=1.5,
            is_range=True
        )
        
        # 3. Neutral RSI
        rsi_neutral = RSI_NEUTRAL_MIN <= metrics.rsi <= RSI_NEUTRAL_MAX
        confluence.add_trigger(
            name="Neutral RSI",
            triggered=rsi_neutral,
            value=metrics.rsi,
            threshold=50.0,
            direction="neutral",
            weight=1.0,
            is_range=True
        )
        
        # 4. Low IV percentile (bonus for short-vol)
        confluence.add_trigger(
            name="Low IV Bonus",
            triggered=metrics.iv_percentile < IV_PERCENTILE_SHORT_VOL,
            value=metrics.iv_percentile,
            threshold=IV_PERCENTILE_SHORT_VOL,
            direction="below",
            weight=1.0,
            is_range=True
        )
        
        # 5. RV/IV ratio < 0.8 (theta-friendly)
        rv_iv = metrics.rv_iv_ratio or 1.0
        confluence.add_trigger(
            name="Theta Friendly",
            triggered=rv_iv < RV_IV_THETA_FRIENDLY,
            value=rv_iv,
            threshold=RV_IV_THETA_FRIENDLY,
            direction="below",
            weight=1.0,
            is_range=True
        )
        
        # 6. Low volume (no trend fuel)
        confluence.add_trigger(
            name="Low Volume",
            triggered=volume_ratio < VOLUME_LOW,
            value=volume_ratio,
            threshold=VOLUME_LOW,
            direction="below",
            weight=0.5,
            is_range=True
        )
        
        # === DETERMINE REGIME BASED ON CONFLUENCE ===
        
        chaos_count = confluence.chaos_triggers
        range_count = confluence.range_triggers
        
        self.logger.debug(
            f"Confluence: chaos_triggers={chaos_count}, range_triggers={range_count}, "
            f"score={confluence.total_score:.2f}"
        )
        
        # CHAOS: Require 3+ triggers (prevents false positives like Feb 5)
        if chaos_count >= MIN_CHAOS_TRIGGERS:
            confidence = min(0.7 + chaos_count * 0.1, 0.95)
            return RegimeType.CHAOS, confidence, confluence
        
        # CAUTION: 2 triggers = allow hedged trades only
        if chaos_count >= MIN_CAUTION_TRIGGERS:
            confidence = 0.6 + chaos_count * 0.1
            return RegimeType.CAUTION, confidence, confluence
        
        # RANGE_BOUND: Strong range signals (3+ range triggers, low chaos)
        if range_count >= 3 and chaos_count == 0:
            confidence = min(0.7 + range_count * 0.08, 0.95)
            return RegimeType.RANGE_BOUND, confidence, confluence
        
        # RANGE_BOUND: Moderate range signals with low IV bonus
        if (metrics.adx < ADX_RANGE_BOUND and 
            metrics.iv_percentile < IV_PERCENTILE_SHORT_VOL and
            RSI_NEUTRAL_MIN <= metrics.rsi <= RSI_NEUTRAL_MAX):
            confidence = 0.75
            return RegimeType.RANGE_BOUND, confidence, confluence
        
        # MEAN_REVERSION: Moderate ADX + extreme RSI
        if (ADX_RANGE_BOUND <= metrics.adx <= ADX_MEAN_REVERSION_MAX and
            (metrics.rsi < RSI_OVERSOLD or metrics.rsi > RSI_OVERBOUGHT)):
            confidence = 0.7 + abs(metrics.rsi - 50) / 100
            return RegimeType.MEAN_REVERSION, min(confidence, 0.9), confluence
        
        # TREND: High ADX but not chaos
        if metrics.adx > ADX_TREND_MIN:
            confidence = min(0.6 + (metrics.adx - ADX_TREND_MIN) / 50, 0.85)
            return RegimeType.TREND, confidence, confluence
        
        # Default: MEAN_REVERSION with moderate confidence
        return RegimeType.MEAN_REVERSION, 0.55, confluence
    
    def _ml_classify(self, metrics: RegimeMetrics) -> Tuple[Optional[RegimeType], float]:
        """
        Classify regime using ML model.
        
        Returns:
            Tuple of (predicted regime, probability)
        """
        if not self.ml_classifier:
            return None, 0.0
        
        try:
            # Prepare features
            features = np.array([[
                metrics.iv_percentile,
                metrics.adx,
                metrics.rsi,
                metrics.realized_vol,
                metrics.rv_atr_ratio
            ]])
            
            # Predict
            prediction = self.ml_classifier.predict(features)[0]
            probability = max(self.ml_classifier.predict_proba(features)[0])
            
            regime_map = {
                0: RegimeType.RANGE_BOUND,
                1: RegimeType.MEAN_REVERSION,
                2: RegimeType.TREND,
                3: RegimeType.CHAOS
            }
            
            return regime_map.get(prediction, RegimeType.UNKNOWN), probability
            
        except Exception as e:
            self.logger.warning(f"ML classification failed: {e}")
            return None, 0.0
    
    def _check_events(self) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Check for upcoming events within blackout period.
        
        Uses EventCalendar service for comprehensive event tracking including:
        - NSE/MCX holidays
        - RBI policy dates
        - US Fed FOMC meetings
        - Union Budget
        - Major earnings
        
        Returns:
            Tuple of (event_flag, event_name, days_until_event)
        """
        return self._event_calendar.check_blackout(blackout_days=EVENT_BLACKOUT_DAYS)
    
    def add_event(self, name: str, event_date: date, event_type: str = "OTHER") -> None:
        """Add an event to the calendar."""
        from ..utilities.event_calendar import EventType
        try:
            etype = EventType(event_type)
        except ValueError:
            etype = EventType.OTHER
        self._event_calendar.add_event(name, event_date, etype)
        self.logger.info(f"Added event: {name} on {event_date}")
    
    def get_upcoming_events(self, days_ahead: int = 14) -> List[Dict]:
        """Get upcoming events within specified days."""
        return self._event_calendar.get_upcoming_events(days_ahead)
    
    def is_trading_day(self, check_date: Optional[date] = None) -> bool:
        """Check if given date is a trading day."""
        return self._event_calendar.is_trading_day(check_date)
    
    def _compute_dc_analysis(self, ohlcv_5min: pd.DataFrame) -> Tuple[Dict, float]:
        """
        Compute DC event analysis and HMM probability.
        
        v2.3: Directional Change event detection with HMM regime classification.
        
        Args:
            ohlcv_5min: 5-minute OHLCV data
            
        Returns:
            Tuple of (dc_indicators dict, p_abnormal float)
        """
        dc_indicators = {
            'T': 0.0,
            'TMV': 0.5,
            'TAR': 0.0,
            'direction': 'none',
            'event_count': 0
        }
        p_abnormal = 0.0
        
        try:
            # Detect DC events
            dc_events_df = self._dc.compute_dc_events(ohlcv_5min)
            
            if not dc_events_df.empty:
                # Get last event indicators
                last_event = dc_events_df.iloc[-1]
                dc_indicators = {
                    'T': float(last_event['T']),
                    'TMV': float(last_event['TMV']),
                    'TAR': float(last_event['TAR']),
                    'direction': last_event['direction'],
                    'event_count': len(dc_events_df)
                }
                
                # Get normalized events for HMM
                normalized_events = self._dc.get_last_n_events(5)
                if normalized_events:
                    for event in normalized_events:
                        self._dc_event_buffer.append(event)
                    
                    # Update HMM and get probability
                    if len(self._dc_event_buffer) >= 3:
                        events_df = pd.DataFrame(list(self._dc_event_buffer))
                        _, p_abnormal = self._hmm.predict_proba(events_df)
                
                self.logger.debug(
                    f"DC: {len(dc_events_df)} events, last={dc_indicators['direction']}, "
                    f"p_abnormal={p_abnormal:.2f}"
                )
        except Exception as e:
            self.logger.warning(f"DC analysis failed: {e}")
        
        return dc_indicators, p_abnormal
    
    def _compute_hybrid_vote(
        self,
        p_abnormal: float,
        simple_regime: RegimeType,
        ml_chaos_prob: float,
        smei_score: float
    ) -> Dict:
        """
        Compute hybrid voting score from DC/HMM, simple classifier, ML, and SMEI.
        
        v2.3: Weighted voting per SENTINEL_DESIGN.md
        - DC/HMM: 50% weight
        - Simple (ADX-based): 20% weight
        - ML: 20% weight
        - Sentiment (SMEI): 10% weight
        
        Args:
            p_abnormal: HMM probability of abnormal state
            simple_regime: Regime from simple ADX-based classifier
            ml_chaos_prob: ML probability of chaos
            smei_score: SMEI sentiment score [-1, 1]
            
        Returns:
            Dict with vote scores and final assessment
        """
        # DC score: high p_abnormal = high abnormal score
        dc_score = p_abnormal
        
        # Simple score: CHAOS/CAUTION = high abnormal score
        if simple_regime == RegimeType.CHAOS:
            simple_score = 1.0
        elif simple_regime == RegimeType.CAUTION:
            simple_score = 0.6
        else:
            simple_score = 0.2
        
        # ML score: direct chaos probability
        ml_score = ml_chaos_prob
        
        # Sentiment score: extreme bearish = higher abnormal
        # SMEI < -0.5 is bearish, > 0.5 is bullish
        sentiment_score = max(0, -smei_score)  # Convert bearish to positive abnormal score
        
        # Weighted combination
        weighted_abnormal = (
            self.DC_WEIGHT * dc_score +
            self.SIMPLE_WEIGHT * simple_score +
            self.ML_WEIGHT * ml_score +
            self.SENTIMENT_WEIGHT * sentiment_score
        )
        
        # Confidence: agreement between voters
        scores = [dc_score, simple_score, ml_score, sentiment_score]
        confidence = 1.0 - np.std(scores)  # Higher agreement = higher confidence
        
        hybrid_vote = {
            'dc_score': dc_score,
            'simple_score': simple_score,
            'ml_score': ml_score,
            'sentiment_score': sentiment_score,
            'weighted_abnormal': weighted_abnormal,
            'confidence': confidence,
            'is_abnormal': weighted_abnormal > 0.5
        }
        
        return hybrid_vote
    
    def alarm_abnormal(self) -> bool:
        """
        Check if DC alarm is currently active.
        
        v2.3: Alarm triggers when p_abnormal > 0.7 for 3+ consecutive DC events.
        
        Returns:
            bool: True if alarm is active
        """
        return self._dc_alarm.is_alarm_active()
    
    def get_dc_status(self) -> Dict:
        """
        Get current DC/HMM status for logging and monitoring.
        
        Returns:
            Dict with DC indicators, p_abnormal, alarm status
        """
        current_event = self._dc.current_event()
        return {
            'current_event': current_event,
            'event_buffer_size': len(self._dc_event_buffer),
            'alarm_active': self._dc_alarm.is_alarm_active(),
            'consecutive_count': self._dc_alarm.get_consecutive_count(),
            'hmm_fitted': self._hmm._is_fitted
        }
    
    def reset_dc_state(self) -> None:
        """Reset DC/HMM state (for backtesting)."""
        self._dc.reset()
        self._hmm.reset()
        self._dc_alarm.reset()
        self._dc_event_buffer.clear()
        # v2.5: Reset sustained trigger counter
        self._chaos_trigger_days = 0
        self._last_chaos_date = None
        self.logger.info("DC/HMM state reset")
    
    def _update_sustained_trigger_counter(
        self,
        regime: RegimeType,
        confluence: ConfluenceScore,
        dc_alarm_active: bool
    ) -> int:
        """
        v2.5: Update sustained trigger counter (Ref L/N).
        
        Tracks consecutive days with chaos triggers. Single day = WARNING,
        2+ consecutive days = CHAOS veto for short-vol.
        
        Args:
            regime: Current regime classification
            confluence: Confluence score with trigger counts
            dc_alarm_active: Whether DC alarm is active
            
        Returns:
            Number of consecutive chaos trigger days
        """
        today = datetime.now().date()
        
        # Check if we have chaos triggers today
        has_chaos_triggers = (
            regime in [RegimeType.CHAOS, RegimeType.CAUTION] or
            dc_alarm_active or
            (confluence and confluence.chaos_triggers >= MIN_CAUTION_TRIGGERS)
        )
        
        if has_chaos_triggers:
            if self._last_chaos_date is None:
                # First chaos day
                self._chaos_trigger_days = 1
                self._last_chaos_date = today
            elif self._last_chaos_date == today:
                # Same day, already counted
                pass
            elif (today - self._last_chaos_date).days == 1:
                # Consecutive day
                self._chaos_trigger_days += 1
                self._last_chaos_date = today
            else:
                # Gap in days, reset counter
                self._chaos_trigger_days = 1
                self._last_chaos_date = today
        else:
            # No chaos triggers today, reset counter
            self._chaos_trigger_days = 0
            self._last_chaos_date = None
        
        return self._chaos_trigger_days
    
    def _calculate_correlations(self, primary_token: int) -> Dict[str, float]:
        """Calculate correlations with other assets."""
        correlations = {}
        
        # Get primary asset data
        primary_data = self._fetch_ohlcv(primary_token, INTERVAL_DAY, 30)
        if primary_data.empty:
            return correlations
        
        primary_returns = primary_data['close'].pct_change().dropna()
        
        for name, token in self._correlation_assets.items():
            if token == primary_token:
                continue
            
            asset_data = self._fetch_ohlcv(token, INTERVAL_DAY, 30)
            if asset_data.empty:
                continue
            
            asset_returns = asset_data['close'].pct_change().dropna()
            
            # Align data
            common_idx = primary_returns.index.intersection(asset_returns.index)
            if len(common_idx) < 10:
                continue
            
            corr = primary_returns.loc[common_idx].corr(asset_returns.loc[common_idx])
            if not np.isnan(corr):
                correlations[name] = float(corr)
        
        return correlations
    
    def _get_approved_universe(
        self,
        correlations: Dict[str, float]
    ) -> Tuple[List[str], List[str]]:
        """
        Determine approved trading universe based on correlations.
        
        Returns:
            Tuple of (approved_instruments, disabled_instruments)
        """
        approved = ["NIFTY"]  # Primary always approved
        disabled = []
        
        for name, corr in correlations.items():
            if abs(corr) > CORRELATION_THRESHOLD:
                disabled.append(name)
                self.logger.debug(f"{name} disabled due to correlation: {corr:.2f}")
            else:
                approved.append(name)
        
        return approved, disabled
    
    def _safety_check(
        self,
        regime: RegimeType,
        metrics: RegimeMetrics,
        event_flag: bool,
        correlations: Dict[str, float],
        confluence: ConfluenceScore
    ) -> Tuple[bool, List[str]]:
        """
        Perform safety checks with confluence awareness.
        
        Returns:
            Tuple of (is_safe, list of reasons if not safe)
        """
        reasons = []
        
        # CHAOS is always unsafe
        if regime == RegimeType.CHAOS:
            reasons.append(f"CHAOS regime ({confluence.chaos_triggers} triggers)")
        
        # CAUTION allows hedged trades but flags as partially unsafe
        if regime == RegimeType.CAUTION:
            reasons.append(f"CAUTION regime ({confluence.chaos_triggers} triggers) - hedged trades only")
        
        if event_flag:
            reasons.append("Event blackout period")
        
        if metrics.iv_percentile > IV_HIGH:
            reasons.append(f"IV percentile too high: {metrics.iv_percentile:.1f}%")
        
        # Only flag correlation if it's a true spike (part of confluence)
        max_corr = max([abs(v) for v in correlations.values()], default=0)
        if max_corr > CORRELATION_INTRA_EQUITY and confluence.chaos_triggers >= MIN_CAUTION_TRIGGERS:
            reasons.append(f"Correlation spike: {max_corr:.2f}")
        
        # Safe if RANGE_BOUND or MEAN_REVERSION with no major issues
        # TREND is also safe if ADX > 25 (strong trend)
        safe_regimes = [RegimeType.RANGE_BOUND, RegimeType.MEAN_REVERSION]
        if regime == RegimeType.TREND and metrics.adx > 25:
            safe_regimes.append(RegimeType.TREND)
            
        is_safe = regime in safe_regimes and not event_flag
        
        return is_safe, reasons
    
    def _get_symbol(self, token: int) -> str:
        """Get symbol name for token."""
        token_map = {
            NIFTY_TOKEN: "NIFTY",
            BANKNIFTY_TOKEN: "BANKNIFTY",
            INDIA_VIX_TOKEN: "INDIAVIX"
        }
        return token_map.get(token, f"TOKEN_{token}")
    
    def _create_unknown_packet(self, token: int) -> RegimePacket:
        """Create a default UNKNOWN regime packet."""
        return RegimePacket(
            timestamp=datetime.now(),
            instrument_token=token,
            symbol=self._get_symbol(token),
            regime=RegimeType.UNKNOWN,
            regime_confidence=0.0,
            metrics=RegimeMetrics(
                adx=0, rsi=50, iv_percentile=50, india_vix=None,
                realized_vol=0.15, atr=0, rv_atr_ratio=1.0
            ),
            correlations={},
            approved_universe=[],
            is_safe=False,
            safety_reasons=["No data available"],
            spot_price=0,
            prev_close=0,
            day_range_pct=0
        )
