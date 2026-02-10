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
from ...config.constants import (
    NIFTY_TOKEN, BANKNIFTY_TOKEN, INDIA_VIX_TOKEN,
    INTERVAL_5MIN, INTERVAL_DAY, REGIME_LOOKBACK_DAYS
)
from ...config.thresholds import (
    ADX_RANGE_BOUND, ADX_MEAN_REVERSION_MAX, ADX_TREND_MIN,
    RSI_OVERSOLD, RSI_OVERBOUGHT, RSI_NEUTRAL_MIN, RSI_NEUTRAL_MAX,
    IV_PERCENTILE_SHORT_VOL, IV_PERCENTILE_STRANGLE, IV_PERCENTILE_CHAOS,
    IV_HIGH,
    CORRELATION_THRESHOLD, CORRELATION_CHAOS, CORRELATION_INTRA_EQUITY,
    ML_OVERRIDE_PROBABILITY, ML_CHAOS_PROBABILITY, EVENT_BLACKOUT_DAYS,
    MIN_CHAOS_TRIGGERS, MIN_CAUTION_TRIGGERS,
    BBW_RANGE_BOUND, BBW_EXPANSION,
    RV_IV_THETA_FRIENDLY, RV_IV_STRONG_THETA,
    VOLUME_SURGE, VOLUME_LOW,
    VIX_LOW_THRESHOLD, VIX_HIGH_THRESHOLD
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
    
    def __init__(
        self,
        kite: KiteClient,
        config: Settings,
        data_cache: Optional[DataCache] = None,
        ml_classifier: Optional[object] = None
    ):
        super().__init__(kite, config, name="Sentinel")
        self.data_cache = data_cache or DataCache()
        self.ml_classifier = ml_classifier
        
        # Event calendar (can be loaded from database)
        self._events: List[Dict] = []
        
        # Correlation tracking
        self._correlation_assets = {
            "NIFTY": NIFTY_TOKEN,
            "BANKNIFTY": BANKNIFTY_TOKEN,
        }
    
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
        
        # 6. Classify regime with confluence scoring
        regime, confidence, confluence = self._classify_regime(metrics, event_flag, correlations)
        
        # 7. ML override (if available) - require higher prob for CHAOS
        ml_regime, ml_probability = self._ml_classify(metrics) if self.ml_classifier else (None, 0.0)
        if ml_regime and ml_probability > ML_OVERRIDE_PROBABILITY:
            # For CHAOS, require higher probability to prevent false positives
            if ml_regime == RegimeType.CHAOS and ml_probability < ML_CHAOS_PROBABILITY:
                self.logger.info(f"ML CHAOS below threshold: {ml_probability:.2f} < {ML_CHAOS_PROBABILITY}")
            else:
                self.logger.info(f"ML override: {ml_regime} (prob={ml_probability:.2f})")
                regime = ml_regime
                confidence = ml_probability
        
        # 8. Determine approved universe
        approved_universe, disabled = self._get_approved_universe(correlations)
        
        # 9. Safety check (updated for confluence)
        is_safe, safety_reasons = self._safety_check(regime, metrics, event_flag, correlations, confluence)
        
        # 10. Build and return packet with confluence
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
        
        # Try cache first
        cached = self.data_cache.get(token, interval, from_date.date(), to_date.date())
        if cached is not None and not cached.empty:
            return cached
        
        # Fetch from API
        df = self.kite.fetch_historical_data(token, interval, from_date, to_date)
        
        if not df.empty:
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
        
        # IV percentile (using VIX as proxy if available)
        iv_percentile = self._calculate_iv_percentile(ohlcv_daily)
        
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
    
    def _calculate_iv_percentile(self, ohlcv_daily: pd.DataFrame) -> float:
        """
        Calculate IV percentile.
        In production, use actual VIX/IV data from option chain.
        Here we use realized vol as a proxy.
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
        ADX_CHAOS_LEVEL = 35
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
        
        Returns:
            Tuple of (event_flag, event_name, days_until_event)
        """
        today = date.today()
        
        for event in self._events:
            event_date = event.get("date")
            if isinstance(event_date, str):
                event_date = datetime.strptime(event_date, "%Y-%m-%d").date()
            
            days_until = (event_date - today).days
            
            if 0 <= days_until <= EVENT_BLACKOUT_DAYS:
                return True, event.get("name", "Unknown Event"), days_until
        
        return False, None, None
    
    def add_event(self, name: str, event_date: date, event_type: str = "OTHER") -> None:
        """Add an event to the calendar."""
        self._events.append({
            "name": name,
            "date": event_date,
            "type": event_type
        })
        self.logger.info(f"Added event: {name} on {event_date}")
    
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
                adx=0, rsi=50, iv_percentile=50,
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
