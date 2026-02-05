import axios from 'axios';
import type { TradingStatus, Regime, Position, Order, BacktestRequest, BacktestResult, User } from '@/types';

const api = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
});

// Auth
export const authApi = {
  getLoginUrl: () => api.get<{ url: string }>('/auth/login-url'),
  callback: (requestToken: string) => api.post<{ user: User }>('/auth/callback', { request_token: requestToken }),
  logout: () => api.post('/auth/logout'),
  me: () => api.get<User>('/auth/me'),
};

// Trading
export const tradingApi = {
  getStatus: () => api.get<TradingStatus>('/trading/status'),
  start: (mode: string) => api.post('/trading/start', null, { params: { mode } }),
  stop: () => api.post('/trading/stop'),
  flatten: (reason?: string) => api.post('/trading/flatten', null, { params: { reason } }),
};

// Regime
export const regimeApi = {
  getCurrent: () => api.get<Regime>('/regime/current'),
};

// Account & Margins
export interface AccountSummary {
  total_margin: number;
  used_margin: number;
  available_margin: number;
  cash_available: number;
  collateral: number;
  intraday_payin: number;
  margin_utilization_pct: number;
  segments: {
    equity: { available: number; used: number; cash: number };
    commodity: { available: number; used: number; cash: number };
  };
}

export interface PositionWithMargin {
  id: string;
  tradingsymbol: string;
  instrument_token: number;
  exchange: string;
  quantity: number;
  average_price: number;
  last_price: number;
  pnl: number;
  pnl_pct: number;
  product: string;
  source: string;
  margin_used: number;
  margin_pct: number;
  pnl_on_margin_pct: number;
}

export interface PositionsWithMarginsResponse {
  positions: PositionWithMargin[];
  account: {
    total_margin: number;
    used_margin: number;
    available_margin: number;
    margin_utilization_pct: number;
  };
  total_position_margin: number;
}

export const accountApi = {
  getSummary: () => api.get<AccountSummary>('/account/summary'),
};

// Positions & Orders
export const positionsApi = {
  getAll: () => api.get<Position[]>('/positions'),
  getWithMargins: () => api.get<PositionsWithMarginsResponse>('/positions/with-margins'),
  getByStrategy: () => api.get<{ strategies: StrategyGroup[] }>('/positions/by-strategy'),
};

export const ordersApi = {
  getAll: () => api.get<Order[]>('/orders'),
};

// Strategies
export interface CreateStrategyRequest {
  name: string;
  label?: string;
  position_ids: string[];
  portfolio_id?: string;
  notes?: string;
  tags?: string[];
}

export interface CreateStrategyResponse {
  id: string;
  name: string;
  positions_count: number;
  message: string;
}

export const strategiesApi = {
  getAll: (params?: { status?: string; strategy_type?: string; source?: string }) => 
    api.get<Strategy[]>('/strategies', { params }),
  getPerformance: (days?: number) => 
    api.get<StrategyPerformance>('/strategies/performance', { params: { days } }),
  create: (data: CreateStrategyRequest) => 
    api.post<CreateStrategyResponse>('/strategies', data),
  getDetail: (id: string) => 
    api.get<Strategy>(`/strategies/${id}`),
  updatePositions: (id: string, data: { add?: string[]; remove?: string[] }) =>
    api.put(`/strategies/${id}/positions`, data),
  close: (id: string, reason?: string) =>
    api.post(`/strategies/${id}/close`, null, { params: { reason } }),
};

// Portfolios
export interface Portfolio {
  id: string;
  name: string;
  description?: string;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  strategy_count: number;
  is_active: boolean;
}

export const portfoliosApi = {
  getAll: () => api.get<Portfolio[]>('/portfolios'),
  create: (data: { name: string; description?: string }) => 
    api.post<{ id: string; name: string; message: string }>('/portfolios', data),
  getPerformance: (id: string, days?: number) =>
    api.get(`/portfolios/${id}/performance`, { params: { days } }),
};

// Position sync
export const positionSyncApi = {
  sync: () => api.post<{ message: string; count: number }>('/positions/sync'),
};

// Types for strategy API
export interface StrategyTrade {
  id: string;
  tradingsymbol: string;
  instrument_token: number;
  exchange: string;
  instrument_type?: string;
  quantity: number;
  entry_price: number;
  last_price: number | null;
  unrealized_pnl: number;
  realized_pnl: number;
  pnl_pct: number;
  status: string;
  entry_time: string | null;
}

export interface Strategy {
  id: string;
  name: string;
  label: string | null;
  status: string;
  source: string;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  trades_count: number;
  trades: StrategyTrade[];
  notes: string | null;
  tags: string[] | null;
  created_at: string | null;
}

export interface StrategyGroup {
  strategy_type: string;
  open_count: number;
  closed_count: number;
  total_pnl: number;
  unrealized_pnl: number;
  win_rate: number;
  winning_trades: number;
  losing_trades: number;
  positions: {
    id: string;
    instrument: string;
    entry_price: number;
    current_pnl: number;
    current_pnl_pct: number;
    status: string;
    source: string;
    entry_timestamp: string | null;
    expiry: string | null;
  }[];
}

export interface StrategyPerformance {
  period: { from: string; to: string };
  by_strategy: {
    strategy_type: string;
    open_count: number;
    closed_count: number;
    total_pnl: number;
    unrealized_pnl: number;
    win_rate: number;
  }[];
  daily_records: {
    date: string;
    strategy_type: string;
    realized_pnl: number;
    trades_closed: number;
    win_rate: number;
  }[];
}

// Backtest
export const backtestApi = {
  run: (request: BacktestRequest) => api.post<BacktestResult>('/backtest/run', request),
  getDataFiles: () => api.get<{ files: string[] }>('/data/files'),
  downloadData: (symbol: string, days: number, interval: string) => 
    api.post('/data/download', { symbol, days, interval }),
};

// Health
export const healthApi = {
  check: () => api.get('/health'),
};

export default api;
