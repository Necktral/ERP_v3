<template>
  <div>
    <div class="reo-encabezado">
      <div class="text-muted">
        Artículos cuya existencia está por debajo del punto de reorden. La cantidad sugerida
        completa el stock máximo (o el doble del punto de reorden) y el proveedor sugerido es
        el de la última compra.
      </div>
      <q-btn flat dense no-caps icon="refresh" label="Actualizar" :loading="loading" @click="reload" />
    </div>

    <q-table
      v-model:selected="seleccion"
      class="app-table"
      :rows="rows"
      :columns="columns"
      row-key="item_id"
      flat
      selection="multiple"
      :loading="loading"
      :pagination="{ rowsPerPage: 25 }"
      no-data-label="Nada bajo el punto de reorden. Todo el inventario está sano."
    >
      <template #body-cell-existencia="props">
        <q-td :props="props">
          {{ formatQty(props.row.qty_on_hand) }}
          <span class="text-muted">/ mín {{ formatQty(props.row.reorder_point) }}</span>
        </q-td>
      </template>
      <template #body-cell-sugerida="props">
        <q-td :props="props" class="text-weight-bold">{{ formatQty(props.row.suggested_qty) }}</q-td>
      </template>
      <template #body-cell-proveedor="props">
        <q-td :props="props">
          {{ props.row.supplier_display_name || 'sin historial' }}
          <span v-if="props.row.last_cost" class="text-muted">
            · último costo {{ formatMoney(props.row.last_cost) }}
          </span>
        </q-td>
      </template>
    </q-table>

    <div class="reo-acciones">
      <q-btn
        v-if="puedeCrearOC"
        unelevated
        no-caps
        color="primary"
        icon="shopping_cart_checkout"
        :label="`Crear OC borrador (${seleccionables.length})`"
        :disable="!seleccionables.length"
        :loading="creando"
        @click="crearOrdenes"
      />
      <div v-if="sinProveedor.length" class="text-caption text-muted">
        {{ sinProveedor.length }} seleccionados sin proveedor conocido: registrá su precio de
        proveedor o crea la OC a mano.
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import type { QTableColumn } from 'quasar';
import { apiErrorMessage } from 'src/core/api';
import { useListado } from 'src/core/composables/useListado';
import { formatMoney, formatQty } from 'src/core/format';
import { MENSAJES_COMPRAS } from 'src/modules/procurement/messages';
import {
  createOrdersFromSuggestions,
  getReorderSuggestions,
  type ReorderSuggestion,
} from 'src/modules/procurement/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const router = useRouter();
const acl = useAclStore();
const ctx = useContextStore();

const { rows, loading, reload } = useListado<ReorderSuggestion>(() => getReorderSuggestions(), {
  errorMessage: 'No se pudieron cargar las sugerencias de reorden.',
});

const puedeCrearOC = computed(() => {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, 'procurement.order.create') : false;
});

const seleccion = ref<ReorderSuggestion[]>([]);
const creando = ref(false);

const seleccionables = computed(() => seleccion.value.filter((s) => s.supplier_party_id != null));
const sinProveedor = computed(() => seleccion.value.filter((s) => s.supplier_party_id == null));

const columns: QTableColumn<ReorderSuggestion>[] = [
  { name: 'sku', label: 'SKU', field: 'sku', align: 'left' },
  { name: 'nombre', label: 'Artículo', field: 'name', align: 'left' },
  { name: 'existencia', label: 'Existencia / punto de reorden', field: 'qty_on_hand', align: 'right' },
  { name: 'sugerida', label: 'Cantidad sugerida', field: 'suggested_qty', align: 'right' },
  { name: 'proveedor', label: 'Proveedor sugerido', field: 'supplier_display_name', align: 'left' },
];

async function crearOrdenes() {
  if (!seleccionables.value.length) return;
  creando.value = true;
  try {
    const out = await createOrdersFromSuggestions(
      seleccionables.value.map((s) => ({
        item_id: s.item_id,
        qty: s.suggested_qty,
        supplier_party_id: s.supplier_party_id as number,
      })),
    );
    seleccion.value = [];
    const primera = out.orders[0];
    $q.notify({
      type: 'positive',
      message: `${out.orders.length} orden(es) de compra en borrador creadas (una por proveedor).`,
    });
    if (out.orders.length === 1 && primera) {
      await router.push(`/compras/oc/${primera.order_id}`);
    }
    await reload();
  } catch (e) {
    const crudo = apiErrorMessage(e, 'No se pudieron crear las órdenes.');
    $q.notify({ type: 'negative', message: MENSAJES_COMPRAS[crudo] ?? crudo });
  } finally {
    creando.value = false;
  }
}
</script>

<style scoped>
.reo-encabezado {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}

.reo-acciones {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  margin-top: var(--app-space-3);
}
</style>
