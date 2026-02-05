import { useEffect, useState, useMemo } from 'react';
import { useTradingStore } from '@/stores/tradingStore';
import { MetricCard } from '@/components/dashboard/MetricCard';
import { RegimeCard } from '@/components/dashboard/RegimeCard';
import { QuickActions } from '@/components/dashboard/QuickActions';
import { formatCurrency } from '@/lib/utils';
import { IndianRupee, Briefcase, TrendingUp, Percent } from 'lucide-react';
import { accountApi, strategiesApi } from '@/services/api';
import { useWebSocket } from '@/hooks/useWebSocket';

export function Dashboard() {
  const { status, regime, positions, fetchStatus, fetchRegime, fetchPositions } = useTradingStore();
  const wsState = useWebSocket();
  const [marginData, setMarginData] = useState<{ used_margin: number; total_margin: number; margin_utilization_pct: number } | null>(null);
  const [winRate, setWinRate] = useState<number | null>(null);

  useEffect(() => {
    fetchStatus();
    fetchRegime();
    fetchPositions();
    fetchMarginData();
    fetchWinRate();

    const interval = setInterval(() => {
      fetchStatus();
      fetchRegime();
      fetchMarginData();
    }, 10000);

    return () => clearInterval(interval);
  }, [fetchStatus, fetchRegime, fetchPositions]);

  const fetchMarginData = async () => {
    try {
      const response = await accountApi.getSummary();
      setMarginData(response.data);
    } catch (error) {
      console.error('Failed to fetch margin data:', error);
    }
  };

  const fetchWinRate = async () => {
    try {
      const response = await strategiesApi.getPerformance();
      const data = response.data;
      if (data && data.by_strategy && data.by_strategy.length > 0) {
        const totalClosed = data.by_strategy.reduce((sum, s) => sum + s.closed_count, 0);
        const weightedWinRate = data.by_strategy.reduce((sum, s) => sum + (s.win_rate * s.closed_count), 0);
        if (totalClosed > 0) {
          setWinRate(weightedWinRate / totalClosed);
        }
      }
    } catch (error) {
      console.error('Failed to fetch win rate:', error);
    }
  };

  // Calculate real-time P&L from WebSocket data
  const livePositions = useMemo(() => {
    if (!wsState.positions || wsState.positions.length === 0) {
      return positions;
    }
    // Use WebSocket positions which have live prices
    return wsState.positions;
  }, [wsState.positions, positions]);

  const dailyPnl = status?.daily_pnl ?? 0;
  const openPositions = livePositions.length;
  const totalPnl = livePositions.reduce((sum, p) => sum + (p.pnl || 0), 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-[var(--muted-foreground)]">Overview of your trading activity</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Daily P&L"
          value={formatCurrency(dailyPnl || totalPnl)}
          icon={IndianRupee}
          trend={(dailyPnl || totalPnl) > 0 ? 'up' : (dailyPnl || totalPnl) < 0 ? 'down' : 'neutral'}
        />
        <MetricCard
          title="Open Positions"
          value={openPositions}
          subtitle={`${formatCurrency(totalPnl)} unrealized`}
          icon={Briefcase}
        />
        <MetricCard
          title="Win Rate"
          value={winRate !== null ? `${winRate.toFixed(1)}%` : '--'}
          subtitle="All time"
          icon={TrendingUp}
        />
        <MetricCard
          title="Margin Used"
          value={marginData ? `${marginData.margin_utilization_pct.toFixed(1)}%` : '--'}
          subtitle={marginData ? formatCurrency(marginData.used_margin) : undefined}
          icon={Percent}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <RegimeCard regime={regime} />
        </div>
        <div>
          <QuickActions />
        </div>
      </div>
    </div>
  );
}
