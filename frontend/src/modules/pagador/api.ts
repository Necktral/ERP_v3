/**
 * Pagador de Nómina — capa de datos tipada.
 *
 * Lectura: resumen consolidado por empleado del período (planillas legales CON/SIN INSS +
 * complemento). Escritura: registro del pago del neto LEGAL completo (idempotente).
 *
 * PROHIBIDO: la nómina NO cobra comisariato ni préstamos personales. El Pagador SOLO entrega el
 * neto legal (devengado − INSS/IR); no hay cobro/recaudación de deudas internas en este flujo.
 *
 * La app es offline-first: el resumen se cachea en SQLite y los pagos se encolan; este módulo
 * solo habla con el servidor (la persistencia local vive en `offline/store.ts`).
 */
import { api } from 'src/boot/axios';

export type PayMethod = 'CASH' | 'BANK_TRANSFER' | 'CHECK';

export interface PaySummaryDeductions {
  inss_laboral: string;
  ir_amount: string;
  loan_payment: string;
  store_credit_deduction: string;
  advance_deduction: string;
  food_deduction: string;
  other_deductions: string;
  total_deductions: string;
}

export interface PaySummarySheet {
  sheet_id: number;
  sheet_name: string;
  has_inss: boolean;
  status: string;
  entry_id: number;
  location: string; // sucursal/finca de la planilla (Santa Isabel, Las Morenas…)
  print_no: number; // No. del trabajador en la planilla IMPRESA
  print_page: number; // hoja del papel donde cae
  total_devengado: string;
  net_to_pay: string;
  already_paid: string;
  remaining: string;
  paid: boolean;
  deductions: PaySummaryDeductions;
}

export interface PaySummaryComplement {
  complement_sheet_id: number;
  line_id: number;
  amount_nio: string;
  received: boolean;
}

export interface PaySummaryTotales {
  neto_total_a_entregar: string;
  pagado: string;
  pendiente: string;
}

export interface PaySummaryRow {
  employee_key: string;
  employee_id: number | null;
  employee_code: string;
  inss_number: string;
  cedula: string;
  worker_code: string; // carnet (ID único de persona del holding)
  full_name: string;
  cargo: string;
  ubicacion: string; // planilla/finca donde está (para la tarjeta)
  planillas: string[];
  sheets: PaySummarySheet[];
  complement: PaySummaryComplement | null;
  totales: PaySummaryTotales;
}

export interface PaySummaryResponse {
  period: { id: number; year: number; month: number; period_type: string; status: string };
  branch_id: number | null;
  count: number;
  results: PaySummaryRow[];
}

export interface PaymentResult {
  id: number;
  entry_id: number;
  payment_method: PayMethod;
  amount: string;
  payment_date: string;
  reference: string;
  notes: string;
  created_at: string;
}

/** Trae el resumen consolidado del período (online). El branch/company viajan por headers. */
export async function getPaySummary(periodId: number, opts: { branch?: number; search?: string } = {}): Promise<PaySummaryResponse> {
  const params: Record<string, string> = {};
  if (opts.branch) params.branch = String(opts.branch);
  if (opts.search) params.search = opts.search;
  const { data } = await api.get<PaySummaryResponse>(`/nomina/periods/${periodId}/pay-summary/`, { params });
  return data;
}

// --- Cobro NEGOCIADO al pagar (deudas internas: comisariato + préstamo) -----------------------
// El CO-PA cobra deudas INTERNAS de empresa al pagar (NO van en el documento legal). El cruce
// del comisariato es multi-empresa (otra compañía, relación CXC); el préstamo es intra-finca.
export interface DeudaRow {
  entry_id: number;
  cedula: string;
  worker_code: string;
  comisariato_saldo: string;
  prestamo_saldo: string;
}

/** Saldos de deuda (comisariato + préstamo) por entrada del período, para negociar el abono. */
export async function getDeudasPlanilla(periodId: number): Promise<DeudaRow[]> {
  const { data } = await api.get<{ results: DeudaRow[] }>(`/comisariato/payroll/deudas/${periodId}/`);
  return data.results;
}

export interface CobrarYPagarResult {
  payment_id: number | null;
  neto_entregado: string;
  abono_comisariato: string;
  abono_prestamo: string;
}

export interface RectificarCobroResult extends CobrarYPagarResult {
  recibo_anulado: number | null; // No. del recibo previo que queda ANULADO
  motivo: string;
}

/**
 * Negocia el abono parcial por deuda (comisariato/préstamo) y paga el neto a entregar.
 * El abono baja el neto y abona la deuda; el resto se entrega en efectivo. Idempotente.
 */
export async function cobrarYPagar(input: {
  periodId: number;
  sheetId: number;
  entryId: number;
  abonoComisariato: string;
  abonoPrestamo: string;
  paymentMethod: PayMethod;
  idempotencyKey: string;
}): Promise<CobrarYPagarResult> {
  const { data } = await api.post<CobrarYPagarResult>(
    `/comisariato/payroll/cobrar-y-pagar/${input.periodId}/${input.sheetId}/${input.entryId}/`,
    {
      abono_comisariato: input.abonoComisariato,
      abono_prestamo: input.abonoPrestamo,
      payment_method: input.paymentMethod,
      idempotency_key: input.idempotencyKey,
    },
  );
  return data;
}

/**
 * Rectifica un cobro YA aplicado (el pagador se equivocó de monto): reversa los abonos previos,
 * anula el recibo anterior y reemite con el monto correcto. `motivo` es obligatorio.
 */
export async function rectificarCobro(input: {
  periodId: number;
  sheetId: number;
  entryId: number;
  abonoComisariato: string;
  abonoPrestamo: string;
  paymentMethod: PayMethod;
  motivo: string;
  idempotencyKey: string;
}): Promise<RectificarCobroResult> {
  const { data } = await api.post<RectificarCobroResult>(
    `/comisariato/payroll/rectificar/${input.periodId}/${input.sheetId}/${input.entryId}/`,
    {
      abono_comisariato: input.abonoComisariato,
      abono_prestamo: input.abonoPrestamo,
      payment_method: input.paymentMethod,
      motivo: input.motivo,
      idempotency_key: input.idempotencyKey,
    },
  );
  return data;
}

/** Registra el pago del neto de una línea. `idempotencyKey` hace seguro el reintento offline. */
export async function payEntry(input: {
  periodId: number;
  sheetId: number;
  entryId: number;
  paymentMethod: PayMethod;
  amount: string;
  idempotencyKey: string;
}): Promise<PaymentResult> {
  const { data } = await api.post<PaymentResult>(
    `/nomina/periods/${input.periodId}/sheets/${input.sheetId}/entries/${input.entryId}/pay/`,
    {
      payment_method: input.paymentMethod,
      amount: input.amount,
      idempotency_key: input.idempotencyKey,
    },
  );
  return data;
}
