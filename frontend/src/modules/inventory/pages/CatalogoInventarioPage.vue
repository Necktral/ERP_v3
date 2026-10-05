<template>
  <q-page class="app-page">
    <PageHeader
      title="Catálogo de inventario"
      subtitle="Artículos, bodegas y lotes. Se configura una vez y las existencias se mueven en la pantalla de Existencias."
      :loading="cargando"
      @refresh="recargarTodo"
    />

    <q-tabs
      v-model="tab"
      dense
      no-caps
      align="left"
      class="cat-tabs"
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab name="articulos" icon="category" label="Artículos" />
      <q-tab name="bodegas" icon="warehouse" label="Bodegas" />
      <q-tab name="lotes" icon="inventory_2" label="Lotes" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <q-tab-panels v-model="tab" animated class="cat-panels">
      <!-- ============ ARTÍCULOS ============ -->
      <q-tab-panel name="articulos" class="q-pa-none">
        <div class="app-actions">
          <q-btn
            v-if="puede('inventory.item.create')"
            unelevated
            no-caps
            color="primary"
            icon="add"
            label="Nuevo artículo"
            @click="abrirCrearItem"
          />
          <q-btn
            flat
            no-caps
            icon="qr_code"
            :label="`Imprimir etiquetas (${seleccionEtiquetas.length})`"
            :disable="!seleccionEtiquetas.length"
            @click="abrirEtiquetas"
          />
          <span class="text-caption text-muted">
            SKU único por empresa. Si el artículo vence (agroquímicos, alimentos), activá lotes y
            vencimiento. Marcá artículos para imprimirles etiquetas con código de barras.
          </span>
        </div>
        <q-table
          v-model:selected="seleccionEtiquetas"
          v-model:pagination="paginacionItems"
          class="app-table"
          :rows="items"
          :columns="columnasItem"
          row-key="id"
          flat
          selection="multiple"
          :loading="cargandoItems"
          :rows-per-page-options="[10, 25, 50, 100]"
          no-data-label="Aún no hay artículos."
          @request="onRequestItems"
        >
          <template #header-selection="scope">
            <q-checkbox v-model="scope.selected" aria-label="Seleccionar todos los artículos" />
          </template>
          <template #body-selection="scope">
            <q-checkbox
              v-model="scope.selected"
              :aria-label="`Seleccionar artículo ${scope.row.sku || scope.row.name || scope.row.id}`"
            />
          </template>
          <template #body-cell-uom="props">
            <q-td :props="props">{{ UOM_LABELS[props.row.uom] ?? props.row.uom }}</q-td>
          </template>
          <template #body-cell-precio="props">
            <q-td :props="props" class="text-right">
              <span v-if="props.row.sale_price != null">{{ formatMoney(props.row.sale_price) }}</span>
              <q-chip v-else dense outline color="warning" label="Sin precio">
                <q-tooltip>Sin precio la Caja de Venta no puede venderlo.</q-tooltip>
              </q-chip>
            </q-td>
          </template>
          <template #body-cell-flags="props">
            <q-td :props="props">
              <q-chip v-if="props.row.track_lots" dense outline color="primary" label="Lotes" />
              <q-chip v-if="props.row.track_expiry" dense outline color="warning" label="Vence" />
              <q-chip v-if="props.row.is_controlled" dense outline color="negative" label="Controlado" />
            </q-td>
          </template>
          <template #body-cell-acciones="props">
            <q-td :props="props" class="text-right">
              <q-btn
                flat
                dense
                no-caps
                size="sm"
                icon="article"
                label="Ficha"
                :to="`/inventario/producto/${props.row.id}`"
              />
              <q-btn
                v-if="puede('inventory.item.update')"
                flat
                dense
                no-caps
                size="sm"
                icon="edit"
                label="Editar"
                @click="abrirEditarItem(props.row)"
              />
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <!-- ============ BODEGAS ============ -->
      <q-tab-panel name="bodegas" class="q-pa-none">
        <div class="app-actions">
          <q-btn
            v-if="puede('inventory.warehouse.create')"
            unelevated
            no-caps
            color="primary"
            icon="add_home_work"
            label="Nueva bodega"
            :disable="!ctx.activeBranchId"
            @click="dlgBodega = true"
          />
          <span class="text-caption text-muted">
            {{
              ctx.activeBranchId
                ? 'Las bodegas pertenecen a la sucursal activa del selector de arriba.'
                : 'Elegí una SUCURSAL en el selector de arriba para crear bodegas.'
            }}
          </span>
        </div>
        <q-table
          class="app-table"
          :rows="bodegas"
          :columns="columnasBodega"
          row-key="id"
          flat
          :loading="cargando"
          :pagination="{ rowsPerPage: 25 }"
          no-data-label="Aún no hay bodegas en esta sucursal."
        >
          <template #body-cell-tipo="props">
            <q-td :props="props">
              {{ WAREHOUSE_TYPE_LABELS[props.row.warehouse_type] ?? props.row.warehouse_type }}
            </q-td>
          </template>
          <template #body-cell-default="props">
            <q-td :props="props">
              <q-icon v-if="props.row.is_default" name="star" color="amber" size="18px" />
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <!-- ============ LOTES ============ -->
      <q-tab-panel name="lotes" class="q-pa-none">
        <div class="app-actions">
          <q-select
            v-model="loteItemId"
            :options="opcionesItemLotes"
            dense
            outlined
            emit-value
            map-options
            label="Artículo con lotes"
            class="cat-lote-sel"
            @update:model-value="cargarLotes"
          />
          <q-btn
            v-if="puede('inventory.lot.create') && loteItemId != null"
            unelevated
            no-caps
            color="primary"
            icon="add"
            label="Nuevo lote"
            @click="dlgLote = true"
          />
        </div>
        <q-table
          class="app-table"
          :rows="lotes"
          :columns="columnasLote"
          row-key="id"
          flat
          :loading="cargandoLotes"
          :pagination="{ rowsPerPage: 25 }"
          :no-data-label="
            loteItemId == null ? 'Elegí un artículo con lotes.' : 'Este artículo no tiene lotes.'
          "
        >
          <template #body-cell-vence="props">
            <q-td :props="props" :class="props.row.is_expired ? 'text-negative' : ''">
              {{ formatDate(props.row.expiry_date) }}
              <span v-if="props.row.days_to_expiry != null" class="text-caption text-muted">
                ({{ props.row.days_to_expiry }} días)
              </span>
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>
    </q-tab-panels>

    <!-- Diálogo: nuevo / editar artículo -->
    <q-dialog v-model="dlgItem">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">
          {{ editandoId == null ? 'Nuevo artículo' : 'Editar artículo' }}
        </q-card-section>
        <q-card-section class="app-form">
          <q-input
            v-model="formItem.sku"
            outlined
            dense
            label="SKU * (código único)"
            :readonly="editandoId != null"
            autofocus
          />
          <q-input v-model="formItem.name" outlined dense label="Nombre *" />
          <q-input v-model="formItem.category" outlined dense label="Categoría" />
          <q-input
            v-model="formItem.barcode"
            outlined
            dense
            label="Código de barras"
            hint="Lo que lee el escáner de la Caja de Venta. Único por empresa."
          />
          <div class="cat-precio-fila">
            <q-input
              v-model="formItem.sale_price"
              outlined
              dense
              type="number"
              min="0"
              label="Precio de venta"
              hint="Vacío = sin precio (la caja no lo vende)."
            />
            <q-input
              v-model="formItem.tax_pct"
              outlined
              dense
              type="number"
              min="0"
              max="100"
              label="IVA %"
              hint="15 = IVA estándar; 0 = exento."
            />
          </div>
          <div class="cat-precio-fila">
            <q-input
              v-model="formItem.wholesale_price"
              outlined
              dense
              type="number"
              min="0"
              label="Precio de mayoreo"
              hint="Vacío = sin mayoreo."
            />
            <q-input
              v-model="formItem.wholesale_min_qty"
              outlined
              dense
              type="number"
              min="0"
              label="Cantidad mínima mayoreo"
              hint="Desde esta cantidad la caja aplica el mayoreo sola."
            />
          </div>
          <q-select
            v-model="formItem.uom"
            :options="opcionesUom"
            label="Unidad de medida"
            outlined
            dense
            emit-value
            map-options
            :readonly="editandoId != null"
          />
          <q-input
            v-model="formItem.reorder_point"
            outlined
            dense
            type="number"
            min="0"
            label="Punto de reorden"
            hint="Cuando el saldo baje de aquí, aparece en la alerta de reorden."
          />
          <template v-if="editandoId == null">
            <q-toggle v-model="formItem.track_lots" label="Maneja lotes" color="primary" />
            <q-toggle
              v-model="formItem.track_expiry"
              :disable="!formItem.track_lots"
              label="Controla vencimiento (requiere lotes)"
              color="warning"
            />
            <q-toggle
              v-model="formItem.is_controlled"
              label="Producto controlado (agroquímico)"
              color="negative"
            />
          </template>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            :label="editandoId == null ? 'Crear artículo' : 'Guardar cambios'"
            :loading="guardando"
            :disable="!formItem.sku.trim() || !formItem.name.trim()"
            @click="guardarItem"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: nueva bodega -->
    <q-dialog v-model="dlgBodega">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Nueva bodega</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="formBodega.name" outlined dense label="Nombre *" autofocus />
          <q-input v-model="formBodega.code" outlined dense label="Código (corto, opcional)" />
          <q-select
            v-model="formBodega.warehouse_type"
            :options="opcionesTipoBodega"
            label="Tipo"
            outlined
            dense
            emit-value
            map-options
          />
          <q-input v-model="formBodega.location_description" outlined dense label="Ubicación" />
          <q-toggle v-model="formBodega.is_default" label="Bodega por defecto" color="primary" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear bodega"
            :loading="guardando"
            :disable="!formBodega.name.trim()"
            @click="crearBodegaNueva"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: nuevo lote -->
    <q-dialog v-model="dlgLote">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Nuevo lote</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="formLote.lot_number" outlined dense label="Número de lote *" autofocus />
          <q-input v-model="formLote.supplier_lot_ref" outlined dense label="Lote del proveedor" />
          <q-input v-model="formLote.production_date" outlined dense type="date" label="Fecha de producción" />
          <q-input v-model="formLote.expiry_date" outlined dense type="date" label="Fecha de vencimiento" />
          <q-input v-model="formLote.notes" outlined dense label="Notas" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear lote"
            :loading="guardando"
            :disable="!formLote.lot_number.trim()"
            @click="crearLoteNuevo"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: etiquetas con código de barras -->
    <q-dialog v-model="dlgEtiquetas">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Imprimir etiquetas</q-card-section>
        <q-card-section class="app-form">
          <div class="text-muted">
            {{ seleccionEtiquetas.length }} artículo(s) seleccionado(s). Cada etiqueta lleva
            nombre, precio y código de barras Code 128 escaneable (usa el código del artículo,
            o el SKU si no tiene).
          </div>
          <q-input
            v-model.number="etiquetasCopias"
            outlined
            dense
            type="number"
            min="1"
            max="100"
            label="Copias por artículo"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            icon="print"
            label="Imprimir"
            @click="imprimirEtiquetas"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { code128Svg } from 'src/core/barcode';
import { formatDate, formatMoney, formatQty } from 'src/core/format';
import {
  createItem,
  createLot,
  createWarehouse,
  listItems,
  listItemsPage,
  listLots,
  listWarehouses,
  updateItem,
  UOM_LABELS,
  WAREHOUSE_TYPE_LABELS,
  type InventoryItem,
  type ItemLot,
  type Warehouse,
} from 'src/modules/inventory/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const tab = ref('articulos');
const cargando = ref(false);
const guardando = ref(false);

// Artículos de la tabla: paginación server-side (el catálogo de SKUs crece sin
// límite; antes truncaba a 200). auto:false porque recargarTodo() carga al montar.
const {
  rows: items,
  loading: cargandoItems,
  pagination: paginacionItems,
  onRequest: onRequestItems,
  reload: recargarItems,
} = useListadoServer<InventoryItem>((page) => listItemsPage({}, page), {
  errorMessage: 'No se pudieron cargar los artículos.',
  auto: false,
});

// Catálogo para el selector de lotes (carga completa a propósito, tope 200 del
// backend: solo alimenta las opciones de artículos con lote).
const itemsLotes = ref<InventoryItem[]>([]);
const bodegas = ref<Warehouse[]>([]);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const opcionesUom = Object.entries(UOM_LABELS).map(([value, label]) => ({ value, label }));
const opcionesTipoBodega = Object.entries(WAREHOUSE_TYPE_LABELS).map(([value, label]) => ({
  value,
  label,
}));

// Sin columnas `sortable`: el endpoint ordena fijo por sku y no acepta `ordering`.
const columnasItem: QTableColumn<InventoryItem>[] = [
  { name: 'sku', label: 'SKU', field: 'sku', align: 'left' },
  { name: 'name', label: 'Nombre', field: 'name', align: 'left' },
  { name: 'category', label: 'Categoría', field: 'category', align: 'left' },
  { name: 'barcode', label: 'Cód. barras', field: 'barcode', align: 'left' },
  { name: 'precio', label: 'Precio venta', field: 'sale_price', align: 'right' },
  {
    name: 'iva',
    label: 'IVA',
    field: (r) => `${Math.round(Number(r.default_tax_rate) * 100)}%`,
    align: 'right',
  },
  { name: 'uom', label: 'Unidad', field: 'uom', align: 'left' },
  {
    name: 'reorder',
    label: 'Reorden',
    field: (r) => formatQty(r.reorder_point),
    align: 'right',
  },
  { name: 'flags', label: 'Controles', field: 'id', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

const columnasBodega: QTableColumn<Warehouse>[] = [
  { name: 'name', label: 'Bodega', field: 'name', align: 'left', sortable: true },
  { name: 'code', label: 'Código', field: 'code', align: 'left' },
  { name: 'tipo', label: 'Tipo', field: 'warehouse_type', align: 'left' },
  { name: 'location', label: 'Ubicación', field: 'location_description', align: 'left' },
  { name: 'default', label: 'Defecto', field: 'is_default', align: 'center' },
];

const columnasLote: QTableColumn<ItemLot>[] = [
  { name: 'lot_number', label: 'Lote', field: 'lot_number', align: 'left' },
  { name: 'supplier_lot_ref', label: 'Ref. proveedor', field: 'supplier_lot_ref', align: 'left' },
  { name: 'production', label: 'Producción', field: (r) => formatDate(r.production_date), align: 'left' },
  { name: 'vence', label: 'Vence', field: 'expiry_date', align: 'left' },
  { name: 'status', label: 'Estado', field: 'status', align: 'left' },
  { name: 'qty', label: 'Recibido', field: (r) => formatQty(r.qty_received), align: 'right' },
];

async function recargarTodo() {
  cargando.value = true;
  try {
    const [lotes, whs] = await Promise.all([listItems(), listWarehouses(), recargarItems()] as const);
    itemsLotes.value = lotes;
    bodegas.value = whs;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el catálogo.') });
  } finally {
    cargando.value = false;
  }
}

// --- Artículos ---
const dlgItem = ref(false);
const editandoId = ref<number | null>(null);
const formItem = reactive({
  sku: '',
  name: '',
  category: '',
  barcode: '',
  sale_price: '',
  tax_pct: '15',
  wholesale_price: '',
  wholesale_min_qty: '',
  uom: 'UNIT',
  reorder_point: '0',
  track_lots: false,
  track_expiry: false,
  is_controlled: false,
});

function abrirCrearItem() {
  editandoId.value = null;
  Object.assign(formItem, {
    sku: '',
    name: '',
    category: '',
    barcode: '',
    sale_price: '',
    tax_pct: '15',
    wholesale_price: '',
    wholesale_min_qty: '',
    uom: 'UNIT',
    reorder_point: '0',
    track_lots: false,
    track_expiry: false,
    is_controlled: false,
  });
  dlgItem.value = true;
}

function abrirEditarItem(item: InventoryItem) {
  editandoId.value = item.id;
  Object.assign(formItem, {
    sku: item.sku,
    name: item.name,
    category: item.category,
    barcode: item.barcode,
    sale_price: item.sale_price ?? '',
    tax_pct: String(Math.round(Number(item.default_tax_rate) * 100)),
    wholesale_price: item.wholesale_price ?? '',
    wholesale_min_qty: item.wholesale_min_qty ?? '',
    uom: item.uom,
    reorder_point: item.reorder_point,
    track_lots: item.track_lots,
    track_expiry: item.track_expiry,
    is_controlled: item.is_controlled,
  });
  dlgItem.value = true;
}

/** El IVA se captura en % y la API lo recibe como fracción 0-1. */
function ivaFraccion(): string {
  return (Number(formItem.tax_pct || '0') / 100).toFixed(4);
}

async function guardarItem() {
  guardando.value = true;
  const precio = formItem.sale_price === '' ? null : String(formItem.sale_price);
  const mayoreo = formItem.wholesale_price === '' ? null : String(formItem.wholesale_price);
  const mayoreoMin = formItem.wholesale_min_qty === '' ? null : String(formItem.wholesale_min_qty);
  try {
    if (editandoId.value == null) {
      await createItem({
        sku: formItem.sku.trim(),
        name: formItem.name.trim(),
        category: formItem.category,
        barcode: formItem.barcode.trim(),
        sale_price: precio,
        default_tax_rate: ivaFraccion(),
        wholesale_price: mayoreo,
        wholesale_min_qty: mayoreoMin,
        uom: formItem.uom,
        reorder_point: formItem.reorder_point || '0',
        track_lots: formItem.track_lots,
        track_expiry: formItem.track_lots && formItem.track_expiry,
        is_controlled: formItem.is_controlled,
      });
      $q.notify({ type: 'positive', message: `Artículo "${formItem.name.trim()}" creado.` });
    } else {
      await updateItem(editandoId.value, {
        name: formItem.name.trim(),
        category: formItem.category,
        barcode: formItem.barcode.trim(),
        sale_price: precio,
        default_tax_rate: ivaFraccion(),
        wholesale_price: mayoreo,
        wholesale_min_qty: mayoreoMin,
        reorder_point: formItem.reorder_point || '0',
      });
      $q.notify({ type: 'positive', message: 'Artículo actualizado.' });
    }
    dlgItem.value = false;
    await recargarTodo();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo guardar el artículo.') });
  } finally {
    guardando.value = false;
  }
}

// --- Bodegas ---
const dlgBodega = ref(false);
const formBodega = reactive({
  name: '',
  code: '',
  warehouse_type: 'GENERAL',
  location_description: '',
  is_default: false,
});

async function crearBodegaNueva() {
  guardando.value = true;
  try {
    await createWarehouse({ ...formBodega, name: formBodega.name.trim() });
    dlgBodega.value = false;
    $q.notify({ type: 'positive', message: `Bodega "${formBodega.name.trim()}" creada.` });
    Object.assign(formBodega, {
      name: '',
      code: '',
      warehouse_type: 'GENERAL',
      location_description: '',
      is_default: false,
    });
    await recargarTodo();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear la bodega.') });
  } finally {
    guardando.value = false;
  }
}

// --- Lotes ---
const loteItemId = ref<number | null>(null);
const lotes = ref<ItemLot[]>([]);
const cargandoLotes = ref(false);
const dlgLote = ref(false);
const formLote = reactive({
  lot_number: '',
  supplier_lot_ref: '',
  production_date: '',
  expiry_date: '',
  notes: '',
});

const opcionesItemLotes = computed(() =>
  itemsLotes.value.filter((i) => i.track_lots).map((i) => ({ value: i.id, label: `${i.sku} — ${i.name}` })),
);

async function cargarLotes() {
  if (loteItemId.value == null) {
    lotes.value = [];
    return;
  }
  cargandoLotes.value = true;
  try {
    lotes.value = await listLots(loteItemId.value);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar los lotes.') });
  } finally {
    cargandoLotes.value = false;
  }
}

async function crearLoteNuevo() {
  if (loteItemId.value == null) return;
  guardando.value = true;
  try {
    await createLot({
      item_id: loteItemId.value,
      lot_number: formLote.lot_number.trim(),
      ...(formLote.supplier_lot_ref ? { supplier_lot_ref: formLote.supplier_lot_ref } : {}),
      ...(formLote.production_date ? { production_date: formLote.production_date } : {}),
      ...(formLote.expiry_date ? { expiry_date: formLote.expiry_date } : {}),
      ...(formLote.notes ? { notes: formLote.notes } : {}),
    });
    dlgLote.value = false;
    $q.notify({ type: 'positive', message: 'Lote creado.' });
    Object.assign(formLote, {
      lot_number: '',
      supplier_lot_ref: '',
      production_date: '',
      expiry_date: '',
      notes: '',
    });
    await cargarLotes();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear el lote.') });
  } finally {
    guardando.value = false;
  }
}

// --- Etiquetas con código de barras (Ola C) ---------------------------------------
const seleccionEtiquetas = ref<InventoryItem[]>([]);
const dlgEtiquetas = ref(false);
const etiquetasCopias = ref(1);

function abrirEtiquetas() {
  etiquetasCopias.value = 1;
  dlgEtiquetas.value = true;
}

function imprimirEtiquetas() {
  const copias = Math.max(1, Math.min(100, Number(etiquetasCopias.value) || 1));
  const etiquetas: string[] = [];
  for (const it of seleccionEtiquetas.value) {
    const codigo = (it.barcode || it.sku).trim();
    const svg = code128Svg(codigo, { height: 44, moduleWidth: 2 });
    if (!svg) continue;
    const precio = it.sale_price != null ? formatMoney(it.sale_price) : '';
    const una = `<div class="et">
      <div class="et-nombre">${it.name}</div>
      ${precio ? `<div class="et-precio">${precio}</div>` : ''}
      <div class="et-barcode">${svg}</div>
      <div class="et-codigo">${codigo}</div>
    </div>`;
    for (let i = 0; i < copias; i++) etiquetas.push(una);
  }
  if (!etiquetas.length) {
    $q.notify({ type: 'warning', message: 'Ningún artículo seleccionado tiene código imprimible.' });
    return;
  }
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Etiquetas</title>
<style>
  body { font-family: Arial, sans-serif; margin: 4mm; }
  .grid { display: flex; flex-wrap: wrap; gap: 3mm; }
  .et { width: 50mm; height: 30mm; border: 1px dashed #bbb; padding: 1.5mm;
        display: flex; flex-direction: column; align-items: center; justify-content: space-between;
        overflow: hidden; box-sizing: border-box; }
  .et-nombre { font-size: 9px; font-weight: bold; text-align: center; line-height: 1.1;
               max-height: 22px; overflow: hidden; }
  .et-precio { font-size: 13px; font-weight: 800; }
  .et-barcode svg { max-width: 46mm; height: 11mm; }
  .et-codigo { font-size: 8px; letter-spacing: 1px; }
  @media print { .et { border: none; } @page { margin: 4mm; } }
</style></head><body><div class="grid">${etiquetas.join('')}</div></body></html>`;
  const win = window.open('', '_blank', 'width=900,height=700');
  if (!win) {
    $q.notify({ type: 'warning', message: 'El navegador bloqueó la ventana de etiquetas.' });
    return;
  }
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 300);
  dlgEtiquetas.value = false;
}

onMounted(recargarTodo);
</script>

<style scoped>
.cat-tabs {
  color: var(--app-text-muted);
}

.cat-panels {
  background: transparent;
}

.cat-lote-sel {
  width: 320px;
}

.cat-precio-fila {
  display: flex;
  gap: var(--app-space-3);
}

.cat-precio-fila > * {
  flex: 1;
}
</style>
