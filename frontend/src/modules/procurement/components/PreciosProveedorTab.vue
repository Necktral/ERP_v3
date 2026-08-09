<template>
  <div>
    <div class="pp-filtros">
      <PartySelect
        v-model="filtroProveedor"
        role="SUPPLIER"
        label="Filtrar por proveedor"
        class="pp-filtros__prov"
        @update:model-value="reload"
      />
      <q-input
        v-model="filtroQ"
        dense
        outlined
        clearable
        placeholder="Buscar artículo…"
        class="pp-filtros__buscar"
        :debounce="350"
        @update:model-value="reload"
      >
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-space />
      <q-btn
        v-if="puedeGestionar"
        unelevated
        no-caps
        color="primary"
        icon="add"
        label="Registrar precio"
        @click="abrirEditar(null)"
      />
    </div>

    <q-table
      class="app-table"
      :rows="rows"
      :columns="columns"
      row-key="id"
      flat
      :loading="loading"
      :pagination="{ rowsPerPage: 25 }"
      no-data-label="Sin precios por proveedor registrados (el último costo se llena solo al recibir OCs)."
    >
      <template #body-cell-ultimo="props">
        <q-td :props="props">
          <template v-if="props.row.last_cost">
            {{ formatMoney(props.row.last_cost) }}
            <span v-if="props.row.last_receipt_at" class="text-muted">
              · {{ formatDate(props.row.last_receipt_at) }}
            </span>
          </template>
          <span v-else class="text-muted">—</span>
        </q-td>
      </template>
      <template #body-cell-acordado="props">
        <q-td :props="props">
          {{ props.row.agreed_price ? formatMoney(props.row.agreed_price) : '—' }}
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props">
          <q-btn
            v-if="puedeGestionar"
            flat
            dense
            round
            size="sm"
            icon="edit"
            aria-label="Editar precio de proveedor"
            @click="abrirEditar(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Diálogo: registrar/editar precio acordado -->
    <q-dialog v-model="dlgEditar">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Precio por proveedor</q-card-section>
        <q-card-section class="app-form">
          <PartySelect
            v-model="form.supplier_party_id"
            role="SUPPLIER"
            label="Proveedor *"
            :disable="editando"
          />
          <ItemSelect v-model="form.item_id" label="Artículo *" :disable="editando" />
          <q-input
            v-model="form.agreed_price"
            outlined
            dense
            type="number"
            min="0"
            label="Precio acordado C$ (vacío = quitar acuerdo)"
          />
          <div class="text-caption text-muted">
            El precio acordado manda sobre el último costo al armar órdenes de compra.
            El último costo se actualiza solo con cada recepción.
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Guardar"
            :loading="guardando"
            :disable="form.supplier_party_id == null || form.item_id == null"
            @click="guardar"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { useQuasar } from 'quasar';
import type { QTableColumn } from 'quasar';
import { apiErrorMessage } from 'src/core/api';
import { useListado } from 'src/core/composables/useListado';
import { formatDate, formatMoney } from 'src/core/format';
import ItemSelect from 'src/modules/inventory/components/ItemSelect.vue';
import PartySelect from 'src/modules/parties/components/PartySelect.vue';
import { MENSAJES_COMPRAS } from 'src/modules/procurement/messages';
import {
  listSupplierPrices,
  upsertSupplierPrice,
  type SupplierItemPriceRow,
} from 'src/modules/procurement/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const filtroProveedor = ref<number | null>(null);
const filtroQ = ref('');

const { rows, loading, reload } = useListado<SupplierItemPriceRow>(
  () =>
    listSupplierPrices({
      ...(filtroProveedor.value ? { supplier_party_id: filtroProveedor.value } : {}),
      ...(filtroQ.value?.trim() ? { q: filtroQ.value.trim() } : {}),
    }),
  { errorMessage: 'No se pudieron cargar los precios por proveedor.' },
);

const puedeGestionar = computed(() => {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, 'procurement.price.manage') : false;
});

const columns: QTableColumn<SupplierItemPriceRow>[] = [
  { name: 'proveedor', label: 'Proveedor', field: 'supplier_display_name', align: 'left' },
  { name: 'sku', label: 'SKU', field: 'item_sku', align: 'left' },
  { name: 'articulo', label: 'Artículo', field: 'item_name', align: 'left' },
  { name: 'ultimo', label: 'Último costo (auto)', field: 'last_cost', align: 'right' },
  { name: 'acordado', label: 'Precio acordado', field: 'agreed_price', align: 'right' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

// --- Editar / crear ---
const dlgEditar = ref(false);
const guardando = ref(false);
const editando = ref(false);
const form = reactive<{
  supplier_party_id: number | null;
  item_id: number | null;
  agreed_price: string;
}>({ supplier_party_id: null, item_id: null, agreed_price: '' });

function abrirEditar(row: SupplierItemPriceRow | null) {
  editando.value = row != null;
  form.supplier_party_id = row?.supplier_party_id ?? null;
  form.item_id = row?.item_id ?? null;
  form.agreed_price = row?.agreed_price ?? '';
  dlgEditar.value = true;
}

async function guardar() {
  if (form.supplier_party_id == null || form.item_id == null) return;
  guardando.value = true;
  try {
    await upsertSupplierPrice({
      supplier_party_id: form.supplier_party_id,
      item_id: form.item_id,
      agreed_price: form.agreed_price !== '' ? Number(form.agreed_price).toFixed(4) : null,
    });
    dlgEditar.value = false;
    $q.notify({ type: 'positive', message: 'Precio guardado.' });
    await reload();
  } catch (e) {
    const crudo = apiErrorMessage(e, 'No se pudo guardar el precio.');
    $q.notify({ type: 'negative', message: MENSAJES_COMPRAS[crudo] ?? crudo });
  } finally {
    guardando.value = false;
  }
}
</script>

<style scoped>
.pp-filtros {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}

.pp-filtros__prov {
  width: 260px;
}

.pp-filtros__buscar {
  width: 260px;
}
</style>
