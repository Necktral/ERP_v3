<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton :to="`/nomina/periodos/${periodId}`" />
    </div>
    <PageHeader
      title="Régimen INSS del período"
      subtitle="Resuelve el vaivén CON/SIN INSS sin mover trabajadores a mano. La afiliación maestra (fechada) se define en el perfil del empleado; aquí ves y ajustas la elección de este período."
      :loading="cargando"
      @refresh="cargar"
    >
      <template #actions>
        <q-btn flat no-caps icon="rule" label="Resolver" :loading="resolviendo" @click="resolver">
          <q-tooltip>Materializa la elección de cada trabajador desde su afiliación vigente</q-tooltip>
        </q-btn>
        <q-btn unelevated no-caps color="primary" icon="splitscreen" label="Clasificar" :loading="clasificando" @click="clasificar">
          <q-tooltip>Mueve cada línea a la planilla CON o SIN INSS correcta y recalcula</q-tooltip>
        </q-btn>
      </template>
    </PageHeader>

    <q-banner v-if="!elecciones.length && !cargando" class="app-card q-mb-md" dense>
      <template #avatar><q-icon name="info" color="primary" /></template>
      Aún no hay elecciones para este período. Pulsa <b>Resolver</b> para traerlas desde la afiliación
      de cada empleado, y luego <b>Clasificar</b> para acomodar las planillas CON/SIN INSS.
    </q-banner>

    <q-table
      v-else
      :rows="elecciones"
      :columns="cols"
      row-key="id"
      flat
      bordered
      :loading="cargando"
      :pagination="{ rowsPerPage: 50, sortBy: 'nombre' }"
      no-data-label="Sin elecciones."
    >
      <template #body-cell-inss="props">
        <q-td :props="props">
          <q-chip dense square :color="props.row.elected_has_inss ? 'positive' : 'grey'" text-color="white" :label="props.row.elected_has_inss ? 'Cotiza INSS' : 'No cotiza'" />
        </q-td>
      </template>
      <template #body-cell-fuente="props">
        <q-td :props="props">
          <span class="text-muted">{{ INSS_SOURCE_LABELS[props.row.source] ?? props.row.source }}</span>
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props">
          <q-btn dense flat no-caps size="sm" :icon="props.row.elected_has_inss ? 'toggle_on' : 'toggle_off'" :label="props.row.elected_has_inss ? 'Quitar INSS' : 'Poner INSS'" @click="abrirOverride(props.row)" />
          <q-btn v-if="props.row.employee_id" dense flat no-caps size="sm" icon="history" label="Historial" @click="verHistorial(props.row)" />
        </q-td>
      </template>
    </q-table>

    <!-- Historial de afiliaciones INSS -->
    <q-dialog v-model="histOpen">
      <q-card class="app-dialog" style="min-width: 420px">
        <q-card-section class="text-h6">Historial INSS · {{ histNombre }}</q-card-section>
        <q-card-section>
          <DataReport :data="histData" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cerrar" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Override -->
    <q-dialog v-model="overrideOpen">
      <q-card class="app-dialog" style="min-width: 360px">
        <q-card-section class="text-h6">Ajustar INSS · {{ nombre(overrideRow) }}</q-card-section>
        <q-card-section class="q-gutter-md">
          <div>
            Cambiar a:
            <b>{{ overrideRow && !overrideRow.elected_has_inss ? 'Cotiza INSS' : 'No cotiza' }}</b>
          </div>
          <q-input v-model="overrideMotivo" type="textarea" autogrow outlined dense label="Motivo (auditado)" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Aplicar" :loading="guardando" @click="aplicarOverride" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import { useRoute } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import DataReport from 'src/components/DataReport.vue';
import { apiErrorMessage } from 'src/core/api';
import { listEmployees } from 'src/modules/hr/api';
import {
  INSS_SOURCE_LABELS,
  classifyInssEntries,
  listEmployeeInssEnrollments,
  listInssElections,
  resolveInssElections,
  setInssElection,
  type InssElection,
} from 'src/modules/nomina/api';

const $q = useQuasar();
const route = useRoute();
const periodId = Number(route.params.id);

const elecciones = ref<InssElection[]>([]);
const cargando = ref(false);
const resolviendo = ref(false);
const clasificando = ref(false);
const guardando = ref(false);
const nombresPorId = ref<Map<number, string>>(new Map());
const nombresPorCedula = ref<Map<string, string>>(new Map());

function nombre(row: InssElection | null): string {
  if (!row) return '';
  if (row.employee_id && nombresPorId.value.has(row.employee_id)) return nombresPorId.value.get(row.employee_id) as string;
  if (row.cedula && nombresPorCedula.value.has(row.cedula)) return nombresPorCedula.value.get(row.cedula) as string;
  return row.cedula || (row.employee_id ? `Empleado #${row.employee_id}` : '—');
}

const cols: QTableColumn<InssElection>[] = [
  { name: 'nombre', label: 'Trabajador', field: (r) => nombre(r), align: 'left', sortable: true },
  { name: 'cedula', label: 'Cédula', field: 'cedula', align: 'left' },
  { name: 'inss', label: 'INSS', field: 'elected_has_inss', align: 'left', sortable: true },
  { name: 'fuente', label: 'Fuente', field: 'source', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

async function cargar() {
  cargando.value = true;
  try {
    elecciones.value = await listInssElections(periodId);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar las elecciones de INSS.') });
  } finally {
    cargando.value = false;
  }
}

async function resolver() {
  resolviendo.value = true;
  try {
    const res = await resolveInssElections(periodId);
    const n = Object.keys(res.elections || {}).length;
    $q.notify({ type: 'positive', message: `Resuelto: ${n} trabajador(es) según su afiliación.` });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo resolver.') });
  } finally {
    resolviendo.value = false;
  }
}

async function clasificar() {
  clasificando.value = true;
  try {
    const res = await classifyInssEntries(periodId);
    $q.notify({ type: 'positive', message: `Clasificado: ${res.updated} actualizada(s), ${res.moved} movida(s) entre planillas.` });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo clasificar.') });
  } finally {
    clasificando.value = false;
  }
}

// ---- historial INSS ----
const histOpen = ref(false);
const histNombre = ref('');
const histData = ref<Record<string, unknown> | null>(null);
async function verHistorial(row: InssElection) {
  if (!row.employee_id) return;
  histNombre.value = nombre(row);
  histData.value = null;
  histOpen.value = true;
  try {
    const enrollments = await listEmployeeInssEnrollments(row.employee_id);
    histData.value = { enrollments };
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el historial.') });
  }
}

// ---- override ----
const overrideOpen = ref(false);
const overrideRow = ref<InssElection | null>(null);
const overrideMotivo = ref('');
function abrirOverride(row: InssElection) {
  overrideRow.value = row;
  overrideMotivo.value = '';
  overrideOpen.value = true;
}
async function aplicarOverride() {
  if (!overrideRow.value) return;
  guardando.value = true;
  try {
    await setInssElection(periodId, {
      employee_id: overrideRow.value.employee_id,
      cedula: overrideRow.value.cedula,
      elected_has_inss: !overrideRow.value.elected_has_inss,
      reason: overrideMotivo.value,
    });
    overrideOpen.value = false;
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo ajustar el INSS.') });
  } finally {
    guardando.value = false;
  }
}

onMounted(async () => {
  await cargar();
  try {
    const emps = await listEmployees();
    const byId = new Map<number, string>();
    const byCedula = new Map<string, string>();
    for (const e of emps) {
      const full = `${e.first_name} ${e.last_name}`.trim();
      byId.set(e.id, full);
      if (e.cedula) byCedula.set(e.cedula, full);
    }
    nombresPorId.value = byId;
    nombresPorCedula.value = byCedula;
  } catch {
    /* noop: se muestra cédula/id si no hay nombres */
  }
});
</script>
