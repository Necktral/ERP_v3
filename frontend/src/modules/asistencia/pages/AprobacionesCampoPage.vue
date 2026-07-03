<template>
  <q-page class="app-page">
    <PageHeader
      title="Aprobaciones de campo"
      subtitle="Bandeja del aprobador (checker): jornadas consolidadas en revisión. Por SoD no podés aprobar lo que vos mismo capturaste; lo aprobado se aplica a la planilla sin duplicar."
      :loading="loading"
      @refresh="recargarTodo"
    >
      <template #actions>
        <q-btn flat no-caps icon="agriculture" label="Jornadas" to="/asistencia/campo" />
        <q-btn
          v-if="puede('nomina.field.approve')"
          outline
          no-caps
          color="primary"
          icon="key"
          label="Aprobar con código"
          @click="abrirAprobar(null)"
        />
      </template>
    </PageHeader>

    <q-banner v-if="!bitacoraDisponible" dense rounded class="bg-warning text-dark q-mb-md">
      No se pudieron detectar las solicitudes pendientes (falta permiso de bitácora): pedile el
      código de solicitud al que consolidó y usá “Aprobar con código”.
    </q-banner>

    <!-- Solicitudes SoD pendientes detectadas en la bitácora -->
    <q-list
      v-if="solicitudesPendientes.length"
      bordered
      separator
      class="rounded-borders q-mb-md"
    >
      <q-item-label header>Solicitudes de aprobación pendientes</q-item-label>
      <q-item v-for="s in solicitudesPendientes" :key="s.request_id">
        <q-item-section>
          <q-item-label class="acampo-uuid">{{ s.request_id }}</q-item-label>
          <q-item-label caption>Solicitada el {{ formatDateTime(s.requested_at) }}</q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-btn
            v-if="puede('nomina.field.approve')"
            dense
            unelevated
            no-caps
            color="positive"
            icon="check_circle"
            label="Aprobar"
            @click="abrirAprobar(s.request_id)"
          />
        </q-item-section>
      </q-item>
    </q-list>

    <!-- Jornadas en revisión (contexto de lo que espera aprobación) -->
    <div class="text-subtitle1 q-mb-sm">Jornadas en revisión</div>
    <q-table
      v-model:pagination="pagination"
      class="app-table q-mb-lg"
      :rows="rows"
      :columns="columns"
      row-key="id"
      flat
      :loading="loading"
      :rows-per-page-options="[10, 25, 50, 100]"
      no-data-label="No hay jornadas en revisión."
      @request="onRequest"
    >
      <template #body-cell-work_date="props">
        <q-td :props="props">{{ formatDate(props.row.work_date) }}</q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props">
          <EstadoChip :estado="props.row.status" :map="MAPA_ESTADO_JORNADA" />
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props">
          <q-btn
            dense
            flat
            no-caps
            color="primary"
            icon="visibility"
            label="Ver"
            :to="`/asistencia/campo/${props.row.id}`"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Aplicar asistencia aprobada a la planilla -->
    <template v-if="puede('nomina.field.apply')">
      <div class="text-subtitle1 q-mb-sm">Aplicar asistencia aprobada a la planilla</div>
      <q-card flat bordered class="acampo-aplicar">
        <q-card-section class="app-form">
          <q-select
            v-model="periodoAplicar"
            outlined
            dense
            emit-value
            map-options
            label="Período de planilla"
            :options="opcionesPeriodo"
            :loading="cargandoPeriodos"
            @update:model-value="cargarPlanillas"
          />
          <q-select
            v-model="planillaAplicar"
            outlined
            dense
            emit-value
            map-options
            label="Planilla"
            :options="opcionesPlanilla"
            :loading="cargandoPlanillas"
            :disable="periodoAplicar == null"
          />
          <q-btn
            unelevated
            no-caps
            color="primary"
            icon="playlist_add_check_circle"
            label="Aplicar a la planilla"
            :loading="aplicando"
            :disable="planillaAplicar == null"
            @click="aplicarAPlanilla"
          />
          <div v-if="resultadoAplicar" class="text-caption text-grey-8">
            {{ resultadoAplicar }}
          </div>
        </q-card-section>
      </q-card>
    </template>

    <!-- Diálogo: aprobar por código de solicitud (SoD) -->
    <q-dialog v-model="dlgAprobar">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Aprobar jornada de campo</q-card-section>
        <q-card-section class="app-form">
          <q-input
            v-model="codigoAprobar"
            outlined
            dense
            label="Código de solicitud *"
            hint="Es el código (UUID) que vio el que consolidó al pedir la aprobación."
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="positive"
            label="Aprobar"
            :loading="aprobando"
            :disable="!codigoValido"
            @click="aprobar"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import EstadoChip from 'src/components/EstadoChip.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { formatDate, formatDateTime } from 'src/core/format';
import { listBitacora } from 'src/modules/audit/api';
import {
  approveFieldWorkDay,
  listFieldWorkDays,
  type FieldWorkDay,
} from 'src/modules/asistencia/api';
import { etiquetaPeriodo, MAPA_ESTADO_JORNADA } from 'src/modules/asistencia/ui';
import { applyFieldAttendance, listPeriods, listSheets } from 'src/modules/nomina/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

// --- jornadas en revisión (server-side) ---
const { rows, loading, pagination, onRequest, reload } = useListadoServer<FieldWorkDay>(
  (page) => listFieldWorkDays({ status: 'IN_REVIEW' }, page),
  { errorMessage: 'No se pudieron cargar las jornadas en revisión.' },
);

const columns: QTableColumn<FieldWorkDay>[] = [
  { name: 'id', label: 'Jornada', field: 'id', align: 'left' },
  { name: 'work_date', label: 'Fecha', field: 'work_date', align: 'left' },
  { name: 'status', label: 'Estado', field: 'status', align: 'left' },
  { name: 'notes', label: 'Notas', field: 'notes', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

// --- solicitudes pendientes vía bitácora -------------------------------------
// El backend NO expone GET de solicitudes SoD: se detectan por los eventos
// IAM_APPROVAL_* de la bitácora (subject_id = UUID de la solicitud,
// metadata.action_type = FIELD_ATTENDANCE_APPROVE). Sin audit.read la página
// degrada a ingreso manual del código.
interface SolicitudPendiente {
  request_id: string;
  requested_at: string;
}

const solicitudesPendientes = ref<SolicitudPendiente[]>([]);
const bitacoraDisponible = ref(true);

async function cargarSolicitudes() {
  const pedidas: SolicitudPendiente[] = [];
  const decididas = new Set<string>();
  try {
    let cursor: string | undefined;
    // Los eventos vienen del más reciente al más viejo; tope de páginas fijo.
    for (let pagina = 0; pagina < 5; pagina++) {
      const res = await listBitacora({ module: 'IAM', subject_type: 'APPROVAL_REQUEST' }, cursor);
      for (const ev of res.results) {
        const meta = ev.metadata as Record<string, unknown> | null | undefined;
        if (meta?.action_type !== 'FIELD_ATTENDANCE_APPROVE') continue;
        const uuid = String(ev.subject_id ?? '');
        if (!uuid) continue;
        if (ev.event_type === 'IAM_APPROVAL_REQUESTED') {
          pedidas.push({ request_id: uuid, requested_at: ev.timestamp_server });
        } else {
          decididas.add(uuid); // aprobada / rechazada / cancelada / ejecutada
        }
      }
      const next = res.next;
      if (!next) break;
      cursor = new URL(next, window.location.origin).searchParams.get('cursor') ?? undefined;
      if (!cursor) break;
    }
    bitacoraDisponible.value = true;
  } catch {
    bitacoraDisponible.value = false;
  }
  const vistas = new Set<string>();
  solicitudesPendientes.value = pedidas.filter((s) => {
    if (decididas.has(s.request_id) || vistas.has(s.request_id)) return false;
    vistas.add(s.request_id);
    return true;
  });
}

void cargarSolicitudes();

async function recargarTodo() {
  await Promise.all([reload(), cargarSolicitudes()]);
}

// --- aprobar (checker, SoD) ---
const dlgAprobar = ref(false);
const aprobando = ref(false);
const codigoAprobar = ref('');

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const codigoValido = computed(() => UUID_RE.test(codigoAprobar.value.trim()));

function abrirAprobar(requestId: string | null) {
  codigoAprobar.value = requestId ?? '';
  dlgAprobar.value = true;
}

async function aprobar() {
  if (!codigoValido.value) return;
  aprobando.value = true;
  try {
    const res = await approveFieldWorkDay(codigoAprobar.value.trim());
    dlgAprobar.value = false;
    $q.notify({
      type: 'positive',
      timeout: 6000,
      message: `Jornada #${res.id} del ${formatDate(res.work_date)} aprobada (${res.consolidations.length} trabajadores).`,
    });
    await recargarTodo();
  } catch (e) {
    // 403 = SoD (mismo usuario que solicitó); 409 = ya decidida; 404 = código incorrecto.
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo aprobar la jornada.') });
  } finally {
    aprobando.value = false;
  }
}

// --- aplicar a planilla ---
const periodoAplicar = ref<number | null>(null);
const planillaAplicar = ref<number | null>(null);
const opcionesPeriodo = ref<{ label: string; value: number }[]>([]);
const opcionesPlanilla = ref<{ label: string; value: number }[]>([]);
const cargandoPeriodos = ref(false);
const cargandoPlanillas = ref(false);
const aplicando = ref(false);
const resultadoAplicar = ref('');

async function cargarPeriodos() {
  if (!puede('nomina.field.apply')) return;
  cargandoPeriodos.value = true;
  try {
    const periodos = await listPeriods();
    opcionesPeriodo.value = periodos.map((p) => ({ label: etiquetaPeriodo(p), value: p.id }));
  } catch {
    opcionesPeriodo.value = [];
  } finally {
    cargandoPeriodos.value = false;
  }
}

void cargarPeriodos();

async function cargarPlanillas() {
  planillaAplicar.value = null;
  opcionesPlanilla.value = [];
  resultadoAplicar.value = '';
  if (periodoAplicar.value == null) return;
  cargandoPlanillas.value = true;
  try {
    const sheets = await listSheets(periodoAplicar.value);
    opcionesPlanilla.value = sheets.map((s) => ({
      label: `#${s.id} — ${s.sheet_name} (${s.entry_count} líneas)`,
      value: s.id,
    }));
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar las planillas.') });
  } finally {
    cargandoPlanillas.value = false;
  }
}

async function aplicarAPlanilla() {
  if (planillaAplicar.value == null) return;
  aplicando.value = true;
  try {
    const res = (await applyFieldAttendance(planillaAplicar.value)) as {
      applied?: number[];
      skipped?: number[];
    };
    const aplicadas = res.applied?.length ?? 0;
    const omitidas = res.skipped?.length ?? 0;
    resultadoAplicar.value = `Se aplicó la asistencia a ${aplicadas} líneas; ${omitidas} sin asistencia aprobada quedaron igual.`;
    $q.notify({ type: 'positive', message: resultadoAplicar.value });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo aplicar la asistencia.') });
  } finally {
    aplicando.value = false;
  }
}
</script>

<style scoped>
.acampo-uuid {
  font-family: monospace;
  word-break: break-all;
}

.acampo-aplicar {
  max-width: 560px;
}
</style>
