# Frontend Implementation Plan
## Trading System v2.0

---

## Phase 1: Project Setup & Authentication (Day 1-2)

### 1.1 Initialize React Project
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

### 1.2 Install Dependencies
```bash
# UI & Styling
npm install tailwindcss postcss autoprefixer
npm install @radix-ui/react-* class-variance-authority clsx tailwind-merge
npm install lucide-react

# State & Data
npm install zustand @tanstack/react-query axios

# Routing
npm install react-router-dom

# Charts
npm install recharts lightweight-charts

# Utils
npm install date-fns
```

### 1.3 Configure TailwindCSS
- Setup dark theme as default
- Configure color palette from FDD
- Add custom animations

### 1.4 Setup shadcn/ui
```bash
npx shadcn-ui@latest init
npx shadcn-ui@latest add button card input table tabs badge
```

### 1.5 Implement Authentication Flow
- [ ] Create `LoginButton` component
- [ ] Create `AuthCallback` page to handle OAuth redirect
- [ ] Create `ProtectedRoute` wrapper
- [ ] Setup `authStore` with Zustand
- [ ] Add auth API endpoints to backend

**Backend Changes Required:**
```python
# New endpoints in backend/app/api/routes.py
@router.get("/auth/login-url")
@router.post("/auth/callback")
@router.post("/auth/logout")
@router.get("/auth/me")
```

---

## Phase 2: Core Layout & Navigation (Day 2-3)

### 2.1 Layout Components
- [ ] `AppShell` - Main layout wrapper
- [ ] `Header` - Top navigation bar
- [ ] `Sidebar` - Side navigation
- [ ] `MobileNav` - Responsive navigation

### 2.2 Routing Setup
```typescript
const routes = [
  { path: '/', element: <Login /> },
  { path: '/callback', element: <AuthCallback /> },
  { 
    path: '/dashboard', 
    element: <ProtectedRoute><Dashboard /></ProtectedRoute>,
    children: [
      { path: '', element: <Overview /> },
      { path: 'positions', element: <Positions /> },
      { path: 'orders', element: <Orders /> },
      { path: 'backtest', element: <Backtest /> },
      { path: 'settings', element: <Settings /> },
    ]
  },
]
```

### 2.3 Common Components
- [ ] `LoadingSpinner`
- [ ] `ErrorBoundary`
- [ ] `Toast` notifications
- [ ] `ConfirmDialog`

---

## Phase 3: Dashboard Overview (Day 3-4)

### 3.1 Metric Cards
- [ ] `PnLCard` - Daily P&L with trend
- [ ] `RegimeCard` - Current market regime
- [ ] `MarginCard` - Margin utilization
- [ ] `PositionsCard` - Open positions count

### 3.2 Charts
- [ ] `PnLChart` - Daily P&L line chart
- [ ] `EquityCurve` - Cumulative returns

### 3.3 Quick Actions
- [ ] Start/Stop Trading button
- [ ] Mode selector (Paper/Live)
- [ ] Emergency Flatten button

### 3.4 Trading Store
```typescript
// stores/tradingStore.ts
interface TradingState {
  mode: 'paper' | 'live' | 'stopped';
  isRunning: boolean;
  dailyPnL: number;
  regime: Regime | null;
  // ... actions
}
```

---

## Phase 4: Positions & Orders (Day 4-5)

### 4.1 Positions Page
- [ ] `PositionsTable` - Sortable, filterable table
- [ ] Position detail modal
- [ ] Exit position action
- [ ] P&L color coding (green/red)

### 4.2 Orders Page
- [ ] `OrdersTable` - Order history
- [ ] Order status badges
- [ ] Filter by status/date
- [ ] Cancel order action

### 4.3 Data Hooks
```typescript
// hooks/usePositions.ts
export function usePositions() {
  return useQuery({
    queryKey: ['positions'],
    queryFn: () => api.get('/positions'),
    refetchInterval: 5000, // Poll every 5s
  });
}
```

---

## Phase 5: Backtesting Interface (Day 5-6)

### 5.1 Backtest Form
- [ ] Symbol selector
- [ ] Date range picker
- [ ] Strategy selector
- [ ] Capital input
- [ ] Position size slider

### 5.2 Backtest Results
- [ ] Metrics summary cards
- [ ] Equity curve chart
- [ ] Trade list table
- [ ] Drawdown chart

### 5.3 Data Download
- [ ] Download data button
- [ ] Progress indicator
- [ ] Available files list

---

## Phase 6: Settings & Polish (Day 6-7)

### 6.1 Settings Page
- [ ] User profile display
- [ ] Trading preferences
- [ ] Risk parameters
- [ ] Notification settings

### 6.2 Polish
- [ ] Loading states
- [ ] Error handling
- [ ] Empty states
- [ ] Animations/transitions
- [ ] Responsive design fixes

### 6.3 Testing
- [ ] Unit tests for stores
- [ ] Component tests
- [ ] E2E test for login flow

---

## File Structure

```
frontend/
├── public/
│   └── favicon.ico
├── src/
│   ├── components/
│   │   ├── ui/              # shadcn components
│   │   ├── auth/
│   │   │   ├── LoginButton.tsx
│   │   │   ├── AuthCallback.tsx
│   │   │   └── ProtectedRoute.tsx
│   │   ├── layout/
│   │   │   ├── AppShell.tsx
│   │   │   ├── Header.tsx
│   │   │   └── Sidebar.tsx
│   │   ├── dashboard/
│   │   │   ├── MetricCard.tsx
│   │   │   ├── RegimeCard.tsx
│   │   │   ├── PnLChart.tsx
│   │   │   └── QuickActions.tsx
│   │   ├── positions/
│   │   │   └── PositionsTable.tsx
│   │   ├── orders/
│   │   │   └── OrdersTable.tsx
│   │   └── backtest/
│   │       ├── BacktestForm.tsx
│   │       └── BacktestResults.tsx
│   ├── hooks/
│   │   ├── useAuth.ts
│   │   ├── usePositions.ts
│   │   ├── useOrders.ts
│   │   ├── useRegime.ts
│   │   └── useBacktest.ts
│   ├── stores/
│   │   ├── authStore.ts
│   │   └── tradingStore.ts
│   ├── services/
│   │   └── api.ts
│   ├── types/
│   │   └── index.ts
│   ├── pages/
│   │   ├── Login.tsx
│   │   ├── Callback.tsx
│   │   ├── Dashboard.tsx
│   │   ├── Positions.tsx
│   │   ├── Orders.tsx
│   │   ├── Backtest.tsx
│   │   └── Settings.tsx
│   ├── lib/
│   │   └── utils.ts
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── .env
├── .env.example
├── tailwind.config.js
├── tsconfig.json
├── vite.config.ts
└── package.json
```

---

## Backend API Updates Required

### New Auth Endpoints
```python
# backend/app/api/auth.py

@router.get("/auth/login-url")
async def get_login_url():
    """Return Kite login URL"""
    
@router.post("/auth/callback")
async def auth_callback(request_token: str):
    """Exchange request_token for access_token"""
    
@router.post("/auth/logout")
async def logout():
    """Clear session"""
    
@router.get("/auth/me")
async def get_current_user():
    """Get current authenticated user"""
```

### Session Management
- Use httpOnly cookies for access_token
- Implement session middleware
- Add CORS configuration for frontend origin

---

## Environment Variables

### Frontend (.env)
```env
VITE_API_URL=http://localhost:8000
VITE_APP_NAME=Trading System v2.0
```

### Backend (.env) - additions
```env
FRONTEND_URL=http://localhost:5173
KITE_REDIRECT_URL=http://localhost:8000/api/v1/auth/callback
```

---

## Milestones

| Milestone | Description | Target |
|-----------|-------------|--------|
| M1 | Auth flow working | Day 2 |
| M2 | Dashboard with mock data | Day 4 |
| M3 | Positions & Orders pages | Day 5 |
| M4 | Backtest interface | Day 6 |
| M5 | Production ready | Day 7 |

---

## Next Steps

1. **Start with Phase 1** - Create React project and setup auth
2. **Update Backend** - Add auth endpoints before frontend work
3. **Iterate** - Build incrementally, test each feature

Ready to begin implementation?
