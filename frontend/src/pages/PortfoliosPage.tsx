/**
 * Portfolios Page - Display only, all data comes from backend.
 */

import { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatCurrency, formatPercent } from '@/lib/utils';
import { ChevronDown, ChevronRight, RefreshCw, Wifi, WifiOff, Plus, FolderOpen, ExternalLink } from 'lucide-react';
import { portfoliosApi } from '@/services/api';
import { portfolioApi, type PortfoliosResponse } from '@/services/portfolioApi';
import { useWebSocket } from '@/hooks/useWebSocket';

export function PortfoliosPage() {
  const navigate = useNavigate();
  const { connected, portfolios: wsPortfolios } = useWebSocket();
  
  // All data comes from backend - no frontend calculations
  const [data, setData] = useState<PortfoliosResponse | null>(null);
  const [expandedPortfolios, setExpandedPortfolios] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [showCreatePortfolio, setShowCreatePortfolio] = useState(false);
  const [newPortfolioName, setNewPortfolioName] = useState('');
  const [newPortfolioDescription, setNewPortfolioDescription] = useState('');
  const [creating, setCreating] = useState(false);
  const [filterSource, setFilterSource] = useState<'all' | 'LIVE' | 'PAPER'>('all');

  const fetchData = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const response = await portfolioApi.getPortfolios();
      setData(response.data);
    } catch (error) {
      console.error('Failed to fetch portfolios:', error);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Merge WebSocket updates with initial data for real-time P&L
  const portfolios = useMemo(() => {
    const basePortfolios = data?.portfolios || [];
    if (!wsPortfolios.length) return basePortfolios;
    
    // Create lookup from WebSocket data
    const wsLookup = new Map(wsPortfolios.map(p => [p.id, p]));
    
    // Merge: use WebSocket P&L if available
    return basePortfolios.map(portfolio => {
      const wsPortfolio = wsLookup.get(portfolio.id);
      if (wsPortfolio) {
        return {
          ...portfolio,
          unrealized_pnl: wsPortfolio.unrealized_pnl,
          total_pnl: wsPortfolio.total_pnl,
        };
      }
      return portfolio;
    });
  }, [data?.portfolios, wsPortfolios]);

  const filteredPortfolios = useMemo(() => {
    if (filterSource === 'all') return portfolios;
    return portfolios.filter((p) => {
      const sources = new Set(p.strategies.map((s) => s.source));
      return sources.has(filterSource);
    });
  }, [portfolios, filterSource]);
  
  const account = data?.account;
  
  // Recalculate totals when portfolios update from WebSocket
  const totals = useMemo(() => {
    if (!filteredPortfolios.length) return data?.totals;
    const totalPnl = filteredPortfolios.reduce((sum, p) => sum + p.total_pnl, 0);
    const totalMargin = filteredPortfolios.reduce((sum, p) => sum + p.total_margin, 0);
    return {
      pnl: totalPnl,
      margin: totalMargin,
      pnl_on_margin_pct: totalMargin > 0 ? (totalPnl / totalMargin * 100) : 0,
      count: filteredPortfolios.length
    };
  }, [filteredPortfolios, data?.totals]);

  const togglePortfolioExpanded = (id: string) => {
    setExpandedPortfolios(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleCreatePortfolio = async () => {
    if (!newPortfolioName.trim()) return;
    
    setCreating(true);
    try {
      await portfoliosApi.create({
        name: newPortfolioName,
        description: newPortfolioDescription
      });
      setShowCreatePortfolio(false);
      setNewPortfolioName('');
      setNewPortfolioDescription('');
      fetchData();
    } catch (error) {
      console.error('Failed to create portfolio:', error);
    } finally {
      setCreating(false);
    }
  };

  if (isLoading) {
    return <div className="text-center py-8 text-[var(--muted-foreground)]">Loading portfolios...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Portfolios</h1>
          <p className="text-[var(--muted-foreground)]">Organize strategies into portfolios with margin tracking</p>
        </div>
        <div className="flex items-center gap-2">
          {connected ? (
            <Badge variant="outline" className="text-[var(--profit)] border-[var(--profit)]">
              <Wifi className="h-3 w-3 mr-1" /> Live
            </Badge>
          ) : (
            <Badge variant="outline" className="text-[var(--muted-foreground)]">
              <WifiOff className="h-3 w-3 mr-1" /> Offline
            </Badge>
          )}
          <Button size="sm" onClick={() => setShowCreatePortfolio(true)}>
            <Plus className="h-4 w-4 mr-1" /> New Portfolio
          </Button>
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
            <CardTitle>Portfolios ({filteredPortfolios.length})</CardTitle>
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
          {filteredPortfolios.length === 0 ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              <FolderOpen className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>No portfolios yet. Create one to organize your strategies.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {filteredPortfolios.map((portfolio) => (
                <div key={portfolio.id} className="border border-[var(--border)] rounded-lg overflow-hidden">
                  {/* Portfolio Header */}
                  <div 
                    className="flex items-center justify-between p-4 bg-[var(--muted)] cursor-pointer hover:bg-[var(--muted)]/80"
                    onClick={() => togglePortfolioExpanded(portfolio.id)}
                  >
                    <div className="flex items-center gap-3">
                      {expandedPortfolios.has(portfolio.id) ? (
                        <ChevronDown className="h-5 w-5" />
                      ) : (
                        <ChevronRight className="h-5 w-5" />
                      )}
                      <div>
                        <h3 className="font-semibold">{portfolio.name}</h3>
                        <p className="text-sm text-[var(--muted-foreground)]">
                          {portfolio.strategy_count} strateg{portfolio.strategy_count !== 1 ? 'ies' : 'y'}
                          {portfolio.description && ` · ${portfolio.description}`}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-6">
                      <div className="text-right">
                        <p className="text-xs text-[var(--muted-foreground)]">Unrealized P&L</p>
                        <p className={`font-medium ${portfolio.unrealized_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatCurrency(portfolio.unrealized_pnl)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-[var(--muted-foreground)]">Margin</p>
                        <p className="font-medium">{formatCurrency(portfolio.total_margin)}</p>
                        <p className="text-xs text-[var(--muted-foreground)]">{formatPercent(portfolio.margin_pct)}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-[var(--muted-foreground)]">P&L/Margin</p>
                        <p className={`font-bold ${portfolio.pnl_on_margin_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatPercent(portfolio.pnl_on_margin_pct)}
                        </p>
                      </div>
                    </div>
                  </div>
                  
                  {/* Expanded Strategies */}
                  {expandedPortfolios.has(portfolio.id) && portfolio.strategies.length > 0 && (
                    <div className="border-t border-[var(--border)]">
                      <table className="w-full">
                        <thead>
                          <tr className="border-b border-[var(--border)] bg-[var(--background)]">
                            <th className="text-left py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">Strategy</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">Trades</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">Unrealized</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">Margin</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">P&L/Margin</th>
                          </tr>
                        </thead>
                        <tbody>
                          {portfolio.strategies.map((strategy) => (
                            <tr 
                              key={strategy.id} 
                              className="border-b border-[var(--border)] hover:bg-[var(--muted)]/50 cursor-pointer"
                              onClick={() => navigate(`/dashboard/strategies?highlight=${strategy.id}`)}
                            >
                              <td className="py-2 px-4">
                                <div className="flex items-center gap-2">
                                  <span className="font-medium">{strategy.name}</span>
                                  <ExternalLink className="h-3 w-3 text-[var(--muted-foreground)]" />
                                </div>
                                {strategy.label && (
                                  <Badge variant="outline" className="text-xs mt-1">{strategy.label}</Badge>
                                )}
                              </td>
                              <td className="py-2 px-4 text-sm text-right">{strategy.trades_count}</td>
                              <td className={`py-2 px-4 text-sm text-right ${strategy.unrealized_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                                {formatCurrency(strategy.unrealized_pnl)}
                              </td>
                              <td className="py-2 px-4 text-sm text-right">
                                <div>{formatCurrency(strategy.total_margin)}</div>
                                <div className="text-xs text-[var(--muted-foreground)]">{formatPercent(strategy.margin_pct)}</div>
                              </td>
                              <td className={`py-2 px-4 text-sm text-right font-medium ${strategy.pnl_on_margin_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                                {formatPercent(strategy.pnl_on_margin_pct)}
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
                    {filteredPortfolios.length} portfolio{filteredPortfolios.length !== 1 ? 's' : ''}
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

      {/* Create Portfolio Modal */}
      {showCreatePortfolio && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-96">
            <CardHeader>
              <CardTitle>Create Portfolio</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm text-[var(--muted-foreground)]">Portfolio Name</label>
                <input
                  type="text"
                  value={newPortfolioName}
                  onChange={(e) => setNewPortfolioName(e.target.value)}
                  className="w-full mt-1 px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  placeholder="Enter portfolio name"
                />
              </div>
              <div>
                <label className="text-sm text-[var(--muted-foreground)]">Description (optional)</label>
                <input
                  type="text"
                  value={newPortfolioDescription}
                  onChange={(e) => setNewPortfolioDescription(e.target.value)}
                  className="w-full mt-1 px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  placeholder="Enter description"
                />
              </div>
              <div className="flex gap-2 justify-end">
                <Button variant="outline" onClick={() => setShowCreatePortfolio(false)}>
                  Cancel
                </Button>
                <Button onClick={handleCreatePortfolio} disabled={creating || !newPortfolioName.trim()}>
                  {creating ? 'Creating...' : 'Create'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
