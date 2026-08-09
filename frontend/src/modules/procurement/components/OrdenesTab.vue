<template>
  <div>
    <div class="oc-filtros">
      <q-select
        v-model="filtroEstado"
        :options="opcionesEstado"
        dense
        outlined
        emit-value
        map-options
        clearable
        label="Estado"
        class="oc-filtros__sel"
        @update:model-value="reload"
      />
      <q-space />
      <q-btn
        v-if="puedeCrear"
        unelevated
        no-caps
        color="primary"
        icon="post_add"
        label="Nueva orden de compra"
        @click="abrirCrear"
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
      no-data-label="No hay órdenes de compra."
      @row-click="(_, row) => abrirDetalle(row as PurchaseOrderRow)"
    >
      <template #body-cell-numero="props">
        <q-td :props="props">{{ props.row.series }}-{{ props.row.number }}</q-td>
      </template>
      <template #body-cell-total="props">
        <q-td :props="props">{{ formatMoney(props.row.total) }}</q-td>
      </template>
      <template #body-cell-fecha="props">
        <q-td :props="props">{{ formatDate(props.row.created_at) }}</q-td>
      </template>
      <template #body-cell-estado="props">
        <q-td :props="props">
          <EstadoChip :estado="props.row.status" :map="MAPA_OC" />
        </q-td>
      </template>
    </q-table>

    <!-- Diálogo: nueva OC con líneas -->
    <q-dialog v-model="dlgCrear">
      <q-card class="app-dialog oc-dialogo">
        <q-card-section class="text-h6">Nueva orden de compra</q-card-section>
        <q-card-section class="app-form">
          <PartySelect v-model="proveedorId" role="SUPPLIER" label="Proveedor *" />
          <q-input v-model="fechaEsperada" outlined dense type="date" label="Fecha esperada de entrega" />

          <div class="text-subtitle2 q-mt-sm">Líneas</div>
          <div v-for="(ln, i) in lineas" :key="i" class="oc-linea">
            <ItemSelect v-model="ln.item_id" class="oc-linea__item" />
            <q-input
              v-model="ln.qty"
              outlined
              dense
              type="number"
              min="0.0001"
              label="Cantidad *"
              class="oc-linea__num"
            />
            <q-input
              v-model="ln.unit_cost"
              outlined
              dense
              type="number"
              min="0"
              label="Costo unit."
              class="oc-linea__num"
            >
              <q-tooltip>Vacío = usa el precio del proveedor (acordado o último costo).</q-tooltip>
            </q-input>
            <q-btn flat dense round icon="close" aria-label="Eliminar línea de orden" :disable="lineas.length === 1" @click="lineas.splice(i, 1)" />
          </div>
          <q-btn flat no-caps icon="add" label="Agregar línea" @click="lineas.push({ item_id: null, qty: '1', unit_cost: '' })" />

          <q-input v-model="notas" outlined dense label="Notas" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear borrador"
            :loading="guardando"
            :disable="!formValido"
            @click="crear"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import type { QTableColumn } from 'quasar';
import EstadoChip from 'src/components/EstadoChip.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListado } from 'src/core/composables/useListado';
import { formatDate, formatMoney } from 'src/core/format';
import ItemSelect from 'src/modules/inventory/components/ItemSelect.vue';
import PartySelect from 'src/modules/parties/components/PartySelect.vue';
import {
  createPurchaseOrder,
  listPurchaseOrders,
  PO_STATUS_LABELS,
  type PurchaseOrderRow,
  type PurchaseOrderStatus,
} from 'src/modules/procurement/api';
import { MENSAJES_COMPRAS } from 'src/modules/procurement/messages';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const router = useRouter();
const acl = useAclStore();
const ctx = useContextStore();

const MAPA_OC = {
  DRAFT: { color: 'grey-7', label: PO_STATUS_LABELS.DRAFT },
  PENDING_APPROVAL: { color: 'orange-8', label: PO_STATUS_LABELS.PENDING_APPROVAL },
  APPROVED: { color: 'teal-7', label: PO_STATUS_LABELS.APPROVED },
  SENT: { color: 'blue-7', label: PO_STATUS_LABELS.SENT },
  PARTIALLY_RECEIVED: { color: 'indigo-6', label: PO_STATUS_LABELS.PARTIALLY_RECEIVED },
  RECEIVED: { color: 'positive', label: PO_STATUS_LABELS.RECEIVED },
  CLOSED: { color: 'grey-9', label: PO_STATUS_LABELS.CLOSED },
  CANCELLED: { color: 'negative', label: PO_STATUS_LABELS.CANCELLED },
};

const filtroEstado = ref<PurchaseOrderStatus | null>(null);

const { rows, loading, reload } = useListado<PurchaseOrderRow>(
  () => listPurchaseOrders({ status: filtroEstado.value ?? '' }),
  { errorMessage: 'No se pudieron cargar las órdenes de compra.' },
);

const puedeCrear = computed(() => {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, 'procurement.order.create') : false;
});

const opcionesEstado = Object.entries(PO_STATUS_LABELS).map(([value, label]) => ({ value, label }));

const columns: QTableColumn<PurchaseOrderRow>[] = [
  { name: 'numero', label: 'Número', field: 'number', align: 'left' },
  { name: 'proveedor', label: 'Proveedor', field: 'supplier_display_name', align: 'left' },
  { name: 'total', label: 'Total', field: 'total', align: 'right' },
  { name: 'fecha', label: 'Creada', field: 'created_at', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
];

function abrirDetalle(row: PurchaseOrderRow) {
  void router.push(`/compras/oc/${row.id}`);
}

// --- Crear ---
interface LineaForm {
  item_id: number | null;
  qty: string;
  unit_cost: string;
}

const dlgCrear = ref(false);
const guardando = ref(false);
const proveedorId = ref<number | null>(null);
const fechaEsperada = ref('');
const notas = ref('');
const lineas = ref<LineaForm[]>([{ item_id: null, qty: '1', unit_cost: '' }]);

const formValido = computed(
  () =>
    proveedorId.value != null &&
    lineas.value.length > 0 &&
    lineas.value.every((ln) => ln.item_id != null && Number(ln.qty) > 0),
);

function abrirCrear() {
  proveedorId.value = null;
  fechaEsperada.value = '';
  notas.value = '';
  lineas.value = [{ item_id: null, qty: '1', unit_cost: '' }];
  dlgCrear.value = true;
}

async function crear() {
  if (!formValido.value || proveedorId.value == null) return;
  guardando.value = true;
  try {
    const res = await createPurchaseOrder({
      supplier_party_id: proveedorId.value,
      ...(fechaEsperada.value ? { expected_date: fechaEsperada.value } : {}),
      ...(notas.value ? { notes: notas.value } : {}),
      lines: lineas.value.map((ln) => ({
        item_id: ln.item_id as number,
        qty: String(ln.qty),
        ...(ln.unit_cost !== '' ? { unit_cost: Number(ln.unit_cost).toFixed(4) } : {}),
      })),
    });
    dlgCrear.value = false;
    $q.notify({ type: 'positive', message: `OC-${res.number} creada como borrador.` });
    await router.push(`/compras/oc/${res.order_id}`);
  } catch (e) {
    const crudo = apiErrorMessage(e, 'No se pudo crear la orden.');
    $q.notify({ type: 'negative', message: MENSAJES_COMPRAS[crudo] ?? crudo });
  } finally {
    guardando.value = false;
  }
}
</script>

<style scoped>
.oc-filtros {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}

.oc-filtros__sel {
  width: 220px;
}

.oc-dialogo {
  min-width: min(680px, 95vw);
}

.oc-linea {
  display: flex;
  gap: var(--app-space-2);
  align-items: center;
  margin-bottom: var(--app-space-1);
}

.oc-linea__item {
  flex: 1;
}

.oc-linea__num {
  width: 130px;
}
</style>
