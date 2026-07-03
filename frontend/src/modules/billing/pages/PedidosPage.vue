<template>
  <q-page class="app-page">
    <PageHeader
      title="Pedidos"
      subtitle="Encargos de venta con aprobación de crédito segregada (maker-checker): el vendedor somete el pedido y otro usuario resuelve el crédito."
      :loading="loading"
      @refresh="reload"
    >
      <template #actions>
        <q-btn
          v-if="puede('billing.order.approve')"
          flat
          no-caps
          icon="rule"
          label="Aprobaciones de crédito"
          to="/facturacion/aprobaciones-credito"
        />
        <q-btn
          v-if="puede('billing.order.create')"
          unelevated
          no-caps
          color="primary"
          icon="post_add"
          label="Nuevo pedido"
          @click="abrirCrear"
        />
      </template>
    </PageHeader>

    <div class="ped-filtros">
      <q-select
        v-model="filtroEstado"
        :options="opcionesEstado"
        dense
        outlined
        emit-value
        map-options
        clearable
        label="Estado"
        class="ped-filtros__sel"
        @update:model-value="reload"
      />
    </div>

    <q-table
      v-model:pagination="pagination"
      class="app-table"
      :rows="rows"
      :columns="columns"
      row-key="id"
      flat
      :loading="loading"
      :rows-per-page-options="[10, 25, 50, 100]"
      no-data-label="No hay pedidos con esos filtros."
      @request="onRequest"
    >
      <template #body-cell-cliente="props">
        <q-td :props="props">{{ props.row.customer_name || '—' }}</q-td>
      </template>
      <template #body-cell-total="props">
        <q-td :props="props">{{ formatMoney(props.row.total) }}</q-td>
      </template>
      <template #body-cell-entrega="props">
        <q-td :props="props">{{ formatDate(props.row.expected_delivery_date) }}</q-td>
      </template>
      <template #body-cell-created_at="props">
        <q-td :props="props">{{ formatDate(props.row.created_at) }}</q-td>
      </template>
      <template #body-cell-estado="props">
        <q-td :props="props">
          <EstadoChip :estado="props.row.status" :map="MAPA_ESTADO" />
        </q-td>
      </template>
      <template #body-cell-credito="props">
        <q-td :props="props">
          <EstadoChip
            v-if="props.row.credit_status !== 'NONE'"
            :estado="props.row.credit_status"
            :map="MAPA_CREDITO"
          />
          <span v-else class="text-muted">—</span>
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props">
          <q-btn
            v-if="puedeSometer(props.row)"
            dense
            flat
            no-caps
            color="primary"
            icon="send"
            label="Someter a crédito"
            @click="abrirSometer(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Diálogo: nuevo pedido con líneas -->
    <q-dialog v-model="dlgCrear">
      <q-card class="app-dialog ped-dlg">
        <q-card-section class="text-h6">Nuevo pedido (encargo)</q-card-section>
        <q-card-section class="app-form">
          <PartySelect
            v-model="form.customer_party_id"
            role="CUSTOMER"
            label="Cliente (del directorio de Terceros)"
            @selected="onCliente"
          />
          <q-input
            v-model="form.customer_name"
            outlined
            dense
            label="Nombre del cliente *"
            hint="Obligatorio; se autocompleta al elegir un tercero."
          />
          <div class="ped-fila">
            <q-input
              v-model="form.customer_ref"
              outlined
              dense
              label="Referencia del cliente"
              class="col"
            />
            <q-input
              v-model="form.expected_delivery_date"
              outlined
              dense
              type="date"
              label="Fecha esperada de entrega"
              class="col"
            />
          </div>
          <q-input v-model="form.notes" outlined dense label="Notas" />

          <q-separator spaced />
          <div class="text-subtitle2">Líneas</div>
          <div v-for="(linea, idx) in form.lines" :key="idx" class="ped-linea-grupo">
            <div class="ped-linea">
              <q-select
                :model-value="linea.inventory_item_id ?? null"
                :options="opcionesArticulo"
                outlined
                dense
                use-input
                clearable
                emit-value
                map-options
                label="Artículo del inventario (opcional)"
                class="ped-linea__articulo"
                input-debounce="350"
                :loading="buscandoArticulo"
                @filter="filtrarArticulos"
                @update:model-value="(v: number | null) => onArticulo(linea, v)"
              >
                <template #no-option>
                  <q-item><q-item-section class="text-muted">Escribí para buscar.</q-item-section></q-item>
                </template>
              </q-select>
              <q-btn flat dense round icon="delete" color="grey-7" @click="form.lines.splice(idx, 1)" />
            </div>
            <div class="ped-linea">
              <q-input v-model="linea.description" outlined dense label="Descripción *" class="ped-linea__desc" />
              <q-input v-model="linea.quantity" outlined dense type="number" min="0" label="Cant. *" class="ped-linea__num" />
              <q-input v-model="linea.unit_price" outlined dense type="number" min="0" label="Precio C$ *" class="ped-linea__num" />
              <q-input v-model="linea.tax_rate" outlined dense type="number" min="0" label="IVA %" class="ped-linea__num" />
              <q-input v-model="linea.discount_pct" outlined dense type="number" min="0" max="100" label="Desc. %" class="ped-linea__num" />
            </div>
          </div>
          <q-btn flat dense no-caps icon="add" label="Agregar línea" @click="agregarLinea" />
          <div class="text-right text-subtitle2">Total estimado: {{ formatMoney(totalEstimado) }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear pedido"
            :loading="guardando"
            :disable="!formValido"
            @click="crear"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: someter a aprobación de crédito (maker) -->
    <q-dialog v-model="dlgSometer">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Someter a aprobación de crédito</q-card-section>
        <q-card-section v-if="pedidoSometer" class="app-form">
          <div>
            Pedido #{{ pedidoSometer.id }} — {{ pedidoSometer.customer_name || 'sin cliente' }} —
            <b>{{ formatMoney(pedidoSometer.total) }}</b>
          </div>
          <q-input
            v-model="notasSometer"
            outlined
            dense
            autogrow
            label="Notas para el aprobador"
          />
          <div class="text-caption text-muted">
            Por segregación de funciones (SoD), la solicitud debe resolverla un usuario
            distinto al que la somete.
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Someter"
            :loading="sometiendo"
            @click="someter"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import EstadoChip, { type EstadoEstilo } from 'src/components/EstadoChip.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { formatDate, formatMoney } from 'src/core/format';
import PartySelect from 'src/modules/parties/components/PartySelect.vue';
import {
  createSalesOrder,
  CREDIT_STATUS_LABELS,
  listSalesOrdersPage,
  SALES_ORDER_STATUS_LABELS,
  submitOrderCredit,
  type BillingLineInput,
  type SalesOrderRow,
  type SalesOrderStatus,
} from 'src/modules/billing/api';
import { listItems, type InventoryItem } from 'src/modules/inventory/api';
import type { Party } from 'src/modules/parties/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const MAPA_ESTADO: Record<string, EstadoEstilo> = Object.fromEntries(
  Object.entries(SALES_ORDER_STATUS_LABELS).map(([code, label]) => [
    code,
    {
      label,
      color:
        code === 'APPROVED' || code === 'READY' || code === 'FULFILLED'
          ? 'secondary'
          : code === 'REJECTED' || code === 'CANCELLED'
            ? 'negative'
            : code === 'PENDING_APPROVAL' || code === 'IN_REVIEW'
              ? 'warning'
              : 'grey-7',
      outline: true,
    },
  ]),
);

const MAPA_CREDITO: Record<string, EstadoEstilo> = Object.fromEntries(
  Object.entries(CREDIT_STATUS_LABELS).map(([code, label]) => [
    code,
    {
      label: `Crédito: ${label}`,
      color:
        code === 'APPROVED'
          ? 'positive'
          : code === 'REJECTED'
            ? 'negative'
            : code === 'NONE'
              ? 'grey-7'
              : 'warning',
      outline: true,
    },
  ]),
);

const filtroEstado = ref<SalesOrderStatus | null>(null);

const { rows, loading, pagination, onRequest, reload } = useListadoServer<SalesOrderRow>(
  (page) => listSalesOrdersPage({ status: filtroEstado.value ?? '' }, page),
  { errorMessage: 'No se pudieron cargar los pedidos.' },
);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const opcionesEstado = Object.entries(SALES_ORDER_STATUS_LABELS).map(([value, label]) => ({
  value,
  label,
}));

// El backend de pedidos NO soporta `ordering`: columnas sin sortable.
const columns: QTableColumn<SalesOrderRow>[] = [
  { name: 'id', label: '#', field: 'id', align: 'left' },
  { name: 'cliente', label: 'Cliente', field: 'customer_name', align: 'left' },
  { name: 'total', label: 'Total', field: 'total', align: 'right' },
  { name: 'entrega', label: 'Entrega', field: 'expected_delivery_date', align: 'left' },
  { name: 'created_at', label: 'Creado', field: 'created_at', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'credito', label: 'Crédito', field: 'credit_status', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

// --- Crear pedido ---
const dlgCrear = ref(false);
const guardando = ref(false);
const form = reactive<{
  customer_party_id: number | null;
  customer_name: string;
  customer_ref: string;
  expected_delivery_date: string;
  notes: string;
  lines: BillingLineInput[];
}>({
  customer_party_id: null,
  customer_name: '',
  customer_ref: '',
  expected_delivery_date: '',
  notes: '',
  lines: [],
});

function onCliente(party: Party | null) {
  // El backend exige customer_name siempre: autocompletar desde el tercero.
  if (party) form.customer_name = party.display_name;
}

function agregarLinea() {
  form.lines.push({ description: '', quantity: '1', unit_price: '', tax_rate: '0', discount_pct: '0' });
}

// --- Artículo del inventario en la línea (autocompleta precio/IVA del catálogo) ---
interface OpcionArticulo {
  label: string;
  value: number;
}
const opcionesArticulo = ref<OpcionArticulo[]>([]);
const buscandoArticulo = ref(false);
const articulosPorId = new Map<number, InventoryItem>();

function filtrarArticulos(input: string, update: (fn: () => void) => void, abort: () => void) {
  if (!input.trim()) {
    abort();
    return;
  }
  buscandoArticulo.value = true;
  listItems({ search: input.trim() })
    .then((rows) => {
      update(() => {
        for (const it of rows) articulosPorId.set(it.id, it);
        opcionesArticulo.value = rows.map((it) => ({
          label: `${it.sku} — ${it.name}${it.sale_price != null ? ` (${formatMoney(it.sale_price)})` : ''}`,
          value: it.id,
        }));
      });
    })
    .catch(() => abort())
    .finally(() => {
      buscandoArticulo.value = false;
    });
}

function onArticulo(linea: BillingLineInput, itemId: number | null) {
  linea.inventory_item_id = itemId;
  if (itemId == null) return;
  const item = articulosPorId.get(itemId);
  if (!item) return;
  linea.description = item.name;
  if (item.sale_price != null) linea.unit_price = item.sale_price;
  linea.tax_rate = String(Math.round(Number(item.default_tax_rate) * 100));
}

function abrirCrear() {
  Object.assign(form, {
    customer_party_id: null,
    customer_name: '',
    customer_ref: '',
    expected_delivery_date: '',
    notes: '',
    lines: [],
  });
  agregarLinea();
  dlgCrear.value = true;
}

const totalEstimado = computed(() =>
  form.lines.reduce((acc, l) => {
    const bruto = Number(l.quantity || 0) * Number(l.unit_price || 0);
    const sub = bruto * (1 - Number(l.discount_pct || 0) / 100);
    return acc + sub * (1 + Number(l.tax_rate || 0) / 100);
  }, 0),
);

const formValido = computed(
  () =>
    form.customer_name.trim().length > 0 &&
    form.lines.length > 0 &&
    form.lines.every(
      (l) => l.description.trim() && Number(l.quantity) > 0 && l.unit_price !== '' && Number(l.unit_price) >= 0,
    ),
);

async function crear() {
  if (!formValido.value) return;
  guardando.value = true;
  try {
    const out = await createSalesOrder({
      customer_name: form.customer_name.trim(),
      ...(form.customer_ref.trim() ? { customer_ref: form.customer_ref.trim() } : {}),
      ...(form.customer_party_id != null ? { customer_party_id: form.customer_party_id } : {}),
      ...(form.expected_delivery_date ? { expected_delivery_date: form.expected_delivery_date } : {}),
      ...(form.notes.trim() ? { notes: form.notes.trim() } : {}),
      lines: form.lines.map((l) => ({
        description: l.description.trim(),
        quantity: String(l.quantity),
        unit_price: String(l.unit_price),
        // el backend espera tasas como fracción decimal (0.15 = 15%)
        tax_rate: String(Number(l.tax_rate || 0) / 100),
        discount_pct: String(Number(l.discount_pct || 0) / 100),
        ...(l.inventory_item_id != null ? { inventory_item_id: l.inventory_item_id } : {}),
      })),
    });
    dlgCrear.value = false;
    $q.notify({ type: 'positive', message: `Pedido #${out.order_id} creado en borrador.` });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear el pedido.') });
  } finally {
    guardando.value = false;
  }
}

// --- Someter a crédito (maker) ---
const dlgSometer = ref(false);
const sometiendo = ref(false);
const pedidoSometer = ref<SalesOrderRow | null>(null);
const notasSometer = ref('');

function puedeSometer(row: SalesOrderRow): boolean {
  // El backend solo acepta someter desde DRAFT o APPROVED.
  return puede('billing.order.submit') && (row.status === 'DRAFT' || row.status === 'APPROVED');
}

function abrirSometer(row: SalesOrderRow) {
  pedidoSometer.value = row;
  notasSometer.value = '';
  dlgSometer.value = true;
}

async function someter() {
  const pedido = pedidoSometer.value;
  if (!pedido) return;
  sometiendo.value = true;
  try {
    const out = await submitOrderCredit(pedido.id, notasSometer.value.trim());
    dlgSometer.value = false;
    $q.notify({
      type: 'positive',
      message: `Pedido #${out.order_id} sometido a crédito (solicitud #${out.approval_id}).`,
    });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo someter el pedido.') });
  } finally {
    sometiendo.value = false;
  }
}
</script>

<style scoped>
.ped-filtros {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-4);
}

.ped-filtros__sel {
  width: 240px;
}

.ped-dlg {
  width: 720px;
}

.ped-fila {
  display: flex;
  gap: var(--app-space-3);
}

.ped-fila .col {
  flex: 1;
}

.ped-linea-grupo {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  padding: var(--app-space-2);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}

.ped-linea {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}

.ped-linea__articulo {
  flex: 1;
}

.ped-linea__desc {
  flex: 1;
}

.ped-linea__num {
  width: 100px;
}
</style>
