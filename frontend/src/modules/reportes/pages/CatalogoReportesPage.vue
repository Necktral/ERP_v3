<template>
  <q-page class="app-page">
    <PageHeader
      title="Catálogo de reportes"
      subtitle="Datasets certificados del kernel de reporting: ejecutalos con filtros, exportá el resultado y guardá vistas."
      :loading="cargando"
      @refresh="cargarCatalogo"
    />

    <div class="cat-toolbar">
      <q-input
        v-model="busqueda"
        dense
        outlined
        clearable
        debounce="150"
        label="Buscar reporte"
        class="cat-toolbar__buscar"
      >
        <template #prepend><q-icon name="search" /></template>
      </q-input>
    </div>

    <q-table
      class="app-table"
      :rows="catalogoFiltrado"
      :columns="columns"
      row-key="dataset_key"
      flat
      :loading="cargando"
      :pagination="{ rowsPerPage: 25 }"
      no-data-label="No hay reportes disponibles (o sin permiso)."
    >
      <template #body-cell-reporte="props">
        <q-td :props="props">
          <div class="cat-nombre">{{ datasetTitle(props.row.dataset_key, props.row.title) }}</div>
          <div class="cat-desc">{{ props.row.description }}</div>
          <div class="cat-key">{{ props.row.dataset_key }}</div>
        </q-td>
      </template>
      <template #body-cell-dominio="props">
        <q-td :props="props">
          <q-chip dense square size="sm" color="grey-3" text-color="grey-9">
            {{ props.row.domain_owner }}
          </q-chip>
        </q-td>
      </template>
      <template #body-cell-alcance="props">
        <q-td :props="props">
          {{ props.row.scope_level === 'BRANCH' ? 'Sucursal' : 'Empresa' }}
        </q-td>
      </template>
      <template #body-cell-frescura="props">
        <q-td :props="props">
          {{ FRESHNESS_LABELS[props.row.freshness_mode] ?? props.row.freshness_mode }}
        </q-td>
      </template>
      <template #body-cell-certificado="props">
        <q-td :props="props">
          <q-icon
            :name="props.row.is_certified ? 'verified' : 'pending'"
            :color="props.row.is_certified ? 'secondary' : 'grey-6'"
            size="18px"
          >
            <q-tooltip>{{ props.row.is_certified ? 'Certificado' : props.row.status }}</q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props">
          <q-btn
            dense
            no-caps
            unelevated
            color="primary"
            icon="play_arrow"
            label="Ejecutar"
            :disable="!puedeEjecutar"
            @click="abrirEjecucion(props.row)"
          >
            <q-tooltip v-if="!puedeEjecutar">Requiere permiso report.dataset.read</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Ejecución del dataset: filtros → envelope (totales + filas + warnings) → export -->
    <q-dialog v-model="dialogoAbierto" @hide="cerrarEjecucion">
      <q-card v-if="datasetActivo" class="cat-run-card">
        <q-card-section class="cat-run-head">
          <div>
            <div class="cat-nombre">
              {{ datasetTitle(datasetActivo.dataset_key, datasetActivo.title) }}
            </div>
            <div class="cat-desc">{{ datasetActivo.description }}</div>
          </div>
          <q-chip
            v-if="resultado"
            dense
            square
            size="sm"
            :color="qualityColor(resultado.quality_status)"
            text-color="white"
            :label="qualityLabel(resultado.quality_status)"
          />
          <q-btn v-close-popup flat round dense icon="close" aria-label="Cerrar" />
        </q-card-section>
        <q-separator />

        <q-card-section class="cat-run-filtros">
          <FiltrosDataset v-model="filtros" :schema="datasetActivo.filters_schema" />
          <div class="cat-run-acciones">
            <q-btn
              no-caps
              unelevated
              color="primary"
              icon="play_arrow"
              label="Ejecutar"
              :loading="ejecutando"
              @click="ejecutar"
            />
            <q-btn
              v-if="puedeGuardarVista"
              flat
              no-caps
              icon="bookmark_add"
              label="Guardar vista"
              :disable="ejecutando"
              @click="guardarVista"
            />
          </div>
          <!-- Vistas guardadas del dataset: aplicar una re-carga sus filtros (detalle) y ejecuta -->
          <div v-if="vistas.length" class="cat-run-vistas">
            <q-chip
              v-for="v in vistas"
              :key="v.view_id"
              dense
              clickable
              size="sm"
              icon="bookmark"
              color="grey-3"
              text-color="grey-9"
              @click="aplicarVista(v)"
            >
              {{ v.name }}
              <q-tooltip>Aplicar filtros de esta vista{{ v.is_shared ? ' (compartida)' : '' }}</q-tooltip>
            </q-chip>
          </div>
        </q-card-section>
        <q-separator />

        <q-card-section v-if="errorEjecucion" class="cat-run-error">
          <q-icon name="error_outline" size="18px" /> {{ errorEjecucion }}
        </q-card-section>

        <template v-if="resultado">
          <q-card-section v-if="warningsLegibles.length" class="cat-run-warnings">
            <div v-for="(w, i) in warningsLegibles" :key="i" class="cat-run-warnings__item">
              <q-icon name="warning_amber" size="16px" /> {{ w }}
            </div>
          </q-card-section>

          <q-card-section v-if="totales.length" class="cat-run-kpis">
            <div v-for="t in totales" :key="t[0]" class="cat-kpi">
              <div class="cat-kpi__label">{{ pretty(t[0]) }}</div>
              <div class="cat-kpi__value">{{ fmtValor(t[1], esMoneda) }}</div>
            </div>
          </q-card-section>

          <q-markup-table v-if="resultado.rows.length" flat dense class="cat-run-tabla">
            <thead>
              <tr>
                <th v-for="c in columnasResultado" :key="c" class="text-left">{{ pretty(c) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in resultado.rows" :key="i">
                <td v-for="c in columnasResultado" :key="c">
                  {{ fmtValor(row[c], esMoneda && medidas.has(c)) }}
                </td>
              </tr>
            </tbody>
          </q-markup-table>
          <q-card-section v-else class="cat-run-vacio">
            Sin filas para los filtros elegidos.
          </q-card-section>

          <q-card-section v-if="puedeExportar" class="cat-run-export">
            <q-btn
              v-for="f in datasetActivo.export_capabilities"
              :key="f"
              flat
              dense
              no-caps
              size="sm"
              icon="download"
              :label="f.toUpperCase()"
              :disable="!resultado.run_id || exportando"
              @click="exportar(f)"
            />
            <q-chip
              v-if="exportActual"
              dense
              square
              size="sm"
              :color="estiloExport.color"
              :text-color="estiloExport.textColor ?? 'white'"
              :outline="estiloExport.outline"
            >
              {{ exportActual.file_name }} · {{ estiloExport.label }}
              <template v-if="exportActual.status === 'SUCCEEDED'">
                · {{ exportActual.file_size }} bytes
              </template>
            </q-chip>
            <q-spinner v-if="exportando" size="18px" color="primary" />
          </q-card-section>
        </template>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';
import FiltrosDataset from 'src/modules/reportes/components/FiltrosDataset.vue';
import {
  createRunExport,
  createSavedView,
  getExportDetail,
  getSavedViewDetail,
  listCatalog,
  listSavedViews,
  runDataset,
  type CatalogEntry,
  type DatasetEnvelope,
  type ExportFormato,
  type ExportResult,
  type SavedView,
} from 'src/modules/reportes/api';
import {
  datasetTitle,
  EXPORT_ESTADOS,
  FRESHNESS_LABELS,
  fmtValor,
  pretty,
  qualityColor,
  qualityLabel,
} from 'src/modules/reportes/labels';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

function hasPerm(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

// Permisos exactos de las views del kernel reporting (permissions/rbac_permission).
const puedeEjecutar = computed(() => hasPerm('report.dataset.read'));
const puedeExportar = computed(() => hasPerm('report.dataset.export'));
const puedeVerVistas = computed(() => hasPerm('report.dashboard.read'));
const puedeGuardarVista = computed(() => hasPerm('report.dashboard.compose'));

// --- Catálogo -------------------------------------------------------------
const catalogo = ref<CatalogEntry[]>([]);
const cargando = ref(false);
const busqueda = ref('');

const columns: QTableColumn<CatalogEntry>[] = [
  { name: 'reporte', label: 'Reporte', field: 'title', align: 'left' },
  { name: 'dominio', label: 'Dominio', field: 'domain_owner', align: 'left' },
  { name: 'alcance', label: 'Alcance', field: 'scope_level', align: 'left' },
  { name: 'frescura', label: 'Frescura', field: 'freshness_mode', align: 'left' },
  { name: 'certificado', label: 'Certificado', field: 'is_certified', align: 'center' },
  { name: 'acciones', label: '', field: 'dataset_key', align: 'right' },
];

const catalogoFiltrado = computed(() => {
  const q = (busqueda.value ?? '').trim().toLowerCase();
  if (!q) return catalogo.value;
  return catalogo.value.filter((c) =>
    [datasetTitle(c.dataset_key, c.title), c.dataset_key, c.description, c.domain_owner]
      .join(' ')
      .toLowerCase()
      .includes(q),
  );
});

async function cargarCatalogo() {
  cargando.value = true;
  try {
    catalogo.value = await listCatalog();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el catálogo.') });
  } finally {
    cargando.value = false;
  }
}

// --- Ejecución ------------------------------------------------------------
const dialogoAbierto = ref(false);
const datasetActivo = ref<CatalogEntry | null>(null);
const filtros = ref<Record<string, unknown>>({});
const resultado = ref<DatasetEnvelope | null>(null);
const ejecutando = ref(false);
const errorEjecucion = ref('');
const vistas = ref<SavedView[]>([]);

const esMoneda = computed(() => resultado.value?.render_hints?.numeric_format === 'currency');
const medidas = computed(() => new Set(resultado.value?.measures ?? []));
const totales = computed(() => Object.entries(resultado.value?.totals ?? {}));

// Columnas del resultado: dimensiones + medidas del envelope, más claves extra de las filas.
const columnasResultado = computed(() => {
  const env = resultado.value;
  if (!env) return [];
  const base = [...(env.dimensions ?? []), ...(env.measures ?? [])];
  const extra = new Set<string>();
  for (const row of env.rows ?? []) {
    for (const k of Object.keys(row)) if (!base.includes(k)) extra.add(k);
  }
  return [...base, ...[...extra].sort()];
});

const warningsLegibles = computed(() =>
  (resultado.value?.warnings ?? []).map((w) => (typeof w === 'string' ? w : JSON.stringify(w))),
);

function abrirEjecucion(entry: CatalogEntry) {
  datasetActivo.value = entry;
  filtros.value = {};
  resultado.value = null;
  errorEjecucion.value = '';
  exportActual.value = null;
  vistas.value = [];
  dialogoAbierto.value = true;
  if (puedeVerVistas.value) void cargarVistas(entry.dataset_key);
}

function cerrarEjecucion() {
  // Al salir del diálogo se cancela cualquier poll de export en curso.
  cancelarPoll();
  datasetActivo.value = null;
}

async function ejecutar() {
  const entry = datasetActivo.value;
  if (!entry) return;
  ejecutando.value = true;
  errorEjecucion.value = '';
  exportActual.value = null;
  try {
    resultado.value = await runDataset(entry.dataset_key, filtros.value);
  } catch (e) {
    resultado.value = null;
    errorEjecucion.value = apiErrorMessage(e, 'No se pudo ejecutar el reporte.');
  } finally {
    ejecutando.value = false;
  }
}

// --- Vistas guardadas (listado + detalle; el backend no expone DELETE) -----
async function cargarVistas(datasetKey: string) {
  try {
    vistas.value = await listSavedViews(datasetKey);
  } catch {
    vistas.value = []; // sin permiso/vistas: la sección simplemente no aparece
  }
}

async function aplicarVista(v: SavedView) {
  try {
    // Detalle: trae filters/render_state completos y frescos de la vista.
    const detalle = await getSavedViewDetail(v.view_id);
    filtros.value = { ...(detalle.filters ?? {}) };
    await ejecutar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo aplicar la vista.') });
  }
}

function guardarVista() {
  const entry = datasetActivo.value;
  if (!entry) return;
  $q.dialog({
    title: 'Guardar vista',
    message: 'Nombre de la vista (guarda el reporte con los filtros actuales):',
    prompt: { model: '', type: 'text', isValid: (v: string) => v.trim().length > 0 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'primary', label: 'Guardar' },
  }).onOk((nombre: string) => {
    void (async () => {
      try {
        await createSavedView({
          name: nombre.trim(),
          dataset_key: entry.dataset_key,
          filters: { ...filtros.value },
        });
        $q.notify({ type: 'positive', message: 'Vista guardada.' });
        await cargarVistas(entry.dataset_key);
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo guardar la vista.') });
      }
    })();
  });
}

// --- Export con poll ------------------------------------------------------
const exportActual = ref<ExportResult | null>(null);
const exportando = ref(false);
// Control del poll en curso: cancelable al cerrar el diálogo o salir de la página.
let pollCancelado = false;
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let pollDespertar: (() => void) | null = null;

const estiloExport = computed(
  () =>
    EXPORT_ESTADOS[exportActual.value?.status ?? ''] ?? {
      label: exportActual.value?.status ?? '',
      color: 'grey-7',
      outline: true,
    },
);

function cancelarPoll() {
  pollCancelado = true;
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  // Despierta el await del backoff para que el loop vea la cancelación y termine.
  if (pollDespertar) {
    pollDespertar();
    pollDespertar = null;
  }
  exportando.value = false;
}

function esperar(ms: number): Promise<void> {
  return new Promise((resolve) => {
    pollDespertar = resolve;
    pollTimer = setTimeout(() => {
      pollTimer = null;
      pollDespertar = null;
      resolve();
    }, ms);
  });
}

/**
 * Poll del export hasta que deje de estar PENDING, con backoff exponencial
 * (1s, 2s, 4s... tope 30s) y `background: true` para que un 403 transitorio
 * no saque al usuario de la página. Se cancela al cerrar el diálogo/página.
 */
async function pollExport(exportId: string) {
  pollCancelado = false;
  let espera = 1_000;
  const TOPE = 30_000;
  const MAX_INTENTOS = 20;
  for (let intento = 0; intento < MAX_INTENTOS; intento++) {
    await esperar(espera);
    if (pollCancelado) return;
    try {
      const det = await getExportDetail(exportId, { background: true });
      if (pollCancelado) return;
      exportActual.value = det;
      if (det.status !== 'PENDING') {
        exportando.value = false;
        $q.notify({
          type: det.status === 'SUCCEEDED' ? 'positive' : 'negative',
          message:
            det.status === 'SUCCEEDED'
              ? `Export ${det.format.toUpperCase()} listo (${det.file_size} bytes).`
              : `El export falló: ${det.error_detail || 'sin detalle'}.`,
        });
        return;
      }
    } catch {
      /* error transitorio del poll: se reintenta con backoff */
    }
    espera = Math.min(espera * 2, TOPE);
  }
  exportando.value = false;
  $q.notify({ type: 'warning', message: 'El export sigue pendiente; consultalo más tarde.' });
}

async function exportar(format: ExportFormato) {
  const runId = resultado.value?.run_id;
  if (!runId) return;
  cancelarPoll();
  exportando.value = true;
  try {
    exportActual.value = await createRunExport(runId, format);
    await pollExport(exportActual.value.export_id);
  } catch (e) {
    exportando.value = false;
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo exportar.') });
  }
}

onBeforeUnmount(cancelarPoll);
onMounted(cargarCatalogo);
</script>

<style scoped>
.cat-toolbar {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-4);
}

.cat-toolbar__buscar {
  width: 320px;
}

.cat-nombre {
  font-family: 'Manrope', 'IBM Plex Sans', sans-serif;
  font-weight: 800;
  color: var(--app-text);
}

.cat-desc {
  color: var(--app-text-muted);
  font-size: 0.82rem;
  white-space: normal;
  max-width: 420px;
}

.cat-key {
  color: var(--app-text-muted);
  font-size: 0.72rem;
  font-family: monospace;
}

.cat-run-card {
  width: 960px;
  max-width: 95vw;
  border-radius: var(--app-radius-md);
  background: var(--app-surface-strong);
}

.cat-run-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}

.cat-run-filtros {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.cat-run-acciones {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}

.cat-run-vistas {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-2);
}

.cat-run-error {
  color: var(--app-negative, #c10015);
  font-size: 0.85rem;
}

.cat-run-warnings {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  color: var(--q-warning, #f2c037);
  font-size: 0.82rem;
}

.cat-run-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--app-space-3);
}

.cat-kpi {
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
}

.cat-kpi__label {
  font-size: 0.74rem;
  color: var(--app-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.cat-kpi__value {
  font-family: 'Manrope', 'IBM Plex Sans', sans-serif;
  font-weight: 800;
  font-size: 1.15rem;
  color: var(--app-text);
}

.cat-run-tabla {
  background: transparent;
  max-height: 45vh;
  overflow: auto;
}

.cat-run-vacio {
  color: var(--app-text-muted);
  font-size: 0.85rem;
}

.cat-run-export {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  border-top: 1px solid var(--app-border);
}
</style>
