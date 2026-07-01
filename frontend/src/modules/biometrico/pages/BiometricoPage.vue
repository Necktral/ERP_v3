<template>
  <q-page class="app-page">
    <PageHeader
      title="Reloj biométrico"
      subtitle="Registrá el aparato, subí el archivo de marcas que exporta, mapeá cada código a un trabajador y consolidá al período de planilla."
      :loading="loading"
      @refresh="reload"
    />

    <q-tabs v-model="tab" dense no-caps align="left" active-color="primary" indicator-color="primary">
      <q-tab name="aparatos" icon="fingerprint" label="Aparatos" />
      <q-tab name="marcas" icon="how_to_reg" label="Marcas" />
      <q-tab name="consolidar" icon="sync_alt" label="Consolidar" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <q-tab-panels v-model="tab" animated>
      <!-- ===== APARATOS ===== -->
      <q-tab-panel name="aparatos" class="q-pa-none">
        <div class="app-actions">
          <q-btn unelevated no-caps color="primary" icon="add" label="Registrar aparato" @click="abrirNuevoAparato" />
          <span class="text-caption text-muted">
            El aparato exporta un Excel/CSV con las marcas; lo subís en la pestaña «Marcas».
          </span>
        </div>
        <q-table
          class="app-table"
          :rows="devices"
          :columns="deviceCols"
          row-key="id"
          flat
          :loading="loading"
          :pagination="{ rowsPerPage: 25 }"
          no-data-label="Aún no hay aparatos registrados."
        >
          <template #body-cell-is_active="props">
            <q-td :props="props">
              <q-toggle
                :model-value="props.row.is_active"
                color="primary"
                @update:model-value="(v: boolean) => toggleAparato(props.row, v)"
              />
            </q-td>
          </template>
          <template #body-cell-acciones="props">
            <q-td :props="props" class="text-right">
              <q-btn flat dense no-caps size="sm" icon="vpn_key" label="Rotar token" @click="rotarToken(props.row)" />
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <!-- ===== MARCAS ===== -->
      <q-tab-panel name="marcas" class="q-pa-none">
        <q-card flat bordered class="bio-import q-mb-md">
          <q-card-section class="bio-import__row">
            <q-select
              v-model="importDeviceId"
              :options="deviceOpts"
              outlined
              dense
              emit-value
              map-options
              label="Aparato"
              style="min-width: 220px"
            />
            <q-file v-model="archivo" outlined dense label="Archivo del aparato (.xlsx/.csv)" accept=".xlsx,.csv" style="min-width: 280px; flex: 1">
              <template #prepend><q-icon name="upload_file" /></template>
            </q-file>
            <q-btn
              unelevated
              no-caps
              color="primary"
              icon="cloud_upload"
              label="Subir marcas"
              :loading="subiendo"
              :disable="!importDeviceId || !archivo"
              @click="subirArchivo"
            />
          </q-card-section>
        </q-card>

        <div class="app-actions">
          <q-toggle v-model="soloNoMapeadas" label="Solo marcas sin trabajador" @update:model-value="cargarMarcas" />
          <q-btn flat dense round icon="refresh" :loading="cargandoMarcas" aria-label="Actualizar" @click="cargarMarcas" />
        </div>
        <q-table
          class="app-table"
          :rows="checks"
          :columns="checkCols"
          row-key="id"
          flat
          dense
          :loading="cargandoMarcas"
          :pagination="{ rowsPerPage: 50 }"
          no-data-label="Sin marcas. Subí el archivo del aparato."
        >
          <template #body-cell-employee="props">
            <q-td :props="props">
              <span v-if="props.row.employee_name">{{ props.row.employee_name }}</span>
              <q-btn v-else flat dense no-caps size="sm" color="primary" icon="link" label="Mapear" @click="abrirMapeo(props.row)" />
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <!-- ===== CONSOLIDAR ===== -->
      <q-tab-panel name="consolidar" class="q-pa-none">
        <q-card flat bordered class="bio-consol">
          <q-card-section>
            <div class="text-subtitle1">Consolidar marcas al período</div>
            <div class="text-caption text-muted q-mb-md">
              Lleva las marcas del reloj a la asistencia del período (solo períodos en borrador/revisión).
            </div>
            <div class="row items-center q-gutter-sm">
              <q-select
                v-model="periodoId"
                :options="periodoOpts"
                outlined
                dense
                emit-value
                map-options
                label="Período"
                style="min-width: 280px"
              />
              <q-btn
                unelevated
                no-caps
                color="primary"
                icon="sync_alt"
                label="Consolidar"
                :loading="consolidando"
                :disable="!periodoId"
                @click="consolidar"
              />
            </div>
          </q-card-section>
        </q-card>
      </q-tab-panel>
    </q-tab-panels>

    <!-- Diálogo: registrar aparato -->
    <q-dialog v-model="dlgAparato">
      <q-card class="bio-dialog">
        <q-card-section class="text-h6">Registrar aparato</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="formAparato.name" outlined dense autofocus label="Nombre *" />
          <q-input v-model="formAparato.vendor" outlined dense label="Marca / fabricante" />
          <q-input v-model="formAparato.serial" outlined dense label="N° de serie" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Registrar" :loading="guardandoAparato" :disable="!formAparato.name.trim()" @click="crearAparato" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: token de un solo uso -->
    <q-dialog v-model="dlgToken">
      <q-card class="bio-dialog">
        <q-card-section class="text-h6">Token del aparato</q-card-section>
        <q-card-section>
          <div class="text-caption text-muted q-mb-sm">
            Guardá este token AHORA: se muestra una sola vez. El aparato (o el puente) lo usa para empujar marcas.
          </div>
          <q-input :model-value="tokenMostrado" readonly outlined dense>
            <template #append><q-btn flat dense round icon="content_copy" @click="copiarToken" /></template>
          </q-input>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn unelevated no-caps color="primary" label="Listo" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: mapear código → empleado -->
    <q-dialog v-model="dlgMapeo">
      <q-card class="bio-dialog">
        <q-card-section class="text-h6">Mapear marca a un trabajador</q-card-section>
        <q-card-section class="app-form">
          <div class="text-caption text-muted">
            Código del aparato: <b>{{ mapeo.external_code }}</b>
            <span v-if="mapeo.external_name"> · {{ mapeo.external_name }}</span>
          </div>
          <q-select
            v-model="mapeo.employee_id"
            :options="employeeOpts"
            outlined
            dense
            use-input
            input-debounce="0"
            label="Trabajador *"
            :options-dense="true"
            @filter="filtrarEmpleados"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Mapear" :loading="mapeando" :disable="!mapeo.employee_id" @click="confirmarMapeo" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import {
  createDevice,
  importChecks,
  listBatches,
  listChecks,
  listDevices,
  mapCode,
  rollup,
  rotateToken,
  updateDevice,
  type BiometricCheck,
  type BiometricDevice,
} from 'src/modules/biometrico/api';
import { listEmployees, type EmployeeRow } from 'src/modules/hr/api';
import { listPeriods, type PayrollPeriod } from 'src/modules/nomina/api';

const $q = useQuasar();
const tab = ref('aparatos');
const loading = ref(false);

const devices = ref<BiometricDevice[]>([]);
const deviceOpts = computed(() => devices.value.map((d) => ({ label: d.name, value: d.id })));

const deviceCols: QTableColumn<BiometricDevice>[] = [
  { name: 'name', label: 'Aparato', field: 'name', align: 'left' },
  { name: 'vendor', label: 'Marca', field: 'vendor', align: 'left' },
  { name: 'serial', label: 'Serie', field: 'serial', align: 'left' },
  { name: 'last_seen_at', label: 'Última vez', field: (r) => (r.last_seen_at ? r.last_seen_at.slice(0, 16).replace('T', ' ') : '—'), align: 'left' },
  { name: 'is_active', label: 'Activo', field: 'is_active', align: 'center' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

// --- Aparatos ---
const dlgAparato = ref(false);
const guardandoAparato = ref(false);
const formAparato = reactive({ name: '', vendor: '', serial: '' });
const dlgToken = ref(false);
const tokenMostrado = ref('');

function abrirNuevoAparato() {
  formAparato.name = '';
  formAparato.vendor = '';
  formAparato.serial = '';
  dlgAparato.value = true;
}

async function crearAparato() {
  if (!formAparato.name.trim()) return;
  guardandoAparato.value = true;
  try {
    const d = await createDevice({ name: formAparato.name.trim(), vendor: formAparato.vendor.trim(), serial: formAparato.serial.trim() });
    dlgAparato.value = false;
    if (d.api_token) {
      tokenMostrado.value = d.api_token;
      dlgToken.value = true;
    }
    $q.notify({ type: 'positive', message: 'Aparato registrado.' });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo registrar el aparato.') });
  } finally {
    guardandoAparato.value = false;
  }
}

async function toggleAparato(d: BiometricDevice, activo: boolean) {
  try {
    await updateDevice(d.id, { is_active: activo });
    d.is_active = activo;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cambiar el aparato.') });
  }
}

async function rotarToken(d: BiometricDevice) {
  try {
    const res = await rotateToken(d.id);
    if (res.api_token) {
      tokenMostrado.value = res.api_token;
      dlgToken.value = true;
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo rotar el token.') });
  }
}

function copiarToken() {
  void navigator.clipboard?.writeText(tokenMostrado.value);
  $q.notify({ type: 'positive', message: 'Token copiado.' });
}

// --- Marcas (import + ver + mapear) ---
const importDeviceId = ref<number | null>(null);
const archivo = ref<File | null>(null);
const subiendo = ref(false);
const checks = ref<BiometricCheck[]>([]);
const cargandoMarcas = ref(false);
const soloNoMapeadas = ref(true);

const checkCols: QTableColumn<BiometricCheck>[] = [
  { name: 'external_code', label: 'Código aparato', field: 'external_code', align: 'left' },
  { name: 'external_name', label: 'Nombre (aparato)', field: 'external_name', align: 'left' },
  { name: 'employee', label: 'Trabajador', field: 'employee_name', align: 'left' },
  { name: 'direction', label: 'Marca', field: 'direction', align: 'left' },
  { name: 'checked_at', label: 'Fecha/hora', field: (r) => r.checked_at.slice(0, 16).replace('T', ' '), align: 'left' },
  { name: 'work_date', label: 'Día', field: 'work_date', align: 'left' },
];

async function subirArchivo() {
  if (!importDeviceId.value || !archivo.value) return;
  subiendo.value = true;
  try {
    const r = await importChecks(importDeviceId.value, archivo.value);
    $q.notify({
      type: 'positive',
      message: `Importado: ${r.created} nuevas, ${r.duplicates} duplicadas, ${r.unmatched} sin mapear${r.error_count ? `, ${r.error_count} con error` : ''}.`,
    });
    archivo.value = null;
    await cargarMarcas();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo importar el archivo.') });
  } finally {
    subiendo.value = false;
  }
}

async function cargarMarcas() {
  cargandoMarcas.value = true;
  try {
    checks.value = await listChecks({ only_unmatched: soloNoMapeadas.value });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar las marcas.') });
  } finally {
    cargandoMarcas.value = false;
  }
}

// --- Mapeo código → empleado ---
const dlgMapeo = ref(false);
const mapeando = ref(false);
const mapeo = reactive<{ external_code: string; external_name: string; employee_id: number | null }>({
  external_code: '',
  external_name: '',
  employee_id: null,
});
const allEmployees = ref<{ label: string; value: number }[]>([]);
const employeeOpts = ref<{ label: string; value: number }[]>([]);

async function cargarEmpleados() {
  if (allEmployees.value.length) return;
  try {
    const rows = await listEmployees();
    allEmployees.value = rows
      .filter((e: EmployeeRow) => e.is_active)
      .map((e: EmployeeRow) => ({
        label: `${e.first_name} ${e.last_name}`.trim() + (e.employee_code ? ` (${e.employee_code})` : ''),
        value: e.id,
      }));
    employeeOpts.value = allEmployees.value;
  } catch {
    /* noop */
  }
}

function filtrarEmpleados(input: string, update: (fn: () => void) => void) {
  update(() => {
    const q = input.trim().toLowerCase();
    employeeOpts.value = !q ? allEmployees.value : allEmployees.value.filter((o) => o.label.toLowerCase().includes(q));
  });
}

function abrirMapeo(c: BiometricCheck) {
  mapeo.external_code = c.external_code;
  mapeo.external_name = c.external_name;
  mapeo.employee_id = null;
  dlgMapeo.value = true;
  void cargarEmpleados();
}

async function confirmarMapeo() {
  if (!mapeo.employee_id) return;
  mapeando.value = true;
  try {
    const res = await mapCode(mapeo.external_code, mapeo.employee_id);
    dlgMapeo.value = false;
    $q.notify({ type: 'positive', message: `Mapeado. Marcas re-asociadas: ${res.rematched_checks}.` });
    await cargarMarcas();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo mapear.') });
  } finally {
    mapeando.value = false;
  }
}

// --- Consolidar (rollup) ---
const periodos = ref<PayrollPeriod[]>([]);
const periodoId = ref<number | null>(null);
const consolidando = ref(false);
const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
const periodoOpts = computed(() =>
  periodos.value.map((p) => ({ label: `${MESES[p.month - 1]} ${p.year} — ${p.period_type}`, value: p.id })),
);

async function consolidar() {
  if (!periodoId.value) return;
  consolidando.value = true;
  try {
    await rollup(periodoId.value);
    $q.notify({ type: 'positive', message: 'Marcas consolidadas al período.' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo consolidar.') });
  } finally {
    consolidando.value = false;
  }
}

// --- Carga ---
async function reload() {
  loading.value = true;
  try {
    devices.value = await listDevices();
    if (!importDeviceId.value && devices.value.length) importDeviceId.value = devices.value[0]?.id ?? null;
    await Promise.all([cargarMarcas(), cargarPeriodos()]);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el reloj biométrico.') });
  } finally {
    loading.value = false;
  }
}

async function cargarPeriodos() {
  try {
    periodos.value = await listPeriods();
  } catch {
    /* noop */
  }
}

// listBatches disponible para una vista futura de lotes; no se lista aquí para mantener la pantalla simple.
void listBatches;

onMounted(reload);
</script>

<style scoped>
.bio-import__row {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  flex-wrap: wrap;
}
.bio-dialog {
  width: 460px;
  max-width: 94vw;
  background: var(--app-surface-strong);
}
.bio-consol {
  max-width: 560px;
  background: var(--app-surface);
}
</style>
