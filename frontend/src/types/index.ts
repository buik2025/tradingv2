export interface User {
  user_id: string;
  user_name: string;
  email: string;
  broker: string;
}

export interface Position {
  id: string;
  tradingsymbol: string;
  instrument_token?: number;
  exchange: string;
  quantity: number;
  average_price: number;
  last_price: number;
  pnl: number;
  pnl_pct: number;
  product?: string;
  source: 'LIVE' | 'PAPER';
}

export interface Order {
  order_id: string;
  tradingsymbol: string;
  exchange: string;
  transaction_type: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  average_price: number;
  status: 'PENDING' | 'COMPLETE' | 'REJECTED' | 'CANCELLED';
  order_timestamp: string;
  tag?: string;
}

export type RegimeType = 'RANGE_BOUND' | 'MEAN_REVERSION' | 'TREND' | 'CHAOS';

export interface Regime {
  regime: RegimeType;
  confidence: number;
  is_safe: boolean;
  metrics: {
    adx: number;
    rsi: number;
    iv_percentile: number;
  };
  timestamp: string;
}

export interface TradingStatus {
  mode: 'paper' | 'live' | 'stopped';
  running: boolean;
  positions: number;
  daily_pnl: number;
  regime: RegimeType | null;
}

export interface BacktestRequest {
  data_file: string;
  strategy: string;
  initial_capital: number;
  position_size_pct: number;
}

export interface BacktestResult {
  total_trades: number;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  profit_factor: number;
}

export interface AuthState {
  isAuthenticated: boolean;
  user: User | null;
  isLoading: boolean;
  error: string | null;
}
