import { useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuthStore } from '@/stores/authStore';

export function Callback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { handleCallback, error, isAuthenticated } = useAuthStore();
  const hasCalledRef = useRef(false);

  useEffect(() => {
    if (hasCalledRef.current) return;
    
    const requestToken = searchParams.get('request_token');
    
    if (requestToken) {
      hasCalledRef.current = true;
      handleCallback(requestToken).then(() => {
        navigate('/dashboard');
      });
    } else {
      navigate('/');
    }
  }, [searchParams, handleCallback, navigate]);

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard');
    }
  }, [isAuthenticated, navigate]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-[var(--destructive)]">{error}</p>
          <a href="/" className="text-[var(--primary)] underline mt-4 block">
            Try again
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin h-8 w-8 border-4 border-[var(--primary)] border-t-transparent rounded-full mx-auto"></div>
        <p className="mt-4 text-[var(--muted-foreground)]">Authenticating...</p>
      </div>
    </div>
  );
}
