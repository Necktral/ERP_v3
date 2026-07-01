<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton to="/tablero" />
    </div>
    <PageHeader
      title="Alertas"
      subtitle="Lo que el sistema detecta (cartera vencida, stock bajo, documentos por vencer, préstamos en mora) y las acciones para actuar: reconocer (vista) o resolver."
      :loading="cargando"
      @refresh="cargar"
    >
      <template #actions>
        <q-btn unelevated no-caps color="primary" icon="radar" label="Escanear ahora" :loading="escaneando" @click="escanear" />
      </template>
    </PageHeader>

    <div class="row q-col-gutter-md q-mb-md">
      <q-select class="col-auto" v-model="fStatus" :options="statusOpts" label="Estado" outlined dense emit-value map-options options-dense style="width: 170px" @update:model-value="cargar" />
      <q-select class="col-auto" v-model="fSeverity" :options="severityOpts" label="Severidad" outlined dense emit-value map-options options-dense style="width: 170px" @update:model-value="cargar" />
    </div>

    <q-table
      :rows="alertas"
      :columns="cols"
      row-key="id"
      flat
      bordered
      :loading="cargando"
      :pagination="{ rowsPerPage: 25 }"
      no-data-label="Sin alertas con esos filtros. Todo en orden."
    >
      <template #body-cell-severity="props">
        <q-td :props="props">
          <q-chip dense square :color="sevColor(props.row.severity)" text-color="white" :label="SEVERITY_LABELS[props.row.severity]" />
        </q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-chip dense square :color="statusColor(props.row.status)" text-color="white" :label="STATUS_LABELS[props.row.status]" />
        </q-td>
      </template>
      <template #body-cell-title="props">
        <q-td :props="props">
          <div>{{ props.row.title }}</div>
          <div v-if="props.row.detail" class="text-caption text-muted">{{ props.row.detail }}</div>
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props" class="q-gutter-xs">
          <q-btn v-if="props.row.status === 'OPEN'" dense flat no-caps size="sm" color="primary" icon="visibility" label="Vista" @click="accion(ackAlert, props.row.id)" />
          <q-btn v-if="props.row.status !== 'RESOLVED'" dense unelevated no-caps size="sm" color="positive" icon="check" label="Resolver" @click="accion(resolveAlert, props.row.id)" />
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import { apiErrorMessage } from 'src/core/api';
import {
  ALERT_TYPE_LABELS,
  SEVERITY_LABELS,
  STATUS_LABELS,
  ackAlert,
  listAlerts,
  resolveAlert,
  scanAlerts,
  type AlertRow,
  type AlertSeverity,
  type AlertStatus,
} from 'src/modules/alertas/api';

const $q = useQuasar();
const alertas = ref<AlertRow[]>([]);
const cargando = ref(false);
const escaneando = ref(false);
const fStatus = ref<string>('OPEN');
const fSeverity = ref<string>('');

const statusOpts = [
  { label: 'Abiertas', value: 'OPEN' },
  { label: 'Vistas', value: 'ACKNOWLEDGED' },
  { label: 'Resueltas', value: 'RESOLVED' },
  { label: 'Todas', value: '' },
];
const severityOpts = [
  { label: 'Todas', value: '' },
  { label: 'Crítica', value: 'CRITICAL' },
  { label: 'Advertencia', value: 'WARNING' },
  { label: 'Informativa', value: 'INFO' },
];

function sevColor(s: AlertSeverity): string {
  return { CRITICAL: 'negative', WARNING: 'warning', INFO: 'info' }[s];
}
function statusColor(s: AlertStatus): string {
  return { OPEN: 'negative', ACKNOWLEDGED: 'warning', RESOLVED: 'positive' }[s];
}

const cols: QTableColumn<AlertRow>[] = [
  { name: 'severity', label: 'Severidad', field: 'severity', align: 'left', sortable: true },
  { name: 'alert_type', label: 'Tipo', field: (r) => ALERT_TYPE_LABELS[r.alert_type] ?? r.alert_type, align: 'left', sortable: true },
  { name: 'title', label: 'Alerta', field: 'title', align: 'left' },
  { name: 'last_seen_at', label: 'Visto', field: (r) => fecha(r.last_seen_at), align: 'left', sortable: true },
  { name: 'status', label: 'Estado', field: 'status', align: 'left', sortable: true },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

function fecha(s: string): string {
  return s ? new Date(s).toLocaleString('es-NI', { dateStyle: 'short', timeStyle: 'short' }) : '—';
}

async function cargar() {
  cargando.value = true;
  try {
    alertas.value = await listAlerts({ status: fStatus.value, severity: fSeverity.value });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar las alertas.') });
  } finally {
    cargando.value = false;
  }
}

async function accion(fn: (id: number) => Promise<unknown>, id: number) {
  try {
    await fn(id);
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo completar la acción.') });
  }
}

async function escanear() {
  escaneando.value = true;
  try {
    const res = await scanAlerts();
    const abiertas = Object.values(res.scanned).reduce((acc, v) => acc + (v?.opened ?? 0), 0);
    $q.notify({ type: 'positive', message: abiertas > 0 ? `Escaneo listo: ${abiertas} alerta(s) nueva(s).` : 'Escaneo listo: sin novedades.' });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo escanear.') });
  } finally {
    escaneando.value = false;
  }
}

onMounted(cargar);
</script>
