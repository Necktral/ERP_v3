export const STORAGE_KEYS = {
  AUTH_ACCESS: 'necktral.auth.access',
  AUTH_REFRESH: 'necktral.auth.refresh',
  CTX_COMPANY_ID: 'necktral.ctx.company_id',
  CTX_BRANCH_ID: 'necktral.ctx.branch_id',
  POS_OFFLINE_QUEUE: 'necktral.pos.offline_queue',
  PAGADOR_PERIOD_ID: 'necktral.pagador.period_id',
  // Última vez que la cola SQLite subió pagos al servidor (ISO) — indicador para el cajero.
  PAGADOR_LAST_SYNC: 'necktral.pagador.last_sync',
  // Caché offline-first: payload de sesión (user+ACL+contexto+módulos) para ENTRAR sin red,
  // lista de períodos por empresa y deudas por período (para operar la planilla offline).
  SESSION_PAYLOAD: 'necktral.session.payload',
  PAGADOR_PERIODS: 'necktral.pagador.periods',
  PAGADOR_DEUDAS: 'necktral.pagador.deudas',
  UI_THEME: 'necktral.ui.theme',
  UI_DENSITY: 'necktral.ui.density',
  // App nativa (Capacitor): servidor al que sincroniza (origen sin /api) + último que respondió.
  SERVER_ORIGIN: 'necktral.server.origin',
  SERVER_LAST_OK: 'necktral.server.last_ok',
} as const;
