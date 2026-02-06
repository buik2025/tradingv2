import { useState, useEffect } from 'react';
import { 
  User, 
  Key, 
  Shield, 
  Clock, 
  RefreshCw, 
  CheckCircle, 
  AlertCircle,
  ExternalLink,
  Copy,
  Eye,
  EyeOff
} from 'lucide-react';

interface CredentialsStatus {
  has_credentials: boolean;
  user_id?: string;
  user_name?: string;
  email?: string;
  broker?: string;
  created_at?: string;
  expires_at?: string;
  is_valid?: boolean;
  is_expired?: boolean;
  api_key_masked?: string;
  access_token_masked?: string;
  message?: string;
}

export function ProfilePage() {
  const [credentials, setCredentials] = useState<CredentialsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [showTokens, setShowTokens] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    fetchCredentials();
  }, []);

  const fetchCredentials = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v1/auth/credentials');
      if (response.ok) {
        const data = await response.json();
        setCredentials(data);
      }
    } catch (error) {
      console.error('Failed to fetch credentials:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleLogin = async () => {
    try {
      const response = await fetch('/api/v1/auth/login-url');
      if (response.ok) {
        const data = await response.json();
        window.location.href = data.url;
      }
    } catch (error) {
      console.error('Failed to get login URL:', error);
    }
  };

  const copyToClipboard = (text: string, field: string) => {
    navigator.clipboard.writeText(text);
    setCopied(field);
    setTimeout(() => setCopied(null), 2000);
  };

  const formatDateTime = (isoString: string | undefined) => {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleString('en-IN', {
      dateStyle: 'medium',
      timeStyle: 'short'
    });
  };

  const getTimeRemaining = (expiresAt: string | undefined) => {
    if (!expiresAt) return null;
    const expires = new Date(expiresAt);
    const now = new Date();
    const diff = expires.getTime() - now.getTime();
    
    if (diff <= 0) return 'Expired';
    
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    
    return `${hours}h ${minutes}m remaining`;
  };

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <RefreshCw className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <User className="w-7 h-7 text-blue-600" />
          Profile & Credentials
        </h1>
        <p className="text-gray-500 mt-1">
          Manage your Kite API credentials and authentication status
        </p>
      </div>

      {/* Credentials Status Card */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className={`px-6 py-4 border-b ${
          credentials?.has_credentials && !credentials?.is_expired
            ? 'bg-green-50 border-green-200'
            : 'bg-amber-50 border-amber-200'
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {credentials?.has_credentials && !credentials?.is_expired ? (
                <CheckCircle className="w-6 h-6 text-green-600" />
              ) : (
                <AlertCircle className="w-6 h-6 text-amber-600" />
              )}
              <div>
                <h2 className="font-semibold text-gray-900">
                  {credentials?.has_credentials 
                    ? (credentials?.is_expired ? 'Credentials Expired' : 'Credentials Active')
                    : 'No Credentials'}
                </h2>
                <p className="text-sm text-gray-600">
                  {credentials?.has_credentials
                    ? (credentials?.is_expired 
                        ? 'Please login again to refresh your access token'
                        : getTimeRemaining(credentials?.expires_at))
                    : 'Login with Kite to enable trading features'}
                </p>
              </div>
            </div>
            <button
              onClick={handleLogin}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors flex items-center gap-2"
            >
              <ExternalLink className="w-4 h-4" />
              {credentials?.has_credentials ? 'Refresh Login' : 'Login with Kite'}
            </button>
          </div>
        </div>

        {credentials?.has_credentials && (
          <div className="p-6 space-y-6">
            {/* User Info */}
            <div>
              <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">
                User Information
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-gray-50 rounded-lg p-4">
                  <div className="text-sm text-gray-500">User ID</div>
                  <div className="font-medium text-gray-900">{credentials.user_id || '-'}</div>
                </div>
                <div className="bg-gray-50 rounded-lg p-4">
                  <div className="text-sm text-gray-500">User Name</div>
                  <div className="font-medium text-gray-900">{credentials.user_name || '-'}</div>
                </div>
                <div className="bg-gray-50 rounded-lg p-4">
                  <div className="text-sm text-gray-500">Email</div>
                  <div className="font-medium text-gray-900">{credentials.email || '-'}</div>
                </div>
                <div className="bg-gray-50 rounded-lg p-4">
                  <div className="text-sm text-gray-500">Broker</div>
                  <div className="font-medium text-gray-900">{credentials.broker || 'ZERODHA'}</div>
                </div>
              </div>
            </div>

            {/* Credentials Info */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wider">
                  API Credentials
                </h3>
                <button
                  onClick={() => setShowTokens(!showTokens)}
                  className="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1"
                >
                  {showTokens ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  {showTokens ? 'Hide' : 'Show'} Details
                </button>
              </div>
              <div className="space-y-3">
                <div className="bg-gray-50 rounded-lg p-4 flex items-center justify-between">
                  <div>
                    <div className="text-sm text-gray-500 flex items-center gap-2">
                      <Key className="w-4 h-4" />
                      API Key
                    </div>
                    <div className="font-mono text-gray-900">
                      {showTokens ? credentials.api_key_masked : '••••••••'}
                    </div>
                  </div>
                  <button
                    onClick={() => copyToClipboard(credentials.api_key_masked || '', 'api_key')}
                    className="p-2 text-gray-400 hover:text-gray-600"
                    title="Copy"
                  >
                    {copied === 'api_key' ? (
                      <CheckCircle className="w-5 h-5 text-green-500" />
                    ) : (
                      <Copy className="w-5 h-5" />
                    )}
                  </button>
                </div>
                <div className="bg-gray-50 rounded-lg p-4 flex items-center justify-between">
                  <div>
                    <div className="text-sm text-gray-500 flex items-center gap-2">
                      <Shield className="w-4 h-4" />
                      Access Token
                    </div>
                    <div className="font-mono text-gray-900">
                      {showTokens ? credentials.access_token_masked : '••••••••••••'}
                    </div>
                  </div>
                  <button
                    onClick={() => copyToClipboard(credentials.access_token_masked || '', 'access_token')}
                    className="p-2 text-gray-400 hover:text-gray-600"
                    title="Copy"
                  >
                    {copied === 'access_token' ? (
                      <CheckCircle className="w-5 h-5 text-green-500" />
                    ) : (
                      <Copy className="w-5 h-5" />
                    )}
                  </button>
                </div>
              </div>
            </div>

            {/* Timestamps */}
            <div>
              <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">
                Session Timing
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-gray-50 rounded-lg p-4">
                  <div className="text-sm text-gray-500 flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    Login Time
                  </div>
                  <div className="font-medium text-gray-900">
                    {formatDateTime(credentials.created_at)}
                  </div>
                </div>
                <div className={`rounded-lg p-4 ${
                  credentials.is_expired ? 'bg-red-50' : 'bg-gray-50'
                }`}>
                  <div className="text-sm text-gray-500 flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    Expires At
                  </div>
                  <div className={`font-medium ${
                    credentials.is_expired ? 'text-red-600' : 'text-gray-900'
                  }`}>
                    {formatDateTime(credentials.expires_at)}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Info Box */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-6">
        <h3 className="font-semibold text-blue-900 mb-2">About Kite Credentials</h3>
        <ul className="text-sm text-blue-800 space-y-2">
          <li>• <strong>Access tokens expire daily at 6:00 AM IST</strong> - you need to login again each trading day</li>
          <li>• Credentials are stored securely in the database and used by background scripts (like the options collector)</li>
          <li>• The options data collector will automatically use these credentials when running</li>
          <li>• If credentials expire, the collector will fail until you login again</li>
        </ul>
      </div>

      {/* Refresh Button */}
      <div className="flex justify-end">
        <button
          onClick={fetchCredentials}
          className="flex items-center gap-2 px-4 py-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh Status
        </button>
      </div>
    </div>
  );
}
