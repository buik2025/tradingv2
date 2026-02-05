import { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatCurrency, formatPercent } from '@/lib/utils';
import { ChevronDown, ChevronRight, RefreshCw, Wifi, WifiOff, Plus, FolderOpen, ExternalLink } from 'lucide-react';
import { portfoliosApi, strategiesApi, positionsApi, type Portfolio, type Strategy, type PositionWithMargin } from '@/services/api';
import { useWebSocket } from '@/hooks/useWebSocket';
import { AccountSummary } from '@/components/AccountSummary';

interface PortfolioWithDetails extends Portfolio {
  strategies: (Strategy & { total_margin?: number; margin_pct?: number; pnl_on_margin_pct?: number })[];
  total_margin: number;
  margin_pct: number;
  pnl_on_margin_pct: number;
}

export function PortfoliosPage() {
  const navigate = useNavigate();
  const wsState = useWebSocket();
  
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [positions, setPositions] = useState<PositionWithMargin[]>([]);
  const [expandedPortfolios, setExpandedPortfolios] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [showCreatePortfolio, setShowCreatePortfolio] = useState(false);
  const [newPortfolioName, setNewPortfolioName] = useState('');
  const [newPortfolioDescription, setNewPortfolioDescription] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [portfoliosRes, strategiesRes, positionsRes] = await Promise.all([
        portfoliosApi.getAll(),
        strategiesApi.getAll(),
        positionsApi.getWithMargins()
      ]);
      setPortfolios(portfoliosRes.data || []);
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

  // Enrich portfolios with strategies and margin data
  const portfoliosWithDetails = useMemo((): PortfolioWithDetails[] => {
    // For now, show all strategies as "unassigned" portfolio if no portfolios exist
    // In a real implementation, strategies would have portfolio_id
    
    if (portfolios.length === 0) {
      // Create a virtual "All Strategies" portfolio
      let totalMargin = 0;
      let totalPnl = 0;
      
      const enrichedStrategies = strategies.map(strategy => {
        let strategyMargin = 0;
        let strategyPnl = 0;
        
        const enrichedTrades = strategy.trades.map(trade => {
          const posData = positionsByToken[trade.instrument_token];
          const marginUsed = posData?.margin_used || 0;
          const wsPos = wsPositionsByToken[trade.instrument_token];
          const livePnl = wsPos?.pnl ?? trade.unrealized_pnl;
          
          strategyMargin += marginUsed;
          strategyPnl += livePnl;
          
          return { ...trade, margin_used: marginUsed, unrealized_pnl: livePnl };
        });
        
        totalMargin += strategyMargin;
        totalPnl += strategyPnl;
        
        const strategyMarginPct = enrichedTrades.reduce((sum, t) => sum + (positionsByToken[t.instrument_token]?.margin_pct || 0), 0);
        
        return {
          ...strategy,
          trades: enrichedTrades,
          unrealized_pnl: strategyPnl,
          total_pnl: strategyPnl + strategy.realized_pnl,
          total_margin: strategyMargin,
          margin_pct: strategyMarginPct,
          pnl_on_margin_pct: strategyMargin > 0 ? (strategyPnl / strategyMargin * 100) : 0
        };
      });
      
      const totalMarginPct = enrichedStrategies.reduce((sum, s) => sum + (s.margin_pct || 0), 0);
      
      return [{
        id: 'all',
        name: 'All Strategies',
        description: 'All trading strategies',
        realized_pnl: strategies.reduce((sum, s) => sum + s.realized_pnl, 0),
        unrealized_pnl: totalPnl,
        total_pnl: totalPnl + strategies.reduce((sum, s) => sum + s.realized_pnl, 0),
        strategy_count: strategies.length,
        is_active: true,
        strategies: enrichedStrategies,
        total_margin: totalMargin,
        margin_pct: totalMarginPct,
        pnl_on_margin_pct: totalMargin > 0 ? (totalPnl / totalMargin * 100) : 0
      }];
    }
    
    // Map portfolios with their strategies
    return portfolios.map(portfolio => {
      // Filter strategies for this portfolio (assuming strategy has portfolio_id)
      const portfolioStrategies = strategies.filter((s: any) => s.portfolio_id === portfolio.id);
      
      let totalMargin = 0;
      let totalPnl = 0;
      
      const enrichedStrategies = portfolioStrategies.map(strategy => {
        let strategyMargin = 0;
        let strategyPnl = 0;
        let strategyMarginPct = 0;
        
        strategy.trades.forEach(trade => {
          const posData = positionsByToken[trade.instrument_token];
          const marginUsed = posData?.margin_used || 0;
          const marginPct = posData?.margin_pct || 0;
          const wsPos = wsPositionsByToken[trade.instrument_token];
          const livePnl = wsPos?.pnl ?? trade.unrealized_pnl;
          
          strategyMargin += marginUsed;
          strategyMarginPct += marginPct;
          strategyPnl += livePnl;
        });
        
        totalMargin += strategyMargin;
        totalPnl += strategyPnl;
        
        return {
          ...strategy,
          total_margin: strategyMargin,
          margin_pct: strategyMarginPct,
          pnl_on_margin_pct: strategyMargin > 0 ? (strategyPnl / strategyMargin * 100) : 0
        };
      });
      
      const totalMarginPct = enrichedStrategies.reduce((sum, s) => sum + (s.margin_pct || 0), 0);
      
      return {
        ...portfolio,
        strategies: enrichedStrategies,
        total_margin: totalMargin,
        margin_pct: totalMarginPct,
        unrealized_pnl: totalPnl,
        total_pnl: totalPnl + portfolio.realized_pnl,
        pnl_on_margin_pct: totalMargin > 0 ? (totalPnl / totalMargin * 100) : 0
      };
    });
  }, [portfolios, strategies, positionsByToken, wsPositionsByToken]);

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

  const totalPnl = useMemo(() => 
    portfoliosWithDetails.reduce((sum, p) => sum + p.total_pnl, 0),
    [portfoliosWithDetails]
  );

  const totalMargin = useMemo(() => 
    portfoliosWithDetails.reduce((sum, p) => sum + p.total_margin, 0),
    [portfoliosWithDetails]
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Portfolios</h1>
          <p className="text-[var(--muted-foreground)]">Organize strategies into portfolios with margin tracking</p>
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
          <Button size="sm" onClick={() => setShowCreatePortfolio(true)}>
            <Plus className="h-4 w-4 mr-1" /> New Portfolio
          </Button>
        </div>
      </div>

      <AccountSummary refreshTrigger={refreshTrigger} />

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Portfolios ({portfoliosWithDetails.length})</CardTitle>
            <Button variant="outline" size="sm" onClick={() => { fetchData(); setRefreshTrigger(t => t + 1); }} disabled={loading}>
              <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              Loading portfolios...
            </div>
          ) : portfoliosWithDetails.length === 0 ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              <FolderOpen className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>No portfolios yet. Create one to organize your strategies.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {portfoliosWithDetails.map((portfolio) => (
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
                        <p className="text-xs text-[var(--muted-foreground)]">P&L %</p>
                        <p className={`font-medium ${portfolio.pnl_on_margin_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatPercent(portfolio.pnl_on_margin_pct)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-[var(--muted-foreground)]">Margin</p>
                        <p className="font-medium">{formatCurrency(portfolio.total_margin)}</p>
                        <p className="text-xs text-[var(--muted-foreground)]">{formatPercent(portfolio.margin_pct || 0)}</p>
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
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">P&L %</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">Margin</th>
                            <th className="text-right py-2 px-4 text-xs font-medium text-[var(--muted-foreground)]">P&L/Margin</th>
                          </tr>
                        </thead>
                        <tbody>
                          {portfolio.strategies.map((strategy: any) => (
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
                              <td className={`py-2 px-4 text-sm text-right ${(strategy.pnl_on_margin_pct || 0) >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                                {formatPercent(strategy.pnl_on_margin_pct || 0)}
                              </td>
                              <td className="py-2 px-4 text-sm text-right">
                                <div>{formatCurrency(strategy.total_margin || 0)}</div>
                                <div className="text-xs text-[var(--muted-foreground)]">{formatPercent(strategy.margin_pct || 0)}</div>
                              </td>
                              <td className={`py-2 px-4 text-sm text-right font-medium ${(strategy.pnl_on_margin_pct || 0) >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                                {formatPercent(strategy.pnl_on_margin_pct || 0)}
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
                  {portfoliosWithDetails.length} portfolio{portfoliosWithDetails.length !== 1 ? 's' : ''}
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
