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

/**
 * Extrae un mensaje legible del envelope de error de DRF:
 * `detail` si existe; si no, el primer error de campo como "campo: mensaje".
 * Si el valor es un código crudo del backend (p. ej. SALES_INSUFFICIENT_STOCK)
 * y está en el diccionario central (src/core/codigos), devuelve su traducción.
 */
export function apiErrorMessage(e: unknown, fallback = ''): string {
  const err = e as { response?: { data?: Record<string, unknown> } };
  const data = err.response?.data;
  if (data && typeof data === 'object') {
    if (typeof data.detail === 'string') {
      return traduccionDeCodigo(data.detail) ?? data.detail;
    }
    for (const k of Object.keys(data)) {
      const v = data[k];
      if (Array.isArray(v) && v.length) {
        const s = String(v[0]);
        return traduccionDeCodigo(s) ?? `${k}: ${s}`;
      }
      if (typeof v === 'string') {
        return traduccionDeCodigo(v) ?? `${k}: ${v}`;
      }
    }
  }
  return fallback;
}
