<template>
  <q-page class="app-page">
    <PageHeader
      title="Ejecuciones de reportes"
      subtitle="Historial de runs del kernel de reporting: quién corrió qué dataset, con qué filtros, duración y calidad."
      :loading="loading"
      @refresh="reload"
    />

    <div class="run-filtros">
      <q-select
        v-model="datasetKey"
        :options="opcionesDataset"
        dense
        outlined
        emit-value
        map-options
        clearable
        use-input
        input-debounce="150"
        label="Dataset"
        class="run-filtros__dataset"
        @filter="filtrarDatasets"
        @update:model-value="reload"
      />
    </div>

    <q-table
      v-model:pagination="pagination"
      class="app-table"
      :rows="runs"
      :columns="columns"
      row-key="run_id"
      flat
      :loading="loading"
      :rows-per-page-options="[25, 50, 100]"
      no-data-label="Sin ejecuciones registradas."
      @request="onRequest"
      @row-click="(_evt, row) => abrirDetalle(row as RunResumen)"
    >
      <template #body-cell-fecha="props">
        <q-td :props="props">{{ formatDateTime(props.row.created_at) }}</q-td>
      </template>
      <template #body-cell-dataset="props">
        <q-td :props="props">
          <div>{{ datasetTitle(props.row.dataset_key) }}</div>
          <div class="run-key">{{ props.row.dataset_key }}</div>
        </q-td>
      </template>
      <template #body-cell-estado="props">
        <q-td :props="props">
          <EstadoChip :estado="props.row.status" :map="RUN_ESTADOS" />
        </q-td>
      </template>
      <template #body-cell-calidad="props">
        <q-td :props="props">
          <q-chip
            v-if="props.row.quality_status"
            dense
            square
            size="sm"
            :color="qualityColor(props.row.quality_status)"
            text-color="white"
            :label="qualityLabel(props.row.quality_status)"
          />
          <span v-else>—</span>
        </q-td>
      </template>
      <template #body-cell-duracion="props">
        <q-td :props="props">{{ fmtDuracion(props.row.duration_ms) }}</q-td>
      </template>
    </q-table>

    <!-- Detalle del run: estado, calidad, filtros usados, warnings y linaje -->
    <q-dialog v-model="detalleAbierto">
      <q-card class="run-det-card">
        <q-card-section class="run-det-head">
          <div>
            <div class="run-det-titulo">
              {{ detalle ? datasetTitle(detalle.dataset_key) : 'Detalle del run' }}
            </div>
            <div v-if="detalle" class="run-key">{{ detalle.run_id }}</div>
          </div>
          <EstadoChip v-if="detalle" :estado="detalle.status" :map="RUN_ESTADOS" />
          <q-btn v-close-popup flat round dense icon="close" aria-label="Cerrar" />
        </q-card-section>
        <q-separator />

        <q-card-section v-if="cargandoDetalle" class="run-det-cargando">
          <q-spinner size="24px" color="primary" /> Cargando detalle...
        </q-card-section>

        <q-card-section v-else-if="detalle" class="run-det-body">
          <div class="run-det-grid">
            <div class="run-det-item">
              <div class="run-det-item__label">Ejecutado</div>
              <div>{{ formatDateTime(detalle.created_at) }}</div>
            </div>
            <div class="run-det-item">
              <div class="run-det-item__label">Completado</div>
              <div>{{ formatDateTime(detalle.completed_at) }}</div>
            </div>
            <div class="run-det-item">
              <div class="run-det-item__label">Duración</div>
              <div>{{ fmtDuracion(detalle.duration_ms) }}</div>
            </div>
            <div class="run-det-item">
              <div class="run-det-item__label">Filas</div>
              <div>{{ detalle.row_count }}</div>
            </div>
            <div class="run-det-item">
              <div class="run-det-item__label">Calidad</div>
              <div>
                <q-chip
                  v-if="detalle.quality_status"
                  dense
                  square
                  size="sm"
                  :color="qualityColor(detalle.quality_status)"
                  text-color="white"
                  :label="qualityLabel(detalle.quality_status)"
                />
                <span v-else>—</span>
              </div>
            </div>
            <div class="run-det-item">
              <div class="run-det-item__label">Consumidor</div>
              <div>{{ detalle.consumer_type }}{{ detalle.consumer_ref ? ` · ${detalle.consumer_ref}` : '' }}</div>
            </div>
            <div class="run-det-item">
              <div class="run-det-item__label">Versión (schema / semántica)</div>
              <div>{{ detalle.schema_version || '—' }} / {{ detalle.semantic_version || '—' }}</div>
            </div>
            <div class="run-det-item">
              <div class="run-det-item__label">Hash del resultado</div>
              <div class="run-key">{{ detalle.result_hash || '—' }}</div>
            </div>
          </div>

          <div v-if="detalle.error_detail" class="run-det-error">
            <q-icon name="error_outline" size="16px" /> {{ detalle.error_detail }}
          </div>

          <div v-if="filtrosUsados.length" class="run-det-seccion">
            <div class="run-det-seccion__titulo">Filtros usados</div>
            <div class="run-det-chips">
              <q-chip v-for="[k, v] in filtrosUsados" :key="k" dense square size="sm" color="grey-3" text-color="grey-9">
                {{ pretty(k) }}: {{ String(v) }}
              </q-chip>
            </div>
          </div>
          <div v-else class="run-det-seccion run-det-muted">Sin filtros (corrió con el alcance completo).</div>

          <div v-if="warningsLegibles.length" class="run-det-seccion">
            <div class="run-det-seccion__titulo">Advertencias</div>
            <div v-for="(w, i) in warningsLegibles" :key="i" class="run-det-warning">
              <q-icon name="warning_amber" size="14px" /> {{ w }}
            </div>
          </div>

          <div v-if="detalle.quality_checks.length" class="run-det-seccion">
            <div class="run-det-seccion__titulo">Checks de calidad</div>
            <div v-for="(c, i) in detalle.quality_checks" :key="i" class="run-det-check">
              {{ JSON.stringify(c) }}
            </div>
          </div>

          <div v-if="fuentes" class="run-det-seccion">
            <div class="run-det-seccion__titulo">Origen / linaje</div>
            <div class="run-det-check">{{ fuentes }}</div>
          </div>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import EstadoChip from 'src/components/EstadoChip.vue';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { formatDateTime } from 'src/core/format';
import {
  getRunDetail,
  listCatalog,
  listRuns,
  type RunDetalle,
  type RunResumen,
} from 'src/modules/reportes/api';
import { datasetTitle, pretty, qualityColor, qualityLabel, RUN_ESTADOS } from 'src/modules/reportes/labels';

const $q = useQuasar();

const datasetKey = ref<string | null>(null);

// Historial paginado SERVER-SIDE: el backend responde {count, limit, offset, results}.
const { rows: runs, loading, pagination, onRequest, reload } = useListadoServer<RunResumen>(
  (page) => listRuns(datasetKey.value ? { dataset_key: datasetKey.value } : {}, page),
  { errorMessage: 'No se pudo cargar el historial de ejecuciones.', rowsPerPage: 25 },
);

const columns: QTableColumn<RunResumen>[] = [
  { name: 'fecha', label: 'Fecha', field: 'created_at', align: 'left' },
  { name: 'dataset', label: 'Reporte', field: 'dataset_key', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'calidad', label: 'Calidad', field: 'quality_status', align: 'left' },
  { name: 'row_count', label: 'Filas', field: 'row_count', align: 'right' },
  { name: 'duracion', label: 'Duración', field: 'duration_ms', align: 'right' },
];

// Opciones del filtro de dataset: del catálogo si hay permiso; si no, de los runs ya listados.
const datasetsConocidos = ref<{ value: string; label: string }[]>([]);
const opcionesDataset = ref<{ value: string; label: string }[]>([]);

function filtrarDatasets(input: string, update: (fn: () => void) => void) {
  update(() => {
    const q = input.trim().toLowerCase();
    opcionesDataset.value = q
      ? datasetsConocidos.value.filter((o) => o.label.toLowerCase().includes(q))
      : datasetsConocidos.value;
  });
}

function fmtDuracion(ms: number): string {
  if (!ms) return '—';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toLocaleString('es-NI', { maximumFractionDigits: 1 })} s`;
}

// --- Detalle ---------------------------------------------------------------
const detalleAbierto = ref(false);
const cargandoDetalle = ref(false);
const detalle = ref<RunDetalle | null>(null);

const filtrosUsados = computed(() => Object.entries(detalle.value?.filters ?? {}));
const warningsLegibles = computed(() =>
  (detalle.value?.warnings ?? []).map((w) => (typeof w === 'string' ? w : JSON.stringify(w))),
);
const fuentes = computed(() => {
  const lineage = detalle.value?.lineage ?? {};
  const source = detalle.value?.source_summary ?? {};
  const partes: string[] = [];
  const mods = (lineage as { source_modules?: unknown }).source_modules;
  if (Array.isArray(mods) && mods.length) partes.push(`módulos: ${mods.join(', ')}`);
  if (Object.keys(source).length) partes.push(`fuente: ${JSON.stringify(source)}`);
  return partes.join(' · ');
});

async function abrirDetalle(row: RunResumen) {
  detalleAbierto.value = true;
  cargandoDetalle.value = true;
  detalle.value = null;
  try {
    detalle.value = await getRunDetail(row.run_id);
  } catch (e) {
    detalleAbierto.value = false;
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el detalle del run.') });
  } finally {
    cargandoDetalle.value = false;
  }
}

onMounted(async () => {
  try {
    // Con report.catalog.read el filtro ofrece títulos legibles; sin él, degrada sin romper.
    const cat = await listCatalog();
    datasetsConocidos.value = cat.map((c) => ({
      value: c.dataset_key,
      label: `${datasetTitle(c.dataset_key, c.title)} (${c.dataset_key})`,
    }));
  } catch {
    datasetsConocidos.value = [];
  }
  opcionesDataset.value = datasetsConocidos.value;
});
</script>

<style scoped>
.run-filtros {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-4);
}

.run-filtros__dataset {
  width: 380px;
}

.run-key {
  color: var(--app-text-muted);
  font-size: 0.72rem;
  font-family: monospace;
}

.run-det-card {
  width: 760px;
  max-width: 95vw;
  border-radius: var(--app-radius-md);
  background: var(--app-surface-strong);
}

.run-det-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}

.run-det-titulo {
  font-family: 'Roboto', 'Segoe UI', system-ui, sans-serif;
  font-weight: 800;
  color: var(--app-text);
}

.run-det-cargando {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--app-text-muted);
}

.run-det-body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}

.run-det-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: var(--app-space-3);
}

.run-det-item__label {
  font-size: 0.72rem;
  color: var(--app-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.run-det-error {
  color: var(--app-negative, #c10015);
  font-size: 0.85rem;
}

.run-det-seccion__titulo {
  font-weight: 700;
  font-size: 0.82rem;
  color: var(--app-text);
  margin-bottom: var(--app-space-1);
}

.run-det-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-1);
}

.run-det-warning {
  color: var(--q-warning, #f2c037);
  font-size: 0.82rem;
}

.run-det-check {
  font-family: monospace;
  font-size: 0.75rem;
  color: var(--app-text-muted);
  word-break: break-all;
}

.run-det-muted {
  color: var(--app-text-muted);
  font-size: 0.82rem;
}
</style>
