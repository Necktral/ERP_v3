<template>
  <q-page class="app-page-container">
    <PageHeader title="Analítica" :subtitle="subtitle" :loading="loading" @refresh="reloadAll" />

    <div class="ana-toolbar">
      <q-btn-toggle
        v-if="wsOptions.length"
        v-model="activeWs"
        :options="wsOptions"
        no-caps
        unelevated
        toggle-color="primary"
        color="grey-3"
        text-color="grey-9"
      />
      <q-space />
      <q-input
        v-model.number="year"
        type="number"
        dense
        outlined
        label="Año"
        class="ana-filter"
        @keyup.enter="reloadAll"
      />
      <q-input
        v-model.number="month"
        type="number"
        dense
        outlined
        label="Mes"
        class="ana-filter"
        @keyup.enter="reloadAll"
      />
      <q-btn no-caps unelevated color="primary" icon="play_arrow" label="Aplicar" @click="reloadAll" />
    </div>

    <div v-if="reports.length" class="ana-reports">
      <q-card v-for="r in reports" :key="r.key" flat bordered class="rep-card">
        <q-card-section class="rep-head">
          <div>
            <div class="rep-title">{{ r.title }}</div>
            <div v-if="r.desc" class="rep-desc">{{ r.desc }}</div>
          </div>
          <q-chip
            v-if="r.quality"
            dense
            square
            size="sm"
            :color="qualityColor(r.quality)"
            text-color="white"
            :label="qualityLabel(r.quality)"
          />
        </q-card-section>
        <q-separator />

        <q-card-section v-if="r.error" class="rep-error">
          <q-icon name="lock" size="18px" /> {{ r.error }}
        </q-card-section>

        <template v-else>
          <q-card-section v-if="r.totals.length" class="rep-kpis">
            <div v-for="t in r.totals" :key="t[0]" class="kpi">
              <div class="kpi-label">{{ pretty(t[0]) }}</div>
              <div class="kpi-value">{{ fmt(t[1], r.currency) }}</div>
            </div>
          </q-card-section>

          <q-markup-table v-if="r.rows.length" flat dense class="rep-table">
            <thead>
              <tr>
                <th v-for="c in r.columns" :key="c" class="text-left">{{ pretty(c) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in r.rows" :key="i">
                <td v-for="c in r.columns" :key="c">{{ cell(row, c, r) }}</td>
              </tr>
            </tbody>
          </q-markup-table>
          <q-card-section v-else class="rep-empty">
            Sin filas para el período seleccionado.
          </q-card-section>

          <q-card-section class="rep-actions">
            <q-btn flat dense no-caps size="sm" icon="download" label="CSV" :disable="!r.run_id" @click="exportar(r, 'csv')" />
            <q-btn flat dense no-caps size="sm" icon="download" label="XLSX" :disable="!r.run_id" @click="exportar(r, 'xlsx')" />
            <q-btn flat dense no-caps size="sm" icon="photo_camera" label="Snapshot" @click="snapshot(r)" />
            <q-btn flat dense no-caps size="sm" icon="bookmark_add" label="Guardar vista" @click="guardarVista(r)" />
            <q-chip
              v-for="v in vistasDe(r.key)"
              :key="v.view_id"
              dense
              clickable
              size="sm"
              icon="bookmark"
              color="grey-3"
              text-color="grey-9"
              @click="aplicarVista(v)"
            >
              {{ v.name }}
            </q-chip>
          </q-card-section>
        </template>
      </q-card>
    </div>

    <q-banner v-else-if="!loading" class="ana-empty">
      <template #avatar><q-icon name="info" color="primary" /></template>
      No hay reportes disponibles en este workspace (o sin permiso).
    </q-banner>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { useQuasar } from 'quasar';
import { listWorkspaces, type WorkspaceRow } from 'src/modules/dashboard/api';
// El consumo del kernel reporting vive en el módulo de Reportes (una sola casa
// para las rutas /reporting/*); Analítica reusa esas funciones.
import {
  createRunExport,
  createSavedView,
  generateSnapshot,
  listSavedViews,
  runDataset,
  type DatasetEnvelope,
  type SavedView,
} from 'src/modules/reportes/api';

interface ReportView {
  key: string;
  title: string;
  desc: string;
  quality: string;
  currency: boolean;
  totals: [string, unknown][];
  columns: string[];
  measures: Set<string>;
  rows: Record<string, unknown>[];
  run_id: string | null;
  error: string | null;
}

const $q = useQuasar();

const workspaces = ref<WorkspaceRow[]>([]);
const activeWs = ref<string>('');
const reports = ref<ReportView[]>([]);
const loading = ref(false);
const lastUpdated = ref<Date | null>(null);
const year = ref<number | null>(null);
const month = ref<number | null>(null);

const wsOptions = computed(() =>
  workspaces.value.map((w) => ({ label: w.title || w.workspace_key, value: w.workspace_key })),
);

const subtitle = computed(() => {
  const n = reports.value.length;
  const base = `${n} ${n === 1 ? 'reporte' : 'reportes'}`;
  if (!lastUpdated.value) return base;
  const hh = lastUpdated.value.toLocaleTimeString('es-NI', { hour: '2-digit', minute: '2-digit' });
  return `${base} · actualizado ${hh}`;
});

// Títulos en español de los datasets del catálogo (el backend los trae en inglés).
const TITLES: Record<string, string> = {
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

// Etiquetas en español para medidas/dimensiones comunes; fallback = prettify.
const LABELS: Record<string, string> = {
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
};

function pretty(key: string): string {
  if (LABELS[key]) return LABELS[key];
  const s = key.replace(/[._]/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function fmtNumber(n: number, currency: boolean): string {
  const s = n.toLocaleString('es-NI', {
    minimumFractionDigits: currency ? 2 : 0,
    maximumFractionDigits: currency ? 2 : 4,
  });
  return currency ? `C$ ${s}` : s;
}

function fmt(v: unknown, currency: boolean): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'number') return Number.isNaN(v) ? '—' : fmtNumber(v, currency);
  if (typeof v === 'string') {
    return /^-?\d+(\.\d+)?$/.test(v) ? fmtNumber(Number(v), currency) : v;
  }
  if (typeof v === 'boolean') return v ? 'Sí' : 'No';
  return '—'; // objetos/arrays no esperados en celdas/totales
}

function cell(row: Record<string, unknown>, col: string, r: ReportView): string {
  // Solo las MEDIDAS se formatean como moneda; las dimensiones (códigos/texto) salen tal cual.
  return fmt(row[col], r.currency && r.measures.has(col));
}

function qualityColor(q: string): string {
  if (q === 'PASS') return 'positive';
  if (q === 'WARN') return 'warning';
  return 'negative';
}
function qualityLabel(q: string): string {
  if (q === 'PASS') return 'OK';
  if (q === 'WARN') return 'Revisar';
  if (q === 'FAIL') return 'Sin datos';
  return q;
}

function toView(key: string, settled: PromiseSettledResult<DatasetEnvelope>): ReportView {
  if (settled.status === 'fulfilled') {
    const e = settled.value;
    const currency = e.render_hints?.numeric_format === 'currency';
    const measures = e.measures ?? [];
    const columns = [...(e.dimensions ?? []), ...measures];
    return {
      key,
      title: TITLES[key] || e.title || key,
      desc: e.description ?? '',
      quality: e.quality_status ?? '',
      currency,
      totals: Object.entries(e.totals ?? {}),
      columns,
      measures: new Set(measures),
      rows: e.rows ?? [],
      run_id: e.run_id ?? null,
      error: null,
    };
  }
  return {
    key,
    title: key,
    desc: '',
    quality: '',
    currency: false,
    totals: [],
    columns: [],
    measures: new Set<string>(),
    rows: [],
    run_id: null,
    error: apiErrorMessage(settled.reason, 'No se pudo cargar el reporte.'),
  };
}

function currentFilters(): Record<string, unknown> {
  const filters: Record<string, unknown> = {};
  if (year.value) filters.year = year.value;
  if (month.value) filters.month = month.value;
  return filters;
}

async function reloadAll() {
  const ws = workspaces.value.find((w) => w.workspace_key === activeWs.value);
  const keys = ws?.datasets ?? [];
  if (!keys.length) {
    reports.value = [];
    return;
  }
  loading.value = true;
  try {
    const filters = currentFilters();
    const results = await Promise.allSettled(keys.map((k) => runDataset(k, filters)));
    reports.value = keys.map((k, i) => toView(k, results[i] as PromiseSettledResult<DatasetEnvelope>));
    lastUpdated.value = new Date();
    void cargarVistas(keys);
  } finally {
    loading.value = false;
  }
}

// --- Reporting avanzado: exportar / snapshot / vistas guardadas ---
const vistas = ref<Map<string, SavedView[]>>(new Map());

function vistasDe(key: string): SavedView[] {
  return vistas.value.get(key) ?? [];
}

async function cargarVistas(keys: string[]) {
  const out = new Map<string, SavedView[]>();
  await Promise.allSettled(
    keys.map(async (k) => {
      try {
        out.set(k, await listSavedViews(k));
      } catch {
        /* sin permiso/vistas */
      }
    }),
  );
  vistas.value = out;
}

async function exportar(r: ReportView, format: 'csv' | 'xlsx') {
  if (!r.run_id) return;
  try {
    const res = await createRunExport(r.run_id, format);
    $q.notify({
      type: 'positive',
      message: `Export ${format.toUpperCase()} generado (${res.status}, ${res.file_size} bytes).`,
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo exportar.') });
  }
}

async function snapshot(r: ReportView) {
  try {
    await generateSnapshot(r.key, currentFilters());
    $q.notify({ type: 'positive', message: 'Snapshot generado.' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo generar el snapshot.') });
  }
}

function guardarVista(r: ReportView) {
  $q.dialog({
    title: 'Guardar vista',
    message: 'Nombre de la vista (guarda el reporte con los filtros actuales):',
    prompt: { model: '', type: 'text', isValid: (v: string) => v.trim().length > 0 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'primary', label: 'Guardar' },
  }).onOk((nombre: string) => {
    void (async () => {
      try {
        await createSavedView({ name: nombre.trim(), dataset_key: r.key, filters: currentFilters() });
        $q.notify({ type: 'positive', message: 'Vista guardada.' });
        await cargarVistas(reports.value.map((x) => x.key));
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo guardar la vista.') });
      }
    })();
  });
}

async function aplicarVista(v: SavedView) {
  const f = v.filters ?? {};
  year.value = typeof f.year === 'number' ? f.year : null;
  month.value = typeof f.month === 'number' ? f.month : null;
  await reloadAll();
}

watch(activeWs, () => void reloadAll());

onMounted(async () => {
  loading.value = true;
  try {
    workspaces.value = await listWorkspaces();
    activeWs.value = workspaces.value[0]?.workspace_key ?? '';
    if (!activeWs.value) {
      reports.value = [];
    }
    // si hay workspace, el watch dispara reloadAll
  } finally {
    if (!activeWs.value) loading.value = false;
  }
});
</script>

<style scoped>
.ana-toolbar {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  flex-wrap: wrap;
  margin-bottom: var(--app-space-5);
}

.ana-filter {
  width: 90px;
}

.ana-reports {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--app-space-5);
}

.rep-card {
  border-radius: var(--app-radius-md);
  border-color: var(--app-border);
  background: var(--app-surface-strong);
  box-shadow: var(--app-shadow-soft);
}

.rep-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}

.rep-title {
  font-family: 'Roboto', 'Segoe UI', system-ui, sans-serif;
  font-weight: 800;
  font-size: 1.02rem;
  color: var(--app-text);
}

.rep-desc {
  color: var(--app-text-muted);
  font-size: 0.82rem;
}

.rep-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--app-space-3);
}

.kpi {
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
}

.kpi-label {
  font-size: 0.74rem;
  color: var(--app-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.kpi-value {
  font-family: 'Roboto', 'Segoe UI', system-ui, sans-serif;
  font-weight: 800;
  font-size: 1.15rem;
  color: var(--app-text);
}

.rep-table {
  background: transparent;
}

.rep-empty {
  color: var(--app-text-muted);
  font-size: 0.85rem;
}

.rep-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  border-top: 1px solid var(--app-border);
}

.rep-error {
  color: var(--app-negative, #c10015);
  font-size: 0.85rem;
}

.ana-empty {
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
  color: var(--app-text);
}
</style>
