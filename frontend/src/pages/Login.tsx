import { useAuthStore } from '@/stores/authStore';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { TrendingUp, AlertCircle } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';

export function Login() {
  const { login, isLoading, error } = useAuthStore();
  const [searchParams] = useSearchParams();
  const isExpired = searchParams.get('expired') === 'true';

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--background)]">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="flex justify-center mb-4">
            <div className="p-4 rounded-full bg-[var(--primary)]/10">
              <TrendingUp className="h-12 w-12 text-[var(--primary)]" />
            </div>
          </div>
          <CardTitle className="text-2xl">Trading System v2.0</CardTitle>
          <CardDescription>
            Multi-Agent Algorithmic Trading for Indian Markets
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {isExpired && (
            <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-600 dark:text-amber-400 text-sm flex items-center gap-2">
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              <span>Your session has expired. Please login again.</span>
            </div>
          )}
          
          {error && (
            <div className="p-3 rounded-lg bg-[var(--destructive)]/10 text-[var(--destructive)] text-sm">
              {error}
            </div>
          )}
          
          <Button 
            className="w-full" 
            size="lg"
            onClick={login}
            disabled={isLoading}
          >
            {isLoading ? 'Connecting...' : 'Login with Kite'}
          </Button>
          
          <p className="text-xs text-center text-[var(--muted-foreground)]">
            Powered by KiteConnect API
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
