/**
 * Diagnóstico — supervisión técnica: errores de runtime (C1/C2/C3), diagnóstico
 * determinista + análisis IA opcional, hallazgos de seguridad y kill switch IA.
 */
import { api } from 'src/boot/axios';
import { PAGE } from 'src/core/api';

export const RISK_LABELS: Record<string, string> = {
  C1: 'C1 (crítico)',
  C2: 'C2 (alto)',
  C3: 'C3 (normal)',
};

export const ERROR_STATUS_LABELS: Record<string, string> = {
  open: 'Abierto',
  triaged: 'En triage',
  confirmed: 'Confirmado',
  fixed: 'Corregido',
  regressed: 'Regresó',
  accepted_risk: 'Riesgo aceptado',
  false_positive: 'Falso positivo',
};

// El identificador es UUID (`error_id`), no un entero. El backend no expone el mensaje
// en claro (solo `message_hash`); se describe el error con tipo + archivo:línea.
export interface ErrorEventRow {
  error_id: string;
  risk_class: string;
  status: string;
  domain: string;
  exception_type?: string;
  file_path?: string;
  line_number?: number;
  function_name?: string;
  endpoint?: string;
  occurrence_count?: number;
  last_seen_at?: string;
  [k: string]: unknown;
}

export interface SecurityFindingRow {
  finding_id: string;
  status: string;
  severity_raw?: string;
  vuln_id?: string;
  cve_id?: string;
  package?: string;
  source_tool?: string;
  file_path?: string;
  [k: string]: unknown;
}

export async function listErrors(filters: { risk_class?: string; status?: string } = {}): Promise<
  ErrorEventRow[]
> {
  const params: Record<string, string | number> = { ...PAGE };
  if (filters.risk_class) params.risk_class = filters.risk_class;
  if (filters.status) params.status = filters.status;
  const { data } = await api.get<{ results: ErrorEventRow[] }>('/diagnostics/errors/', { params });
  return data.results;
}

export async function diagnoseError(errorId: string): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>(`/diagnostics/errors/${errorId}/diagnose/`, {});
  return data;
}

export async function triageError(errorId: string, status: string): Promise<void> {
  await api.post(`/diagnostics/errors/${errorId}/triage/`, { status });
}

export async function listSecurityFindings(): Promise<SecurityFindingRow[]> {
  const { data } = await api.get<{ results: SecurityFindingRow[] }>('/diagnostics/findings/', {
    params: PAGE,
  });
  return data.results;
}

export async function triageSecurityFinding(findingId: string, status: string): Promise<void> {
  await api.post(`/diagnostics/findings/${findingId}/triage/`, { status });
}

export async function getReleaseReadiness(): Promise<Record<string, unknown>> {
  const { data } = await api.get<Record<string, unknown>>('/diagnostics/release-readiness/');
  return data;
}

export async function getSupervision(): Promise<Record<string, unknown>> {
  const { data } = await api.get<Record<string, unknown>>('/diagnostics/supervision/');
  return data;
}

export async function getAiControl(): Promise<{ enabled: boolean }> {
  const { data } = await api.get<{ ai_enabled: boolean }>('/diagnostics/ai-control/');
  return { enabled: Boolean(data.ai_enabled) };
}

export async function setAiControl(enabled: boolean, reason = ''): Promise<void> {
  await api.post('/diagnostics/ai-control/', { enabled, reason });
}

// --- Diagnósticos (causa raíz) + análisis IA + evidencia de cobertura -----------
// El diagnóstico determinista de un error se dispara con diagnoseError() (ya existe) y
// crea un DiagnosticRun; aquí se lista/ve, se le puede pedir el análisis IA (detrás del
// kill switch → 409 si la IA está apagada) y se ve la cobertura de código por línea.
export const CONFIDENCE_LABELS: Record<string, string> = {
  low: 'Baja',
  medium: 'Media',
  high: 'Alta',
};
export const COVERAGE_LABELS: Record<string, string> = {
  covered: 'Cubierta',
  uncovered: 'Sin cobertura',
  partial: 'Parcial',
  unknown: 'Desconocida',
};

export interface DiagnosisRow {
  run_id: string;
  subject_type: string;
  subject_id: string;
  trigger_type: string;
  domain: string;
  risk_class: string;
  evidence: Record<string, unknown>;
  summary: string;
  blast_radius: Record<string, unknown>;
  root_cause_hypothesis: string;
  recommended_tests: string;
  recommended_fix: string;
  confidence: string;
  ai_assisted: boolean;
  generated_by: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface CodeEvidenceRow {
  path: string;
  line_start: number;
  line_end: number;
  symbol: string;
  domain: string;
  coverage_state: string;
  error_refs: unknown[];
  security_refs: unknown[];
  last_commit: string;
  created_at: string;
  updated_at: string;
}

export async function listDiagnoses(
  filters: { risk_class?: string; status?: string; domain?: string } = {},
): Promise<DiagnosisRow[]> {
  const params: Record<string, string> = {};
  if (filters.risk_class) params.risk_class = filters.risk_class;
  if (filters.status) params.status = filters.status;
  if (filters.domain) params.domain = filters.domain;
  const { data } = await api.get<{ results: DiagnosisRow[] }>('/diagnostics/diagnoses/', { params });
  return data.results;
}
export async function getDiagnosis(runId: string): Promise<DiagnosisRow> {
  const { data } = await api.get<DiagnosisRow>(`/diagnostics/diagnoses/${runId}/`);
  return data;
}
/** Rellena la hipótesis IA del diagnóstico. Lanza si la IA está apagada (HTTP 409). */
export async function aiAnalyzeDiagnosis(runId: string): Promise<DiagnosisRow> {
  const { data } = await api.post<DiagnosisRow>(`/diagnostics/diagnoses/${runId}/ai-analyze/`, {});
  return data;
}
export async function listCodeEvidence(
  filters: { domain?: string; coverage_state?: string } = {},
): Promise<CodeEvidenceRow[]> {
  const params: Record<string, string> = {};
  if (filters.domain) params.domain = filters.domain;
  if (filters.coverage_state) params.coverage_state = filters.coverage_state;
  const { data } = await api.get<{ results: CodeEvidenceRow[] }>('/diagnostics/code-evidence/', {
    params,
  });
  return data.results;
}
