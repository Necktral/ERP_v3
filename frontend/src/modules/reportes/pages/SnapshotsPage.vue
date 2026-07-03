<template>
  <q-page class="app-page">
    <PageHeader
      title="Snapshots de reportes"
      subtitle="Materializaciones persistidas de los datasets: qué corte existe, hasta cuándo está fresco y su versión."
      :loading="loading"
      @refresh="reload"
    >
      <template #actions>
        <q-btn
          v-if="puedeGenerar"
          no-caps
          unelevated
          color="primary"
          icon="photo_camera"
          label="Generar snapshot"
          @click="abrirGenerar"
        />
      </template>
    </PageHeader>

    <div class="snap-filtros">
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
        class="snap-filtros__dataset"
        @filter="filtrarDatasets"
        @update:model-value="reload"
      />
      <q-select
        v-model="estado"
        :options="opcionesEstado"
        dense
        outlined
        emit-value
        map-options
        clearable
        label="Estado"
        class="snap-filtros__estado"
        @update:model-value="reload"
      />
    </div>

    <q-table
      v-model:pagination="pagination"
      class="app-table"
      :rows="snapshots"
      :columns="columns"
      row-key="snapshot_id"
      flat
      :loading="loading"
      :rows-per-page-options="[25, 50, 100]"
      no-data-label="Sin snapshots materializados."
      @request="onRequest"
    >
      <template #body-cell-dataset="props">
        <q-td :props="props">
          <div>{{ datasetTitle(props.row.dataset_key) }}</div>
          <div class="snap-key">{{ props.row.dataset_key }}</div>
        </q-td>
      </template>
      <template #body-cell-estado="props">
        <q-td :props="props">
          <EstadoChip :estado="props.row.status" :map="SNAPSHOT_ESTADOS" />
        </q-td>
      </template>
      <template #body-cell-fresco="props">
        <q-td :props="props">{{ formatDateTime(props.row.fresh_until) }}</q-td>
      </template>
      <template #body-cell-creado="props">
        <q-td :props="props">{{ formatDateTime(props.row.created_at) }}</q-td>
      </template>
      <template #body-cell-version="props">
        <q-td :props="props">
          {{ props.row.schema_version || '—' }} / {{ props.row.semantic_version || '—' }}
        </q-td>
      </template>
    </q-table>

    <!-- Generar snapshot: dataset materializable + filtros de su schema + refresh forzado -->
    <q-dialog v-model="generarAbierto">
      <q-card class="snap-gen-card">
        <q-card-section class="snap-gen-head">
          <div class="snap-gen-titulo">Generar snapshot</div>
          <q-btn v-close-popup flat round dense icon="close" aria-label="Cerrar" />
        </q-card-section>
        <q-separator />

        <q-card-section class="snap-gen-body">
          <q-select
            v-model="genDatasetKey"
            :options="opcionesGenerables"
            dense
            outlined
            emit-value
            map-options
            label="Dataset *"
            hint="Solo datasets con materialización (los LIVE_ONLY no snapshotean)."
          />
          <FiltrosDataset
            v-if="genSchema"
            v-model="genFiltros"
            :schema="genSchema"
          />
          <q-toggle v-model="genForzar" dense label="Forzar refresh (ignora el snapshot fresco)" />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn v-close-popup flat no-caps label="Cancelar" />
          <q-btn
            no-caps
            unelevated
            color="primary"
            icon="photo_camera"
            label="Generar"
            :loading="generando"
            :disable="!genDatasetKey"
            @click="generar"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import EstadoChip from 'src/components/EstadoChip.vue';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { formatDateTime } from 'src/core/format';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';
import FiltrosDataset from 'src/modules/reportes/components/FiltrosDataset.vue';
import {
  generateSnapshot,
  listCatalog,
  listSnapshots,
  type CatalogEntry,
  type SnapshotRow,
} from 'src/modules/reportes/api';
import { datasetTitle, SNAPSHOT_ESTADOS } from 'src/modules/reportes/labels';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

// Permiso exacto de SnapshotGenerateView: report.snapshot.generate.
const puedeGenerar = computed(() => {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, 'report.snapshot.generate') : false;
});

const datasetKey = ref<string | null>(null);
const estado = ref<string | null>(null);

const opcionesEstado = Object.entries(SNAPSHOT_ESTADOS).map(([value, e]) => ({
  value,
  label: e.label,
}));

// Snapshots paginados SERVER-SIDE: envelope {count, limit, offset, results}.
const { rows: snapshots, loading, pagination, onRequest, reload } = useListadoServer<SnapshotRow>(
  (page) =>
    listSnapshots(
      {
        ...(datasetKey.value ? { dataset_key: datasetKey.value } : {}),
        ...(estado.value ? { status: estado.value } : {}),
      },
      page,
    ),
  { errorMessage: 'No se pudieron cargar los snapshots.', rowsPerPage: 25 },
);

const columns: QTableColumn<SnapshotRow>[] = [
  { name: 'snapshot_id', label: '#', field: 'snapshot_id', align: 'left' },
  { name: 'dataset', label: 'Reporte', field: 'dataset_key', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'fresco', label: 'Fresco hasta', field: 'fresh_until', align: 'left' },
  { name: 'row_count', label: 'Filas', field: 'row_count', align: 'right' },
  { name: 'version', label: 'Versión', field: 'schema_version', align: 'left' },
  { name: 'creado', label: 'Creado', field: 'created_at', align: 'left' },
];

// --- Catálogo para filtros/generación (degrada sin permiso de catálogo) ----
const catalogo = ref<CatalogEntry[]>([]);
const datasetsConocidos = computed(() =>
  catalogo.value.map((c) => ({
    value: c.dataset_key,
    label: `${datasetTitle(c.dataset_key, c.title)} (${c.dataset_key})`,
  })),
);
const opcionesDataset = ref<{ value: string; label: string }[]>([]);

function filtrarDatasets(input: string, update: (fn: () => void) => void) {
  update(() => {
    const q = input.trim().toLowerCase();
    opcionesDataset.value = q
      ? datasetsConocidos.value.filter((o) => o.label.toLowerCase().includes(q))
      : datasetsConocidos.value;
  });
}

// --- Generación ------------------------------------------------------------
const generarAbierto = ref(false);
const generando = ref(false);
const genDatasetKey = ref<string | null>(null);
const genFiltros = ref<Record<string, unknown>>({});
const genForzar = ref(false);

// Solo datasets materializables: LIVE_ONLY responde 400 en snapshots/generate.
const opcionesGenerables = computed(() =>
  catalogo.value
    .filter((c) => c.materialization_policy !== 'LIVE_ONLY')
    .map((c) => ({
      value: c.dataset_key,
      label: `${datasetTitle(c.dataset_key, c.title)} (${c.dataset_key})`,
    })),
);

const genSchema = computed(
  () => catalogo.value.find((c) => c.dataset_key === genDatasetKey.value)?.filters_schema ?? null,
);

watch(genDatasetKey, () => {
  genFiltros.value = {}; // el schema de filtros cambia con el dataset
});

function abrirGenerar() {
  genDatasetKey.value = null;
  genFiltros.value = {};
  genForzar.value = false;
  generarAbierto.value = true;
}

async function generar() {
  if (!genDatasetKey.value) return;
  generando.value = true;
  try {
    const out = await generateSnapshot(genDatasetKey.value, genFiltros.value, {
      forceRefresh: genForzar.value,
    });
    $q.notify({
      type: 'positive',
      message: `Snapshot #${out.snapshot_id} generado (${out.row_count} filas).`,
    });
    generarAbierto.value = false;
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo generar el snapshot.') });
  } finally {
    generando.value = false;
  }
}

onMounted(async () => {
  try {
    // Con report.catalog.read los selects ofrecen títulos legibles; sin él, degrada.
    catalogo.value = await listCatalog();
  } catch {
    catalogo.value = [];
  }
  opcionesDataset.value = datasetsConocidos.value;
});
</script>

<style scoped>
.snap-filtros {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-4);
}

.snap-filtros__dataset {
  width: 380px;
}

.snap-filtros__estado {
  width: 180px;
}

.snap-key {
  color: var(--app-text-muted);
  font-size: 0.72rem;
  font-family: monospace;
}

.snap-gen-card {
  width: 640px;
  max-width: 95vw;
  border-radius: var(--app-radius-md);
  background: var(--app-surface-strong);
}

.snap-gen-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.snap-gen-titulo {
  font-family: 'Manrope', 'IBM Plex Sans', sans-serif;
  font-weight: 800;
  color: var(--app-text);
}

.snap-gen-body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}
</style>
