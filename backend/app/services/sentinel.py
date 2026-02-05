"""Sentinel Agent - Market Regime Detection for Trading System v2.0"""

from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from loguru import logger

from .base_agent import BaseAgent
from ..core.kite_client import KiteClient
from ..core.data_cache import DataCache
from ..config.settings import Settings
from ..config.constants import (
    NIFTY_TOKEN, BANKNIFTY_TOKEN, INDIA_VIX_TOKEN,
    INTERVAL_5MIN, INTERVAL_DAY, REGIME_LOOKBACK_DAYS
)
from ..config.thresholds import (
    ADX_RANGE_BOUND, ADX_TREND,
    RSI_OVERSOLD, RSI_OVERBOUGHT, RSI_NEUTRAL_LOW, RSI_NEUTRAL_HIGH,
    IV_LOW, IV_HIGH, IV_ENTRY_MIN,
    CORRELATION_THRESHOLD, CORRELATION_CHAOS,
    ML_OVERRIDE_PROBABILITY, EVENT_BLACKOUT_DAYS
)
from ..models.regime import RegimeType, RegimePacket, RegimeMetrics
from .technical import calculate_adx, calculate_rsi, calculate_atr, calculate_day_range
from .volatility import (
    calculate_iv_percentile, calculate_realized_vol, 
    calculate_correlation, detect_correlation_spike
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
        
        # 6. Classify regime
        regime, confidence = self._classify_regime(metrics, event_flag, correlations)
        
        # 7. ML override (if available)
        ml_regime, ml_probability = self._ml_classify(metrics) if self.ml_classifier else (None, 0.0)
        if ml_regime and ml_probability > ML_OVERRIDE_PROBABILITY:
            self.logger.info(f"ML override: {ml_regime} (prob={ml_probability:.2f})")
            regime = ml_regime
            confidence = ml_probability
        
        # 8. Determine approved universe
        approved_universe, disabled = self._get_approved_universe(correlations)
        
        # 9. Safety check
        is_safe, safety_reasons = self._safety_check(regime, metrics, event_flag, correlations)
        
        # 10. Build and return packet
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
        """Calculate all technical metrics."""
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
        # In production, fetch actual VIX data
        iv_percentile = self._calculate_iv_percentile(ohlcv_daily)
        
        # RV/ATR ratio
        rv_atr_ratio = current_rv / (current_atr / ohlcv_5min['close'].iloc[-1]) if current_atr > 0 else 1.0
        
        return RegimeMetrics(
            adx=float(current_adx) if not np.isnan(current_adx) else 15.0,
            rsi=float(current_rsi) if not np.isnan(current_rsi) else 50.0,
            iv_percentile=iv_percentile,
            realized_vol=float(current_rv) if not np.isnan(current_rv) else 0.15,
            atr=float(current_atr) if not np.isnan(current_atr) else 0.0,
            rv_atr_ratio=float(rv_atr_ratio) if not np.isnan(rv_atr_ratio) else 1.0,
            skew=None,  # Would need option chain data
            oi_change_pct=None  # Would need OI data
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
    ) -> Tuple[RegimeType, float]:
        """
        Classify market regime using rule-based logic.
        
        Priority:
        1. CHAOS (highest priority - safety first)
        2. RANGE_BOUND
        3. MEAN_REVERSION
        4. TREND
        """
        # CHAOS conditions (highest priority)
        if event_flag:
            return RegimeType.CHAOS, 0.9
        
        if metrics.iv_percentile > IV_HIGH:
            return RegimeType.CHAOS, 0.85
        
        # Check correlation spike
        if any(abs(v) > CORRELATION_CHAOS for v in correlations.values()):
            return RegimeType.CHAOS, 0.8
        
        # RANGE_BOUND: Low ADX, moderate IV, neutral RSI
        if (metrics.adx < ADX_RANGE_BOUND and 
            metrics.iv_percentile < IV_HIGH and
            RSI_NEUTRAL_LOW <= metrics.rsi <= RSI_NEUTRAL_HIGH):
            confidence = 1.0 - (metrics.adx / ADX_RANGE_BOUND) * 0.3
            return RegimeType.RANGE_BOUND, confidence
        
        # MEAN_REVERSION: Moderate ADX, extreme RSI
        if (ADX_RANGE_BOUND <= metrics.adx <= ADX_TREND and
            (metrics.rsi < RSI_OVERSOLD or metrics.rsi > RSI_OVERBOUGHT)):
            confidence = 0.7 + abs(metrics.rsi - 50) / 100
            return RegimeType.MEAN_REVERSION, min(confidence, 0.9)
        
        # TREND: High ADX
        if metrics.adx > ADX_TREND:
            confidence = min(0.6 + (metrics.adx - ADX_TREND) / 50, 0.95)
            return RegimeType.TREND, confidence
        
        # Default to MEAN_REVERSION with lower confidence
        return RegimeType.MEAN_REVERSION, 0.5
    
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
        correlations: Dict[str, float]
    ) -> Tuple[bool, List[str]]:
        """
        Perform safety checks.
        
        Returns:
            Tuple of (is_safe, list of reasons if not safe)
        """
        reasons = []
        
        if regime == RegimeType.CHAOS:
            reasons.append("CHAOS regime detected")
        
        if event_flag:
            reasons.append("Event blackout period")
        
        if metrics.iv_percentile > IV_HIGH:
            reasons.append(f"IV percentile too high: {metrics.iv_percentile:.1f}%")
        
        if any(abs(v) > CORRELATION_CHAOS for v in correlations.values()):
            reasons.append("Correlation spike detected")
        
        is_safe = len(reasons) == 0
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
