<template>
  <q-page class="app-page">
    <PageHeader
      title="Intereses de créditos"
      subtitle="Devengos de interés calculados período a período sobre los créditos activos. Los genera el proceso periódico de devengo; acá se auditan."
      :loading="cargando"
      @refresh="recargar"
    >
      <template #actions>
        <BackButton to="/cartera/creditos" />
      </template>
    </PageHeader>

    <div class="int-filtros">
      <q-select
        v-model="filtroCredito"
        :options="creditoOpts"
        label="Crédito"
        outlined
        dense
        clearable
        emit-value
        map-options
        options-dense
        class="int-filtro-credito"
        @update:model-value="recargar"
      />
      <q-select
        v-model="filtroCapitalizado"
        :options="OPCIONES_CAPITALIZACION"
        label="Capitalización"
        outlined
        dense
        emit-value
        map-options
        options-dense
        class="int-filtro-cap"
        @update:model-value="recargar"
      />
    </div>

    <div class="int-resumen">
      <div class="int-card">
        <div class="text-muted">Interés devengado (filtro actual)</div>
        <div class="int-cifra">{{ formatMoney(resumen.total) }}</div>
      </div>
      <div class="int-card">
        <div class="text-muted">Sin capitalizar</div>
        <div class="int-cifra">{{ formatMoney(resumen.sinCapitalizar) }}</div>
      </div>
      <div class="int-card">
        <div class="text-muted">Devengos</div>
        <div class="int-cifra">{{ rows.length }}</div>
      </div>
    </div>

    <q-table
      class="app-table"
      :rows="rows"
      :columns="columnas"
      row-key="id"
      flat
      :loading="cargando"
      :pagination="{ rowsPerPage: 25 }"
      no-data-label="No hay devengos de interés registrados."
      @row-click="(_evt, row) => abrirDetalle(row as InterestAccrual)"
    >
      <template #body-cell-credito="props">
        <q-td :props="props">{{ nombreCredito(props.row.credit) }}</q-td>
      </template>
      <template #body-cell-interes="props">
        <q-td :props="props" class="text-weight-bold">{{ formatMoney(props.row.accrued_interest) }}</q-td>
      </template>
      <template #body-cell-capitalizado="props">
        <q-td :props="props">
          <q-badge
            :color="props.row.is_capitalized ? 'positive' : 'grey-6'"
            :label="props.row.is_capitalized ? 'Capitalizado' : 'Pendiente'"
            outline
          />
        </q-td>
      </template>
    </q-table>

    <!-- Diálogo: detalle del devengo (fetch fresco, trae el cálculo completo) -->
    <q-dialog v-model="dlgDetalle">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Detalle del devengo</q-card-section>
        <q-card-section v-if="cargandoDetalle" class="text-center">
          <q-spinner size="2em" color="primary" />
        </q-card-section>
        <q-card-section v-else-if="detalle" class="q-pt-none">
          <div class="int-det-grid">
            <div class="text-muted">Crédito</div>
            <div>{{ nombreCredito(detalle.credit) }}</div>
            <div class="text-muted">Fecha de devengo</div>
            <div>{{ formatDate(detalle.accrual_date) }}</div>
            <div class="text-muted">Período</div>
            <div>
              {{ formatDate(detalle.period_start) }} – {{ formatDate(detalle.period_end) }}
              ({{ detalle.days_in_period }} días)
            </div>
            <div class="text-muted">Principal del período</div>
            <div>{{ formatMoney(detalle.principal_balance) }}</div>
            <div class="text-muted">Tasa aplicada</div>
            <div>{{ detalle.interest_rate_applied }} % anual</div>
            <div class="text-muted">Método de cálculo</div>
            <div>{{ METODO_LABELS[detalle.calculation_method] ?? detalle.calculation_method || '—' }}</div>
            <div class="text-muted">Interés devengado</div>
            <div class="text-weight-bold">{{ formatMoney(detalle.accrued_interest) }}</div>
            <div class="text-muted">Capitalización</div>
            <div>
              {{ detalle.is_capitalized ? `Capitalizado el ${formatDateTime(detalle.capitalized_at)}` : 'Pendiente' }}
            </div>
          </div>
          <q-expansion-item
            v-if="Object.keys(detalle.metadata_json ?? {}).length"
            dense
            icon="calculate"
            label="Detalle del cálculo"
            class="q-mt-sm"
          >
            <pre class="int-det-json">{{ JSON.stringify(detalle.metadata_json, null, 2) }}</pre>
          </q-expansion-item>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cerrar" v-close-popup />
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
import { apiErrorMessage } from 'src/core/api';
import { formatDate, formatDateTime, formatMoney } from 'src/core/format';
import {
  getInterestAccrual,
  listCredits,
  listInterestAccruals,
  type InterestAccrual,
} from 'src/modules/portfolio/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const METODO_LABELS: Record<string, string> = {
  SIMPLE: 'Interés simple',
  COMPOUND: 'Interés compuesto',
  FLAT: 'Tasa flat (mensual)',
};

const OPCIONES_CAPITALIZACION = [
  { label: 'Todos', value: 'todos' },
  { label: 'Capitalizados', value: 'si' },
  { label: 'Sin capitalizar', value: 'no' },
];

const cargando = ref(false);
const rows = ref<InterestAccrual[]>([]);
const filtroCredito = ref<number | null>(null);
const filtroCapitalizado = ref<'todos' | 'si' | 'no'>('todos');

const creditoOpts = ref<{ label: string; value: number }[]>([]);
const nombresCredito = ref(new Map<number, string>());

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

function nombreCredito(creditId: number): string {
  return nombresCredito.value.get(creditId) ?? `Crédito #${creditId}`;
}

const columnas: QTableColumn<InterestAccrual>[] = [
  { name: 'fecha', label: 'Devengo', field: (r) => formatDate(r.accrual_date), align: 'left' },
  { name: 'credito', label: 'Crédito', field: 'credit', align: 'left' },
  {
    name: 'periodo',
    label: 'Período',
    field: (r) => `${formatDate(r.period_start)} – ${formatDate(r.period_end)}`,
    align: 'left',
  },
  { name: 'dias', label: 'Días', field: 'days_in_period', align: 'right' },
  { name: 'principal', label: 'Principal', field: (r) => formatMoney(r.principal_balance), align: 'right' },
  { name: 'tasa', label: 'Tasa %', field: 'interest_rate_applied', align: 'right' },
  { name: 'interes', label: 'Interés', field: 'accrued_interest', align: 'right' },
  { name: 'capitalizado', label: 'Capitalización', field: 'is_capitalized', align: 'left' },
];

const resumen = computed(() => {
  let total = 0;
  let sinCapitalizar = 0;
  for (const r of rows.value) {
    const monto = Number(r.accrued_interest);
    total += monto;
    if (!r.is_capitalized) sinCapitalizar += monto;
  }
  return { total, sinCapitalizar };
});

async function recargar() {
  cargando.value = true;
  try {
    const filtros: { credit?: number; is_capitalized?: boolean } = {};
    if (filtroCredito.value) filtros.credit = filtroCredito.value;
    if (filtroCapitalizado.value !== 'todos') filtros.is_capitalized = filtroCapitalizado.value === 'si';
    rows.value = await listInterestAccruals(filtros);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar los devengos.') });
  } finally {
    cargando.value = false;
  }
}

// --- Detalle ---
const dlgDetalle = ref(false);
const cargandoDetalle = ref(false);
const detalle = ref<InterestAccrual | null>(null);

function abrirDetalle(row: InterestAccrual) {
  detalle.value = null;
  dlgDetalle.value = true;
  cargandoDetalle.value = true;
  getInterestAccrual(row.id)
    .then((d) => {
      detalle.value = d;
    })
    .catch((e: unknown) => {
      dlgDetalle.value = false;
      $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el devengo.') });
    })
    .finally(() => {
      cargandoDetalle.value = false;
    });
}

onMounted(async () => {
  await recargar();
  if (puede('portfolio.credit.read')) {
    try {
      const creditos = await listCredits();
      nombresCredito.value = new Map(
        creditos.map((c) => [c.id, c.contract_number || `Crédito #${c.id}`]),
      );
      creditoOpts.value = creditos.map((c) => ({
        label: c.contract_number || `Crédito #${c.id}`,
        value: c.id,
      }));
    } catch {
      /* nombres opcionales: la tabla pinta "Crédito #id" */
    }
  }
});
</script>

<style scoped>
.int-filtros {
  display: flex;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
  flex-wrap: wrap;
}

.int-filtro-credito {
  width: 320px;
  max-width: 100%;
}

.int-filtro-cap {
  width: 200px;
}

.int-resumen {
  display: flex;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
  flex-wrap: wrap;
}

.int-card {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
  padding: var(--app-space-3) var(--app-space-4);
  min-width: 160px;
}

.int-cifra {
  font-size: 1.3rem;
  font-weight: 700;
}

.int-det-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 16px;
}

.int-det-json {
  margin: 0;
  padding: var(--app-space-2);
  font-size: 0.75rem;
  overflow-x: auto;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}
</style>
