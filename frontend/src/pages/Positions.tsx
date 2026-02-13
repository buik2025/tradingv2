import { useEffect, useState, useMemo, useCallback } from 'react';
import { useTradingStore } from '@/stores/tradingStore';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatCurrency, formatPercent } from '@/lib/utils';
import { ArrowUpDown, ArrowUp, ArrowDown, Search, X, LayoutList, Layers, ChevronDown, ChevronRight, Plus, Check, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { strategiesApi, type Strategy } from '@/services/api';
import { useWebSocket } from '@/hooks/useWebSocket';

type SortField = 'tradingsymbol' | 'exchange' | 'source' | 'quantity' | 'average_price' | 'last_price' | 'pnl' | 'pnl_pct';
type SortDirection = 'asc' | 'desc';
type ViewMode = 'positions' | 'strategies';

export function Positions() {
  const { positions: storePositions, fetchPositions } = useTradingStore();
  const wsState = useWebSocket();
  
  // Use WebSocket data if connected, otherwise fall back to store
  // IMPORTANT: Use Kite's P&L directly - don't recalculate
  const positions = wsState.connected && wsState.positions.length > 0 
    ? wsState.positions.map(p => ({
        id: p.id,
        tradingsymbol: p.tradingsymbol,
        exchange: p.exchange,
        quantity: p.quantity,
        average_price: p.average_price,
        last_price: p.last_price || 0,
        pnl: p.pnl,  // Use Kite's P&L directly
        pnl_pct: p.pnl_pct || 0,  // Use Kite's P&L % if available
        source: p.source,
      }))
    : storePositions;

  const [viewMode, setViewMode] = useState<ViewMode>('positions');
  const [sortField, setSortField] = useState<SortField>('pnl');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [searchTerm, setSearchTerm] = useState('');
  const [filterExchange, setFilterExchange] = useState<string>('all');
  const [filterSource, setFilterSource] = useState<string>('all');
  
  // Strategy view state
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [expandedStrategies, setExpandedStrategies] = useState<Set<string>>(new Set());
  const [loadingStrategies, setLoadingStrategies] = useState(false);

  // Position selection for strategy creation
  const [selectedPositions, setSelectedPositions] = useState<Set<string>>(new Set());
  const [showCreateStrategy, setShowCreateStrategy] = useState(false);
  const [newStrategyName, setNewStrategyName] = useState('');
  const [newStrategyLabel, setNewStrategyLabel] = useState('');
  const [creatingStrategy, setCreatingStrategy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Fetch positions with loading state
  const refreshPositions = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await fetchPositions();
      setLastUpdated(new Date());
    } finally {
      setIsRefreshing(false);
    }
  }, [fetchPositions]);

  useEffect(() => {
    // Initial fetch
    refreshPositions();
    
    // Only poll if WebSocket is NOT connected
    // WebSocket provides real-time updates, polling is fallback only
    if (!wsState.connected) {
      const interval = setInterval(refreshPositions, 5000);
      return () => clearInterval(interval);
    }
  }, [refreshPositions, wsState.connected]);

  useEffect(() => {
    if (viewMode === 'strategies') {
      fetchStrategies();
    }
  }, [viewMode]);

  const fetchStrategies = async () => {
    setLoadingStrategies(true);
    try {
      const response = await strategiesApi.getAll();
      setStrategies(response.data || []);
    } catch (error) {
      console.error('Failed to fetch strategies:', error);
    } finally {
      setLoadingStrategies(false);
    }
  };

  const toggleStrategyExpanded = (strategyType: string) => {
    setExpandedStrategies(prev => {
      const next = new Set(prev);
      if (next.has(strategyType)) {
        next.delete(strategyType);
      } else {
        next.add(strategyType);
      }
      return next;
    });
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <ArrowUpDown className="h-4 w-4 ml-1 opacity-50" />;
    return sortDirection === 'asc' 
      ? <ArrowUp className="h-4 w-4 ml-1" /> 
      : <ArrowDown className="h-4 w-4 ml-1" />;
  };

  const uniqueExchanges = useMemo(() => 
    [...new Set(positions.map(p => p.exchange))], [positions]
  );

  const uniqueSources = useMemo(() => 
    [...new Set(positions.map(p => p.source || 'LIVE'))], [positions]
  );

  const filteredAndSortedPositions = useMemo(() => {
    let result = [...positions];

    // Filter by search term
    if (searchTerm) {
      result = result.filter(p => 
        p.tradingsymbol.toLowerCase().includes(searchTerm.toLowerCase())
      );
    }

    // Filter by exchange
    if (filterExchange !== 'all') {
      result = result.filter(p => p.exchange === filterExchange);
    }

    // Filter by source
    if (filterSource !== 'all') {
      result = result.filter(p => (p.source || 'LIVE') === filterSource);
    }

    // Sort
    result.sort((a, b) => {
      let aVal: string | number = a[sortField] ?? '';
      let bVal: string | number = b[sortField] ?? '';

      if (typeof aVal === 'string') {
        aVal = aVal.toLowerCase();
        bVal = (bVal as string).toLowerCase();
      }

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });

    return result;
  }, [positions, searchTerm, filterExchange, filterSource, sortField, sortDirection]);

  const totalPnl = useMemo(() => 
    filteredAndSortedPositions.reduce((sum, p) => sum + p.pnl, 0), 
    [filteredAndSortedPositions]
  );

  const clearFilters = () => {
    setSearchTerm('');
    setFilterExchange('all');
    setFilterSource('all');
  };

  const hasFilters = searchTerm || filterExchange !== 'all' || filterSource !== 'all';

  // Generate default strategy name from selected positions
  const generateDefaultStrategyName = useCallback(() => {
    if (selectedPositions.size === 0) return '';
    
    const selected = positions.filter(p => selectedPositions.has(p.id));
    if (selected.length === 0) return '';
    
    // Extract underlying from tradingsymbol (e.g., NIFTY from NIFTY24FEB23500PE)
    const underlyings = new Set<string>();
    selected.forEach(p => {
      const match = p.tradingsymbol.match(/^(NIFTY|BANKNIFTY|FINNIFTY)/i);
      if (match) underlyings.add(match[1].toUpperCase());
    });
    
    const underlying = underlyings.size === 1 ? [...underlyings][0] : 'Mixed';
    const date = new Date();
    const month = date.toLocaleString('en-US', { month: 'short' });
    
    return `${underlying} ${month} Strategy (${selected.length} legs)`;
  }, [selectedPositions, positions]);

  // Toggle position selection
  const togglePositionSelection = (positionId: string) => {
    setSelectedPositions(prev => {
      const next = new Set(prev);
      if (next.has(positionId)) {
        next.delete(positionId);
      } else {
        next.add(positionId);
      }
      return next;
    });
  };

  // Select all / deselect all
  const toggleSelectAll = () => {
    if (selectedPositions.size === filteredAndSortedPositions.length) {
      setSelectedPositions(new Set());
    } else {
      setSelectedPositions(new Set(filteredAndSortedPositions.map(p => p.id)));
    }
  };

  // Create strategy from selected positions
  const handleCreateStrategy = async () => {
    if (selectedPositions.size === 0) {
      setCreateError('No positions selected');
      return;
    }
    
    const name = newStrategyName.trim();
    if (!name) {
      setCreateError('Strategy name is required');
      return;
    }
    
    setCreatingStrategy(true);
    setCreateError(null);
    
    try {
      const response = await strategiesApi.create({
        name,
        label: newStrategyLabel || undefined,
        position_ids: [...selectedPositions],
      });
      
      console.log('Strategy created:', response.data);
      
      // Reset state
      setSelectedPositions(new Set());
      setShowCreateStrategy(false);
      setNewStrategyName('');
      setNewStrategyLabel('');
      setCreateError(null);
      
      // Refresh strategies if in strategy view
      if (viewMode === 'strategies') {
        fetchStrategies();
      }
      
      // Switch to strategies view to show the new strategy
      setViewMode('strategies');
      fetchStrategies();
    } catch (error: any) {
      console.error('Failed to create strategy:', error);
      const errorMsg = error.response?.data?.detail || error.message || 'Failed to create strategy';
      setCreateError(errorMsg);
    } finally {
      setCreatingStrategy(false);
    }
  };

  // Open create strategy modal with default name
  const openCreateStrategyModal = () => {
    setNewStrategyName(generateDefaultStrategyName());
    setCreateError(null);
    setShowCreateStrategy(true);
  };

  // Strategy view helpers - update strategies with real-time WebSocket data
  const strategiesWithLiveData = useMemo(() => {
    if (!wsState.connected || wsState.positions.length === 0) {
      return strategies;
    }
    
    // Create lookup by instrument_token for fast matching
    const positionsByToken: Record<number, typeof wsState.positions[0]> = {};
    for (const pos of wsState.positions) {
      positionsByToken[pos.instrument_token] = pos;
    }
    
    // Update each strategy's trades with live data
    return strategies.map(strategy => {
      let totalUnrealized = 0;
      let totalRealized = strategy.realized_pnl;
      
      const updatedTrades = strategy.trades.map(trade => {
        const livePos = positionsByToken[trade.instrument_token];
        if (livePos && trade.status === 'OPEN') {
          // Use live data from WebSocket
          const livePnl = livePos.pnl;
          const livePnlPct = livePos.pnl_pct || 0;
          totalUnrealized += livePnl;
          
          return {
            ...trade,
            last_price: livePos.last_price,
            unrealized_pnl: livePnl,
            pnl_pct: livePnlPct
          };
        }
        // No live data, use stored values
        totalUnrealized += trade.unrealized_pnl;
        return trade;
      });
      
      return {
        ...strategy,
        trades: updatedTrades,
        unrealized_pnl: totalUnrealized,
        total_pnl: totalUnrealized + totalRealized
      };
    });
  }, [strategies, wsState.connected, wsState.positions]);

  const totalStrategyPnl = useMemo(() => 
    strategiesWithLiveData.reduce((sum: number, s: Strategy) => sum + s.total_pnl, 0),
    [strategiesWithLiveData]
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Positions</h1>
          <p className="text-[var(--muted-foreground)]">Manage your open positions</p>
        </div>
        
        {/* View Toggle */}
        <div className="flex items-center gap-1 bg-[var(--muted)] p-1 rounded-lg">
          <Button
            variant={viewMode === 'positions' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setViewMode('positions')}
            className="gap-1"
          >
            <LayoutList className="h-4 w-4" />
            Positions
          </Button>
          <Button
            variant={viewMode === 'strategies' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setViewMode('strategies')}
            className="gap-1"
          >
            <Layers className="h-4 w-4" />
            Strategies
          </Button>
        </div>
      </div>

      {viewMode === 'positions' ? (
        <Card>
          <CardHeader>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div className="flex items-center gap-3">
                  <CardTitle>Open Positions ({filteredAndSortedPositions.length})</CardTitle>
                  {/* WebSocket connection status */}
                  {wsState.connected ? (
                    <Badge variant="success" className="gap-1">
                      <Wifi className="h-3 w-3" /> Live
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="gap-1">
                      <WifiOff className="h-3 w-3" /> Polling
                    </Badge>
                  )}
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    onClick={refreshPositions}
                    disabled={isRefreshing}
                    className="h-8 w-8 p-0"
                  >
                    <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
                  </Button>
                  {(wsState.lastUpdated || lastUpdated) && (
                    <span className="text-xs text-[var(--muted-foreground)]">
                      Updated {(wsState.lastUpdated || lastUpdated)?.toLocaleTimeString()}
                    </span>
                  )}
                </div>
              <div className="flex flex-wrap items-center gap-2">
                {/* Search */}
                <div className="relative">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--muted-foreground)]" />
                  <input
                    type="text"
                    placeholder="Search symbol..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="pl-8 pr-3 py-1.5 text-sm rounded-md bg-[var(--input)] border border-[var(--border)] w-40"
                  />
                </div>

                {/* Exchange filter */}
                <select
                  value={filterExchange}
                  onChange={(e) => setFilterExchange(e.target.value)}
                  className="px-3 py-1.5 text-sm rounded-md bg-[var(--input)] border border-[var(--border)]"
                >
                  <option value="all">All Exchanges</option>
                  {uniqueExchanges.map(ex => (
                    <option key={ex} value={ex}>{ex}</option>
                  ))}
                </select>

                {/* Source filter */}
                <select
                  value={filterSource}
                  onChange={(e) => setFilterSource(e.target.value)}
                  className="px-3 py-1.5 text-sm rounded-md bg-[var(--input)] border border-[var(--border)]"
                >
                  <option value="all">All Sources</option>
                  {uniqueSources.map(src => (
                    <option key={src} value={src}>{src}</option>
                  ))}
                </select>

                {hasFilters && (
                  <Button variant="ghost" size="sm" onClick={clearFilters}>
                    <X className="h-4 w-4 mr-1" /> Clear
                  </Button>
                )}
              </div>
            </div>
          </CardHeader>
        <CardContent>
          {positions.length === 0 ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              No open positions
            </div>
          ) : filteredAndSortedPositions.length === 0 ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              No positions match your filters
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-[var(--border)]">
                      <th className="py-3 px-2 w-10">
                        <input
                          type="checkbox"
                          checked={selectedPositions.size === filteredAndSortedPositions.length && filteredAndSortedPositions.length > 0}
                          onChange={toggleSelectAll}
                          className="h-4 w-4 rounded border-[var(--border)] cursor-pointer"
                        />
                      </th>
                      <th 
                        className="text-left py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]"
                        onClick={() => handleSort('tradingsymbol')}
                      >
                        <div className="flex items-center">Symbol <SortIcon field="tradingsymbol" /></div>
                      </th>
                      <th 
                        className="text-left py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]"
                        onClick={() => handleSort('exchange')}
                      >
                        <div className="flex items-center">Exchange <SortIcon field="exchange" /></div>
                      </th>
                      <th 
                        className="text-left py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]"
                        onClick={() => handleSort('source')}
                      >
                        <div className="flex items-center">Source <SortIcon field="source" /></div>
                      </th>
                      <th 
                        className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]"
                        onClick={() => handleSort('quantity')}
                      >
                        <div className="flex items-center justify-end">Qty <SortIcon field="quantity" /></div>
                      </th>
                      <th 
                        className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]"
                        onClick={() => handleSort('average_price')}
                      >
                        <div className="flex items-center justify-end">Avg Price <SortIcon field="average_price" /></div>
                      </th>
                      <th 
                        className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]"
                        onClick={() => handleSort('last_price')}
                      >
                        <div className="flex items-center justify-end">LTP <SortIcon field="last_price" /></div>
                      </th>
                      <th 
                        className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]"
                        onClick={() => handleSort('pnl')}
                      >
                        <div className="flex items-center justify-end">P&L <SortIcon field="pnl" /></div>
                      </th>
                      <th 
                        className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]"
                        onClick={() => handleSort('pnl_pct')}
                      >
                        <div className="flex items-center justify-end">P&L % <SortIcon field="pnl_pct" /></div>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredAndSortedPositions.map((position) => (
                      <tr 
                        key={position.id} 
                        className={`border-b border-[var(--border)] hover:bg-[var(--muted)] ${selectedPositions.has(position.id) ? 'bg-[var(--muted)]/50' : ''}`}
                      >
                        <td className="py-3 px-2">
                          <input
                            type="checkbox"
                            checked={selectedPositions.has(position.id)}
                            onChange={() => togglePositionSelection(position.id)}
                            className="h-4 w-4 rounded border-[var(--border)] cursor-pointer"
                          />
                        </td>
                        <td className="py-3 px-4 font-medium">{position.tradingsymbol}</td>
                        <td className="py-3 px-4">
                          <Badge variant="outline">{position.exchange}</Badge>
                        </td>
                        <td className="py-3 px-4">
                          <Badge variant={position.source === 'LIVE' ? 'destructive' : 'warning'}>
                            {position.source || 'LIVE'}
                          </Badge>
                        </td>
                        <td className="py-3 px-4 text-right">{position.quantity}</td>
                        <td className="py-3 px-4 text-right">{formatCurrency(position.average_price)}</td>
                        <td className="py-3 px-4 text-right">{formatCurrency(position.last_price)}</td>
                        <td className={`py-3 px-4 text-right font-medium ${position.pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatCurrency(position.pnl)}
                        </td>
                        <td className={`py-3 px-4 text-right ${position.pnl_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatPercent(position.pnl_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Summary row */}
              <div className="mt-4 pt-4 border-t border-[var(--border)] flex justify-between items-center">
                <div className="flex items-center gap-4">
                  <span className="text-sm text-[var(--muted-foreground)]">
                    {filteredAndSortedPositions.length} position{filteredAndSortedPositions.length !== 1 ? 's' : ''}
                  </span>
                  {selectedPositions.size > 0 && (
                    <Button 
                      size="sm" 
                      onClick={openCreateStrategyModal}
                      className="gap-1"
                    >
                      <Plus className="h-4 w-4" />
                      Create Strategy ({selectedPositions.size} selected)
                    </Button>
                  )}
                </div>
                <div className="text-right">
                  <span className="text-sm text-[var(--muted-foreground)]">Total P&L: </span>
                  <span className={`font-bold ${totalPnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                    {formatCurrency(totalPnl)}
                  </span>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      ) : (
        /* Strategy View */
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Strategies</CardTitle>
              <Button variant="outline" size="sm" onClick={fetchStrategies} disabled={loadingStrategies}>
                {loadingStrategies ? 'Loading...' : 'Refresh'}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {loadingStrategies ? (
              <div className="text-center py-8 text-[var(--muted-foreground)]">
                Loading strategies...
              </div>
            ) : strategiesWithLiveData.length === 0 ? (
              <div className="text-center py-8 text-[var(--muted-foreground)]">
                No strategies created yet. Select positions and click "Create Strategy" to get started.
              </div>
            ) : (
              <div className="space-y-4">
                {strategiesWithLiveData.map((strategy) => (
                  <div key={strategy.id} className="border border-[var(--border)] rounded-lg overflow-hidden">
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
                          <p className="text-xs text-[var(--muted-foreground)]">Unrealized</p>
                          <p className={`font-medium ${strategy.unrealized_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                            {formatCurrency(strategy.unrealized_pnl)}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="text-xs text-[var(--muted-foreground)]">Realized</p>
                          <p className={`font-medium ${strategy.realized_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                            {formatCurrency(strategy.realized_pnl)}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="text-xs text-[var(--muted-foreground)]">Total P&L</p>
                          <p className={`font-bold ${strategy.total_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                            {formatCurrency(strategy.total_pnl)}
                          </p>
                        </div>
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
                            </tr>
                          </thead>
                          <tbody>
                            {strategy.trades.map((trade) => (
                              <tr key={trade.id} className="border-b border-[var(--border)] hover:bg-[var(--muted)]/50">
                                <td className="py-2 px-4 text-sm font-medium">{trade.tradingsymbol}</td>
                                <td className="py-2 px-4">
                                  <Badge variant="outline" className="text-xs">
                                    {trade.exchange}
                                  </Badge>
                                </td>
                                <td className="py-2 px-4 text-sm text-right">{trade.quantity}</td>
                                <td className="py-2 px-4 text-sm text-right">{formatCurrency(trade.entry_price)}</td>
                                <td className="py-2 px-4 text-sm text-right">{trade.last_price ? formatCurrency(trade.last_price) : '-'}</td>
                                <td className={`py-2 px-4 text-sm text-right font-medium ${trade.unrealized_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                                  {formatCurrency(trade.unrealized_pnl)}
                                </td>
                                <td className={`py-2 px-4 text-sm text-right ${trade.pnl_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                                  {formatPercent(trade.pnl_pct)}
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
                    {strategiesWithLiveData.length} strateg{strategiesWithLiveData.length !== 1 ? 'ies' : 'y'}
                  </span>
                  <div className="text-right">
                    <span className="text-sm text-[var(--muted-foreground)]">Total P&L: </span>
                    <span className={`font-bold ${totalStrategyPnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                      {formatCurrency(totalStrategyPnl)}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Create Strategy Modal */}
      {showCreateStrategy && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-full max-w-md mx-4">
            <CardHeader>
              <CardTitle>Create Strategy</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium text-[var(--muted-foreground)]">Strategy Name</label>
                <input
                  type="text"
                  value={newStrategyName}
                  onChange={(e) => setNewStrategyName(e.target.value)}
                  placeholder="Enter strategy name..."
                  className="w-full mt-1 px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)]"
                />
              </div>
              <div>
                <label className="text-sm font-medium text-[var(--muted-foreground)]">Label (optional)</label>
                <select
                  value={newStrategyLabel}
                  onChange={(e) => setNewStrategyLabel(e.target.value)}
                  className="w-full mt-1 px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)]"
                >
                  <option value="">No label</option>
                  <option value="IRON_CONDOR">Iron Condor</option>
                  <option value="JADE_LIZARD">Jade Lizard</option>
                  <option value="BUTTERFLY">Butterfly</option>
                  <option value="SPREAD">Spread</option>
                  <option value="STRADDLE">Straddle</option>
                  <option value="STRANGLE">Strangle</option>
                  <option value="CUSTOM">Custom</option>
                </select>
              </div>
              <div className="text-sm text-[var(--muted-foreground)]">
                <Check className="h-4 w-4 inline mr-1" />
                {selectedPositions.size} position{selectedPositions.size !== 1 ? 's' : ''} selected
              </div>
              {createError && (
                <div className="text-sm text-[var(--loss)] bg-[var(--loss)]/10 px-3 py-2 rounded">
                  {createError}
                </div>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <Button 
                  variant="outline" 
                  onClick={() => setShowCreateStrategy(false)}
                >
                  Cancel
                </Button>
                <Button 
                  onClick={handleCreateStrategy}
                  disabled={creatingStrategy || !newStrategyName.trim()}
                >
                  {creatingStrategy ? 'Creating...' : 'Create Strategy'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
