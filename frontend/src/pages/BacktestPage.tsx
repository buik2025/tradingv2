import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { 
  Play, Download, TrendingUp, TrendingDown, Target, 
  BarChart3, Activity, AlertTriangle, CheckCircle,
  ChevronDown, ChevronUp, RefreshCw
} from 'lucide-react';

const API_BASE = '/api/v1';

interface StrategyInfo {
  id: string;
  name: string;
  description: string;
  regime: string;
  risk_profile: string;
  category?: string;
  asset_class?: string;
}

interface TradeResult {
  id: string;
  strategy_type: string;
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
  holding_days: number;
  regime_at_entry: string;
  regime_at_exit: string;
}

interface StrategyMetrics {
  total_trades: number;
  total_pnl: number;
  win_rate: number;
  avg_pnl: number;
  profit_factor: number;
}

interface BacktestResult {
  total_return: number;
  total_return_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  max_drawdown_duration: number;
  win_rate: number;
  profit_factor: number;
  avg_win: number;
  avg_loss: number;
  expectancy: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  avg_holding_days: number;
  by_strategy: Record<string, StrategyMetrics>;
  by_regime: Record<string, { total_trades: number; total_pnl: number; win_rate: number }>;
  equity_curve: number[];
  drawdown_curve: number[];
  regime_distribution: Record<string, number>;
  trades: TradeResult[];
}

interface MonteCarloResult {
  base_total_return_pct: number;
  base_sharpe_ratio: number;
  base_max_drawdown: number;
  base_total_trades: number;
  num_simulations: number;
  passed: boolean;
  failure_rate: number;
  avg_max_drawdown: number;
  worst_drawdown: number;
  best_drawdown: number;
  avg_return: number;
  median_return: number;
  return_5th_percentile: number;
  return_95th_percentile: number;
  return_std: number;
}

interface DataFile {
  filename: string;
  size_kb: number;
  rows: number | null;
  date_range: string | null;
}

const formatCurrency = (value: number) => {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0
  }).format(value);
};

const formatPercent = (value: number) => {
  return `${(value * 100).toFixed(2)}%`;
};

export function BacktestPage() {
  // State
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [dataFiles, setDataFiles] = useState<DataFile[]>([]);
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>(['iron_condor']);
  const [selectedFile, setSelectedFile] = useState<string>('');
  const [capital, setCapital] = useState(1000000);
  const [positionSize, setPositionSize] = useState(0.02);
  const [maxPositions, setMaxPositions] = useState(3);
  const [assetClass, setAssetClass] = useState<string>('equity');
  const [symbol, setSymbol] = useState<string>('NIFTY');
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');
  const [interval, setInterval] = useState<string>('day');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  
  const [isLoading, setIsLoading] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [isRunningMC, setIsRunningMC] = useState(false);
  
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [mcResult, setMcResult] = useState<MonteCarloResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  const [showTrades, setShowTrades] = useState(false);
  const [activeTab, setActiveTab] = useState<'config' | 'results' | 'monte-carlo'>('config');

  useEffect(() => {
    loadStrategies();
    loadDataFiles();
  }, []);

  const loadStrategies = async () => {
    try {
      const res = await fetch(`${API_BASE}/backtest/strategies`);
      const data = await res.json();
      setStrategies(data.strategies);
    } catch (err) {
      console.error('Failed to load strategies:', err);
    }
  };

  const loadDataFiles = async () => {
    try {
      const res = await fetch(`${API_BASE}/backtest/data/files`);
      const data = await res.json();
      setDataFiles(data);
      if (data.length > 0 && !selectedFile) {
        setSelectedFile(data[0].filename);
      }
    } catch (err) {
      console.error('Failed to load data files:', err);
    }
  };

  const handleDownloadData = async () => {
    setIsDownloading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/backtest/data/download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          symbol: 'ALL',  // Download all instruments
          interval: 'ALL'  // Download all intervals
        })
      });
      const data = await res.json();
      if (res.ok) {
        setError(`Download started: ${data.total_downloads} files queued. This may take several minutes.`);
      } else {
        setError(data.detail || 'Failed to start download');
      }
      // Refresh file list after delay
      setTimeout(loadDataFiles, 5000);
      setTimeout(loadDataFiles, 30000);
    } catch (err) {
      setError('Failed to start data download. Check if Kite API is authenticated.');
    }
    setIsDownloading(false);
  };

  const handleRunBacktest = async () => {
    if (selectedStrategies.length === 0) {
      setError('Please select at least one strategy');
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);
    setMcResult(null);

    try {
      const res = await fetch(`${API_BASE}/backtest/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          data_file: selectedFile || null,  // null means auto-detect
          symbol: symbol,
          asset_class: assetClass,
          strategies: selectedStrategies,
          initial_capital: capital,
          position_size_pct: positionSize,
          max_positions: maxPositions,
          start_date: startDate || null,
          end_date: endDate || null,
          interval: interval
        })
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Backtest failed');
      }

      const data = await res.json();
      setResult(data);
      setActiveTab('results');
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else if (typeof err === 'object' && err !== null && 'detail' in err) {
        setError(String((err as {detail: string}).detail));
      } else {
        setError('Backtest failed. Check console for details.');
      }
    }
    setIsLoading(false);
  };

  const handleRunMonteCarlo = async () => {
    if (selectedStrategies.length === 0) {
      setError('Please select at least one strategy');
      return;
    }

    setIsRunningMC(true);
    setError(null);
    setMcResult(null);

    try {
      const res = await fetch(`${API_BASE}/backtest/monte-carlo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          data_file: selectedFile || undefined,
          symbol: 'NIFTY',
          strategies: selectedStrategies,
          initial_capital: capital,
          num_simulations: 1000
        })
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Monte Carlo failed');
      }

      const data = await res.json();
      setMcResult(data);
      setActiveTab('monte-carlo');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Monte Carlo failed');
    }
    setIsRunningMC(false);
  };

  const toggleStrategy = (strategyId: string) => {
    setSelectedStrategies(prev => 
      prev.includes(strategyId)
        ? prev.filter(s => s !== strategyId)
        : [...prev, strategyId]
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold">Strategy Backtesting</h1>
          <p className="text-[var(--muted-foreground)]">
            Test strategies with full agent integration (Sentinel → Strategist → Treasury)
          </p>
        </div>
        <div className="flex gap-2">
          <Button 
            variant="outline" 
            onClick={handleDownloadData} 
            disabled={isDownloading}
          >
            <Download className="h-4 w-4 mr-2" />
            {isDownloading ? 'Downloading...' : 'Download Data'}
          </Button>
          <Button 
            onClick={handleRunBacktest} 
            disabled={isLoading || selectedStrategies.length === 0}
          >
            <Play className="h-4 w-4 mr-2" />
            {isLoading ? 'Running...' : 'Run Backtest'}
          </Button>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="p-4 rounded-lg bg-[var(--destructive)]/10 text-[var(--destructive)] flex items-center gap-2">
          <AlertTriangle className="h-5 w-5" />
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-[var(--border)]">
        <button
          className={`px-4 py-2 font-medium ${activeTab === 'config' ? 'border-b-2 border-[var(--primary)] text-[var(--primary)]' : 'text-[var(--muted-foreground)]'}`}
          onClick={() => setActiveTab('config')}
        >
          Configuration
        </button>
        <button
          className={`px-4 py-2 font-medium ${activeTab === 'results' ? 'border-b-2 border-[var(--primary)] text-[var(--primary)]' : 'text-[var(--muted-foreground)]'}`}
          onClick={() => setActiveTab('results')}
          disabled={!result}
        >
          Results
        </button>
        <button
          className={`px-4 py-2 font-medium ${activeTab === 'monte-carlo' ? 'border-b-2 border-[var(--primary)] text-[var(--primary)]' : 'text-[var(--muted-foreground)]'}`}
          onClick={() => setActiveTab('monte-carlo')}
          disabled={!mcResult}
        >
          Monte Carlo
        </button>
      </div>

      {/* Configuration Tab */}
      {activeTab === 'config' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Strategy Selection */}
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Target className="h-5 w-5" />
                Strategy Selection
              </CardTitle>
              <div className="flex gap-2 mt-2">
                {['all', 'short_vol', 'directional', 'hedge'].map(cat => (
                  <button
                    key={cat}
                    className={`px-3 py-1 text-xs rounded-full ${categoryFilter === cat ? 'bg-[var(--primary)] text-white' : 'bg-[var(--muted)] text-[var(--muted-foreground)]'}`}
                    onClick={() => setCategoryFilter(cat)}
                  >
                    {cat === 'all' ? 'All' : cat === 'short_vol' ? 'Short Vol' : cat === 'directional' ? 'Directional' : 'Hedging'}
                  </button>
                ))}
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {strategies
                  .filter(s => categoryFilter === 'all' || s.category === categoryFilter)
                  .map(strategy => (
                  <div
                    key={strategy.id}
                    className={`p-4 rounded-lg border cursor-pointer transition-colors ${
                      selectedStrategies.includes(strategy.id)
                        ? 'border-[var(--primary)] bg-[var(--primary)]/10'
                        : 'border-[var(--border)] hover:border-[var(--primary)]/50'
                    }`}
                    onClick={() => toggleStrategy(strategy.id)}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <h3 className="font-semibold">{strategy.name}</h3>
                      {selectedStrategies.includes(strategy.id) && (
                        <CheckCircle className="h-5 w-5 text-[var(--primary)]" />
                      )}
                    </div>
                    <p className="text-sm text-[var(--muted-foreground)] mb-2">
                      {strategy.description}
                    </p>
                    <div className="flex gap-2 flex-wrap">
                      <Badge variant="secondary">{strategy.regime}</Badge>
                      {strategy.category && (
                        <Badge variant="outline" className="text-xs">
                          {strategy.category === 'short_vol' ? 'Short Vol' : strategy.category === 'hedge' ? 'Hedge' : 'Directional'}
                        </Badge>
                      )}
                      {strategy.asset_class && strategy.asset_class !== 'equity' && (
                        <Badge variant="outline" className="text-xs">
                          {strategy.asset_class}
                        </Badge>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Parameters */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-5 w-5" />
                Parameters
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Asset Class & Symbol */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-sm font-medium mb-2">Asset Class</label>
                  <select
                    value={assetClass}
                    onChange={(e) => setAssetClass(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
                  >
                    <option value="equity">Equity</option>
                    <option value="commodity">Commodity</option>
                    <option value="multi_asset">Multi-Asset</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-2">Symbol</label>
                  <select
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
                  >
                    {assetClass === 'equity' && (
                      <>
                        <option value="NIFTY">NIFTY</option>
                        <option value="BANKNIFTY">BANKNIFTY</option>
                      </>
                    )}
                    {assetClass === 'commodity' && (
                      <>
                        <option value="GOLD">Gold</option>
                        <option value="CRUDE">Crude Oil</option>
                        <option value="SILVER">Silver</option>
                      </>
                    )}
                    {assetClass === 'multi_asset' && (
                      <>
                        <option value="NIFTY">NIFTY (Primary)</option>
                        <option value="GOLD">Gold (Primary)</option>
                      </>
                    )}
                  </select>
                </div>
              </div>

              {/* Date Range */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-sm font-medium mb-2">Start Date</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-2">End Date</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
                  />
                </div>
              </div>

              {/* Time Interval */}
              <div>
                <label className="block text-sm font-medium mb-2">Time Interval</label>
                <select
                  value={interval}
                  onChange={(e) => setInterval(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
                >
                  <option value="day">Daily</option>
                  <option value="60minute">1 Hour</option>
                  <option value="15minute">15 Minutes</option>
                  <option value="5minute">5 Minutes</option>
                  <option value="minute">1 Minute</option>
                </select>
                <p className="text-xs text-[var(--muted-foreground)] mt-1">
                  Data will be auto-downloaded if not cached
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">Data File</label>
                <select
                  value={selectedFile}
                  onChange={(e) => setSelectedFile(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
                >
                  <option value="">Auto-detect</option>
                  {dataFiles.map(file => (
                    <option key={file.filename} value={file.filename}>
                      {file.filename} ({file.size_kb.toFixed(1)} KB)
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">Initial Capital (₹)</label>
                <input
                  type="number"
                  value={capital}
                  onChange={(e) => setCapital(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
                  min={100000}
                  step={100000}
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">
                  Position Size: {(positionSize * 100).toFixed(1)}%
                </label>
                <input
                  type="range"
                  value={positionSize}
                  onChange={(e) => setPositionSize(Number(e.target.value))}
                  className="w-full"
                  min={0.01}
                  max={0.10}
                  step={0.005}
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">Max Positions</label>
                <select
                  value={maxPositions}
                  onChange={(e) => setMaxPositions(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
                >
                  {[1, 2, 3, 4, 5].map(n => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </div>

              <div className="pt-4 border-t border-[var(--border)]">
                <Button 
                  variant="outline" 
                  className="w-full"
                  onClick={handleRunMonteCarlo}
                  disabled={isRunningMC || selectedStrategies.length === 0}
                >
                  <RefreshCw className={`h-4 w-4 mr-2 ${isRunningMC ? 'animate-spin' : ''}`} />
                  {isRunningMC ? 'Running...' : 'Monte Carlo Stress Test'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Results Tab */}
      {activeTab === 'results' && result && (
        <div className="space-y-6">
          {/* Summary Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            <MetricCard
              title="Total Return"
              value={formatPercent(result.total_return_pct)}
              subtitle={formatCurrency(result.total_return)}
              positive={result.total_return_pct >= 0}
            />
            <MetricCard
              title="Sharpe Ratio"
              value={result.sharpe_ratio.toFixed(2)}
              subtitle={result.sharpe_ratio >= 1 ? 'Good' : 'Below target'}
              positive={result.sharpe_ratio >= 1}
            />
            <MetricCard
              title="Max Drawdown"
              value={formatPercent(result.max_drawdown)}
              subtitle={`${result.max_drawdown_duration} days`}
              positive={result.max_drawdown <= 0.15}
              invert
            />
            <MetricCard
              title="Win Rate"
              value={formatPercent(result.win_rate)}
              subtitle={`${result.winning_trades}W / ${result.losing_trades}L`}
              positive={result.win_rate >= 0.55}
            />
            <MetricCard
              title="Profit Factor"
              value={result.profit_factor.toFixed(2)}
              subtitle={result.profit_factor >= 1.5 ? 'Good' : 'Below target'}
              positive={result.profit_factor >= 1.5}
            />
            <MetricCard
              title="Total Trades"
              value={result.total_trades.toString()}
              subtitle={`Avg ${result.avg_holding_days.toFixed(1)} days`}
            />
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Equity Curve */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5" />
                  Equity Curve
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <EquityChart data={result.equity_curve} initial={capital} />
                </div>
              </CardContent>
            </Card>

            {/* Drawdown Chart */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingDown className="h-5 w-5" />
                  Drawdown
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <DrawdownChart data={result.drawdown_curve} />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Breakdown Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* By Strategy */}
            <Card>
              <CardHeader>
                <CardTitle>Performance by Strategy</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {Object.entries(result.by_strategy).map(([strategy, metrics]) => (
                    <div key={strategy} className="flex justify-between items-center p-3 rounded-lg bg-[var(--muted)]">
                      <div>
                        <p className="font-medium">{strategy.replace('_', ' ').toUpperCase()}</p>
                        <p className="text-sm text-[var(--muted-foreground)]">
                          {metrics.total_trades} trades
                        </p>
                      </div>
                      <div className="text-right">
                        <p className={`font-bold ${metrics.total_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatCurrency(metrics.total_pnl)}
                        </p>
                        <p className="text-sm text-[var(--muted-foreground)]">
                          {formatPercent(metrics.win_rate)} win rate
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* By Regime */}
            <Card>
              <CardHeader>
                <CardTitle>Performance by Regime</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {Object.entries(result.by_regime).map(([regime, metrics]) => (
                    <div key={regime} className="flex justify-between items-center p-3 rounded-lg bg-[var(--muted)]">
                      <div>
                        <p className="font-medium">{regime}</p>
                        <p className="text-sm text-[var(--muted-foreground)]">
                          {metrics.total_trades} trades
                        </p>
                      </div>
                      <div className="text-right">
                        <p className={`font-bold ${metrics.total_pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                          {formatCurrency(metrics.total_pnl)}
                        </p>
                        <p className="text-sm text-[var(--muted-foreground)]">
                          {formatPercent(metrics.win_rate)} win rate
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Trade List */}
          <Card>
            <CardHeader>
              <CardTitle 
                className="flex items-center justify-between cursor-pointer"
                onClick={() => setShowTrades(!showTrades)}
              >
                <span className="flex items-center gap-2">
                  <BarChart3 className="h-5 w-5" />
                  Trade History ({result.trades.length} trades)
                </span>
                {showTrades ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
              </CardTitle>
            </CardHeader>
            {showTrades && (
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[var(--border)]">
                        <th className="text-left py-2 px-3">Strategy</th>
                        <th className="text-left py-2 px-3">Entry</th>
                        <th className="text-left py-2 px-3">Exit</th>
                        <th className="text-right py-2 px-3">P&L</th>
                        <th className="text-right py-2 px-3">P&L %</th>
                        <th className="text-left py-2 px-3">Exit Reason</th>
                        <th className="text-left py-2 px-3">Regime</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.slice(0, 50).map(trade => (
                        <tr key={trade.id} className="border-b border-[var(--border)]/50 hover:bg-[var(--muted)]/50">
                          <td className="py-2 px-3 font-medium">{trade.strategy_type}</td>
                          <td className="py-2 px-3">{new Date(trade.entry_date).toLocaleDateString()}</td>
                          <td className="py-2 px-3">{new Date(trade.exit_date).toLocaleDateString()}</td>
                          <td className={`py-2 px-3 text-right font-medium ${trade.pnl >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                            {formatCurrency(trade.pnl)}
                          </td>
                          <td className={`py-2 px-3 text-right ${trade.pnl_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                            {formatPercent(trade.pnl_pct)}
                          </td>
                          <td className="py-2 px-3">
                            <Badge variant={trade.exit_reason === 'PROFIT_TARGET' ? 'success' : 'secondary'}>
                              {trade.exit_reason}
                            </Badge>
                          </td>
                          <td className="py-2 px-3 text-[var(--muted-foreground)]">{trade.regime_at_entry}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            )}
          </Card>
        </div>
      )}

      {/* Monte Carlo Tab */}
      {activeTab === 'monte-carlo' && mcResult && (
        <div className="space-y-6">
          {/* Pass/Fail Banner */}
          <div className={`p-6 rounded-lg ${mcResult.passed ? 'bg-[var(--profit)]/10' : 'bg-[var(--loss)]/10'}`}>
            <div className="flex items-center gap-4">
              {mcResult.passed ? (
                <CheckCircle className="h-12 w-12 text-[var(--profit)]" />
              ) : (
                <AlertTriangle className="h-12 w-12 text-[var(--loss)]" />
              )}
              <div>
                <h2 className={`text-2xl font-bold ${mcResult.passed ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                  {mcResult.passed ? 'STRESS TEST PASSED' : 'STRESS TEST FAILED'}
                </h2>
                <p className="text-[var(--muted-foreground)]">
                  {mcResult.num_simulations} simulations • {formatPercent(mcResult.failure_rate)} failure rate
                </p>
              </div>
            </div>
          </div>

          {/* Monte Carlo Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard
              title="Avg Max Drawdown"
              value={formatPercent(mcResult.avg_max_drawdown)}
              subtitle="Across all simulations"
              positive={mcResult.avg_max_drawdown <= 0.15}
              invert
            />
            <MetricCard
              title="Worst Drawdown"
              value={formatPercent(mcResult.worst_drawdown)}
              subtitle="Worst case scenario"
              positive={mcResult.worst_drawdown <= 0.20}
              invert
            />
            <MetricCard
              title="Median Return"
              value={formatPercent(mcResult.median_return)}
              subtitle="50th percentile"
              positive={mcResult.median_return >= 0}
            />
            <MetricCard
              title="Return Std Dev"
              value={formatPercent(mcResult.return_std)}
              subtitle="Volatility of returns"
            />
          </div>

          {/* Return Distribution */}
          <Card>
            <CardHeader>
              <CardTitle>Return Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <span className="text-[var(--muted-foreground)]">5th Percentile (Worst 5%)</span>
                  <span className={mcResult.return_5th_percentile >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}>
                    {formatPercent(mcResult.return_5th_percentile)}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-[var(--muted-foreground)]">Average Return</span>
                  <span className={mcResult.avg_return >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}>
                    {formatPercent(mcResult.avg_return)}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-[var(--muted-foreground)]">Median Return</span>
                  <span className={mcResult.median_return >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}>
                    {formatPercent(mcResult.median_return)}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-[var(--muted-foreground)]">95th Percentile (Best 5%)</span>
                  <span className={mcResult.return_95th_percentile >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}>
                    {formatPercent(mcResult.return_95th_percentile)}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Base Backtest Summary */}
          <Card>
            <CardHeader>
              <CardTitle>Base Backtest Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-4 rounded-lg bg-[var(--muted)]">
                  <p className="text-sm text-[var(--muted-foreground)]">Total Return</p>
                  <p className={`text-xl font-bold ${mcResult.base_total_return_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                    {formatPercent(mcResult.base_total_return_pct)}
                  </p>
                </div>
                <div className="p-4 rounded-lg bg-[var(--muted)]">
                  <p className="text-sm text-[var(--muted-foreground)]">Sharpe Ratio</p>
                  <p className="text-xl font-bold">{mcResult.base_sharpe_ratio.toFixed(2)}</p>
                </div>
                <div className="p-4 rounded-lg bg-[var(--muted)]">
                  <p className="text-sm text-[var(--muted-foreground)]">Max Drawdown</p>
                  <p className="text-xl font-bold text-[var(--loss)]">{formatPercent(mcResult.base_max_drawdown)}</p>
                </div>
                <div className="p-4 rounded-lg bg-[var(--muted)]">
                  <p className="text-sm text-[var(--muted-foreground)]">Total Trades</p>
                  <p className="text-xl font-bold">{mcResult.base_total_trades}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

// Helper Components

function MetricCard({ 
  title, 
  value, 
  subtitle, 
  positive, 
  invert = false 
}: { 
  title: string; 
  value: string; 
  subtitle?: string; 
  positive?: boolean;
  invert?: boolean;
}) {
  const colorClass = positive === undefined 
    ? '' 
    : (invert ? !positive : positive) 
      ? 'text-[var(--profit)]' 
      : 'text-[var(--loss)]';

  return (
    <div className="p-4 rounded-lg bg-[var(--card)] border border-[var(--border)]">
      <p className="text-sm text-[var(--muted-foreground)]">{title}</p>
      <p className={`text-2xl font-bold ${colorClass}`}>{value}</p>
      {subtitle && <p className="text-xs text-[var(--muted-foreground)]">{subtitle}</p>}
    </div>
  );
}

function EquityChart({ data, initial }: { data: number[]; initial: number }) {
  if (!data || data.length === 0) {
    return <div className="flex items-center justify-center h-full text-[var(--muted-foreground)]">No data</div>;
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((value, i) => {
    const x = (i / (data.length - 1)) * 100;
    const y = 100 - ((value - min) / range) * 100;
    return `${x},${y}`;
  }).join(' ');

  const finalReturn = ((data[data.length - 1] - initial) / initial) * 100;

  return (
    <div className="relative h-full">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
        <polyline
          points={points}
          fill="none"
          stroke={finalReturn >= 0 ? 'var(--profit)' : 'var(--loss)'}
          strokeWidth="0.5"
        />
      </svg>
      <div className="absolute bottom-0 left-0 text-xs text-[var(--muted-foreground)]">
        {new Intl.NumberFormat('en-IN').format(min)}
      </div>
      <div className="absolute top-0 left-0 text-xs text-[var(--muted-foreground)]">
        {new Intl.NumberFormat('en-IN').format(max)}
      </div>
    </div>
  );
}

function DrawdownChart({ data }: { data: number[] }) {
  if (!data || data.length === 0) {
    return <div className="flex items-center justify-center h-full text-[var(--muted-foreground)]">No data</div>;
  }

  const max = Math.max(...data);
  const range = max || 0.01;

  const points = data.map((value, i) => {
    const x = (i / (data.length - 1)) * 100;
    const y = (value / range) * 100;
    return `${x},${y}`;
  }).join(' ');

  return (
    <div className="relative h-full">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
        <polyline
          points={points}
          fill="none"
          stroke="var(--loss)"
          strokeWidth="0.5"
        />
      </svg>
      <div className="absolute bottom-0 left-0 text-xs text-[var(--muted-foreground)]">0%</div>
      <div className="absolute top-0 left-0 text-xs text-[var(--muted-foreground)]">
        {(max * 100).toFixed(1)}%
      </div>
    </div>
  );
}

export default BacktestPage;
