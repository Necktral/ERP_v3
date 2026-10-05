/**
 * Estado de conexión con el servidor de recepción — fuente única.
 *
 * No basta `navigator.onLine` (dice si hay red, no si el SERVIDOR responde):
 * se hace un latido real a `/api/nomina/health/` (público) cada 25 s, con
 * verificación inmediata al recuperar red o volver a la app (móvil).
 * Notifica SOLO en las transiciones (conectado ↔ sin conexión).
 */
import { ref } from 'vue';
import { Notify } from 'quasar';
import { isNativeApp } from 'src/core/platform';
import { getServerOrigin } from 'src/core/storage/server';

const HEARTBEAT_MS = 25_000;
const PROBE_TIMEOUT_MS = 5_000;
const HEALTH_PATH = '/api/nomina/health/';

/**
 * URL de salud. En la APP NATIVA el origen del WebView es `https://localhost`, así que un path
 * relativo sondearía un servidor inexistente → `online` siempre falso → la cola SQLite nunca se
 * sincroniza. Por eso en nativo se sondea el servidor CONFIGURADO (absoluto), releído cada vez para
 * respetar el selector. En web sigue relativo (mismo origen, lo proxya el dev server/nginx).
 */
function healthUrl(): string {
  return isNativeApp() ? `${getServerOrigin()}${HEALTH_PATH}` : HEALTH_PATH;
}

const online = ref(true);
const lastCheckAt = ref<Date | null>(null);

let started = false;
let probing = false;

async function probeServer(): Promise<boolean> {
  if (typeof navigator !== 'undefined' && !navigator.onLine) return false;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
  try {
    const res = await fetch(healthUrl(), { signal: ctrl.signal, cache: 'no-store' });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function setOnline(value: boolean) {
  if (value === online.value) return;
  const wasOnline = online.value;
  online.value = value;
  Notify.create(
    value
      ? { type: 'positive', icon: 'wifi', message: 'Conexión con el servidor restablecida.' }
      : {
          type: 'negative',
          icon: 'wifi_off',
          message: 'Sin conexión con el servidor.',
          caption: 'Verificá la red. Los cambios locales no se enviarán hasta reconectar.',
          timeout: 4000,
        },
  );
  if (!wasOnline && value && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('necktral:server-online'));
  }
}

async function refresh() {
  if (probing) return;
  probing = true;
  try {
    setOnline(await probeServer());
    lastCheckAt.value = new Date();
  } finally {
    probing = false;
  }
}

export function useConnectivity() {
  if (!started && typeof window !== 'undefined') {
    started = true;
    window.addEventListener('online', () => void refresh());
    window.addEventListener('offline', () => setOnline(false));
    // En el cel: al volver a la app (estaba en segundo plano), verificar al instante.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') void refresh();
    });
    window.setInterval(() => void refresh(), HEARTBEAT_MS);
    void refresh();
  }
  return { online, lastCheckAt, refresh };
}
