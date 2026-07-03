/**
 * Cartera (kernel portfolio) — CxC (lo que te deben), CxP (lo que debés),
 * créditos y aplicaciones de pago. Aging automático por buckets.
 *
 * OJO: este kernel es un router DRF sin envelope de paginación: los listados
 * devuelven ARRAY plano (no {count, results}).
 */
import { api } from 'src/boot/axios';

export type ObligationStatus =
  | 'PENDING'
  | 'PARTIAL'
  | 'PAID'
  | 'OVERDUE'
  | 'WRITTEN_OFF'
  | 'DISPUTED'
  | 'RESTRUCTURED'
  | 'CANCELLED';

export const AGING_BUCKET_LABELS: Record<string, string> = {
  CURRENT: 'Al día',
  'DAYS_1_30': '1–30 días',
  'DAYS_31_60': '31–60 días',
  'DAYS_61_90': '61–90 días',
  'DAYS_91_120': '91–120 días',
  'DAYS_120_PLUS': '+120 días',
};

interface ObligationBase {
  id: number;
  obligation_id: string;
  company: number;
  branch: number | null;
  party: number;
  reference_type: string;
  reference_id: number;
  status: ObligationStatus;
  currency: string;
  principal_amount: string;
  interest_amount: string;
  fee_amount: string;
  penalty_amount: string;
  allocated_amount: string;
  total_amount: string;
  outstanding_amount: string;
  issue_date: string;
  due_date: string;
  days_overdue: number;
  aging_bucket: string;
  is_overdue: boolean;
  notes: string;
}

export interface Receivable extends ObligationBase {
  invoice_number: string;
  invoice_date: string | null;
  risk_rating: string;
  collection_priority: string;
}

export interface Payable extends ObligationBase {
  supplier_invoice_number: string;
  supplier_invoice_date: string | null;
  payment_priority: string;
}

export interface Credit {
  id: number;
  obligation_id: string;
  company: number;
  // El serializer NO expone `party`: el deudor es `borrower_party`.
  borrower_party: number;
  lender_party: number;
  guarantor_party: number | null;
  credit_type: string;
  credit_status: string;
  contract_number: string;
  currency: string;
  approved_amount: string;
  disbursed_amount: string;
  principal_amount: string;
  interest_amount: string;
  allocated_amount: string;
  total_amount: string;
  outstanding_amount: string;
  interest_rate: string;
  interest_calculation_method: string;
  payment_frequency: string;
  term_months: number | null;
  grace_period_months: number;
  approval_date: string | null;
  disbursement_date: string | null;
  first_payment_date: string | null;
  maturity_date: string | null;
  due_date: string;
  late_payment_penalty_rate: string;
  days_past_due: number;
  collateral_type: string;
  collateral_value: string | null;
  loan_to_value_ratio: string | null;
  collateral_description: string;
  restructure_count: number;
  notes: string;
}

export interface AllocationRow {
  id: number;
  allocation_id: string;
  status: string;
  allocated_amount: string;
  currency: string;
  allocation_date: string;
  obligation_content_type: number;
  obligation_object_id: number;
  reversed_at: string | null;
  reversal_reason: string;
}

export const CREDIT_STATUS_LABELS: Record<string, string> = {
  PENDING: 'Pendiente',
  APPROVED: 'Aprobado',
  ACTIVE: 'Activo',
  MATURED: 'Vencido (plazo)',
  DEFAULTED: 'En mora',
  FULLY_PAID: 'Pagado',
  CANCELLED: 'Cancelado',
};

export async function listReceivables(filters: { status?: string; party?: number } = {}): Promise<Receivable[]> {
  const params: Record<string, string | number> = {};
  if (filters.status) params.status = filters.status;
  if (filters.party) params.party = filters.party;
  const { data } = await api.get<Receivable[]>('/portfolio/receivables/', { params });
  return data;
}

export async function adjustReceivable(
  id: number,
  input: { adjustment_amount: string; reason: string },
): Promise<Receivable> {
  const { data } = await api.post<Receivable>(`/portfolio/receivables/${id}/adjust/`, input);
  return data;
}

export async function writeoffReceivable(id: number, reason: string): Promise<Receivable> {
  const { data } = await api.post<Receivable>(`/portfolio/receivables/${id}/writeoff/`, { reason });
  return data;
}

export async function listPayables(filters: { status?: string; party?: number } = {}): Promise<Payable[]> {
  const params: Record<string, string | number> = {};
  if (filters.status) params.status = filters.status;
  if (filters.party) params.party = filters.party;
  const { data } = await api.get<Payable[]>('/portfolio/payables/', { params });
  return data;
}

export async function listCredits(): Promise<Credit[]> {
  const { data } = await api.get<Credit[]>('/portfolio/credits/');
  return data;
}

/** Detalle fresco de un crédito (el saldo/interés cambia con devengos y abonos). */
export async function getCredit(id: number): Promise<Credit> {
  const { data } = await api.get<Credit>(`/portfolio/credits/${id}/`);
  return data;
}

export async function disburseCredit(
  id: number,
  input: { disbursed_amount: string; disbursement_date: string },
): Promise<Credit> {
  const { data } = await api.post<Credit>(`/portfolio/credits/${id}/disburse/`, input);
  return data;
}

export async function listAllocations(): Promise<AllocationRow[]> {
  const { data } = await api.get<AllocationRow[]>('/portfolio/allocations/');
  return data;
}

// --- O5: devengo de intereses (InterestAccrualViewSet, solo lectura) ----------

export interface InterestAccrual {
  id: number;
  accrual_id: string;
  credit: number;
  accrual_date: string;
  period_start: string;
  period_end: string;
  days_in_period: number;
  principal_balance: string;
  interest_rate_applied: string;
  accrued_interest: string;
  is_capitalized: boolean;
  capitalized_at: string | null;
  calculation_method: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

/** Listado de devengos (array plano; filtra por crédito y/o capitalización). */
export async function listInterestAccruals(
  filters: { credit?: number; is_capitalized?: boolean } = {},
): Promise<InterestAccrual[]> {
  const params: Record<string, string | number | boolean> = {};
  if (filters.credit) params.credit = filters.credit;
  if (filters.is_capitalized !== undefined) params.is_capitalized = filters.is_capitalized;
  const { data } = await api.get<InterestAccrual[]>('/portfolio/interest-accruals/', { params });
  return data;
}

/** Detalle fresco de un devengo (trae metadata_json con el cálculo completo). */
export async function getInterestAccrual(id: number): Promise<InterestAccrual> {
  const { data } = await api.get<InterestAccrual>(`/portfolio/interest-accruals/${id}/`);
  return data;
}

// --- O5: configuración de cartera (PortfolioSettingsViewSet, 1 por empresa) ---

export interface PortfolioSettings {
  company: number;
  aging_buckets_json: Record<string, string>;
  auto_allocate_payments: boolean;
  allocation_strategy: string;
  interest_accrual_frequency: string;
  auto_capitalize_interest: boolean;
  auto_writeoff_enabled: boolean;
  auto_writeoff_days: number;
  gate_mode: string;
  functional_currency: string;
  auto_convert_currency: boolean;
  sync_with_billing: boolean;
  sync_with_procurement: boolean;
  integration_mode: string;
  settings_json: Record<string, unknown>;
  updated_at: string;
}

export type PortfolioSettingsInput = Partial<Omit<PortfolioSettings, 'company' | 'updated_at'>>;

/** La configuración es única por empresa: el listado (scoped) trae 0 o 1 filas. */
export async function getPortfolioSettings(): Promise<PortfolioSettings | null> {
  const { data } = await api.get<PortfolioSettings[]>('/portfolio/settings/');
  return data[0] ?? null;
}

export async function createPortfolioSettings(input: PortfolioSettingsInput): Promise<PortfolioSettings> {
  const { data } = await api.post<PortfolioSettings>('/portfolio/settings/', input);
  return data;
}

/** El pk del recurso es el id de la empresa (OneToOne company ↔ settings). */
export async function updatePortfolioSettings(
  companyId: number,
  input: PortfolioSettingsInput,
): Promise<PortfolioSettings> {
  const { data } = await api.patch<PortfolioSettings>(`/portfolio/settings/${companyId}/`, input);
  return data;
}

// --- Ola D: cobranza (dunning) ------------------------------------------------

export interface CollectionsWorkbenchRow {
  party_id: number;
  party_name: string;
  currency: string;
  docs: number;
  total_outstanding: string;
  max_days_overdue: number;
  last_reminder: { level: number; date: string } | null;
  suggested_level: number;
  cooldown_active: boolean;
}

export interface CollectionReminderLine {
  obligation_id: string;
  invoice_number: string;
  due_date: string;
  days_overdue: number;
  outstanding: string;
}

export interface CollectionReminder {
  id: number;
  party_id: number;
  party_name: string;
  level: number;
  reminder_date: string;
  total_outstanding: string;
  currency: string;
  receivables: CollectionReminderLine[];
  notes: string;
  generated_by: string;
  created_at: string;
}

/** Mesa de cobranza: clientes con saldo vencido y nivel de recordatorio sugerido. */
export async function getCollectionsWorkbench(): Promise<CollectionsWorkbenchRow[]> {
  const { data } = await api.get<{ results: CollectionsWorkbenchRow[] }>(
    '/portfolio/collections/workbench/',
  );
  return data.results;
}

export async function listCollectionReminders(partyId?: number): Promise<CollectionReminder[]> {
  const params: Record<string, number> = {};
  if (partyId) params.party_id = partyId;
  const { data } = await api.get<{ results: CollectionReminder[] }>(
    '/portfolio/collections/reminders/',
    { params },
  );
  return data.results;
}

export async function createCollectionReminder(input: {
  party_id: number;
  currency?: string;
  level?: number | null;
  notes?: string;
}): Promise<CollectionReminder> {
  const { data } = await api.post<CollectionReminder>('/portfolio/collections/reminders/', input);
  return data;
}
