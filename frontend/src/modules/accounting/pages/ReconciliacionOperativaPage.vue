<template>
  <q-page class="app-page">
    <PageHeader
      title="Reconciliación operativa"
      subtitle="Cuadre entre la operación (ventas, cobros, inventario) y la contabilidad: cuántos eventos operativos ya tienen su asiento y cuáles siguen pendientes."
      :loading="cargando"
      @refresh="cargar"
    >
      <template #actions>
        <BackButton to="/contabilidad" />
      </template>
    </PageHeader>

    <div class="reco-filtros">
      <q-input
        v-model="fechaDesde"
        dense
        outlined
        type="date"
        label="Desde"
        class="reco-filtros__fecha"
        clearable
      />
      <q-input
        v-model="fechaHasta"
        dense
        outlined
        type="date"
        label="Hasta"
        class="reco-filtros__fecha"
        clearable
      />
      <q-btn
        unelevated
        no-caps
        color="primary"
        icon="search"
        label="Consultar"
        :loading="cargando"
        :disable="rangoInvalido"
        @click="cargar"
      />
      <span v-if="rangoInvalido" class="text-caption text-negative">Desde debe ser ≤ Hasta.</span>
    </div>

    <template v-if="reporte">
      <!-- Estado global del cuadre -->
      <q-banner rounded class="reco-banner" :class="cuadrado ? 'reco-banner--ok' : 'reco-banner--pend'">
        <template #avatar>
          <q-icon :name="cuadrado ? 'verified' : 'rule'" :color="cuadrado ? 'positive' : 'warning'" />
        </template>
        <template v-if="cuadrado">
          La operación cuadra con la contabilidad: todos los eventos operativos del rango tienen su
          evento económico y no hay borradores en excepción.
        </template>
        <template v-else>
          Hay diferencias entre la operación y la contabilidad:
          {{ reporte.summary.pending_operational_events }} evento(s) sin vincular y
          {{ reporte.summary.drafts_exception }} borrador(es) en excepción.
        </template>
      </q-banner>

      <!-- Resumen -->
      <div class="row q-col-gutter-md q-mb-md">
        <div v-for="kpi in kpis" :key="kpi.label" class="col-6 col-sm-4 col-md-2">
          <q-card flat bordered class="app-card reco-kpi">
            <div class="reco-kpi__label">{{ kpi.label }}</div>
            <div class="reco-kpi__value" :class="kpi.clase">{{ kpi.value }}</div>
          </q-card>
        </div>
      </div>

      <!-- Detalle por tipo de evento -->
      <div class="reco-titulo">Cuadre por tipo de evento</div>
      <q-table
        class="app-table"
        :rows="reporte.by_event_type"
        :columns="columnas"
        :row-key="claveFila"
        flat
        dense
        :loading="cargando"
        :pagination="{ rowsPerPage: 25 }"
        no-data-label="Sin eventos operativos en el rango elegido."
      >
        <template #body-cell-modulo="props">
          <q-td :props="props">{{ MODULO_LABELS[props.row.source_module] ?? props.row.source_module }}</q-td>
        </template>
        <template #body-cell-estado="props">
          <q-td :props="props">
            <q-chip
              dense
              square
              :color="estadoFila(props.row).color"
              text-color="white"
              :icon="estadoFila(props.row).icon"
              :label="estadoFila(props.row).label"
            />
          </q-td>
        </template>
        <template #body-cell-monto_operativo="props">
          <q-td :props="props">{{ formatMoney(props.row.operational_amount) }}</q-td>
        </template>
        <template #body-cell-monto_posteado="props">
          <q-td :props="props">{{ formatMoney(props.row.posted_amount) }}</q-td>
        </template>
        <template #body-cell-diferencia="props">
          <q-td :props="props" :class="Number(diferencia(props.row)) === 0 ? 'text-positive' : 'text-negative'">
            {{ formatMoney(diferencia(props.row)) }}
          </q-td>
        </template>
      </q-table>

      <!-- Eventos operativos sin vincular -->
      <template v-if="reporte.pending_operational_events.length">
        <div class="reco-titulo">
          Eventos operativos sin evento económico
          <span class="text-caption text-muted">(muestra hasta 200)</span>
        </div>
        <q-table
          class="app-table"
          :rows="reporte.pending_operational_events"
          :columns="columnasPendientes"
          row-key="outbox_event_id"
          flat
          dense
          :pagination="{ rowsPerPage: 10 }"
        >
          <template #body-cell-modulo="props">
            <q-td :props="props">{{ MODULO_LABELS[props.row.source_module] ?? props.row.source_module }}</q-td>
          </template>
          <template #body-cell-ocurrido="props">
            <q-td :props="props">{{ formatDateTime(props.row.occurred_at) }}</q-td>
          </template>
        </q-table>
      </template>
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
import {
  getOperationalReconciliation,
  type OperationalReconciliation,
  type OperationalReconciliationRow,
  type PendingOperationalEvent,
} from 'src/modules/accounting/api';

const $q = useQuasar();

const MODULO_LABELS: Record<string, string> = {
  BILLING: 'Facturación',
  PAYMENTS: 'Caja y pagos',
  INVENTORY: 'Inventario',
  ACCOUNTING: 'Contabilidad',
};

const fechaDesde = ref('');
const fechaHasta = ref('');
const cargando = ref(false);
const reporte = ref<OperationalReconciliation | null>(null);

const rangoInvalido = computed(
  () => Boolean(fechaDesde.value && fechaHasta.value) && fechaDesde.value > fechaHasta.value,
);

/** Cuadra cuando no hay eventos sin vincular ni borradores en excepción. */
const cuadrado = computed(() => {
  const s = reporte.value?.summary;
  return Boolean(s && s.pending_operational_events === 0 && s.drafts_exception === 0);
});

const kpis = computed(() => {
  const s = reporte.value?.summary;
  if (!s) return [];
  return [
    { label: 'Eventos operativos', value: String(s.operational_events), clase: '' },
    { label: 'Vinculados', value: String(s.economic_events_linked), clase: '' },
    {
      label: 'Sin vincular',
      value: String(s.pending_operational_events),
      clase: s.pending_operational_events > 0 ? 'text-negative' : 'text-positive',
    },
    { label: 'Borradores', value: String(s.drafts_total), clase: '' },
    {
      label: 'En excepción',
      value: String(s.drafts_exception),
      clase: s.drafts_exception > 0 ? 'text-negative' : 'text-positive',
    },
    { label: 'Posteados', value: String(s.drafts_posted), clase: '' },
  ];
});

const columnas: QTableColumn<OperationalReconciliationRow>[] = [
  { name: 'modulo', label: 'Módulo', field: 'source_module', align: 'left' },
  { name: 'evento', label: 'Evento', field: 'event_type', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'event_type', align: 'left' },
  { name: 'operativos', label: 'Operativos', field: 'operational_count', align: 'right' },
  { name: 'vinculados', label: 'Vinculados', field: 'linked_count', align: 'right' },
  { name: 'posteados', label: 'Posteados', field: 'posted_count', align: 'right' },
  { name: 'excepciones', label: 'Excepciones', field: 'draft_exception_count', align: 'right' },
  { name: 'monto_operativo', label: 'Monto operativo', field: 'operational_amount', align: 'right' },
  { name: 'monto_posteado', label: 'Monto posteado', field: 'posted_amount', align: 'right' },
  { name: 'diferencia', label: 'Diferencia', field: 'operational_amount', align: 'right' },
];

const columnasPendientes: QTableColumn<PendingOperationalEvent>[] = [
  { name: 'modulo', label: 'Módulo', field: 'source_module', align: 'left' },
  { name: 'evento', label: 'Evento', field: 'event_type', align: 'left' },
  { name: 'ocurrido', label: 'Ocurrido', field: 'occurred_at', align: 'left' },
  { name: 'outbox', label: 'Evento outbox', field: 'outbox_event_id', align: 'left' },
];

function claveFila(r: OperationalReconciliationRow): string {
  return `${r.source_module}.${r.event_type}`;
}

/** Monto operativo − monto posteado: 0 cuando el tipo de evento cuadra. */
function diferencia(r: OperationalReconciliationRow): string {
  return (Number(r.operational_amount) - Number(r.posted_amount)).toFixed(2);
}

function estadoFila(r: OperationalReconciliationRow): { label: string; color: string; icon: string } {
  if (r.draft_exception_count > 0) return { label: 'Excepción', color: 'negative', icon: 'error' };
  if (r.linked_count < r.operational_count) return { label: 'Sin vincular', color: 'warning', icon: 'link_off' };
  if (r.posted_count < r.operational_count) return { label: 'Por postear', color: 'grey-7', icon: 'pending' };
  return { label: 'Cuadra', color: 'positive', icon: 'check_circle' };
}

async function cargar() {
  if (rangoInvalido.value) return;
  cargando.value = true;
  try {
    reporte.value = await getOperationalReconciliation({
      ...(fechaDesde.value ? { date_from: fechaDesde.value } : {}),
      ...(fechaHasta.value ? { date_to: fechaHasta.value } : {}),
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar la reconciliación.') });
  } finally {
    cargando.value = false;
  }
}

onMounted(cargar);
</script>

<style scoped>
.reco-filtros {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-4);
}

.reco-filtros__fecha {
  width: 180px;
}

.reco-banner {
  margin-bottom: var(--app-space-4);
  border: 1px solid var(--app-border);
  background: var(--app-surface);
}

.reco-banner--ok {
  border-color: var(--app-positive, #2e7d32);
}

.reco-banner--pend {
  border-color: var(--app-warning, #f2c037);
}

.reco-kpi {
  padding: var(--app-space-3);
}

.reco-kpi__label {
  font-size: 0.75rem;
  color: var(--app-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.reco-kpi__value {
  font-size: 1.35rem;
  font-weight: 700;
  font-family: 'Manrope', sans-serif;
}

.reco-titulo {
  font-family: 'Manrope', 'IBM Plex Sans', sans-serif;
  font-weight: 800;
  color: var(--app-text);
  margin: var(--app-space-4) 0 var(--app-space-3);
}
</style>
