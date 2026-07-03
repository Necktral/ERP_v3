<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton to="/contabilidad" />
    </div>
    <PageHeader
      title="Consolidación del grupo"
      subtitle="Estados financieros consolidados del holding por período: corre la consolidación de varias empresas (elimina los cruces intercompañía) y mira la balanza, el estado de resultados y el balance general del grupo."
      :loading="corriendo || cargandoReportes"
      @refresh="recargarReportes"
    />

    <!-- Formulario de corrida -->
    <q-card flat bordered class="app-card q-mb-md">
      <q-card-section class="row items-center q-col-gutter-md">
        <q-input class="col-auto" v-model.number="form.year" type="number" min="2000" max="2100" label="Año" outlined dense style="width: 110px" />
        <q-select class="col-auto" v-model="form.month" :options="mesesOpts" label="Mes" outlined dense emit-value map-options options-dense style="width: 150px" />
        <q-select
          class="col"
          v-model="form.company_ids"
          :options="empresaOpts"
          label="Empresas a consolidar *"
          outlined
          dense
          multiple
          use-chips
          emit-value
          map-options
          options-dense
          style="min-width: 240px"
        />
        <q-toggle class="col-auto" v-model="form.strict" label="Estricto" />
        <q-btn class="col-auto" unelevated no-caps color="primary" icon="account_tree" label="Correr consolidación" :loading="corriendo" :disable="!form.company_ids.length" @click="correr" />
      </q-card-section>
      <q-separator v-if="run" />
      <q-card-section v-if="run" class="row items-center q-gutter-sm">
        <q-chip dense square :color="run.status === 'BLOCKED' ? 'negative' : 'positive'" text-color="white" :icon="run.status === 'BLOCKED' ? 'block' : 'verified'" :label="run.status === 'BLOCKED' ? 'Bloqueada' : 'Consolidada'" />
        <span class="text-caption text-muted">Corrida {{ run.run_id.slice(0, 8) }} · {{ run.issues_count }} incidencia(s){{ run.idempotent ? ' · ya existía' : '' }}</span>
        <q-btn flat dense no-caps size="sm" color="primary" icon="summarize" label="Ver resumen" :loading="cargandoResumen" @click="verResumen" />
        <span v-if="run.status === 'BLOCKED'" class="text-caption text-negative">
          Hay incidencias que impiden consolidar (p. ej. cruces intercompañía descuadrados). Revisá y reintentá; con "Estricto" apagado se consolida igual.
        </span>
      </q-card-section>
    </q-card>

    <!-- Diálogo: resumen persistido de la corrida -->
    <q-dialog v-model="dlgResumen">
      <q-card class="app-dialog" style="min-width: min(480px, 92vw)">
        <q-card-section class="text-h6">Resumen de la corrida</q-card-section>
        <q-card-section v-if="resumen" class="q-pt-none">
          <q-list dense>
            <q-item v-for="fila in filasResumen" :key="fila.label">
              <q-item-section>
                <q-item-label caption>{{ fila.label }}</q-item-label>
                <q-item-label>{{ fila.value }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
          <template v-if="incidenciasResumen.length">
            <div class="text-caption text-negative q-mt-sm">Incidencias</div>
            <q-list dense>
              <q-item v-for="(cod, i) in incidenciasResumen" :key="i">
                <q-item-section avatar><q-icon name="error" color="negative" size="18px" /></q-item-section>
                <q-item-section>{{ cod }}</q-item-section>
              </q-item>
            </q-list>
          </template>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cerrar" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Reportes consolidados -->
    <template v-if="run && run.status !== 'BLOCKED'">
      <q-tabs v-model="tab" align="left" dense class="text-primary q-mb-md" narrow-indicator>
        <q-tab name="balanza" no-caps label="Balanza" />
        <q-tab name="resultados" no-caps label="Estado de resultados" />
        <q-tab name="balance" no-caps label="Balance general" />
      </q-tabs>

      <q-tab-panels v-model="tab" animated>
        <!-- Balanza -->
        <q-tab-panel name="balanza" class="q-pa-none">
          <q-table :rows="trial" :columns="colsTrial" row-key="account_code" flat bordered dense :loading="cargandoReportes" :pagination="{ rowsPerPage: 50 }" no-data-label="Sin movimientos consolidados.">
            <template #body-cell-debito="props"><q-td :props="props" class="text-right">{{ formatMoney(props.row.debit_net) }}</q-td></template>
            <template #body-cell-credito="props"><q-td :props="props" class="text-right">{{ formatMoney(props.row.credit_net) }}</q-td></template>
            <template #body-cell-saldo="props"><q-td :props="props" class="text-right">{{ formatMoney(props.row.net_balance) }}</q-td></template>
          </q-table>
        </q-tab-panel>

        <!-- Estado de resultados -->
        <q-tab-panel name="resultados" class="q-pa-none">
          <div v-if="pnl" class="row q-col-gutter-md q-mb-md">
            <div class="col-6 col-md-4"><q-card flat bordered class="app-card kpi"><div class="kpi__label">Ingresos</div><div class="kpi__value">{{ formatMoney(pnl.totals.revenue) }}</div></q-card></div>
            <div class="col-6 col-md-4"><q-card flat bordered class="app-card kpi"><div class="kpi__label">Gastos</div><div class="kpi__value">{{ formatMoney(pnl.totals.expense) }}</div></q-card></div>
            <div class="col-12 col-md-4"><q-card flat bordered class="app-card kpi" :class="netoColor"><div class="kpi__label">Resultado neto</div><div class="kpi__value">{{ formatMoney(pnl.totals.net_income) }}</div></q-card></div>
          </div>
          <q-table :rows="pnl?.rows ?? []" :columns="colsPnl" row-key="account_code" flat bordered dense :pagination="{ rowsPerPage: 50 }" no-data-label="Sin cuentas de resultado.">
            <template #body-cell-balance="props"><q-td :props="props" class="text-right">{{ formatMoney(props.row.balance) }}</q-td></template>
          </q-table>
        </q-tab-panel>

        <!-- Balance general -->
        <q-tab-panel name="balance" class="q-pa-none">
          <div v-if="bs" class="text-caption text-muted q-mb-sm">Al {{ bs.as_of }}</div>
          <div v-if="bs" class="row q-col-gutter-md">
            <div v-for="sec in seccionesBs" :key="sec.titulo" class="col-12 col-md-4">
              <q-card flat bordered class="app-card">
                <q-card-section class="row items-center justify-between">
                  <div class="text-subtitle1">{{ sec.titulo }}</div>
                  <b>{{ formatMoney(sec.data.total) }}</b>
                </q-card-section>
                <q-separator />
                <q-list dense>
                  <q-item v-for="r in sec.data.rows" :key="r.account_code">
                    <q-item-section><q-item-label>{{ r.account_name }}</q-item-label><q-item-label caption>{{ r.account_code }}</q-item-label></q-item-section>
                    <q-item-section side><span>{{ formatMoney(r.balance) }}</span></q-item-section>
                  </q-item>
                  <q-item v-if="!sec.data.rows.length"><q-item-section class="text-muted">—</q-item-section></q-item>
                </q-list>
              </q-card>
            </div>
          </div>
        </q-tab-panel>
      </q-tab-panels>
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatDateTime, formatMoney } from 'src/core/format';
import { listCompanies } from 'src/modules/org/api';
import {
  getConsolBalanceSheet,
  getConsolPnl,
  getConsolTrialBalance,
  getConsolidationRunSummary,
  runConsolidation,
  type ConsolBalanceSheet,
  type ConsolPnl,
  type ConsolTrialRow,
  type ConsolidationRunResult,
  type ConsolidationRunSummary,
} from 'src/modules/accounting/api';

const $q = useQuasar();
const now = new Date();
const form = ref<{ year: number; month: number; company_ids: number[]; strict: boolean }>({
  year: now.getFullYear(),
  month: now.getMonth() + 1,
  company_ids: [],
  strict: true,
});
const empresaOpts = ref<{ label: string; value: number }[]>([]);
const mesesOpts = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
].map((label, i) => ({ label, value: i + 1 }));

const corriendo = ref(false);
const cargandoReportes = ref(false);
const run = ref<ConsolidationRunResult | null>(null);
const tab = ref<'balanza' | 'resultados' | 'balance'>('balanza');
const trial = ref<ConsolTrialRow[]>([]);
const pnl = ref<ConsolPnl | null>(null);
const bs = ref<ConsolBalanceSheet | null>(null);

const colsTrial: QTableColumn<ConsolTrialRow>[] = [
  { name: 'account_code', label: 'Cuenta', field: 'account_code', align: 'left', sortable: true },
  { name: 'account_name', label: 'Nombre', field: 'account_name', align: 'left' },
  { name: 'account_type', label: 'Tipo', field: 'account_type', align: 'left' },
  { name: 'debito', label: 'Débito', field: 'debit_net', align: 'right' },
  { name: 'credito', label: 'Crédito', field: 'credit_net', align: 'right' },
  { name: 'saldo', label: 'Saldo', field: 'net_balance', align: 'right' },
];
const colsPnl: QTableColumn<ConsolPnl['rows'][number]>[] = [
  { name: 'account_code', label: 'Cuenta', field: 'account_code', align: 'left', sortable: true },
  { name: 'account_name', label: 'Nombre', field: 'account_name', align: 'left' },
  { name: 'account_type', label: 'Tipo', field: 'account_type', align: 'left' },
  { name: 'balance', label: 'Saldo', field: 'balance', align: 'right' },
];

const netoColor = computed(() => {
  if (!pnl.value) return '';
  return Number(pnl.value.totals.net_income) >= 0 ? 'kpi--ok' : 'kpi--bad';
});
const seccionesBs = computed(() => {
  if (!bs.value) return [];
  return [
    { titulo: 'Activos', data: bs.value.assets },
    { titulo: 'Pasivos', data: bs.value.liabilities },
    { titulo: 'Patrimonio', data: bs.value.equity },
  ];
});

async function correr() {
  if (!form.value.company_ids.length) return;
  corriendo.value = true;
  run.value = null;
  trial.value = [];
  pnl.value = null;
  bs.value = null;
  try {
    run.value = await runConsolidation({
      year: form.value.year,
      month: form.value.month,
      company_ids: form.value.company_ids,
      strict: form.value.strict,
    });
    if (run.value.status !== 'BLOCKED') {
      await recargarReportes();
      $q.notify({ type: 'positive', message: 'Consolidación lista.' });
    } else {
      $q.notify({ type: 'warning', message: `Consolidación bloqueada: ${run.value.issues_count} incidencia(s).` });
    }
  } catch (e) {
    // 409 = corrida BLOQUEADA: el cuerpo trae el detalle de la corrida.
    const resp = (e as { response?: { status?: number; data?: ConsolidationRunResult } })?.response;
    if (resp?.status === 409 && resp.data) {
      run.value = resp.data;
      $q.notify({ type: 'warning', message: `Consolidación bloqueada: ${resp.data.issues_count} incidencia(s).` });
    } else {
      $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo correr la consolidación.') });
    }
  } finally {
    corriendo.value = false;
  }
}

// --- Resumen persistido de la corrida (GET /consolidation/runs/<id>/summary/) ---
const dlgResumen = ref(false);
const cargandoResumen = ref(false);
const resumen = ref<ConsolidationRunSummary | null>(null);

async function verResumen() {
  if (!run.value) return;
  cargandoResumen.value = true;
  try {
    resumen.value = await getConsolidationRunSummary(run.value.run_id);
    dlgResumen.value = true;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el resumen de la corrida.') });
  } finally {
    cargandoResumen.value = false;
  }
}

const filasResumen = computed<{ label: string; value: string }[]>(() => {
  const r = resumen.value;
  if (!r) return [];
  const s = (r.summary ?? {}) as Record<string, unknown>;
  const metrics = (typeof s.metrics === 'object' && s.metrics !== null ? s.metrics : {}) as Record<string, unknown>;
  const mes = mesesOpts.find((m) => m.value === r.month)?.label ?? String(r.month);
  const filas = [
    { label: 'Corrida', value: r.run_id },
    { label: 'Estado', value: r.status === 'BLOCKED' ? 'Bloqueada' : r.status === 'COMPLETED' ? 'Consolidada' : r.status },
    { label: 'Período', value: `${mes} ${r.year}` },
    { label: 'Empresas consolidadas', value: r.company_ids.join(', ') || '—' },
    { label: 'Iniciada', value: r.started_at ? formatDateTime(r.started_at) : '—' },
    { label: 'Completada', value: r.completed_at ? formatDateTime(r.completed_at) : '—' },
  ];
  // Métricas del summary_json (en corridas bloqueadas vienen al nivel raíz).
  const filasConsol = metrics.rows_count ?? null;
  const eliminaciones = metrics.elimination_count ?? s.elimination_count ?? null;
  if (typeof filasConsol === 'number') filas.push({ label: 'Cuentas consolidadas', value: String(filasConsol) });
  if (typeof eliminaciones === 'number') filas.push({ label: 'Eliminaciones intercompañía', value: String(eliminaciones) });
  if (r.output_manifest_hash) filas.push({ label: 'Manifest de salida', value: r.output_manifest_hash.slice(0, 16) + '…' });
  return filas;
});

const incidenciasResumen = computed<string[]>(() => {
  const s = (resumen.value?.summary ?? {}) as Record<string, unknown>;
  const issues = Array.isArray(s.issues) ? s.issues : [];
  return issues.map((i) =>
    i && typeof i === 'object' && 'code' in i ? String((i as Record<string, unknown>).code) : String(i),
  );
});

async function recargarReportes() {
  if (!run.value || run.value.status === 'BLOCKED') return;
  const runId = run.value.run_id;
  cargandoReportes.value = true;
  try {
    const [tb, pl, b] = await Promise.all([
      getConsolTrialBalance(runId),
      getConsolPnl(runId),
      getConsolBalanceSheet(runId),
    ]);
    trial.value = tb.results;
    pnl.value = pl;
    bs.value = b;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar los reportes consolidados.') });
  } finally {
    cargandoReportes.value = false;
  }
}

onMounted(async () => {
  try {
    const cos = await listCompanies();
    empresaOpts.value = cos.map((c) => ({ label: c.name, value: c.id }));
  } catch {
    /* noop: el selector queda vacío si no hay empresas */
  }
});
</script>

<style scoped>
.kpi {
  padding: var(--app-space-4);
}
.kpi__label {
  font-size: 0.78rem;
  color: var(--app-text-muted, #888);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.kpi__value {
  font-size: 1.5rem;
  font-weight: 700;
  font-family: 'Manrope', sans-serif;
  margin-top: 2px;
}
.kpi--ok .kpi__value {
  color: var(--app-positive, #2e7d32);
}
.kpi--bad .kpi__value {
  color: var(--app-negative, #c0392b);
}
</style>
