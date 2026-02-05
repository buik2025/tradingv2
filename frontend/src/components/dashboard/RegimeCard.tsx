import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { Regime } from '@/types';
import { Activity, TrendingUp, Repeat, AlertTriangle } from 'lucide-react';

const regimeConfig: Record<string, { color: string; icon: typeof Activity; label: string }> = {
  RANGE_BOUND: { color: 'var(--regime-range)', icon: Repeat, label: 'Range Bound' },
  MEAN_REVERSION: { color: 'var(--regime-mean-rev)', icon: Activity, label: 'Mean Reversion' },
  TREND: { color: 'var(--regime-trend)', icon: TrendingUp, label: 'Trending' },
  CHAOS: { color: 'var(--regime-chaos)', icon: AlertTriangle, label: 'Chaos' },
  UNKNOWN: { color: 'var(--muted-foreground)', icon: Activity, label: 'Unknown' },
};

interface RegimeCardProps {
  regime: Regime | null;
}

export function RegimeCard({ regime }: RegimeCardProps) {
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
          <div>
            <p className="text-xl font-bold" style={{ color: config.color }}>
              {config.label}
            </p>
            <p className="text-xs text-[var(--muted-foreground)]">
              Confidence: {(regime.confidence * 100).toFixed(0)}%
            </p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4 mt-4 pt-4 border-t border-[var(--border)]">
          <div>
            <p className="text-xs text-[var(--muted-foreground)]">ADX</p>
            <p className="font-medium">{regime.metrics.adx.toFixed(1)}</p>
          </div>
          <div>
            <p className="text-xs text-[var(--muted-foreground)]">RSI</p>
            <p className="font-medium">{regime.metrics.rsi.toFixed(1)}</p>
          </div>
          <div>
            <p className="text-xs text-[var(--muted-foreground)]">IV %ile</p>
            <p className="font-medium">{regime.metrics.iv_percentile.toFixed(0)}%</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
