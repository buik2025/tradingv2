import { useState, useEffect, useCallback } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { useTradingStore } from '@/stores/tradingStore';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { LogOut, User, ChevronDown, TrendingUp, TrendingDown, Settings2, Plus, X } from 'lucide-react';
import api from '@/services/api';

interface IndexQuote {
  symbol: string;
  name: string;
  last_price: number;
  change: number;
  change_pct: number;
  market_open?: boolean;
  last_trade_time?: string;
}

// Default indices to track
const DEFAULT_INDICES = [
  { symbol: 'NSE:NIFTY 50', name: 'NIFTY 50' },
  { symbol: 'BSE:SENSEX', name: 'SENSEX' },
  { symbol: 'NSE:NIFTY BANK', name: 'BANK NIFTY' },
];

// Available indices for selection
const AVAILABLE_INDICES = [
  { symbol: 'NSE:NIFTY 50', name: 'NIFTY 50' },
  { symbol: 'BSE:SENSEX', name: 'SENSEX' },
  { symbol: 'NSE:NIFTY BANK', name: 'BANK NIFTY' },
  { symbol: 'NSE:NIFTY FIN SERVICE', name: 'NIFTY FIN' },
  { symbol: 'NSE:NIFTY IT', name: 'NIFTY IT' },
  { symbol: 'NSE:NIFTY MIDCAP 50', name: 'MIDCAP 50' },
  { symbol: 'NSE:INDIA VIX', name: 'INDIA VIX' },
];

export function Header() {
  const { user, logout } = useAuthStore();
  const { status } = useTradingStore();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showIndexSettings, setShowIndexSettings] = useState(false);
  const [selectedIndices, setSelectedIndices] = useState<{ symbol: string; name: string }[]>(() => {
    const saved = localStorage.getItem('selectedIndices');
    return saved ? JSON.parse(saved) : DEFAULT_INDICES;
  });
  const [indexQuotes, setIndexQuotes] = useState<IndexQuote[]>([]);

  useEffect(() => {
    localStorage.setItem('selectedIndices', JSON.stringify(selectedIndices));
  }, [selectedIndices]);

  const fetchIndices = useCallback(async () => {
    if (selectedIndices.length === 0) return;
    
    try {
      const symbols = selectedIndices.map(i => i.symbol);
      console.log('Fetching indices:', symbols);
      const response = await api.post('/indices/quotes', { symbols });
      console.log('Indices response:', response.data);
      if (response.data && response.data.quotes) {
        setIndexQuotes(response.data.quotes);
      }
    } catch (error) {
      console.error('Failed to fetch indices:', error);
    }
  }, [selectedIndices]);

  useEffect(() => {
    fetchIndices();
    const interval = setInterval(fetchIndices, 2000); // Update every 2 seconds for more responsive ticker
    return () => clearInterval(interval);
  }, [fetchIndices]);

  const handleLogout = async () => {
    setShowUserMenu(false);
    await logout();
  };

  const addIndex = (index: { symbol: string; name: string }) => {
    if (!selectedIndices.find(i => i.symbol === index.symbol)) {
      setSelectedIndices([...selectedIndices, index]);
    }
  };

  const removeIndex = (symbol: string) => {
    setSelectedIndices(selectedIndices.filter(i => i.symbol !== symbol));
  };

  const formatPrice = (price: number) => price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const formatChangePct = (pct: number) => (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';

  return (
    <header className="h-14 border-b border-[var(--border)] bg-[var(--card)] flex items-center sticky top-0 z-10">
      {/* Static Indices Display */}
      <div className="flex items-center gap-4 px-4 overflow-x-auto scrollbar-hide">
        {indexQuotes.length === 0 ? (
          <span className="text-sm text-[var(--muted-foreground)]">Loading indices...</span>
        ) : (
          indexQuotes.map((quote, idx) => (
            <div key={quote.symbol} className="flex items-center gap-1.5 text-xs shrink-0">
              <span className="font-medium text-[var(--muted-foreground)]">{quote.name}</span>
              <span className={quote.change >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}>
                {formatPrice(quote.last_price)}
              </span>
              <span className={quote.change >= 0 ? 'text-[var(--profit)]' : 'text-[var(--loss)]'}>
                {formatChangePct(quote.change_pct)}
              </span>
              {quote.change >= 0 ? (
                <TrendingUp className="h-3 w-3 text-[var(--profit)]" />
              ) : (
                <TrendingDown className="h-3 w-3 text-[var(--loss)]" />
              )}
              {quote.market_open === false && (
                <span className="text-[9px] text-[var(--muted-foreground)] bg-[var(--muted)] px-1 rounded">CLOSED</span>
              )}
              {idx < indexQuotes.length - 1 && <span className="text-[var(--border)] mx-1">|</span>}
            </div>
          ))
        )}
      </div>
      
      <div className="flex-1" /> {/* Spacer */}

      {/* Right side controls */}
      <div className="flex items-center gap-4 px-4 shrink-0">
        {/* Index Settings */}
        <div className="relative">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowIndexSettings(!showIndexSettings)}
            className="h-8 w-8 p-0"
          >
            <Settings2 className="h-4 w-4" />
          </Button>
          
          {showIndexSettings && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowIndexSettings(false)} />
              <div className="absolute right-0 top-full mt-1 w-64 bg-[var(--card)] border border-[var(--border)] rounded-md shadow-lg z-20 p-3">
                <p className="text-xs font-medium text-[var(--muted-foreground)] mb-2">Selected Indices</p>
                <div className="space-y-1 mb-3">
                  {selectedIndices.map(idx => (
                    <div key={idx.symbol} className="flex items-center justify-between text-sm py-1 px-2 bg-[var(--muted)] rounded">
                      <span>{idx.name}</span>
                      <button onClick={() => removeIndex(idx.symbol)} className="text-[var(--muted-foreground)] hover:text-[var(--loss)]">
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
                <p className="text-xs font-medium text-[var(--muted-foreground)] mb-2">Add Index</p>
                <div className="space-y-1">
                  {AVAILABLE_INDICES.filter(a => !selectedIndices.find(s => s.symbol === a.symbol)).map(idx => (
                    <button
                      key={idx.symbol}
                      onClick={() => addIndex(idx)}
                      className="flex items-center gap-2 text-sm py-1 px-2 w-full hover:bg-[var(--muted)] rounded text-left"
                    >
                      <Plus className="h-3 w-3" />
                      {idx.name}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Status Badges */}
        <div className="flex items-center gap-2">
          {status && (
            <Badge 
              variant={status.mode === 'live' ? 'destructive' : status.mode === 'paper' ? 'warning' : 'secondary'}
            >
              {status.mode.toUpperCase()}
            </Badge>
          )}
          {status?.running && (
            <Badge variant="success">RUNNING</Badge>
          )}
        </div>

        {/* User Menu */}
        {user && (
          <div className="relative">
            <Button 
              variant="ghost" 
              className="flex items-center gap-2 text-sm"
              onClick={() => setShowUserMenu(!showUserMenu)}
            >
              <User className="h-4 w-4" />
              <span>{user.user_name}</span>
              <ChevronDown className="h-3 w-3" />
            </Button>
            
            {showUserMenu && (
              <>
                <div 
                  className="fixed inset-0 z-10" 
                  onClick={() => setShowUserMenu(false)}
                />
                <div className="absolute right-0 top-full mt-1 w-48 bg-[var(--card)] border border-[var(--border)] rounded-md shadow-lg z-20">
                  <div className="p-3 border-b border-[var(--border)]">
                    <p className="font-medium">{user.user_name}</p>
                    <p className="text-xs text-[var(--muted-foreground)]">{user.email}</p>
                    <p className="text-xs text-[var(--muted-foreground)]">ID: {user.user_id}</p>
                  </div>
                  <button
                    onClick={handleLogout}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-[var(--muted)] flex items-center gap-2 text-[var(--loss)]"
                  >
                    <LogOut className="h-4 w-4" />
                    Logout
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
