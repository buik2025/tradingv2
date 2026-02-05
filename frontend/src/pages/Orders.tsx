import { useEffect } from 'react';
import { useTradingStore } from '@/stores/tradingStore';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { formatCurrency } from '@/lib/utils';

const statusVariant: Record<string, 'default' | 'success' | 'destructive' | 'warning' | 'secondary'> = {
  PENDING: 'warning',
  COMPLETE: 'success',
  REJECTED: 'destructive',
  CANCELLED: 'secondary',
};

export function Orders() {
  const { orders, fetchOrders } = useTradingStore();

  useEffect(() => {
    fetchOrders();
    const interval = setInterval(fetchOrders, 5000);
    return () => clearInterval(interval);
  }, [fetchOrders]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Orders</h1>
        <p className="text-[var(--muted-foreground)]">View your order history</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Today's Orders</CardTitle>
        </CardHeader>
        <CardContent>
          {orders.length === 0 ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              No orders today
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    <th className="text-left py-3 px-4 text-sm font-medium text-[var(--muted-foreground)]">Time</th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-[var(--muted-foreground)]">Symbol</th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-[var(--muted-foreground)]">Type</th>
                    <th className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)]">Qty</th>
                    <th className="text-right py-3 px-4 text-sm font-medium text-[var(--muted-foreground)]">Price</th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-[var(--muted-foreground)]">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((order) => (
                    <tr key={order.order_id} className="border-b border-[var(--border)] hover:bg-[var(--muted)]">
                      <td className="py-3 px-4 text-sm text-[var(--muted-foreground)]">
                        {new Date(order.order_timestamp).toLocaleTimeString()}
                      </td>
                      <td className="py-3 px-4 font-medium">{order.tradingsymbol}</td>
                      <td className="py-3 px-4">
                        <Badge variant={order.transaction_type === 'BUY' ? 'success' : 'destructive'}>
                          {order.transaction_type}
                        </Badge>
                      </td>
                      <td className="py-3 px-4 text-right">{order.quantity}</td>
                      <td className="py-3 px-4 text-right">{formatCurrency(order.average_price || order.price)}</td>
                      <td className="py-3 px-4">
                        <Badge variant={statusVariant[order.status] || 'default'}>
                          {order.status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
