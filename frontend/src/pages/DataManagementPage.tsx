import { useState, useEffect } from 'react';
import { 
  Database, 
  Download, 
  Play, 
  Square, 
  RefreshCw, 
  HardDrive,
  Clock,
  TrendingUp,
  AlertCircle,
  CheckCircle,
  Loader2,
  FileText,
  Calendar,
  BarChart3
} from 'lucide-react';

interface DataFile {
  filename: string;
  size_kb: number;
  rows: number | null;
  date_range: string | null;
}

interface OptionsFile {
  filename: string;
  symbol: string;
  date: string;
  size_mb: number;
  records: number;
}

interface CollectorStatus {
  running: boolean;
  symbols: string[];
  interval_seconds: number;
  collections_today: number;
  records_today: number;
  errors_today: number;
  last_collection: string | null;
  start_time: string | null;
}

interface DownloadStatus {
  in_progress: boolean;
  current_symbol: string | null;
  current_interval: string | null;
  completed: number;
  total: number;
  errors: string[];
}

const INSTRUMENTS = [
  { id: 'NIFTY', name: 'NIFTY 50', type: 'Index' },
  { id: 'BANKNIFTY', name: 'Bank NIFTY', type: 'Index' },
  { id: 'INDIAVIX', name: 'India VIX', type: 'Volatility' },
  { id: 'GOLD', name: 'Gold', type: 'Commodity' },
  { id: 'SILVER', name: 'Silver', type: 'Commodity' },
  { id: 'CRUDE', name: 'Crude Oil', type: 'Commodity' },
];

const INTERVALS = [
  { id: 'day', name: 'Daily', maxDays: 2000 },
  { id: '60minute', name: '60 Minute', maxDays: 400 },
  { id: '15minute', name: '15 Minute', maxDays: 200 },
  { id: '5minute', name: '5 Minute', maxDays: 100 },
  { id: 'minute', name: '1 Minute', maxDays: 60 },
];

export function DataManagementPage() {
  // Historical data state
  const [dataFiles, setDataFiles] = useState<DataFile[]>([]);
  const [_downloadStatus, setDownloadStatus] = useState<DownloadStatus>({
    in_progress: false,
    current_symbol: null,
    current_interval: null,
    completed: 0,
    total: 0,
    errors: []
  });
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>(['NIFTY', 'BANKNIFTY']);
  const [selectedIntervals, setSelectedIntervals] = useState<string[]>(['day', '60minute']);
  
  // Options collector state
  const [collectorStatus, setCollectorStatus] = useState<CollectorStatus>({
    running: false,
    symbols: ['NIFTY', 'BANKNIFTY'],
    interval_seconds: 60,
    collections_today: 0,
    records_today: 0,
    errors_today: 0,
    last_collection: null,
    start_time: null
  });
  const [optionsFiles, setOptionsFiles] = useState<OptionsFile[]>([]);
  const [collectorSymbols, setCollectorSymbols] = useState<string[]>(['NIFTY', 'BANKNIFTY']);
  const [collectorInterval, setCollectorInterval] = useState(60);
  
  // UI state
  const [activeTab, setActiveTab] = useState<'historical' | 'options'>('historical');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);

  // Fetch data files on mount
  useEffect(() => {
    fetchDataFiles();
    fetchOptionsFiles();
    fetchCollectorStatus();
    
    // Poll collector status every 10 seconds
    const interval = setInterval(() => {
      fetchCollectorStatus();
    }, 10000);
    
    return () => clearInterval(interval);
  }, []);

  const fetchDataFiles = async () => {
    try {
      const response = await fetch('/api/v1/backtest/data/files');
      if (response.ok) {
        const files = await response.json();
        setDataFiles(files);
      }
    } catch (error) {
      console.error('Failed to fetch data files:', error);
    }
  };

  const fetchOptionsFiles = async () => {
    try {
      const response = await fetch('/api/v1/data/options/files');
      if (response.ok) {
        const data = await response.json();
        setOptionsFiles(data.files || []);
      }
    } catch (error) {
      console.error('Failed to fetch options files:', error);
    }
  };

  const fetchCollectorStatus = async () => {
    try {
      const response = await fetch('/api/v1/data/options/collector/status');
      if (response.ok) {
        const status = await response.json();
        setCollectorStatus(status);
      }
    } catch (error) {
      // Collector might not be running - that's OK
    }
  };

  const handleDownloadHistorical = async () => {
    if (selectedSymbols.length === 0 || selectedIntervals.length === 0) {
      setMessage({ type: 'error', text: 'Please select at least one symbol and interval' });
      return;
    }

    setLoading(true);
    setMessage(null);
    setDownloadStatus({
      in_progress: true,
      current_symbol: null,
      current_interval: null,
      completed: 0,
      total: selectedSymbols.length * selectedIntervals.length,
      errors: []
    });

    try {
      const response = await fetch('/api/v1/backtest/data/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: selectedSymbols.length === 1 ? selectedSymbols[0] : 'ALL',
          interval: selectedIntervals.length === 1 ? selectedIntervals[0] : 'ALL'
        })
      });

      if (response.ok) {
        const result = await response.json();
        setMessage({ 
          type: 'success', 
          text: `Download started: ${result.total_downloads} tasks queued` 
        });
        
        // Refresh file list after a delay
        setTimeout(fetchDataFiles, 5000);
      } else {
        const error = await response.json();
        setMessage({ type: 'error', text: error.detail || 'Download failed' });
      }
    } catch (error) {
      setMessage({ type: 'error', text: 'Failed to start download' });
    } finally {
      setLoading(false);
      setDownloadStatus(prev => ({ ...prev, in_progress: false }));
    }
  };

  const handleStartCollector = async () => {
    setLoading(true);
    setMessage(null);

    try {
      const response = await fetch('/api/v1/data/options/collector/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbols: collectorSymbols,
          interval_seconds: collectorInterval
        })
      });

      if (response.ok) {
        setMessage({ type: 'success', text: 'Options collector started' });
        fetchCollectorStatus();
      } else {
        const error = await response.json();
        setMessage({ type: 'error', text: error.detail || 'Failed to start collector' });
      }
    } catch (error) {
      setMessage({ type: 'error', text: 'Failed to start collector' });
    } finally {
      setLoading(false);
    }
  };

  const handleStopCollector = async () => {
    setLoading(true);
    setMessage(null);

    try {
      const response = await fetch('/api/v1/data/options/collector/stop', {
        method: 'POST'
      });

      if (response.ok) {
        setMessage({ type: 'success', text: 'Options collector stopped' });
        fetchCollectorStatus();
      } else {
        const error = await response.json();
        setMessage({ type: 'error', text: error.detail || 'Failed to stop collector' });
      }
    } catch (error) {
      setMessage({ type: 'error', text: 'Failed to stop collector' });
    } finally {
      setLoading(false);
    }
  };

  const toggleSymbol = (symbol: string) => {
    setSelectedSymbols(prev => 
      prev.includes(symbol) 
        ? prev.filter(s => s !== symbol)
        : [...prev, symbol]
    );
  };

  const toggleInterval = (interval: string) => {
    setSelectedIntervals(prev => 
      prev.includes(interval) 
        ? prev.filter(i => i !== interval)
        : [...prev, interval]
    );
  };

  const toggleCollectorSymbol = (symbol: string) => {
    setCollectorSymbols(prev => 
      prev.includes(symbol) 
        ? prev.filter(s => s !== symbol)
        : [...prev, symbol]
    );
  };

  const formatBytes = (kb: number) => {
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    return `${(kb / 1024).toFixed(2)} MB`;
  };

  const formatNumber = (num: number) => {
    return num.toLocaleString();
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Database className="w-7 h-7 text-blue-600" />
            Data Management
          </h1>
          <p className="text-gray-500 mt-1">
            Download historical data and collect real-time options data for backtesting
          </p>
        </div>
        <button
          onClick={() => { fetchDataFiles(); fetchOptionsFiles(); fetchCollectorStatus(); }}
          className="flex items-center gap-2 px-4 py-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {/* Message */}
      {message && (
        <div className={`p-4 rounded-lg flex items-center gap-2 ${
          message.type === 'success' ? 'bg-green-50 text-green-800 border border-green-200' :
          message.type === 'error' ? 'bg-red-50 text-red-800 border border-red-200' :
          'bg-blue-50 text-blue-800 border border-blue-200'
        }`}>
          {message.type === 'success' && <CheckCircle className="w-5 h-5" />}
          {message.type === 'error' && <AlertCircle className="w-5 h-5" />}
          {message.text}
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-4">
          <button
            onClick={() => setActiveTab('historical')}
            className={`pb-3 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'historical'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <div className="flex items-center gap-2">
              <BarChart3 className="w-4 h-4" />
              Historical Data
            </div>
          </button>
          <button
            onClick={() => setActiveTab('options')}
            className={`pb-3 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'options'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <div className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4" />
              Options Data Collector
              {collectorStatus.running && (
                <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              )}
            </div>
          </button>
        </nav>
      </div>

      {/* Historical Data Tab */}
      {activeTab === 'historical' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Download Controls */}
          <div className="lg:col-span-1 space-y-6">
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <Download className="w-5 h-5 text-blue-600" />
                Download Historical Data
              </h2>
              
              {/* Symbol Selection */}
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Instruments
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {INSTRUMENTS.map(inst => (
                    <button
                      key={inst.id}
                      onClick={() => toggleSymbol(inst.id)}
                      className={`px-3 py-2 text-sm rounded-lg border transition-colors ${
                        selectedSymbols.includes(inst.id)
                          ? 'bg-blue-50 border-blue-300 text-blue-700'
                          : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'
                      }`}
                    >
                      {inst.name}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => setSelectedSymbols(
                    selectedSymbols.length === INSTRUMENTS.length 
                      ? [] 
                      : INSTRUMENTS.map(i => i.id)
                  )}
                  className="mt-2 text-xs text-blue-600 hover:text-blue-800"
                >
                  {selectedSymbols.length === INSTRUMENTS.length ? 'Deselect All' : 'Select All'}
                </button>
              </div>

              {/* Interval Selection */}
              <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Intervals
                </label>
                <div className="space-y-2">
                  {INTERVALS.map(int => (
                    <button
                      key={int.id}
                      onClick={() => toggleInterval(int.id)}
                      className={`w-full px-3 py-2 text-sm rounded-lg border transition-colors flex justify-between items-center ${
                        selectedIntervals.includes(int.id)
                          ? 'bg-blue-50 border-blue-300 text-blue-700'
                          : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'
                      }`}
                    >
                      <span>{int.name}</span>
                      <span className="text-xs text-gray-400">~{int.maxDays} days</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Download Button */}
              <button
                onClick={handleDownloadHistorical}
                disabled={loading || selectedSymbols.length === 0 || selectedIntervals.length === 0}
                className="w-full py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Downloading...
                  </>
                ) : (
                  <>
                    <Download className="w-5 h-5" />
                    Download Data
                  </>
                )}
              </button>

              <p className="mt-3 text-xs text-gray-500">
                Downloads maximum available data per Kite API limits. Data is saved to both CSV and Parquet formats.
              </p>
            </div>
          </div>

          {/* Data Files List */}
          <div className="lg:col-span-2">
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <HardDrive className="w-5 h-5 text-gray-600" />
                Available Data Files
                <span className="text-sm font-normal text-gray-500">
                  ({dataFiles.length} files)
                </span>
              </h2>

              {dataFiles.length === 0 ? (
                <div className="text-center py-12 text-gray-500">
                  <FileText className="w-12 h-12 mx-auto mb-3 text-gray-300" />
                  <p>No data files found</p>
                  <p className="text-sm">Download historical data to get started</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="text-left text-sm text-gray-500 border-b">
                        <th className="pb-3 font-medium">Filename</th>
                        <th className="pb-3 font-medium">Size</th>
                        <th className="pb-3 font-medium">Rows</th>
                        <th className="pb-3 font-medium">Date Range</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {dataFiles.map((file, idx) => (
                        <tr key={idx} className="text-sm">
                          <td className="py-3 font-mono text-gray-900">{file.filename}</td>
                          <td className="py-3 text-gray-600">{formatBytes(file.size_kb)}</td>
                          <td className="py-3 text-gray-600">
                            {file.rows ? formatNumber(file.rows) : '-'}
                          </td>
                          <td className="py-3 text-gray-600">{file.date_range || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Options Data Tab */}
      {activeTab === 'options' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Collector Controls */}
          <div className="lg:col-span-1 space-y-6">
            {/* Status Card */}
            <div className={`rounded-xl border p-6 ${
              collectorStatus.running 
                ? 'bg-green-50 border-green-200' 
                : 'bg-gray-50 border-gray-200'
            }`}>
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-gray-900">Collector Status</h2>
                <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                  collectorStatus.running
                    ? 'bg-green-100 text-green-800'
                    : 'bg-gray-200 text-gray-600'
                }`}>
                  {collectorStatus.running ? 'Running' : 'Stopped'}
                </span>
              </div>

              {collectorStatus.running && (
                <div className="space-y-3 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Symbols</span>
                    <span className="font-medium">{collectorStatus.symbols.join(', ')}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Interval</span>
                    <span className="font-medium">{collectorStatus.interval_seconds}s</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Collections Today</span>
                    <span className="font-medium">{formatNumber(collectorStatus.collections_today)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Records Today</span>
                    <span className="font-medium">{formatNumber(collectorStatus.records_today)}</span>
                  </div>
                  {collectorStatus.errors_today > 0 && (
                    <div className="flex justify-between text-red-600">
                      <span>Errors</span>
                      <span className="font-medium">{collectorStatus.errors_today}</span>
                    </div>
                  )}
                  {collectorStatus.last_collection && (
                    <div className="flex justify-between">
                      <span className="text-gray-600">Last Collection</span>
                      <span className="font-medium">
                        {new Date(collectorStatus.last_collection).toLocaleTimeString()}
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Collector Configuration */}
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <Clock className="w-5 h-5 text-purple-600" />
                Collector Settings
              </h2>

              {/* Symbol Selection */}
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Symbols to Collect
                </label>
                <div className="flex gap-2">
                  {['NIFTY', 'BANKNIFTY'].map(symbol => (
                    <button
                      key={symbol}
                      onClick={() => toggleCollectorSymbol(symbol)}
                      disabled={collectorStatus.running}
                      className={`flex-1 px-3 py-2 text-sm rounded-lg border transition-colors ${
                        collectorSymbols.includes(symbol)
                          ? 'bg-purple-50 border-purple-300 text-purple-700'
                          : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'
                      } ${collectorStatus.running ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {symbol}
                    </button>
                  ))}
                </div>
              </div>

              {/* Interval Selection */}
              <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Collection Interval
                </label>
                <select
                  value={collectorInterval}
                  onChange={(e) => setCollectorInterval(Number(e.target.value))}
                  disabled={collectorStatus.running}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm disabled:opacity-50"
                >
                  <option value={30}>30 seconds</option>
                  <option value={60}>1 minute</option>
                  <option value={120}>2 minutes</option>
                  <option value={300}>5 minutes</option>
                </select>
              </div>

              {/* Start/Stop Buttons */}
              {collectorStatus.running ? (
                <button
                  onClick={handleStopCollector}
                  disabled={loading}
                  className="w-full py-3 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 disabled:bg-gray-300 transition-colors flex items-center justify-center gap-2"
                >
                  {loading ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <Square className="w-5 h-5" />
                  )}
                  Stop Collector
                </button>
              ) : (
                <button
                  onClick={handleStartCollector}
                  disabled={loading || collectorSymbols.length === 0}
                  className="w-full py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
                >
                  {loading ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <Play className="w-5 h-5" />
                  )}
                  Start Collector
                </button>
              )}

              <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <p className="text-xs text-amber-800">
                  <strong>Note:</strong> The collector runs during market hours (9:15 AM - 3:30 PM IST). 
                  It collects options chain data for all strikes ±20 from ATM for multiple expiries.
                </p>
              </div>
            </div>
          </div>

          {/* Options Files List */}
          <div className="lg:col-span-2">
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <Calendar className="w-5 h-5 text-purple-600" />
                Collected Options Data
                <span className="text-sm font-normal text-gray-500">
                  ({optionsFiles.length} files)
                </span>
              </h2>

              {optionsFiles.length === 0 ? (
                <div className="text-center py-12 text-gray-500">
                  <TrendingUp className="w-12 h-12 mx-auto mb-3 text-gray-300" />
                  <p>No options data collected yet</p>
                  <p className="text-sm">Start the collector during market hours to begin collecting data</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="text-left text-sm text-gray-500 border-b">
                        <th className="pb-3 font-medium">Date</th>
                        <th className="pb-3 font-medium">Symbol</th>
                        <th className="pb-3 font-medium">Records</th>
                        <th className="pb-3 font-medium">Size</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {optionsFiles.map((file, idx) => (
                        <tr key={idx} className="text-sm">
                          <td className="py-3 text-gray-900">{file.date}</td>
                          <td className="py-3 font-medium text-purple-600">{file.symbol}</td>
                          <td className="py-3 text-gray-600">{formatNumber(file.records)}</td>
                          <td className="py-3 text-gray-600">{file.size_mb.toFixed(2)} MB</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Data Info */}
              <div className="mt-6 p-4 bg-gray-50 rounded-lg">
                <h3 className="font-medium text-gray-900 mb-2">What's being collected?</h3>
                <ul className="text-sm text-gray-600 space-y-1">
                  <li>• <strong>Strikes:</strong> ±20 from ATM (~40 strikes per symbol)</li>
                  <li>• <strong>Expiries:</strong> Current week, next 2 weeks, monthly, next monthly</li>
                  <li>• <strong>Data:</strong> LTP, Bid, Ask, Volume, OI, OHLC</li>
                  <li>• <strong>Expected:</strong> ~1.1 million records per day (both symbols)</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
