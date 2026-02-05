import { create } from 'zustand';
import type { TradingStatus, Regime, Position, Order } from '@/types';
import { tradingApi, regimeApi, positionsApi, ordersApi } from '@/services/api';

interface TradingStore {
  status: TradingStatus | null;
  regime: Regime | null;
  positions: Position[];
  orders: Order[];
  isLoading: boolean;
  error: string | null;

  fetchStatus: () => Promise<void>;
  fetchRegime: () => Promise<void>;
  fetchPositions: () => Promise<void>;
  fetchOrders: () => Promise<void>;
  startTrading: (mode: 'paper' | 'live') => Promise<void>;
  stopTrading: () => Promise<void>;
  flattenAll: (reason?: string) => Promise<void>;
}

export const useTradingStore = create<TradingStore>((set) => ({
  status: null,
  regime: null,
  positions: [],
  orders: [],
  isLoading: false,
  error: null,

  fetchStatus: async () => {
    try {
      const response = await tradingApi.getStatus();
      set({ status: response.data });
    } catch (error) {
      console.error('Failed to fetch status:', error);
    }
  },

  fetchRegime: async () => {
    try {
      const response = await regimeApi.getCurrent();
      set({ regime: response.data });
    } catch (error) {
      console.error('Failed to fetch regime:', error);
    }
  },

  fetchPositions: async () => {
    try {
      const response = await positionsApi.getAll();
      set({ positions: response.data });
    } catch (error) {
      console.error('Failed to fetch positions:', error);
    }
  },

  fetchOrders: async () => {
    try {
      const response = await ordersApi.getAll();
      set({ orders: response.data });
    } catch (error) {
      console.error('Failed to fetch orders:', error);
    }
  },

  startTrading: async (mode) => {
    set({ isLoading: true, error: null });
    try {
      await tradingApi.start(mode);
      const response = await tradingApi.getStatus();
      set({ status: response.data, isLoading: false });
    } catch (error) {
      set({ error: 'Failed to start trading', isLoading: false });
    }
  },

  stopTrading: async () => {
    set({ isLoading: true, error: null });
    try {
      await tradingApi.stop();
      const response = await tradingApi.getStatus();
      set({ status: response.data, isLoading: false });
    } catch (error) {
      set({ error: 'Failed to stop trading', isLoading: false });
    }
  },

  flattenAll: async (reason) => {
    set({ isLoading: true, error: null });
    try {
      await tradingApi.flatten(reason);
      set({ positions: [], isLoading: false });
    } catch (error) {
      set({ error: 'Failed to flatten positions', isLoading: false });
    }
  },
}));
