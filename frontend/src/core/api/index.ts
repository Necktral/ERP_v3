/**
 * Utilidades compartidas de la capa de datos (todas las features/*.api.ts
 * importan de aquí; ninguna define las suyas propias).
 */

import { CODIGOS, esCodigoBackend } from 'src/core/codigos';

/** Envelope de paginación estándar del backend ({count, limit, offset, results}). */
export interface Paginated<T> {
  count: number;
  limit: number;
  offset: number;
  results: T[];
}

/**
 * Página por defecto para listados de CATÁLOGO CORTO (trae todo de una vez).
 * OJO: trunca en silencio por encima de `limit`. Para tablas que pueden crecer
 * usa paginación server-side con `useListadoServer` + `toPageParams`.
 */
export const PAGE = { limit: 200, offset: 0 } as const;

/** Parámetros de página que entiende el backend (limit/offset DRF + ordering). */
export interface PageReq {
  limit: number;
  offset: number;
  ordering?: string;
  search?: string;
}

/** Estado de paginación de q-table (subset que nos interesa). */
export interface QTablePagination {
  page: number;
  rowsPerPage: number;
  sortBy?: string | null;
  descending?: boolean;
  rowsNumber?: number;
}

/**
 * Mapea la paginación de q-table a limit/offset/ordering DRF.
 * `ordering` solo se emite si hay columna de orden (con "-" si es descendente).
 * rowsPerPage=0 es el "Todos" de q-table: se mapea al tope del backend (200,
 * que es a lo que igual clampa get_limit_offset) — nunca mandar limit 0.
 */
export function toPageParams(p: QTablePagination): PageReq {
  const porPagina = p.rowsPerPage > 0 ? p.rowsPerPage : PAGE.limit;
  const req: PageReq = {
    limit: porPagina,
    offset: (p.page - 1) * porPagina,
  };
  if (p.sortBy) {
    req.ordering = p.descending ? `-${p.sortBy}` : p.sortBy;
  }
  return req;
}

/**
 * Traducción del diccionario central si `valor` es un código crudo del backend
 * (CODIGO_EN_MAYUSCULAS) con entrada conocida; null si no aplica.
 */
function traduccionDeCodigo(valor: string): string | null {
  const v = valor.trim();
  return esCodigoBackend(v) ? (CODIGOS[v] ?? null) : null;
}

function mensajeDeValor(valor: unknown): string | null {
  if (typeof valor === 'string') return traduccionDeCodigo(valor) ?? valor;
  if (Array.isArray(valor)) {
    for (const item of valor) {
      const message = mensajeDeValor(item);
      if (message) return message;
    }
  }
  if (valor && typeof valor === 'object') {
    const record = valor as Record<string, unknown>;
    for (const key of ['code', 'error', 'detail', 'non_field_errors', 'message']) {
      const message = mensajeDeValor(record[key]);
      if (message) return message;
    }
    for (const value of Object.values(record)) {
      const message = mensajeDeValor(value);
      if (message) return message;
    }
  }
  return null;
}

/**
 * Extrae un mensaje legible del envelope de error de DRF:
 * `detail` si existe; si no, el primer error de campo como "campo: mensaje".
 * Si el valor es un código crudo del backend (p. ej. SALES_INSUFFICIENT_STOCK)
 * y está en el diccionario central (src/core/codigos), devuelve su traducción.
 */
export function apiErrorMessage(e: unknown, fallback = ''): string {
  const err = e as { message?: unknown; response?: { status?: number; data?: unknown } };
  const data = err.response?.data;
  if (typeof data === 'string') return traduccionDeCodigo(data) ?? data;
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    const record = data as Record<string, unknown>;
    const known = new Set(['code', 'error', 'detail', 'non_field_errors', 'message']);
    for (const key of known) {
      const message = mensajeDeValor(record[key]);
      if (message) return message;
    }
    for (const [key, value] of Object.entries(record)) {
      const message = mensajeDeValor(value);
      if (message) return `${key}: ${message}`;
    }
  }
  if (!err.response) return fallback || 'No se pudo conectar con el servidor.';
  const status = err.response.status;
  if (status === 401) return 'La sesión venció. Iniciá sesión nuevamente.';
  if (status === 403) return 'No tenés permiso para realizar esta acción.';
  if (status === 404) return 'No se encontró la información solicitada.';
  if (status === 409) return 'La operación entra en conflicto con el estado actual.';
  if (status === 429) return 'Hay demasiadas solicitudes. Esperá un momento e intentá nuevamente.';
  if (status && status >= 500) return 'El servidor no pudo completar la operación.';
  if (fallback) return fallback;
  return typeof err.message === 'string' && err.message.trim()
    ? err.message
    : 'No se pudo completar la operación.';
}
