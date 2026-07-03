/**
 * Helpers de presentación compartidos por las páginas de asistencia de campo
 * (mapas de EstadoChip, etiquetas de período y carga de selects de personal).
 */
import type { EstadoEstilo } from 'src/components/EstadoChip.vue';
import { listEmployees, type EmployeeRow } from 'src/modules/hr/api';
import type { PayrollPeriod } from 'src/modules/nomina/api';
import {
  CAPTURE_STATUS_LABELS,
  CONSOLIDATION_STATUS_LABELS,
  WORK_DAY_STATUS_LABELS,
} from './api';

// --- Mapas para EstadoChip ---------------------------------------------------

export const MAPA_ESTADO_JORNADA: Record<string, EstadoEstilo> = {
  OPEN: { label: WORK_DAY_STATUS_LABELS.OPEN, color: 'info', outline: true },
  ROLLCALL_SUBMITTED: {
    label: WORK_DAY_STATUS_LABELS.ROLLCALL_SUBMITTED,
    color: 'primary',
    outline: true,
  },
  CREW_REPORTS_PENDING: {
    label: WORK_DAY_STATUS_LABELS.CREW_REPORTS_PENDING,
    color: 'warning',
    outline: true,
  },
  IN_REVIEW: { label: WORK_DAY_STATUS_LABELS.IN_REVIEW, color: 'warning', textColor: 'white' },
  APPROVED: { label: WORK_DAY_STATUS_LABELS.APPROVED, color: 'positive', textColor: 'white' },
  LOCKED: { label: WORK_DAY_STATUS_LABELS.LOCKED, color: 'grey-9', textColor: 'white' },
};

export const MAPA_ESTADO_CAPTURA: Record<string, EstadoEstilo> = {
  DRAFT: { label: CAPTURE_STATUS_LABELS.DRAFT, color: 'grey-7', outline: true },
  SUBMITTED: { label: CAPTURE_STATUS_LABELS.SUBMITTED, color: 'primary', outline: true },
  APPROVAL_PENDING: {
    label: CAPTURE_STATUS_LABELS.APPROVAL_PENDING,
    color: 'warning',
    textColor: 'white',
  },
  APPROVED: { label: CAPTURE_STATUS_LABELS.APPROVED, color: 'positive', textColor: 'white' },
};

export const MAPA_ESTADO_CONSOLIDACION: Record<string, EstadoEstilo> = {
  OK: { label: CONSOLIDATION_STATUS_LABELS.OK ?? 'OK', color: 'positive', outline: true },
  WARNING: {
    label: CONSOLIDATION_STATUS_LABELS.WARNING ?? 'Advertencia',
    color: 'warning',
    outline: true,
  },
  CONFLICT: {
    label: CONSOLIDATION_STATUS_LABELS.CONFLICT ?? 'Conflicto',
    color: 'negative',
    textColor: 'white',
  },
  BLOCKED: {
    label: CONSOLIDATION_STATUS_LABELS.BLOCKED ?? 'Bloqueado',
    color: 'negative',
    outline: true,
  },
  APPROVED: {
    label: CONSOLIDATION_STATUS_LABELS.APPROVED ?? 'Aprobado',
    color: 'positive',
    textColor: 'white',
  },
  LOCKED_FOR_PAYROLL: {
    label: CONSOLIDATION_STATUS_LABELS.LOCKED_FOR_PAYROLL ?? 'Bloqueado p/ nómina',
    color: 'grey-9',
    textColor: 'white',
  },
};

// --- Etiqueta legible de un período de planilla -------------------------------

const MESES = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
];

const TIPO_PERIODO: Record<string, string> = {
  FIRST_HALF: '1ª quincena',
  SECOND_HALF: '2ª quincena',
  CATORCENA: 'catorcena',
  MONTHLY: 'mensual',
};

export function etiquetaPeriodo(p: PayrollPeriod): string {
  const mes = MESES[(p.month ?? 1) - 1] ?? '';
  const tipo = TIPO_PERIODO[p.period_type] ?? p.period_type;
  return `#${p.id} · ${mes} ${p.year} · ${tipo}`;
}

// --- Select de trabajadores (personal activo de RH) ----------------------------

export interface OpcionEmpleado {
  value: number;
  label: string;
  emp: EmployeeRow;
}

/** Carga el personal como opciones de q-select ("Nombre Apellido (código)"). */
export async function cargarOpcionesEmpleados(): Promise<OpcionEmpleado[]> {
  const emps = await listEmployees();
  return emps.map((e) => ({
    value: e.id,
    label:
      `${e.first_name} ${e.last_name}`.trim() + (e.employee_code ? ` (${e.employee_code})` : ''),
    emp: e,
  }));
}

/** Filtro estándar de q-select con use-input sobre opciones de empleados. */
export function filtrarOpciones<T extends { label: string }>(
  todas: T[],
  input: string,
): T[] {
  const q = input.trim().toLowerCase();
  if (!q) return todas;
  return todas.filter((o) => o.label.toLowerCase().includes(q));
}
