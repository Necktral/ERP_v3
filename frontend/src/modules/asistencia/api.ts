/**
 * Asistencia del día — capa de datos (pantalla del mandador/capataz, PC y cel).
 */
import { api } from 'src/boot/axios';

export type EstadoAsistencia =
  | 'SIN_MARCAR'
  | 'PRESENTE'
  | 'AUSENTE'
  | 'ENFERMO'
  | 'MEDIO_DIA'
  | 'ACCIDENTADO';

export interface PersonalRow {
  employee_id: number;
  employee_code: string;
  first_name: string;
  last_name: string;
  phone: string;
  position_name: string;
  has_photo: boolean;
  estado: EstadoAsistencia;
  /** Solo aplica a ENFERMO: con constancia el día SE PAGA. null = no aplica. */
  constancia_medica: boolean | null;
}

export interface AsistenciaHoy {
  work_date: string;
  work_day_id: number | null;
  work_day_status: string | null;
  total: number;
  marcados: number;
  results: PersonalRow[];
}

export async function getAsistenciaHoy(): Promise<AsistenciaHoy> {
  const { data } = await api.get<AsistenciaHoy>('/nomina/asistencia/hoy/');
  return data;
}

export async function marcarAsistencia(
  // SIN_MARCAR está permitido: deshace/corrige una marca puesta por equivocación.
  employeeId: number,
  estado: EstadoAsistencia,
  opts: { constancia_medica?: boolean } = {},
): Promise<void> {
  await api.post('/nomina/asistencia/hoy/', { employee_id: employeeId, estado, ...opts });
}

/** SoD maker: solicita la aprobación de la consolidación del día (cierra #4 del audit). */
export async function requestFieldApproval(
  workDayId: number,
  reason: string,
): Promise<{ approval_request_id: string; status: string }> {
  const { data } = await api.post<{ approval_request_id: string; status: string }>(
    `/nomina/field/work-days/${workDayId}/approve-request/`,
    { reason, idempotency_key: crypto.randomUUID() },
  );
  return data;
}
