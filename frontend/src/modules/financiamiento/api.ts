/**
 * Acopio de café + Financiamiento a productores (ex-SIFA "DON OSMAN COFFEE").
 * Mapea los endpoints reales del backend (`apps.modulos.financiamiento`). Las
 * pantallas NO llaman axios directo: usan estas funciones tipadas.
 * Montaje backend: `api/financiamiento/` → con baseURL `/api` => `/financiamiento/...`.
 */
import { api } from 'src/boot/axios';

export type Currency = 'NIO' | 'USD';
export type DisbursementForm = 'CASH' | 'CHECK' | 'TRANSFER' | 'IN_KIND';
export type ApplicationStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'REJECTED' | 'DISBURSED';
export type LoanStatus = 'ACTIVE' | 'PAID' | 'CANCELLED';
export type FixationStatus = 'OPEN' | 'LIQUIDATED';
export type PhysicalState = 'MOJADO' | 'HUMEDO' | 'OREADO' | 'SECO';

export const CURRENCY_LABELS: Record<string, string> = { NIO: 'Córdoba (C$)', USD: 'Dólar (US$)' };
export const DISBURSEMENT_LABELS: Record<string, string> = {
  CASH: 'Efectivo',
  CHECK: 'Cheque',
  TRANSFER: 'Transferencia',
  IN_KIND: 'Especie (insumos)',
};
export const APPLICATION_STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Borrador',
  SUBMITTED: 'Presentada',
  APPROVED: 'Aprobada',
  REJECTED: 'Rechazada',
  DISBURSED: 'Desembolsada',
};
export const LOAN_STATUS_LABELS: Record<string, string> = {
  ACTIVE: 'Activo',
  PAID: 'Cancelado',
  CANCELLED: 'Anulado',
};
export const FIXATION_STATUS_LABELS: Record<string, string> = {
  OPEN: 'Fijada (sin liquidar)',
  LIQUIDATED: 'Liquidada',
};
export const PHYSICAL_STATE_LABELS: Record<string, string> = {
  MOJADO: 'Mojado',
  HUMEDO: 'Húmedo',
  OREADO: 'Oreado',
  SECO: 'Pergamino seco',
};

// ---------- Productores ----------
export interface ProducerRow {
  id: number;
  party_id: number;
  party_name: string;
  national_id: string;
  acopio_code: string;
  certifications: string;
  is_active: boolean;
  notes: string;
}
export interface ProducerDeposit {
  received_lb: string;
  fixed_lb: string;
  liquidated_lb: string;
  available_to_fix_lb: string;
  in_custody_lb: string;
}

export async function listProducers(): Promise<ProducerRow[]> {
  const { data } = await api.get<{ results: ProducerRow[] }>('/financiamiento/producers/');
  return data.results;
}
export async function createProducer(body: {
  party_id: number;
  acopio_code?: string;
  certifications?: string;
  notes?: string;
}): Promise<ProducerRow> {
  const { data } = await api.post<ProducerRow>('/financiamiento/producers/', body);
  return data;
}
export async function producerDeposit(producerId: number): Promise<ProducerDeposit> {
  const { data } = await api.get<ProducerDeposit>(`/financiamiento/producers/${producerId}/deposit/`);
  return data;
}

// ---------- Calidades de café ----------
export interface QualityRow {
  id: number;
  code: string;
  name: string;
  default_tare_pct: string;
  is_active: boolean;
}
export async function listQualities(): Promise<QualityRow[]> {
  const { data } = await api.get<{ results: QualityRow[] }>('/financiamiento/qualities/');
  return data.results;
}
export async function createQuality(body: {
  code: string;
  name: string;
  default_tare_pct?: number;
}): Promise<QualityRow> {
  const { data } = await api.post<QualityRow>('/financiamiento/qualities/', body);
  return data;
}

// ---------- Tasa de cambio ----------
export interface ExchangeRateRow {
  id: number;
  rate_date: string;
  rate: string;
}
export async function listRates(): Promise<ExchangeRateRow[]> {
  const { data } = await api.get<{ results: ExchangeRateRow[] }>('/financiamiento/exchange-rates/');
  return data.results;
}
export async function upsertRate(body: { rate_date: string; rate: number }): Promise<ExchangeRateRow> {
  const { data } = await api.post<ExchangeRateRow>('/financiamiento/exchange-rates/', body);
  return data;
}

// ---------- Solicitudes de financiamiento ----------
export interface ApplicationRow {
  id: number;
  producer_id: number;
  producer_name: string;
  requested_nio: string;
  requested_usd: string;
  term_months: number;
  credit_type: string;
  activity: string;
  interest_rate: string;
  penalty_rate: string;
  commission_rate: string;
  disbursement_form: DisbursementForm;
  guarantee_farm_area_mz: string;
  guarantee_solar: string;
  guarantee_other: string;
  guarantee_coffee_qq: string;
  status: ApplicationStatus;
  submitted_at: string | null;
  decided_at: string | null;
  rejection_reason: string;
  created_at: string;
}
export interface ApplicationCreate {
  producer_id: number;
  requested_nio?: number;
  requested_usd?: number;
  term_months: number;
  credit_type?: string;
  activity?: string;
  interest_rate: number;
  penalty_rate?: number;
  commission_rate?: number;
  disbursement_form?: DisbursementForm;
  guarantee_farm_area_mz?: number;
  guarantee_solar?: string;
  guarantee_other?: string;
  guarantee_coffee_qq?: number;
}
export async function listApplications(): Promise<ApplicationRow[]> {
  const { data } = await api.get<{ results: ApplicationRow[] }>('/financiamiento/applications/');
  return data.results;
}
export async function createApplication(body: ApplicationCreate): Promise<ApplicationRow> {
  const { data } = await api.post<ApplicationRow>('/financiamiento/applications/', body);
  return data;
}
export async function submitApplication(id: number): Promise<ApplicationRow> {
  const { data } = await api.post<ApplicationRow>(`/financiamiento/applications/${id}/submit/`, {});
  return data;
}
export async function approveApplication(id: number): Promise<ApplicationRow> {
  const { data } = await api.post<ApplicationRow>(`/financiamiento/applications/${id}/approve/`, {});
  return data;
}
export async function rejectApplication(id: number, reason: string): Promise<ApplicationRow> {
  const { data } = await api.post<ApplicationRow>(`/financiamiento/applications/${id}/reject/`, { reason });
  return data;
}
export async function disburseApplication(
  id: number,
  body: { disbursement_date?: string; reference?: string },
): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>(
    `/financiamiento/applications/${id}/disburse/`,
    body,
  );
  return data;
}

// ---------- Préstamos ----------
export interface LoanRow {
  id: number;
  reference: string;
  producer_id: number;
  producer_name: string;
  credit_type: string;
  activity: string;
  interest_rate: string;
  penalty_rate: string;
  commission_rate: string;
  term_months: number;
  maturity_date: string;
  disbursement_form: DisbursementForm;
  disbursed_at: string | null;
  status: LoanStatus;
  created_at: string;
}
export interface LoanBalance {
  principal: string;
  interest: string;
  fee: string;
  penalty: string;
  allocated: string;
  outstanding: string;
  days_overdue: number;
}
export interface LoanStatement {
  loan_id: number;
  reference: string;
  status: LoanStatus;
  producer: string;
  maturity_date: string;
  balances: Record<string, LoanBalance>;
  consolidated_nio: string | null;
  rate_used: string | null;
}
export async function listLoans(status?: LoanStatus): Promise<LoanRow[]> {
  const { data } = await api.get<{ results: LoanRow[] }>('/financiamiento/loans/', {
    params: status ? { status } : undefined,
  });
  return data.results;
}
export async function loanStatement(loanId: number): Promise<LoanStatement> {
  const { data } = await api.get<LoanStatement>(`/financiamiento/loans/${loanId}/statement/`);
  return data;
}
export async function registerLoanPayment(
  loanId: number,
  body: {
    amount: number;
    paid_currency: Currency;
    target_currency?: Currency | '';
    payment_method?: string;
    exchange_rate?: number | null;
    payment_date?: string | null;
    idempotency_key?: string;
  },
): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>(
    `/financiamiento/loans/${loanId}/payments/`,
    body,
  );
  return data;
}

// ---------- Recibos de café (acopio en custodia) ----------
export interface ReceptionRow {
  id: number;
  producer_id: number;
  producer_name: string;
  reception_date: string;
  reference: string;
  quality_id: number;
  quality_code: string;
  physical_state: PhysicalState;
  sacks: number;
  gross_lb: string;
  tare_lb: string;
  net_lb: string;
  stock_movement_id: number | null;
  note: string;
}
export async function listReceptions(): Promise<ReceptionRow[]> {
  const { data } = await api.get<{ results: ReceptionRow[] }>('/financiamiento/receptions/');
  return data.results;
}
export async function createReception(body: {
  producer_id: number;
  quality_id: number;
  physical_state?: PhysicalState;
  sacks: number;
  gross_lb: number;
  tare_lb?: number | null;
  reception_date?: string | null;
  reference?: string;
  note?: string;
}): Promise<ReceptionRow> {
  const { data } = await api.post<ReceptionRow>('/financiamiento/receptions/', body);
  return data;
}

// ---------- Fijaciones de precio ----------
export interface FixationRow {
  id: number;
  producer_id: number;
  fixation_date: string;
  pounds: string;
  price_per_lb: string;
  currency: Currency;
  status: FixationStatus;
  liquidation_id: number | null;
  note: string;
}
export async function listFixations(): Promise<FixationRow[]> {
  const { data } = await api.get<{ results: FixationRow[] }>('/financiamiento/fixations/');
  return data.results;
}
export async function createFixation(body: {
  producer_id: number;
  pounds: number;
  price_per_lb: number;
  currency?: Currency;
  fixation_date?: string | null;
  note?: string;
}): Promise<FixationRow> {
  const { data } = await api.post<FixationRow>('/financiamiento/fixations/', body);
  return data;
}

// ---------- Liquidaciones ----------
export interface LiquidationRow {
  id: number;
  producer_id: number;
  producer_name: string;
  loan_id: number | null;
  loan_reference: string;
  liquidation_date: string;
  currency: Currency;
  pounds_total: string;
  gross_value: string;
  deductions_total: string;
  applied_to_loan: string;
  applied_currency: string;
  surplus_amount: string;
  exchange_rate_used: string | null;
  payment_intent_id: number | null;
  note: string;
}
export async function listLiquidations(): Promise<LiquidationRow[]> {
  const { data } = await api.get<{ results: LiquidationRow[] }>('/financiamiento/liquidations/');
  return data.results;
}
export async function createLiquidation(body: {
  producer_id: number;
  fixation_ids: number[];
  loan_id?: number | null;
  deductions?: { concept: string; amount: number }[];
  liquidation_date?: string | null;
  exchange_rate?: number | null;
  note?: string;
}): Promise<LiquidationRow> {
  const { data } = await api.post<LiquidationRow>('/financiamiento/liquidations/', body);
  return data;
}

// ---------- Riesgo de cartera (ASESOR, read-only) ----------
// PD por préstamo (heurística determinista o Random Forest si está disponible y
// encendido) + simulación Monte Carlo con factor sistémico: pérdida esperada + VaR.
// No escribe nada ni toca gates. Perm: financing.risk.read.
export interface RiskLoanRow {
  referencia: string;
  productor: string;
  exposicion: string;
  pd: number;
  lgd: number;
  fuente_pd: 'modelo' | 'heuristica';
}
export interface RiskSimulation {
  simulaciones: number;
  rho: number;
  seed: number;
  perdida_esperada: string;
  perdida_p50: string;
  var_95: string;
  var_99: string;
  perdida_maxima: string;
}
export interface RiskPackage {
  empresa: string;
  prestamos_activos: number;
  exposicion_total: string;
  tipo_cambio: string;
  ai_used: boolean;
  fuente_pd: 'modelo' | 'heuristica';
  detalle: RiskLoanRow[];
  simulacion: RiskSimulation | null;
  perdida_esperada_pct: number | null;
}
export async function getPortfolioRisk(
  params: { simulations?: number; seed?: number } = {},
): Promise<RiskPackage> {
  const { data } = await api.get<RiskPackage>('/financiamiento/risk/', {
    params: {
      ...(params.simulations ? { simulations: params.simulations } : {}),
      ...(params.seed != null ? { seed: params.seed } : {}),
    },
  });
  return data;
}

// ---------- Configuración de acopio ----------
export interface FinancingSettings {
  coffee_item_id: number | null;
  custody_warehouse_id: number | null;
  liquidation_warehouse_id: number | null;
  lender_party_id: number | null;
}
export async function getFinancingSettings(): Promise<FinancingSettings> {
  const { data } = await api.get<FinancingSettings>('/financiamiento/settings/');
  return data;
}
export async function updateFinancingSettings(
  body: Partial<FinancingSettings>,
): Promise<{ ok: boolean }> {
  const { data } = await api.post<{ ok: boolean }>('/financiamiento/settings/', body);
  return data;
}

export const FIN_MENSAJES: Record<string, string> = {
  FIN_SETTINGS_INCOMPLETE: 'Configura el ítem de café y la bodega de custodia antes de acopiar.',
  PRODUCER_EXISTS: 'Ese tercero ya está registrado como productor.',
};
