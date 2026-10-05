/**
 * Reportes — consumo del kernel `reporting` (catálogo de datasets, ejecuciones,
 * exports, snapshots y vistas guardadas). ÚNICO dueño de las rutas /reporting/*
 * del frontend: el dashboard (Analítica) importa de aquí, no duplica rutas.
 *
 * Permisos (rbac_permission de las views del backend):
 * - catálogo (list/detalle) ........... report.catalog.read
 * - ejecutar dataset .................. report.dataset.read (+ permiso del dominio)
 * - runs (list/detalle) ............... report.run.read
 * - export (crear/poll detalle) ....... report.dataset.export
 * - snapshots (list) .................. report.run.read
 * - snapshots/generate ................ report.snapshot.generate
 * - saved-views GET (list/detalle) .... report.dashboard.read
 * - saved-views POST .................. report.dashboard.compose
 */
import { api } from 'src/boot/axios';
import type { PageReq, Paginated } from 'src/core/api';

// ---------------------------------------------------------------------------
// Catálogo (GET /reporting/catalog/ y /reporting/catalog/<key>/)
// ---------------------------------------------------------------------------

/** Campo del filters_schema del dataset ({ type: 'int'|'date'|'str', required }). */
export interface FiltroSchemaCampo {
  type: string;
  required?: boolean;
}

/** Entrada del catálogo, fiel a services.list_catalog(). */
export interface CatalogEntry {
  dataset_key: string;
  title: string;
  description: string;
  domain_owner: string;
  scope_level: string;
  schema_version: string;
  semantic_version: string;
  freshness_mode: string;
  materialization_policy: string;
  required_permissions: string[];
  filters_schema: Record<string, FiltroSchemaCampo>;
  dimensions: string[];
  measures: string[];
  render_hints: { numeric_format?: string; default_chart?: string } & Record<string, unknown>;
  drill_metadata: Record<string, unknown>;
  quality_policy: Record<string, unknown>;
  export_capabilities: ExportFormato[];
  status: string;
  is_certified: boolean;
  is_enabled: boolean;
}

/** Catálogo de datasets habilitados (el backend ya filtra is_enabled). */
export async function listCatalog(): Promise<CatalogEntry[]> {
  const { data } = await api.get<{ count: number; results: CatalogEntry[] }>('/reporting/catalog/');
  return data.results;
}

/** Detalle de un dataset del catálogo por su key. */
export async function getCatalogEntry(datasetKey: string): Promise<CatalogEntry> {
  const { data } = await api.get<CatalogEntry>(`/reporting/catalog/${datasetKey}/`);
  return data;
}

// ---------------------------------------------------------------------------
// Ejecución (POST /reporting/datasets/<key>/run/)
// ---------------------------------------------------------------------------

/** Check de calidad evaluado sobre el envelope del run. */
export interface QualityCheck {
  [k: string]: unknown;
}

/**
 * Envelope del dataset (contracts.build_dataset_envelope + run_id que agrega la
 * view): dimensiones/medidas/filas/totales + calidad y linaje.
 */
export interface DatasetEnvelope {
  dataset_key: string;
  title: string;
  description?: string;
  schema_version?: string;
  semantic_version?: string;
  generated_at?: string;
  freshness_mode?: string;
  scope?: Record<string, unknown>;
  filters?: Record<string, unknown>;
  grain?: string;
  dimensions: string[];
  measures: string[];
  rows: Record<string, unknown>[];
  totals: Record<string, unknown>;
  warnings?: unknown[];
  lineage?: Record<string, unknown>;
  render_hints?: { numeric_format?: string; default_chart?: string };
  drill_metadata?: Record<string, unknown>;
  quality_status: string;
  quality_checks?: QualityCheck[];
  export_capabilities?: ExportFormato[];
  run_id?: string;
}

/**
 * Corre un dataset del kernel `reporting` y devuelve el envelope. Permiso:
 * report.dataset.read + el del dominio del dataset (p. ej. accounting.report.read).
 * Los datasets SNAPSHOT_REQUIRED se corren en vivo y persisten su snapshot solos.
 */
export async function runDataset(
  datasetKey: string,
  filters?: Record<string, unknown>,
): Promise<DatasetEnvelope> {
  const { data } = await api.post<DatasetEnvelope>(`/reporting/datasets/${datasetKey}/run/`, {
    filters: filters ?? {},
  });
  return data;
}

// ---------------------------------------------------------------------------
// Runs (GET /reporting/runs/ y /reporting/runs/<id>/)
// ---------------------------------------------------------------------------

export type RunEstado = string;

/** Fila del historial de ejecuciones (RunsListView). */
export interface RunResumen {
  run_id: string;
  dataset_key: string;
  status: RunEstado;
  row_count: number;
  duration_ms: number;
  quality_status: string;
  created_at: string;
  completed_at: string | null;
  company_id: number | null;
  branch_id: number | null;
}

/**
 * Historial de ejecuciones, paginado server-side con el envelope estándar
 * {count, limit, offset, results} (paginate_queryset del backend).
 */
export async function listRuns(
  filtros: { dataset_key?: string },
  page: PageReq,
): Promise<Paginated<RunResumen>> {
  const params: Record<string, unknown> = { limit: page.limit, offset: page.offset };
  if (filtros.dataset_key) params.dataset_key = filtros.dataset_key;
  const { data } = await api.get<Paginated<RunResumen>>('/reporting/runs/', { params });
  return data;
}

/** Detalle completo de un run (RunDetailView). */
export interface RunDetalle extends Omit<RunResumen, 'company_id' | 'branch_id'> {
  filters: Record<string, unknown>;
  result_hash: string;
  quality_checks: QualityCheck[];
  warnings: unknown[];
  source_summary: Record<string, unknown>;
  lineage: Record<string, unknown>;
  schema_version: string;
  semantic_version: string;
  consumer_type: string;
  consumer_ref: string;
  error_detail: string;
}

export async function getRunDetail(runId: string): Promise<RunDetalle> {
  const { data } = await api.get<RunDetalle>(`/reporting/runs/${runId}/`);
  return data;
}

// ---------------------------------------------------------------------------
// Exports (POST /reporting/runs/<id>/export/ y GET /reporting/exports/<id>/)
// ---------------------------------------------------------------------------

export type ExportFormato = 'json' | 'csv' | 'xlsx';
export type ExportEstado = string;

/** Export de un run, fiel a exports.export_to_dict(). */
export interface ExportResult {
  export_id: string;
  run_id: string;
  dataset_key: string;
  format: ExportFormato;
  status: ExportEstado;
  output_hash: string;
  file_size: number;
  mime_type: string;
  file_name: string;
  delivery_channel: string;
  error_detail: string;
  created_at: string;
  completed_at: string | null;
  updated_at: string;
}

/** Crea un export del run en el formato pedido (permiso report.dataset.export). */
export async function createRunExport(
  runId: string,
  format: ExportFormato,
): Promise<ExportResult> {
  const { data } = await api.post<ExportResult>(`/reporting/runs/${runId}/export/`, { format });
  return data;
}

/**
 * Detalle/poll de un export. `background: true` en el poll: un 403 no debe
 * navegar a /403 ni sacar al usuario de la página (flag de boot/axios.ts).
 */
export async function getExportDetail(
  exportId: string,
  opts: { background?: boolean } = {},
): Promise<ExportResult> {
  const config = opts.background ? { background: true } : {};
  const { data } = await api.get<ExportResult>(`/reporting/exports/${exportId}/`, config);
  return data;
}

// ---------------------------------------------------------------------------
// Snapshots (GET /reporting/snapshots/ y POST /reporting/snapshots/generate/)
// ---------------------------------------------------------------------------

export type SnapshotEstado = string;

/** Fila del listado de snapshots (SnapshotsListView). */
export interface SnapshotRow {
  snapshot_id: number;
  dataset_key: string;
  status: SnapshotEstado;
  fresh_until: string | null;
  row_count: number;
  payload_hash: string;
  schema_version: string;
  semantic_version: string;
  company_id: number | null;
  branch_id: number | null;
  created_at: string;
  updated_at: string;
}

/**
 * Snapshots materializados, paginados server-side con el envelope estándar
 * {count, limit, offset, results}.
 */
export async function listSnapshots(
  filtros: { dataset_key?: string; status?: string },
  page: PageReq,
): Promise<Paginated<SnapshotRow>> {
  const params: Record<string, unknown> = { limit: page.limit, offset: page.offset };
  if (filtros.dataset_key) params.dataset_key = filtros.dataset_key;
  if (filtros.status) params.status = filtros.status;
  const { data } = await api.get<Paginated<SnapshotRow>>('/reporting/snapshots/', { params });
  return data;
}

/** Resultado de generar un snapshot (services.generate_snapshot_from_request). */
export interface SnapshotGenerado {
  dataset_key: string;
  run_id: string;
  snapshot_id: number;
  status: SnapshotEstado;
  fresh_until: string | null;
  row_count: number;
  payload_hash: string;
  schema_version: string;
  semantic_version: string;
  created_at: string;
  updated_at: string;
  materialization_strategy: string | null;
  force_refresh: boolean;
}

/**
 * Genera (o refresca) el snapshot de un dataset. Permiso report.snapshot.generate.
 * Los datasets LIVE_ONLY no lo soportan (el backend responde 400).
 */
export async function generateSnapshot(
  datasetKey: string,
  filters?: Record<string, unknown>,
  opts: { forceRefresh?: boolean } = {},
): Promise<SnapshotGenerado> {
  const { data } = await api.post<SnapshotGenerado>('/reporting/snapshots/generate/', {
    dataset_key: datasetKey,
    filters: filters ?? {},
    ...(opts.forceRefresh ? { force_refresh: true } : {}),
  });
  return data;
}

// ---------------------------------------------------------------------------
// Vistas guardadas (GET/POST /reporting/saved-views/ y GET /reporting/saved-views/<id>/)
// ---------------------------------------------------------------------------

/** Vista guardada, fiel a services._saved_view_to_dict(). */
export interface SavedView {
  view_id: string;
  name: string;
  dataset_key: string;
  filters: Record<string, unknown>;
  render_state: Record<string, unknown>;
  is_shared: boolean;
  is_owner: boolean;
  created_at: string;
  updated_at: string;
}

/** Vistas guardadas del usuario (+ compartidas) para un dataset. */
export async function listSavedViews(datasetKey: string): Promise<SavedView[]> {
  const { data } = await api.get<Paginated<SavedView>>('/reporting/saved-views/', {
    params: { dataset_key: datasetKey },
  });
  return data.results;
}

/**
 * Detalle de una vista guardada (para re-aplicar sus filtros/render_state).
 * OJO: el backend NO expone DELETE para saved-views (SavedViewDetailView solo
 * tiene GET); por eso el frontend no ofrece borrado.
 */
export async function getSavedViewDetail(viewId: string): Promise<SavedView> {
  const { data } = await api.get<SavedView>(`/reporting/saved-views/${viewId}/`);
  return data;
}

/** Crea una vista guardada (permiso report.dashboard.compose). */
export async function createSavedView(input: {
  name: string;
  dataset_key: string;
  filters: Record<string, unknown>;
  render_state?: Record<string, unknown>;
  is_shared?: boolean;
}): Promise<SavedView> {
  const { data } = await api.post<SavedView>('/reporting/saved-views/', input);
  return data;
}
