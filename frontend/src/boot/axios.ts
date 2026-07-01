import { boot } from 'quasar/wrappers';
import { Notify } from 'quasar';
import type {
  AxiosError,
  AxiosInstance,
  AxiosRequestConfig,
  InternalAxiosRequestConfig,
} from 'axios';
import axios from 'axios';
import { useAuthStore } from 'src/stores/auth.store';
import { useContextStore } from 'src/stores/context.store';
import { forgetDevice } from 'src/core/device';
import { isNativeApp } from 'src/core/platform';
import { getApiBaseUrl } from 'src/core/storage/server';
import { readTokens } from 'src/core/storage/auth';

declare module 'axios' {
  export interface AxiosRequestConfig {
    _retry?: boolean;
    _skipAuthRefresh?: boolean;
  }
}

declare module 'vue' {
  interface ComponentCustomProperties {
    $axios: AxiosInstance;
    $api: AxiosInstance;
  }
}

// App nativa (Capacitor) → auth Bearer contra una URL absoluta configurable (LAN o internet).
// Web → cookie HttpOnly mismo-origen (`/api`).
const NATIVE = isNativeApp();
const AUTH_TRANSPORT: 'cookie' | 'header' = NATIVE ? 'header' : 'cookie';
const CSRF_COOKIE_NAME = import.meta.env.VITE_CSRF_COOKIE_NAME || 'nt_csrf';
const RAW_API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api';

function resolveApiBaseUrl(raw: string): string {
  // Nativo: la base es el servidor configurado por el usuario (dominio de prod o LAN), absoluto.
  // En cada request el interceptor la relee, así cambiar de servidor surte efecto al instante.
  if (NATIVE) return getApiBaseUrl();

  const normalized = (raw || '').trim() || '/api';

  // Con auth por cookie (web), priorizamos same-origin para evitar drift de sesión.
  if (typeof window === 'undefined') return normalized;
  if (!/^https?:\/\//i.test(normalized)) return normalized;

  try {
    const parsed = new URL(normalized);
    if (parsed.origin !== window.location.origin) {
      console.warn(
        `[auth-cookie] VITE_API_BASE_URL cross-origin (${parsed.origin}) detectado; se fuerza /api para sesión estable.`,
      );
      return '/api';
    }
  } catch {
    return '/api';
  }

  return normalized;
}

const API_BASE_URL = resolveApiBaseUrl(RAW_API_BASE_URL);

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp('(^|;\\s*)' + name + '=([^;]*)'));
  const value = m?.[2];
  return value ? decodeURIComponent(value) : null;
}

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 25_000,
  withCredentials: AUTH_TRANSPORT === 'cookie',
});

export const authApi = axios.create({
  baseURL: API_BASE_URL,
  timeout: 25_000,
  withCredentials: AUTH_TRANSPORT === 'cookie',
});

// Endpoints exentos de contexto (no requieren X-Company-Id)
const CONTEXT_EXEMPT_PREFIXES = [
  '/auth/login/',
  '/auth/refresh/',
  '/auth/logout/',
  '/auth/me/',
  '/auth/me/acl/',
  '/auth/bootstrap/',
  '/auth/password/',
  '/sync/enroll/',
  '/sync/batch/',
  '/schema/',
];

const AUTH_REFRESH_EXEMPT_PREFIXES = [
  '/auth/login/',
  '/auth/refresh/',
  '/auth/logout/',
  '/auth/bootstrap/',
  '/sync/enroll/',
  '/sync/batch/',
];

function getPath(config: AxiosRequestConfig): string {
  const url = config.url ?? '';
  // Si url es relativa ("/auth/login/"), esto ya sirve.
  // Si fuera absoluta, igual soporta parsing.
  try {
    const full = new URL(url, config.baseURL);
    return full.pathname.replace(/\/api\/?/, '/'); // normaliza si aparece /api/
  } catch {
    return url;
  }
}

function isContextExempt(path: string): boolean {
  return CONTEXT_EXEMPT_PREFIXES.some((p) => path.startsWith(p));
}

function isAuthRefreshExempt(path: string): boolean {
  return AUTH_REFRESH_EXEMPT_PREFIXES.some((p) => path.startsWith(p));
}

// Decoración nativa (Capacitor): base configurable + transporte Bearer. DEBE aplicarse a AMBAS
// instancias (api y authApi). Si authApi no la lleva, el login NO manda `X-Auth-Transport: header`
// → el backend responde en modo cookie ({ok:true}, sin tokens en el body) → la app no guarda
// sesión → al pedir /me da 401 → refresh sin token → "Sin refresh token local".
function decorateNativeRequest(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  // Servidor configurable: se relee la base por request → cambiar de LAN a internet surte efecto al instante.
  config.baseURL = getApiBaseUrl();
  config.headers = config.headers ?? {};
  config.headers['X-Auth-Transport'] = 'header';
  // Adjunta el access token (login lo ignora; refresh lee el refresh del body → inocuo).
  const { access } = readTokens();
  if (access) config.headers['Authorization'] = `Bearer ${access}`;
  return config;
}

export default boot(({ app, router }) => {
  app.config.globalProperties.$axios = axios;
  app.config.globalProperties.$api = api;

  if (
    AUTH_TRANSPORT === 'cookie' &&
    typeof window !== 'undefined' &&
    window.location.protocol !== 'https:' &&
    !['localhost', '127.0.0.1'].includes(window.location.hostname)
  ) {
    console.warn(
      '[auth-cookie] Contexto no HTTPS detectado para sesión autenticada. En LAN/prod se requiere HTTPS para estabilidad y seguridad.',
    );
  }

  // authApi (login/refresh/logout/2fa) necesita la MISMA decoración nativa que api: sin ella, el
  // login no manda X-Auth-Transport y el backend responde en modo cookie (sin tokens en el body).
  if (NATIVE) {
    authApi.interceptors.request.use((config) => decorateNativeRequest(config));
  }

  api.interceptors.request.use((config) => {
    const auth = useAuthStore();
    const ctx = useContextStore();

    auth.initFromStorage();
    ctx.initFromStorage();

    const path = getPath(config);
    if (isAuthRefreshExempt(path)) {
      config._skipAuthRefresh = true;
    }

    if (NATIVE) decorateNativeRequest(config);

    if (AUTH_TRANSPORT === 'cookie') {
      const csrf = readCookie(CSRF_COOKIE_NAME);
      if (csrf) {
        config.headers = config.headers ?? {};
        config.headers['X-CSRF-Token'] = csrf;
      }
    }

    // Identidad del dispositivo enrolado → la bitácora registra desde QUÉ aparato
    // se hizo cada acción (el backend solo lo acepta si el Device está ACTIVO).
    const deviceRaw = localStorage.getItem('nt_device_identity');
    if (deviceRaw) {
      try {
        const deviceId = (JSON.parse(deviceRaw) as { device_id?: string }).device_id;
        if (deviceId) {
          config.headers = config.headers ?? {};
          config.headers['X-Device-Id'] = deviceId;
        }
      } catch {
        /* identidad corrupta: se ignora */
      }
    }

    // Context headers (solo si no es endpoint exento)
    if (!isContextExempt(path)) {
      config.headers = config.headers ?? {};
      // Si el llamador YA fijó X-Company-Id (p. ej. el tablero consultando OTRA
      // empresa del holding), lo respetamos tal cual y NO le inyectamos la
      // sucursal activa (que pertenece a la empresa activa, no a la consultada).
      if (!config.headers['X-Company-Id']) {
        if (!ctx.activeCompanyId) {
          // Dejar que el router guard fuerce /select-context; aquí devolvemos error claro.
          // También evita llamadas operativas “sin company”.
          const err = new Error('ContextMissing: X-Company-Id is required');
          return Promise.reject(err);
        }
        config.headers['X-Company-Id'] = ctx.activeCompanyId;
        if (ctx.activeBranchId) config.headers['X-Branch-Id'] = ctx.activeBranchId;
      }
    }

    return config;
  });

  api.interceptors.response.use(
    (resp) => resp,
    async (error: AxiosError) => {
      const auth = useAuthStore();
      const original = error.config as AxiosRequestConfig | undefined;

      // Si no hay config, no hay nada que reintentar
      if (!original) return Promise.reject(error);

      const status = error.response?.status;
      const path = getPath(original);

      // 401: intentar refresh una vez, y reintentar request
      if (status === 401 && isAuthRefreshExempt(path)) {
        return Promise.reject(error);
      }

      if (status === 401 && !original._retry && !original._skipAuthRefresh) {
        original._retry = true;

        try {
          await auth.refresh();

          // Reintentar request (cookies ya viajan automaticamente)
          return api.request(original);
        } catch (e) {
          // Refresh falló → logout duro y llevar a login
          auth.hardClearLocal();
          await router.replace('/login');
          const reason = e instanceof Error ? e : new Error(String(e));
          return Promise.reject(reason);
        }
      }

      // Kill-switch del aparato: este dispositivo fue REVOCADO. Cerramos sesión, olvidamos
      // la identidad local y mandamos a login con un mensaje claro (antes del 403 genérico).
      const errCode = (error.response?.data as { error?: { code?: string } } | undefined)?.error
        ?.code;
      if (status === 403 && errCode === 'DEVICE_REVOKED') {
        forgetDevice();
        auth.hardClearLocal();
        Notify.create({
          type: 'negative',
          message: 'Este dispositivo fue revocado. Contactá al administrador.',
        });
        await router.replace('/login');
        return Promise.reject(error);
      }

      // 403: mandamos a /403 (sin romper sesión)
      if (status === 403) {
        await router.replace('/403');
      }

      return Promise.reject(error);
    },
  );
});

export { axios };
