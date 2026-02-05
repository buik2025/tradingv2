import { useEffect } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/authStore';
import { AppShell } from '@/components/layout/AppShell';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { Login } from '@/pages/Login';
import { Callback } from '@/pages/Callback';
import { Dashboard } from '@/pages/Dashboard';
import { PositionsPage } from '@/pages/PositionsPage';
import { StrategiesPage } from '@/pages/StrategiesPage';
import { PortfoliosPage } from '@/pages/PortfoliosPage';
import { Orders } from '@/pages/Orders';
import { Backtest } from '@/pages/Backtest';
import { Settings } from '@/pages/Settings';

const queryClient = new QueryClient();

function AppContent() {
  const { checkAuth } = useAuthStore();

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  return (
    <Routes>
      <Route path="/" element={<Login />} />
      <Route path="/callback" element={<Callback />} />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="positions" element={<PositionsPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="portfolios" element={<PortfoliosPage />} />
        <Route path="orders" element={<Orders />} />
        <Route path="backtest" element={<Backtest />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
