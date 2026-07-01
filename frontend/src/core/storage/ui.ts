import { STORAGE_KEYS } from './keys';

export type UiThemeMode = 'cafetalero' | 'light' | 'dark' | 'system';
export type UiDensityMode = 'comfortable' | 'compact';

export type StoredUiPrefs = {
  theme: UiThemeMode;
  density: UiDensityMode;
};

function isTheme(x: string | null): x is UiThemeMode {
  return x === 'cafetalero' || x === 'light' || x === 'dark' || x === 'system';
}

function isDensity(x: string | null): x is UiDensityMode {
  return x === 'comfortable' || x === 'compact';
}

export function readUiPrefs(): StoredUiPrefs {
  const t = localStorage.getItem(STORAGE_KEYS.UI_THEME);
  const d = localStorage.getItem(STORAGE_KEYS.UI_DENSITY);

  return {
    theme: isTheme(t) ? t : 'cafetalero',
    density: isDensity(d) ? d : 'comfortable',
  };
}

export function writeUiPrefs(prefs: StoredUiPrefs) {
  localStorage.setItem(STORAGE_KEYS.UI_THEME, prefs.theme);
  localStorage.setItem(STORAGE_KEYS.UI_DENSITY, prefs.density);
}

export function clearUiPrefs() {
  localStorage.removeItem(STORAGE_KEYS.UI_THEME);
  localStorage.removeItem(STORAGE_KEYS.UI_DENSITY);
}
