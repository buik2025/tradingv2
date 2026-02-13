/**
 * Strategies Page - Display only, all data comes from backend.
 */

import { useEffect, useState, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { SourceBadge } from '@/components/ui/source-badge';
import { Button } from '@/components/ui/button';
import { formatCurrency, formatPercent } from '@/lib/utils';
import { ChevronDown, ChevronRight, RefreshCw, Trash2, Shield, ShieldCheck, TrendingUp } from 'lucide-react';
import { ConnectionBadge } from '@/components/ui/connection-badge';
import { strategiesApi, trailingStopApi, type TrailingStopStatus } from '@/services/api';
import { portfolioApi, type StrategiesResponse } from '@/services/portfolioApi';
import { useWebSocket } from '@/hooks/useWebSocket';

export function StrategiesPage() {
  const [searchParams] = useSearchParams();
  const highlightId = searchParams.get('highlight');
  const { connected, strategies: wsStrategies } = useWebSocket();
  
  // All data comes from backend - no frontend calculations
  const [data, setData] = useState<StrategiesResponse | null>(null);
  const [expandedStrategies, setExpandedStrategies] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [filterSource, setFilterSource] = useState<'all' | 'LIVE' | 'PAPER'>('all');
  
  // Trailing stop state
  const [trailingStopStatuses, setTrailingStopStatuses] = useState<Record<string, TrailingStopStatus>>({});
  const [trailingStopLoading, setTrailingStopLoading] = useState<Set<string>>(new Set());
  const [monitorRunning, setMonitorRunning] = useState(false);
  
  // Trailing stop config edit modal state
  const [editingTrailingStop, setEditingTrailingStop] = useState<string | null>(null);
  const [editActivationPct, setEditActivationPct] = useState(0.8);
  const [editStepPct, setEditStepPct] = useState(0.1);
  const [editLockPct, setEditLockPct] = useState(0.05);
  const [savingConfig, setSavingConfig] = useState(false);

  const fetchData = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const response = await portfolioApi.getStrategies();
      setData(response.data);
    } catch (error) {
      console.error('Failed to fetch strategies:', error);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Merge WebSocket updates with initial data for real-time P&L
  const strategies = useMemo(() => {
    const baseStrategies = data?.strategies || [];
    if (!wsStrategies.length) return baseStrategies;
    
    // Create lookup from WebSocket data
    const wsLookup = new Map(wsStrategies.map(s => [s.id, s]));
    
    // Merge: use WebSocket P&L if available
    return baseStrategies.map(strategy => {
      const wsStrategy = wsLookup.get(strategy.id);
      if (wsStrategy) {
        return {
          ...strategy,
          unrealized_pnl: wsStrategy.unrealized_pnl,
          total_pnl: wsStrategy.unrealized_pnl + strategy.realized_pnl,
        };
      }
      return strategy;
    });
  }, [data?.strategies, wsStrategies]);

  const filteredStrategies = useMemo(() => {
    if (filterSource === 'all') return strategies;
    return strategies.filter((s) => s.source === filterSource);
  }, [strategies, filterSource]);
  
  const account = data?.account;
  
  // Recalculate totals when strategies update from WebSocket
  const totals = useMemo(() => {
    if (!filteredStrategies.length) return data?.totals;
    const totalPnl = filteredStrategies.reduce((sum, s) => sum + s.total_pnl, 0);
    const totalMargin = filteredStrategies.reduce((sum, s) => sum + s.total_margin, 0);
    return {
      pnl: totalPnl,
      margin: totalMargin,
      pnl_on_margin_pct: totalMargin > 0 ? (totalPnl / totalMargin * 100) : 0,
      count: filteredStrategies.length
    };
  }, [filteredStrategies, data?.totals]);

  useEffect(() => {
    if (highlightId && strategies.length > 0) {
      setExpandedStrategies(prev => new Set([...prev, highlightId]));
      setTimeout(() => {
        const element = document.getElementById(`strategy-${highlightId}`);
        element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 100);
    }
  }, [highlightId, strategies.length]);

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

  const handleCloseStrategy = async (strategyId: string) => {
    if (!confirm('Are you sure you want to close this strategy?')) return;
    
    try {
      await strategiesApi.close(strategyId, 'Manual close');
      fetchData();
    } catch (error) {
      console.error('Failed to close strategy:', error);
    }
  };

  // Trailing stop handlers
  const fetchTrailingStopStatus = useCallback(async (strategyId: string) => {
    try {
      const response = await strategiesApi.getTrailingStopStatus(strategyId);
      setTrailingStopStatuses(prev => ({ ...prev, [strategyId]: response.data }));
    } catch (error) {
      console.error('Failed to fetch trailing stop status:', error);
    }
  }, []);

  const handleToggleTrailingStop = async (strategyId: string, currentlyEnabled: boolean) => {
    setTrailingStopLoading(prev => new Set([...prev, strategyId]));
    try {
      if (currentlyEnabled) {
        await strategiesApi.disableTrailingStop(strategyId);
      } else {
        await strategiesApi.enableTrailingStop(strategyId, {
          activation_pct: 0.8,
          step_pct: 0.1,
          lock_pct: 0.05
        });
      }
      await fetchTrailingStopStatus(strategyId);
    } catch (error) {
      console.error('Failed to toggle trailing stop:', error);
    } finally {
      setTrailingStopLoading(prev => {
        const next = new Set(prev);
        next.delete(strategyId);
        return next;
      });
    }
  };

  const handleStartMonitor = async () => {
    try {
      await trailingStopApi.start(5);
      setMonitorRunning(true);
    } catch (error) {
      console.error('Failed to start trailing stop monitor:', error);
    }
  };

  const handleStopMonitor = async () => {
    try {
      await trailingStopApi.stop();
      setMonitorRunning(false);
    } catch (error) {
      console.error('Failed to stop trailing stop monitor:', error);
    }
  };

  const openEditTrailingStop = (strategyId: string) => {
    const status = trailingStopStatuses[strategyId];
    if (status) {
      setEditActivationPct(status.config.activation_pct);
      setEditStepPct(status.config.step_pct);
      setEditLockPct(status.config.lock_pct);
    }
    setEditingTrailingStop(strategyId);
  };

  const handleSaveTrailingStopConfig = async () => {
    if (!editingTrailingStop) return;
    
    setSavingConfig(true);
    try {
      await strategiesApi.updateTrailingStopConfig(editingTrailingStop, {
        activation_pct: editActivationPct,
        step_pct: editStepPct,
        lock_pct: editLockPct,
      });
      await fetchTrailingStopStatus(editingTrailingStop);
      setEditingTrailingStop(null);
    } catch (error) {
      console.error('Failed to save trailing stop config:', error);
    } finally {
      setSavingConfig(false);
    }
  };

  // Fetch trailing stop status for expanded strategies
  useEffect(() => {
    expandedStrategies.forEach(strategyId => {
      if (!trailingStopStatuses[strategyId]) {
        fetchTrailingStopStatus(strategyId);
      }
    });
  }, [expandedStrategies, trailingStopStatuses, fetchTrailingStopStatus]);

  if (isLoading) {
    return <div className="text-center py-8 text-[var(--muted-foreground)]">Loading strategies...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Strategies</h1>
          <p className="text-[var(--muted-foreground)]">Manage your trading strategies with margin tracking</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Trailing Stop Monitor Controls */}
          {monitorRunning ? (
            <Button variant="outline" size="sm" onClick={handleStopMonitor} className="text-[var(--loss)]">
              <Shield className="h-4 w-4 mr-1" /> Stop Monitor
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={handleStartMonitor} className="text-[var(--profit)]">
              <ShieldCheck className="h-4 w-4 mr-1" /> Start Monitor
            </Button>
          )}
          <ConnectionBadge connected={connected} />
        </div>
      </div>

      {/* Account Summary from backend */}
      {account && (
        <div className="grid grid-cols-4 gap-4">
          <Card><CardContent className="pt-4">
            <p className="text-xs text-[var(--muted-foreground)]">Total Margin</p>
            <p className="text-xl font-bold">{formatCurrency(account.total_margin)}</p>
          </CardContent></Card>
          <Card><CardContent className="pt-4">
            <p className="text-xs text-[var(--muted-foreground)]">Used Margin</p>
            <p className="text-xl font-bold">{formatCurrency(account.used_margin)}</p>
            <p className="text-xs text-[var(--muted-foreground)]">{formatPercent(account.margin_utilization_pct)} utilized</p>
          </CardContent></Card>
          <Card><CardContent className="pt-4">
            <p className="text-xs text-[var(--muted-foreground)]">Available Margin</p>
            <p className="text-xl font-bold text-[var(--profit)]">{formatCurrency(account.available_margin)}</p>
            <p className="text-xs text-[var(--muted-foreground)]">{formatPercent(account.available_margin_pct)} available</p>
          </CardContent></Card>
          <Card><CardContent className="pt-4">
            <p className="text-xs text-[var(--muted-foreground)]">Cash Available</p>
            <p className="text-xl font-bold">{formatCurrency(account.cash_available)}</p>
          </CardContent></Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Strategies ({filteredStrategies.length})</CardTitle>
            <div className="flex items-center gap-3">
              <select
                value={filterSource}
                onChange={(e) => setFilterSource(e.target.value as 'all' | 'LIVE' | 'PAPER')}
                className="px-3 py-2 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none"
              >
                <option value="all">All Sources</option>
                <option value="LIVE">Live (Kite)</option>
                <option value="PAPER">Paper (Simulator)</option>
              </select>
              <Button variant="outline" size="sm" onClick={fetchData} disabled={isRefreshing}>
                <RefreshCw className={`h-4 w-4 mr-1 ${isRefreshing ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {filteredStrategies.length === 0 ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              No strategies created yet. Go to Positions to create a strategy.
            </div>
          ) : (
            <div className="space-y-4">
              {filteredStrategies.map((strategy) => (
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
                      <div className="flex items-center gap-2">
                        <div>
                          <h3 className="font-semibold">{strategy.name}</h3>
                          <p className="text-sm text-[var(--muted-foreground)]">
                            {strategy.trades_count} trade{strategy.trades_count !== 1 ? 's' : ''} · {strategy.status}
                            {strategy.label && ` · ${strategy.label}`}
                          </p>
                        </div>
                        <SourceBadge source={(strategy.source || 'LIVE') as 'LIVE' | 'PAPER'} size="sm" />
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
                        <p className="text-xs text-[var(--muted-foreground)]">Margin</p>
                        <p className="font-medium">{formatCurrency(strategy.total_margin)}</p>
                        <p className="text-xs text-[var(--muted-foreground)]">{formatPercent(strategy.margin_pct)}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-[var(--muted-foreground)]">P&L/Margin</p>
                        <p className={`font-bold ${strategy.pnl_on_margin_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatPercent(strategy.pnl_on_margin_pct)}
                        </p>
                      </div>
                      {/* Trailing Stop Toggle */}
                      <Button 
                        variant="ghost" 
                        size="sm" 
                        onClick={(e) => { 
                          e.stopPropagation(); 
                          const status = trailingStopStatuses[strategy.id];
                          handleToggleTrailingStop(strategy.id, status?.enabled || false);
                        }}
                        disabled={trailingStopLoading.has(strategy.id)}
                        className={trailingStopStatuses[strategy.id]?.enabled 
                          ? "text-[var(--profit)]" 
                          : "text-[var(--muted-foreground)] hover:text-[var(--profit)]"}
                        title={trailingStopStatuses[strategy.id]?.enabled ? "Disable Trailing Stop" : "Enable Trailing Stop"}
                      >
                        {trailingStopStatuses[strategy.id]?.enabled ? (
                          <ShieldCheck className="h-4 w-4" />
                        ) : (
                          <Shield className="h-4 w-4" />
                        )}
                      </Button>
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
                  
                  {/* Trailing Stop Status Bar */}
                  {trailingStopStatuses[strategy.id]?.enabled && (
                    <div className="px-4 py-2 bg-[var(--muted)]/50 border-t border-[var(--border)] flex items-center justify-between text-sm">
                      <div className="flex items-center gap-4">
                        <span className="text-[var(--muted-foreground)]">
                          <TrendingUp className="h-4 w-4 inline mr-1" />
                          Trailing Stop
                        </span>
                        {trailingStopStatuses[strategy.id]?.state.is_active ? (
                          <Badge variant="outline" className="text-[var(--profit)] border-[var(--profit)]">
                            Active
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-[var(--muted-foreground)]">
                            Waiting (≥{trailingStopStatuses[strategy.id]?.config.activation_pct}%)
                          </Badge>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => { e.stopPropagation(); openEditTrailingStop(strategy.id); }}
                          className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] h-6 px-2"
                        >
                          Edit Config
                        </Button>
                      </div>
                      <div className="flex items-center gap-4 text-xs">
                        {trailingStopStatuses[strategy.id]?.state.floor_pct !== null && (
                          <span>
                            Floor: <span className="text-[var(--profit)] font-medium">
                              {trailingStopStatuses[strategy.id]?.state.floor_pct?.toFixed(3)}%
                            </span>
                          </span>
                        )}
                        {trailingStopStatuses[strategy.id]?.state.high_water_pct !== null && (
                          <span>
                            High: <span className="font-medium">
                              {trailingStopStatuses[strategy.id]?.state.high_water_pct?.toFixed(3)}%
                            </span>
                          </span>
                        )}
                        {trailingStopStatuses[strategy.id]?.state.current_pnl_pct !== null && (
                          <span>
                            Current: <span className={`font-medium ${(trailingStopStatuses[strategy.id]?.state.current_pnl_pct || 0) >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                              {trailingStopStatuses[strategy.id]?.state.current_pnl_pct?.toFixed(3)}%
                            </span>
                          </span>
                        )}
                        {(trailingStopStatuses[strategy.id]?.state.sl_order_ids?.length || 0) > 0 && (
                          <span className="text-[var(--muted-foreground)]">
                            SL Orders: {trailingStopStatuses[strategy.id]?.state.sl_order_ids?.length}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  
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
                              <td className="py-2 px-4 text-sm text-right">
                                <div>{formatCurrency(trade.margin_used)}</div>
                                <div className="text-xs text-[var(--muted-foreground)]">{formatPercent(trade.margin_pct)}</div>
                              </td>
                              <td className={`py-2 px-4 text-sm text-right font-medium ${trade.pnl_on_margin_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                                {formatPercent(trade.pnl_on_margin_pct)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ))}

              {/* Total Summary from backend */}
              {totals && (
                <div className="mt-4 pt-4 border-t border-[var(--border)] flex justify-between items-center">
                  <span className="text-sm text-[var(--muted-foreground)]">
                    {filteredStrategies.length} strateg{filteredStrategies.length !== 1 ? 'ies' : 'y'}
                  </span>
                  <div className="flex items-center gap-6">
                    <div className="text-right">
                      <span className="text-sm text-[var(--muted-foreground)]">Total Margin: </span>
                      <span className="font-bold">{formatCurrency(totals.margin)}</span>
                    </div>
                    <div className="text-right">
                      <span className="text-sm text-[var(--muted-foreground)]">Total P&L: </span>
                      <span className={`font-bold ${totals.pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                        {formatCurrency(totals.pnl)}
                      </span>
                    </div>
                    <div className="text-right">
                      <span className="text-sm text-[var(--muted-foreground)]">P&L/Margin: </span>
                      <span className={`font-bold ${totals.pnl_on_margin_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                        {formatPercent(totals.pnl_on_margin_pct)}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Edit Trailing Stop Config Modal */}
      {editingTrailingStop && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-[420px]">
            <CardHeader>
              <CardTitle>Edit Trailing Stop Config</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-[var(--muted-foreground)]">
                Adjust the trailing stop parameters for this strategy.
              </p>
              
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs text-[var(--muted-foreground)]">Activation %</label>
                  <input
                    type="number"
                    step="0.1"
                    value={editActivationPct}
                    onChange={(e) => setEditActivationPct(parseFloat(e.target.value) || 0.8)}
                    className="w-full mt-1 px-2 py-1.5 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  />
                  <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">of margin</p>
                </div>
                <div>
                  <label className="text-xs text-[var(--muted-foreground)]">Step %</label>
                  <input
                    type="number"
                    step="0.05"
                    value={editStepPct}
                    onChange={(e) => setEditStepPct(parseFloat(e.target.value) || 0.1)}
                    className="w-full mt-1 px-2 py-1.5 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  />
                  <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">P&L increase</p>
                </div>
                <div>
                  <label className="text-xs text-[var(--muted-foreground)]">Lock %</label>
                  <input
                    type="number"
                    step="0.01"
                    value={editLockPct}
                    onChange={(e) => setEditLockPct(parseFloat(e.target.value) || 0.05)}
                    className="w-full mt-1 px-2 py-1.5 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  />
                  <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">per step</p>
                </div>
              </div>
              
              <p className="text-xs text-[var(--muted-foreground)] bg-[var(--muted)] p-2 rounded">
                When P&L ≥ {editActivationPct}% of margin, lock in profits. 
                Every {editStepPct}% increase raises floor by {editLockPct}%.
              </p>
              
              <div className="flex gap-2 justify-end">
                <Button variant="outline" onClick={() => setEditingTrailingStop(null)}>
                  Cancel
                </Button>
                <Button onClick={handleSaveTrailingStopConfig} disabled={savingConfig}>
                  {savingConfig ? 'Saving...' : 'Save'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
