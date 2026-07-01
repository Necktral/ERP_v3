/**
 * Nómina (planilla) — capa de datos tipada del kernel `nomina`.
 *
 * Flujo del planillero: config del año (una vez) → período → planilla(s) →
 * entradas (aplicar asistencia de campo o agregar manual) → calcular →
 * enviar/aprobar → exportar XLSX/PDF legal.
 */
import { api } from 'src/boot/axios';
import { PAGE, type Paginated } from 'src/core/api';

// --- Configuración (tasas + IR) ---------------------------------------------
export interface NominaConfig {
  id: number;
  fiscal_year: number;
  effective_from: string;
  is_active: boolean;
  inss_laboral_rate: string;
  inss_patronal_rate_small: string;
  inss_patronal_rate_large: string;
  inatec_rate: string;
  vacation_rate: string;
  thirteenth_month_rate: string;
  min_wage_agro: string;
  ir_brackets: { id: number; order: number; min_income: string; max_income: string | null; base_tax: string; rate: string }[];
}

export async function listConfigs(): Promise<NominaConfig[]> {
  const { data } = await api.get<Paginated<NominaConfig>>('/nomina/config/', { params: PAGE });
  return data.results;
}

export async function createDefaultConfig(fiscalYear?: number): Promise<NominaConfig> {
  const { data } = await api.post<NominaConfig>('/nomina/config/', fiscalYear ? { fiscal_year: fiscalYear } : {});
  return data;
}

export interface IRBracketInput {
  order: number;
  min_income: string;
  max_income: string | null;
  base_tax: string;
  rate: string;
}

/** Upsert de los tramos del IR de una config del año (cierra #4 del audit). */
export async function upsertIrBrackets(
  configId: number,
  brackets: IRBracketInput[],
): Promise<NominaConfig['ir_brackets']> {
  const { data } = await api.post<NominaConfig['ir_brackets']>(
    `/nomina/config/${configId}/ir-brackets/`,
    { brackets },
  );
  return data;
}

/** Historial de afiliaciones INSS (fechadas) de un empleado (cierra #4 del audit). */
export async function listEmployeeInssEnrollments(
  employeeId: number,
): Promise<Record<string, unknown>[]> {
  const { data } = await api.get<{ results: Record<string, unknown>[] }>(
    `/nomina/inss/employees/${employeeId}/enrollments/`,
  );
  return data.results;
}

// --- Períodos -----------------------------------------------------------------
export type PeriodType = 'FIRST_HALF' | 'SECOND_HALF' | 'CATORCENA' | 'MONTHLY';
export type PeriodStatus = 'DRAFT' | 'IN_REVIEW' | 'APPROVED' | 'PAID' | 'CLOSED';

export interface PayrollPeriod {
  id: number;
  year: number;
  month: number;
  period_type: PeriodType;
  start_date: string;
  end_date: string;
  working_days: number;
  exchange_rate_usd: string;
  status: PeriodStatus;
  total_gross: string;
  total_deductions: string;
  total_net: string;
  total_patronal: string;
  total_payroll_cost: string;
  notes: string;
}

export async function listPeriods(params: { year?: number; status?: string } = {}): Promise<PayrollPeriod[]> {
  const { data } = await api.get<Paginated<PayrollPeriod>>('/nomina/periods/', {
    params: { ...PAGE, ...params },
  });
  return data.results;
}

export async function createPeriod(input: {
  year: number;
  month: number;
  period_type: PeriodType;
  start_date: string;
  end_date: string;
  working_days?: number;
  exchange_rate_usd?: string | null;
  notes?: string;
}): Promise<PayrollPeriod> {
  const { data } = await api.post<PayrollPeriod>('/nomina/periods/', input);
  return data;
}

// --- Planillas (sheets) --------------------------------------------------------
export type SheetStatus = 'DRAFT' | 'SUBMITTED' | 'REVIEWED' | 'APPROVED' | 'REJECTED';

export interface PayrollSheet {
  id: number;
  sheet_name: string;
  has_inss: boolean;
  status: SheetStatus;
  entry_count: number;
  notes: string;
  submitted_at: string | null;
  approved_at: string | null;
}

export async function listSheets(periodId: number): Promise<PayrollSheet[]> {
  const { data } = await api.get<Paginated<PayrollSheet>>(`/nomina/periods/${periodId}/sheets/`, {
    params: PAGE,
  });
  return data.results;
}

export async function createSheet(
  periodId: number,
  input: { sheet_name: string; has_inss: boolean; branch_id?: number | null; notes?: string },
): Promise<PayrollSheet> {
  const { data } = await api.post<PayrollSheet>(`/nomina/periods/${periodId}/sheets/`, input);
  return data;
}

export async function sheetAction(
  periodId: number,
  sheetId: number,
  action: 'submit' | 'approve' | 'compute',
): Promise<{ computed?: number }> {
  const { data } = await api.post<{ computed?: number }>(
    `/nomina/periods/${periodId}/sheets/${sheetId}/${action}/`,
    {},
  );
  return data;
}

export async function applyFieldAttendance(sheetId: number): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>(
    `/nomina/field/sheets/${sheetId}/apply-field-attendance/`,
    {},
  );
  return data;
}

// --- Consolidación de asistencia de campo (cierra el día → planilla en revisión) ---
/** Una fila por empleado/día con su valor de día (1 / 0.5 / 0) y estado de control. */
export interface FieldConsolidation {
  id: number;
  employee_id: number;
  work_day_id: number;
  work_date: string;
  payroll_period_id: number | null;
  status: string; // OK | WARNING | CONFLICT | BLOCKED | APPROVED | LOCKED_FOR_PAYROLL
  day_value: string; // "1.00" | "0.50" | "0.00"
  primary_event_type: string;
  conflict_codes: string[];
  has_inss_snapshot: boolean;
}

export interface FieldConsolidateResult {
  id: number; // work_day_id
  status: string; // estado del día (pasa a IN_REVIEW)
  payroll_period_id: number | null;
  consolidations: FieldConsolidation[];
}

/**
 * Consolida las marcas del día de campo (work_day) hacia un período de planilla.
 * Idempotente: re-consolidar reprocesa salvo las consolidaciones ya aprobadas/bloqueadas.
 */
export async function consolidateFieldAttendance(
  workDayId: number,
  payrollPeriodId: number,
): Promise<FieldConsolidateResult> {
  const { data } = await api.post<FieldConsolidateResult>(
    `/nomina/field/work-days/${workDayId}/consolidate/`,
    { payroll_period_id: payrollPeriodId },
  );
  return data;
}

// --- Entradas (líneas de planilla) ----------------------------------------------
/** Línea de planilla — MISMAS casillas que la planilla legal en Excel (carpeta excel/). */
export interface PayrollEntry {
  id: number;
  inss_number: string;
  cedula: string;
  full_name: string;
  gender: string;
  cargo: string;
  has_inss: boolean;
  salary_type: 'MONTHLY' | 'DAILY' | 'HOURLY';
  daily_rate_nio: string; // Salario Diario
  base_salary_nio: string; // Salario Mensual
  // INGRESOS
  quincenal_salary: string; // Salario del Período
  days_in_period: number;
  days_worked: string; // Días Laborados
  overtime_hours: string; // Horas Extra (captura)
  overtime_amount: string; // Horas Extra (monto)
  sunday_worked_days: number; // Domingos laborados (captura)
  sunday_bonus_amount: string; // Domingos (monto)
  seventh_day_days: string; // Séptimo Día
  seventh_day_amount: string;
  holiday_worked_days: string; // Feriados laborados (captura)
  holiday_amount: string;
  days_subsidy: string; // Días Subsidio
  subsidy_amount: string; // Subsidio
  other_income: string; // Otros Ingresos (viáticos/bonos)
  alimentacion_amount: string; // ALIMENTOS: alimentación de la empresa (SUMA al neto)
  vacation_provision: string; // Vacaciones (ingreso)
  thirteenth_month_provision: string; // 13vo Mes (ingreso)
  total_income: string; // Total Ingresos
  /** Captura de asistencia día-por-día (planilla fiel): {"YYYY-MM-DD": "P"|"A"|"M"|"S"|"V"|"F"|"D"}. */
  daily_attendance: Record<string, string>;
  // RETENCIONES
  inss_laboral: string; // INSS
  ir_amount: string; // IR
  loan_payment: string; // Abono Préstamos
  total_deductions: string; // Total Retención
  // OTRAS DEDUCCIONES
  food_deduction: string; // Alimentación
  advance_deduction: string; // Adelanto Finca
  store_credit_deduction: string; // Crédito Comisariato
  other_deductions: string; // Otras Deducciones
  // Totales
  total_devengado: string; // Salario Devengado
  net_to_pay: string; // Neto a Pagar
  // COSTOS PATRONALES
  inss_patronal: string;
  vacation_cost: string;
  thirteenth_month_cost: string;
  inatec: string; // INATEC 2%
  total_employer_cost: string;
  total_payroll_cost: string; // Total Gastos Nómina
  notes: string;
}

export async function listEntries(
  periodId: number,
  sheetId: number,
  search = '',
): Promise<PayrollEntry[]> {
  const { data } = await api.get<Paginated<PayrollEntry>>(
    `/nomina/periods/${periodId}/sheets/${sheetId}/entries/`,
    { params: { ...PAGE, ...(search ? { search } : {}) } },
  );
  return data.results;
}

export interface EntryInput {
  /** Con employee_id el backend autollena del expediente HR (cédula, INSS, género, cargo, salario). */
  employee_id?: number | null;
  /** Obligatorio solo para entradas manuales (sin expediente). */
  full_name?: string;
  cedula?: string;
  inss_number?: string;
  cargo?: string;
  has_inss?: boolean;
  salary_type?: 'MONTHLY' | 'DAILY' | 'HOURLY';
  payment_frequency: PeriodType;
  /** Mensuales: salario del mes. */
  base_salary_nio?: string;
  /** Jornaleros (DAILY): el jornal del día tal cual; el backend lo lleva a base mensual. */
  daily_rate_nio?: string;
  days_in_period: number;
  days_worked: string;
  notes?: string;
}

export async function createEntry(
  periodId: number,
  sheetId: number,
  input: EntryInput,
): Promise<PayrollEntry> {
  const { data } = await api.post<PayrollEntry>(
    `/nomina/periods/${periodId}/sheets/${sheetId}/entries/`,
    input,
  );
  return data;
}

/**
 * Campos editables de una línea EXISTENTE (planilla en borrador): asistencia,
 * horas extra, domingos/séptimo/feriados, otros ingresos y deducciones manuales.
 * Crédito comisariato y abono de préstamos se llenan por integración (no acá).
 * Todos opcionales: viajan solo los que cambian y el backend recalcula.
 */
export interface EntryUpdateInput {
  days_in_period?: number;
  days_worked?: string;
  days_subsidy?: string;
  overtime_hours?: string;
  sunday_worked_days?: number;
  seventh_day_days?: string;
  holiday_worked_days?: string;
  other_income?: string;
  alimentacion_amount?: string;
  food_deduction?: string;
  advance_deduction?: string;
  other_deductions?: string;
  notes?: string;
}

export async function updateEntry(
  periodId: number,
  sheetId: number,
  entryId: number,
  input: EntryUpdateInput,
): Promise<PayrollEntry> {
  const { data } = await api.patch<PayrollEntry>(
    `/nomina/periods/${periodId}/sheets/${sheetId}/entries/${entryId}/`,
    input,
  );
  return data;
}

/**
 * Fija la captura de asistencia DÍA-POR-DÍA de una línea (planilla fiel) y recalcula.
 * `marks` = {"YYYY-MM-DD": código}. De la captura el backend deriva días/séptimo/domingos (legal).
 */
export async function setDailyAttendance(
  periodId: number,
  sheetId: number,
  entryId: number,
  marks: Record<string, string>,
): Promise<PayrollEntry> {
  const { data } = await api.post<PayrollEntry>(
    `/nomina/periods/${periodId}/sheets/${sheetId}/entries/${entryId}/daily-attendance/`,
    { marks },
  );
  return data;
}

export async function deleteEntry(
  periodId: number,
  sheetId: number,
  entryId: number,
): Promise<void> {
  await api.delete(`/nomina/periods/${periodId}/sheets/${sheetId}/entries/${entryId}/`);
}

// --- Export legal (XLSX / PDF) — vía blob para mantener cookies + contexto ------
export async function downloadPlanilla(
  periodId: number,
  sheetId: number,
  format: 'xlsx' | 'pdf',
): Promise<void> {
  const url = `/nomina/periods/${periodId}/sheets/${sheetId}/planilla.${format}`;
  const { data } = await api.get<Blob>(url, { responseType: 'blob' });
  const objectUrl = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = `planilla_${periodId}_${sheetId}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

// --- Complemento de salario (convenio personal, bruto en recibo) ----------------
// Planilla replicada, desacoplada de la legal (NO crea PayrollEntry/INSS): net = gross.
// Vive bajo un período. SoD: manage arma/envía (maker), approve aprueba (checker).
// Perms: nomina.complement.read/manage/approve.
export type ComplementStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED';
export const COMPLEMENT_STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Borrador',
  SUBMITTED: 'Enviada al encargado',
  APPROVED: 'Aprobada',
};
export interface ComplementSheetRow {
  id: number;
  name: string;
  status: ComplementStatus;
  branch_id: number | null;
  lines: number;
  created_at: string;
}
export interface ComplementLine {
  id: number;
  employee_id: number;
  full_name: string;
  cedula: string;
  cargo: string;
  devengado_nio: string;
  neto_nio: string;
  received_at: string | null;
}
export interface ComplementSheetDetail {
  id: number;
  period_id: number;
  branch_id: number | null;
  name: string;
  status: ComplementStatus;
  subtotal_nio: string;
  lines: ComplementLine[];
  created_at: string;
}
export async function listComplementSheets(
  periodId: number,
  status?: string,
): Promise<ComplementSheetRow[]> {
  const { data } = await api.get<{ results: ComplementSheetRow[] }>(
    `/nomina/periods/${periodId}/complement-sheets/`,
    { params: status ? { status } : undefined },
  );
  return data.results;
}
export async function createComplementSheet(
  periodId: number,
  body: { branch_id?: number | null; name?: string },
): Promise<ComplementSheetDetail> {
  const { data } = await api.post<ComplementSheetDetail>(
    `/nomina/periods/${periodId}/complement-sheets/`,
    body,
  );
  return data;
}
export async function getComplementSheet(
  periodId: number,
  sheetId: number,
): Promise<ComplementSheetDetail> {
  const { data } = await api.get<ComplementSheetDetail>(
    `/nomina/periods/${periodId}/complement-sheets/${sheetId}/`,
  );
  return data;
}
export async function complementAction(
  periodId: number,
  sheetId: number,
  action: 'submit' | 'approve',
): Promise<ComplementSheetDetail> {
  const { data } = await api.post<ComplementSheetDetail>(
    `/nomina/periods/${periodId}/complement-sheets/${sheetId}/${action}/`,
    {},
  );
  return data;
}
export async function setComplementLineAmount(
  periodId: number,
  sheetId: number,
  lineId: number,
  amountNio: number,
): Promise<{ id: number; amount_nio: string }> {
  const { data } = await api.patch<{ id: number; amount_nio: string }>(
    `/nomina/periods/${periodId}/complement-sheets/${sheetId}/lines/${lineId}/`,
    { amount_nio: amountNio },
  );
  return data;
}
export async function markComplementReceived(
  periodId: number,
  sheetId: number,
  lineId: number,
  note = '',
): Promise<{ id: number; received_at: string }> {
  const { data } = await api.post<{ id: number; received_at: string }>(
    `/nomina/periods/${periodId}/complement-sheets/${sheetId}/lines/${lineId}/`,
    { note },
  );
  return data;
}
export async function downloadComplementRecibo(periodId: number, sheetId: number): Promise<void> {
  const url = `/nomina/periods/${periodId}/complement-sheets/${sheetId}/recibo.pdf`;
  const { data } = await api.get<Blob>(url, { responseType: 'blob' });
  const objectUrl = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = `complemento_${periodId}_${sheetId}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

// --- Régimen INSS por período (resuelve el shuffle CON/SIN INSS) -----------------
// La afiliación (verdad maestra, fechada) se administra en el perfil del empleado.
// Aquí, por período: ver/ajustar la elección de cada trabajador, RESOLVER (materializa
// desde la afiliación) y CLASIFICAR (mueve cada línea a la planilla CON/SIN INSS y recalcula).
// Perms: nomina.inss.read (ver) · nomina.inss.manage (escribir/resolver/clasificar).
export interface InssElection {
  id: number;
  period_id: number;
  employee_id: number | null;
  cedula: string;
  elected_has_inss: boolean;
  source: string;
  reason: string;
  created_at: string;
  updated_at: string;
}
export const INSS_SOURCE_LABELS: Record<string, string> = {
  ENROLLMENT: 'Afiliación',
  OVERRIDE: 'Ajuste manual',
  MANUAL: 'Ajuste manual',
  DEFAULT: 'Por defecto',
};
export async function listInssElections(periodId: number): Promise<InssElection[]> {
  const { data } = await api.get<{ results: InssElection[] }>(
    `/nomina/periods/${periodId}/inss/elections/`,
  );
  return data.results;
}
export async function setInssElection(
  periodId: number,
  body: { employee_id?: number | null; cedula?: string; elected_has_inss: boolean; reason?: string },
): Promise<InssElection> {
  const { data } = await api.post<InssElection>(`/nomina/periods/${periodId}/inss/elections/`, body);
  return data;
}
export async function resolveInssElections(
  periodId: number,
): Promise<{ elections: Record<string, boolean> }> {
  const { data } = await api.post<{ elections: Record<string, boolean> }>(
    `/nomina/periods/${periodId}/inss/resolve/`,
    {},
  );
  return data;
}
export async function classifyInssEntries(
  periodId: number,
): Promise<{ updated: number; moved: number; elections: Record<string, boolean> }> {
  const { data } = await api.post<{ updated: number; moved: number; elections: Record<string, boolean> }>(
    `/nomina/periods/${periodId}/inss/classify/`,
    {},
  );
  return data;
}
