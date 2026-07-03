/**
 * Analítica / Dashboard — workspaces de tableros y tokens de embed temporales.
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
 * Visor de reportes EN LA APP — corre un dataset del kernel `reporting` y devuelve el
 * envelope con dimensiones/medidas/filas/totales. Reemplaza el viejo flujo de "embed
 * token" (que requería un visor de BI externo inexistente). Permiso: report.dataset.read
 * + el del dominio del dataset (p. ej. accounting.report.read). Algunos datasets son
 * SNAPSHOT_REQUIRED: el kernel los corre en vivo y persiste el snapshot, no hay que
 * pre-generarlo.
 */
export interface DatasetEnvelope {
  dataset_key: string;
  title: string;
  description?: string;
  dimensions: string[];
  measures: string[];
  rows: Record<string, unknown>[];
  totals: Record<string, unknown>;
  quality_status: string;
  render_hints?: { numeric_format?: string; default_chart?: string };
  run_id?: string;
}

export async function runDataset(
  datasetKey: string,
  filters?: Record<string, unknown>,
): Promise<DatasetEnvelope> {
  const { data } = await api.post<DatasetEnvelope>(`/reporting/datasets/${datasetKey}/run/`, {
    filters: filters ?? {},
  });
  return data;
}

// --- Reporting avanzado: exportar / snapshot / vistas guardadas (cierra #4 del audit) ---
export interface ExportResult {
  export_id: string;
  format: string;
  status: string;
  file_size: number;
}

export async function createRunExport(runId: string, format: 'csv' | 'xlsx'): Promise<ExportResult> {
  const { data } = await api.post<ExportResult>(`/reporting/runs/${runId}/export/`, { format });
  return data;
}

export async function generateSnapshot(
  datasetKey: string,
  filters?: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>('/reporting/snapshots/generate/', {
    dataset_key: datasetKey,
    filters: filters ?? {},
  });
  return data;
}

export interface SavedView {
  view_id: string;
  name: string;
  dataset_key: string;
  filters: Record<string, unknown>;
  [k: string]: unknown;
}

export async function listSavedViews(datasetKey: string): Promise<SavedView[]> {
  const { data } = await api.get<{ results: SavedView[] }>('/reporting/saved-views/', {
    params: { dataset_key: datasetKey },
  });
  return data.results;
}

export async function createSavedView(input: {
  name: string;
  dataset_key: string;
  filters: Record<string, unknown>;
}): Promise<SavedView> {
  const { data } = await api.post<SavedView>('/reporting/saved-views/', input);
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
