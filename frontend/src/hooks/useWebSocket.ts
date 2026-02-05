/**
 * WebSocket hook for real-time price and P&L updates.
 * 
 * Connects to backend WebSocket and provides:
 * - Real-time position updates
 * - Strategy P&L aggregation
 * - Portfolio P&L aggregation
 */

import { useEffect, useRef, useState, useCallback } from 'react';

export interface PositionUpdate {
  id: string;
  tradingsymbol: string;
  instrument_token: number;
  exchange: string;
  quantity: number;
  average_price: number;
  last_price: number | null;
  pnl: number;
  pnl_pct?: number;
  source: string;
}

export interface StrategyUpdate {
  id: string;
  name: string;
  label: string | null;
  status: string;
  unrealized_pnl: number;
  realized_pnl: number;
  position_count: number;
  source: string;
}

export interface PortfolioUpdate {
  id: string;
  name: string;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  strategy_count: number;
}

export interface WebSocketState {
  positions: PositionUpdate[];
  strategies: StrategyUpdate[];
  portfolios: PortfolioUpdate[];
  connected: boolean;
  lastUpdated: Date | null;
}

interface WebSocketMessage {
  type: 'initial_state' | 'price_update' | 'heartbeat' | 'pong';
  data?: {
    positions?: PositionUpdate[];
    strategies?: StrategyUpdate[];
    portfolios?: PortfolioUpdate[];
    timestamp?: string;
  };
  timestamp?: string;
}

const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/v1/ws/prices`;

export function useWebSocket(): WebSocketState & { reconnect: () => void } {
  const [state, setState] = useState<WebSocketState>({
    positions: [],
    strategies: [],
    portfolios: [],
    connected: false,
    lastUpdated: null,
  });
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  
  const connect = useCallback(() => {
    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }
    
    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      
      ws.onopen = () => {
        console.log('WebSocket connected');
        setState(prev => ({ ...prev, connected: true }));
        
        // Start ping interval to keep connection alive
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 25000);
      };
      
      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          
          switch (message.type) {
            case 'initial_state':
            case 'price_update':
              setState(prev => ({
                ...prev,
                positions: message.data?.positions || prev.positions,
                strategies: message.data?.strategies || prev.strategies,
                portfolios: message.data?.portfolios || prev.portfolios,
                lastUpdated: new Date(),
              }));
              break;
            
            case 'heartbeat':
            case 'pong':
              // Connection is alive
              break;
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };
      
      ws.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason);
        setState(prev => ({ ...prev, connected: false }));
        
        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }
        
        // Attempt reconnect after delay (unless intentionally closed)
        if (event.code !== 1000) {
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('Attempting WebSocket reconnect...');
            connect();
          }, 3000);
        }
      };
      
      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
      };
      
    } catch (e) {
      console.error('Failed to create WebSocket:', e);
      
      // Retry after delay
      reconnectTimeoutRef.current = setTimeout(connect, 5000);
    }
  }, []);
  
  const reconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    connect();
  }, [connect]);
  
  // Only connect once on mount, not on every render
  useEffect(() => {
    // Prevent multiple connections
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      return;
    }
    
    connect();
    
    return () => {
      // Cleanup on unmount
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted');
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);  // Empty deps - only run on mount
  
  return { ...state, reconnect };
}

/**
 * Hook to get position by ID from WebSocket state
 */
export function usePosition(positionId: string, wsState: WebSocketState): PositionUpdate | undefined {
  return wsState.positions.find(p => p.id === positionId);
}

/**
 * Hook to get strategy by ID from WebSocket state
 */
export function useStrategy(strategyId: string, wsState: WebSocketState): StrategyUpdate | undefined {
  return wsState.strategies.find(s => s.id === strategyId);
}

/**
 * Hook to get portfolio by ID from WebSocket state
 */
export function usePortfolio(portfolioId: string, wsState: WebSocketState): PortfolioUpdate | undefined {
  return wsState.portfolios.find(p => p.id === portfolioId);
}
