import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { LucideIcon } from 'lucide-react';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  trend?: 'up' | 'down' | 'neutral';
  className?: string;
}

export function MetricCard({ title, value, subtitle, icon: Icon, trend, className }: MetricCardProps) {
  return (
    <Card className={cn("", className)}>
      <CardContent className="p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-[var(--muted-foreground)]">{title}</p>
            <p className={cn(
              "text-2xl font-bold mt-1",
              trend === 'up' && "text-[var(--profit)]",
              trend === 'down' && "text-[var(--loss)]"
            )}>
              {value}
            </p>
            {subtitle && (
              <p className="text-xs text-[var(--muted-foreground)] mt-1">{subtitle}</p>
            )}
          </div>
          <div className={cn(
            "p-3 rounded-lg",
            trend === 'up' && "bg-[var(--profit)]/10",
            trend === 'down' && "bg-[var(--loss)]/10",
            !trend && "bg-[var(--muted)]"
          )}>
            <Icon className={cn(
              "h-6 w-6",
              trend === 'up' && "text-[var(--profit)]",
              trend === 'down' && "text-[var(--loss)]",
              !trend && "text-[var(--muted-foreground)]"
            )} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
