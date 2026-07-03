/**
 * Analítica / Dashboard — workspaces de tableros y tokens de embed temporales.
 *
 * El consumo del kernel `reporting` (runDataset, exports, snapshots, saved
 * views) vive en src/modules/reportes/api.ts — módulo de Reportes — para no
 * duplicar rutas; Analítica importa de ahí.
 */
import { api } from 'src/boot/axios';

export interface WorkspaceRow {
  workspace_key: string;
  title: string;
  description?: string;
  datasets?: string[];
  required_permissions?: string[];
  compose_allowed?: boolean;
}

export async function listWorkspaces(): Promise<WorkspaceRow[]> {
  const { data } = await api.get<{ results: WorkspaceRow[] }>('/backend/dashboard/workspaces/');
  return data.results;
}

export async function createEmbedToken(workspaceKey: string): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>('/backend/dashboard/embed-token/', {
    workspace_key: workspaceKey,
  });
  return data;
}

/**
 * Tablero del día (resumen en vivo) — reusa el "resumen del día" del asistente
 * (`/knowledge/summary/`): cada sección es una skill operativa (ventas, caja,
 * cobros/pagos, stock bajo, ...) gateada por permiso y acotada a la EMPRESA
 * activa. Para una vista del holding se llama por empresa cambiando el contexto.
 */
export interface SummarySection {
  skill: string;
  etiqueta: string;
  answer: string;
  data: Record<string, unknown>;
}

export interface DailySummary {
  empresa: string;
  secciones: SummarySection[];
}

export async function getDailySummary(
  companyId?: string | number,
  opts: { background?: boolean } = {},
): Promise<DailySummary> {
  // Con companyId se consulta OTRA empresa del holding (override de X-Company-Id,
  // a nivel empresa, sin sucursal). Sin él, la empresa/sucursal activa.
  // background:true en el polling del tablero: un 403 no debe navegar a /403.
  const config = {
    ...(companyId != null ? { headers: { 'X-Company-Id': String(companyId) } } : {}),
    ...(opts.background ? { background: true } : {}),
  };
  const { data } = await api.get<{ data: DailySummary }>('/knowledge/summary/', config);
  return data.data;
}
