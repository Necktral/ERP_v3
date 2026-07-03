<template>
  <q-page class="app-page">
    <PageHeader
      :title="`Reporte de cuadrilla #${crewId}`"
      subtitle="El capataz reporta qué hizo cada trabajador de su cuadrilla en el día. Reenviarlo reemplaza el borrador anterior."
      hide-refresh
    >
      <template #actions>
        <q-btn
          flat
          no-caps
          icon="arrow_back"
          :label="jornadaId ? `Jornada #${jornadaId}` : 'Jornadas'"
          :to="jornadaId ? `/asistencia/campo/${jornadaId}` : '/asistencia/campo'"
        />
      </template>
    </PageHeader>

    <div class="row q-col-gutter-md">
      <!-- Datos de la labor -->
      <div class="col-12 col-md-4">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1">Labor del día</q-card-section>
          <q-card-section class="app-form">
            <q-input v-model="laborNombre" outlined dense label="Labor (ej: corte de café)" />
            <q-input v-model="laborCodigo" outlined dense label="Código de labor" />
            <q-input v-model="zona" outlined dense label="Zona / lote" />
            <q-input v-model="notas" outlined dense autogrow label="Notas del reporte" />
          </q-card-section>
        </q-card>
      </div>

      <!-- Trabajadores de la cuadrilla -->
      <div class="col-12 col-md-8">
        <q-card flat bordered>
          <q-card-section class="row items-center q-col-gutter-sm">
            <div class="col text-subtitle1">Trabajadores ({{ lineas.length }})</div>
            <div class="col-auto">
              <q-select
                v-model="empleadoAgregar"
                outlined
                dense
                use-input
                input-debounce="0"
                emit-value
                map-options
                label="Agregar trabajador…"
                style="min-width: 240px"
                :options="opcionesDisponibles"
                :loading="cargandoEmpleados"
                @filter="filtrarEmpleados"
                @update:model-value="agregarLinea"
              />
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section v-if="lineas.length === 0" class="text-grey-7">
            Agregá los trabajadores de la cuadrilla: el reporte necesita al menos uno.
          </q-card-section>
          <q-list v-else separator>
            <q-item v-for="(linea, idx) in lineas" :key="linea.employee_id" class="rcuad-linea">
              <q-item-section>
                <q-item-label class="text-weight-bold">{{ linea.nombre }}</q-item-label>
                <div class="row q-col-gutter-sm q-mt-xs">
                  <div class="col-12 col-sm-4">
                    <q-select
                      v-model="linea.event_type"
                      outlined
                      dense
                      emit-value
                      map-options
                      label="Evento"
                      :options="opcionesEvento"
                    />
                  </div>
                  <div class="col-6 col-sm-3">
                    <q-select
                      v-model="linea.day_value"
                      outlined
                      dense
                      emit-value
                      map-options
                      label="Valor del día"
                      :options="OPCIONES_DIA"
                    />
                  </div>
                  <div class="col-6 col-sm-5">
                    <q-input
                      v-model="linea.notes"
                      outlined
                      dense
                      :label="
                        requiereDetalle(linea.event_type) ? 'Detalle * (obligatorio)' : 'Detalle'
                      "
                    />
                  </div>
                </div>
              </q-item-section>
              <q-item-section side top>
                <q-btn
                  dense
                  flat
                  round
                  icon="delete"
                  color="grey-7"
                  aria-label="Quitar"
                  @click="lineas.splice(idx, 1)"
                />
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>

        <div class="q-mt-md row items-center q-col-gutter-sm">
          <div class="col-auto">
            <q-btn
              unelevated
              no-caps
              color="primary"
              icon="send"
              label="Enviar reporte de cuadrilla"
              :loading="enviando"
              :disable="!puedeEnviar"
              @click="enviarReporte"
            >
              <q-tooltip v-if="!puedeEnviar && lineas.length > 0">
                Completá el detalle de los eventos que lo exigen (enfermo, accidente, otro).
              </q-tooltip>
            </q-btn>
          </div>
          <div v-if="enviado" class="col-auto text-positive text-weight-bold">
            <q-icon name="check_circle" /> Reporte enviado — la jornada quedó en revisión.
          </div>
        </div>
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import {
  FIELD_EVENT_LABELS,
  FIELD_EVENTS_CON_DETALLE,
  submitCrewReport,
  type FieldEventType,
} from 'src/modules/asistencia/api';
import {
  cargarOpcionesEmpleados,
  filtrarOpciones,
  type OpcionEmpleado,
} from 'src/modules/asistencia/ui';

const $q = useQuasar();
const route = useRoute();

const crewId = Number(route.params.crewId);
const jornadaId = computed(() => {
  const q = Number(route.query.jornada);
  return Number.isInteger(q) && q > 0 ? q : null;
});

// --- datos de la labor ---
const laborNombre = ref('');
const laborCodigo = ref('');
const zona = ref('');
const notas = ref('');

// --- líneas por trabajador ---
interface LineaReporte {
  employee_id: number;
  nombre: string;
  event_type: FieldEventType;
  day_value: string;
  notes: string;
}

const lineas = ref<LineaReporte[]>([]);
const empleadoAgregar = ref<number | null>(null);

const OPCIONES_DIA = [
  { label: 'Día completo (1.00)', value: '1.00' },
  { label: 'Medio día (0.50)', value: '0.50' },
  { label: 'Sin día (0.00)', value: '0.00' },
];

// TRANSFERRED va por el flujo de traslados de la jornada, no por el reporte.
const opcionesEvento = (Object.entries(FIELD_EVENT_LABELS) as [FieldEventType, string][])
  .filter(([value]) => value !== 'TRANSFERRED')
  .map(([value, label]) => ({ value, label }));

function requiereDetalle(tipo: FieldEventType): boolean {
  return FIELD_EVENTS_CON_DETALLE.includes(tipo);
}

// --- personal de RH ---
const cargandoEmpleados = ref(false);
const opcionesEmpleados = ref<OpcionEmpleado[]>([]);
const filtroEmpleados = ref('');

const opcionesDisponibles = computed(() => {
  const usados = new Set(lineas.value.map((l) => l.employee_id));
  return filtrarOpciones(
    opcionesEmpleados.value.filter((o) => !usados.has(o.value)),
    filtroEmpleados.value,
  );
});

function filtrarEmpleados(input: string, update: (fn: () => void) => void) {
  update(() => {
    filtroEmpleados.value = input;
  });
}

function agregarLinea(employeeId: number | null) {
  if (employeeId == null) return;
  const opcion = opcionesEmpleados.value.find((o) => o.value === employeeId);
  if (!opcion || lineas.value.some((l) => l.employee_id === employeeId)) return;
  lineas.value.push({
    employee_id: employeeId,
    nombre: opcion.label,
    event_type: 'PRESENT',
    day_value: '1.00',
    notes: '',
  });
  empleadoAgregar.value = null;
}

// --- envío ---
const enviando = ref(false);
const enviado = ref(false);

const puedeEnviar = computed(
  () =>
    lineas.value.length > 0 &&
    lineas.value.every((l) => !requiereDetalle(l.event_type) || l.notes.trim().length > 0),
);

async function enviarReporte() {
  if (!puedeEnviar.value) return;
  enviando.value = true;
  try {
    const res = await submitCrewReport(crewId, {
      lines: lineas.value.map((l) => ({
        employee_id: l.employee_id,
        event_type: l.event_type,
        day_value: l.day_value,
        ...(l.notes.trim() ? { notes: l.notes.trim() } : {}),
      })),
      ...(laborCodigo.value.trim() ? { labor_code: laborCodigo.value.trim() } : {}),
      ...(laborNombre.value.trim() ? { labor_name: laborNombre.value.trim() } : {}),
      ...(zona.value.trim() ? { zone_label: zona.value.trim() } : {}),
      ...(notas.value.trim() ? { notes: notas.value.trim() } : {}),
    });
    enviado.value = true;
    $q.notify({
      type: 'positive',
      message: `Reporte #${res.id} enviado (${lineas.value.length} trabajadores).`,
    });
  } catch (e) {
    // 400 típico: reporte ya enviado/revisado (no se puede reenviar desde ese estado).
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo enviar el reporte.') });
  } finally {
    enviando.value = false;
  }
}

onMounted(async () => {
  cargandoEmpleados.value = true;
  try {
    opcionesEmpleados.value = await cargarOpcionesEmpleados();
  } catch {
    $q.notify({ type: 'warning', message: 'No se pudo cargar el personal de RH.' });
  } finally {
    cargandoEmpleados.value = false;
  }
});
</script>

<style scoped>
.rcuad-linea {
  align-items: flex-start;
}
</style>
