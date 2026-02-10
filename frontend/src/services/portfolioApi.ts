/**
 * Unified Portfolio API - All data comes pre-calculated from backend.
 * Frontend should only display, no calculations needed.
 */

import api from './api';

// ============== Types ==============

export interface Position {
  id: string;
  tradingsymbol: string;
  instrument_token: number;
  exchange: string;
  quantity: number;
  average_price: number;
  last_price: number;
  close_price: number;
  ltp_change: number;
  ltp_change_pct: number;
  pnl: number;
  pnl_pct: number;
  product: string;  // CNC, NRML, MIS
  source: string;   // LIVE, PAPER
  margin_used: number;
  margin_pct: number;
  pnl_on_margin_pct: number;
  // Kite-like categorization fields
  segment: string;  // CASH, NFO, MCX, BFO
  instrument_type: string;  // EQ, FUT, CE, PE
  underlying: string;  // Underlying symbol for derivatives
  expiry?: string;  // Expiry date for derivatives
  strike?: number;  // Strike price for options
  is_overnight: boolean;
  is_short: boolean;  // True short (derivatives/intraday)
  is_sold_holding: boolean;  // CNC equity sold from holdings
  position_status: string;  // OPEN or CLOSED
  transaction_type: string;  // BUY or SELL
}

export interface Trade {
  id: string;
  tradingsymbol: string;
  instrument_token: number;
  exchange: string;
  instrument_type?: string;
  quantity: number;
  entry_price: number;
  last_price?: number;
  unrealized_pnl: number;
  realized_pnl: number;
  pnl_pct: number;
  status: string;
  entry_time?: string;
  margin_used: number;
  margin_pct: number;
  pnl_on_margin_pct: number;
}

export interface Strategy {
  id: string;
  name: string;
  label?: string;
  status: string;
  source: string;
  trades_count: number;
  trades: Trade[];
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  total_margin: number;
  margin_pct: number;
  pnl_on_margin_pct: number;
  notes?: string;
  tags?: string[];
  created_at?: string;
}

export interface Portfolio {
  id: string;
  name: string;
  description?: string;
  strategy_count: number;
  strategies: Strategy[];
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  total_margin: number;
  margin_pct: number;
  pnl_on_margin_pct: number;
  is_active: boolean;
}

export interface Account {
  total_margin: number;
  used_margin: number;
  available_margin: number;
  cash_available: number;
  collateral: number;
  margin_utilization_pct: number;
  available_margin_pct: number;
}

export interface Totals {
  pnl: number;
  margin: number;
  pnl_on_margin_pct: number;
  count: number;
}

export interface PositionsResponse {
  positions: Position[];
  account: Account;
  totals: Totals;
}

export interface StrategiesResponse {
  strategies: Strategy[];
  account: Account;
  totals: Totals;
}

export interface PortfoliosResponse {
  portfolios: Portfolio[];
  account: Account;
  totals: Totals;
}

// ============== API ==============

export const portfolioApi = {
  getAccount: () => 
    api.get<Account>('/portfolio/account'),
  
  getPositions: () => 
    api.get<PositionsResponse>('/portfolio/positions'),
  
  getStrategies: () => 
    api.get<StrategiesResponse>('/portfolio/strategies'),
  
  getPortfolios: () => 
    api.get<PortfoliosResponse>('/portfolio/portfolios'),
};
