import { STORAGE_KEYS } from './keys';
import { isNativeApp } from 'src/core/platform';

export type StoredTokens = {
  access: string | null;
  refresh: string | null;
};

/**
 * Tokens de sesión.
 *
 * WEB: la auth va por cookie HttpOnly mismo-origen → el frontend NO guarda JWT (estas funciones
 * devuelven `null`/no-op porque el login web responde `{ok:true}` sin tokens en el body).
 *
 * APP NATIVA (Capacitor): la auth va por Bearer (`X-Auth-Transport: header`) → el login responde
 * `{access, refresh}` y se persisten en el dispositivo (WebView sandbox propio de la app) para
 * operar offline y reanudar sesión entre arranques. Solo el código nativo de `axios.ts`/`auth.store`
 * llama a `writeTokens`/`readTokens`, así que en web nunca se escribe nada.
 */
let tokens: StoredTokens = { access: null, refresh: null };

async function secureStorage() {
  const { SecureStorage } = await import('@aparajita/capacitor-secure-storage');
  await SecureStorage.setKeyPrefix('necktral_');
  return SecureStorage;
}

/** Inicializa el espejo en memoria y migra una única vez los JWT legacy de localStorage. */
export async function initTokenStorage(): Promise<void> {
  if (!isNativeApp()) return;
  const storage = await secureStorage();
  const legacyAccess = localStorage.getItem(STORAGE_KEYS.AUTH_ACCESS);
  const legacyRefresh = localStorage.getItem(STORAGE_KEYS.AUTH_REFRESH);
  const storedAccess = await storage.getItem(STORAGE_KEYS.AUTH_ACCESS);
  const storedRefresh = await storage.getItem(STORAGE_KEYS.AUTH_REFRESH);
  tokens = {
    access: storedAccess ?? legacyAccess,
    refresh: storedRefresh ?? legacyRefresh,
  };
  if (!storedAccess && legacyAccess) await storage.setItem(STORAGE_KEYS.AUTH_ACCESS, legacyAccess);
  if (!storedRefresh && legacyRefresh) await storage.setItem(STORAGE_KEYS.AUTH_REFRESH, legacyRefresh);
  localStorage.removeItem(STORAGE_KEYS.AUTH_ACCESS);
  localStorage.removeItem(STORAGE_KEYS.AUTH_REFRESH);
}

/** Lectura síncrona del espejo cargado por el boot, necesaria para interceptores Axios. */
export function readTokens(): StoredTokens {
  return { ...tokens };
}

export async function writeTokens(access: string | null, refresh: string | null): Promise<void> {
  if (!isNativeApp()) return;
  tokens = { access, refresh };
  const storage = await secureStorage();
  if (access) await storage.setItem(STORAGE_KEYS.AUTH_ACCESS, access);
  else await storage.removeItem(STORAGE_KEYS.AUTH_ACCESS);
  if (refresh) await storage.setItem(STORAGE_KEYS.AUTH_REFRESH, refresh);
  else await storage.removeItem(STORAGE_KEYS.AUTH_REFRESH);
}

export async function clearTokens(): Promise<void> {
  tokens = { access: null, refresh: null };
  localStorage.removeItem(STORAGE_KEYS.AUTH_ACCESS);
  localStorage.removeItem(STORAGE_KEYS.AUTH_REFRESH);
  if (!isNativeApp()) return;
  const storage = await secureStorage();
  await Promise.all([
    storage.removeItem(STORAGE_KEYS.AUTH_ACCESS),
    storage.removeItem(STORAGE_KEYS.AUTH_REFRESH),
  ]);
}
