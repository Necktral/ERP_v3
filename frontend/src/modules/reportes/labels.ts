/**
 * Etiquetas y formato compartidos del módulo de Reportes: títulos en español de
 * los datasets del catálogo (el backend los trae en inglés), etiquetas de
 * medidas/dimensiones y estilos de estado para chips.
 */
import type { EstadoEstilo } from 'src/components/EstadoChip.vue';

/** Títulos en español por dataset_key (fallback: title del backend). */
export const DATASET_TITLES: Record<string, string> = {
  'accounting.pnl.period': 'Estado de Resultados',
  'accounting.balance_sheet.as_of': 'Balance General',
  'accounting.trial_balance.period': 'Balanza de Comprobación',
  'accounting.general_ledger.transaction': 'Libro Mayor',
  'accounting.operational_reconciliation.period': 'Conciliación Operativa',
  'fuel.sales.by_shift.daily': 'Ventas de Combustible por Turno',
  'fuel.sales.by_pump.daily': 'Ventas de Combustible por Surtidor',
  'fuel.dispense_vs_sale.daily': 'Despacho vs Venta de Combustible',
  'billing.summary.period': 'Resumen de Facturación',
  'inventory.stock_balance.current': 'Existencias',
  'inventory.movements.period': 'Movimientos de Inventario',
  'hr.headcount.current': 'Plantilla de Personal',
  'payments.collection.period': 'Cobranzas',
  'procurement.purchases.period': 'Resumen de Compras',
};

/** Etiquetas en español para medidas/dimensiones comunes; fallback = prettify. */
const FIELD_LABELS: Record<string, string> = {
  revenue: 'Ingresos',
  expense: 'Gastos',
  net_income: 'Utilidad neta',
  assets: 'Activos',
  liabilities_plus_equity: 'Pasivo + Patrimonio',
  debit_total: 'Débito',
  credit_total: 'Crédito',
  net_balance: 'Saldo neto',
  balance: 'Saldo',
  account_code: 'Cuenta',
  account_name: 'Nombre de cuenta',
  account_type: 'Tipo',
  total_amount: 'Monto total',
  amount_total: 'Monto total',
  amount_sold: 'Monto vendido',
  liters_sold: 'Litros vendidos',
  liters: 'Litros',
  liters_dispensed: 'Litros despachados',
  sales_active: 'Ventas',
  sales_cancelled: 'Anuladas',
  cancelled_sales: 'Ventas anuladas',
  sales_count: 'N.º de ventas',
  dispense_count: 'N.º de despachos',
  operational_events: 'Eventos operativos',
  economic_events_linked: 'Eventos contables ligados',
  shift: 'Turno',
  pump: 'Surtidor',
  product: 'Producto',
  warehouse: 'Bodega',
  quantity: 'Cantidad',
  year: 'Año',
  month: 'Mes',
  date_from: 'Desde',
  date_to: 'Hasta',
  as_of: 'Al corte',
};

export function pretty(key: string): string {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key];
  const s = key.replace(/[._]/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Título del dataset en español (o el del backend/la key como fallback). */
export function datasetTitle(key: string, backendTitle?: string): string {
  return DATASET_TITLES[key] || backendTitle || key;
}

export function qualityColor(q: string): string {
  if (q === 'PASS') return 'positive';
  if (q === 'WARN') return 'warning';
  return 'negative';
}

export function qualityLabel(q: string): string {
  if (q === 'PASS') return 'OK';
  if (q === 'WARN') return 'Revisar';
  if (q === 'FAIL') return 'Sin datos';
  return q;
}

/** Estados de un run (RunStatus del backend) para EstadoChip. */
export const RUN_ESTADOS: Record<string, EstadoEstilo> = {
  RUNNING: { label: 'Ejecutando', color: 'warning', textColor: 'white' },
  SUCCEEDED: { label: 'Exitoso', color: 'secondary', textColor: 'white' },
  FAILED: { label: 'Fallido', color: 'negative', textColor: 'white' },
};

/** Estados de un snapshot (SnapshotStatus del backend) para EstadoChip. */
export const SNAPSHOT_ESTADOS: Record<string, EstadoEstilo> = {
  ACTIVE: { label: 'Activo', color: 'secondary', textColor: 'white' },
  EXPIRED: { label: 'Expirado', color: 'grey-7', outline: true },
  FAILED: { label: 'Fallido', color: 'negative', textColor: 'white' },
};

/** Estados de un export (ExportStatus del backend) para EstadoChip. */
export const EXPORT_ESTADOS: Record<string, EstadoEstilo> = {
  PENDING: { label: 'Pendiente', color: 'warning', textColor: 'white' },
  SUCCEEDED: { label: 'Listo', color: 'secondary', textColor: 'white' },
  FAILED: { label: 'Fallido', color: 'negative', textColor: 'white' },
};

/** Frescura del dataset, legible. */
export const FRESHNESS_LABELS: Record<string, string> = {
  LIVE_ONLY: 'En vivo',
  CACHE_ALLOWED: 'Caché permitido',
  SNAPSHOT_REQUIRED: 'Con snapshot',
};

/** Formatea un valor de celda/total: números como es-NI, moneda si aplica. */
export function fmtValor(v: unknown, currency: boolean): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'number') {
    if (Number.isNaN(v)) return '—';
    return fmtNumero(v, currency);
  }
  if (typeof v === 'string') {
    return /^-?\d+(\.\d+)?$/.test(v) ? fmtNumero(Number(v), currency) : v;
  }
  if (typeof v === 'boolean') return v ? 'Sí' : 'No';
  return '—'; // objetos/arrays no esperados en celdas/totales
}

function fmtNumero(n: number, currency: boolean): string {
  const s = n.toLocaleString('es-NI', {
    minimumFractionDigits: currency ? 2 : 0,
    maximumFractionDigits: currency ? 2 : 4,
  });
  return currency ? `C$ ${s}` : s;
}
