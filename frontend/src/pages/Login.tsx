import { useAuthStore } from '@/stores/authStore';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { TrendingUp } from 'lucide-react';

export function Login() {
  const { login, isLoading, error } = useAuthStore();

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
