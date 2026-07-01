<template>
  <q-page class="app-page">
    <PageHeader
      title="Reportes de finca"
      subtitle="Costo por lote/labor, costo real y conciliación de campo. Elegí el reporte y los filtros."
      :loading="cargando"
      @refresh="cargar"
    >
      <template #actions>
        <BackButton to="/finca" />
      </template>
    </PageHeader>

    <div class="rep-filtros">
      <q-select
        v-model="reporte"
        :options="opcionesReporte"
        dense
        outlined
        emit-value
        map-options
        label="Reporte"
        class="rep-filtros__rep"
        @update:model-value="cargar"
      />
      <q-select
        v-if="needsFinca"
        v-model="fincaId"
        :options="opcionesFinca"
        dense
        outlined
        emit-value
        map-options
        clearable
        label="Finca"
        class="rep-filtros__sel"
        @update:model-value="cargar"
      />
      <q-input v-model="season" dense outlined label="Ciclo (opcional)" class="rep-filtros__season" @keyup.enter="cargar" />
      <q-btn unelevated no-caps color="primary" icon="play_arrow" label="Ver" @click="cargar" />
    </div>

    <q-banner v-if="needsFinca && fincaId == null" class="rep-aviso" rounded>
      <template #avatar><q-icon name="info" color="primary" /></template>
      Este reporte requiere elegir una finca.
    </q-banner>
    <DataReport v-else :data="data" />
  </q-page>
</template>

<script setup lang="ts">
import BackButton from 'src/components/BackButton.vue';
import DataReport from 'src/components/DataReport.vue';
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import {
  FINCA_REPORTS,
  getFincaReport,
  listFincas,
  type FincaReportKey,
  type FincaRow,
} from 'src/modules/finca/api';

const $q = useQuasar();

const fincas = ref<FincaRow[]>([]);
const reporte = ref<FincaReportKey>('company-cost');
const fincaId = ref<number | null>(null);
const season = ref('');
const cargando = ref(false);
const data = ref<Record<string, unknown> | null>(null);

const opcionesReporte = FINCA_REPORTS.map((r) => ({ value: r.key, label: r.label }));
const opcionesFinca = computed(() =>
  fincas.value.map((f) => ({ value: Number(f.finca_id), label: (f.name as string) ?? `#${f.finca_id}` })),
);
const needsFinca = computed(() => FINCA_REPORTS.find((r) => r.key === reporte.value)?.needsFinca ?? false);

async function cargar() {
  if (needsFinca.value && fincaId.value == null) {
    data.value = null;
    return;
  }
  cargando.value = true;
  try {
    data.value = await getFincaReport(reporte.value, {
      ...(fincaId.value ? { finca_id: fincaId.value } : {}),
      ...(season.value ? { season: season.value } : {}),
    });
  } catch (e) {
    data.value = null;
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el reporte.') });
  } finally {
    cargando.value = false;
  }
}

onMounted(async () => {
  try {
    fincas.value = await listFincas();
  } catch {
    /* sin fincas */
  }
  await cargar();
});
</script>

<style scoped>
.rep-filtros {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-5);
}
.rep-filtros__rep {
  width: 300px;
}
.rep-filtros__sel {
  width: 220px;
}
.rep-filtros__season {
  width: 160px;
}
.rep-aviso {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  color: var(--app-text-muted);
}
</style>
