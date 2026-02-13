import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { Regime } from '@/types';
import { Activity, TrendingUp, Repeat, AlertTriangle, ChevronDown, ChevronUp, CheckCircle2, XCircle, AlertCircle } from 'lucide-react';

const regimeConfig: Record<string, { color: string; icon: typeof Activity; label: string }> = {
  RANGE_BOUND: { color: 'var(--regime-range)', icon: Repeat, label: 'Range Bound' },
  MEAN_REVERSION: { color: 'var(--regime-mean-rev)', icon: Activity, label: 'Mean Reversion' },
  TREND: { color: 'var(--regime-trend)', icon: TrendingUp, label: 'Trending' },
  CHAOS: { color: 'var(--regime-chaos)', icon: AlertTriangle, label: 'Chaos' },
  UNKNOWN: { color: 'var(--muted-foreground)', icon: Activity, label: 'Unknown' },
};

const getResultIcon = (result: string) => {
  if (result === 'PASSED' || result === 'NEUTRAL' || result === 'LOW') {
    return <CheckCircle2 className="h-4 w-4 text-[var(--profit)]" />;
  }
  if (result === 'TRIGGERED' || result === 'HIGH') {
    return <XCircle className="h-4 w-4 text-[var(--loss)]" />;
  }
  return <AlertCircle className="h-4 w-4 text-[var(--warning)]" />;
};

const getResultColor = (result: string) => {
  if (result === 'PASSED' || result === 'NEUTRAL' || result === 'LOW') return 'text-[var(--profit)]';
  if (result === 'TRIGGERED' || result === 'HIGH') return 'text-[var(--loss)]';
  return 'text-[var(--warning)]';
};

interface RegimeCardProps {
  regime: Regime | null;
}

export function RegimeCard({ regime }: RegimeCardProps) {
  const [showExplanation, setShowExplanation] = useState(false);

  if (!regime) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Market Regime</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-[var(--muted-foreground)]">Loading...</p>
        </CardContent>
      </Card>
    );
  }

  const config = regimeConfig[regime.regime] || regimeConfig.UNKNOWN;
  const Icon = config.icon;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Market Regime</CardTitle>
          <Badge variant={regime.is_safe ? 'success' : 'destructive'}>
            {regime.is_safe ? 'SAFE' : 'UNSAFE'}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-3">
          <div 
            className="p-3 rounded-lg" 
            style={{ backgroundColor: `${config.color}20` }}
          >
            <Icon className="h-6 w-6" style={{ color: config.color }} />
          </div>
          <div className="flex-1">
            <p className="text-xl font-bold" style={{ color: config.color }}>
              {config.label}
            </p>
            <p className="text-xs text-[var(--muted-foreground)]">
              Confidence: {(regime.confidence * 100).toFixed(0)}%
            </p>
          </div>
          <button
            onClick={() => setShowExplanation(!showExplanation)}
            className="p-2 hover:bg-[var(--muted)] rounded-lg transition-colors"
            title={showExplanation ? 'Hide explanation' : 'Show why this regime'}
          >
            {showExplanation ? (
              <ChevronUp className="h-5 w-5 text-[var(--muted-foreground)]" />
            ) : (
              <ChevronDown className="h-5 w-5 text-[var(--muted-foreground)]" />
            )}
          </button>
        </div>

        {/* Metrics Summary */}
        <div className="grid grid-cols-3 gap-4 mt-4 pt-4 border-t border-[var(--border)]">
          <div>
            <p className="text-xs text-[var(--muted-foreground)]">ADX</p>
            <p className="font-medium">{regime.metrics.adx.toFixed(1)}</p>
            {regime.thresholds && (
              <p className="text-[10px] text-[var(--muted-foreground)]">
                &lt;{regime.thresholds.adx_range_bound} range, &gt;{regime.thresholds.adx_trend} trend
              </p>
            )}
          </div>
          <div>
            <p className="text-xs text-[var(--muted-foreground)]">RSI</p>
            <p className="font-medium">{regime.metrics.rsi.toFixed(1)}</p>
            {regime.thresholds && (
              <p className="text-[10px] text-[var(--muted-foreground)]">
                {regime.thresholds.rsi_neutral_low}-{regime.thresholds.rsi_neutral_high} neutral
              </p>
            )}
          </div>
          <div>
            <p className="text-xs text-[var(--muted-foreground)]">IV Rank</p>
            <p className="font-medium">{regime.metrics.iv_percentile.toFixed(0)}%</p>
            {regime.metrics.india_vix && (
              <p className="text-[10px] text-[var(--muted-foreground)]">
                VIX: {regime.metrics.india_vix.toFixed(1)}
              </p>
            )}
            {!regime.metrics.india_vix && regime.thresholds && (
              <p className="text-[10px] text-[var(--muted-foreground)]">
                &gt;{regime.thresholds.iv_high}% = chaos
              </p>
            )}
          </div>
        </div>

        {/* Detailed Explanation */}
        {showExplanation && regime.explanation && (
          <div className="mt-4 pt-4 border-t border-[var(--border)]">
            <p className="text-xs font-medium text-[var(--muted-foreground)] mb-3">Classification Steps</p>
            <div className="space-y-2">
              {regime.explanation.steps.map((step) => (
                <div 
                  key={step.step} 
                  className="flex items-start gap-2 p-2 rounded-lg bg-[var(--muted)]/30"
                >
                  <div className="mt-0.5">{getResultIcon(step.result)}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium">{step.check}</span>
                      <span className={`text-xs font-bold ${getResultColor(step.result)}`}>
                        {step.result}
                      </span>
                    </div>
                    <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                      {step.condition}
                    </p>
                    <p className="text-[10px] text-[var(--foreground)]/70 mt-0.5">
                      → {step.impact}
                    </p>
                  </div>
                </div>
              ))}
            </div>

            {/* Decision Summary */}
            <div className="mt-3 p-3 rounded-lg" style={{ backgroundColor: `${config.color}15` }}>
              <p className="text-xs font-medium" style={{ color: config.color }}>
                Decision
              </p>
              <p className="text-sm mt-1">{regime.explanation.decision}</p>
            </div>

            {/* Safety Reasons */}
            {regime.safety_reasons && regime.safety_reasons.length > 0 && (
              <div className="mt-3 p-3 rounded-lg bg-[var(--loss)]/10">
                <p className="text-xs font-medium text-[var(--loss)]">Safety Concerns</p>
                <ul className="mt-1 space-y-1">
                  {regime.safety_reasons.map((reason, idx) => (
                    <li key={idx} className="text-xs text-[var(--loss)]">• {reason}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Correlations */}
            {regime.correlations && Object.keys(regime.correlations).length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-[var(--muted-foreground)] mb-1">Asset Correlations</p>
                <div className="flex gap-2">
                  {Object.entries(regime.correlations).map(([asset, corr]) => (
                    <span 
                      key={asset} 
                      className={`text-xs px-2 py-1 rounded ${Math.abs(corr) > 0.5 ? 'bg-[var(--loss)]/20 text-[var(--loss)]' : 'bg-[var(--muted)]'}`}
                    >
                      {asset}: {(corr * 100).toFixed(0)}%
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
