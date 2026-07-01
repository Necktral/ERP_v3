/**
 * Cola offline de pagos del pagador de nómina — lógica pura (testeable).
 *
 * Espejo del patrón probado del POS (`features/pos/offlineQueue.ts`), pero la persistencia
 * vive en SQLite (`PayrollStore`) en vez de localStorage. Aquí va SOLO la lógica:
 * dedupe por empleado, backoff exponencial, estados y drenado. El `executor` (envío al
 * servidor) y el `store` (SQLite/memoria) se inyectan, así esto se prueba sin red ni nativo.
 */
import type { PayMethod, PaySummaryResponse } from '../api';

export type PayQueueStatus = 'PENDING' | 'PROCESSING' | 'DONE' | 'FAILED';

export interface PayrollPaymentCommand {
  /** Clave de idempotencia generada en el cliente; viaja como idempotency_key al servidor. */
  id: string;
  period_id: number;
  sheet_id: number;
  entry_id: number;
  company_id: number;
  branch_id: number;
  employee_key: string;
  full_name: string;
  payment_method: PayMethod;
  amount: string;
  status: PayQueueStatus;
  attempts: number;
  created_at: string;
  updated_at: string;
  next_retry_at: string | null;
  last_error: string;
}

/** Persistencia local de la sala de pago (implementada con SQLite o memoria). */
export interface PayrollStore {
  init(): Promise<void>;
  /** Backend efectivo, para mostrarlo en la UI ('sqlite' en dispositivo, 'memory' de respaldo). */
  backend(): 'sqlite' | 'memory';
  cacheSummary(periodKey: string, payload: PaySummaryResponse): Promise<void>;
  readSummary(periodKey: string): Promise<PaySummaryResponse | null>;
  enqueue(cmd: PayrollPaymentCommand): Promise<void>;
  updateCommand(id: string, patch: Partial<PayrollPaymentCommand>): Promise<void>;
  listCommands(): Promise<PayrollPaymentCommand[]>;
}

export interface PayQueueStats {
  total: number;
  pending: number;
  processing: number;
  failed: number;
  done: number;
  due_now: number;
}

export interface PayDrainResult {
  attempted: number;
  succeeded: number;
  failed: number;
  still_pending: number;
}

const MAX_ATTEMPTS = 8;
const BACKOFF_CAP_MS = 15 * 60 * 1000;

export function periodKey(companyId: number, branchId: number | null, periodId: number): string {
  return `${companyId}:${branchId ?? 'all'}:${periodId}`;
}

function nowIso(ms = Date.now()): string {
  return new Date(ms).toISOString();
}

function parseIsoMs(value: string | null | undefined): number {
  if (!value) return 0;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : 0;
}

function nextBackoffMs(attempt: number): number {
  const step = Math.max(1, Math.min(12, attempt));
  return Math.min(2 ** step * 1000, BACKOFF_CAP_MS);
}

export function newCommandId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `payq_${Math.random().toString(36).slice(2)}_${Date.now()}`;
}

export function classifyError(error: unknown): { retryable: boolean; message: string } {
  if (typeof error === 'object' && error !== null) {
    const maybe = error as {
      message?: string;
      response?: { status?: number; data?: { detail?: string } };
      code?: string;
    };
    const status = Number(maybe.response?.status || 0);
    const msg = maybe.response?.data?.detail || maybe.message || maybe.code || 'Error desconocido';
    if (!status) return { retryable: true, message: msg }; // sin respuesta → red caída → reintentar
    if (status >= 500 || status === 429) return { retryable: true, message: msg };
    return { retryable: false, message: msg }; // 4xx (incl. 422 sobrepago) → no reintentar
  }
  return { retryable: true, message: String(error) };
}

function isDue(cmd: PayrollPaymentCommand, nowMs: number): boolean {
  if (cmd.status === 'DONE' || cmd.status === 'PROCESSING') return false;
  const at = parseIsoMs(cmd.next_retry_at);
  return !at || at <= nowMs;
}

export function queueStats(commands: PayrollPaymentCommand[], nowMs = Date.now()): PayQueueStats {
  const stats: PayQueueStats = { total: commands.length, pending: 0, processing: 0, failed: 0, done: 0, due_now: 0 };
  for (const c of commands) {
    if (c.status === 'PENDING') stats.pending += 1;
    else if (c.status === 'PROCESSING') stats.processing += 1;
    else if (c.status === 'FAILED') stats.failed += 1;
    else stats.done += 1;
    if (isDue(c, nowMs)) stats.due_now += 1;
  }
  return stats;
}

export function buildPaymentCommand(input: {
  period_id: number;
  sheet_id: number;
  entry_id: number;
  company_id: number;
  branch_id: number;
  employee_key: string;
  full_name: string;
  payment_method: PayMethod;
  amount: string;
}): PayrollPaymentCommand {
  const now = nowIso();
  return {
    id: newCommandId(),
    period_id: input.period_id,
    sheet_id: input.sheet_id,
    entry_id: input.entry_id,
    company_id: input.company_id,
    branch_id: input.branch_id,
    employee_key: input.employee_key,
    full_name: input.full_name,
    payment_method: input.payment_method,
    amount: input.amount,
    status: 'PENDING',
    attempts: 0,
    created_at: now,
    updated_at: now,
    next_retry_at: null,
    last_error: '',
  };
}

/**
 * Encola un pago. Dedupe por línea de planilla (entry_id): si ya hay un comando NO terminado
 * para esa línea, lo devuelve como duplicado (evita pagar dos veces al mismo trabajador offline).
 */
export async function enqueuePayment(
  store: PayrollStore,
  command: PayrollPaymentCommand,
): Promise<{ command: PayrollPaymentCommand; duplicate: boolean }> {
  const existing = (await store.listCommands()).find(
    (c) => c.entry_id === command.entry_id && c.status !== 'DONE' && c.status !== 'FAILED',
  );
  if (existing) return { command: existing, duplicate: true };
  await store.enqueue(command);
  return { command, duplicate: false };
}

/** Drena los comandos vencidos: ejecuta el envío y actualiza estado/backoff. */
export async function drainQueue(
  store: PayrollStore,
  executor: (cmd: PayrollPaymentCommand) => Promise<void>,
  opts: { nowMs?: number; max?: number } = {},
): Promise<PayDrainResult> {
  const nowMs = opts.nowMs ?? Date.now();
  const max = Math.max(1, opts.max ?? 25);
  const due = (await store.listCommands())
    .filter((c) => isDue(c, nowMs))
    .sort((a, b) => parseIsoMs(a.created_at) - parseIsoMs(b.created_at))
    .slice(0, max);

  const result: PayDrainResult = { attempted: 0, succeeded: 0, failed: 0, still_pending: 0 };

  for (const cmd of due) {
    result.attempted += 1;
    await store.updateCommand(cmd.id, { status: 'PROCESSING', updated_at: nowIso() });
    try {
      await executor(cmd);
      result.succeeded += 1;
      await store.updateCommand(cmd.id, {
        status: 'DONE',
        updated_at: nowIso(),
        next_retry_at: null,
        last_error: '',
      });
    } catch (error) {
      const verdict = classifyError(error);
      const attempts = cmd.attempts + 1;
      const canRetry = verdict.retryable && attempts < MAX_ATTEMPTS;
      if (canRetry) result.still_pending += 1;
      else result.failed += 1;
      await store.updateCommand(cmd.id, {
        status: canRetry ? 'PENDING' : 'FAILED',
        attempts,
        updated_at: nowIso(),
        last_error: verdict.message.slice(0, 255),
        next_retry_at: canRetry ? nowIso(Date.now() + nextBackoffMs(attempts)) : null,
      });
    }
  }
  return result;
}
