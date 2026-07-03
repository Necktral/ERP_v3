/**
 * Inventario (kernel inventarios) — bodegas, artículos, lotes, existencias,
 * kardex y movimientos (recibir/despachar/ajustar/transferir).
 *
 * Los movimientos generan idempotency_key (uuid) para que un reintento de red
 * no duplique el movimiento. El backend responde con el saldo y el estado
 * contable (accounting_status) del posteo automático a GL.
 */
import { api } from 'src/boot/axios';
import { PAGE, type PageReq, type Paginated } from 'src/core/api';

// --- Catálogos / enums --------------------------------------------------------
export const UOM_LABELS: Record<string, string> = {
  UNIT: 'Unidad',
  DOZEN: 'Docena',
  PACK: 'Paquete',
  BOX: 'Caja',
  GRAM: 'Gramo',
  KILOGRAM: 'Kilogramo',
  POUND: 'Libra',
  QUINTAL: 'Quintal (100 lb)',
  TON: 'Tonelada métrica',
  MILLILITER: 'Mililitro',
  LITER: 'Litro',
  GALLON: 'Galón',
  BARREL: 'Barril',
  METER: 'Metro',
  SQUARE_METER: 'Metro cuadrado',
  MANZANA: 'Manzana',
  HOUR: 'Hora',
  DAY: 'Día',
  GOLD_QUINTAL: 'Quintal oro',
  WET_QUINTAL: 'Quintal húmedo',
  DRY_QUINTAL: 'Quintal seco',
};

export const WAREHOUSE_TYPE_LABELS: Record<string, string> = {
  GENERAL: 'General',
  AGROCHEMICAL: 'Agroquímicos',
  COLD_STORAGE: 'Cámara fría',
  FINISHED_GOODS: 'Producto terminado',
  RAW_MATERIALS: 'Materia prima',
  TOOLS: 'Herramientas y equipos',
  FUEL: 'Combustibles',
  TRANSIT: 'En tránsito',
  COFFEE: 'Café',
};

export const MOVEMENT_TYPE_LABELS: Record<string, string> = {
  RECEIVE: 'Recepción',
  ISSUE: 'Despacho',
  ADJUST: 'Ajuste',
  TRANSFER_OUT: 'Transferencia (salida)',
  TRANSFER_IN: 'Transferencia (entrada)',
  RETURN: 'Devolución',
  SHRINKAGE: 'Merma',
  PRODUCTION_IN: 'Producción (entrada)',
  PRODUCTION_OUT: 'Producción (salida)',
  PHYSICAL_COUNT: 'Conteo físico',
};

// --- Tipos ---------------------------------------------------------------------
export interface Warehouse {
  id: number;
  name: string;
  code: string;
  warehouse_type: string;
  location_description: string;
  is_active: boolean;
  is_default: boolean;
}

export interface InventoryItem {
  id: number;
  sku: string;
  name: string;
  description: string;
  category: string;
  barcode: string;
  uom: string;
  /** Precio de venta por unidad; null = sin precio definido (la caja lo rechaza). */
  sale_price: string | null;
  /** IVA por defecto como fracción 0-1 (0.15 = 15%). */
  default_tax_rate: string;
  /** Mayoreo: a partir de wholesale_min_qty aplica wholesale_price (null = sin mayoreo). */
  wholesale_price: string | null;
  wholesale_min_qty: string | null;
  reorder_point: string;
  min_stock_qty: string;
  max_stock_qty: string | null;
  track_lots: boolean;
  track_expiry: boolean;
  shelf_life_days: number | null;
  storage_condition: string;
  is_controlled: boolean;
  is_active: boolean;
}

export interface ItemLot {
  id: number;
  lot_number: string;
  supplier_lot_ref: string;
  production_date: string | null;
  expiry_date: string | null;
  status: string;
  qty_received: string;
  notes: string;
  is_expired: boolean;
  days_to_expiry: number | null;
}

export interface StockRow {
  id: number;
  item: number;
  item_sku: string;
  item_name: string;
  item_uom: string;
  warehouse: number;
  warehouse_name: string;
  qty_on_hand: string;
  qty_reserved: string;
  qty_available: string;
  avg_cost: string;
  updated_at: string;
}

export interface LotStockRow {
  id: number;
  lot: number;
  lot_number: string;
  expiry_date: string | null;
  lot_status: string;
  qty_on_hand: string;
  avg_cost: string;
}

export interface KardexRow {
  id: number;
  movement_type: string;
  item: number;
  item_sku: string;
  warehouse: number;
  warehouse_name: string;
  qty_delta: string;
  unit_cost: string;
  total_cost: string;
  lot: number | null;
  lot_number: string | null;
  note: string;
  accounting_status: string;
  created_at: string;
}

/** Respuesta de cada movimiento posteado (incluye estado del asiento a GL). */
export interface PostResult {
  movement_id: number;
  qty_on_hand: string;
  avg_cost: string;
  accounting_status: string;
  accounting_error: string;
  journal_draft_id: number | null;
  journal_entry_id: number | null;
}

// --- Bodegas ---------------------------------------------------------------------
export async function listWarehouses(): Promise<Warehouse[]> {
  const { data } = await api.get<Paginated<Warehouse>>('/inventory/warehouses/', { params: PAGE });
  return data.results;
}

export async function createWarehouse(input: {
  name: string;
  code?: string;
  warehouse_type?: string;
  location_description?: string;
  is_default?: boolean;
}): Promise<Warehouse> {
  const { data } = await api.post<Warehouse>('/inventory/warehouses/', input);
  return data;
}

// --- Artículos ---------------------------------------------------------------------
export async function listItems(filters: { search?: string; is_active?: boolean } = {}): Promise<
  InventoryItem[]
> {
  const params: Record<string, string | number | boolean> = { ...PAGE };
  if (filters.search) params.search = filters.search;
  if (filters.is_active !== undefined) params.is_active = filters.is_active;
  const { data } = await api.get<Paginated<InventoryItem>>('/inventory/items/', { params });
  return data.results;
}

export interface ItemInput {
  sku: string;
  name: string;
  description?: string;
  category?: string;
  barcode?: string;
  uom?: string;
  sale_price?: string | null;
  default_tax_rate?: string;
  wholesale_price?: string | null;
  wholesale_min_qty?: string | null;
  reorder_point?: string;
  track_lots?: boolean;
  track_expiry?: boolean;
  shelf_life_days?: number | null;
  is_controlled?: boolean;
}

export async function createItem(input: ItemInput): Promise<InventoryItem> {
  const { data } = await api.post<InventoryItem>('/inventory/items/', input);
  return data;
}

/** Detalle de un artículo por id (ficha de producto). */
export async function getItem(itemId: number): Promise<InventoryItem> {
  const { data } = await api.get<InventoryItem>(`/inventory/items/${itemId}/`);
  return data;
}

export async function updateItem(
  itemId: number,
  input: Partial<{
    name: string;
    description: string;
    category: string;
    barcode: string;
    sale_price: string | null;
    default_tax_rate: string;
    wholesale_price: string | null;
    wholesale_min_qty: string | null;
    reorder_point: string;
    min_stock_qty: string;
    max_stock_qty: string | null;
    is_active: boolean;
  }>,
): Promise<InventoryItem> {
  const { data } = await api.patch<InventoryItem>(`/inventory/items/${itemId}/`, input);
  return data;
}

/** Lookup EXACTO por código de barras (escáner de la caja): 0 o 1 resultado. */
export async function findItemByBarcode(barcode: string): Promise<InventoryItem | null> {
  const { data } = await api.get<Paginated<InventoryItem>>('/inventory/items/', {
    params: { barcode, limit: 1, offset: 0 },
  });
  return data.results[0] ?? null;
}

// --- Lotes ---------------------------------------------------------------------
export async function listLots(itemId: number): Promise<ItemLot[]> {
  const { data } = await api.get<Paginated<ItemLot>>('/inventory/lots/', {
    params: { ...PAGE, item_id: itemId },
  });
  return data.results;
}

export async function createLot(input: {
  item_id: number;
  lot_number: string;
  supplier_lot_ref?: string;
  production_date?: string;
  expiry_date?: string;
  notes?: string;
}): Promise<ItemLot> {
  const { data } = await api.post<ItemLot>('/inventory/lots/create/', input);
  return data;
}

// --- Existencias / kardex ---------------------------------------------------------
export interface StockFilters {
  warehouse_id?: number;
  item_id?: number;
  below_reorder?: boolean;
}

export async function getStock(filters: StockFilters = {}): Promise<StockRow[]> {
  const params: Record<string, string | number | boolean> = { ...PAGE };
  if (filters.warehouse_id) params.warehouse_id = filters.warehouse_id;
  if (filters.item_id) params.item_id = filters.item_id;
  if (filters.below_reorder) params.below_reorder = 'true';
  const { data } = await api.get<Paginated<StockRow>>('/inventory/stock/', { params });
  return data.results;
}

/** Variante paginada server-side de existencias (envelope completo con `count`). */
export async function getStockPage(filters: StockFilters, page: PageReq): Promise<Paginated<StockRow>> {
  const params: Record<string, string | number | boolean> = { limit: page.limit, offset: page.offset };
  if (filters.warehouse_id) params.warehouse_id = filters.warehouse_id;
  if (filters.item_id) params.item_id = filters.item_id;
  if (filters.below_reorder) params.below_reorder = 'true';
  const { data } = await api.get<Paginated<StockRow>>('/inventory/stock/', { params });
  return data;
}

export async function getStockLots(itemId: number, warehouseId?: number): Promise<LotStockRow[]> {
  const params: Record<string, string | number> = { ...PAGE, item_id: itemId };
  if (warehouseId) params.warehouse_id = warehouseId;
  const { data } = await api.get<Paginated<LotStockRow>>('/inventory/stock/lots/', { params });
  return data.results;
}

export interface KardexFilters {
  item_id: number;
  warehouse_id?: number;
  movement_type?: string;
  date_from?: string;
  date_to?: string;
}

export async function getKardex(filters: KardexFilters): Promise<KardexRow[]> {
  const params: Record<string, string | number> = { ...PAGE, ...filters };
  const { data } = await api.get<Paginated<KardexRow>>('/inventory/kardex/', { params });
  return data.results;
}

/** Variante paginada server-side del kardex (envelope completo con `count`). */
export async function getKardexPage(filters: KardexFilters, page: PageReq): Promise<Paginated<KardexRow>> {
  const params: Record<string, string | number> = { limit: page.limit, offset: page.offset, ...filters };
  const { data } = await api.get<Paginated<KardexRow>>('/inventory/kardex/', { params });
  return data;
}

// --- Movimientos ---------------------------------------------------------------------
function idemKey(): string {
  return crypto.randomUUID();
}

export async function receiveStock(input: {
  warehouse_id: number;
  item_id: number;
  qty: string;
  unit_cost: string;
  lot_number?: string;
  expiry_date?: string;
  note?: string;
}): Promise<PostResult> {
  const { data } = await api.post<PostResult>('/inventory/movements/receive/', {
    ...input,
    idempotency_key: idemKey(),
  });
  return data;
}

export async function issueStock(input: {
  warehouse_id: number;
  item_id: number;
  qty: string;
  lot_id?: number;
  note?: string;
}): Promise<PostResult> {
  const { data } = await api.post<PostResult>('/inventory/movements/issue/', {
    ...input,
    idempotency_key: idemKey(),
  });
  return data;
}

export async function adjustStock(input: {
  warehouse_id: number;
  item_id: number;
  new_qty_on_hand: string;
  note?: string;
}): Promise<PostResult> {
  const { data } = await api.post<PostResult>('/inventory/movements/adjust/', {
    ...input,
    idempotency_key: idemKey(),
  });
  return data;
}

export async function transferStock(input: {
  from_warehouse_id: number;
  to_warehouse_id: number;
  item_id: number;
  qty: string;
  lot_id?: number;
  note?: string;
}): Promise<{ from_movement: PostResult; to_movement: PostResult }> {
  const { data } = await api.post<{ from_movement: PostResult; to_movement: PostResult }>(
    '/inventory/transfers/',
    { ...input, idempotency_key: idemKey() },
  );
  return data;
}

// --- Conteo físico (Ola C) ---------------------------------------------------------
export type PhysicalCountStatus = 'OPEN' | 'COUNTED' | 'POSTED' | 'CANCELLED';

export const COUNT_STATUS_LABELS: Record<PhysicalCountStatus, string> = {
  OPEN: 'Abierto',
  COUNTED: 'Contado',
  POSTED: 'Posteado',
  CANCELLED: 'Cancelado',
};

export interface PhysicalCountRow {
  id: number;
  status: PhysicalCountStatus;
  warehouse_id: number;
  warehouse_name: string;
  category: string;
  notes: string;
  lines: number;
  created_by: string | null;
  counted_by: string | null;
  approved_by: string | null;
  created_at: string;
}

export interface PhysicalCountLine {
  id: number;
  item_id: number;
  item_sku: string;
  item_name: string;
  item_uom: string;
  /** Existencia esperada al generar la hoja (snapshot). */
  qty_expected: string;
  qty_counted: string | null;
  variance: string | null;
  movement_id: number | null;
}

export interface PhysicalCountDetail extends Omit<PhysicalCountRow, 'lines'> {
  counted_at: string | null;
  approved_at: string | null;
  lines: PhysicalCountLine[];
  adjusted_lines?: number;
  pending_lines?: number;
}

export async function listPhysicalCounts(filters: { status?: PhysicalCountStatus | '' } = {}): Promise<
  PhysicalCountRow[]
> {
  const params: Record<string, string | number> = { ...PAGE };
  if (filters.status) params.status = filters.status;
  const { data } = await api.get<Paginated<PhysicalCountRow>>('/inventory/counts/', { params });
  return data.results;
}

export async function getPhysicalCount(countId: number): Promise<PhysicalCountDetail> {
  const { data } = await api.get<PhysicalCountDetail>(`/inventory/counts/${countId}/`);
  return data;
}

export async function createPhysicalCount(input: {
  warehouse_id: number;
  category?: string;
  notes?: string;
}): Promise<PhysicalCountDetail> {
  const { data } = await api.post<PhysicalCountDetail>('/inventory/counts/', input);
  return data;
}

export async function capturePhysicalCount(
  countId: number,
  lines: { line_id: number; qty_counted: string }[],
): Promise<PhysicalCountDetail> {
  const { data } = await api.post<PhysicalCountDetail>(`/inventory/counts/${countId}/capture/`, {
    lines,
  });
  return data;
}

/** Aprueba las varianzas y postea los ajustes (quien capturó NO puede aprobar). */
export async function approvePhysicalCount(countId: number): Promise<PhysicalCountDetail> {
  const { data } = await api.post<PhysicalCountDetail>(`/inventory/counts/${countId}/approve/`, {});
  return data;
}

export async function cancelPhysicalCount(countId: number): Promise<{ id: number; status: string }> {
  const { data } = await api.post<{ id: number; status: string }>(
    `/inventory/counts/${countId}/cancel/`,
    {},
  );
  return data;
}

// --- Valorización ---------------------------------------------------------------
export interface ValuationGroup {
  warehouse_id?: number;
  warehouse_name?: string;
  category?: string;
  items: number;
  value: string;
}

export interface ValuationDetailRow {
  item_id: number;
  sku: string;
  name: string;
  category: string;
  warehouse_id: number;
  warehouse_name: string;
  qty_on_hand: string;
  avg_cost: string;
  value: string;
}

export interface InventoryValuation {
  total_value: string;
  by_warehouse: ValuationGroup[];
  by_category: ValuationGroup[];
  detail: ValuationDetailRow[];
}

/** Valorización: Σ existencia × costo promedio (solo lectura). */
export async function getInventoryValuation(warehouseId?: number): Promise<InventoryValuation> {
  const { data } = await api.get<InventoryValuation>('/inventory/valuation/', {
    params: warehouseId ? { warehouse_id: warehouseId } : {},
  });
  return data;
}

// --- Listas de precios ---------------------------------------------------------
// Administra listas, sus tramos por (artículo, cantidad mínima) y a quién aplican
// (cliente o segmento). El PRECIO de venta lo sigue resolviendo SIEMPRE el servidor;
// esta API solo administra las listas. Perms: inventory.pricelist.read/write.
export interface PriceListRow {
  id: number;
  name: string;
  currency: string;
  is_active: boolean;
  created_at: string;
}
export interface PriceListItemRow {
  id: number;
  item_id: number;
  min_qty: string;
  price: string;
}
export interface PriceListAssignmentRow {
  id: number;
  party_id: number | null;
  segment: string;
  is_active: boolean;
}
export interface PriceListDetail extends PriceListRow {
  items: PriceListItemRow[];
  assignments: PriceListAssignmentRow[];
}

export async function listPriceLists(
  filters: { currency?: string; is_active?: boolean } = {},
): Promise<PriceListRow[]> {
  const params: Record<string, string | number | boolean> = { ...PAGE };
  if (filters.currency) params.currency = filters.currency;
  if (filters.is_active !== undefined) params.is_active = filters.is_active;
  const { data } = await api.get<Paginated<PriceListRow>>('/inventory/pricelists/', { params });
  return data.results;
}
export async function createPriceList(body: {
  name: string;
  currency?: string;
  is_active?: boolean;
}): Promise<PriceListDetail> {
  const { data } = await api.post<PriceListDetail>('/inventory/pricelists/', body);
  return data;
}
export async function getPriceList(id: number): Promise<PriceListDetail> {
  const { data } = await api.get<PriceListDetail>(`/inventory/pricelists/${id}/`);
  return data;
}
export async function updatePriceList(
  id: number,
  body: { name?: string; currency?: string; is_active?: boolean },
): Promise<PriceListDetail> {
  const { data } = await api.patch<PriceListDetail>(`/inventory/pricelists/${id}/`, body);
  return data;
}
export async function upsertPriceListItem(
  id: number,
  body: { item_id: number; min_qty?: number; price: number },
): Promise<PriceListItemRow> {
  const { data } = await api.post<PriceListItemRow>(`/inventory/pricelists/${id}/items/`, body);
  return data;
}
export async function deletePriceListItem(id: number, lineId: number): Promise<void> {
  await api.delete(`/inventory/pricelists/${id}/items/${lineId}/`);
}
export async function createPriceListAssignment(
  id: number,
  body: { party_id?: number | null; segment?: string },
): Promise<PriceListAssignmentRow> {
  const { data } = await api.post<PriceListAssignmentRow>(
    `/inventory/pricelists/${id}/assignments/`,
    body,
  );
  return data;
}
export async function deletePriceListAssignment(id: number, assignId: number): Promise<void> {
  await api.delete(`/inventory/pricelists/${id}/assignments/${assignId}/`);
}

export const PRICELIST_MENSAJES: Record<string, string> = {
  PRICELIST_NAME_CONFLICT: 'Ya existe una lista con ese nombre.',
  PRICELIST_ASSIGNMENT_CONFLICT: 'Ese cliente o segmento ya tiene una lista asignada.',
  PRICELIST_NOT_FOUND: 'La lista de precios no existe.',
  INVENTORY_ITEM_NOT_FOUND: 'El artículo no existe en esta empresa.',
  PARTY_NOT_FOUND: 'El cliente no existe en esta empresa.',
};
