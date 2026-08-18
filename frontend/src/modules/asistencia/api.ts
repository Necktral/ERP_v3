/**
 * Asistencia del día — capa de datos (pantalla del mandador/capataz, PC y cel).
 *
 * Cubre además el flujo COMPLETO de asistencia de campo (nomina field/*):
 * - Flujo diario: jornada (work-day) → pase de lista → cuadrillas → eventos /
 *   traslados → consolidar → aprobación SoD (maker≠checker) → aplicar a planilla.
 * - Flujo de captura por cuadrilla (PR#17): cuadrillas persistentes → jornada de
 *   captura → reporte → eventos → aprobación SoD → construir asistencia legal.
 */
import { api } from 'src/boot/axios';
import type { PageReq, Paginated } from 'src/core/api';

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

// ===========================================================================
// Flujo diario de asistencia de campo (field/work-days/*)
// ===========================================================================

export type FieldWorkDayStatus =
  | 'OPEN'
  | 'ROLLCALL_SUBMITTED'
  | 'CREW_REPORTS_PENDING'
  | 'IN_REVIEW'
  | 'APPROVED'
  | 'LOCKED';

export const WORK_DAY_STATUS_LABELS: Record<FieldWorkDayStatus, string> = {
  OPEN: 'Abierta',
  ROLLCALL_SUBMITTED: 'Lista enviada',
  CREW_REPORTS_PENDING: 'Reportes pendientes',
  IN_REVIEW: 'En revisión',
  APPROVED: 'Aprobada',
  LOCKED: 'Bloqueada',
};

/** Jornada de campo (FieldWorkDayOut del backend). */
export interface FieldWorkDay {
  id: number;
  company_id: number;
  branch_id: number | null;
  payroll_period_id: number | null;
  work_date: string;
  status: FieldWorkDayStatus;
  opened_by_id: number | null;
  opened_at: string | null;
  approved_by_id: number | null;
  approved_at: string | null;
  locked_at: string | null;
  notes: string;
}

export interface FieldWorkDayFilters {
  status?: string;
  work_date?: string;
  branch_id?: number;
}

/** Lista jornadas de campo (paginado server-side, más recientes primero). */
export async function listFieldWorkDays(
  filters: FieldWorkDayFilters,
  page: PageReq,
): Promise<Paginated<FieldWorkDay>> {
  const { data } = await api.get<Paginated<FieldWorkDay>>('/nomina/field/work-days/', {
    params: { ...filters, ...page },
  });
  return data;
}

/** Abre la jornada de campo del día (una por fecha/sucursal). */
export async function createFieldWorkDay(input: {
  work_date: string;
  branch_id?: number | null;
  payroll_period_id?: number | null;
  notes?: string;
}): Promise<FieldWorkDay> {
  const { data } = await api.post<FieldWorkDay>('/nomina/field/work-days/', input);
  return data;
}

export async function getFieldWorkDay(workDayId: number): Promise<FieldWorkDay> {
  const { data } = await api.get<FieldWorkDay>(`/nomina/field/work-days/${workDayId}/`);
  return data;
}

// --- Pase de lista (rollcall) ---------------------------------------------

export type RollcallLineStatus = 'PRESENT' | 'ABSENT' | 'UNKNOWN';

export const ROLLCALL_STATUS_LABELS: Record<RollcallLineStatus, string> = {
  PRESENT: 'Presente',
  ABSENT: 'Ausente',
  UNKNOWN: 'No confirmado',
};

export interface RollcallLineIn {
  employee_id: number;
  status?: RollcallLineStatus;
  absence_reason?: string;
  note?: string;
}

export interface FieldRollcall {
  id: number;
  work_day_id: number;
  submitted_by_id: number;
  submitted_at: string;
  notes: string;
  lines: Array<RollcallLineIn & { id: number; employee_id: number }>;
}

export async function getFieldRollcall(workDayId: number): Promise<FieldRollcall | null> {
  const { data } = await api.get<FieldRollcall | null>(
    `/nomina/field/work-days/${workDayId}/rollcall/`,
  );
  return data;
}

/** Envía el pase de lista inicial del día (reemplaza el anterior si lo hay). */
export async function submitRollcall(
  workDayId: number,
  input: { lines: RollcallLineIn[]; notes?: string },
): Promise<FieldWorkDay & { rollcall_id: number }> {
  const { data } = await api.post<FieldWorkDay & { rollcall_id: number }>(
    `/nomina/field/work-days/${workDayId}/rollcall/`,
    input,
  );
  return data;
}

// --- Cuadrillas del día y reporte de cuadrilla ------------------------------

export interface FieldCrewCreated {
  id: number;
  name: string;
  work_day_id: number;
  supervisor_employee_id: number;
}

export interface FieldCrew extends FieldCrewCreated {
  is_active: boolean;
}

export async function listFieldCrews(workDayId: number): Promise<FieldCrew[]> {
  const { data } = await api.get<{ results: FieldCrew[] }>(
    `/nomina/field/work-days/${workDayId}/crews/`,
  );
  return data.results;
}

export interface FieldApprovalRequest {
  request_id: string;
  work_day_id: number;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED' | 'EXECUTED';
  requested_by_id: number;
  reason: string;
  requested_at: string;
  decided_by_id: number | null;
  decided_at: string | null;
}

export async function listFieldApprovalRequests(
  filters: { workDayId?: number; status?: FieldApprovalRequest['status'] } = {},
): Promise<FieldApprovalRequest[]> {
  const path = filters.workDayId == null
    ? '/nomina/field/approval-requests/'
    : `/nomina/field/work-days/${filters.workDayId}/approve-request/`;
  const { data } = await api.get<{ results: FieldApprovalRequest[] }>(path, {
    params: filters.status ? { status: filters.status } : undefined,
  });
  return data.results;
}

/** Crea una cuadrilla de la jornada (capataz responsable incluido). */
export async function createFieldCrew(
  workDayId: number,
  input: { name: string; supervisor_employee_id: number },
): Promise<FieldCrewCreated> {
  const { data } = await api.post<FieldCrewCreated>(
    `/nomina/field/work-days/${workDayId}/crews/`,
    input,
  );
  return data;
}

/** Tipos de novedad del flujo diario (FieldWorkerEventType del backend). */
export type FieldEventType =
  | 'PRESENT'
  | 'ABSENT'
  | 'SICK'
  | 'ACCIDENT'
  | 'TRANSFERRED'
  | 'PERMISSION'
  | 'LEFT_EARLY'
  | 'JOINED_LATE'
  | 'DISMISSED'
  | 'OTHER';

export const FIELD_EVENT_LABELS: Record<FieldEventType, string> = {
  PRESENT: 'Presente',
  ABSENT: 'Ausente',
  SICK: 'Enfermo',
  ACCIDENT: 'Accidente',
  TRANSFERRED: 'Trasladado',
  PERMISSION: 'Permiso',
  LEFT_EARLY: 'Salió temprano',
  JOINED_LATE: 'Ingresó tarde',
  DISMISSED: 'Despedido',
  OTHER: 'Otro',
};

/** Eventos que exigen detalle obligatorio (regla del backend). */
export const FIELD_EVENTS_CON_DETALLE: FieldEventType[] = ['SICK', 'ACCIDENT', 'OTHER'];

export interface CrewReportLineIn {
  employee_id: number;
  event_type?: FieldEventType;
  day_value?: string | null;
  notes?: string;
}

/** Envía el reporte diario de una cuadrilla (reemplaza líneas si estaba en borrador). */
export async function submitCrewReport(
  crewId: number,
  input: {
    lines: CrewReportLineIn[];
    labor_code?: string;
    labor_name?: string;
    zone_label?: string;
    notes?: string;
  },
): Promise<{ id: number; crew_id: number; status: string; work_day_status: FieldWorkDayStatus }> {
  const { data } = await api.post<{
    id: number;
    crew_id: number;
    status: string;
    work_day_status: FieldWorkDayStatus;
  }>(`/nomina/field/crews/${crewId}/report/`, input);
  return data;
}

// --- Novedades individuales y traslados -------------------------------------

/** Registra una novedad individual de un trabajador en la jornada. */
export async function recordFieldEvent(
  workDayId: number,
  input: {
    employee_id: number;
    event_type: FieldEventType;
    details?: string;
    crew_report_id?: number | null;
    occurred_at?: string | null;
  },
): Promise<{ id: number; work_day_id: number; employee_id: number; event_type: FieldEventType }> {
  const { data } = await api.post<{
    id: number;
    work_day_id: number;
    employee_id: number;
    event_type: FieldEventType;
  }>(`/nomina/field/work-days/${workDayId}/events/`, input);
  return data;
}

/** Traslada un trabajador entre cuadrillas de la jornada (motivo obligatorio). */
export async function transferFieldWorker(
  workDayId: number,
  input: { employee_id: number; from_crew_id: number; to_crew_id: number; reason: string },
): Promise<{
  id: number;
  work_day_id: number;
  employee_id: number;
  from_crew_id: number;
  to_crew_id: number;
}> {
  const { data } = await api.post<{
    id: number;
    work_day_id: number;
    employee_id: number;
    from_crew_id: number;
    to_crew_id: number;
  }>(`/nomina/field/work-days/${workDayId}/transfers/`, input);
  return data;
}

// --- Consolidación y aprobación SoD -----------------------------------------
// consolidar (consolidateFieldAttendance) y aplicar a planilla (applyFieldAttendance)
// viven en src/modules/nomina/api.ts; aquí va el resto del ciclo.

export const CONSOLIDATION_STATUS_LABELS: Record<string, string> = {
  OK: 'OK',
  WARNING: 'Advertencia',
  CONFLICT: 'Conflicto',
  BLOCKED: 'Bloqueado',
  APPROVED: 'Aprobado',
  LOCKED_FOR_PAYROLL: 'Bloqueado p/ nómina',
};

export interface FieldConsolidationRow {
  id: number;
  employee_id: number;
  work_day_id: number;
  work_date: string;
  payroll_period_id: number | null;
  status: string;
  day_value: string;
  primary_event_type: string;
  conflict_codes: string[];
  has_inss_snapshot: boolean;
  approved_at: string | null;
  locked_at: string | null;
}

/** Consolidaciones (una por empleado) de una jornada. No pagina. */
export async function listFieldConsolidations(workDayId: number): Promise<FieldConsolidationRow[]> {
  const { data } = await api.get<{ results: FieldConsolidationRow[] }>(
    `/nomina/field/work-days/${workDayId}/consolidations/`,
  );
  return data.results;
}

/**
 * SoD checker: aprueba la consolidación de la jornada. El código de solicitud
 * (UUID) lo genera el maker al pedir aprobación; el backend valida approver≠maker.
 */
export async function approveFieldWorkDay(
  requestId: string,
): Promise<FieldWorkDay & { consolidations: FieldConsolidationRow[] }> {
  const { data } = await api.post<FieldWorkDay & { consolidations: FieldConsolidationRow[] }>(
    `/nomina/field/approvals/${requestId}/approve/`,
    {},
  );
  return data;
}

// ===========================================================================
// Flujo de captura por cuadrilla (PR#17): field/crews, field/capture, field/reports
// ===========================================================================

/** Cuadrilla persistente del catálogo de captura (modelo Crew). */
export interface CaptureCrew {
  id: number;
  crew_id: string;
  company: number;
  branch: number;
  code: string;
  name: string;
  foreman: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** Lista cuadrillas del catálogo (paginado server-side). */
export async function listCaptureCrews(
  page: PageReq,
  filters: { branch_id?: number } = {},
): Promise<Paginated<CaptureCrew>> {
  const { data } = await api.get<Paginated<CaptureCrew>>('/nomina/field/crews/', {
    params: { ...filters, ...page },
  });
  return data;
}

/** Crea una cuadrilla persistente (requiere sucursal; capataz opcional). */
export async function createCaptureCrew(input: {
  branch_id: number;
  name: string;
  code?: string;
  foreman_id?: number | null;
}): Promise<CaptureCrew> {
  const { data } = await api.post<CaptureCrew>('/nomina/field/crews/', input);
  return data;
}

export type CaptureStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVAL_PENDING' | 'APPROVED';

export const CAPTURE_STATUS_LABELS: Record<CaptureStatus, string> = {
  DRAFT: 'Borrador',
  SUBMITTED: 'Enviado',
  APPROVAL_PENDING: 'Aprobación pendiente',
  APPROVED: 'Aprobado',
};

export interface CaptureWorkDay {
  id: number;
  work_day_id: string;
  company: number;
  branch: number;
  period: number;
  crew: number;
  work_date: string;
  status: CaptureStatus;
  submitted_by: number | null;
  submitted_at: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface CaptureReport {
  id: number;
  report_id: string;
  company: number;
  branch: number;
  period: number;
  work_day: number;
  crew: number;
  status: CaptureStatus;
  reported_by: number | null;
  submitted_at: string | null;
  approved_by: number | null;
  approved_at: string | null;
  approval_request: number | null;
  approval_request_uuid: string | null;
  observations: string;
  event_count: number;
  created_at: string;
  updated_at: string;
}

/**
 * Lista los REPORTES de captura (el GET de capture/work-days devuelve reportes,
 * uno por cuadrilla/fecha). Paginado server-side.
 */
export async function listCaptureReports(
  filters: { period_id?: number; crew_id?: number },
  page: PageReq,
): Promise<Paginated<CaptureReport>> {
  const { data } = await api.get<Paginated<CaptureReport>>('/nomina/field/capture/work-days/', {
    params: { ...filters, ...page },
  });
  return data;
}

/**
 * Crea (o reutiliza, es upsert por cuadrilla+fecha) la jornada de captura y su
 * reporte. La fecha debe caer dentro del período de nómina elegido.
 */
export async function createCaptureWorkDay(input: {
  period_id: number;
  crew_id: number;
  work_date: string;
  notes?: string;
  observations?: string;
}): Promise<{ work_day: CaptureWorkDay; report: CaptureReport }> {
  const { data } = await api.post<{ work_day: CaptureWorkDay; report: CaptureReport }>(
    '/nomina/field/capture/work-days/',
    input,
  );
  return data;
}

/** Tipos de evento del flujo de captura (FieldCaptureEvent.EventType). */
export type CaptureEventType =
  | 'PRESENT'
  | 'ABSENT'
  | 'SICK'
  | 'SUBSIDY'
  | 'ACCIDENT'
  | 'TRANSFER'
  | 'VACATION';

export const CAPTURE_EVENT_LABELS: Record<CaptureEventType, string> = {
  PRESENT: 'Presente',
  ABSENT: 'Ausente',
  SICK: 'Enfermo',
  SUBSIDY: 'Subsidio INSS',
  ACCIDENT: 'Accidente laboral',
  TRANSFER: 'Traslado',
  VACATION: 'Vacaciones',
};

export interface CaptureEvent {
  id: number;
  event_id: string;
  company: number;
  branch: number;
  period: number;
  work_day: number;
  report: number;
  crew: number;
  employee: number | null;
  cedula: string;
  employee_name: string;
  event_type: CaptureEventType;
  day_value: string;
  overtime_hours: string;
  sunday_worked_days: number;
  from_crew: number | null;
  to_crew: number | null;
  notes: string;
  recorded_by: number | null;
  recorded_at: string;
  created_at: string;
  updated_at: string;
}

/** Eventos de un reporte de captura (paginado server-side). */
export async function listCaptureEvents(
  reportId: number,
  page: PageReq,
): Promise<Paginated<CaptureEvent>> {
  const { data } = await api.get<Paginated<CaptureEvent>>(
    `/nomina/field/reports/${reportId}/events/`,
    { params: { ...page } },
  );
  return data;
}

/** Registra un evento de trabajador en el reporte (empleado de RH o cédula/nombre manual). */
export async function createCaptureEvent(
  reportId: number,
  input: {
    employee_id?: number | null;
    cedula?: string;
    employee_name?: string;
    event_type: CaptureEventType;
    day_value?: string;
    overtime_hours?: string;
    sunday_worked_days?: number;
    to_crew_id?: number | null;
    notes?: string;
  },
): Promise<CaptureEvent> {
  const { data } = await api.post<CaptureEvent>(`/nomina/field/reports/${reportId}/events/`, input);
  return data;
}

/** SoD maker (revisor): solicita la aprobación del reporte de captura. */
export async function requestCaptureApproval(
  reportId: number,
  reason: string,
): Promise<{ approval_request_id: string; report: CaptureReport }> {
  const { data } = await api.post<{ approval_request_id: string; report: CaptureReport }>(
    `/nomina/field/reports/${reportId}/approve/request/`,
    { reason },
  );
  return data;
}

/** SoD checker: aprueba el reporte con el código de solicitud del maker. */
export async function approveCaptureReport(
  reportId: number,
  input: { approval_request_id: string; note?: string },
): Promise<CaptureReport> {
  const { data } = await api.post<CaptureReport>(
    `/nomina/field/reports/${reportId}/approve/`,
    input,
  );
  return data;
}

/** Reporte legal de asistencia construido desde la captura aprobada. */
export interface AttendanceReportRow {
  id: number;
  report_id: string;
  company: number;
  branch: number;
  period: number;
  employee: number | null;
  employee_name: string;
  inss_number: string;
  cedula: string;
  source: string;
  status: string;
  days_worked: string;
  days_absent: string;
  days_sick: string;
  days_subsidy: string;
  days_accident: string;
  days_transferred: string;
  days_vacation: string;
  overtime_hours: string;
  sunday_worked_days: number;
  observations: string;
  approved_by: number | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Construye la asistencia legal (AttendanceReport) desde el reporte APROBADO. Idempotente. */
export async function buildCaptureAttendance(
  reportId: number,
): Promise<{ count: number; results: AttendanceReportRow[] }> {
  const { data } = await api.post<{ count: number; results: AttendanceReportRow[] }>(
    `/nomina/field/reports/${reportId}/build-attendance/`,
    {},
  );
  return data;
}
