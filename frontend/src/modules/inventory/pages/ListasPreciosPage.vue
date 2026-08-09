<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton to="/inventario" />
    </div>
    <PageHeader
      title="Listas de precios"
      subtitle="Precios por artículo y cantidad (tramos de mayoreo) y a quién aplican (cliente o segmento). El precio de venta lo resuelve siempre el servidor; aquí solo se administran las listas."
      :loading="loading"
      @refresh="reload"
    />

    <div class="row q-col-gutter-md">
      <!-- ===== Listas ===== -->
      <div class="col-12 col-md-4">
        <q-card flat bordered class="app-card">
          <q-card-section class="row items-center justify-between">
            <div class="text-subtitle1">Listas</div>
            <q-btn dense unelevated no-caps color="primary" icon="add" label="Nueva" @click="abrirAltaLista" />
          </q-card-section>
          <q-separator />
          <q-list separator>
            <q-item
              v-for="pl in listas"
              :key="pl.id"
              clickable
              :active="pl.id === selId"
              active-class="lista--activa"
              @click="seleccionar(pl.id)"
            >
              <q-item-section>
                <q-item-label>{{ pl.name }}</q-item-label>
                <q-item-label caption>{{ pl.currency }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-chip dense square :color="pl.is_active ? 'positive' : 'grey'" text-color="white" size="sm" :label="pl.is_active ? 'Activa' : 'Inactiva'" />
              </q-item-section>
            </q-item>
            <q-item v-if="!listas.length && !loading">
              <q-item-section class="text-muted">Sin listas de precios. Crea la primera.</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>

      <!-- ===== Detalle ===== -->
      <div class="col-12 col-md-8">
        <q-card v-if="detalle" flat bordered class="app-card">
          <q-card-section class="row items-center justify-between">
            <div>
              <div class="text-h6">{{ detalle.name }}</div>
              <div class="text-caption text-muted">{{ detalle.currency }} · {{ detalle.is_active ? 'Activa' : 'Inactiva' }}</div>
            </div>
            <q-btn dense flat no-caps icon="edit" label="Editar" @click="abrirEdicion" />
          </q-card-section>
          <q-separator />

          <!-- Tramos -->
          <q-card-section>
            <div class="row items-center justify-between q-mb-sm">
              <div class="text-subtitle1">Tramos de precio</div>
              <q-btn dense unelevated no-caps color="primary" icon="add" label="Agregar tramo" @click="abrirTramo" />
            </div>
            <q-table
              :rows="detalle.items"
              :columns="itemCols"
              row-key="id"
              flat
              bordered
              dense
              :pagination="{ rowsPerPage: 0 }"
              hide-bottom
              no-data-label="Sin tramos. Agrega artículo + cantidad mínima + precio."
            >
              <template #body-cell-acciones="props">
                <q-td :props="props" class="q-gutter-xs">
                  <q-btn dense flat round size="sm" color="negative" icon="delete" aria-label="Eliminar tramo de precio" @click="borrarTramo(props.row)" />
                </q-td>
              </template>
            </q-table>
          </q-card-section>
          <q-separator />

          <!-- Asignaciones -->
          <q-card-section>
            <div class="row items-center justify-between q-mb-sm">
              <div class="text-subtitle1">Aplica a</div>
              <q-btn dense unelevated no-caps color="primary" icon="add" label="Asignar" @click="abrirAsignacion" />
            </div>
            <q-table
              :rows="detalle.assignments"
              :columns="asgCols"
              row-key="id"
              flat
              bordered
              dense
              :pagination="{ rowsPerPage: 0 }"
              hide-bottom
              no-data-label="Sin asignaciones (aplica como lista general / por defecto)."
            >
              <template #body-cell-destino="props">
                <q-td :props="props">
                  <span v-if="props.row.party_id">Cliente #{{ props.row.party_id }}</span>
                  <q-chip v-else dense square color="secondary" text-color="white" size="sm" :label="'Segmento ' + props.row.segment" />
                </q-td>
              </template>
              <template #body-cell-acciones="props">
                <q-td :props="props" class="q-gutter-xs">
                  <q-btn dense flat round size="sm" color="negative" icon="delete" aria-label="Eliminar asignación de lista" @click="borrarAsignacion(props.row)" />
                </q-td>
              </template>
            </q-table>
          </q-card-section>
        </q-card>
        <q-card v-else flat bordered class="app-card">
          <q-card-section class="text-muted">Selecciona una lista para ver sus tramos y asignaciones.</q-card-section>
        </q-card>
      </div>
    </div>

    <!-- Alta / edición de lista -->
    <q-dialog v-model="listaOpen">
      <q-card class="app-dialog" style="width: min(360px, calc(100vw - 32px))">
        <q-card-section class="text-h6">{{ editId ? 'Editar lista' : 'Nueva lista de precios' }}</q-card-section>
        <q-card-section class="q-gutter-md">
          <q-input v-model="fLista.name" label="Nombre *" outlined dense />
          <q-input v-model="fLista.currency" label="Moneda" outlined dense maxlength="8" hint="NIO, USD…" />
          <q-toggle v-model="fLista.is_active" label="Activa" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" :label="editId ? 'Guardar' : 'Crear'" :loading="guardando" :disable="!fLista.name.trim()" @click="guardarLista" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Tramo -->
    <q-dialog v-model="tramoOpen">
      <q-card class="app-dialog" style="width: min(380px, calc(100vw - 32px))">
        <q-card-section class="text-h6">Agregar tramo de precio</q-card-section>
        <q-card-section class="q-gutter-md">
          <ItemSelect v-model="fTramo.item_id" label="Artículo *" @selected="onItemSel" />
          <div class="row q-col-gutter-md">
            <q-input class="col" v-model.number="fTramo.min_qty" type="number" min="0" step="0.0001" label="Cantidad mínima" outlined dense />
            <q-input class="col" v-model.number="fTramo.price" type="number" min="0" step="0.0001" label="Precio *" outlined dense />
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Agregar" :loading="guardando" :disable="!fTramo.item_id || !(fTramo.price > 0)" @click="guardarTramo" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Asignación -->
    <q-dialog v-model="asgOpen">
      <q-card class="app-dialog" style="width: min(380px, calc(100vw - 32px))">
        <q-card-section class="text-h6">Asignar lista</q-card-section>
        <q-card-section class="q-gutter-md">
          <q-option-group v-model="asgTipo" :options="asgTipoOpts" color="primary" inline />
          <PartySelect v-if="asgTipo === 'party'" v-model="fAsg.party_id" role="CUSTOMER" label="Cliente *" />
          <q-input v-else v-model="fAsg.segment" label="Segmento *" outlined dense hint="Ej. MAYORISTA, VIP" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Asignar" :loading="guardando" :disable="!asgValida" @click="guardarAsignacion" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { LatestRequest } from 'src/core/latest-request';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import ItemSelect from 'src/modules/inventory/components/ItemSelect.vue';
import PartySelect from 'src/modules/parties/components/PartySelect.vue';
import { apiErrorMessage } from 'src/core/api';
import {
  PRICELIST_MENSAJES,
  createPriceList,
  createPriceListAssignment,
  deletePriceListAssignment,
  deletePriceListItem,
  getPriceList,
  listItems,
  listPriceLists,
  updatePriceList,
  upsertPriceListItem,
  type InventoryItem,
  type PriceListAssignmentRow,
  type PriceListDetail,
  type PriceListItemRow,
  type PriceListRow,
} from 'src/modules/inventory/api';

const $q = useQuasar();
const listas = ref<PriceListRow[]>([]);
const detalle = ref<PriceListDetail | null>(null);
const selId = ref<number | null>(null);
const loading = ref(false);
const detalleLoading = ref(false);
const selectionRequests = new LatestRequest();
const guardando = ref(false);
const itemNames = ref<Map<number, string>>(new Map());

function nombreItem(id: number): string {
  return itemNames.value.get(id) ?? `Art. #${id}`;
}
function fail(e: unknown, fallback: string) {
  const code = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  const msg = code && PRICELIST_MENSAJES[code] ? PRICELIST_MENSAJES[code] : apiErrorMessage(e, fallback);
  $q.notify({ type: 'negative', message: msg });
}

const itemCols: QTableColumn<PriceListItemRow>[] = [
  { name: 'item', label: 'Artículo', field: (r) => nombreItem(r.item_id), align: 'left' },
  { name: 'min_qty', label: 'Cant. mínima', field: 'min_qty', align: 'right' },
  { name: 'price', label: 'Precio', field: 'price', align: 'right' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];
const asgCols: QTableColumn<PriceListAssignmentRow>[] = [
  { name: 'destino', label: 'Destino', field: 'id', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

async function reload() {
  loading.value = true;
  try {
    listas.value = await listPriceLists();
    if (selId.value && !listas.value.some((l) => l.id === selId.value)) {
      selId.value = null;
      detalle.value = null;
    }
  } catch (e) {
    fail(e, 'No se pudieron cargar las listas.');
  } finally {
    loading.value = false;
  }
}
async function seleccionar(id: number) {
  const isCurrent = selectionRequests.begin();
  selId.value = id;
  detalle.value = null;
  detalleLoading.value = true;
  try {
    const result = await getPriceList(id);
    if (isCurrent() && selId.value === id) detalle.value = result;
  } catch (e) {
    if (isCurrent()) fail(e, 'No se pudo cargar la lista.');
  } finally {
    if (isCurrent()) detalleLoading.value = false;
  }
}
async function refrescarDetalle() {
  if (selId.value) await seleccionar(selId.value);
}

// ---- alta/edición lista ----
const listaOpen = ref(false);
const editId = ref<number | null>(null);
const fLista = ref<{ name: string; currency: string; is_active: boolean }>({ name: '', currency: 'NIO', is_active: true });
function abrirAltaLista() {
  editId.value = null;
  fLista.value = { name: '', currency: 'NIO', is_active: true };
  listaOpen.value = true;
}
function abrirEdicion() {
  if (!detalle.value) return;
  editId.value = detalle.value.id;
  fLista.value = { name: detalle.value.name, currency: detalle.value.currency, is_active: detalle.value.is_active };
  listaOpen.value = true;
}
async function guardarLista() {
  if (!fLista.value.name.trim()) return;
  guardando.value = true;
  try {
    if (editId.value) {
      await updatePriceList(editId.value, fLista.value);
      $q.notify({ type: 'positive', message: 'Lista actualizada.' });
    } else {
      const creada = await createPriceList(fLista.value);
      selId.value = creada.id;
      detalle.value = creada;
      $q.notify({ type: 'positive', message: 'Lista creada.' });
    }
    listaOpen.value = false;
    await reload();
    await refrescarDetalle();
  } catch (e) {
    fail(e, 'No se pudo guardar la lista.');
  } finally {
    guardando.value = false;
  }
}

// ---- tramo ----
const tramoOpen = ref(false);
const fTramo = ref<{ item_id: number | null; min_qty: number; price: number }>({ item_id: null, min_qty: 0, price: 0 });
function abrirTramo() {
  fTramo.value = { item_id: null, min_qty: 0, price: 0 };
  tramoOpen.value = true;
}
function onItemSel(item: InventoryItem | null) {
  if (item) itemNames.value.set(item.id, item.name);
}
async function guardarTramo() {
  if (!selId.value || !fTramo.value.item_id || !(fTramo.value.price > 0)) return;
  guardando.value = true;
  try {
    await upsertPriceListItem(selId.value, {
      item_id: fTramo.value.item_id,
      min_qty: fTramo.value.min_qty,
      price: fTramo.value.price,
    });
    $q.notify({ type: 'positive', message: 'Tramo guardado.' });
    tramoOpen.value = false;
    await refrescarDetalle();
  } catch (e) {
    fail(e, 'No se pudo guardar el tramo.');
  } finally {
    guardando.value = false;
  }
}
async function borrarTramo(row: PriceListItemRow) {
  if (!selId.value) return;
  try {
    await deletePriceListItem(selId.value, row.id);
    await refrescarDetalle();
  } catch (e) {
    fail(e, 'No se pudo eliminar el tramo.');
  }
}

// ---- asignación ----
const asgOpen = ref(false);
const asgTipo = ref<'party' | 'segment'>('party');
const asgTipoOpts = [
  { label: 'Cliente', value: 'party' },
  { label: 'Segmento', value: 'segment' },
];
const fAsg = ref<{ party_id: number | null; segment: string }>({ party_id: null, segment: '' });
const asgValida = computed(() => (asgTipo.value === 'party' ? !!fAsg.value.party_id : !!fAsg.value.segment.trim()));
function abrirAsignacion() {
  asgTipo.value = 'party';
  fAsg.value = { party_id: null, segment: '' };
  asgOpen.value = true;
}
async function guardarAsignacion() {
  if (!selId.value || !asgValida.value) return;
  guardando.value = true;
  try {
    const body = asgTipo.value === 'party' ? { party_id: fAsg.value.party_id } : { segment: fAsg.value.segment.trim() };
    await createPriceListAssignment(selId.value, body);
    $q.notify({ type: 'positive', message: 'Asignación creada.' });
    asgOpen.value = false;
    await refrescarDetalle();
  } catch (e) {
    fail(e, 'No se pudo asignar.');
  } finally {
    guardando.value = false;
  }
}
async function borrarAsignacion(row: PriceListAssignmentRow) {
  if (!selId.value) return;
  try {
    await deletePriceListAssignment(selId.value, row.id);
    await refrescarDetalle();
  } catch (e) {
    fail(e, 'No se pudo quitar la asignación.');
  }
}

onMounted(async () => {
  await reload();
  try {
    const items = await listItems({ is_active: true });
    const map = new Map<number, string>();
    for (const it of items) map.set(it.id, it.name);
    itemNames.value = map;
  } catch {
    /* noop: los tramos mostrarán "Art. #id" si no hay nombres */
  }
});
</script>

<style scoped>
.lista--activa {
  background: var(--app-primary-soft, rgba(0, 0, 0, 0.05));
  font-weight: 600;
}
</style>
