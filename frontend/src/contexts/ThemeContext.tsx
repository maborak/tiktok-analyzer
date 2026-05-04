import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';

export type ThemePreference = 'light' | 'dark' | 'system';
type ResolvedTheme = 'light' | 'dark';

interface ThemeContextType {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (pref: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const STORAGE_KEY = 'theme-preference';

function getSystemTheme(): ResolvedTheme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function resolveTheme(pref: ThemePreference): ResolvedTheme {
  if (pref === 'system') return getSystemTheme();
  return pref;
}

function applyTheme(theme: ResolvedTheme) {
  document.documentElement.setAttribute('data-theme', theme);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
    return 'light';
  });

  const resolved = resolveTheme(preference);

  const setPreference = useCallback((pref: ThemePreference) => {
    localStorage.setItem(STORAGE_KEY, pref);
    setPreferenceState(pref);
    applyTheme(resolveTheme(pref));
    // Toggle may re-enable transitions if a theme switch happens early
    document.documentElement.classList.remove('no-transition');
  }, []);

  useEffect(() => {
    applyTheme(resolved);

    // Remove the no-transition class after the first paint so theme
    // switches after mount animate normally. The class is initially set
    // by the FOUC script in index.html to suppress the cascading
    // transition on load.
    requestAnimationFrame(() => {
      document.documentElement.classList.remove('no-transition');
    });

    // When following the OS preference, watch for changes and re-apply.
    if (preference === 'system') {
      const mql = window.matchMedia('(prefers-color-scheme: dark)');
      const handler = () => applyTheme(getSystemTheme());
      mql.addEventListener('change', handler);
      return () => mql.removeEventListener('change', handler);
    }
  }, [preference, resolved]);

  return (
    <ThemeContext.Provider value={{ preference, resolved, setPreference }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextType {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
