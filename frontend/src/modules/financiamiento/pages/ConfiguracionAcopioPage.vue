<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton to="/financiamiento" />
    </div>
    <PageHeader
      title="Configuración de acopio"
      subtitle="Define el artículo de café, las bodegas de custodia y liquidación, y el tercero prestamista. Necesario antes de acopiar y liquidar."
      :loading="cargando"
      @refresh="cargar"
    />

    <q-card flat bordered class="app-card" style="max-width: 560px">
      <q-card-section class="q-gutter-md">
        <ItemSelect v-model="form.coffee_item_id" label="Artículo de café (en custodia)" />
        <q-select
          v-model="form.custody_warehouse_id"
          :options="bodegaOpts"
          label="Bodega de custodia"
          outlined
          dense
          clearable
          emit-value
          map-options
          options-dense
        />
        <q-select
          v-model="form.liquidation_warehouse_id"
          :options="bodegaOpts"
          label="Bodega de liquidación"
          outlined
          dense
          clearable
          emit-value
          map-options
          options-dense
        />
        <PartySelect v-model="form.lender_party_id" label="Tercero prestamista" />
      </q-card-section>
      <q-card-actions align="right">
        <q-btn unelevated no-caps color="primary" icon="save" label="Guardar" :loading="guardando" @click="guardar" />
      </q-card-actions>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import ItemSelect from 'src/modules/inventory/components/ItemSelect.vue';
import PartySelect from 'src/modules/parties/components/PartySelect.vue';
import { apiErrorMessage } from 'src/core/api';
import { listWarehouses } from 'src/modules/inventory/api';
import {
  getFinancingSettings,
  updateFinancingSettings,
  type FinancingSettings,
} from 'src/modules/financiamiento/api';

const $q = useQuasar();
const cargando = ref(false);
const guardando = ref(false);
const form = ref<FinancingSettings>({
  coffee_item_id: null,
  custody_warehouse_id: null,
  liquidation_warehouse_id: null,
  lender_party_id: null,
});
const bodegaOpts = ref<{ label: string; value: number }[]>([]);

async function cargar() {
  cargando.value = true;
  try {
    const [settings, whs] = await Promise.all([getFinancingSettings(), listWarehouses()]);
    form.value = settings;
    bodegaOpts.value = whs.filter((w) => w.is_active).map((w) => ({ label: `${w.code} · ${w.name}`, value: w.id }));
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar la configuración.') });
  } finally {
    cargando.value = false;
  }
}

async function guardar() {
  guardando.value = true;
  try {
    await updateFinancingSettings(form.value);
    $q.notify({ type: 'positive', message: 'Configuración guardada.' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo guardar la configuración.') });
  } finally {
    guardando.value = false;
  }
}

onMounted(cargar);
</script>
