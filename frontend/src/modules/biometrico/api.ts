/**
 * Reloj biométrico de asistencia — capa de datos tipada del kernel `nomina/biometric`.
 *
 * Flujo: registrar el aparato (da un token de un solo uso) → subir el Excel/CSV que exporta
 * el reloj (import) → ver lotes y marcas → mapear el código del aparato a un empleado →
 * consolidar las marcas al período de planilla (rollup).
 */
import { api } from 'src/boot/axios';
import { PAGE, type Paginated } from 'src/core/api';

export interface BiometricDevice {
  id: number;
  name: string;
  vendor: string;
  serial: string;
  branch_id: number | null;
  is_active: boolean;
  last_seen_at: string | null;
  created_at: string;
  api_token?: string; // solo al crear o rotar (se muestra UNA vez)
}

export interface BiometricBatch {
  id: number;
  device_id: number;
  device_name: string;
  file_name: string;
  rows_total: number;
  created: number;
  duplicates: number;
  unmatched: number;
  error_count: number;
  created_at: string;
}

export interface BiometricCheck {
  id: number;
  device_id: number;
  external_code: string;
  external_name: string;
  employee_id: number | null;
  employee_name: string | null;
  direction: string;
  checked_at: string;
  work_date: string;
}

export interface BiometricImportResult {
  batch_id: number;
  rows_total: number;
  created: number;
  duplicates: number;
  unmatched: number;
  errors: string[];
  error_count: number;
}

const BASE = '/nomina/biometric';

export async function listDevices(): Promise<BiometricDevice[]> {
  const { data } = await api.get<{ results: BiometricDevice[] }>(`${BASE}/devices/`);
  return data.results;
}

export async function createDevice(input: {
  name: string;
  vendor?: string;
  serial?: string;
  branch_id?: number | null;
}): Promise<BiometricDevice> {
  const { data } = await api.post<BiometricDevice>(`${BASE}/devices/`, input);
  return data;
}

export async function updateDevice(
  id: number,
  patch: Partial<{ name: string; vendor: string; serial: string; is_active: boolean; branch_id: number | null }>,
): Promise<BiometricDevice> {
  const { data } = await api.patch<BiometricDevice>(`${BASE}/devices/${id}/`, patch);
  return data;
}

export async function rotateToken(id: number): Promise<BiometricDevice> {
  const { data } = await api.post<BiometricDevice>(`${BASE}/devices/${id}/rotate-token/`, {});
  return data;
}

/** Sube el archivo (.xlsx/.csv) que exporta el aparato; el backend ingiere las marcas. */
export async function importChecks(deviceId: number, file: File): Promise<BiometricImportResult> {
  const fd = new FormData();
  fd.append('file', file);
  const { data } = await api.post<BiometricImportResult>(`${BASE}/devices/${deviceId}/import/`, fd);
  return data;
}

export async function listBatches(): Promise<BiometricBatch[]> {
  const { data } = await api.get<Paginated<BiometricBatch>>(`${BASE}/batches/`, { params: PAGE });
  return data.results;
}

export async function listChecks(params: {
  work_date?: string;
  employee_id?: number;
  only_unmatched?: boolean;
} = {}): Promise<BiometricCheck[]> {
  const { data } = await api.get<Paginated<BiometricCheck>>(`${BASE}/checks/`, {
    params: {
      ...PAGE,
      ...(params.work_date ? { work_date: params.work_date } : {}),
      ...(params.employee_id ? { employee_id: params.employee_id } : {}),
      ...(params.only_unmatched ? { only_unmatched: 1 } : {}),
    },
  });
  return data.results;
}

/** Mapea el código del aparato a un empleado; re-asocia las marcas pendientes de ese código. */
export async function mapCode(externalCode: string, employeeId: number): Promise<{ rematched_checks: number }> {
  const { data } = await api.post<{ ok: boolean; rematched_checks: number }>(`${BASE}/map/`, {
    external_code: externalCode,
    employee_id: employeeId,
  });
  return data;
}

/** Consolida las marcas del período hacia la asistencia (rollup). */
export async function rollup(periodId: number): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>(`${BASE}/rollup/`, { period_id: periodId });
  return data;
}
