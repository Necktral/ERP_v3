<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton to="/financiamiento" />
    </div>
    <PageHeader
      title="Fijación y liquidación"
      subtitle="Fijá el precio del café (precio por libra del día) y liquidá las entregas: valor − deducciones, aplica al préstamo y paga el excedente."
      :loading="loadingFix || loadingLiq"
      @refresh="reloadAll"
    />

    <q-tabs v-model="tab" align="left" dense class="text-primary q-mb-md" narrow-indicator>
      <q-tab name="fijaciones" no-caps label="Fijaciones" />
      <q-tab name="liquidaciones" no-caps label="Liquidaciones" />
    </q-tabs>

    <!-- ===== FIJACIONES ===== -->
    <div v-if="tab === 'fijaciones'">
      <div class="q-mb-md">
        <q-btn unelevated no-caps color="primary" icon="add" label="Nueva fijación" @click="abrirFix" />
      </div>
      <q-table :rows="fixations" :columns="fixCols" row-key="id" flat bordered :loading="loadingFix" v-model:pagination="fixPagination" @request="fixRequest" no-data-label="Sin fijaciones.">
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-chip dense square :color="props.row.status === 'OPEN' ? 'info' : 'positive'" text-color="white" :label="FIXATION_STATUS_LABELS[props.row.status]" />
          </q-td>
        </template>
      </q-table>
    </div>

    <!-- ===== LIQUIDACIONES ===== -->
    <div v-else>
      <div class="q-mb-md">
        <q-btn unelevated no-caps color="primary" icon="add" label="Nueva liquidación" @click="abrirLiq" />
      </div>
      <q-table :rows="liquidations" :columns="liqCols" row-key="id" flat bordered :loading="loadingLiq" v-model:pagination="liqPagination" @request="liqRequest" no-data-label="Sin liquidaciones." />
    </div>

    <!-- Nueva fijación -->
    <q-dialog v-model="fixOpen">
      <q-card class="app-dialog" style="min-width: 380px">
        <q-card-section class="text-h6">Nueva fijación de precio</q-card-section>
        <q-card-section class="q-gutter-md">
          <q-select v-model="fFix.producer_id" :options="prodOpts" label="Productor *" outlined dense emit-value map-options options-dense />
          <div class="row q-col-gutter-md">
            <q-input class="col" v-model.number="fFix.pounds" type="number" label="Libras *" outlined dense />
            <q-input class="col" v-model.number="fFix.price_per_lb" type="number" step="0.0001" label="Precio/lb *" outlined dense />
          </div>
          <q-select v-model="fFix.currency" :options="monedaOpts" label="Moneda" outlined dense emit-value map-options options-dense />
          <q-input v-model="fFix.note" outlined dense label="Nota" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Fijar" :loading="guardando" :disable="!fFix.producer_id || !fFix.pounds || !fFix.price_per_lb" @click="guardarFix" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Nueva liquidación -->
    <q-dialog v-model="liqOpen">
      <q-card class="app-dialog" style="min-width: 460px">
        <q-card-section class="text-h6">Nueva liquidación</q-card-section>
        <q-card-section class="q-gutter-md">
          <q-select v-model="fLiq.producer_id" :options="prodOpts" label="Productor *" outlined dense emit-value map-options options-dense @update:model-value="onProducerLiq" />

          <div v-if="fLiq.producer_id">
            <div class="text-caption text-muted q-mb-xs">Fijaciones abiertas a liquidar *</div>
            <div v-if="fixDisponibles.length === 0" class="text-caption text-muted">Este productor no tiene fijaciones abiertas.</div>
            <q-option-group v-else v-model="fLiq.fixation_ids" type="checkbox" :options="fixOpts" />
          </div>

          <q-select v-model="fLiq.loan_id" :options="loanOpts" label="Aplicar a préstamo (opcional)" outlined dense emit-value map-options options-dense clearable />
          <q-input v-model.number="fLiq.exchange_rate" type="number" step="0.0001" label="Tasa de cambio (si cruza moneda)" outlined dense />

          <div>
            <div class="text-caption text-muted q-mb-xs">Deducciones (ej. retención IR, secado)</div>
            <div v-for="(d, i) in fLiq.deductions" :key="i" class="row q-col-gutter-sm q-mb-xs items-center">
              <q-input class="col" v-model="d.concept" dense outlined label="Concepto" />
              <q-input class="col-4" v-model.number="d.amount" type="number" dense outlined label="Monto" />
              <q-btn flat dense round size="sm" icon="close" aria-label="Eliminar deducción" @click="fLiq.deductions.splice(i, 1)" />
            </div>
            <q-btn flat dense no-caps size="sm" icon="add" label="Agregar deducción" @click="fLiq.deductions.push({ concept: '', amount: 0 })" />
          </div>

          <q-input v-model="fLiq.note" outlined dense label="Nota" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Liquidar" :loading="guardando" :disable="!fLiq.producer_id || fLiq.fixation_ids.length === 0" @click="guardarLiq" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { apiErrorMessage } from 'src/core/api';
import {
  CURRENCY_LABELS,
  FIXATION_STATUS_LABELS,
  createFixation,
  createLiquidation,
  listFixationsPage,
  listLoans,
  listLiquidationsPage,
  listProducers,
  type Currency,
  type FixationRow,
  type LiquidationRow,
} from 'src/modules/financiamiento/api';

const $q = useQuasar();
const tab = ref<'fijaciones' | 'liquidaciones'>('fijaciones');
const fixListado = useListadoServer<FixationRow>(listFixationsPage, { rowsPerPage: 15 });
const liqListado = useListadoServer<LiquidationRow>(listLiquidationsPage, { rowsPerPage: 15 });
const { rows: fixations, loading: loadingFix, pagination: fixPagination, onRequest: fixRequest, reload: reloadFix } = fixListado;
const { rows: liquidations, loading: loadingLiq, pagination: liqPagination, onRequest: liqRequest, reload: reloadLiq } = liqListado;

function reloadAll() {
  void reloadFix();
  void reloadLiq();
}

interface Opt<T = number> {
  label: string;
  value: T;
}
const prodOpts = ref<Opt[]>([]);
const loanOpts = ref<Opt[]>([]);
const monedaOpts = (Object.keys(CURRENCY_LABELS) as Currency[]).map((k) => ({ label: CURRENCY_LABELS[k], value: k }));
const guardando = ref(false);

const fixCols: QTableColumn<FixationRow>[] = [
  { name: 'fixation_date', label: 'Fecha', field: 'fixation_date', align: 'left', sortable: true },
  { name: 'producer_id', label: 'Productor', field: (r) => prodName(r.producer_id), align: 'left' },
  { name: 'pounds', label: 'Libras', field: 'pounds', align: 'right' },
  { name: 'price_per_lb', label: 'Precio/lb', field: 'price_per_lb', align: 'right' },
  { name: 'currency', label: 'Moneda', field: 'currency', align: 'left' },
  { name: 'status', label: 'Estado', field: 'status', align: 'left' },
];
const liqCols: QTableColumn<LiquidationRow>[] = [
  { name: 'liquidation_date', label: 'Fecha', field: 'liquidation_date', align: 'left', sortable: true },
  { name: 'producer_name', label: 'Productor', field: 'producer_name', align: 'left', sortable: true },
  { name: 'pounds_total', label: 'Libras', field: 'pounds_total', align: 'right' },
  { name: 'gross_value', label: 'Valor', field: 'gross_value', align: 'right' },
  { name: 'deductions_total', label: 'Deducc.', field: 'deductions_total', align: 'right' },
  { name: 'applied_to_loan', label: 'A préstamo', field: 'applied_to_loan', align: 'right' },
  { name: 'surplus_amount', label: 'Excedente', field: 'surplus_amount', align: 'right' },
  { name: 'loan_reference', label: 'Préstamo', field: 'loan_reference', align: 'left' },
];

const prodNameById = new Map<number, string>();
function prodName(id: number): string {
  return prodNameById.get(id) ?? `#${id}`;
}

// ---- fijación ----
const fixOpen = ref(false);
const fFix = ref<{ producer_id: number | null; pounds: number; price_per_lb: number; currency: Currency; note: string }>({ producer_id: null, pounds: 0, price_per_lb: 0, currency: 'USD', note: '' });
function abrirFix() {
  fFix.value = { producer_id: null, pounds: 0, price_per_lb: 0, currency: 'USD', note: '' };
  fixOpen.value = true;
}
async function guardarFix() {
  if (!fFix.value.producer_id || !fFix.value.pounds || !fFix.value.price_per_lb) return;
  guardando.value = true;
  try {
    await createFixation({
      producer_id: fFix.value.producer_id,
      pounds: fFix.value.pounds,
      price_per_lb: fFix.value.price_per_lb,
      currency: fFix.value.currency,
      note: fFix.value.note,
    });
    $q.notify({ type: 'positive', message: 'Fijación registrada.' });
    fixOpen.value = false;
    await reloadFix();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo fijar.') });
  } finally {
    guardando.value = false;
  }
}

// ---- liquidación ----
const liqOpen = ref(false);
const fLiq = ref({
  producer_id: null as number | null,
  fixation_ids: [] as number[],
  loan_id: null as number | null,
  exchange_rate: null as number | null,
  deductions: [] as { concept: string; amount: number }[],
  note: '',
});
const fixDisponibles = computed(() =>
  fixations.value.filter((f) => f.status === 'OPEN' && f.producer_id === fLiq.value.producer_id),
);
const fixOpts = computed(() =>
  fixDisponibles.value.map((f) => ({
    label: `${f.fixation_date} · ${f.pounds} lb @ ${f.price_per_lb} ${f.currency}`,
    value: f.id,
  })),
);
function abrirLiq() {
  fLiq.value = { producer_id: null, fixation_ids: [], loan_id: null, exchange_rate: null, deductions: [], note: '' };
  liqOpen.value = true;
}
function onProducerLiq() {
  fLiq.value.fixation_ids = [];
}
async function guardarLiq() {
  if (!fLiq.value.producer_id || fLiq.value.fixation_ids.length === 0) return;
  guardando.value = true;
  try {
    await createLiquidation({
      producer_id: fLiq.value.producer_id,
      fixation_ids: fLiq.value.fixation_ids,
      loan_id: fLiq.value.loan_id,
      exchange_rate: fLiq.value.exchange_rate,
      deductions: fLiq.value.deductions.filter((d) => d.concept && d.amount),
      note: fLiq.value.note,
    });
    $q.notify({ type: 'positive', message: 'Liquidación registrada.' });
    liqOpen.value = false;
    reloadAll();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo liquidar.') });
  } finally {
    guardando.value = false;
  }
}

onMounted(async () => {
  try {
    const [prods, loans] = await Promise.all([listProducers(), listLoans('ACTIVE')]);
    prodOpts.value = prods.map((p) => ({ label: `${p.acopio_code ? p.acopio_code + ' · ' : ''}${p.party_name}`, value: p.id }));
    for (const p of prods) prodNameById.set(p.id, p.party_name);
    loanOpts.value = loans.map((l) => ({ label: `${l.reference} · ${l.producer_name}`, value: l.id }));
  } catch {
    /* noop */
  }
});
</script>
