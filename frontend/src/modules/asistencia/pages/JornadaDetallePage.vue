<template>
  <q-page class="app-page">
    <PageHeader
      :title="`Jornada de campo #${workDayId}`"
      :subtitle="jornada ? `Fecha de trabajo: ${formatDate(jornada.work_date)}` : ''"
      :loading="loading"
      @refresh="cargar"
    >
      <template #actions>
        <EstadoChip v-if="jornada" :estado="jornada.status" :map="MAPA_ESTADO_JORNADA" />
        <q-btn flat no-caps icon="arrow_back" label="Jornadas" to="/asistencia/campo" />
      </template>
    </PageHeader>

    <q-banner v-if="jornada && !editable" dense rounded class="bg-grey-3 text-dark q-mb-md">
      <template #avatar><q-icon name="lock" /></template>
      La jornada está {{ etiquetaEstado }} y ya no admite cambios de captura.
    </q-banner>

    <q-tabs
      v-model="tab"
      dense
      no-caps
      align="left"
      class="text-grey-7 q-mb-md"
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab name="lista" icon="checklist" label="Pase de lista" />
      <q-tab name="cuadrillas" icon="groups_2" label="Cuadrillas" />
      <q-tab name="eventos" icon="event_note" label="Eventos" />
      <q-tab name="traslados" icon="swap_horiz" label="Traslados" />
      <q-tab name="consolidacion" icon="fact_check" label="Consolidación" />
    </q-tabs>

    <q-tab-panels v-model="tab" animated class="bg-transparent">
      <!-- ================= Pase de lista ================= -->
      <q-tab-panel name="lista" class="q-pa-none">
        <q-banner v-if="!puedeCapturar" dense rounded class="bg-grey-3 text-dark q-mb-md">
          <template #avatar><q-icon name="visibility" /></template>
          Modo consulta: tu rol no captura el pase de lista.
        </q-banner>
        <div class="row items-center q-col-gutter-sm q-mb-sm">
          <div class="col">
            <q-input
              v-model="busquedaLista"
              outlined
              dense
              clearable
              debounce="150"
              placeholder="Buscar trabajador…"
            >
              <template #prepend><q-icon name="search" /></template>
            </q-input>
          </div>
          <div class="col-auto text-caption text-grey-7">
            {{ marcadosLista }} / {{ lineasLista.length }} confirmados
          </div>
        </div>

        <div v-if="cargandoEmpleados" class="q-pa-md text-grey-7">
          <q-spinner size="24px" /> Cargando personal…
        </div>
        <div v-else class="jcampo-lista">
          <div v-for="linea in lineasFiltradas" :key="linea.employee_id" class="jcampo-fila">
            <div class="jcampo-fila__nombre">
              <div class="text-weight-bold">{{ linea.nombre }}</div>
              <q-input
                v-if="linea.status === 'ABSENT'"
                v-model="linea.absence_reason"
                dense
                outlined
                class="q-mt-xs"
                label="Motivo de ausencia"
              />
            </div>
            <q-btn-toggle
              v-model="linea.status"
              dense
              no-caps
              unelevated
              toggle-color="primary"
              :disable="!puedeCapturar || !editable"
              :options="[
                { label: 'Presente', value: 'PRESENT' },
                { label: 'Ausente', value: 'ABSENT' },
                { label: 'Sin confirmar', value: 'UNKNOWN' },
              ]"
            />
          </div>
          <div v-if="lineasFiltradas.length === 0" class="q-pa-md text-grey-7">
            {{ busquedaLista ? 'Nadie coincide con la búsqueda.' : 'No hay personal activo.' }}
          </div>
        </div>

        <div class="q-mt-md row q-col-gutter-sm items-center">
          <div class="col-12 col-sm-6">
            <q-input v-model="notasLista" outlined dense label="Notas del pase de lista" />
          </div>
          <div class="col-auto">
            <q-btn
              v-if="puedeCapturar"
              unelevated
              no-caps
              color="primary"
              icon="send"
              label="Enviar pase de lista"
              :loading="enviandoLista"
              :disable="!editable || marcadosLista === 0"
              @click="enviarPaseDeLista"
            >
              <q-tooltip v-if="marcadosLista === 0">
                Confirmá al menos un trabajador (presente o ausente).
              </q-tooltip>
            </q-btn>
          </div>
        </div>
      </q-tab-panel>

      <!-- ================= Cuadrillas ================= -->
      <q-tab-panel name="cuadrillas" class="q-pa-none">
        <div class="row q-col-gutter-md">
          <div v-if="puedeCapturar" class="col-12 col-md-5">
            <q-card flat bordered>
              <q-card-section class="text-subtitle1">Nueva cuadrilla</q-card-section>
              <q-card-section class="app-form">
                <q-input v-model="nombreCuadrilla" outlined dense label="Nombre de la cuadrilla *" />
                <q-select
                  v-model="capatazCuadrilla"
                  outlined
                  dense
                  use-input
                  input-debounce="0"
                  emit-value
                  map-options
                  label="Capataz responsable *"
                  :options="opcionesEmpleadosFiltradas"
                  :loading="cargandoEmpleados"
                  @filter="filtrarEmpleados"
                />
                <q-btn
                  unelevated
                  no-caps
                  color="primary"
                  icon="group_add"
                  label="Crear cuadrilla"
                  :loading="creandoCuadrilla"
                  :disable="!editable || !nombreCuadrilla.trim() || capatazCuadrilla == null"
                  @click="crearCuadrilla"
                />
              </q-card-section>
            </q-card>
          </div>
          <div class="col-12 col-md-7">
            <q-card flat bordered>
              <q-card-section class="text-subtitle1">Cuadrillas de la jornada</q-card-section>
              <q-card-section v-if="cuadrillas.length === 0" class="text-grey-7">
                Aún no hay cuadrillas registradas en esta jornada.
              </q-card-section>
              <q-list v-else separator>
                <q-item v-for="c in cuadrillas" :key="c.id">
                  <q-item-section>
                    <q-item-label>#{{ c.id }} — {{ c.name }}</q-item-label>
                    <q-item-label caption>Capataz: {{ nombreEmpleado(c.supervisor_employee_id) }}</q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <q-btn
                      v-if="puedeCapturar"
                      dense
                      flat
                      no-caps
                      color="primary"
                      icon="assignment"
                      label="Reporte"
                      :to="`/asistencia/campo/cuadrillas/${c.id}/reporte?jornada=${workDayId}`"
                    />
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card>
          </div>
        </div>
      </q-tab-panel>

      <!-- ================= Eventos ================= -->
      <q-tab-panel name="eventos" class="q-pa-none">
        <q-card flat bordered class="jcampo-form-card">
          <q-card-section class="text-subtitle1">Registrar novedad de un trabajador</q-card-section>
          <q-card-section class="app-form">
            <q-select
              v-model="eventoEmpleado"
              outlined
              dense
              use-input
              input-debounce="0"
              emit-value
              map-options
              label="Trabajador *"
              :options="opcionesEmpleadosFiltradas"
              :loading="cargandoEmpleados"
              @filter="filtrarEmpleados"
            />
            <q-select
              v-model="eventoTipo"
              outlined
              dense
              emit-value
              map-options
              label="Tipo de novedad *"
              :options="opcionesEvento"
            />
            <q-input
              v-model="eventoDetalle"
              outlined
              dense
              autogrow
              :label="detalleObligatorio ? 'Detalle * (obligatorio para este tipo)' : 'Detalle'"
            />
            <q-btn
              v-if="puedeCapturar"
              unelevated
              no-caps
              color="primary"
              icon="add_task"
              label="Registrar novedad"
              :loading="registrandoEvento"
              :disable="!puedeRegistrarEvento"
              @click="registrarEvento"
            />
          </q-card-section>
        </q-card>

        <q-list v-if="eventosSesion.length" bordered separator class="q-mt-md rounded-borders">
          <q-item-label header>Novedades registradas en esta sesión</q-item-label>
          <q-item v-for="ev in eventosSesion" :key="ev.id">
            <q-item-section>
              <q-item-label>{{ ev.empleado }} — {{ FIELD_EVENT_LABELS[ev.event_type] }}</q-item-label>
              <q-item-label v-if="ev.details" caption>{{ ev.details }}</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-tab-panel>

      <!-- ================= Traslados ================= -->
      <q-tab-panel name="traslados" class="q-pa-none">
        <q-banner v-if="cuadrillas.length < 2" dense rounded class="bg-grey-3 text-dark q-mb-md">
          <template #avatar><q-icon name="info" /></template>
          Un traslado necesita al menos dos cuadrillas registradas (pestaña Cuadrillas).
        </q-banner>
        <q-card flat bordered class="jcampo-form-card">
          <q-card-section class="text-subtitle1">Trasladar trabajador entre cuadrillas</q-card-section>
          <q-card-section class="app-form">
            <q-select
              v-model="trasladoEmpleado"
              outlined
              dense
              use-input
              input-debounce="0"
              emit-value
              map-options
              label="Trabajador *"
              :options="opcionesEmpleadosFiltradas"
              :loading="cargandoEmpleados"
              @filter="filtrarEmpleados"
            />
            <q-select
              v-model="trasladoDesde"
              outlined
              dense
              emit-value
              map-options
              label="De la cuadrilla *"
              :options="opcionesCuadrilla"
            />
            <q-select
              v-model="trasladoHacia"
              outlined
              dense
              emit-value
              map-options
              label="A la cuadrilla *"
              :options="opcionesCuadrilla"
            />
            <q-input v-model="trasladoMotivo" outlined dense label="Motivo del traslado *" />
            <q-btn
              v-if="puedeCapturar"
              unelevated
              no-caps
              color="primary"
              icon="swap_horiz"
              label="Registrar traslado"
              :loading="registrandoTraslado"
              :disable="!puedeRegistrarTraslado"
              @click="registrarTraslado"
            />
          </q-card-section>
        </q-card>
      </q-tab-panel>

      <!-- ================= Consolidación ================= -->
      <q-tab-panel name="consolidacion" class="q-pa-none">
        <div class="row q-col-gutter-sm q-mb-md">
          <div class="col-auto">
            <q-btn
              v-if="puedeConsolidar"
              unelevated
              no-caps
              color="primary"
              icon="playlist_add_check"
              :label="consolidaciones.length ? 'Re-consolidar el día' : 'Consolidar el día'"
              :loading="consolidando"
              :disable="!jornada || jornada.status === 'APPROVED' || jornada.status === 'LOCKED'"
              @click="consolidarDia"
            />
          </div>
          <div class="col-auto">
            <q-btn
              v-if="puedeSolicitarAprobacion"
              outline
              no-caps
              color="primary"
              icon="how_to_vote"
              label="Solicitar aprobación (SoD)"
              :loading="solicitandoAprobacion"
              :disable="consolidaciones.length === 0"
              @click="solicitarAprobacion"
            >
              <q-tooltip v-if="consolidaciones.length === 0">
                Primero consolidá el día.
              </q-tooltip>
            </q-btn>
          </div>
        </div>

        <q-banner v-if="codigoAprobacion" dense rounded class="bg-blue-1 text-dark q-mb-md">
          <template #avatar><q-icon name="key" color="primary" /></template>
          Código de solicitud para el aprobador: <b class="jcampo-uuid">{{ codigoAprobacion }}</b>
          <template #action>
            <q-btn dense flat no-caps icon="content_copy" label="Copiar" @click="copiarCodigo" />
          </template>
        </q-banner>

        <q-table
          class="app-table"
          :rows="consolidaciones"
          :columns="columnasConsolidacion"
          row-key="id"
          flat
          :loading="cargandoConsolidaciones"
          :rows-per-page-options="[10, 25, 50, 100]"
          no-data-label="Sin consolidaciones: consolidá el día para generarlas."
        >
          <template #body-cell-empleado="props">
            <q-td :props="props">{{ nombreEmpleado(props.row.employee_id) }}</q-td>
          </template>
          <template #body-cell-status="props">
            <q-td :props="props">
              <EstadoChip :estado="props.row.status" :map="MAPA_ESTADO_CONSOLIDACION" />
            </q-td>
          </template>
          <template #body-cell-evento="props">
            <q-td :props="props">
              {{ etiquetaEvento(props.row.primary_event_type) }}
            </q-td>
          </template>
          <template #body-cell-conflictos="props">
            <q-td :props="props">
              {{ props.row.conflict_codes.length ? props.row.conflict_codes.join(', ') : '—' }}
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>
    </q-tab-panels>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { copyToClipboard, useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import EstadoChip from 'src/components/EstadoChip.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatDate } from 'src/core/format';
import {
  createFieldCrew,
  FIELD_EVENT_LABELS,
  FIELD_EVENTS_CON_DETALLE,
  getFieldWorkDay,
  getFieldRollcall,
  listFieldApprovalRequests,
  listFieldCrews,
  listFieldConsolidations,
  recordFieldEvent,
  requestFieldApproval,
  submitRollcall,
  transferFieldWorker,
  WORK_DAY_STATUS_LABELS,
  type FieldConsolidationRow,
  type FieldCrew,
  type FieldEventType,
  type FieldWorkDay,
  type RollcallLineStatus,
} from 'src/modules/asistencia/api';
import {
  cargarOpcionesEmpleados,
  etiquetaPeriodo,
  filtrarOpciones,
  MAPA_ESTADO_CONSOLIDACION,
  MAPA_ESTADO_JORNADA,
  type OpcionEmpleado,
} from 'src/modules/asistencia/ui';
import { consolidateFieldAttendance, listPeriods } from 'src/modules/nomina/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const route = useRoute();
const acl = useAclStore();
const ctx = useContextStore();

const workDayId = Number(route.params.id);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const puedeCapturar = computed(() => puede('nomina.field.capture'));
const puedeConsolidar = computed(() => puede('nomina.field.consolidate'));
const puedeSolicitarAprobacion = computed(() => puede('nomina.field.approve.request'));

const tab = ref('lista');
const loading = ref(false);
const jornada = ref<FieldWorkDay | null>(null);

const editable = computed(
  () => !!jornada.value && jornada.value.status !== 'APPROVED' && jornada.value.status !== 'LOCKED',
);
const etiquetaEstado = computed(() =>
  jornada.value ? WORK_DAY_STATUS_LABELS[jornada.value.status].toLowerCase() : '',
);

async function cargar() {
  loading.value = true;
  try {
    jornada.value = await getFieldWorkDay(workDayId);
    const [rollcall, crews, approvals] = await Promise.all([
      getFieldRollcall(workDayId),
      listFieldCrews(workDayId),
      listFieldApprovalRequests({ workDayId }),
      cargarConsolidaciones(),
    ]);
    cuadrillas.value = crews;
    codigoAprobacion.value = approvals[0]?.request_id ?? '';
    if (rollcall) {
      notasLista.value = rollcall.notes;
      const byEmployee = new Map(rollcall.lines.map((line) => [line.employee_id, line]));
      lineasLista.value = lineasLista.value.map((line) => {
        const persisted = byEmployee.get(line.employee_id);
        return persisted
          ? { ...line, status: persisted.status ?? 'UNKNOWN', absence_reason: persisted.absence_reason ?? '' }
          : line;
      });
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar la jornada.') });
  } finally {
    loading.value = false;
  }
}

// --- personal (RH) compartido por todas las pestañas ---
const cargandoEmpleados = ref(false);
const opcionesEmpleados = ref<OpcionEmpleado[]>([]);
const opcionesEmpleadosFiltradas = ref<OpcionEmpleado[]>([]);

function filtrarEmpleados(input: string, update: (fn: () => void) => void) {
  update(() => {
    opcionesEmpleadosFiltradas.value = filtrarOpciones(opcionesEmpleados.value, input);
  });
}

function nombreEmpleado(id: number): string {
  return opcionesEmpleados.value.find((o) => o.value === id)?.label ?? `Empleado #${id}`;
}

async function cargarEmpleados() {
  cargandoEmpleados.value = true;
  try {
    opcionesEmpleados.value = await cargarOpcionesEmpleados();
    opcionesEmpleadosFiltradas.value = opcionesEmpleados.value;
    lineasLista.value = opcionesEmpleados.value.map((o) => ({
      employee_id: o.value,
      nombre: o.label,
      status: 'UNKNOWN',
      absence_reason: '',
    }));
  } catch {
    $q.notify({ type: 'warning', message: 'No se pudo cargar el personal de RH.' });
  } finally {
    cargandoEmpleados.value = false;
  }
}

// --- pase de lista ---
interface LineaLista {
  employee_id: number;
  nombre: string;
  status: RollcallLineStatus;
  absence_reason: string;
}

const lineasLista = ref<LineaLista[]>([]);
const busquedaLista = ref('');
const notasLista = ref('');
const enviandoLista = ref(false);

const lineasFiltradas = computed(() => {
  const q = (busquedaLista.value || '').trim().toLowerCase();
  if (!q) return lineasLista.value;
  return lineasLista.value.filter((l) => l.nombre.toLowerCase().includes(q));
});

const marcadosLista = computed(
  () => lineasLista.value.filter((l) => l.status !== 'UNKNOWN').length,
);

async function enviarPaseDeLista() {
  enviandoLista.value = true;
  try {
    const res = await submitRollcall(workDayId, {
      lines: lineasLista.value.map((l) => ({
        employee_id: l.employee_id,
        status: l.status,
        ...(l.status === 'ABSENT' && l.absence_reason.trim()
          ? { absence_reason: l.absence_reason.trim() }
          : {}),
      })),
      ...(notasLista.value.trim() ? { notes: notasLista.value.trim() } : {}),
    });
    jornada.value = res;
    $q.notify({ type: 'positive', message: 'Pase de lista enviado.' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo enviar el pase de lista.') });
  } finally {
    enviandoLista.value = false;
  }
}

// --- cuadrillas persistidas de la jornada ---
const cuadrillas = ref<FieldCrew[]>([]);
const nombreCuadrilla = ref('');
const capatazCuadrilla = ref<number | null>(null);
const creandoCuadrilla = ref(false);

const opcionesCuadrilla = computed(() =>
  cuadrillas.value.map((c) => ({ label: `#${c.id} — ${c.name}`, value: c.id })),
);

async function crearCuadrilla() {
  if (!nombreCuadrilla.value.trim() || capatazCuadrilla.value == null) return;
  creandoCuadrilla.value = true;
  try {
    const creada = await createFieldCrew(workDayId, {
      name: nombreCuadrilla.value.trim(),
      supervisor_employee_id: capatazCuadrilla.value,
    });
    await cargar();
    nombreCuadrilla.value = '';
    capatazCuadrilla.value = null;
    $q.notify({ type: 'positive', message: `Cuadrilla #${creada.id} creada.` });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear la cuadrilla.') });
  } finally {
    creandoCuadrilla.value = false;
  }
}

// --- eventos individuales ---
const eventoEmpleado = ref<number | null>(null);
const eventoTipo = ref<FieldEventType>('PRESENT');
const eventoDetalle = ref('');
const registrandoEvento = ref(false);
const eventosSesion = ref<{ id: number; empleado: string; event_type: FieldEventType; details: string }[]>([]);

// TRANSFERRED se registra desde la pestaña Traslados (exige cuadrillas origen/destino).
const opcionesEvento = (Object.entries(FIELD_EVENT_LABELS) as [FieldEventType, string][])
  .filter(([value]) => value !== 'TRANSFERRED')
  .map(([value, label]) => ({ value, label }));

const detalleObligatorio = computed(() => FIELD_EVENTS_CON_DETALLE.includes(eventoTipo.value));
const puedeRegistrarEvento = computed(
  () =>
    editable.value &&
    eventoEmpleado.value != null &&
    (!detalleObligatorio.value || eventoDetalle.value.trim().length > 0),
);

async function registrarEvento() {
  if (!puedeRegistrarEvento.value || eventoEmpleado.value == null) return;
  registrandoEvento.value = true;
  try {
    const res = await recordFieldEvent(workDayId, {
      employee_id: eventoEmpleado.value,
      event_type: eventoTipo.value,
      ...(eventoDetalle.value.trim() ? { details: eventoDetalle.value.trim() } : {}),
    });
    eventosSesion.value.unshift({
      id: res.id,
      empleado: nombreEmpleado(res.employee_id),
      event_type: res.event_type,
      details: eventoDetalle.value.trim(),
    });
    eventoEmpleado.value = null;
    eventoDetalle.value = '';
    $q.notify({ type: 'positive', message: 'Novedad registrada.' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo registrar la novedad.') });
  } finally {
    registrandoEvento.value = false;
  }
}

// --- traslados ---
const trasladoEmpleado = ref<number | null>(null);
const trasladoDesde = ref<number | null>(null);
const trasladoHacia = ref<number | null>(null);
const trasladoMotivo = ref('');
const registrandoTraslado = ref(false);

const puedeRegistrarTraslado = computed(
  () =>
    editable.value &&
    trasladoEmpleado.value != null &&
    trasladoDesde.value != null &&
    trasladoHacia.value != null &&
    trasladoDesde.value !== trasladoHacia.value &&
    trasladoMotivo.value.trim().length > 0,
);

async function registrarTraslado() {
  if (!puedeRegistrarTraslado.value) return;
  registrandoTraslado.value = true;
  try {
    await transferFieldWorker(workDayId, {
      employee_id: trasladoEmpleado.value as number,
      from_crew_id: trasladoDesde.value as number,
      to_crew_id: trasladoHacia.value as number,
      reason: trasladoMotivo.value.trim(),
    });
    $q.notify({ type: 'positive', message: 'Traslado registrado.' });
    trasladoEmpleado.value = null;
    trasladoDesde.value = null;
    trasladoHacia.value = null;
    trasladoMotivo.value = '';
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo registrar el traslado.') });
  } finally {
    registrandoTraslado.value = false;
  }
}

// --- consolidación + aprobación SoD ---
const consolidaciones = ref<FieldConsolidationRow[]>([]);
const cargandoConsolidaciones = ref(false);
const consolidando = ref(false);
const solicitandoAprobacion = ref(false);
const codigoAprobacion = ref('');

const columnasConsolidacion: QTableColumn<FieldConsolidationRow>[] = [
  { name: 'empleado', label: 'Trabajador', field: 'employee_id', align: 'left' },
  { name: 'status', label: 'Estado', field: 'status', align: 'left' },
  { name: 'day_value', label: 'Valor del día', field: 'day_value', align: 'right' },
  { name: 'evento', label: 'Evento principal', field: 'primary_event_type', align: 'left' },
  { name: 'conflictos', label: 'Conflictos', field: 'conflict_codes', align: 'left' },
];

function etiquetaEvento(codigo: string): string {
  return FIELD_EVENT_LABELS[codigo as FieldEventType] ?? codigo ?? '—';
}

async function cargarConsolidaciones() {
  cargandoConsolidaciones.value = true;
  try {
    consolidaciones.value = await listFieldConsolidations(workDayId);
  } catch (e) {
    $q.notify({
      type: 'negative',
      message: apiErrorMessage(e, 'No se pudieron cargar las consolidaciones.'),
    });
  } finally {
    cargandoConsolidaciones.value = false;
  }
}

async function consolidarDia() {
  // El destino es un período de planilla ABIERTO; si la jornada ya tiene uno, se reusa.
  let periodId = jornada.value?.payroll_period_id ?? null;
  if (periodId == null) {
    let abiertos;
    try {
      abiertos = (await listPeriods()).filter((p) => p.status === 'DRAFT' || p.status === 'IN_REVIEW');
    } catch {
      $q.notify({ type: 'negative', message: 'No se pudieron cargar los períodos de planilla.' });
      return;
    }
    if (abiertos.length === 0) {
      $q.notify({
        type: 'warning',
        timeout: 6000,
        message: 'No hay un período de planilla abierto. Creá uno en Nómina y volvé.',
      });
      return;
    }
    periodId = await new Promise<number | null>((resolve) => {
      $q.dialog({
        title: 'Consolidar la jornada',
        message: '¿Hacia qué período de planilla se consolida el día?',
        options: {
          type: 'radio',
          model: String(abiertos[0]!.id),
          items: abiertos.map((p) => ({ label: etiquetaPeriodo(p), value: String(p.id) })),
        },
        ok: { label: 'Consolidar', color: 'primary', noCaps: true, unelevated: true },
        cancel: { label: 'Cancelar', flat: true, noCaps: true },
      })
        .onOk((v: string) => resolve(Number(v)))
        .onCancel(() => resolve(null));
    });
    if (periodId == null) return;
  }

  consolidando.value = true;
  try {
    const res = await consolidateFieldAttendance(workDayId, periodId);
    $q.notify({
      type: 'positive',
      message: `Día consolidado: ${res.consolidations.length} trabajadores.`,
    });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo consolidar el día.') });
  } finally {
    consolidando.value = false;
  }
}

async function solicitarAprobacion() {
  solicitandoAprobacion.value = true;
  try {
    const res = await requestFieldApproval(workDayId, 'Aprobación de asistencia de campo');
    codigoAprobacion.value = res.approval_request_id;
    $q.notify({
      type: 'positive',
      timeout: 8000,
      message: 'Aprobación solicitada. Compartí el código con quien aprueba (SoD: debe ser otra persona).',
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo solicitar la aprobación.') });
  } finally {
    solicitandoAprobacion.value = false;
  }
}

function copiarCodigo() {
  void copyToClipboard(codigoAprobacion.value).then(() =>
    $q.notify({ type: 'positive', message: 'Código copiado.' }),
  );
}

onMounted(async () => {
  await cargarEmpleados();
  await cargar();
});
</script>

<style scoped>
.jcampo-lista {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}

.jcampo-fila {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  padding: var(--app-space-2) var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.jcampo-fila__nombre {
  flex: 1;
  min-width: 0;
}

.jcampo-form-card {
  max-width: 560px;
}

.jcampo-uuid {
  word-break: break-all;
}

@media (max-width: 599px) {
  .jcampo-fila {
    flex-wrap: wrap;
  }
}
</style>
