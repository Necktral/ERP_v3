/**
 * Compras (procurement) — documentos de proveedor con ciclo
 * BORRADOR → POSTEADO → ANULADO. El posteo asigna número y crea la CxP.
 */
import { api } from 'src/boot/axios';
import { PAGE, type PageReq, type Paginated } from 'src/core/api';

export type PurchaseDocType =
  | 'GOODS_RECEIPT'
  | 'SUPPLIER_INVOICE'
  | 'SUPPLIER_CREDIT_NOTE'
  | 'SUPPLIER_PAYMENT'
  | 'ADJUSTMENT';

export type PurchaseDocStatus = 'DRAFT' | 'POSTED' | 'VOIDED';

export const PURCHASE_DOC_TYPE_LABELS: Record<PurchaseDocType, string> = {
  GOODS_RECEIPT: 'Recepción de bienes',
  SUPPLIER_INVOICE: 'Factura de proveedor',
  SUPPLIER_CREDIT_NOTE: 'Nota de crédito de proveedor',
  SUPPLIER_PAYMENT: 'Pago a proveedor',
  ADJUSTMENT: 'Ajuste',
};

export interface PurchaseDocRow {
  id: number;
  doc_type: PurchaseDocType;
  status: PurchaseDocStatus;
  series: string;
  number: number;
  currency: string;
  supplier_name: string;
  supplier_party_id: number | null;
  supplier_party_display_name: string;
  subtotal: string;
  tax_total: string;
  total: string;
  created_at: string;
  posted_at: string | null;
  voided_at: string | null;
}

export interface PurchaseDoc extends PurchaseDocRow {
  supplier_ref: string;
  external_ref: string;
  void_reason: string;
  notes: string;
}

export interface PurchaseDocFilters {
  status?: PurchaseDocStatus | '';
  doc_type?: PurchaseDocType | '';
  q?: string;
  date_from?: string;
  date_to?: string;
}

export async function listPurchaseDocs(filters: PurchaseDocFilters = {}): Promise<PurchaseDocRow[]> {
  const params: Record<string, string | number> = { ...PAGE };
  for (const [k, v] of Object.entries(filters)) {
    if (v) params[k] = v;
  }
  const { data } = await api.get<Paginated<PurchaseDocRow>>('/procurement/docs/', { params });
  return data.results;
}

/** Variante paginada server-side (envelope completo con `count`). */
export async function listPurchaseDocsPage(
  filters: PurchaseDocFilters,
  page: PageReq,
): Promise<Paginated<PurchaseDocRow>> {
  const params: Record<string, string | number> = { limit: page.limit, offset: page.offset };
  for (const [k, v] of Object.entries(filters)) {
    if (v) params[k] = v;
  }
  const { data } = await api.get<Paginated<PurchaseDocRow>>('/procurement/docs/', { params });
  return data;
}

export async function getPurchaseDoc(docId: number): Promise<PurchaseDoc> {
  const { data } = await api.get<PurchaseDoc>(`/procurement/docs/${docId}/`);
  return data;
}

export async function createPurchaseDoc(input: {
  doc_type: PurchaseDocType;
  supplier_party_id?: number;
  supplier_name?: string;
  supplier_ref?: string;
  external_ref?: string;
  subtotal: string;
  tax_total: string;
  total: string;
  notes?: string;
}): Promise<number> {
  const { data } = await api.post<{ id: number }>('/procurement/docs/', {
    ...input,
    idempotency_key: crypto.randomUUID(),
  });
  return data.id;
}

export async function postPurchaseDoc(docId: number): Promise<{ status: string; number: number }> {
  const { data } = await api.post<{ status: string; number: number }>(
    `/procurement/docs/${docId}/post/`,
    {},
  );
  return data;
}

export async function voidPurchaseDoc(docId: number, reason: string): Promise<{ status: string }> {
  const { data } = await api.post<{ status: string }>(`/procurement/docs/${docId}/void/`, { reason });
  return data;
}

// --------------------------------------------------------------------------- Ola B
// Órdenes de compra formales: ciclo con aprobación (quien envía no aprueba),
// recepciones parciales que postean inventario, factura con 3-way match.

export type PurchaseOrderStatus =
  | 'DRAFT'
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'SENT'
  | 'PARTIALLY_RECEIVED'
  | 'RECEIVED'
  | 'CLOSED'
  | 'CANCELLED';

export const PO_STATUS_LABELS: Record<PurchaseOrderStatus, string> = {
  DRAFT: 'Borrador',
  PENDING_APPROVAL: 'Pendiente de aprobación',
  APPROVED: 'Aprobada',
  SENT: 'Enviada al proveedor',
  PARTIALLY_RECEIVED: 'Recibida parcial',
  RECEIVED: 'Recibida',
  CLOSED: 'Cerrada',
  CANCELLED: 'Cancelada',
};

export interface PurchaseOrderRow {
  id: number;
  status: PurchaseOrderStatus;
  series: string;
  number: number;
  currency: string;
  supplier_party_id: number;
  supplier_display_name: string;
  expected_date: string | null;
  subtotal: string;
  tax_total: string;
  total: string;
  created_at: string;
}

export interface PurchaseOrderLine {
  id: number;
  item_id: number;
  item_sku: string;
  item_name: string;
  description: string;
  qty_ordered: string;
  qty_received: string;
  qty_pending: string;
  unit_cost: string;
  tax_rate: string;
  line_subtotal: string;
  line_total: string;
}

export interface PurchaseOrderReceipt {
  id: number;
  number: number;
  warehouse_id: number;
  warehouse_name: string;
  posted_at: string;
  received_by: string | null;
  lines: { order_line_id: number; item_sku: string; item_name: string; qty: string; unit_cost: string }[];
}

export interface PurchaseOrderInvoiceRef {
  id: number;
  series: string;
  number: number;
  status: PurchaseDocStatus;
  total: string;
  supplier_ref: string;
  created_at: string;
}

export interface PurchaseOrderDetail extends Omit<PurchaseOrderRow, 'created_at'> {
  notes: string;
  submitted_by: string | null;
  approved_by: string | null;
  created_at: string;
  lines: PurchaseOrderLine[];
  receipts: PurchaseOrderReceipt[];
  invoices: PurchaseOrderInvoiceRef[];
  /** Valor recibido aún sin factura (base del 3-way match). */
  pending_to_invoice: string;
}

export interface PurchaseOrderLineInput {
  item_id: number;
  qty: string;
  /** Sin costo: el servidor usa el precio del proveedor (acordado → último costo). */
  unit_cost?: string;
  tax_rate?: string;
  description?: string;
}

export async function listPurchaseOrders(filters: {
  status?: PurchaseOrderStatus | '';
  supplier_party_id?: number;
  q?: string;
} = {}): Promise<PurchaseOrderRow[]> {
  const params: Record<string, string | number> = { ...PAGE };
  for (const [k, v] of Object.entries(filters)) {
    if (v) params[k] = v;
  }
  const { data } = await api.get<Paginated<PurchaseOrderRow>>('/procurement/orders/', { params });
  return data.results;
}

export async function getPurchaseOrder(orderId: number): Promise<PurchaseOrderDetail> {
  const { data } = await api.get<PurchaseOrderDetail>(`/procurement/orders/${orderId}/`);
  return data;
}

export async function createPurchaseOrder(input: {
  supplier_party_id: number;
  lines: PurchaseOrderLineInput[];
  expected_date?: string | null;
  notes?: string;
}): Promise<{ order_id: number; number: number }> {
  const { data } = await api.post<{ order_id: number; number: number }>('/procurement/orders/', {
    ...input,
    idempotency_key: crypto.randomUUID(),
  });
  return data;
}

export async function updatePurchaseOrder(
  orderId: number,
  input: { lines?: PurchaseOrderLineInput[]; expected_date?: string | null; notes?: string },
): Promise<{ order_id: number; status: string; total: string }> {
  const { data } = await api.patch<{ order_id: number; status: string; total: string }>(
    `/procurement/orders/${orderId}/`,
    input,
  );
  return data;
}

async function orderAction(orderId: number, action: string, body: object = {}) {
  const { data } = await api.post<{ order_id: number; status: PurchaseOrderStatus }>(
    `/procurement/orders/${orderId}/${action}/`,
    body,
  );
  return data;
}

export const submitPurchaseOrder = (id: number) => orderAction(id, 'submit');
export const approvePurchaseOrder = (id: number) => orderAction(id, 'approve');
export const sendPurchaseOrder = (id: number) => orderAction(id, 'send');
export const closePurchaseOrder = (id: number) => orderAction(id, 'close');
export const cancelPurchaseOrder = (id: number, reason: string) =>
  orderAction(id, 'cancel', { reason });

export async function receivePurchaseOrder(
  orderId: number,
  input: {
    warehouse_id: number;
    lines: { order_line_id: number; qty: string; unit_cost?: string }[];
    notes?: string;
  },
): Promise<{ receipt_id: number; number: number; order_status: PurchaseOrderStatus }> {
  const { data } = await api.post<{
    receipt_id: number;
    number: number;
    order_status: PurchaseOrderStatus;
  }>(`/procurement/orders/${orderId}/receive/`, {
    ...input,
    idempotency_key: crypto.randomUUID(),
  });
  return data;
}

export async function invoicePurchaseOrder(
  orderId: number,
  input: {
    subtotal: string;
    tax_total: string;
    total: string;
    supplier_ref?: string;
    notes?: string;
    match_override?: boolean;
  },
): Promise<{ doc_id: number; pending_to_invoice: string; deviation: string }> {
  const { data } = await api.post<{ doc_id: number; pending_to_invoice: string; deviation: string }>(
    `/procurement/orders/${orderId}/invoice/`,
    { ...input, idempotency_key: crypto.randomUUID() },
  );
  return data;
}

// --- Requisiciones ---
export type RequisitionStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'REJECTED' | 'CONVERTED';

export const REQUISITION_STATUS_LABELS: Record<RequisitionStatus, string> = {
  DRAFT: 'Borrador',
  SUBMITTED: 'Enviada',
  APPROVED: 'Aprobada',
  REJECTED: 'Rechazada',
  CONVERTED: 'Convertida a OC',
};

export interface RequisitionLine {
  id: number;
  item_id: number;
  item_sku: string;
  item_name: string;
  qty: string;
  note: string;
}

export interface Requisition {
  id: number;
  status: RequisitionStatus;
  notes: string;
  requested_by: string | null;
  decided_by: string | null;
  rejection_reason: string;
  converted_order_id: number | null;
  created_at: string;
  lines: RequisitionLine[];
}

export async function listRequisitions(filters: { status?: RequisitionStatus | '' } = {}): Promise<
  Requisition[]
> {
  const params: Record<string, string | number> = { ...PAGE };
  if (filters.status) params.status = filters.status;
  const { data } = await api.get<Paginated<Requisition>>('/procurement/requisitions/', { params });
  return data.results;
}

export async function createRequisition(input: {
  lines: { item_id: number; qty: string; note?: string }[];
  notes?: string;
}): Promise<{ requisition_id: number }> {
  const { data } = await api.post<{ requisition_id: number }>('/procurement/requisitions/', input);
  return data;
}

async function requisitionAction(reqId: number, action: string, body: object = {}) {
  const { data } = await api.post<{ requisition_id: number; status: RequisitionStatus; order_id?: number }>(
    `/procurement/requisitions/${reqId}/${action}/`,
    body,
  );
  return data;
}

export const submitRequisition = (id: number) => requisitionAction(id, 'submit');
export const approveRequisition = (id: number) => requisitionAction(id, 'approve');
export const rejectRequisition = (id: number, reason: string) =>
  requisitionAction(id, 'reject', { reason });
export const convertRequisition = (id: number, supplierPartyId: number) =>
  requisitionAction(id, 'convert', { supplier_party_id: supplierPartyId });

// --- Reorden ---
export interface ReorderSuggestion {
  item_id: number;
  sku: string;
  name: string;
  qty_on_hand: string;
  reorder_point: string;
  suggested_qty: string;
  supplier_party_id: number | null;
  supplier_display_name: string | null;
  last_cost: string | null;
  agreed_price: string | null;
  currency: string;
}

export async function getReorderSuggestions(): Promise<ReorderSuggestion[]> {
  const { data } = await api.get<{ results: ReorderSuggestion[] }>(
    '/procurement/reorder-suggestions/',
  );
  return data.results;
}

export async function createOrdersFromSuggestions(
  items: { item_id: number; qty: string; supplier_party_id: number }[],
): Promise<{ orders: { order_id: number; supplier_party_id: number; lines: number }[] }> {
  const { data } = await api.post<{
    orders: { order_id: number; supplier_party_id: number; lines: number }[];
  }>('/procurement/reorder-suggestions/create-orders/', { items });
  return data;
}

// --- Precios por proveedor ---
export interface SupplierItemPriceRow {
  id: number;
  supplier_party_id: number;
  supplier_display_name: string;
  item_id: number;
  item_sku: string;
  item_name: string;
  /** Último costo recibido (automático, solo lectura). */
  last_cost: string | null;
  /** Precio acordado con el proveedor (editable). */
  agreed_price: string | null;
  currency: string;
  last_receipt_at: string | null;
}

export async function listSupplierPrices(filters: {
  supplier_party_id?: number;
  q?: string;
} = {}): Promise<SupplierItemPriceRow[]> {
  const params: Record<string, string | number> = { ...PAGE };
  if (filters.supplier_party_id) params.supplier_party_id = filters.supplier_party_id;
  if (filters.q) params.q = filters.q;
  const { data } = await api.get<Paginated<SupplierItemPriceRow>>('/procurement/supplier-prices/', {
    params,
  });
  return data.results;
}

export async function upsertSupplierPrice(input: {
  supplier_party_id: number;
  item_id: number;
  agreed_price: string | null;
  currency?: string;
}): Promise<{ id: number }> {
  const { data } = await api.put<{ id: number }>('/procurement/supplier-prices/', input);
  return data;
}

// --- Ola D: pago de CxP al proveedor desde caja ------------------------------

export interface PayPayableInput {
  payable_id: number;
  amount: string;
  method: string;
  idempotency_key: string;
}

export interface PayPayableResult {
  payable_id: string;
  allocation_id: string;
  paid: string;
  outstanding_after: string;
  status_after: string;
  cash_movement_id: number | null;
}

/** Paga una CxP: efectivo sale de la sesión de caja abierta; transferencia/cheque no la tocan. */
export async function payPayable(input: PayPayableInput): Promise<PayPayableResult> {
  const { data } = await api.post<PayPayableResult>('/procurement/pay-payable/', input);
  return data;
}
