<template>
  <q-select
    :model-value="modelValue"
    :options="opciones"
    :label="label ?? 'Artículo'"
    outlined
    dense
    use-input
    clearable
    emit-value
    map-options
    input-debounce="350"
    :loading="buscando"
    @update:model-value="onSelect"
    @filter="filtrar"
  >
    <template #option="scope">
      <q-item v-bind="scope.itemProps">
        <q-item-section>
          <q-item-label>{{ scope.opt.label }}</q-item-label>
          <q-item-label caption>{{ scope.opt.caption }}</q-item-label>
        </q-item-section>
      </q-item>
    </template>
    <template #no-option>
      <q-item>
        <q-item-section class="text-muted">Sin coincidencias. Escribí para buscar.</q-item-section>
      </q-item>
    </template>
  </q-select>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { listItems, type InventoryItem } from 'src/modules/inventory/api';

defineProps<{
  modelValue: number | null;
  label?: string;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: number | null];
  /** El artículo completo elegido (o null al limpiar). */
  selected: [item: InventoryItem | null];
}>();

interface Opcion {
  label: string;
  value: number;
  caption: string;
}

const opciones = ref<Opcion[]>([]);
const buscando = ref(false);
const porId = new Map<number, InventoryItem>();

function filtrar(input: string, update: (fn: () => void) => void, abort: () => void) {
  buscando.value = true;
  listItems({ search: input.trim(), is_active: true })
    .then((rows) => {
      update(() => {
        porId.clear();
        for (const it of rows) porId.set(it.id, it);
        opciones.value = rows.map((it) => ({
          label: it.name,
          value: it.id,
          caption: [it.sku, it.barcode ? `Cód. ${it.barcode}` : ''].filter(Boolean).join(' · '),
        }));
      });
    })
    .catch(() => abort())
    .finally(() => {
      buscando.value = false;
    });
}

function onSelect(value: number | null) {
  emit('update:modelValue', value);
  emit('selected', value != null ? (porId.get(value) ?? null) : null);
}
</script>
