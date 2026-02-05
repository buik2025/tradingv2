import { useEffect, useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { accountApi, type AccountSummary as AccountSummaryType } from '@/services/api';
import { formatCurrency } from '@/lib/utils';
import { Wallet, TrendingUp, TrendingDown, PiggyBank } from 'lucide-react';

interface AccountSummaryProps {
  refreshTrigger?: number;
}

export function AccountSummary({ refreshTrigger }: AccountSummaryProps) {
  const [account, setAccount] = useState<AccountSummaryType | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAccountSummary();
  }, [refreshTrigger]);

  const fetchAccountSummary = async () => {
    try {
      const response = await accountApi.getSummary();
      setAccount(response.data);
    } catch (error) {
      console.error('Failed to fetch account summary:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading || !account) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i} className="animate-pulse">
            <CardContent className="p-4">
              <div className="h-4 bg-[var(--muted)] rounded w-20 mb-2"></div>
              <div className="h-6 bg-[var(--muted)] rounded w-28"></div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const utilizationColor = account.margin_utilization_pct > 80 
    ? 'text-[var(--loss)]' 
    : account.margin_utilization_pct > 50 
      ? 'text-[var(--warning)]' 
      : 'text-[var(--profit)]';

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 text-[var(--muted-foreground)] text-sm mb-1">
            <Wallet className="h-4 w-4" />
            Total Margin
          </div>
          <div className="text-xl font-bold">{formatCurrency(account.total_margin)}</div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 text-[var(--muted-foreground)] text-sm mb-1">
            <TrendingDown className="h-4 w-4" />
            Used Margin
          </div>
          <div className="text-xl font-bold">{formatCurrency(account.used_margin)}</div>
          <div className={`text-xs ${utilizationColor}`}>
            {account.margin_utilization_pct}% utilized
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 text-[var(--muted-foreground)] text-sm mb-1">
            <TrendingUp className="h-4 w-4" />
            Available Margin
          </div>
          <div className="text-xl font-bold text-[var(--profit)]">
            {formatCurrency(account.available_margin)}
          </div>
          <div className="text-xs text-[var(--muted-foreground)]">
            {(100 - account.margin_utilization_pct).toFixed(2)}% available
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 text-[var(--muted-foreground)] text-sm mb-1">
            <PiggyBank className="h-4 w-4" />
            Cash Available
          </div>
          <div className="text-xl font-bold">{formatCurrency(account.cash_available)}</div>
          {account.collateral > 0 && (
            <div className="text-xs text-[var(--muted-foreground)]">
              +{formatCurrency(account.collateral)} collateral
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
