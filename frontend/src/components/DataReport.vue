<template>
  <div class="dr">
    <div v-if="kpis.length" class="dr-kpis">
      <div v-for="k in kpis" :key="k.key" class="dr-kpi">
        <div class="dr-kpi__label">{{ pretty(k.key) }}</div>
        <div class="dr-kpi__value">{{ fmt(k.value) }}</div>
      </div>
    </div>

    <div v-for="sec in sections" :key="sec.key" class="dr-section">
      <div class="dr-section__title">{{ pretty(sec.key) }}</div>
      <q-markup-table v-if="sec.rows.length" flat dense class="dr-table">
        <thead>
          <tr>
            <th v-for="c in sec.cols" :key="c" class="text-left">{{ pretty(c) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in sec.rows" :key="i">
            <td v-for="c in sec.cols" :key="c">{{ fmt(row[c]) }}</td>
          </tr>
        </tbody>
      </q-markup-table>
      <div v-else class="dr-empty">Sin filas.</div>
    </div>

    <div v-if="!kpis.length && !sections.length" class="dr-empty">Sin datos para los filtros elegidos.</div>
  </div>
</template>

<script setup lang="ts">
/**
 * Renderer genérico de un objeto-reporte del backend: escalares → KPIs, arreglos de
 * objetos → tablas, objetos anidados → tabla de una fila. Reutilizable por cualquier
 * pantalla de reporte (finca, intercompañía, etc.) para no volcar JSON crudo.
 */
import { computed } from 'vue';

const props = defineProps<{ data: Record<string, unknown> | null }>();

interface Kpi {
  key: string;
  value: unknown;
}
interface Section {
  key: string;
  cols: string[];
  rows: Record<string, unknown>[];
}

// Etiquetas en español para claves comunes; fallback = prettify.
const LABELS: Record<string, string> = {
  total: 'Total',
  total_cost: 'Costo total',
  cost: 'Costo',
  amount: 'Monto',
  labor_cost: 'Mano de obra',
  insumo_cost: 'Insumos',
  insumos_cost: 'Insumos',
  jornales: 'Jornales',
  jornales_total: 'Jornales',
  by_labor: 'Por labor',
  by_plot: 'Por lote',
  by_zone: 'Por zona',
  by_zona: 'Por zona',
  by_finca: 'Por finca',
  by_company: 'Por empresa',
  finca_id: 'Finca (id)',
  plots: 'Lotes',
  empresa: 'Empresa',
  cxc_external: 'CxC externa',
  cxc_intercompany: 'CxC intercompañía',
  cxp_external: 'CxP externa',
  cxp_intercompany: 'CxP intercompañía',
  results: 'Detalle',
  rows: 'Detalle',
  finca: 'Finca',
  finca_name: 'Finca',
  plot: 'Lote',
  plot_name: 'Lote',
  labor: 'Labor',
  labor_name: 'Labor',
  labor_code: 'Código labor',
  zone: 'Zona',
  season: 'Ciclo',
  company: 'Empresa',
  company_name: 'Empresa',
  qty: 'Cantidad',
  quantity: 'Cantidad',
  unit: 'Unidad',
  days: 'Días',
  workers: 'Trabajadores',
  rate: 'Tarifa',
  variance: 'Variación',
  budget: 'Presupuesto',
  actual: 'Real',
  currency: 'Moneda',
  matched: 'Conciliados',
  unmatched: 'Sin conciliar',
  missing: 'Faltantes',
  receivable: 'Por cobrar',
  payable: 'Por pagar',
  balance: 'Saldo',
};

function pretty(key: string): string {
  if (LABELS[key]) return LABELS[key];
  const s = key.replace(/[._]/g, ' ').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : key;
}

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'number') {
    return Number.isNaN(v) ? '—' : v.toLocaleString('es-NI', { maximumFractionDigits: 2 });
  }
  if (typeof v === 'string') {
    return /^-?\d+(\.\d+)?$/.test(v)
      ? Number(v).toLocaleString('es-NI', { maximumFractionDigits: 2 })
      : v;
  }
  if (typeof v === 'boolean') return v ? 'Sí' : 'No';
  if (Array.isArray(v)) return `${v.length} ítem(s)`;
  return '—';
}

function isScalar(v: unknown): boolean {
  return v === null || ['string', 'number', 'boolean'].includes(typeof v);
}
function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

const kpis = computed<Kpi[]>(() => {
  const d = props.data;
  if (!d) return [];
  const out: Kpi[] = [];
  for (const [key, value] of Object.entries(d)) {
    if (isScalar(value)) out.push({ key, value });
    else if (Array.isArray(value) && !value.some((x) => isObject(x))) out.push({ key, value });
  }
  return out;
});

const sections = computed<Section[]>(() => {
  const d = props.data;
  if (!d) return [];
  const out: Section[] = [];
  for (const [key, value] of Object.entries(d)) {
    let rows: Record<string, unknown>[] | null = null;
    if (Array.isArray(value) && value.some((x) => isObject(x))) {
      rows = value.filter(isObject);
    } else if (isObject(value)) {
      // objeto anidado: si tiene escalares, mostrarlo como tabla de una fila
      if (Object.values(value).some(isScalar)) rows = [value];
    }
    if (rows && rows.length) {
      const cols: string[] = [];
      for (const r of rows) for (const c of Object.keys(r)) if (!cols.includes(c)) cols.push(c);
      out.push({ key, cols, rows });
    }
  }
  return out;
});
</script>

<style scoped>
.dr {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-5);
}
.dr-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: var(--app-space-3);
}
.dr-kpi {
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
}
.dr-kpi__label {
  font-size: 0.74rem;
  color: var(--app-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.dr-kpi__value {
  font-family: 'Manrope', 'IBM Plex Sans', sans-serif;
  font-weight: 800;
  font-size: 1.1rem;
  color: var(--app-text);
}
.dr-section__title {
  font-weight: 800;
  color: var(--app-text);
  margin-bottom: var(--app-space-2);
}
.dr-table {
  background: transparent;
}
.dr-empty {
  color: var(--app-text-muted);
  font-size: 0.85rem;
}
</style>
