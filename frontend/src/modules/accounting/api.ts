/**
 * Contabilidad (kernel accounting) — plan de cuentas, períodos fiscales,
 * diario (borradores con SoD aprobar→postear, asientos con reversa), reportes,
 * tipo de cambio/revaluación e intercompany.
 */
import { api } from 'src/boot/axios';
import { PAGE, type PageReq, type Paginated } from 'src/core/api';

export const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  ASSET: 'Activo',
  LIABILITY: 'Pasivo',
  EQUITY: 'Patrimonio',
  REVENUE: 'Ingreso',
  EXPENSE: 'Gasto',
};

export const DRAFT_STATE_LABELS: Record<string, string> = {
  GENERATED: 'Generado',
  VALIDATED: 'Validado',
  EXCEPTION: 'Excepción',
  APPROVED_FOR_POSTING: 'Aprobado',
  POSTED: 'Posteado',
  SUPERSEDED: 'Sustituido',
};

export const IC_STATUS_LABELS: Record<string, string> = {
  CREATED: 'Creada',
  CONFIRMED: 'Confirmada',
  RECONCILED: 'Conciliada',
  DISPUTED: 'En disputa',
  SETTLED: 'Liquidada',
  CLOSED: 'Cerrada',
};

// --- Plan de cuentas ---
export interface CoARow {
  id: number;
  code: string;
  name: string;
  account_type: string;
  parent_code: string;
  is_postable: boolean;
  is_active: boolean;
  is_revaluable: boolean;
}

export interface CoAResponse extends Paginated<CoARow> {
  config: {
    functional_currency: string;
    fx_gain_account_code: string;
    fx_loss_account_code: string;
    retained_earnings_account_code: string;
  };
}

export async function getChartOfAccounts(): Promise<CoAResponse> {
  const { data } = await api.get<CoAResponse>('/accounting/chart-of-accounts/', { params: PAGE });
  return data;
}

export async function upsertChartOfAccounts(rows: {
  code: string;
  name: string;
  account_type: string;
  parent_code?: string;
  is_postable?: boolean;
  is_active?: boolean;
  is_revaluable?: boolean;
}[]): Promise<void> {
  await api.put('/accounting/chart-of-accounts/', { rows });
}

// --- Períodos ---
export interface FiscalPeriodRow {
  id: number;
  year: number;
  month: number;
  status: 'OPEN' | 'CLOSED';
  opened_at: string | null;
  closed_at: string | null;
}

export async function listPeriods(): Promise<FiscalPeriodRow[]> {
  const { data } = await api.get<Paginated<FiscalPeriodRow>>('/accounting/periods/', { params: PAGE });
  return data.results;
}

export async function closePeriod(year: number, month: number): Promise<void> {
  await api.post('/accounting/periods/close/', { year, month });
}

export async function reopenPeriod(year: number, month: number, reason: string): Promise<void> {
  await api.post('/accounting/periods/reopen/', { year, month, reason });
}

// --- Diario: borradores ---
export interface JournalDraftRow {
  id: number;
  state: string;
  close_run_id: string;
  economic_event_id: number;
  total_debit: string;
  total_credit: string;
  generated_at: string;
  validated_at: string | null;
  approved_at: string | null;
  posted_at: string | null;
  validation_passed: boolean | null;
}

export async function listJournalDrafts(state?: string): Promise<JournalDraftRow[]> {
  const params: Record<string, string | number> = { ...PAGE };
  if (state) params.state = state;
  const { data } = await api.get<Paginated<JournalDraftRow>>('/accounting/journal-drafts/', { params });
  return data.results;
}

/** Página de borradores con envelope completo (para useListadoServer). */
export async function listJournalDraftsPage(
  state: string | undefined,
  page: PageReq,
): Promise<Paginated<JournalDraftRow>> {
  const params: Record<string, string | number> = { limit: page.limit, offset: page.offset };
  if (state) params.state = state;
  const { data } = await api.get<Paginated<JournalDraftRow>>('/accounting/journal-drafts/', { params });
  return data;
}

export async function approveDrafts(limit = 200): Promise<{ attempted: number; approved: number; skipped: number }> {
  const { data } = await api.post('/accounting/journal-drafts/approve/', { limit });
  return data as { attempted: number; approved: number; skipped: number };
}

export async function postDrafts(limit = 200): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>('/accounting/journal-drafts/post/', { limit });
  return data;
}

// --- Diario: asientos ---
export interface JournalEntryRow {
  id: number;
  draft_id: number;
  year: number;
  month: number;
  entry_date: string;
  description: string;
  debit_total: string;
  credit_total: string;
  status?: string;
}

export async function listJournalEntries(filters: { year?: number; month?: number } = {}): Promise<
  JournalEntryRow[]
> {
  const params: Record<string, string | number> = { ...PAGE };
  if (filters.year) params.year = filters.year;
  if (filters.month) params.month = filters.month;
  const { data } = await api.get<Paginated<JournalEntryRow>>('/accounting/journal-entries/', { params });
  return data.results;
}

/**
 * Variante paginada server-side (envelope completo con `count`).
 * El backend ordena fijo por -posted_at; no acepta `ordering`.
 */
export async function listJournalEntriesPage(
  filters: { year?: number; month?: number },
  page: PageReq,
): Promise<Paginated<JournalEntryRow>> {
  const params: Record<string, string | number> = { limit: page.limit, offset: page.offset };
  if (filters.year) params.year = filters.year;
  if (filters.month) params.month = filters.month;
  const { data } = await api.get<Paginated<JournalEntryRow>>('/accounting/journal-entries/', { params });
  return data;
}

export async function reverseJournalEntry(entryId: number, reason: string): Promise<void> {
  await api.post(`/accounting/journal-entries/${entryId}/reverse/`, { reason });
}

// --- Reportes (filas dinámicas) ---
export type ReportKey = 'trial-balance' | 'general-ledger' | 'pnl' | 'balance-sheet';

export interface ReportResponse {
  count: number;
  results: Record<string, unknown>[];
  filters?: Record<string, string>;
}

export async function getAccountingReport(
  report: ReportKey,
  params: { year?: number; month?: number; date_from?: string; date_to?: string; as_of?: string; account_code?: string },
): Promise<ReportResponse> {
  const q: Record<string, string | number> = { ...PAGE };
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '' && v !== null) q[k] = v;
  }
  const { data } = await api.get<ReportResponse>(`/accounting/reports/${report}/`, { params: q });
  return data;
}

// --- Reconciliación operativa ↔ contable (cuadre por tipo de evento) ---
export interface OperationalReconciliationSummary {
  operational_events: number;
  economic_events_linked: number;
  drafts_total: number;
  drafts_validated: number;
  drafts_exception: number;
  drafts_posted: number;
  pending_operational_events: number;
}

export interface OperationalReconciliationRow {
  source_module: string;
  event_type: string;
  operational_count: number;
  linked_count: number;
  posted_count: number;
  draft_exception_count: number;
  operational_amount: string;
  draft_amount: string;
  posted_amount: string;
}

export interface PendingOperationalEvent {
  outbox_event_id: string;
  source_module: string;
  event_type: string;
  occurred_at: string;
}

export interface OperationalReconciliation {
  summary: OperationalReconciliationSummary;
  by_event_type: OperationalReconciliationRow[];
  /** Eventos operativos sin evento económico vinculado (el backend trunca a 200). */
  pending_operational_events: PendingOperationalEvent[];
  filters: { date_from: string; date_to: string; branch_id: number | null };
}

/** Perm: accounting.report.read. Ambas fechas opcionales (date_from ≤ date_to). */
export async function getOperationalReconciliation(
  params: { date_from?: string; date_to?: string } = {},
): Promise<OperationalReconciliation> {
  const q: Record<string, string> = {};
  if (params.date_from) q.date_from = params.date_from;
  if (params.date_to) q.date_to = params.date_to;
  const { data } = await api.get<OperationalReconciliation>(
    '/accounting/reports/operational-reconciliation/',
    { params: q },
  );
  return data;
}

// --- FX / revaluación ---
export interface FxRateRow {
  id?: number;
  rate_date: string;
  from_currency: string;
  to_currency: string;
  rate_type: string;
  rate: string;
}

export async function listFxRates(): Promise<FxRateRow[]> {
  const { data } = await api.get<Paginated<FxRateRow> | FxRateRow[]>('/accounting/fx-rates/', {
    params: PAGE,
  });
  return Array.isArray(data) ? data : data.results;
}

/** Página de tasas de cambio con envelope completo (para useListadoServer). */
export async function listFxRatesPage(page: PageReq): Promise<Paginated<FxRateRow>> {
  const { data } = await api.get<Paginated<FxRateRow>>('/accounting/fx-rates/', {
    params: { limit: page.limit, offset: page.offset },
  });
  return data;
}

export async function upsertFxRate(input: FxRateRow): Promise<void> {
  await api.post('/accounting/fx-rates/', input);
}

export async function runRevaluation(input: { year: number; month: number }): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>('/accounting/revaluation/run/', input);
  return data;
}

// --- Intercompany ---
export interface IntercompanyTx {
  /** UUID del cruce — el backend NO manda `id` numérico (BUG-009). */
  tx_id: string;
  status: string;
  amount: string;
  currency: string;
  description?: string;
  reference_code?: string;
  source_company_id?: number;
  target_company_id?: number;
  [k: string]: unknown;
}

/**
 * Listado paginado server-side (envelope {count,...}). El backend ordena fijo
 * por -created_at; no acepta `ordering`. `status` filtra por estado del cruce.
 */
export async function listIntercompanyTxsPage(
  page: PageReq,
  filters: { status?: string } = {},
): Promise<Paginated<IntercompanyTx>> {
  const params: Record<string, string | number> = { limit: page.limit, offset: page.offset };
  if (filters.status) params.status = filters.status;
  const { data } = await api.get<Paginated<IntercompanyTx>>(
    '/accounting/intercompany/transactions/',
    { params },
  );
  return data;
}

export async function createIntercompanyTx(input: {
  target_company_id: number;
  amount: string;
  source_account_code: string;
  target_account_code: string;
  description?: string;
}): Promise<void> {
  await api.post('/accounting/intercompany/transactions/', input);
}

export async function intercompanyAction(
  txId: string,
  action: 'confirm' | 'reconcile' | 'settle' | 'close',
): Promise<void> {
  await api.post(`/accounting/intercompany/transactions/${txId}/${action}/`, {});
}

export async function disputeIntercompanyTx(txId: string, reason: string): Promise<void> {
  await api.post(`/accounting/intercompany/transactions/${txId}/dispute/`, { reason });
}

// --- Reversa por lote + bandeja de disputas (cierra #4 del audit) ---
export async function reverseJournalBatch(input: {
  year: number;
  month: number;
  reason: string;
}): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>(
    '/accounting/journal-entries/reverse-batch/',
    input,
  );
  return data;
}

export interface DisputeReason {
  code: string;
  label?: string;
  [k: string]: unknown;
}
export interface DisputeCase {
  case_id: string;
  tx_id: string;
  status: string;
  reason_code: string;
  summary: string;
  resolution_note: string;
  evidence_count: number;
  sla_due_at: string | null;
  opened_at: string | null;
  updated_at: string | null;
}

export async function listIntercompanyDisputes(status?: string): Promise<DisputeCase[]> {
  const params: Record<string, string> = {};
  if (status) params.status = status;
  const { data } = await api.get<{ results: DisputeCase[] }>(
    '/accounting/intercompany/disputes/',
    { params },
  );
  return data.results;
}

/** Página de disputas con envelope completo (para useListadoServer). */
export async function listIntercompanyDisputesPage(
  status: string | undefined,
  page: PageReq,
): Promise<Paginated<DisputeCase>> {
  const params: Record<string, string | number> = { limit: page.limit, offset: page.offset };
  if (status) params.status = status;
  const { data } = await api.get<Paginated<DisputeCase>>('/accounting/intercompany/disputes/', { params });
  return data;
}

export async function listDisputeReasons(): Promise<DisputeReason[]> {
  const { data } = await api.get<{ results: DisputeReason[] }>(
    '/accounting/intercompany/dispute-reasons/',
  );
  return data.results;
}

export async function reviewIntercompanyDispute(
  caseId: string,
  action: 'UNDER_REVIEW' | 'APPROVED' | 'REJECTED' | 'CANCELLED',
  note: string,
): Promise<void> {
  await api.post(`/accounting/intercompany/disputes/${caseId}/review/`, { action, note });
}

// --------------------------------------------------------------- Ola E

export const BUDGET_STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Borrador',
  APPROVED: 'Aprobado',
  ARCHIVED: 'Archivado',
};

export const ACCOUNTING_PLUS_MENSAJES: Record<string, string> = {
  ACCOUNTING_PHASE7_REQUIRED: 'La contabilidad detallada (GL por línea) no está habilitada para esta empresa.',
  ACCOUNTING_COST_CENTER_DUPLICATE: 'Ya existe un centro de costo con ese código.',
  ACCOUNTING_COST_CENTER_INVALID: 'Faltan datos del centro de costo (código y nombre).',
  ACCOUNTING_COST_CENTER_NOT_FOUND: 'El centro de costo no existe en esta empresa.',
  ACCOUNTING_MANUAL_NO_LINES: 'El asiento necesita al menos una línea.',
  ACCOUNTING_MANUAL_UNBALANCED: 'El asiento no cuadra: el débito y el crédito deben ser iguales.',
  ACCOUNTING_MANUAL_EMPTY: 'El asiento está vacío.',
  ACCOUNTING_ACCOUNT_NOT_FOUND: 'Una cuenta no existe en el plan de cuentas.',
  ACCOUNTING_ACCOUNT_NOT_POSTABLE: 'Una cuenta no es imputable (es una cuenta de agrupación).',
  ACCOUNTING_LINE_SIDE_INVALID: 'Cada línea debe ser débito o crédito.',
  ACCOUNTING_LINE_AMOUNT_INVALID: 'Hay una línea con monto inválido.',
  ACCOUNTING_PERIOD_CLOSED: 'El período de esa fecha está cerrado.',
  ACCOUNTING_BUDGET_DUPLICATE: 'Ya existe un presupuesto con ese nombre para el año.',
  ACCOUNTING_BUDGET_NOT_DRAFT: 'El presupuesto ya no es borrador: no se puede editar.',
  ACCOUNTING_BUDGET_EMPTY: 'El presupuesto no tiene líneas.',
  ACCOUNTING_BUDGET_SOD_SELF_APPROVAL: 'Quien crea el presupuesto no puede aprobarlo.',
  ACCOUNTING_BUDGET_LINE_DUPLICATE: 'Hay líneas repetidas (misma cuenta y centro).',
  ACCOUNTING_BUDGET_AMOUNT_INVALID: 'Hay un monto presupuestado inválido.',
  ACCOUNTING_RETAINED_EARNINGS_NOT_CONFIGURED:
    'Falta configurar la cuenta de resultados acumulados (Plan de cuentas → configuración).',
  ACCOUNTING_YEAR_END_MONTHS_OPEN: 'Hay meses de enero a noviembre sin cerrar.',
  ACCOUNTING_YEAR_END_DECEMBER_NOT_OPEN: 'Diciembre debe estar abierto para postear el asiento de cierre.',
  ACCOUNTING_YEAR_END_NOT_FOUND: 'Ese ejercicio no está cerrado.',
  ACCOUNTING_YEAR_END_REOPEN_REASON_REQUIRED: 'Escribí el motivo de la reapertura.',
};

export interface CostCenterRow {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
  created_at: string;
}

export async function listCostCenters(): Promise<CostCenterRow[]> {
  const { data } = await api.get<{ results: CostCenterRow[] }>('/accounting/cost-centers/');
  return data.results;
}

export async function createCostCenter(input: { code: string; name: string }): Promise<CostCenterRow> {
  const { data } = await api.post<CostCenterRow>('/accounting/cost-centers/', input);
  return data;
}

export async function updateCostCenter(
  id: number,
  input: { name?: string; is_active?: boolean },
): Promise<CostCenterRow> {
  const { data } = await api.patch<CostCenterRow>(`/accounting/cost-centers/${id}/`, input);
  return data;
}

export interface ManualLineInput {
  account_code: string;
  side: 'DEBIT' | 'CREDIT';
  amount: string;
  description?: string;
  cost_center_id?: number | null;
}

export async function createManualJournalDraft(input: {
  entry_date: string;
  memo: string;
  lines: ManualLineInput[];
}): Promise<{ draft_id: number; state: string }> {
  const { data } = await api.post('/accounting/journal-drafts/manual/', input);
  return data as { draft_id: number; state: string };
}

export interface BudgetRow {
  id: number;
  fiscal_year: number;
  name: string;
  currency: string;
  status: string;
  created_at: string;
  approved_at: string | null;
}

export interface BudgetLineRow {
  id: number;
  account_code: string;
  account_name: string;
  cost_center_id: number | null;
  cost_center_code: string | null;
  monthly: Record<string, string>;
  annual_amount: string;
}

export interface BudgetDetail extends BudgetRow {
  lines: BudgetLineRow[];
}

export async function listBudgets(fiscalYear?: number): Promise<BudgetRow[]> {
  const params: Record<string, number> = {};
  if (fiscalYear) params.fiscal_year = fiscalYear;
  const { data } = await api.get<{ results: BudgetRow[] }>('/accounting/budgets/', { params });
  return data.results;
}

export async function getBudget(id: number): Promise<BudgetDetail> {
  const { data } = await api.get<BudgetDetail>(`/accounting/budgets/${id}/`);
  return data;
}

export async function createBudget(input: {
  fiscal_year: number;
  name: string;
  currency?: string;
}): Promise<BudgetRow> {
  const { data } = await api.post<BudgetRow>('/accounting/budgets/', input);
  return data;
}

export async function setBudgetLines(
  id: number,
  lines: { account_code: string; cost_center_id?: number | null; monthly: Record<string, string> }[],
): Promise<BudgetDetail> {
  const { data } = await api.put<BudgetDetail>(`/accounting/budgets/${id}/lines/`, { lines });
  return data;
}

export async function approveBudget(id: number): Promise<BudgetRow> {
  const { data } = await api.post<BudgetRow>(`/accounting/budgets/${id}/approve/`, {});
  return data;
}

export async function archiveBudget(id: number): Promise<BudgetRow> {
  const { data } = await api.post<BudgetRow>(`/accounting/budgets/${id}/archive/`, {});
  return data;
}

export interface BudgetVsActualRow {
  account_code: string;
  account_name: string;
  account_type: string;
  cost_center_id: number | null;
  cost_center_code: string | null;
  budget: string;
  actual: string;
  variance: string;
  variance_pct: string | null;
}

export interface BudgetVsActual {
  budget_id: number;
  fiscal_year: number;
  name: string;
  month_from: number;
  month_to: number;
  cost_center_id: number | null;
  rows: BudgetVsActualRow[];
  total_budget: string;
  total_actual: string;
  total_variance: string;
}

export async function getBudgetVsActual(
  id: number,
  params: { month_from?: number; month_to?: number; cost_center_id?: number | null } = {},
): Promise<BudgetVsActual> {
  const q: Record<string, number> = {};
  if (params.month_from) q.month_from = params.month_from;
  if (params.month_to) q.month_to = params.month_to;
  if (params.cost_center_id) q.cost_center_id = params.cost_center_id;
  const { data } = await api.get<BudgetVsActual>(`/accounting/budgets/${id}/vs-actual/`, { params: q });
  return data;
}

export interface YearEndStatus {
  fiscal_year: number;
  status: string | null;
  net_result: string;
  revenue: string;
  expense: string;
  months: Record<string, string | null>;
  months_pending_close: number[];
  december_open: boolean;
  closing_entry_id: number | null;
  manifest_hash: string;
}

export async function getYearEndStatus(fiscalYear: number): Promise<YearEndStatus> {
  const { data } = await api.get<YearEndStatus>('/accounting/year-end/', {
    params: { fiscal_year: fiscalYear },
  });
  return data;
}

export async function closeFiscalYear(fiscalYear: number, force = false): Promise<YearEndStatus> {
  const { data } = await api.post<YearEndStatus>('/accounting/year-end/close/', {
    fiscal_year: fiscalYear,
    force,
  });
  return data;
}

export async function reopenFiscalYear(
  fiscalYear: number,
  reason: string,
  force = false,
): Promise<YearEndStatus> {
  const { data } = await api.post<YearEndStatus>('/accounting/year-end/reopen/', {
    fiscal_year: fiscalYear,
    reason,
    force,
  });
  return data;
}

// --- Consolidación de grupo (holding) -------------------------------------------
// Corre la consolidación de varias empresas del grupo por período (elimina cruces
// intercompañía) y entrega los 3 estados consolidados. Perms:
// accounting.consolidation.run (correr) · accounting.consolidation.read (leer).
export interface ConsolidationRunResult {
  run_id: string;
  status: string;
  idempotent: boolean;
  issues_count: number;
  manifest_hash: string;
  summary: Record<string, unknown>;
}
export interface ConsolTrialRow {
  account_code: string;
  account_name: string;
  account_type: string;
  debit_net: string;
  credit_net: string;
  net_balance: string;
}
export interface ConsolPnlRow {
  account_code: string;
  account_name: string;
  account_type: string;
  balance: string;
}
export interface ConsolPnl {
  run_id: string;
  rows: ConsolPnlRow[];
  totals: { revenue: string; expense: string; net_income: string };
}
export interface ConsolBsRow {
  account_code: string;
  account_name: string;
  balance: string;
}
export interface ConsolBsSection {
  rows: ConsolBsRow[];
  total: string;
}
export interface ConsolBalanceSheet {
  run_id: string;
  as_of: string;
  assets: ConsolBsSection;
  liabilities: ConsolBsSection;
  equity: ConsolBsSection;
}

export async function runConsolidation(body: {
  year: number;
  month: number;
  company_ids: number[];
  strict?: boolean;
}): Promise<ConsolidationRunResult> {
  const { data } = await api.post<ConsolidationRunResult>('/accounting/consolidation/run/', body);
  return data;
}
export async function getConsolTrialBalance(
  runId: string,
): Promise<{ run_id: string; count: number; results: ConsolTrialRow[] }> {
  const { data } = await api.get<{ run_id: string; count: number; results: ConsolTrialRow[] }>(
    '/accounting/consolidation/reports/trial-balance/',
    { params: { run_id: runId } },
  );
  return data;
}
export async function getConsolPnl(runId: string): Promise<ConsolPnl> {
  const { data } = await api.get<ConsolPnl>('/accounting/consolidation/reports/pnl/', {
    params: { run_id: runId },
  });
  return data;
}
export async function getConsolBalanceSheet(runId: string): Promise<ConsolBalanceSheet> {
  const { data } = await api.get<ConsolBalanceSheet>(
    '/accounting/consolidation/reports/balance-sheet/',
    { params: { run_id: runId } },
  );
  return data;
}

/** Metadatos + summary_json persistidos de una corrida de consolidación. */
export interface ConsolidationRunSummary {
  run_id: string;
  status: string;
  parent_company_id: number;
  year: number;
  month: number;
  company_ids: number[];
  input_manifest_hash: string;
  output_manifest_hash: string;
  started_at: string | null;
  completed_at: string | null;
  /** summary_json de la corrida: period, metrics, issues, trial_balance, pnl, balance_sheet… */
  summary: Record<string, unknown>;
}

export async function getConsolidationRunSummary(runId: string): Promise<ConsolidationRunSummary> {
  const { data } = await api.get<ConsolidationRunSummary>(
    `/accounting/consolidation/runs/${runId}/summary/`,
  );
  return data;
}
