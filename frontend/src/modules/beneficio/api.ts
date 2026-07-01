/**
 * Beneficio de café (transformación con merma): recetas insumo→producto y
 * órdenes de procesamiento que mueven stock (consumen insumo, reciben producto).
 * Mapea los endpoints reales de `apps.modulos.beneficio`. Las pantallas NO llaman
 * axios directo: usan estas funciones tipadas.
 * Montaje backend: `api/beneficio/` → con baseURL `/api` => `/beneficio/...`.
 * Las acciones que mueven stock (iniciar/cerrar) exigen sucursal (X-Branch-Id,
 * que el interceptor de axios envía desde el contexto).
 */
import { api } from 'src/boot/axios';

export type OrderStatus = 'DRAFT' | 'IN_PROCESS' | 'DONE' | 'CANCELLED';

export const ORDER_STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Borrador',
  IN_PROCESS: 'En proceso',
  DONE: 'Cerrada',
  CANCELLED: 'Anulada',
};

// ---------- Recetas de transformación ----------
export interface RecipeRow {
  id: number;
  code: string;
  name: string;
  input_item_id: number;
  input_item_name: string;
  output_item_id: number;
  output_item_name: string;
  expected_yield_pct: string;
  yield_tolerance_pct: string;
  is_active: boolean;
}
export async function listRecipes(): Promise<RecipeRow[]> {
  const { data } = await api.get<{ results: RecipeRow[] }>('/beneficio/recipes/');
  return data.results;
}
export async function createRecipe(body: {
  code: string;
  name: string;
  input_item_id: number;
  output_item_id: number;
  expected_yield_pct: number;
  yield_tolerance_pct?: number;
}): Promise<RecipeRow> {
  const { data } = await api.post<RecipeRow>('/beneficio/recipes/', body);
  return data;
}

// ---------- Órdenes de procesamiento ----------
export interface OrderRow {
  id: number;
  reference: string;
  recipe_id: number;
  recipe_code: string;
  input_warehouse_id: number;
  output_warehouse_id: number;
  input_qty: string;
  output_qty: string | null;
  status: OrderStatus;
  input_cost_total: string | null;
  output_unit_cost: string | null;
  yield_pct: string | null;
  shrinkage_qty: string | null;
  issue_movement_id: number | null;
  receive_movement_id: number | null;
  started_at: string | null;
  finished_at: string | null;
  note: string;
  created_at: string;
}
export async function listOrders(status?: OrderStatus): Promise<OrderRow[]> {
  const { data } = await api.get<{ results: OrderRow[] }>('/beneficio/orders/', {
    params: status ? { status } : undefined,
  });
  return data.results;
}
export async function createOrder(body: {
  recipe_id: number;
  input_warehouse_id: number;
  output_warehouse_id: number;
  input_qty: number;
  reference?: string;
  note?: string;
}): Promise<OrderRow> {
  const { data } = await api.post<OrderRow>('/beneficio/orders/', body);
  return data;
}
export async function startOrder(orderId: number): Promise<OrderRow> {
  const { data } = await api.post<OrderRow>(`/beneficio/orders/${orderId}/start/`, {});
  return data;
}
export async function closeOrder(orderId: number, outputQty: number): Promise<OrderRow> {
  const { data } = await api.post<OrderRow>(`/beneficio/orders/${orderId}/close/`, {
    output_qty: outputQty,
  });
  return data;
}
export async function cancelOrder(orderId: number): Promise<OrderRow> {
  const { data } = await api.post<OrderRow>(`/beneficio/orders/${orderId}/cancel/`, {});
  return data;
}

export const BENEFICIO_MENSAJES: Record<string, string> = {
  BEN_KERNEL: 'No hay stock suficiente del insumo en la bodega de entrada.',
  BEN_YIELD_OUT_OF_RANGE: 'El rendimiento quedó fuera de la tolerancia de la receta.',
  BEN_INVALID_STATE: 'La orden no está en un estado que permita esa acción.',
};
