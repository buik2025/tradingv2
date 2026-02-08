"""
Greek Hedging Strategies - Advanced Risk Management.

Implements portfolio-level Greek management:
- Delta hedging: Keep portfolio delta neutral (target: -12% to +12%)
- Vega management: Prevent volatility overexposure (target: -35% to +35% of equity)
- Gamma management: Control convexity risk (target: <-0.15% of equity)
- Automatic rebalancing: When Greeks breach thresholds
"""

from typing import Optional, Dict, List, Tuple
from pydantic import BaseModel, Field
from enum import Enum
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class HedgeType(str, Enum):
    """Types of hedging strategies."""
    DELTA = "delta"
    VEGA = "vega"
    GAMMA = "gamma"
    DELTA_VEGA = "delta_vega"


class GreekMetrics(BaseModel):
    """Portfolio-level Greek metrics."""
    
    # Delta metrics
    portfolio_delta: float = Field(0.0, description="Sum of all position deltas")
    delta_notional: float = Field(0.0, description="Delta notional exposure in rupees")
    delta_pct_equity: float = Field(0.0, description="Delta as % of equity")
    delta_hedge_active: bool = Field(False, description="Delta hedge currently active")
    
    # Vega metrics
    portfolio_vega: float = Field(0.0, description="Sum of all position vegas")
    vega_notional: float = Field(0.0, description="Vega per 1% IV change")
    vega_pct_equity: float = Field(0.0, description="Vega as % of equity")
    vega_hedge_active: bool = Field(False, description="Vega hedge currently active")
    
    # Gamma metrics
    portfolio_gamma: float = Field(0.0, description="Sum of all position gammas")
    gamma_pct_equity: float = Field(0.0, description="Gamma as % of equity")
    gamma_risk_level: str = Field("normal", description="gamma risk level")
    
    # Theta metrics
    portfolio_theta: float = Field(0.0, description="Daily theta decay")
    theta_daily_rupees: float = Field(0.0, description="Daily theta in rupees")
    
    # Hedge tracking
    active_hedges: List[str] = Field(default_factory=list, description="Active hedges")
    last_rebalance: Optional[str] = Field(None, description="Last rebalance timestamp")
    rebalance_count: int = Field(0, description="Number of rebalances today")


class GreekHedgeRecommendation(BaseModel):
    """Recommendation for hedging action."""
    
    hedge_type: HedgeType
    reason: str
    current_value: float
    threshold: float
    suggested_action: str  # e.g., "Buy 5 OTM calls", "Sell 3 ATM strangles"
    estimated_cost: float
    hedging_ratio: float  # e.g., 0.5 for 50% hedge


class GreekHedger:
    """Manages Greek hedging for portfolio risk."""
    
    # Greek thresholds from v2_rulebook Section 5 & 6
    DELTA_MIN_THRESHOLD = -0.12  # -12% of equity
    DELTA_MAX_THRESHOLD = 0.12   # +12% of equity
    
    VEGA_MIN_THRESHOLD = -0.35   # -35% of equity
    VEGA_MAX_THRESHOLD = 0.35    # +35% of equity
    
    GAMMA_MAX_THRESHOLD = -0.0015  # -0.15% of equity
    
    # Short Greek caps (from Section 5)
    SHORT_VEGA_CAP = -0.60  # -60% of equity
    SHORT_GAMMA_CAP = -0.0015  # -0.15% of equity
    
    def __init__(self, equity: float = 100000.0):
        """Initialize Greek hedger.
        
        Args:
            equity: Current account equity
        """
        self.equity = equity
        self.metrics = GreekMetrics()
    
    def update_portfolio_greeks(self,
                               delta: float,
                               vega: float,
                               gamma: float,
                               theta: float) -> None:
        """Update portfolio Greek metrics.
        
        Args:
            delta: Sum of all position deltas
            vega: Sum of all position vegas
            gamma: Sum of all position gammas
            theta: Daily theta decay
        """
        self.metrics.portfolio_delta = delta
        self.metrics.portfolio_vega = vega
        self.metrics.portfolio_gamma = gamma
        self.metrics.portfolio_theta = theta
        
        # Calculate as % of equity
        self.metrics.delta_pct_equity = delta / self.equity
        self.metrics.vega_pct_equity = vega / self.equity
        self.metrics.gamma_pct_equity = gamma / self.equity
        self.metrics.theta_daily_rupees = theta
        
        # Log risk levels
        self._assess_greek_exposure()
    
    def _assess_greek_exposure(self) -> None:
        """Assess current Greek exposure levels."""
        # Delta assessment
        delta_pct = self.metrics.delta_pct_equity
        if delta_pct < self.DELTA_MIN_THRESHOLD or delta_pct > self.DELTA_MAX_THRESHOLD:
            logger.warning(
                f"⚠️ DELTA BREACH: {delta_pct:.1%} (threshold: ±{abs(self.DELTA_MAX_THRESHOLD):.1%})"
            )
        
        # Vega assessment
        vega_pct = self.metrics.vega_pct_equity
        if vega_pct < self.VEGA_MIN_THRESHOLD or vega_pct > self.VEGA_MAX_THRESHOLD:
            logger.warning(
                f"⚠️ VEGA BREACH: {vega_pct:.1%} (threshold: ±{abs(self.VEGA_MAX_THRESHOLD):.1%})"
            )
        
        # Gamma assessment (gamma is negative for short options, threshold is also negative)
        gamma_pct = self.metrics.gamma_pct_equity
        if gamma_pct < self.GAMMA_MAX_THRESHOLD:  # More negative than threshold
            self.metrics.gamma_risk_level = "high"
            logger.warning(
                f"⚠️ GAMMA RISK HIGH: {gamma_pct:.4f} (threshold: {self.GAMMA_MAX_THRESHOLD:.4f})"
            )
        else:
            self.metrics.gamma_risk_level = "normal"
    
    def get_hedging_recommendations(self) -> List[GreekHedgeRecommendation]:
        """Identify Greeks that need hedging.
        
        Returns:
            List of hedging recommendations
        """
        recommendations = []
        
        # Check Delta
        delta_pct = self.metrics.delta_pct_equity
        if delta_pct > self.DELTA_MAX_THRESHOLD:
            recommendations.append(
                GreekHedgeRecommendation(
                    hedge_type=HedgeType.DELTA,
                    reason=f"Portfolio delta {delta_pct:.1%} > {self.DELTA_MAX_THRESHOLD:.1%} (long bias)",
                    current_value=delta_pct,
                    threshold=self.DELTA_MAX_THRESHOLD,
                    suggested_action=f"Sell {int(abs(delta_pct * self.equity / 50))} OTM calls or buy puts",
                    estimated_cost=abs(delta_pct * self.equity * 0.01),  # Rough estimate: 1% of notional
                    hedging_ratio=0.5
                )
            )
        elif delta_pct < self.DELTA_MIN_THRESHOLD:
            recommendations.append(
                GreekHedgeRecommendation(
                    hedge_type=HedgeType.DELTA,
                    reason=f"Portfolio delta {delta_pct:.1%} < {self.DELTA_MIN_THRESHOLD:.1%} (short bias)",
                    current_value=delta_pct,
                    threshold=self.DELTA_MIN_THRESHOLD,
                    suggested_action=f"Buy {int(abs(delta_pct * self.equity / 50))} OTM calls or sell puts",
                    estimated_cost=abs(delta_pct * self.equity * 0.01),
                    hedging_ratio=0.5
                )
            )
        
        # Check Vega
        vega_pct = self.metrics.vega_pct_equity
        if vega_pct > self.VEGA_MAX_THRESHOLD:
            recommendations.append(
                GreekHedgeRecommendation(
                    hedge_type=HedgeType.VEGA,
                    reason=f"Portfolio vega {vega_pct:.1%} > {self.VEGA_MAX_THRESHOLD:.1%} (long vol)",
                    current_value=vega_pct,
                    threshold=self.VEGA_MAX_THRESHOLD,
                    suggested_action="Sell strangles or condors to reduce vega",
                    estimated_cost=abs(vega_pct * self.equity * 0.015),
                    hedging_ratio=0.75
                )
            )
        elif vega_pct < self.VEGA_MIN_THRESHOLD:
            recommendations.append(
                GreekHedgeRecommendation(
                    hedge_type=HedgeType.VEGA,
                    reason=f"Portfolio vega {vega_pct:.1%} < {self.VEGA_MIN_THRESHOLD:.1%} (short vol)",
                    current_value=vega_pct,
                    threshold=self.VEGA_MIN_THRESHOLD,
                    suggested_action="Buy strangles or spreads to increase vega",
                    estimated_cost=abs(vega_pct * self.equity * 0.015),
                    hedging_ratio=0.75
                )
            )
        
        # Check Gamma
        gamma_pct = self.metrics.gamma_pct_equity
        if gamma_pct < self.GAMMA_MAX_THRESHOLD:
            recommendations.append(
                GreekHedgeRecommendation(
                    hedge_type=HedgeType.GAMMA,
                    reason=f"Portfolio gamma {gamma_pct:.3%} < {self.GAMMA_MAX_THRESHOLD:.3%} (negative gamma risk)",
                    current_value=gamma_pct,
                    threshold=self.GAMMA_MAX_THRESHOLD,
                    suggested_action="Buy options (calls/puts) to reduce negative gamma",
                    estimated_cost=abs(gamma_pct * self.equity * 0.02),
                    hedging_ratio=0.5
                )
            )
        
        return recommendations
    
    def should_rebalance(self) -> bool:
        """Check if Greeks require immediate rebalancing.
        
        Returns:
            True if rebalancing needed
        """
        recommendations = self.get_hedging_recommendations()
        return len(recommendations) > 0
    
    def execute_delta_hedge(self, hedge_ratio: float = 0.5) -> Dict:
        """Execute delta hedge (neutralize long/short exposure).
        
        Args:
            hedge_ratio: How much delta to hedge (0.0-1.0)
            
        Returns:
            Hedge execution details
        """
        delta_pct = self.metrics.delta_pct_equity
        hedge_amount = delta_pct * hedge_ratio
        
        # In practice, this would execute trades to reduce delta by hedge_amount
        logger.info(
            f"📊 Executing delta hedge: current delta {delta_pct:.1%}, "
            f"hedging {hedge_ratio:.0%} ({hedge_amount:.1%})"
        )
        
        self.metrics.delta_hedge_active = True
        return {
            'hedge_type': 'delta',
            'current_delta': delta_pct,
            'hedge_ratio': hedge_ratio,
            'target_delta': delta_pct * (1 - hedge_ratio),
            'status': 'queued_for_execution'
        }
    
    def execute_vega_hedge(self, hedge_ratio: float = 0.75) -> Dict:
        """Execute vega hedge (neutralize volatility exposure).
        
        Args:
            hedge_ratio: How much vega to hedge (0.0-1.0)
            
        Returns:
            Hedge execution details
        """
        vega_pct = self.metrics.vega_pct_equity
        hedge_amount = vega_pct * hedge_ratio
        
        logger.info(
            f"📊 Executing vega hedge: current vega {vega_pct:.1%}, "
            f"hedging {hedge_ratio:.0%} ({hedge_amount:.1%})"
        )
        
        self.metrics.vega_hedge_active = True
        return {
            'hedge_type': 'vega',
            'current_vega': vega_pct,
            'hedge_ratio': hedge_ratio,
            'target_vega': vega_pct * (1 - hedge_ratio),
            'status': 'queued_for_execution'
        }
    
    def execute_gamma_hedge(self, hedge_ratio: float = 0.5) -> Dict:
        """Execute gamma hedge (reduce negative convexity risk).
        
        Args:
            hedge_ratio: How much gamma to hedge (0.0-1.0)
            
        Returns:
            Hedge execution details
        """
        gamma_pct = self.metrics.gamma_pct_equity
        hedge_amount = gamma_pct * hedge_ratio
        
        logger.info(
            f"📊 Executing gamma hedge: current gamma {gamma_pct:.3%}, "
            f"hedging {hedge_ratio:.0%} ({hedge_amount:.3%})"
        )
        
        return {
            'hedge_type': 'gamma',
            'current_gamma': gamma_pct,
            'hedge_ratio': hedge_ratio,
            'target_gamma': gamma_pct * (1 - hedge_ratio),
            'status': 'queued_for_execution'
        }
    
    def check_short_greek_caps(self) -> Dict[str, bool]:
        """Check if short Greek positions exceed caps (Section 5).
        
        Returns:
            Dictionary of cap breach status
        """
        breaches = {
            'short_vega_exceeded': self.metrics.vega_pct_equity < self.SHORT_VEGA_CAP,
            'short_gamma_exceeded': self.metrics.gamma_pct_equity < self.SHORT_GAMMA_CAP,
        }
        
        if breaches['short_vega_exceeded']:
            logger.error(
                f"❌ SHORT VEGA CAP EXCEEDED: {self.metrics.vega_pct_equity:.1%} "
                f"< {self.SHORT_VEGA_CAP:.1%}"
            )
        
        if breaches['short_gamma_exceeded']:
            logger.error(
                f"❌ SHORT GAMMA CAP EXCEEDED: {self.metrics.gamma_pct_equity:.3%} "
                f"< {self.SHORT_GAMMA_CAP:.3%}"
            )
        
        return breaches
    
    def get_status(self) -> Dict:
        """Get current Greek hedging status.
        
        Returns:
            Status dictionary
        """
        caps_breached = self.check_short_greek_caps()
        recommendations = self.get_hedging_recommendations()
        
        return {
            'portfolio_delta': f"{self.metrics.delta_pct_equity:.1%}",
            'portfolio_vega': f"{self.metrics.vega_pct_equity:.1%}",
            'portfolio_gamma': f"{self.metrics.gamma_pct_equity:.3%}",
            'daily_theta': f"₹{self.metrics.theta_daily_rupees:.0f}",
            'delta_hedge_active': self.metrics.delta_hedge_active,
            'vega_hedge_active': self.metrics.vega_hedge_active,
            'gamma_risk_level': self.metrics.gamma_risk_level,
            'caps_breached': caps_breached,
            'hedging_recommendations': len(recommendations),
            'needs_rebalance': self.should_rebalance()
        }
