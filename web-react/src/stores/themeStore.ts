import { create } from 'zustand';

export type ThemePreference = 'light' | 'auto' | 'dark';
export const THEME_STORAGE_KEY = 'claw-theme';
const SYSTEM_THEME_QUERY = '(prefers-color-scheme: dark)';

function parsePreference(value: string | null): ThemePreference {
  return value === 'light' || value === 'dark' ? value : 'auto';
}

function readPreference(): ThemePreference {
  try {
    return parsePreference(localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return 'auto';
  }
}

function applyTheme(preference: ThemePreference) {
  document.documentElement.dataset.theme = preference === 'auto'
    ? (window.matchMedia?.(SYSTEM_THEME_QUERY).matches ? 'dark' : 'light')
    : preference;
}

export const useThemeStore = create<{
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
}>((set) => ({
  preference: readPreference(),
  setPreference: (preference) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, preference);
    } catch {
      // Keep switching available when the browser blocks local storage.
    }
    applyTheme(preference);
    set({ preference });
  },
}));

export function initializeTheme() {
  const preference = readPreference();
  useThemeStore.setState({ preference });
  applyTheme(preference);

  const media = window.matchMedia?.(SYSTEM_THEME_QUERY);
  const onSystemChange = () => applyTheme(useThemeStore.getState().preference);
  const onStorage = (event: StorageEvent) => {
    if (event.storageArea && event.storageArea !== localStorage) return;
    if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
    const next = parsePreference(event.newValue);
    applyTheme(next);
    useThemeStore.setState({ preference: next });
  };
  media?.addEventListener('change', onSystemChange);
  window.addEventListener('storage', onStorage);
  return () => {
    media?.removeEventListener('change', onSystemChange);
    window.removeEventListener('storage', onStorage);
  };
}
