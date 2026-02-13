/**
 * Positions Page - Display only, all data comes from backend.
 */

import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { SourceBadge } from '@/components/ui/source-badge';
import { Button } from '@/components/ui/button';
import { formatCurrency, formatPercent } from '@/lib/utils';
import { ArrowUpDown, ArrowUp, ArrowDown, Search, X, Plus, RefreshCw } from 'lucide-react';
import { ConnectionBadge } from '@/components/ui/connection-badge';
import { strategiesApi } from '@/services/api';
import { portfolioApi, type Position, type PositionsResponse } from '@/services/portfolioApi';
import { useWebSocket } from '@/hooks/useWebSocket';

type SortField = keyof Position;
type SortDirection = 'asc' | 'desc';

export function PositionsPage() {
  const { connected, positions: wsPositions } = useWebSocket();
  
  // All data comes from backend - no frontend calculations
  const [data, setData] = useState<PositionsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  
  const [sortField, setSortField] = useState<SortField>('pnl');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [searchTerm, setSearchTerm] = useState('');
  const [filterExchange, setFilterExchange] = useState<string>('all');
  const [filterSource, setFilterSource] = useState<'all' | 'LIVE' | 'PAPER'>('all');
  const [filterProduct, setFilterProduct] = useState<string>('all');
  const [filterDirection, setFilterDirection] = useState<'all' | 'LONG' | 'SHORT'>('all');
  const [filterStatus, setFilterStatus] = useState<'all' | 'OPEN' | 'CLOSED'>('OPEN');  // Default to OPEN
  const [groupBy, setGroupBy] = useState<'none' | 'underlying' | 'expiry'>('none');
  const [showSettings, setShowSettings] = useState(false);
  const [selectedPositions, setSelectedPositions] = useState<Set<string>>(new Set());
  const [showCreateStrategy, setShowCreateStrategy] = useState(false);
  const [newStrategyName, setNewStrategyName] = useState('');
  const [creatingStrategy, setCreatingStrategy] = useState(false);
  
  // Trailing stop config for strategy creation
  const [trailingStopEnabled, setTrailingStopEnabled] = useState(false);
  const [trailingActivationPct, setTrailingActivationPct] = useState(0.8);
  const [trailingStepPct, setTrailingStepPct] = useState(0.1);
  const [trailingLockPct, setTrailingLockPct] = useState(0.05);

  const fetchData = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const response = await portfolioApi.getPositions();
      setData(response.data);
    } catch (error) {
      console.error('Failed to fetch positions:', error);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Merge WebSocket updates with initial data for real-time prices
  const positions = useMemo(() => {
    const basePositions = data?.positions || [];
    if (!wsPositions.length) return basePositions;
    
    // Create lookup from WebSocket data
    const wsLookup = new Map(wsPositions.map(p => [p.instrument_token, p]));
    
    // Merge: use WebSocket prices if available
    return basePositions.map(pos => {
      const wsPos = wsLookup.get(pos.instrument_token);
      if (wsPos && wsPos.last_price) {
        return {
          ...pos,
          last_price: wsPos.last_price,
          ltp_change: wsPos.ltp_change ?? pos.ltp_change,
          ltp_change_pct: wsPos.ltp_change_pct ?? pos.ltp_change_pct,
          pnl: wsPos.pnl,
          pnl_pct: wsPos.pnl_pct || pos.pnl_pct,
        };
      }
      return pos;
    });
  }, [data?.positions, wsPositions]);
  
  const account = data?.account;
  
  // Recalculate totals when positions update from WebSocket
  const totals = useMemo(() => {
    if (!positions.length) return data?.totals;
    const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0);
    const totalMargin = positions.reduce((sum, p) => sum + p.margin_used, 0);
    return {
      pnl: totalPnl,
      margin: totalMargin,
      pnl_on_margin_pct: totalMargin > 0 ? (totalPnl / totalMargin * 100) : 0,
      count: positions.length
    };
  }, [positions, data?.totals]);

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

  // Get unique products for filter
  const uniqueProducts = useMemo(() => 
    [...new Set(positions.map(p => p.product))], [positions]
  );

  // Only filtering and sorting in frontend - no calculations
  const filteredAndSortedPositions = useMemo(() => {
    let result = [...positions];

    if (searchTerm) {
      result = result.filter(p => 
        p.tradingsymbol.toLowerCase().includes(searchTerm.toLowerCase())
      );
    }

    if (filterExchange !== 'all') {
      result = result.filter(p => p.exchange === filterExchange);
    }

    if (filterSource !== 'all') {
      result = result.filter(p => p.source === filterSource);
    }

    if (filterProduct !== 'all') {
      result = result.filter(p => p.product === filterProduct);
    }

    if (filterDirection !== 'all') {
      result = result.filter(p => 
        filterDirection === 'LONG' ? !p.is_short : p.is_short
      );
    }

    if (filterStatus !== 'all') {
      result = result.filter(p => p.position_status === filterStatus);
    }

    result.sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];
      const modifier = sortDirection === 'asc' ? 1 : -1;
      
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return aVal.localeCompare(bVal) * modifier;
      }
      return ((aVal as number) - (bVal as number)) * modifier;
    });

    return result;
  }, [positions, searchTerm, filterExchange, filterSource, filterProduct, filterDirection, filterStatus, sortField, sortDirection]);

  // Group positions by underlying or expiry
  const groupedPositions = useMemo(() => {
    if (groupBy === 'none') return null;
    
    const groups: Record<string, { positions: typeof filteredAndSortedPositions; pnl: number }> = {};
    
    for (const pos of filteredAndSortedPositions) {
      const key = groupBy === 'underlying' 
        ? (pos.underlying || pos.tradingsymbol)
        : (pos.expiry || 'Equity');
      
      if (!groups[key]) {
        groups[key] = { positions: [], pnl: 0 };
      }
      groups[key].positions.push(pos);
      groups[key].pnl += pos.pnl;
    }
    
    return groups;
  }, [filteredAndSortedPositions, groupBy]);

  const togglePositionSelection = (id: string) => {
    setSelectedPositions(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleCreateStrategy = async () => {
    if (!newStrategyName.trim() || selectedPositions.size === 0) return;
    
    setCreatingStrategy(true);
    try {
      await strategiesApi.create({
        name: newStrategyName,
        position_ids: Array.from(selectedPositions),
        trailing_stop: {
          enabled: trailingStopEnabled,
          activation_pct: trailingActivationPct,
          step_pct: trailingStepPct,
          lock_pct: trailingLockPct,
        },
      });
      setSelectedPositions(new Set());
      setShowCreateStrategy(false);
      setNewStrategyName('');
      // Reset trailing stop config to defaults
      setTrailingStopEnabled(false);
      setTrailingActivationPct(0.8);
      setTrailingStepPct(0.1);
      setTrailingLockPct(0.05);
    } catch (error) {
      console.error('Failed to create strategy:', error);
    } finally {
      setCreatingStrategy(false);
    }
  };

  if (isLoading) {
    return <div className="text-center py-8 text-[var(--muted-foreground)]">Loading positions...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Positions</h1>
          <p className="text-[var(--muted-foreground)]">Manage your open positions with margin tracking</p>
        </div>
        <div className="flex items-center gap-2">
          <ConnectionBadge connected={connected} />
        </div>
      </div>

      {/* Account Summary - data from backend */}
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
            <p className="text-xs text-[var(--muted-foreground)]">+{formatCurrency(account.collateral)} collateral</p>
          </CardContent></Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>
              {filterStatus === 'OPEN' ? 'Open' : filterStatus === 'CLOSED' ? 'Closed' : 'All'} Positions ({filteredAndSortedPositions.length})
            </CardTitle>
            <div className="flex items-center gap-4">
              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value as 'all' | 'OPEN' | 'CLOSED')}
                className="px-3 py-2 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none font-medium"
              >
                <option value="all">All Positions</option>
                <option value="OPEN">Open Positions</option>
                <option value="CLOSED">Closed Positions</option>
              </select>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-[var(--muted-foreground)]" />
                <input
                  type="text"
                  placeholder="Search symbol..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-9 pr-8 py-2 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md w-48 focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                />
                {searchTerm && (
                  <button onClick={() => setSearchTerm('')} className="absolute right-2 top-1/2 transform -translate-y-1/2">
                    <X className="h-4 w-4 text-[var(--muted-foreground)]" />
                  </button>
                )}
              </div>
              <select
                value={filterExchange}
                onChange={(e) => setFilterExchange(e.target.value)}
                className="px-3 py-2 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none"
              >
                <option value="all">All Exchanges</option>
                {uniqueExchanges.map(ex => <option key={ex} value={ex}>{ex}</option>)}
              </select>
              <select
                value={filterSource}
                onChange={(e) => setFilterSource(e.target.value as 'all' | 'LIVE' | 'PAPER')}
                className="px-3 py-2 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none"
              >
                <option value="all">All Sources</option>
                <option value="LIVE">Live (Kite)</option>
                <option value="PAPER">Paper (Simulator)</option>
              </select>
              <select
                value={filterProduct}
                onChange={(e) => setFilterProduct(e.target.value)}
                className="px-3 py-2 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none"
              >
                <option value="all">All Products</option>
                {uniqueProducts.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
              <select
                value={filterDirection}
                onChange={(e) => setFilterDirection(e.target.value as 'all' | 'LONG' | 'SHORT')}
                className="px-3 py-2 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none"
              >
                <option value="all">All Directions</option>
                <option value="LONG">Long</option>
                <option value="SHORT">Short</option>
              </select>
              <div className="relative">
                <Button variant="outline" size="sm" onClick={() => setShowSettings(!showSettings)}>
                  Settings
                </Button>
                {showSettings && (
                  <div className="absolute right-0 top-full mt-2 w-64 bg-[var(--card)] border border-[var(--border)] rounded-lg shadow-lg p-4 z-50">
                    <div className="space-y-4">
                      <div>
                        <p className="text-sm font-medium mb-2">GROUPING</p>
                        <div className="space-y-1">
                          <label className="flex items-center gap-2 text-sm">
                            <input type="radio" name="groupBy" checked={groupBy === 'none'} onChange={() => setGroupBy('none')} />
                            None
                          </label>
                          <label className="flex items-center gap-2 text-sm">
                            <input type="radio" name="groupBy" checked={groupBy === 'underlying'} onChange={() => setGroupBy('underlying')} />
                            Underlying
                          </label>
                          <label className="flex items-center gap-2 text-sm">
                            <input type="radio" name="groupBy" checked={groupBy === 'expiry'} onChange={() => setGroupBy('expiry')} />
                            Underlying & Expiry
                          </label>
                        </div>
                      </div>
                      <Button variant="outline" size="sm" className="w-full" onClick={() => {
                        setFilterExchange('all');
                        setFilterSource('all');
                        setFilterProduct('all');
                        setFilterDirection('all');
                        setFilterStatus('OPEN');
                        setGroupBy('none');
                      }}>
                        CLEAR
                      </Button>
                    </div>
                  </div>
                )}
              </div>
              <Button variant="outline" size="sm" onClick={fetchData} disabled={isRefreshing}>
                <RefreshCw className={`h-4 w-4 mr-1 ${isRefreshing ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  <th className="w-8 py-3 px-2">
                    <input
                      type="checkbox"
                      checked={selectedPositions.size === filteredAndSortedPositions.length && filteredAndSortedPositions.length > 0}
                      onChange={() => {
                        if (selectedPositions.size === filteredAndSortedPositions.length) {
                          setSelectedPositions(new Set());
                        } else {
                          setSelectedPositions(new Set(filteredAndSortedPositions.map(p => p.id)));
                        }
                      }}
                      className="h-4 w-4 rounded border-[var(--border)]"
                    />
                  </th>
                  <th className="text-left py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]" onClick={() => handleSort('tradingsymbol')}>
                    <div className="flex items-center">Symbol <SortIcon field="tradingsymbol" /></div>
                  </th>
                  <th className="text-left py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]" onClick={() => handleSort('exchange')}>
                    <div className="flex items-center">Exchange <SortIcon field="exchange" /></div>
                  </th>
                  <th className="text-left py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]" onClick={() => handleSort('source')}>
                    <div className="flex items-center">Source <SortIcon field="source" /></div>
                  </th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]" onClick={() => handleSort('quantity')}>
                    <div className="flex items-center justify-end">Qty <SortIcon field="quantity" /></div>
                  </th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]" onClick={() => handleSort('average_price')}>
                    <div className="flex items-center justify-end">Avg Price <SortIcon field="average_price" /></div>
                  </th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]" onClick={() => handleSort('last_price')}>
                    <div className="flex items-center justify-end">LTP <SortIcon field="last_price" /></div>
                  </th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]" onClick={() => handleSort('pnl')}>
                    <div className="flex items-center justify-end">P&L <SortIcon field="pnl" /></div>
                  </th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]" onClick={() => handleSort('pnl_pct')}>
                    <div className="flex items-center justify-end">P&L % <SortIcon field="pnl_pct" /></div>
                  </th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]" onClick={() => handleSort('margin_used')}>
                    <div className="flex items-center justify-end">Margin <SortIcon field="margin_used" /></div>
                  </th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]" onClick={() => handleSort('pnl_on_margin_pct')}>
                    <div className="flex items-center justify-end">P&L/Margin <SortIcon field="pnl_on_margin_pct" /></div>
                  </th>
                </tr>
              </thead>
              <tbody>
                {groupBy !== 'none' && groupedPositions ? (
                  // Grouped view
                  Object.entries(groupedPositions).map(([groupName, group]) => (
                    <React.Fragment key={`group-${groupName}`}>
                      {/* Group header row */}
                      <tr className="bg-[var(--muted)]/30">
                        <td colSpan={7} className="py-2 px-4 font-medium">
                          <div className="flex items-center gap-2">
                            <span>{groupName}</span>
                            <span className="text-xs text-[var(--muted-foreground)]">({group.positions.length})</span>
                          </div>
                        </td>
                        <td className={`py-2 px-4 text-right font-medium ${group.pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatCurrency(group.pnl)}
                        </td>
                        <td colSpan={3}></td>
                      </tr>
                      {/* Group positions */}
                      {group.positions.map((position) => (
                        <tr 
                          key={position.id} 
                          className={`border-b border-[var(--border)] hover:bg-[var(--muted)] ${selectedPositions.has(position.id) ? 'bg-[var(--muted)]/50' : ''}`}
                        >
                          <td className="py-3 px-2">
                            <input
                              type="checkbox"
                              checked={selectedPositions.has(position.id)}
                              onChange={() => togglePositionSelection(position.id)}
                              className="h-4 w-4 rounded border-[var(--border)]"
                            />
                          </td>
                          <td className="py-3 px-4 pl-8">
                            <div className="flex items-center gap-2">
                              <Badge 
                                variant="outline" 
                                className={
                                  position.product === 'CNC' ? 'bg-blue-500/10 text-blue-500 border-blue-500/30' :
                                  position.product === 'NRML' ? 'bg-orange-500/10 text-orange-500 border-orange-500/30' :
                                  'bg-purple-500/10 text-purple-500 border-purple-500/30'
                                }
                              >
                                {position.product}
                              </Badge>
                              <span className="font-medium">{position.tradingsymbol}</span>
                              {position.instrument_type !== 'EQ' && (
                                <span className="text-xs text-[var(--muted-foreground)]">
                                  {position.instrument_type}
                                </span>
                              )}
                              {position.is_sold_holding && (
                                <span className="text-xs text-[var(--muted-foreground)]">SOLD HOLDING</span>
                              )}
                              {position.is_short && (
                                <span className="text-xs text-[var(--loss)]">SHORT</span>
                              )}
                            </div>
                          </td>
                          <td className="py-3 px-4">
                            <Badge variant="outline">{position.exchange}</Badge>
                          </td>
                          <td className="py-3 px-4">
                            <SourceBadge source={position.source as 'LIVE' | 'PAPER'} />
                          </td>
                          <td className="py-3 px-4 text-right">{position.quantity}</td>
                          <td className="py-3 px-4 text-right">{formatCurrency(position.average_price)}</td>
                          <td className="py-3 px-4 text-right">
                            <div>{formatCurrency(position.last_price)}</div>
                            <div className={`text-xs ${(position.ltp_change_pct || 0) >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                              {formatPercent(position.ltp_change_pct || 0)}
                            </div>
                          </td>
                          <td className={`py-3 px-4 text-right font-medium ${position.pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                            {formatCurrency(position.pnl)}
                          </td>
                          <td className={`py-3 px-4 text-right ${position.pnl_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                            {formatPercent(position.pnl_pct)}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <div>{formatCurrency(position.margin_used)}</div>
                            <div className="text-xs text-[var(--muted-foreground)]">{formatPercent(position.margin_pct)}</div>
                          </td>
                          <td className={`py-3 px-4 text-right font-medium ${position.pnl_on_margin_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                            {formatPercent(position.pnl_on_margin_pct)}
                          </td>
                        </tr>
                      ))}
                    </React.Fragment>
                  ))
                ) : (
                  // Flat view (no grouping)
                  filteredAndSortedPositions.map((position) => (
                    <tr 
                      key={position.id} 
                      className={`border-b border-[var(--border)] hover:bg-[var(--muted)] ${selectedPositions.has(position.id) ? 'bg-[var(--muted)]/50' : ''}`}
                    >
                      <td className="py-3 px-2">
                        <input
                          type="checkbox"
                          checked={selectedPositions.has(position.id)}
                          onChange={() => togglePositionSelection(position.id)}
                          className="h-4 w-4 rounded border-[var(--border)]"
                        />
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <Badge 
                            variant="outline" 
                            className={
                              position.product === 'CNC' ? 'bg-blue-500/10 text-blue-500 border-blue-500/30' :
                              position.product === 'NRML' ? 'bg-orange-500/10 text-orange-500 border-orange-500/30' :
                              'bg-purple-500/10 text-purple-500 border-purple-500/30'
                            }
                          >
                            {position.product}
                          </Badge>
                          <span className="font-medium">{position.tradingsymbol}</span>
                          {position.instrument_type !== 'EQ' && (
                            <span className="text-xs text-[var(--muted-foreground)]">
                              {position.instrument_type}
                            </span>
                          )}
                          {position.is_sold_holding && (
                            <span className="text-xs text-[var(--muted-foreground)]">SOLD HOLDING</span>
                          )}
                          {position.is_short && (
                            <span className="text-xs text-[var(--loss)]">SHORT</span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <Badge variant="outline">{position.exchange}</Badge>
                      </td>
                      <td className="py-3 px-4">
                        <SourceBadge source={position.source as 'LIVE' | 'PAPER'} />
                      </td>
                      <td className="py-3 px-4 text-right">{position.quantity}</td>
                      <td className="py-3 px-4 text-right">{formatCurrency(position.average_price)}</td>
                      <td className="py-3 px-4 text-right">
                        <div>{formatCurrency(position.last_price)}</div>
                        <div className={`text-xs ${(position.ltp_change_pct || 0) >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatPercent(position.ltp_change_pct || 0)}
                        </div>
                      </td>
                      <td className={`py-3 px-4 text-right font-medium ${position.pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                        {formatCurrency(position.pnl)}
                      </td>
                      <td className={`py-3 px-4 text-right ${position.pnl_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                        {formatPercent(position.pnl_pct)}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <div>{formatCurrency(position.margin_used)}</div>
                        <div className="text-xs text-[var(--muted-foreground)]">{formatPercent(position.margin_pct)}</div>
                      </td>
                      <td className={`py-3 px-4 text-right font-medium ${position.pnl_on_margin_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                        {formatPercent(position.pnl_on_margin_pct)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Footer with totals from backend */}
          <div className="mt-4 pt-4 border-t border-[var(--border)] flex justify-between items-center">
            <div className="flex items-center gap-4">
              <span className="text-sm text-[var(--muted-foreground)]">
                {filteredAndSortedPositions.length} position{filteredAndSortedPositions.length !== 1 ? 's' : ''}
              </span>
              {selectedPositions.size > 0 && (
                <Button 
                  size="sm" 
                  onClick={() => {
                    const date = new Date();
                    setNewStrategyName(`Strategy ${date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`);
                    setShowCreateStrategy(true);
                  }}
                  className="gap-1"
                >
                  <Plus className="h-4 w-4" />
                  Create Strategy ({selectedPositions.size} selected)
                </Button>
              )}
            </div>
            {totals && (
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
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Create Strategy Modal */}
      {showCreateStrategy && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-[480px]">
            <CardHeader>
              <CardTitle>Create Strategy</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm text-[var(--muted-foreground)]">Strategy Name</label>
                <input
                  type="text"
                  value={newStrategyName}
                  onChange={(e) => setNewStrategyName(e.target.value)}
                  className="w-full mt-1 px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  placeholder="Enter strategy name"
                />
              </div>
              <p className="text-sm text-[var(--muted-foreground)]">
                {selectedPositions.size} position{selectedPositions.size !== 1 ? 's' : ''} will be added to this strategy.
              </p>
              
              {/* Trailing Stop Configuration */}
              <div className="border border-[var(--border)] rounded-lg p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium">Trailing Stop-Loss</label>
                  <button
                    type="button"
                    onClick={() => setTrailingStopEnabled(!trailingStopEnabled)}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      trailingStopEnabled ? 'bg-[var(--primary)]' : 'bg-[var(--muted)]'
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        trailingStopEnabled ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>
                
                {trailingStopEnabled && (
                  <div className="space-y-3 pt-2 border-t border-[var(--border)]">
                    <p className="text-xs text-[var(--muted-foreground)]">
                      Automatically trail profits when P&L exceeds activation threshold.
                    </p>
                    <div className="grid grid-cols-3 gap-3">
                      <div>
                        <label className="text-xs text-[var(--muted-foreground)]">Activation %</label>
                        <input
                          type="number"
                          step="0.1"
                          value={trailingActivationPct}
                          onChange={(e) => setTrailingActivationPct(parseFloat(e.target.value) || 0.8)}
                          className="w-full mt-1 px-2 py-1.5 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                        />
                        <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">of margin</p>
                      </div>
                      <div>
                        <label className="text-xs text-[var(--muted-foreground)]">Step %</label>
                        <input
                          type="number"
                          step="0.05"
                          value={trailingStepPct}
                          onChange={(e) => setTrailingStepPct(parseFloat(e.target.value) || 0.1)}
                          className="w-full mt-1 px-2 py-1.5 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                        />
                        <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">P&L increase</p>
                      </div>
                      <div>
                        <label className="text-xs text-[var(--muted-foreground)]">Lock %</label>
                        <input
                          type="number"
                          step="0.01"
                          value={trailingLockPct}
                          onChange={(e) => setTrailingLockPct(parseFloat(e.target.value) || 0.05)}
                          className="w-full mt-1 px-2 py-1.5 text-sm bg-[var(--background)] border border-[var(--border)] rounded-md focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                        />
                        <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">per step</p>
                      </div>
                    </div>
                    <p className="text-xs text-[var(--muted-foreground)] bg-[var(--muted)] p-2 rounded">
                      When P&L ≥ {trailingActivationPct}% of margin, lock in profits. 
                      Every {trailingStepPct}% increase raises floor by {trailingLockPct}%.
                    </p>
                  </div>
                )}
              </div>
              
              <div className="flex gap-2 justify-end">
                <Button variant="outline" onClick={() => setShowCreateStrategy(false)}>
                  Cancel
                </Button>
                <Button onClick={handleCreateStrategy} disabled={creatingStrategy || !newStrategyName.trim()}>
                  {creatingStrategy ? 'Creating...' : 'Create'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
