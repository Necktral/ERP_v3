/**
 * Alertas y recordatorios: lo que el sistema DETECTA (cartera vencida, stock bajo,
 * documentos de flota por vencer, préstamos en mora…) y las acciones humanas para
 * ACTUAR sobre ellas (reconocer / resolver) + un re-escaneo manual.
 * Mapea los endpoints reales de `apps.modulos.alertas`. Las pantallas NO llaman
 * axios directo: usan estas funciones tipadas.
 * Montaje backend: `api/alertas/` → con baseURL `/api` => `/alertas/...`.
 */
import { api } from 'src/boot/axios';

export type AlertSeverity = 'INFO' | 'WARNING' | 'CRITICAL';
export type AlertStatus = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED';

export const SEVERITY_LABELS: Record<string, string> = {
  INFO: 'Informativa',
  WARNING: 'Advertencia',
  CRITICAL: 'Crítica',
};
export const STATUS_LABELS: Record<string, string> = {
  OPEN: 'Abierta',
  ACKNOWLEDGED: 'Vista',
  RESOLVED: 'Resuelta',
};
export const ALERT_TYPE_LABELS: Record<string, string> = {
  RECEIVABLE_OVERDUE: 'Cuenta por cobrar vencida',
  LOW_STOCK: 'Stock bajo',
  FLEET_DOC_EXPIRING: 'Documento de flota por vencer',
  FINANCING_LOAN_OVERDUE: 'Préstamo en mora',
  YIELD_ANOMALY: 'Anomalía de rendimiento',
};

export interface AlertRow {
  id: number;
  alert_type: string;
  severity: AlertSeverity;
  subject_type: string;
  subject_id: string;
  title: string;
  detail: string;
  payload_json: Record<string, unknown>;
  status: AlertStatus;
  first_seen_at: string;
  last_seen_at: string;
  resolved_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by_username: string;
}

export async function listAlerts(
  filters: { status?: string; severity?: string; alert_type?: string } = {},
): Promise<AlertRow[]> {
  const params: Record<string, string> = {};
  if (filters.status) params.status = filters.status;
  if (filters.severity) params.severity = filters.severity;
  if (filters.alert_type) params.alert_type = filters.alert_type;
  const { data } = await api.get<{ results: AlertRow[] }>('/alertas/', { params });
  return data.results;
}
export async function ackAlert(alertId: number): Promise<AlertRow> {
  const { data } = await api.post<AlertRow>(`/alertas/${alertId}/ack/`, {});
  return data;
}
export async function resolveAlert(alertId: number): Promise<AlertRow> {
  const { data } = await api.post<AlertRow>(`/alertas/${alertId}/resolve/`, {});
  return data;
}
export interface ScanResult {
  scanned: Record<string, { active: number; opened: number; resolved: number }>;
}
export async function scanAlerts(): Promise<ScanResult> {
  const { data } = await api.post<ScanResult>('/alertas/scan/', {});
  return data;
}
