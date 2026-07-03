<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton to="/financiamiento" />
    </div>
    <PageHeader
      title="Productores"
      subtitle="Ficha de cada productor de café (carnet de acopio). El depósito muestra el café recibido, fijado y en custodia."
      :loading="loading"
      @refresh="reload"
    >
      <template #actions>
        <q-btn unelevated no-caps color="primary" icon="add" label="Nuevo productor" @click="abrirAlta" />
      </template>
    </PageHeader>

    <q-input v-model="filtro" outlined dense clearable debounce="200" placeholder="Buscar por nombre o código…" class="q-mb-md" style="max-width: 420px">
      <template #prepend><q-icon name="search" /></template>
    </q-input>

    <!-- módulo dormido: carga completa client-side a propósito; revisar si el módulo se activa -->
    <q-table
      :rows="filtradas"
      :columns="cols"
      row-key="id"
      flat
      bordered
      :loading="loading"
      :pagination="{ rowsPerPage: 20 }"
      no-data-label="Aún no hay productores. Creá el primero con «Nuevo productor»."
    >
      <template #body-cell-acciones="props">
        <q-td :props="props">
          <q-btn flat dense no-caps size="sm" icon="account_balance_wallet" label="Depósito" @click="verDeposito(props.row)" />
        </q-td>
      </template>
    </q-table>

    <!-- Alta de productor -->
    <q-dialog v-model="altaOpen">
      <q-card class="app-dialog" style="min-width: 380px">
        <q-card-section class="text-h6">Nuevo productor</q-card-section>
        <q-card-section class="q-gutter-md">
          <PartySelect v-model="form.party_id" label="Tercero (productor) *" />
          <q-input v-model="form.acopio_code" outlined dense label="Código de acopio" />
          <q-input v-model="form.certifications" outlined dense label="Certificaciones (ej. orgánico, FT)" />
          <q-input v-model="form.notes" outlined dense type="textarea" autogrow label="Notas" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Crear" :loading="guardando" :disable="!form.party_id" @click="guardar" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Depósito del productor -->
    <q-dialog v-model="depOpen">
      <q-card class="app-dialog" style="min-width: 320px">
        <q-card-section class="text-h6">Depósito de café · {{ depProducer?.party_name }}</q-card-section>
        <q-card-section v-if="dep">
          <div class="dep-row"><span>Recibido (lb)</span><b>{{ dep.received_lb }}</b></div>
          <div class="dep-row"><span>Fijado (lb)</span><b>{{ dep.fixed_lb }}</b></div>
          <div class="dep-row"><span>Liquidado (lb)</span><b>{{ dep.liquidated_lb }}</b></div>
          <q-separator class="q-my-sm" />
          <div class="dep-row dep-row--hi"><span>Disponible para fijar (lb)</span><b>{{ dep.available_to_fix_lb }}</b></div>
          <div class="dep-row dep-row--hi"><span>En custodia (lb)</span><b>{{ dep.in_custody_lb }}</b></div>
        </q-card-section>
        <q-card-section v-else class="text-muted">Cargando…</q-card-section>
        <q-card-actions align="right"><q-btn flat no-caps label="Cerrar" v-close-popup /></q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import PartySelect from 'src/modules/parties/components/PartySelect.vue';
import { useListado } from 'src/core/composables/useListado';
import { apiErrorMessage } from 'src/core/api';
import {
  createProducer,
  listProducers,
  producerDeposit,
  type ProducerDeposit,
  type ProducerRow,
} from 'src/modules/financiamiento/api';

const $q = useQuasar();
const { rows, loading, reload } = useListado<ProducerRow>(listProducers);

const filtro = ref('');
const filtradas = computed(() => {
  const q = filtro.value.trim().toLowerCase();
  if (!q) return rows.value;
  return rows.value.filter(
    (r) =>
      r.party_name.toLowerCase().includes(q) ||
      r.acopio_code.toLowerCase().includes(q) ||
      r.national_id.toLowerCase().includes(q),
  );
});

const cols: QTableColumn<ProducerRow>[] = [
  { name: 'acopio_code', label: 'Código', field: 'acopio_code', align: 'left', sortable: true },
  { name: 'party_name', label: 'Productor', field: 'party_name', align: 'left', sortable: true },
  { name: 'national_id', label: 'Cédula', field: 'national_id', align: 'left' },
  { name: 'certifications', label: 'Certificaciones', field: 'certifications', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

const altaOpen = ref(false);
const guardando = ref(false);
const form = ref({ party_id: null as number | null, acopio_code: '', certifications: '', notes: '' });

function abrirAlta() {
  form.value = { party_id: null, acopio_code: '', certifications: '', notes: '' };
  altaOpen.value = true;
}

async function guardar() {
  if (!form.value.party_id) return;
  guardando.value = true;
  try {
    await createProducer({
      party_id: form.value.party_id,
      acopio_code: form.value.acopio_code,
      certifications: form.value.certifications,
      notes: form.value.notes,
    });
    $q.notify({ type: 'positive', message: 'Productor creado.' });
    altaOpen.value = false;
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear el productor.') });
  } finally {
    guardando.value = false;
  }
}

const depOpen = ref(false);
const dep = ref<ProducerDeposit | null>(null);
const depProducer = ref<ProducerRow | null>(null);

async function verDeposito(row: ProducerRow) {
  depProducer.value = row;
  dep.value = null;
  depOpen.value = true;
  try {
    dep.value = await producerDeposit(row.id);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el depósito.') });
  }
}
</script>

<style scoped>
.dep-row {
  display: flex;
  justify-content: space-between;
  gap: var(--app-space-4);
  padding: 2px 0;
  font-size: 0.9rem;
}
.dep-row--hi {
  color: var(--app-primary);
  font-weight: 600;
}
</style>
