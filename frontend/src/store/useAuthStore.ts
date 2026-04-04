/**
 * Auth Store — Zustand store for authentication state.
 *
 * Manages: login status, current user, setup-required flag.
 * Provides actions: checkAuth, login, setup (first-time), logout.
 */

import { create } from 'zustand';
import { authApi, setToken, removeToken } from '@/lib/authApi';

interface AuthState {
  // State
  isAuthenticated: boolean;
  hasUsers: boolean;
  username: string | null;
  displayName: string | null;
  isLoading: boolean;
  /** True once the initial checkAuth() call completes */
  initialized: boolean;

  // Actions
  checkAuth: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  setup: (username: string, password: string, displayName?: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  hasUsers: false,
  username: null,
  displayName: null,
  isLoading: true,
  initialized: false,

  checkAuth: async () => {
    try {
      set({ isLoading: true });
      const status = await authApi.status();
      set({
        hasUsers: status.has_users,
        isAuthenticated: status.is_authenticated,
        username: status.username,
        displayName: status.display_name,
        isLoading: false,
        initialized: true,
      });
    } catch {
      // If backend is unreachable, assume no auth required (standalone mode)
      set({ isLoading: false, initialized: true });
    }
  },

  login: async (username, password) => {
    const res = await authApi.login({ username, password });
    setToken(res.token);
    set({
      isAuthenticated: true,
      username: res.username,
      displayName: res.display_name,
    });
  },

  setup: async (username, password, displayName) => {
    const res = await authApi.setup({ username, password, display_name: displayName });
    setToken(res.token);
    set({
      isAuthenticated: true,
      hasUsers: true,
      username: res.username,
      displayName: res.display_name,
    });
  },

  logout: async () => {
    try {
      await authApi.logout();
    } catch {
      // ignore — server might be down
    }
    removeToken();
    set({
      isAuthenticated: false,
      username: null,
      displayName: null,
    });
  },
}));
