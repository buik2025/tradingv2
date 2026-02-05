import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { backtestApi } from '@/services/api';
import type { BacktestResult } from '@/types';
import { Play, Download } from 'lucide-react';
import { formatPercent } from '@/lib/utils';

export function Backtest() {
  const [dataFiles, setDataFiles] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState('');
  const [strategy, setStrategy] = useState('iron_condor');
  const [capital, setCapital] = useState(1000000);
  const [isLoading, setIsLoading] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDataFiles();
  }, []);

  const loadDataFiles = async () => {
    try {
      const response = await backtestApi.getDataFiles();
      setDataFiles(response.data.files);
      if (response.data.files.length > 0) {
        setSelectedFile(response.data.files[0]);
      }
    } catch {
      console.error('Failed to load data files');
    }
  };

  const handleDownload = async () => {
    setIsDownloading(true);
    try {
      await backtestApi.downloadData('NIFTY', 90, 'day');
      await loadDataFiles();
    } catch {
      setError('Failed to download data');
    }
    setIsDownloading(false);
  };

  const handleRunBacktest = async () => {
    if (!selectedFile) {
      setError('Please select a data file');
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await backtestApi.run({
        data_file: selectedFile,
        strategy,
        initial_capital: capital,
        position_size_pct: 0.02,
      });
      setResult(response.data);
    } catch {
      setError('Backtest failed');
    }
    setIsLoading(false);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Backtesting</h1>
        <p className="text-[var(--muted-foreground)]">Test strategies on historical data</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Data File</label>
              <div className="flex gap-2">
                <select
                  value={selectedFile}
                  onChange={(e) => setSelectedFile(e.target.value)}
                  className="flex-1 px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
                >
                  {dataFiles.length === 0 ? (
                    <option value="">No data files available</option>
                  ) : (
                    dataFiles.map((file) => (
                      <option key={file} value={file}>{file}</option>
                    ))
                  )}
                </select>
                <Button variant="outline" onClick={handleDownload} disabled={isDownloading}>
                  <Download className="h-4 w-4" />
                </Button>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Strategy</label>
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
                className="w-full px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
              >
                <option value="iron_condor">Iron Condor</option>
                <option value="jade_lizard">Jade Lizard</option>
                <option value="risk_reversal">Risk Reversal</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Initial Capital (₹)</label>
              <input
                type="number"
                value={capital}
                onChange={(e) => setCapital(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-md bg-[var(--input)] border border-[var(--border)] text-sm"
              />
            </div>

            {error && (
              <div className="p-3 rounded-lg bg-[var(--destructive)]/10 text-[var(--destructive)] text-sm">
                {error}
              </div>
            )}

            <Button className="w-full" onClick={handleRunBacktest} disabled={isLoading}>
              <Play className="h-4 w-4 mr-2" />
              {isLoading ? 'Running...' : 'Run Backtest'}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Results</CardTitle>
          </CardHeader>
          <CardContent>
            {!result ? (
              <div className="text-center py-8 text-[var(--muted-foreground)]">
                Run a backtest to see results
              </div>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="p-4 rounded-lg bg-[var(--muted)]">
                    <p className="text-sm text-[var(--muted-foreground)]">Total Return</p>
                    <p className={`text-2xl font-bold ${result.total_return_pct >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}`}>
                      {formatPercent(result.total_return_pct)}
                    </p>
                  </div>
                  <div className="p-4 rounded-lg bg-[var(--muted)]">
                    <p className="text-sm text-[var(--muted-foreground)]">Sharpe Ratio</p>
                    <p className="text-2xl font-bold">{result.sharpe_ratio.toFixed(2)}</p>
                  </div>
                  <div className="p-4 rounded-lg bg-[var(--muted)]">
                    <p className="text-sm text-[var(--muted-foreground)]">Max Drawdown</p>
                    <p className="text-2xl font-bold text-[var(--loss)]">
                      {formatPercent(result.max_drawdown)}
                    </p>
                  </div>
                  <div className="p-4 rounded-lg bg-[var(--muted)]">
                    <p className="text-sm text-[var(--muted-foreground)]">Win Rate</p>
                    <p className="text-2xl font-bold">{(result.win_rate * 100).toFixed(0)}%</p>
                  </div>
                </div>

                <div className="flex justify-between items-center pt-4 border-t border-[var(--border)]">
                  <span className="text-sm text-[var(--muted-foreground)]">Total Trades</span>
                  <Badge variant="secondary">{result.total_trades}</Badge>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-[var(--muted-foreground)]">Profit Factor</span>
                  <Badge variant={result.profit_factor > 1 ? 'success' : 'destructive'}>
                    {result.profit_factor.toFixed(2)}
                  </Badge>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
