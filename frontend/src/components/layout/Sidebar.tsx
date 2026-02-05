import { NavLink } from 'react-router-dom';
import { 
  LayoutDashboard, 
  Briefcase, 
  Layers,
  FolderOpen,
  ClipboardList, 
  FlaskConical, 
  Settings,
  TrendingUp
} from 'lucide-react';
import { cn } from '@/lib/utils';

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/dashboard/positions', icon: Briefcase, label: 'Positions' },
  { to: '/dashboard/strategies', icon: Layers, label: 'Strategies' },
  { to: '/dashboard/portfolios', icon: FolderOpen, label: 'Portfolios' },
  { to: '/dashboard/orders', icon: ClipboardList, label: 'Orders' },
  { to: '/dashboard/backtest', icon: FlaskConical, label: 'Backtest' },
  { to: '/dashboard/settings', icon: Settings, label: 'Settings' },
];

export function Sidebar() {
  return (
    <aside className="w-64 border-r border-[var(--border)] bg-[var(--card)] h-screen sticky top-0">
      <div className="p-6 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-8 w-8 text-[var(--primary)]" />
          <div>
            <h1 className="font-bold text-lg">Trading System</h1>
            <p className="text-xs text-[var(--muted-foreground)]">v2.0</p>
          </div>
        </div>
      </div>
      
      <nav className="p-4 space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/dashboard'}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors",
                isActive
                  ? "bg-[var(--primary)] text-white"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
              )
            }
          >
            <item.icon className="h-5 w-5" />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
