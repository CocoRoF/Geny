'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

// ────────────────────────────────────────────────────────────
// Types
// ────────────────────────────────────────────────────────────
export type Theme = 'light' | 'dark';

interface ThemeContextValue {
  /** The resolved theme actually applied (always 'light' | 'dark'). */
  theme: Theme;
  /** Set the theme explicitly. */
  setTheme: (t: Theme) => void;
}

const STORAGE_KEY = 'geny-theme-preference';

// ────────────────────────────────────────────────────────────
// Context
// ────────────────────────────────────────────────────────────
const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

// ────────────────────────────────────────────────────────────
// External store for useSyncExternalStore
// ────────────────────────────────────────────────────────────
const listeners = new Set<() => void>();

function emitChange() {
  listeners.forEach((l) => l());
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => { listeners.delete(callback); };
}

/** Client snapshot: read from localStorage, fallback to OS preference. */
function getSnapshot(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/** Server snapshot: always 'dark' — matches the FOUC script fallback. */
function getServerSnapshot(): Theme {
  return 'dark';
}

/** Apply the resolved theme class to <html> and set color-scheme. */
function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.remove('light', 'dark');
  root.classList.add(theme);
  root.style.colorScheme = theme;
}

// ────────────────────────────────────────────────────────────
// Provider
// ────────────────────────────────────────────────────────────
export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  // Keep <html> class in sync whenever theme changes
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    localStorage.setItem(STORAGE_KEY, t);
    applyTheme(t);
    emitChange(); // trigger useSyncExternalStore re-read
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, setTheme }),
    [theme, setTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

// ────────────────────────────────────────────────────────────
// Hook
// ────────────────────────────────────────────────────────────
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within <ThemeProvider>');
  return ctx;
}
