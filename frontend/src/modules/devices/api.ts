/**
 * Dispositivos enrolados (sync_engine) — capa de datos tipada.
 *
 * El flujo es de dos puntas: el ADMIN genera aquí el código de un solo uso
 * (`/sync/enrollment/challenges/`) y el APARATO lo canjea en `/sync/enroll/`
 * (eso vive en `core/device.ts` porque corre en el aparato).
 */
import { api } from 'src/boot/axios';

export interface EnrollmentChallenge {
  challenge_id: string;
  enrollment_code: string; // solo se entrega UNA vez
  enrollment_uri: string;
  expires_at: string;
}

export interface DeviceRow {
  id: string;
  label: string;
  status: 'ACTIVE' | 'REVOKED' | 'QUARANTINED';
  company_id: number | null;
  branch_id: number | null;
  created_at: string | null;
  revoked_at: string | null;
  last_seen_at: string | null;
  last_accepted_sequence: number | null;
}

export interface DevicePage {
  count: number;
  next: string | null;
  previous: string | null;
  results: DeviceRow[];
}

export async function createEnrollmentChallenge(input: {
  label_hint?: string;
  expires_in_minutes?: number;
}): Promise<EnrollmentChallenge> {
  const { data } = await api.post<EnrollmentChallenge>('/sync/enrollment/challenges/', input);
  return data;
}

export async function listDevices(limit = 25, offset = 0): Promise<DevicePage> {
  const { data } = await api.get<DevicePage>('/sync/devices/', {
    params: { limit, offset },
  });
  return data;
}

export async function revokeDevice(deviceId: string): Promise<void> {
  await api.post(`/sync/devices/${deviceId}/revoke/`, {});
}
