import { useState } from 'react';
import { useTradingStore } from '@/stores/tradingStore';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Play, Square, AlertTriangle } from 'lucide-react';

export function QuickActions() {
  const { status, startTrading, stopTrading, flattenAll, isLoading } = useTradingStore();
  const [mode, setMode] = useState<'paper' | 'live'>('paper');

  const isRunning = status?.running ?? false;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Quick Actions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Button
            variant={mode === 'paper' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setMode('paper')}
            disabled={isRunning}
          >
            Paper
          </Button>
          <Button
            variant={mode === 'live' ? 'destructive' : 'outline'}
            size="sm"
            onClick={() => setMode('live')}
            disabled={isRunning}
          >
            Live
          </Button>
        </div>

        <div className="flex gap-2">
          {!isRunning ? (
            <Button 
              className="flex-1" 
              onClick={() => startTrading(mode)}
              disabled={isLoading}
            >
              <Play className="h-4 w-4 mr-2" />
              Start Trading
            </Button>
          ) : (
            <Button 
              variant="secondary" 
              className="flex-1" 
              onClick={stopTrading}
              disabled={isLoading}
            >
              <Square className="h-4 w-4 mr-2" />
              Stop Trading
            </Button>
          )}
        </div>

        <Button 
          variant="destructive" 
          className="w-full" 
          onClick={() => flattenAll('MANUAL')}
          disabled={isLoading || !isRunning}
        >
          <AlertTriangle className="h-4 w-4 mr-2" />
          Flatten All Positions
        </Button>
      </CardContent>
    </Card>
  );
}
