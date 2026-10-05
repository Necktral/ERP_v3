/**
 * Caja de Venta (POS de mercadería) — escaneo → precio del catálogo → contado o crédito.
 *
 * El PRECIO lo resuelve el servidor desde el catálogo (anti-fraude); mandar un
 * unit_price distinto exige el permiso sales.pos.price_override. La venta es
 * idempotente por idempotency_key (un reintento de red no duplica la factura,
 * el despacho ni el cobro).
 */
import { api } from 'src/boot/axios';

export const POS_PAYMENT_METHOD_LABELS: Record<string, string> = {
  CASH: 'Efectivo',
  TRANSFER: 'Transferencia',
  CARD: 'Tarjeta',
  CHECK: 'Cheque',
  CREDIT: 'Crédito',
};

export interface PosSaleLine {
  inventory_item_id: number;
  quantity: string;
  /** Solo con permiso sales.pos.price_override; si no viene, manda el catálogo. */
  unit_price?: string;
  discount_pct?: string;
  warehouse_id?: number;
}

export interface PosSalePayment {
  method: string;
  /** CREDIT no manda monto (es el total); contado sí. */
  amount?: string;
}

export interface PosSaleInput {
  warehouse_id: number;
  customer_party_id?: number | null;
  customer_name?: string;
  currency?: string;
  is_fiscal?: boolean;
  idempotency_key: string;
  /** Código del pre-ticket de auto-factura que esta venta cobra (opcional). */
  self_service_code?: string;
  /** Grant firmado de autorización de supervisor (cajero sin permiso de override). */
  override_grant?: string;
  lines: PosSaleLine[];
  payments: PosSalePayment[];
}

export interface PosSaleResult {
  sale_type: 'CASH' | 'CREDIT';
  doc_id: number;
  number?: number;
  status?: string;
  total: string;
  payment_status?: string;
  cash_movement_id?: number | null;
  cash_session_id?: number | null;
  /** Solo crédito: CxC creada y disponible restante de la cuenta. */
  receivable_id?: string | null;
  available_after?: string | null;
  duplicate: boolean;
}

export async function posSale(input: PosSaleInput): Promise<PosSaleResult> {
  const { data } = await api.post<PosSaleResult>('/sales/pos-sale/', input);
  return data;
}

export interface PosOverrideGrant {
  grant: string;
  expires_in: number;
  authorized_by: string;
  authorized_by_id: number;
}

/**
 * Un supervisor autoriza, en la caja del cajero, un override de precio/descuento.
 * Devuelve un grant firmado y efímero (5 min) que la próxima venta debe adjuntar.
 */
export async function grantPosOverride(input: {
  supervisor_username: string;
  supervisor_password: string;
  reason: string;
}): Promise<PosOverrideGrant> {
  const { data } = await api.post<PosOverrideGrant>('/sales/pos-override/', input);
  return data;
}

export interface CollectReceivableResult {
  receivable_id: string;
  allocation_id: string;
  allocated: string;
  outstanding_after: string;
  status_after: string;
  cash_movement_id: number | null;
}

/** Cobro de una CxC en caja: aplica a cartera, refleja en la factura y entra a la sesión. */
export async function collectReceivable(input: {
  receivable_id: number;
  amount: string;
  method: string;
  idempotency_key: string;
}): Promise<CollectReceivableResult> {
  const { data } = await api.post<CollectReceivableResult>('/sales/collect-receivable/', input);
  return data;
}

export interface CreditAccountSummary {
  account_id: number;
  party_id: number;
  party_display_name: string;
  segment: string;
  /** null = sin tope (ilimitado explícito). */
  credit_limit: string | null;
  credit_days: number;
  /** null = sin tope. */
  available: string | null;
}

/** Cuenta de crédito del cliente (404 = no tiene → solo contado). */
export function isCreditAccountNotFound(error: unknown): boolean {
  return (error as { response?: { status?: number } }).response?.status === 404;
}

export async function getCreditAccount(partyId: number): Promise<CreditAccountSummary | null> {
  try {
    const { data } = await api.get<CreditAccountSummary>(`/sales/credit-account/${partyId}/`);
    return data;
  } catch (error) {
    if (isCreditAccountNotFound(error)) return null;
    throw error;
  }
}

// --- Corte de ventas del día ---
export interface PosReport {
  date: string;
  sales: {
    count: number;
    subtotal: string;
    tax: string;
    discount: string;
    total: string;
    credit_total: string;
  };
  payments_by_method: { method: string; amount: string; count: number }[];
  returns: { count: number; total: string };
  cost_of_goods: string;
  gross_profit: string;
  top_products: { sku: string; name: string; qty: string; amount: string }[];
  by_cashier: { username: string; count: number; total: string }[];
}

/** Corte X: ventas del día por método, devoluciones y utilidad bruta (solo lectura). */
export async function getPosReport(date?: string): Promise<PosReport> {
  const { data } = await api.get<PosReport>('/sales/pos-report/', {
    params: date ? { date } : {},
  });
  return data;
}

// --- Auto-factura (pre-ticket de kiosko/tableta) ---
export interface SelfServiceLine {
  inventory_item_id: number;
  quantity: string;
  name: string;
  sku: string;
  /** null cuando el artículo quedó sin precio o inactivo (unavailable). */
  unit_price: string | null;
  line_total: string | null;
  unavailable: boolean;
}

export interface SelfServiceTicket {
  code: string;
  status: 'OPEN' | 'CHARGED' | 'CANCELLED' | 'EXPIRED';
  currency: string;
  expires_at: string;
  estimated_subtotal: string;
  estimated_tax: string;
  /** Estimado informativo: el precio definitivo lo resuelve la caja al cobrar. */
  estimated_total: string;
  lines: SelfServiceLine[];
  charged_doc_id: number | null;
}

/** El cliente crea su pre-ticket desde la tableta (sin cliente ni pago). */
export async function createSelfServiceTicket(
  lines: { inventory_item_id: number; quantity: string }[],
): Promise<SelfServiceTicket> {
  const { data } = await api.post<SelfServiceTicket>('/sales/self-service/', { lines });
  return data;
}

/** La caja trae el pre-ticket por código, con precios re-resueltos al momento. */
export async function getSelfServiceTicket(code: string): Promise<SelfServiceTicket> {
  const { data } = await api.get<SelfServiceTicket>(
    `/sales/self-service/${encodeURIComponent(code.trim().toUpperCase())}/`,
  );
  return data;
}

/** El kiosko cancela su pre-ticket (antes de pasar a caja). */
export async function cancelSelfServiceTicket(code: string): Promise<{ ok: boolean }> {
  const { data } = await api.post<{ ok: boolean }>(
    `/sales/self-service/${encodeURIComponent(code.trim().toUpperCase())}/cancel/`,
  );
  return data;
}
