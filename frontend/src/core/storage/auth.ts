import { STORAGE_KEYS } from './keys';

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
export function readTokens(): StoredTokens {
  return {
    access: localStorage.getItem(STORAGE_KEYS.AUTH_ACCESS),
    refresh: localStorage.getItem(STORAGE_KEYS.AUTH_REFRESH),
  };
}

export function writeTokens(access: string | null, refresh: string | null): void {
  if (access) localStorage.setItem(STORAGE_KEYS.AUTH_ACCESS, access);
  if (refresh) localStorage.setItem(STORAGE_KEYS.AUTH_REFRESH, refresh);
}

export function clearTokens(): void {
  localStorage.removeItem(STORAGE_KEYS.AUTH_ACCESS);
  localStorage.removeItem(STORAGE_KEYS.AUTH_REFRESH);
}
