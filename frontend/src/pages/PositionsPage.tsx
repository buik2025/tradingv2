import { useEffect, useState, useMemo, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatCurrency, formatPercent } from '@/lib/utils';
import { ArrowUpDown, ArrowUp, ArrowDown, Search, X, Plus, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { positionsApi, strategiesApi, type PositionWithMargin } from '@/services/api';
import { useWebSocket } from '@/hooks/useWebSocket';
import { AccountSummary } from '@/components/AccountSummary';

type SortField = 'tradingsymbol' | 'exchange' | 'quantity' | 'average_price' | 'last_price' | 'pnl' | 'pnl_pct' | 'margin_used' | 'margin_pct' | 'pnl_on_margin_pct';
type SortDirection = 'asc' | 'desc';

export function PositionsPage() {
  const wsState = useWebSocket();
  
  const [positions, setPositions] = useState<PositionWithMargin[]>([]);
  const [sortField, setSortField] = useState<SortField>('pnl');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [searchTerm, setSearchTerm] = useState('');
  const [filterExchange, setFilterExchange] = useState<string>('all');
  const [selectedPositions, setSelectedPositions] = useState<Set<string>>(new Set());
  const [showCreateStrategy, setShowCreateStrategy] = useState(false);
  const [newStrategyName, setNewStrategyName] = useState('');
  const [creatingStrategy, setCreatingStrategy] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const fetchPositions = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const response = await positionsApi.getWithMargins();
      setPositions(response.data.positions || []);
    } catch (error) {
      console.error('Failed to fetch positions:', error);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchPositions();
  }, [fetchPositions]);

  // Update positions with WebSocket data for real-time P&L
  const positionsWithLiveData = useMemo(() => {
    if (!wsState.connected || wsState.positions.length === 0) {
      return positions;
    }
    
    const positionsByToken: Record<number, typeof wsState.positions[0]> = {};
    for (const pos of wsState.positions) {
      positionsByToken[pos.instrument_token] = pos;
    }
    
    return positions.map(pos => {
      const livePos = positionsByToken[pos.instrument_token];
      if (livePos) {
        const pnl = livePos.pnl;
        const pnlOnMarginPct = pos.margin_used > 0 ? (pnl / pos.margin_used * 100) : 0;
        return {
          ...pos,
          last_price: livePos.last_price || pos.last_price,
          pnl: pnl,
          pnl_pct: livePos.pnl_pct || pos.pnl_pct,
          pnl_on_margin_pct: pnlOnMarginPct
        };
      }
      return pos;
    });
  }, [positions, wsState.connected, wsState.positions]);

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
    [...new Set(positionsWithLiveData.map(p => p.exchange))], [positionsWithLiveData]
  );

  const filteredAndSortedPositions = useMemo(() => {
    let result = [...positionsWithLiveData];

    if (searchTerm) {
      result = result.filter(p => 
        p.tradingsymbol.toLowerCase().includes(searchTerm.toLowerCase())
      );
    }

    if (filterExchange !== 'all') {
      result = result.filter(p => p.exchange === filterExchange);
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
  }, [positionsWithLiveData, searchTerm, filterExchange, sortField, sortDirection]);

  const totalPnl = useMemo(() => 
    filteredAndSortedPositions.reduce((sum, p) => sum + p.pnl, 0),
    [filteredAndSortedPositions]
  );

  const totalMarginUsed = useMemo(() => 
    filteredAndSortedPositions.reduce((sum, p) => sum + p.margin_used, 0),
    [filteredAndSortedPositions]
  );

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
      });
      
      setSelectedPositions(new Set());
      setShowCreateStrategy(false);
      setNewStrategyName('');
    } catch (error) {
      console.error('Failed to create strategy:', error);
    } finally {
      setCreatingStrategy(false);
    }
  };

  const generateDefaultStrategyName = () => {
    const date = new Date();
    return `Strategy ${date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Positions</h1>
          <p className="text-[var(--muted-foreground)]">Manage your open positions with margin tracking</p>
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
            <CardTitle className="flex items-center gap-2">
              Open Positions ({filteredAndSortedPositions.length})
            </CardTitle>
            <div className="flex items-center gap-4">
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
                  <button
                    onClick={() => setSearchTerm('')}
                    className="absolute right-2 top-1/2 transform -translate-y-1/2"
                  >
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
                {uniqueExchanges.map(ex => (
                  <option key={ex} value={ex}>{ex}</option>
                ))}
              </select>
              <Button variant="outline" size="sm" onClick={() => { fetchPositions(); setRefreshTrigger(t => t + 1); }} disabled={isRefreshing}>
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
                        className="h-4 w-4 rounded border-[var(--border)]"
                      />
                    </td>
                    <td className="py-3 px-4 font-medium">{position.tradingsymbol}</td>
                    <td className="py-3 px-4">
                      <Badge variant="outline">{position.exchange}</Badge>
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
                    <td className="py-3 px-4 text-right">
                      <div>{formatCurrency(position.margin_used)}</div>
                      <div className="text-xs text-[var(--muted-foreground)]">{formatPercent(position.margin_pct)}</div>
                    </td>
                    <td className={`py-3 px-4 text-right font-medium ${position.pnl_on_margin_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                      {formatPercent(position.pnl_on_margin_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 pt-4 border-t border-[var(--border)] flex justify-between items-center">
            <div className="flex items-center gap-4">
              <span className="text-sm text-[var(--muted-foreground)]">
                {filteredAndSortedPositions.length} position{filteredAndSortedPositions.length !== 1 ? 's' : ''}
              </span>
              {selectedPositions.size > 0 && (
                <Button 
                  size="sm" 
                  onClick={() => {
                    setNewStrategyName(generateDefaultStrategyName());
                    setShowCreateStrategy(true);
                  }}
                  className="gap-1"
                >
                  <Plus className="h-4 w-4" />
                  Create Strategy ({selectedPositions.size} selected)
                </Button>
              )}
            </div>
            <div className="flex items-center gap-6">
              <div className="text-right">
                <span className="text-sm text-[var(--muted-foreground)]">Total Margin: </span>
                <span className="font-bold">{formatCurrency(totalMarginUsed)}</span>
              </div>
              <div className="text-right">
                <span className="text-sm text-[var(--muted-foreground)]">Total P&L: </span>
                <span className={`font-bold ${totalPnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                  {formatCurrency(totalPnl)}
                </span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Create Strategy Modal */}
      {showCreateStrategy && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-96">
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
