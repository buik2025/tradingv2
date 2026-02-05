import { useEffect, useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatCurrency, formatPercent } from '@/lib/utils';
import { ChevronDown, ChevronRight, RefreshCw, Wifi, WifiOff, Trash2 } from 'lucide-react';
import { strategiesApi, positionsApi, type Strategy, type PositionWithMargin } from '@/services/api';
import { useWebSocket } from '@/hooks/useWebSocket';
import { AccountSummary } from '@/components/AccountSummary';

export function StrategiesPage() {
  const [searchParams] = useSearchParams();
  const highlightId = searchParams.get('highlight');
  const wsState = useWebSocket();
  
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [positions, setPositions] = useState<PositionWithMargin[]>([]);
  const [expandedStrategies, setExpandedStrategies] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  useEffect(() => {
    fetchData();
  }, []);

  // Auto-expand highlighted strategy from URL
  useEffect(() => {
    if (highlightId && strategies.length > 0) {
      setExpandedStrategies(prev => new Set([...prev, highlightId]));
      // Scroll to the strategy
      setTimeout(() => {
        const element = document.getElementById(`strategy-${highlightId}`);
        element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 100);
    }
  }, [highlightId, strategies]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [strategiesRes, positionsRes] = await Promise.all([
        strategiesApi.getAll(),
        positionsApi.getWithMargins()
      ]);
      setStrategies(strategiesRes.data || []);
      setPositions(positionsRes.data.positions || []);
    } catch (error) {
      console.error('Failed to fetch data:', error);
    } finally {
      setLoading(false);
    }
  };

  // Create position lookup by instrument_token
  const positionsByToken = useMemo(() => {
    const lookup: Record<number, PositionWithMargin> = {};
    for (const pos of positions) {
      lookup[pos.instrument_token] = pos;
    }
    return lookup;
  }, [positions]);

  // Create WebSocket position lookup
  const wsPositionsByToken = useMemo(() => {
    const lookup: Record<number, typeof wsState.positions[0]> = {};
    for (const pos of wsState.positions) {
      lookup[pos.instrument_token] = pos;
    }
    return lookup;
  }, [wsState.positions]);

  // Enrich strategies with margin data and live P&L
  const strategiesWithMargins = useMemo(() => {
    return strategies.map(strategy => {
      let totalMargin = 0;
      let totalUnrealizedPnl = 0;
      
      const enrichedTrades = strategy.trades.map(trade => {
        // Get margin data from positions
        const posData = positionsByToken[trade.instrument_token];
        const marginUsed = posData?.margin_used || 0;
        const marginPct = posData?.margin_pct || 0;
        
        // Get live P&L from WebSocket
        const wsPos = wsPositionsByToken[trade.instrument_token];
        const livePnl = wsPos?.pnl ?? trade.unrealized_pnl;
        const liveLtp = wsPos?.last_price ?? trade.last_price;
        const pnlOnMarginPct = marginUsed > 0 ? (livePnl / marginUsed * 100) : 0;
        
        totalMargin += marginUsed;
        totalUnrealizedPnl += livePnl;
        
        return {
          ...trade,
          last_price: liveLtp,
          unrealized_pnl: livePnl,
          margin_used: marginUsed,
          margin_pct: marginPct,
          pnl_on_margin_pct: pnlOnMarginPct
        };
      });
      
      const pnlOnMarginPct = totalMargin > 0 ? (totalUnrealizedPnl / totalMargin * 100) : 0;
      
      return {
        ...strategy,
        trades: enrichedTrades,
        unrealized_pnl: totalUnrealizedPnl,
        total_pnl: totalUnrealizedPnl + strategy.realized_pnl,
        total_margin: totalMargin,
        pnl_on_margin_pct: pnlOnMarginPct
      };
    });
  }, [strategies, positionsByToken, wsPositionsByToken]);

  const toggleStrategyExpanded = (id: string) => {
    setExpandedStrategies(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const totalPnl = useMemo(() => 
    strategiesWithMargins.reduce((sum, s) => sum + s.total_pnl, 0),
    [strategiesWithMargins]
  );

  const totalMargin = useMemo(() => 
    strategiesWithMargins.reduce((sum, s) => sum + s.total_margin, 0),
    [strategiesWithMargins]
  );

  const handleCloseStrategy = async (strategyId: string) => {
    if (!confirm('Are you sure you want to close this strategy?')) return;
    
    try {
      await strategiesApi.close(strategyId, 'Manual close');
      fetchData();
    } catch (error) {
      console.error('Failed to close strategy:', error);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Strategies</h1>
          <p className="text-[var(--muted-foreground)]">Manage your trading strategies with margin tracking</p>
        </div>
        <div className="flex items-center gap-2">
          {wsState.connected ? (
            <Badge variant="outline" className="text-[var(--profit)] border-[var(--profit)]">
              <Wifi className="h-3 w-3 mr-1" /> Live
            </Badge>
          ) : (
            <Badge variant="outline" className="text-[var(--muted-foreground)]">
              <WifiOff className="h-3 w-3 mr-1" /> Offline
            </Badge>
          )}
        </div>
      </div>

      <AccountSummary refreshTrigger={refreshTrigger} />

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Strategies ({strategiesWithMargins.length})</CardTitle>
            <Button variant="outline" size="sm" onClick={() => { fetchData(); setRefreshTrigger(t => t + 1); }} disabled={loading}>
              <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              Loading strategies...
            </div>
          ) : strategiesWithMargins.length === 0 ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              No strategies created yet. Go to Positions to create a strategy.
            </div>
          ) : (
            <div className="space-y-4">
              {strategiesWithMargins.map((strategy) => (
                <div 
                  key={strategy.id} 
                  id={`strategy-${strategy.id}`}
                  className={`border rounded-lg overflow-hidden ${highlightId === strategy.id ? 'border-[var(--primary)] ring-2 ring-[var(--primary)]/20' : 'border-[var(--border)]'}`}
                >
                  {/* Strategy Header */}
                  <div 
                    className="flex items-center justify-between p-4 bg-[var(--muted)] cursor-pointer hover:bg-[var(--muted)]/80"
                    onClick={() => toggleStrategyExpanded(strategy.id)}
                  >
                    <div className="flex items-center gap-3">
                      {expandedStrategies.has(strategy.id) ? (
                        <ChevronDown className="h-5 w-5" />
                      ) : (
                        <ChevronRight className="h-5 w-5" />
                      )}
                      <div>
                        <h3 className="font-semibold">{strategy.name}</h3>
                        <p className="text-sm text-[var(--muted-foreground)]">
                          {strategy.trades_count} trade{strategy.trades_count !== 1 ? 's' : ''} · {strategy.status}
                          {strategy.label && ` · ${strategy.label}`}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-6">
                      <div className="text-right">
                        <p className="text-xs text-[var(--muted-foreground)]">Unrealized P&L</p>
                        <p className={`font-medium ${strategy.unrealized_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatCurrency(strategy.unrealized_pnl)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-[var(--muted-foreground)]">P&L %</p>
                        <p className={`font-medium ${strategy.unrealized_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatPercent(strategy.pnl_on_margin_pct)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-[var(--muted-foreground)]">Margin</p>
                        <p className="font-medium">{formatCurrency(strategy.total_margin)}</p>
                        <p className="text-xs text-[var(--muted-foreground)]">{formatPercent(strategy.trades.reduce((sum, t) => sum + (t.margin_pct || 0), 0))}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-[var(--muted-foreground)]">P&L/Margin</p>
                        <p className={`font-bold ${strategy.pnl_on_margin_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatPercent(strategy.pnl_on_margin_pct)}
                        </p>
                      </div>
                      <Button 
                        variant="ghost" 
                        size="sm" 
                        onClick={(e) => { e.stopPropagation(); handleCloseStrategy(strategy.id); }}
                        className="text-[var(--muted-foreground)] hover:text-[var(--loss)]"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                  
                  {/* Expanded Trades */}
                  {expandedStrategies.has(strategy.id) && strategy.trades.length > 0 && (
                    <div className="border-t border-[var(--border)]">
                      <table className="w-full">
                        <thead>
                          <tr className="border-b border-[var(--border)] bg-[var(--background)]">
                            <th className="text-left py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">Symbol</th>
                            <th className="text-left py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">Exchange</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">Qty</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">Entry</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">LTP</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">P&L</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">P&L %</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">Margin</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">P&L/Margin</th>
                          </tr>
                        </thead>
                        <tbody>
                          {strategy.trades.map((trade) => (
                            <tr key={trade.id} className="border-b border-[var(--border)] hover:bg-[var(--muted)]/50">
                              <td className="py-2 px-4 text-sm font-medium">{trade.tradingsymbol}</td>
                              <td className="py-2 px-4">
                                <Badge variant="outline" className="text-xs">{trade.exchange}</Badge>
                              </td>
                              <td className="py-2 px-4 text-sm text-right">{trade.quantity}</td>
                              <td className="py-2 px-4 text-sm text-right">{formatCurrency(trade.entry_price)}</td>
                              <td className="py-2 px-4 text-sm text-right">{trade.last_price ? formatCurrency(trade.last_price) : '-'}</td>
                              <td className={`py-2 px-4 text-sm text-right font-medium ${trade.unrealized_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                                {formatCurrency(trade.unrealized_pnl)}
                              </td>
                              <td className={`py-2 px-4 text-sm text-right ${(trade.pnl_on_margin_pct || 0) >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                                {formatPercent(trade.pnl_on_margin_pct || 0)}
                              </td>
                              <td className="py-2 px-4 text-sm text-right">
                                <div>{formatCurrency(trade.margin_used || 0)}</div>
                                <div className="text-xs text-[var(--muted-foreground)]">{formatPercent(trade.margin_pct || 0)}</div>
                              </td>
                              <td className={`py-2 px-4 text-sm text-right font-medium ${(trade.pnl_on_margin_pct || 0) >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                                {formatPercent(trade.pnl_on_margin_pct || 0)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ))}

              {/* Total Summary */}
              <div className="mt-4 pt-4 border-t border-[var(--border)] flex justify-between items-center">
                <span className="text-sm text-[var(--muted-foreground)]">
                  {strategiesWithMargins.length} strateg{strategiesWithMargins.length !== 1 ? 'ies' : 'y'}
                </span>
                <div className="flex items-center gap-6">
                  <div className="text-right">
                    <span className="text-sm text-[var(--muted-foreground)]">Total Margin: </span>
                    <span className="font-bold">{formatCurrency(totalMargin)}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-sm text-[var(--muted-foreground)]">Total P&L: </span>
                    <span className={`font-bold ${totalPnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                      {formatCurrency(totalPnl)}
                    </span>
                  </div>
                  <div className="text-right">
                    <span className="text-sm text-[var(--muted-foreground)]">P&L/Margin: </span>
                    <span className={`font-bold ${(totalMargin > 0 ? totalPnl / totalMargin * 100 : 0) >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                      {formatPercent(totalMargin > 0 ? totalPnl / totalMargin * 100 : 0)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
