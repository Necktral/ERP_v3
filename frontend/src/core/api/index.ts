/**
 * Utilidades compartidas de la capa de datos (todas las features/*.api.ts
 * importan de aquí; ninguna define las suyas propias).
 */

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
 * Extrae un mensaje legible del envelope de error de DRF:
 * `detail` si existe; si no, el primer error de campo como "campo: mensaje".
 */
export function apiErrorMessage(e: unknown, fallback = ''): string {
  const err = e as { response?: { data?: Record<string, unknown> } };
  const data = err.response?.data;
  if (data && typeof data === 'object') {
    if (typeof data.detail === 'string') return data.detail;
    for (const k of Object.keys(data)) {
      const v = data[k];
      if (Array.isArray(v) && v.length) return `${k}: ${String(v[0])}`;
      if (typeof v === 'string') return `${k}: ${v}`;
    }
  }
  return fallback;
}
