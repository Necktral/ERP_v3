<template>
  <q-page class="app-page">
    <!-- ===================== Vista 1: listado de reportes ===================== -->
    <template v-if="!reporte">
      <PageHeader
        title="Captura de campo por cuadrilla"
        subtitle="Flujo simple: jornada de la cuadrilla → eventos por trabajador → aprobación (otra persona) → asistencia del período."
        :loading="loading"
        @refresh="reload"
      >
        <template #actions>
          <q-btn
            v-if="puede('nomina.field.capture')"
            unelevated
            no-caps
            color="primary"
            icon="add"
            label="Nueva jornada"
            @click="dlgNueva = true"
          />
        </template>
      </PageHeader>

      <q-table
        v-model:pagination="pagination"
        class="app-table"
        :rows="rows"
        :columns="columnasReporte"
        row-key="id"
        flat
        :loading="loading"
        :rows-per-page-options="[10, 25, 50, 100]"
        no-data-label="No hay reportes de captura. Creá la jornada de una cuadrilla para empezar."
        @request="onRequest"
        @row-click="(_evt: Event, row: CaptureReport) => seleccionarReporte(row)"
      >
        <template #body-cell-cuadrilla="props">
          <q-td :props="props">{{ nombreCuadrilla(props.row.crew) }}</q-td>
        </template>
        <template #body-cell-status="props">
          <q-td :props="props">
            <EstadoChip :estado="props.row.status" :map="MAPA_ESTADO_CAPTURA" />
          </q-td>
        </template>
        <template #body-cell-created_at="props">
          <q-td :props="props">{{ formatDate(props.row.created_at) }}</q-td>
        </template>
        <template #body-cell-acciones="props">
          <q-td :props="props">
            <q-btn
              dense
              flat
              no-caps
              color="primary"
              icon="chevron_right"
              label="Abrir"
              @click.stop="seleccionarReporte(props.row)"
            />
          </q-td>
        </template>
      </q-table>
    </template>

    <!-- ===================== Vista 2: reporte seleccionado ===================== -->
    <template v-else>
      <PageHeader
        :title="`Reporte de captura #${reporte.id}`"
        :subtitle="`Cuadrilla: ${nombreCuadrilla(reporte.crew)} · Período #${reporte.period}`"
        hide-refresh
      >
        <template #actions>
          <EstadoChip :estado="reporte.status" :map="MAPA_ESTADO_CAPTURA" />
          <q-btn flat no-caps icon="arrow_back" label="Reportes" @click="volverAlListado" />
        </template>
      </PageHeader>

      <!-- Paso a paso lineal -->
      <div class="ccampo-pasos q-mb-md">
        <q-chip
          v-for="(paso, i) in pasos"
          :key="paso.clave"
          dense
          :color="paso.hecho ? 'positive' : 'grey-4'"
          :text-color="paso.hecho ? 'white' : 'grey-8'"
          :icon="paso.hecho ? 'check' : undefined"
        >
          {{ i + 1 }}. {{ paso.etiqueta }}
        </q-chip>
      </div>

      <q-banner v-if="codigoSolicitud" dense rounded class="bg-blue-1 text-dark q-mb-md">
        <template #avatar><q-icon name="key" color="primary" /></template>
        Código de solicitud para el aprobador: <b class="ccampo-uuid">{{ codigoSolicitud }}</b>
        <template #action>
          <q-btn dense flat no-caps icon="content_copy" label="Copiar" @click="copiarCodigo" />
        </template>
      </q-banner>

      <div class="row q-col-gutter-md">
        <!-- Eventos -->
        <div class="col-12 col-md-7">
          <q-card flat bordered>
            <q-card-section class="text-subtitle1">
              Eventos por trabajador ({{ paginacionEventos.rowsNumber }})
            </q-card-section>
            <q-table
              v-model:pagination="paginacionEventos"
              class="app-table"
              :rows="eventos"
              :columns="columnasEvento"
              row-key="id"
              flat
              :loading="cargandoEventos"
              :rows-per-page-options="[10, 25, 50, 100]"
              no-data-label="Sin eventos: registrá a cada trabajador de la cuadrilla."
              @request="onRequestEventos"
            >
              <template #body-cell-trabajador="props">
                <q-td :props="props">
                  {{ props.row.employee_name || props.row.cedula || `Empleado #${props.row.employee}` }}
                </q-td>
              </template>
              <template #body-cell-event_type="props">
                <q-td :props="props">{{ CAPTURE_EVENT_LABELS[props.row.event_type as CaptureEventType] }}</q-td>
              </template>
            </q-table>
          </q-card>
        </div>

        <!-- Registrar evento + acciones -->
        <div class="col-12 col-md-5">
          <q-card v-if="puede('nomina.field.capture') && reporte.status !== 'APPROVED'" flat bordered>
            <q-card-section class="text-subtitle1">Registrar evento</q-card-section>
            <q-card-section class="app-form">
              <q-btn-toggle
                v-model="modoEmpleado"
                dense
                no-caps
                unelevated
                toggle-color="primary"
                :options="[
                  { label: 'Personal de RH', value: 'rh' },
                  { label: 'Por cédula', value: 'manual' },
                ]"
              />
              <q-select
                v-if="modoEmpleado === 'rh'"
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
              <template v-else>
                <q-input v-model="eventoCedula" outlined dense label="Cédula *" />
                <q-input v-model="eventoNombre" outlined dense label="Nombre completo *" />
              </template>
              <q-select
                v-model="eventoTipo"
                outlined
                dense
                emit-value
                map-options
                label="Tipo de evento *"
                :options="opcionesEventoCaptura"
              />
              <q-select
                v-model="eventoDia"
                outlined
                dense
                emit-value
                map-options
                label="Valor del día"
                :options="OPCIONES_DIA"
              />
              <div class="row q-col-gutter-sm">
                <div class="col-6">
                  <q-input
                    v-model.number="eventoHorasExtra"
                    outlined
                    dense
                    type="number"
                    min="0"
                    step="0.5"
                    label="Horas extra"
                  />
                </div>
                <div class="col-6">
                  <q-input
                    v-model.number="eventoDomingos"
                    outlined
                    dense
                    type="number"
                    min="0"
                    label="Domingos trabajados"
                  />
                </div>
              </div>
              <q-select
                v-if="eventoTipo === 'TRANSFER'"
                v-model="eventoCuadrillaDestino"
                outlined
                dense
                emit-value
                map-options
                label="Cuadrilla destino *"
                :options="opcionesCuadrillaDestino"
              />
              <q-input v-model="eventoNotas" outlined dense label="Notas" />
              <q-btn
                unelevated
                no-caps
                color="primary"
                icon="add_task"
                label="Registrar evento"
                :loading="registrandoEvento"
                :disable="!puedeRegistrarEvento"
                @click="registrarEvento"
              />
            </q-card-section>
          </q-card>

          <!-- Aprobación y asistencia -->
          <q-card flat bordered class="q-mt-md">
            <q-card-section class="text-subtitle1">Cierre del reporte</q-card-section>
            <q-card-section class="app-form">
              <q-btn
                v-if="puede('nomina.attendance.review')"
                unelevated
                no-caps
                color="primary"
                icon="how_to_vote"
                label="Pedir aprobación (SoD)"
                :loading="solicitando"
                :disable="reporte.status === 'APPROVED' || eventos.length === 0"
                @click="pedirAprobacion"
              >
                <q-tooltip v-if="eventos.length === 0">Registrá al menos un evento.</q-tooltip>
              </q-btn>
              <q-btn
                v-if="puede('nomina.attendance.approve')"
                outline
                no-caps
                color="positive"
                icon="check_circle"
                label="Aprobar reporte"
                :disable="reporte.status !== 'APPROVAL_PENDING'"
                @click="dlgAprobar = true"
              />
              <q-btn
                v-if="puede('nomina.attendance.build')"
                unelevated
                no-caps
                color="secondary"
                icon="fact_check"
                label="Construir asistencia del período"
                :loading="construyendo"
                :disable="reporte.status !== 'APPROVED'"
                @click="construirAsistencia"
              >
                <q-tooltip v-if="reporte.status !== 'APPROVED'">
                  Disponible cuando el reporte esté aprobado.
                </q-tooltip>
              </q-btn>
              <div class="text-caption text-grey-7">
                Por SoD quien aprueba debe ser una persona distinta de quien pidió la aprobación.
              </div>
            </q-card-section>
          </q-card>

          <!-- Resultado de la asistencia construida -->
          <q-card v-if="asistencia.length" flat bordered class="q-mt-md">
            <q-card-section class="text-subtitle1">
              Asistencia del período ({{ asistencia.length }} trabajadores)
            </q-card-section>
            <q-markup-table flat dense>
              <thead>
                <tr>
                  <th class="text-left">Trabajador</th>
                  <th class="text-right">Trabajados</th>
                  <th class="text-right">Ausencias</th>
                  <th class="text-right">Subsidio</th>
                  <th class="text-right">H. extra</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="a in asistencia" :key="a.id">
                  <td>{{ a.employee_name || a.cedula }}</td>
                  <td class="text-right">{{ a.days_worked }}</td>
                  <td class="text-right">{{ a.days_absent }}</td>
                  <td class="text-right">{{ a.days_subsidy }}</td>
                  <td class="text-right">{{ a.overtime_hours }}</td>
                </tr>
              </tbody>
            </q-markup-table>
          </q-card>
        </div>
      </div>

      <!-- Diálogo: aprobar (checker) -->
      <q-dialog v-model="dlgAprobar">
        <q-card class="app-dialog">
          <q-card-section class="text-h6">Aprobar reporte de captura</q-card-section>
          <q-card-section class="app-form">
            <q-input
              v-model="codigoAprobar"
              outlined
              dense
              label="Código de solicitud *"
              hint="Lo vio quien pidió la aprobación; si fue en este equipo ya viene puesto."
            />
            <q-input v-model="notaAprobar" outlined dense label="Nota (opcional)" />
          </q-card-section>
          <q-card-actions align="right">
            <q-btn flat no-caps label="Cancelar" v-close-popup />
            <q-btn
              unelevated
              no-caps
              color="positive"
              label="Aprobar"
              :loading="aprobando"
              :disable="!codigoAprobarValido"
              @click="aprobarReporte"
            />
          </q-card-actions>
        </q-card>
      </q-dialog>
    </template>

    <!-- Diálogo: nueva jornada de captura (cuadrilla + período + fecha) -->
    <q-dialog v-model="dlgNueva">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Nueva jornada de captura</q-card-section>
        <q-card-section class="app-form">
          <q-select
            v-model="nuevaCuadrilla"
            outlined
            dense
            emit-value
            map-options
            label="Cuadrilla *"
            :options="opcionesCuadrilla"
            :loading="cargandoCuadrillas"
          />
          <q-expansion-item
            v-if="puede('nomina.field.manage')"
            dense
            icon="group_add"
            label="Crear cuadrilla nueva"
          >
            <div class="app-form q-pa-sm">
              <q-input v-model="cuadrillaNombre" outlined dense label="Nombre *" />
              <q-input v-model="cuadrillaCodigo" outlined dense label="Código" />
              <q-select
                v-model="cuadrillaSucursal"
                outlined
                dense
                emit-value
                map-options
                label="Sucursal / finca *"
                :options="opcionesSucursal"
              />
              <q-select
                v-model="cuadrillaCapataz"
                outlined
                dense
                clearable
                use-input
                input-debounce="0"
                emit-value
                map-options
                label="Capataz (opcional)"
                :options="opcionesEmpleadosFiltradas"
                :loading="cargandoEmpleados"
                @filter="filtrarEmpleados"
              />
              <q-btn
                outline
                no-caps
                color="primary"
                label="Crear cuadrilla"
                :loading="creandoCuadrilla"
                :disable="!cuadrillaNombre.trim() || cuadrillaSucursal == null"
                @click="crearCuadrilla"
              />
            </div>
          </q-expansion-item>
          <q-select
            v-model="nuevoPeriodo"
            outlined
            dense
            emit-value
            map-options
            label="Período de planilla *"
            :options="opcionesPeriodo"
            :loading="cargandoPeriodos"
          />
          <q-input
            v-model="nuevaFecha"
            outlined
            dense
            type="date"
            label="Fecha de trabajo *"
            hint="Debe caer dentro del período elegido."
          />
          <q-input v-model="nuevasObservaciones" outlined dense autogrow label="Observaciones" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear jornada"
            :loading="creandoJornada"
            :disable="nuevaCuadrilla == null || nuevoPeriodo == null || !nuevaFecha"
            @click="crearJornada"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { copyToClipboard, useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import EstadoChip from 'src/components/EstadoChip.vue';
import { apiErrorMessage, PAGE } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { formatDate } from 'src/core/format';
import {
  approveCaptureReport,
  buildCaptureAttendance,
  CAPTURE_EVENT_LABELS,
  createCaptureCrew,
  createCaptureEvent,
  createCaptureWorkDay,
  listCaptureCrews,
  listCaptureEvents,
  listCaptureReports,
  requestCaptureApproval,
  type AttendanceReportRow,
  type CaptureCrew,
  type CaptureEvent,
  type CaptureEventType,
  type CaptureReport,
} from 'src/modules/asistencia/api';
import {
  cargarOpcionesEmpleados,
  etiquetaPeriodo,
  filtrarOpciones,
  MAPA_ESTADO_CAPTURA,
  type OpcionEmpleado,
} from 'src/modules/asistencia/ui';
import { listBranches } from 'src/modules/hr/api';
import { listPeriods } from 'src/modules/nomina/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

// ===================== listado de reportes =====================
const { rows, loading, pagination, onRequest, reload } = useListadoServer<CaptureReport>(
  (page) => listCaptureReports({}, page),
  { errorMessage: 'No se pudieron cargar los reportes de captura.' },
);

const columnasReporte: QTableColumn<CaptureReport>[] = [
  { name: 'id', label: 'N°', field: 'id', align: 'left' },
  { name: 'cuadrilla', label: 'Cuadrilla', field: 'crew', align: 'left' },
  { name: 'period', label: 'Período', field: 'period', align: 'left' },
  { name: 'status', label: 'Estado', field: 'status', align: 'left' },
  { name: 'event_count', label: 'Eventos', field: 'event_count', align: 'right' },
  { name: 'created_at', label: 'Creado', field: 'created_at', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

// ===================== cuadrillas (catálogo) =====================
const cuadrillas = ref<CaptureCrew[]>([]);
const cargandoCuadrillas = ref(false);

const opcionesCuadrilla = computed(() =>
  cuadrillas.value.map((c) => ({
    label: c.code ? `${c.name} (${c.code})` : c.name,
    value: c.id,
  })),
);

function nombreCuadrilla(id: number): string {
  const c = cuadrillas.value.find((x) => x.id === id);
  return c ? c.name : `Cuadrilla #${id}`;
}

async function cargarCuadrillas() {
  cargandoCuadrillas.value = true;
  try {
    const res = await listCaptureCrews({ ...PAGE });
    cuadrillas.value = res.results;
  } catch {
    cuadrillas.value = [];
  } finally {
    cargandoCuadrillas.value = false;
  }
}

// ===================== personal (RH) =====================
const cargandoEmpleados = ref(false);
const opcionesEmpleados = ref<OpcionEmpleado[]>([]);
const opcionesEmpleadosFiltradas = ref<OpcionEmpleado[]>([]);

function filtrarEmpleados(input: string, update: (fn: () => void) => void) {
  update(() => {
    opcionesEmpleadosFiltradas.value = filtrarOpciones(opcionesEmpleados.value, input);
  });
}

// ===================== nueva jornada =====================
const dlgNueva = ref(false);
const nuevaCuadrilla = ref<number | null>(null);
const nuevoPeriodo = ref<number | null>(null);
const nuevaFecha = ref(new Date().toISOString().slice(0, 10));
const nuevasObservaciones = ref('');
const creandoJornada = ref(false);

const opcionesPeriodo = ref<{ label: string; value: number }[]>([]);
const cargandoPeriodos = ref(false);

// nueva cuadrilla (inline)
const cuadrillaNombre = ref('');
const cuadrillaCodigo = ref('');
const cuadrillaSucursal = ref<number | null>(null);
const cuadrillaCapataz = ref<number | null>(null);
const creandoCuadrilla = ref(false);
const opcionesSucursal = ref<{ label: string; value: number }[]>([]);

async function cargarPeriodos() {
  cargandoPeriodos.value = true;
  try {
    const periodos = (await listPeriods()).filter(
      (p) => p.status === 'DRAFT' || p.status === 'IN_REVIEW',
    );
    opcionesPeriodo.value = periodos.map((p) => ({ label: etiquetaPeriodo(p), value: p.id }));
  } catch {
    opcionesPeriodo.value = [];
  } finally {
    cargandoPeriodos.value = false;
  }
}

async function crearCuadrilla() {
  if (!cuadrillaNombre.value.trim() || cuadrillaSucursal.value == null) return;
  creandoCuadrilla.value = true;
  try {
    const creada = await createCaptureCrew({
      branch_id: cuadrillaSucursal.value,
      name: cuadrillaNombre.value.trim(),
      ...(cuadrillaCodigo.value.trim() ? { code: cuadrillaCodigo.value.trim() } : {}),
      ...(cuadrillaCapataz.value != null ? { foreman_id: cuadrillaCapataz.value } : {}),
    });
    cuadrillas.value.push(creada);
    nuevaCuadrilla.value = creada.id;
    cuadrillaNombre.value = '';
    cuadrillaCodigo.value = '';
    $q.notify({ type: 'positive', message: `Cuadrilla "${creada.name}" creada.` });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear la cuadrilla.') });
  } finally {
    creandoCuadrilla.value = false;
  }
}

async function crearJornada() {
  if (nuevaCuadrilla.value == null || nuevoPeriodo.value == null || !nuevaFecha.value) return;
  creandoJornada.value = true;
  try {
    const res = await createCaptureWorkDay({
      period_id: nuevoPeriodo.value,
      crew_id: nuevaCuadrilla.value,
      work_date: nuevaFecha.value,
      ...(nuevasObservaciones.value.trim()
        ? { observations: nuevasObservaciones.value.trim() }
        : {}),
    });
    dlgNueva.value = false;
    $q.notify({ type: 'positive', message: `Jornada de captura lista (reporte #${res.report.id}).` });
    seleccionarReporte(res.report);
  } catch (e) {
    // 400 típico: la fecha no cae dentro del período elegido.
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear la jornada.') });
  } finally {
    creandoJornada.value = false;
  }
}

// ===================== reporte seleccionado =====================
const reporte = ref<CaptureReport | null>(null);
const asistencia = ref<AttendanceReportRow[]>([]);

function claveSolicitud(reportId: number): string {
  return `asistencia.captura.reporte.${reportId}.solicitud`;
}

const codigoSolicitud = ref('');

function seleccionarReporte(row: CaptureReport) {
  reporte.value = row;
  asistencia.value = [];
  codigoSolicitud.value = localStorage.getItem(claveSolicitud(row.id)) ?? '';
  codigoAprobar.value = codigoSolicitud.value;
  void recargarEventos();
}

function volverAlListado() {
  reporte.value = null;
  void reload();
}

const pasos = computed(() => {
  const st = reporte.value?.status ?? 'DRAFT';
  const hayEventos = paginacionEventos.value.rowsNumber > 0;
  return [
    { clave: 'jornada', etiqueta: 'Jornada creada', hecho: true },
    { clave: 'eventos', etiqueta: 'Eventos registrados', hecho: hayEventos },
    {
      clave: 'solicitud',
      etiqueta: 'Aprobación pedida',
      hecho: st === 'APPROVAL_PENDING' || st === 'APPROVED',
    },
    { clave: 'aprobado', etiqueta: 'Aprobado', hecho: st === 'APPROVED' },
    { clave: 'asistencia', etiqueta: 'Asistencia construida', hecho: asistencia.value.length > 0 },
  ];
});

// --- eventos del reporte (server-side, carga al seleccionar) ---
const {
  rows: eventos,
  loading: cargandoEventos,
  pagination: paginacionEventos,
  onRequest: onRequestEventos,
  reload: recargarEventos,
} = useListadoServer<CaptureEvent>(
  (page) =>
    reporte.value
      ? listCaptureEvents(reporte.value.id, page)
      : Promise.resolve({ count: 0, limit: page.limit, offset: page.offset, results: [] }),
  { errorMessage: 'No se pudieron cargar los eventos.', auto: false },
);

const columnasEvento: QTableColumn<CaptureEvent>[] = [
  { name: 'trabajador', label: 'Trabajador', field: 'employee_name', align: 'left' },
  { name: 'event_type', label: 'Evento', field: 'event_type', align: 'left' },
  { name: 'day_value', label: 'Día', field: 'day_value', align: 'right' },
  { name: 'overtime_hours', label: 'H. extra', field: 'overtime_hours', align: 'right' },
  { name: 'sunday_worked_days', label: 'Domingos', field: 'sunday_worked_days', align: 'right' },
];

// --- registrar evento ---
const modoEmpleado = ref<'rh' | 'manual'>('rh');
const eventoEmpleado = ref<number | null>(null);
const eventoCedula = ref('');
const eventoNombre = ref('');
const eventoTipo = ref<CaptureEventType>('PRESENT');
const eventoDia = ref('1.00');
const eventoHorasExtra = ref<number>(0);
const eventoDomingos = ref<number>(0);
const eventoCuadrillaDestino = ref<number | null>(null);
const eventoNotas = ref('');
const registrandoEvento = ref(false);

const OPCIONES_DIA = [
  { label: 'Día completo (1.00)', value: '1.00' },
  { label: 'Medio día (0.50)', value: '0.50' },
  { label: 'Sin día (0.00)', value: '0.00' },
];

const opcionesEventoCaptura = (
  Object.entries(CAPTURE_EVENT_LABELS) as [CaptureEventType, string][]
).map(([value, label]) => ({ value, label }));

const opcionesCuadrillaDestino = computed(() =>
  opcionesCuadrilla.value.filter((o) => o.value !== reporte.value?.crew),
);

const puedeRegistrarEvento = computed(() => {
  const conEmpleado =
    modoEmpleado.value === 'rh'
      ? eventoEmpleado.value != null
      : eventoCedula.value.trim().length > 0 && eventoNombre.value.trim().length > 0;
  const conDestino = eventoTipo.value !== 'TRANSFER' || eventoCuadrillaDestino.value != null;
  return conEmpleado && conDestino;
});

async function registrarEvento() {
  if (!reporte.value || !puedeRegistrarEvento.value) return;
  registrandoEvento.value = true;
  try {
    await createCaptureEvent(reporte.value.id, {
      ...(modoEmpleado.value === 'rh'
        ? { employee_id: eventoEmpleado.value }
        : { cedula: eventoCedula.value.trim(), employee_name: eventoNombre.value.trim() }),
      event_type: eventoTipo.value,
      day_value: eventoDia.value,
      overtime_hours: String(eventoHorasExtra.value || 0),
      sunday_worked_days: eventoDomingos.value || 0,
      ...(eventoTipo.value === 'TRANSFER' ? { to_crew_id: eventoCuadrillaDestino.value } : {}),
      ...(eventoNotas.value.trim() ? { notes: eventoNotas.value.trim() } : {}),
    });
    eventoEmpleado.value = null;
    eventoCedula.value = '';
    eventoNombre.value = '';
    eventoNotas.value = '';
    eventoCuadrillaDestino.value = null;
    eventoHorasExtra.value = 0;
    eventoDomingos.value = 0;
    $q.notify({ type: 'positive', message: 'Evento registrado.' });
    await recargarEventos();
  } catch (e) {
    // 400 típico: mismo trabajador con el mismo tipo de evento repetido en el reporte.
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo registrar el evento.') });
  } finally {
    registrandoEvento.value = false;
  }
}

// --- aprobación SoD ---
const solicitando = ref(false);
const dlgAprobar = ref(false);
const aprobando = ref(false);
const codigoAprobar = ref('');
const notaAprobar = ref('');

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const codigoAprobarValido = computed(() => UUID_RE.test(codigoAprobar.value.trim()));

async function pedirAprobacion() {
  if (!reporte.value) return;
  solicitando.value = true;
  try {
    const res = await requestCaptureApproval(reporte.value.id, 'Aprobación del reporte de captura');
    reporte.value = res.report;
    codigoSolicitud.value = res.approval_request_id;
    codigoAprobar.value = res.approval_request_id;
    localStorage.setItem(claveSolicitud(res.report.id), res.approval_request_id);
    $q.notify({
      type: 'positive',
      timeout: 8000,
      message: 'Aprobación pedida. Compartí el código con quien aprueba (debe ser otra persona).',
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo pedir la aprobación.') });
  } finally {
    solicitando.value = false;
  }
}

async function aprobarReporte() {
  if (!reporte.value || !codigoAprobarValido.value) return;
  aprobando.value = true;
  try {
    const res = await approveCaptureReport(reporte.value.id, {
      approval_request_id: codigoAprobar.value.trim(),
      ...(notaAprobar.value.trim() ? { note: notaAprobar.value.trim() } : {}),
    });
    reporte.value = res;
    dlgAprobar.value = false;
    $q.notify({ type: 'positive', message: 'Reporte aprobado: ya se puede construir la asistencia.' });
  } catch (e) {
    // 403 = SoD (mismo usuario que pidió la aprobación).
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo aprobar el reporte.') });
  } finally {
    aprobando.value = false;
  }
}

// --- construir asistencia ---
const construyendo = ref(false);

async function construirAsistencia() {
  if (!reporte.value) return;
  construyendo.value = true;
  try {
    const res = await buildCaptureAttendance(reporte.value.id);
    asistencia.value = res.results;
    $q.notify({
      type: 'positive',
      message: `Asistencia del período construida para ${res.count} trabajadores.`,
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo construir la asistencia.') });
  } finally {
    construyendo.value = false;
  }
}

// ===================== carga inicial =====================
onMounted(async () => {
  cargandoEmpleados.value = true;
  try {
    opcionesEmpleados.value = await cargarOpcionesEmpleados();
    opcionesEmpleadosFiltradas.value = opcionesEmpleados.value;
  } catch {
    opcionesEmpleados.value = [];
  } finally {
    cargandoEmpleados.value = false;
  }
  await Promise.all([cargarCuadrillas(), cargarPeriodos()]);
  try {
    const branches = await listBranches();
    opcionesSucursal.value = branches.map((b) => ({ label: b.name, value: b.id }));
  } catch {
    opcionesSucursal.value = [];
  }
});
</script>

<style scoped>
.ccampo-pasos {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-2);
}

.ccampo-uuid {
  word-break: break-all;
}
</style>
