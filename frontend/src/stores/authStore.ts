import { create } from 'zustand';
import type { AuthState } from '@/types';
import { authApi } from '@/services/api';

interface AuthStore extends AuthState {
  login: () => Promise<void>;
  logout: () => Promise<void>;
  handleCallback: (requestToken: string) => Promise<void>;
  checkAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthStore>((set) => ({
  isAuthenticated: false,
  user: null,
  isLoading: true,
  error: null,

  login: async () => {
    try {
      const response = await authApi.getLoginUrl();
      window.location.href = response.data.url;
    } catch (error) {
      set({ error: 'Failed to get login URL' });
    }
  },

  logout: async () => {
    try {
      await authApi.logout();
      set({ isAuthenticated: false, user: null });
      // Redirect to login page
      window.location.href = '/';
    } catch (error) {
      console.error('Logout failed:', error);
      // Still clear local state even if API fails
      set({ isAuthenticated: false, user: null });
      window.location.href = '/';
    }
  },

  handleCallback: async (requestToken: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await authApi.callback(requestToken);
      set({ 
        isAuthenticated: true, 
        user: response.data.user, 
        isLoading: false 
      });
    } catch (error) {
      set({ 
        error: 'Authentication failed', 
        isLoading: false 
      });
    }
  },

  checkAuth: async () => {
    set({ isLoading: true });
    try {
      const response = await authApi.me();
      set({ 
        isAuthenticated: true, 
        user: response.data, 
        isLoading: false 
      });
    } catch {
      set({ 
        isAuthenticated: false, 
        user: null, 
        isLoading: false 
      });
    }
  },
}));
