# Frontend Design Document (FDD)
## Trading System v2.0

**Version:** 1.0  
**Date:** February 2026  
**Status:** Draft

---

## 1. Overview

### 1.1 Purpose
This document describes the frontend architecture for the Trading System v2.0. The frontend provides a web-based interface for:
- KiteConnect OAuth authentication
- Real-time trading dashboard
- **Portfolio and strategy management**
- **Flexible position grouping into user-defined strategies**
- Backtesting interface
- Position and order management
- Market regime visualization

### 1.2 Core Concepts

#### Portfolio → Strategy → Position Hierarchy
```
Portfolio (decision-making level)
├── Total P&L tracking
├── Risk metrics for position sizing
└── Strategies[]
    ├── Strategy (user-defined grouping)
    │   ├── Custom name and optional label
    │   ├── Aggregate P&L
    │   └── Positions[]
    │       ├── Position 1 (broker-level)
    │       ├── Position 2
    │       └── ...
    └── Ungrouped Positions
```

**Key Principles:**
- **Flexibility**: No fixed strategy types - users define their own groupings
- **Runtime adjustments**: Positions can be combined into strategies at any time
- **Portfolio-level decisions**: P&L tracking at portfolio level drives trading decisions
- **Performance attribution**: Track which strategies perform best for future optimization

### 1.3 Technology Stack
| Component | Technology |
|-----------|------------|
| Framework | React 18+ with TypeScript |
| Build Tool | Vite |
| Styling | TailwindCSS |
| UI Components | shadcn/ui |
| Icons | Lucide React |
| State Management | Zustand |
| Data Fetching | TanStack Query (React Query) |
| Charts | Recharts / Lightweight Charts |
| Routing | React Router v6 |

---

## 2. KiteConnect Authentication Flow

### 2.1 OAuth Flow Diagram
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │     │   Backend   │     │   Kite      │     │   Kite      │
│   (React)   │     │  (FastAPI)  │     │   Login     │     │   API       │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │                   │
       │ 1. Click Login    │                   │                   │
       │──────────────────>│                   │                   │
       │                   │                   │                   │
       │ 2. Return login_url                   │                   │
       │<──────────────────│                   │                   │
       │                   │                   │                   │
       │ 3. Redirect to Kite Login             │                   │
       │──────────────────────────────────────>│                   │
       │                   │                   │                   │
       │ 4. User authenticates                 │                   │
       │                   │                   │                   │
       │ 5. Redirect with request_token        │                   │
       │<──────────────────────────────────────│                   │
       │                   │                   │                   │
       │ 6. Send request_token                 │                   │
       │──────────────────>│                   │                   │
       │                   │                   │                   │
       │                   │ 7. Exchange for access_token          │
       │                   │──────────────────────────────────────>│
       │                   │                   │                   │
       │                   │ 8. Return access_token                │
       │                   │<──────────────────────────────────────│
       │                   │                   │                   │
       │ 9. Return session │                   │                   │
       │<──────────────────│                   │                   │
       │                   │                   │                   │
       │ 10. Store token, show dashboard       │                   │
       │                   │                   │                   │
```

### 2.2 Authentication States
| State | Description | UI |
|-------|-------------|-----|
| `UNAUTHENTICATED` | No valid token | Show login button |
| `AUTHENTICATING` | OAuth in progress | Show loading spinner |
| `AUTHENTICATED` | Valid access token | Show dashboard |
| `TOKEN_EXPIRED` | Token needs refresh | Prompt re-login |
| `ERROR` | Auth failed | Show error message |

### 2.3 Token Storage
- Access token stored in **httpOnly cookie** (set by backend)
- Frontend uses session-based auth
- Token expiry: End of trading day (~3:30 PM IST)
- Auto-logout on token expiry

---

## 3. Application Structure

### 3.1 Page Hierarchy
```
/                       → Landing/Login page
/callback               → OAuth callback handler
/dashboard              → Main trading dashboard (protected)
/dashboard/positions    → Position management (with Strategy view toggle)
/dashboard/strategies   → Strategy management
/dashboard/portfolios   → Portfolio overview
/dashboard/orders       → Order history
/dashboard/backtest     → Backtesting interface
/dashboard/settings     → User settings
```

### 3.2 Component Architecture
```
src/
├── components/
│   ├── ui/                    # shadcn/ui components
│   ├── auth/
│   │   ├── LoginButton.tsx
│   │   ├── AuthCallback.tsx
│   │   └── ProtectedRoute.tsx
│   ├── dashboard/
│   │   ├── Header.tsx
│   │   ├── Sidebar.tsx
│   │   ├── RegimeCard.tsx
│   │   ├── PositionsTable.tsx
│   │   ├── StrategyCard.tsx
│   │   ├── PortfolioSummary.tsx
│   │   ├── OrdersTable.tsx
│   │   ├── PnLChart.tsx
│   │   └── QuickActions.tsx
│   ├── strategy/
│   │   ├── StrategyList.tsx
│   │   ├── StrategyDetail.tsx
│   │   ├── CreateStrategyModal.tsx
│   │   └── PositionSelector.tsx
│   ├── portfolio/
│   │   ├── PortfolioList.tsx
│   │   ├── PortfolioDetail.tsx
│   │   └── PerformanceChart.tsx
│   ├── backtest/
│   │   ├── BacktestForm.tsx
│   │   ├── BacktestResults.tsx
│   │   └── EquityCurve.tsx
│   └── common/
│       ├── LoadingSpinner.tsx
│       ├── ErrorBoundary.tsx
│       └── Toast.tsx
├── hooks/
│   ├── useAuth.ts
│   ├── usePositions.ts
│   ├── useStrategies.ts
│   ├── usePortfolios.ts
│   ├── useOrders.ts
│   ├── useRegime.ts
│   └── useBacktest.ts
├── stores/
│   ├── authStore.ts
│   ├── tradingStore.ts
│   ├── strategyStore.ts
│   └── portfolioStore.ts
├── services/
│   └── api.ts
├── types/
│   └── index.ts
└── pages/
    ├── Login.tsx
    ├── Callback.tsx
    ├── Dashboard.tsx
    ├── Positions.tsx
    ├── Strategies.tsx
    ├── Portfolios.tsx
    ├── Orders.tsx
    ├── Backtest.tsx
    └── Settings.tsx
```

---

## 4. UI/UX Design

### 4.1 Design Principles
1. **Dark Theme First** - Trading apps work better with dark themes
2. **Information Density** - Show key metrics at a glance
3. **Real-time Updates** - Live data with visual indicators
4. **Responsive** - Works on desktop and tablet
5. **Accessibility** - WCAG 2.1 AA compliant

### 4.2 Color Palette
```css
/* Dark Theme */
--background: #0a0a0a;
--card: #141414;
--border: #262626;
--text-primary: #fafafa;
--text-secondary: #a1a1aa;

/* Semantic Colors */
--profit: #22c55e;      /* Green */
--loss: #ef4444;        /* Red */
--warning: #f59e0b;     /* Amber */
--info: #3b82f6;        /* Blue */

/* Regime Colors */
--regime-range: #8b5cf6;      /* Purple */
--regime-trend: #06b6d4;      /* Cyan */
--regime-mean-rev: #22c55e;   /* Green */
--regime-chaos: #ef4444;      /* Red */
```

### 4.3 Key Screens

#### 4.3.1 Login Page
```
┌────────────────────────────────────────────────────────────┐
│                                                            │
│                    Trading System v2.0                     │
│                                                            │
│              Multi-Agent Algorithmic Trading               │
│                                                            │
│                 ┌─────────────────────┐                    │
│                 │  Login with Kite    │                    │
│                 └─────────────────────┘                    │
│                                                            │
│              Powered by KiteConnect API                    │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

#### 4.3.2 Dashboard
```
┌────────────────────────────────────────────────────────────┐
│ ☰  Trading System v2.0          Paper Mode    [User] [⚙️] │
├────────┬───────────────────────────────────────────────────┤
│        │                                                   │
│ 📊     │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ │
│ Dash   │  │ P&L     │ │ Regime  │ │ Margin  │ │ Positions│ │
│        │  │ +12,450 │ │ RANGE   │ │ 23%     │ │ 3 Open  │ │
│ 📈     │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ │
│ Pos    │                                                   │
│        │  ┌─────────────────────────────────────────────┐ │
│ 📋     │  │              P&L Chart                      │ │
│ Orders │  │                                             │ │
│        │  │     ╱╲    ╱╲                               │ │
│ 🔬     │  │    ╱  ╲  ╱  ╲    ╱╲                       │ │
│ Back   │  │   ╱    ╲╱    ╲  ╱  ╲                      │ │
│        │  │  ╱            ╲╱    ╲                      │ │
│ ⚙️     │  └─────────────────────────────────────────────┘ │
│ Set    │                                                   │
│        │  ┌─────────────────────────────────────────────┐ │
│        │  │ Open Positions                              │ │
│        │  ├─────────────────────────────────────────────┤ │
│        │  │ NIFTY IC 22000/22500  │ +2,340 │ 65% │ Exit│ │
│        │  │ BANKNIFTY JL 48000    │ -1,200 │ 32% │ Exit│ │
│        │  └─────────────────────────────────────────────┘ │
│        │                                                   │
└────────┴───────────────────────────────────────────────────┘
```

#### 4.3.3 Backtest Page
```
┌────────────────────────────────────────────────────────────┐
│ ☰  Backtesting                                             │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌─────────────────────┐  ┌─────────────────────────────┐ │
│  │ Configuration       │  │ Results                     │ │
│  │                     │  │                             │ │
│  │ Symbol: [NIFTY  ▼]  │  │ Total Return: +24.5%       │ │
│  │ Period: [90 days ]  │  │ Sharpe Ratio: 1.82         │ │
│  │ Strategy: [IC   ▼]  │  │ Max Drawdown: -8.2%        │ │
│  │ Capital: [10L    ]  │  │ Win Rate: 67%              │ │
│  │                     │  │ Profit Factor: 2.1         │ │
│  │ [▶ Run Backtest]    │  │ Total Trades: 45           │ │
│  └─────────────────────┘  └─────────────────────────────┘ │
│                                                            │
│  ┌─────────────────────────────────────────────────────┐  │
│  │                  Equity Curve                        │  │
│  │                                                      │  │
│  │      ╱╲    ╱╲                    ╱                  │  │
│  │     ╱  ╲  ╱  ╲    ╱╲    ╱╲    ╱                    │  │
│  │    ╱    ╲╱    ╲  ╱  ╲  ╱  ╲  ╱                     │  │
│  │   ╱            ╲╱    ╲╱    ╲╱                       │  │
│  │  ╱                                                  │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## 5. API Integration

### 5.1 Backend Endpoints (FastAPI)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/auth/login-url` | GET | Get Kite login URL |
| `/api/v1/auth/callback` | POST | Exchange request_token |
| `/api/v1/auth/logout` | POST | Logout user |
| `/api/v1/auth/me` | GET | Get current user |
| `/api/v1/trading/status` | GET | Trading system status |
| `/api/v1/trading/start` | POST | Start trading |
| `/api/v1/trading/stop` | POST | Stop trading |
| `/api/v1/positions` | GET | Get positions |
| `/api/v1/positions/sync` | POST | Sync positions from broker |
| `/api/v1/positions/by-strategy` | GET | Get positions grouped by strategy |
| `/api/v1/orders` | GET | Get orders |
| `/api/v1/regime/current` | GET | Get current regime |
| `/api/v1/strategies` | GET | Get all strategies |
| `/api/v1/strategies` | POST | Create strategy from positions |
| `/api/v1/strategies/{id}` | GET | Get strategy detail |
| `/api/v1/strategies/{id}/positions` | PUT | Add/remove positions |
| `/api/v1/strategies/{id}/close` | POST | Close strategy |
| `/api/v1/portfolios` | GET | Get all portfolios |
| `/api/v1/portfolios` | POST | Create portfolio |
| `/api/v1/portfolios/{id}/performance` | GET | Portfolio performance |
| `/api/v1/backtest/run` | POST | Run backtest |
| `/api/v1/data/download` | POST | Download historical data |

### 5.2 WebSocket Endpoint

**URL**: `ws://localhost:8173/api/v1/ws/prices`

Real-time price and P&L updates via WebSocket connection.

```typescript
// Message types
interface WebSocketMessage {
  type: 'initial_state' | 'price_update' | 'heartbeat' | 'pong';
  data?: {
    positions: PositionUpdate[];
    strategies: StrategyUpdate[];
    portfolios: PortfolioUpdate[];
    timestamp: string;
  };
}

// Frontend hook usage
const { positions, strategies, portfolios, connected, lastUpdated } = useWebSocket();

// Connection status shown in UI
// - "Live" badge (green) when WebSocket connected
// - "Polling" badge (gray) when falling back to REST polling
```

**Data Flow**:
```
Kite WebSocket Ticker → Backend Hub → Frontend Client
         ↓
    Positions → Strategies → Portfolios
    (cascade P&L aggregation)
```

**Key Backend Services**:

| Service | File | Purpose |
|---------|------|---------|
| `InstrumentCache` | `services/instrument_cache.py` | Caches lot sizes, multipliers from Kite |
| `PnLCalculator` | `services/pnl_calculator.py` | Backend P&L calculations (source of truth) |
| `KiteTickerManager` | `api/websocket.py` | Single Kite WebSocket connection |

**P&L Calculation** (backend is source of truth):
```python
# All instrument types (EQ, FUT, CE, PE):
pnl = (last_price - average_price) * quantity
pnl_pct = (pnl / (average_price * abs(quantity))) * 100
```

---

## 6. State Management

### 6.1 Auth Store (Zustand)
```typescript
interface AuthState {
  isAuthenticated: boolean;
  user: User | null;
  accessToken: string | null;
  isLoading: boolean;
  error: string | null;
  
  login: () => Promise<void>;
  logout: () => Promise<void>;
  handleCallback: (requestToken: string) => Promise<void>;
}
```

### 6.2 Trading Store (Zustand)
```typescript
interface TradingState {
  mode: 'paper' | 'live' | 'stopped';
  isRunning: boolean;
  positions: Position[];
  orders: Order[];
  regime: Regime | null;
  dailyPnL: number;
  
  startTrading: (mode: string) => Promise<void>;
  stopTrading: () => Promise<void>;
  flattenAll: () => Promise<void>;
}
```

### 6.3 WebSocket State (Hook)
```typescript
interface WebSocketState {
  positions: PositionUpdate[];
  strategies: StrategyUpdate[];
  portfolios: PortfolioUpdate[];
  connected: boolean;
  lastUpdated: Date | null;
}

// Usage in components
const wsState = useWebSocket();

// Positions page uses WebSocket data when connected,
// falls back to REST polling when disconnected
const positions = wsState.connected && wsState.positions.length > 0 
  ? wsState.positions 
  : storePositions;
```

---

## 7. Security Considerations

### 7.1 Token Handling
- Never store access_token in localStorage (XSS vulnerable)
- Use httpOnly cookies set by backend
- Implement CSRF protection
- Token refresh handled by backend

### 7.2 API Security
- All API calls over HTTPS
- CORS configured for frontend origin only
- Rate limiting on sensitive endpoints
- Input validation on all forms

---

## 8. Performance Optimization

### 8.1 Strategies
- **Code Splitting**: Lazy load routes
- **Memoization**: React.memo for expensive components
- **Virtual Lists**: For large order/position tables
- **Debouncing**: For search/filter inputs
- **Caching**: TanStack Query for API responses

### 8.2 Bundle Size Targets
- Initial JS: < 200KB gzipped
- First Contentful Paint: < 1.5s
- Time to Interactive: < 3s

---

## 9. Testing Strategy

### 9.1 Test Types
| Type | Tool | Coverage Target |
|------|------|-----------------|
| Unit | Vitest | 80% |
| Component | React Testing Library | Key components |
| E2E | Playwright | Critical flows |

### 9.2 Critical Test Scenarios
1. Login flow (happy path + errors)
2. OAuth callback handling
3. Position display and updates
4. Backtest execution
5. Trading start/stop

---

## 10. Deployment

### 10.1 Build & Deploy
```bash
# Build
npm run build

# Preview
npm run preview

# Deploy (Vercel/Netlify)
vercel deploy --prod
```

### 10.2 Environment Variables
```env
VITE_API_URL=http://localhost:8000
VITE_KITE_API_KEY=your_api_key
```

---

## Appendix A: Type Definitions

```typescript
interface User {
  user_id: string;
  user_name: string;
  email: string;
  broker: string;
}

interface Position {
  id: string;
  tradingsymbol: string;
  exchange: string;
  quantity: number;
  average_price: number;
  last_price: number;
  pnl: number;
  pnl_pct: number;
}

interface Order {
  order_id: string;
  tradingsymbol: string;
  transaction_type: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  status: 'PENDING' | 'COMPLETE' | 'REJECTED' | 'CANCELLED';
  order_timestamp: string;
}

interface Regime {
  regime: 'RANGE_BOUND' | 'MEAN_REVERSION' | 'TREND' | 'CHAOS';
  confidence: number;
  is_safe: boolean;
  metrics: {
    adx: number;
    rsi: number;
    iv_percentile: number;
  };
}

interface BacktestResult {
  total_trades: number;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  profit_factor: number;
  equity_curve: number[];
}
```
