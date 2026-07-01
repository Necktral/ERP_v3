/**
 * Configuración del servidor para la app NATIVA (Capacitor) — offline-first, LAN + internet.
 *
 * La APK está empacada (sin `server.url`): la UI vive en el dispositivo y habla con el backend
 * por una URL ABSOLUTA. El dueño eligió "Ambos": por defecto la app sincroniza contra el dominio
 * de producción (`https://wiscontext-sync.org`, esta PC vía Cloudflare Tunnel) y puede cambiar a un
 * servidor de LAN (p. ej. `http://192.168.1.13:8000`) cuando esté en la base. Se recuerda el último
 * que funcionó. En WEB nada de esto aplica (axios usa `/api` mismo-origen).
 */
import { STORAGE_KEYS } from './keys';

/** Origen de producción por defecto (sin `/api`). */
export const DEFAULT_SERVER_ORIGIN = 'https://wiscontext-sync.org';

/** Override de LAN sugerido (editable por el usuario en el selector). */
export const SUGGESTED_LAN_ORIGIN = 'http://192.168.1.13:8000';

/** Normaliza a `scheme://host[:port]` sin barra final ni sufijo `/api`. */
export function normalizeOrigin(input: string): string {
  let s = (input || '').trim();
  if (!s) return '';
  if (!/^https?:\/\//i.test(s)) s = 'https://' + s;
  return s.replace(/\/+$/, '').replace(/\/api$/i, '');
}

/** Origen configurado (o el de producción por defecto). */
export function getServerOrigin(): string {
  const saved = localStorage.getItem(STORAGE_KEYS.SERVER_ORIGIN);
  return normalizeOrigin(saved || '') || DEFAULT_SERVER_ORIGIN;
}

/** Base URL absoluta que consume axios en modo nativo: `<origen>/api`. */
export function getApiBaseUrl(): string {
  return getServerOrigin() + '/api';
}

export function setServerOrigin(origin: string): void {
  const n = normalizeOrigin(origin);
  if (n) localStorage.setItem(STORAGE_KEYS.SERVER_ORIGIN, n);
}

/** ¿el usuario fijó un servidor explícito? (false = se usa el default de producción). */
export function hasServerConfigured(): boolean {
  return !!localStorage.getItem(STORAGE_KEYS.SERVER_ORIGIN);
}

export function markServerOk(origin: string): void {
  localStorage.setItem(STORAGE_KEYS.SERVER_LAST_OK, normalizeOrigin(origin));
}

export function getLastOkOrigin(): string | null {
  return localStorage.getItem(STORAGE_KEYS.SERVER_LAST_OK);
}

/**
 * Health-probe: ¿este origen responde el bootstrap? Usa `fetch` directo (sin axios/interceptores)
 * para poder probar un servidor ANTES de fijarlo. No requiere auth.
 */
export async function probeServer(origin: string, timeoutMs = 6000): Promise<boolean> {
  const base = normalizeOrigin(origin);
  if (!base) return false;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(base + '/api/auth/bootstrap/status/', {
      method: 'GET',
      signal: ctrl.signal,
      // Sin credenciales: es un probe anónimo.
      credentials: 'omit',
    });
    return r.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
