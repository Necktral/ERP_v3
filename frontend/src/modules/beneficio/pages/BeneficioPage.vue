<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton to="/tablero" />
    </div>
    <PageHeader
      title="Beneficio de café"
      subtitle="Transformación insumo → producto con merma. Recetas (rendimiento esperado) y órdenes que consumen insumo y reciben el producto terminado en bodega."
      :loading="loadingOrders || loadingRecipes"
      @refresh="reloadAll"
    />

    <q-tabs v-model="tab" align="left" dense class="text-primary q-mb-md" narrow-indicator>
      <q-tab name="ordenes" no-caps label="Órdenes" />
      <q-tab name="recetas" no-caps label="Recetas" />
    </q-tabs>

    <!-- ===== ÓRDENES ===== -->
    <div v-if="tab === 'ordenes'">
      <div class="q-mb-md">
        <q-btn
          unelevated
          no-caps
          color="primary"
          icon="add"
          label="Nueva orden"
          :disable="!recetas.length"
          @click="abrirAltaOrden"
        />
        <span v-if="!recetas.length" class="text-muted q-ml-sm text-caption">
          Crea primero una receta.
        </span>
      </div>
      <!-- módulo dormido: carga completa client-side a propósito; revisar si el módulo se activa -->
      <q-table
        :rows="orders"
        :columns="orderCols"
        row-key="id"
        flat
        bordered
        :loading="loadingOrders"
        :pagination="{ rowsPerPage: 15, sortBy: 'id', descending: true }"
        no-data-label="Sin órdenes de beneficio."
      >
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-chip dense square :color="orderColor(props.row.status)" text-color="white" :label="ORDER_STATUS_LABELS[props.row.status]" />
          </q-td>
        </template>
        <template #body-cell-acciones="props">
          <q-td :props="props" class="q-gutter-xs">
            <q-btn v-if="props.row.status === 'DRAFT'" dense unelevated no-caps size="sm" color="primary" label="Iniciar" @click="accion(startOrder, props.row.id)" />
            <q-btn v-if="props.row.status === 'IN_PROCESS'" dense unelevated no-caps size="sm" color="positive" label="Cerrar" @click="abrirCierre(props.row)" />
            <q-btn v-if="props.row.status === 'DONE'" dense flat no-caps size="sm" icon="insights" label="Resultado" @click="verResultado(props.row)" />
            <q-btn v-if="props.row.status === 'DRAFT' || props.row.status === 'IN_PROCESS'" dense flat no-caps size="sm" color="negative" label="Anular" @click="accion(cancelOrder, props.row.id)" />
          </q-td>
        </template>
      </q-table>
    </div>

    <!-- ===== RECETAS ===== -->
    <div v-else>
      <div class="q-mb-md">
        <q-btn unelevated no-caps color="primary" icon="add" label="Nueva receta" @click="abrirAltaReceta" />
      </div>
      <!-- módulo dormido: carga completa client-side a propósito; revisar si el módulo se activa -->
      <q-table
        :rows="recetas"
        :columns="recipeCols"
        row-key="id"
        flat
        bordered
        :loading="loadingRecipes"
        :pagination="{ rowsPerPage: 15, sortBy: 'code' }"
        no-data-label="Sin recetas de transformación."
      />
    </div>

    <!-- Alta orden -->
    <q-dialog v-model="ordenOpen">
      <q-card class="app-dialog" style="min-width: 440px">
        <q-card-section class="text-h6">Nueva orden de beneficio</q-card-section>
        <q-card-section class="q-gutter-md">
          <q-select v-model="fOrden.recipe_id" :options="recetaOpts" label="Receta *" outlined dense emit-value map-options options-dense />
          <q-select v-model="fOrden.input_warehouse_id" :options="bodegaOpts" label="Bodega de entrada (insumo) *" outlined dense emit-value map-options options-dense />
          <q-select v-model="fOrden.output_warehouse_id" :options="bodegaOpts" label="Bodega de salida (producto) *" outlined dense emit-value map-options options-dense />
          <q-input v-model.number="fOrden.input_qty" type="number" min="0" step="0.01" label="Cantidad de insumo *" outlined dense />
          <q-input v-model="fOrden.reference" label="Referencia" outlined dense />
          <q-input v-model="fOrden.note" type="textarea" autogrow label="Nota" outlined dense />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Crear" :loading="guardando" :disable="!ordenValida" @click="guardarOrden" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Cerrar orden -->
    <q-dialog v-model="cierreOpen">
      <q-card class="app-dialog" style="min-width: 360px">
        <q-card-section class="text-h6">Cerrar orden · {{ cierreOrden?.reference || cierreOrden?.id }}</q-card-section>
        <q-card-section class="q-gutter-md">
          <div class="text-caption text-muted">
            Insumo consumido: {{ cierreOrden?.input_qty }}. Indica el producto terminado obtenido.
          </div>
          <q-input v-model.number="cierreOutputQty" type="number" min="0" step="0.01" label="Producto obtenido *" outlined dense autofocus />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="positive" label="Cerrar" :loading="guardando" :disable="!cierreOutputQty || cierreOutputQty <= 0" @click="confirmarCierre" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Resultado -->
    <q-dialog v-model="resultadoOpen">
      <q-card class="app-dialog" style="min-width: 380px">
        <q-card-section class="text-h6">Resultado · {{ resultado?.reference || resultado?.id }}</q-card-section>
        <q-card-section v-if="resultado">
          <div class="dep-row"><span>Insumo consumido</span><b>{{ resultado.input_qty }}</b></div>
          <div class="dep-row"><span>Producto obtenido</span><b>{{ resultado.output_qty }}</b></div>
          <div class="dep-row dep-row--hi"><span>Rendimiento</span><b>{{ pct(resultado.yield_pct) }}</b></div>
          <div class="dep-row"><span>Merma</span><b>{{ resultado.shrinkage_qty }}</b></div>
          <q-separator class="q-my-sm" />
          <div class="dep-row"><span>Costo del insumo</span><b>{{ resultado.input_cost_total }}</b></div>
          <div class="dep-row dep-row--hi"><span>Costo unitario del producto</span><b>{{ resultado.output_unit_cost }}</b></div>
        </q-card-section>
        <q-card-actions align="right"><q-btn flat no-caps label="Cerrar" v-close-popup /></q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Alta receta -->
    <q-dialog v-model="recetaOpen">
      <q-card class="app-dialog" style="min-width: 440px">
        <q-card-section class="text-h6">Nueva receta de transformación</q-card-section>
        <q-card-section class="q-gutter-md">
          <div class="row q-col-gutter-md">
            <q-input class="col" v-model="fReceta.code" label="Código *" outlined dense />
            <q-input class="col" v-model="fReceta.name" label="Nombre *" outlined dense />
          </div>
          <ItemSelect v-model="fReceta.input_item_id" label="Artículo insumo (entra) *" />
          <ItemSelect v-model="fReceta.output_item_id" label="Artículo producto (sale) *" />
          <div class="row q-col-gutter-md">
            <q-input class="col" v-model.number="fReceta.expected_yield_pct" type="number" min="0" max="100" step="0.01" label="Rendimiento esperado % *" outlined dense />
            <q-input class="col" v-model.number="fReceta.yield_tolerance_pct" type="number" min="0" max="100" step="0.01" label="Tolerancia %" outlined dense />
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Crear" :loading="guardando" :disable="!recetaValida" @click="guardarReceta" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import ItemSelect from 'src/modules/inventory/components/ItemSelect.vue';
import { useListado } from 'src/core/composables/useListado';
import { apiErrorMessage } from 'src/core/api';
import { listWarehouses } from 'src/modules/inventory/api';
import {
  BENEFICIO_MENSAJES,
  ORDER_STATUS_LABELS,
  cancelOrder,
  closeOrder,
  createOrder,
  createRecipe,
  listOrders,
  listRecipes,
  startOrder,
  type OrderRow,
  type OrderStatus,
  type RecipeRow,
} from 'src/modules/beneficio/api';

const $q = useQuasar();
const tab = ref<'ordenes' | 'recetas'>('ordenes');
const { rows: orders, loading: loadingOrders, reload: reloadOrders } = useListado<OrderRow>(() => listOrders());
const { rows: recetas, loading: loadingRecipes, reload: reloadRecipes } = useListado<RecipeRow>(listRecipes);

function reloadAll() {
  void reloadOrders();
  void reloadRecipes();
}

interface Opt {
  label: string;
  value: number;
}
const recetaOpts = ref<Opt[]>([]);
const bodegaOpts = ref<Opt[]>([]);
const guardando = ref(false);

function pct(v: string | null): string {
  return v == null ? '—' : `${v}%`;
}
function orderColor(s: OrderStatus): string {
  return { DRAFT: 'grey', IN_PROCESS: 'info', DONE: 'positive', CANCELLED: 'negative' }[s];
}
function fail(e: unknown, fallback: string) {
  // Las acciones de negocio devuelven {error:{code,message}}; mapeamos el código a español.
  const code = (e as { response?: { data?: { error?: { code?: string } } } })?.response?.data?.error?.code;
  const msg = code && BENEFICIO_MENSAJES[code] ? BENEFICIO_MENSAJES[code] : apiErrorMessage(e, fallback);
  $q.notify({ type: 'negative', message: msg });
}

const orderCols: QTableColumn<OrderRow>[] = [
  { name: 'id', label: '#', field: 'id', align: 'left', sortable: true },
  { name: 'reference', label: 'Referencia', field: 'reference', align: 'left' },
  { name: 'recipe_code', label: 'Receta', field: 'recipe_code', align: 'left', sortable: true },
  { name: 'input_qty', label: 'Insumo', field: 'input_qty', align: 'right' },
  { name: 'output_qty', label: 'Producto', field: (r) => r.output_qty ?? '—', align: 'right' },
  { name: 'yield_pct', label: 'Rend.', field: (r) => (r.yield_pct ? `${r.yield_pct}%` : '—'), align: 'right' },
  { name: 'status', label: 'Estado', field: 'status', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];
const recipeCols: QTableColumn<RecipeRow>[] = [
  { name: 'code', label: 'Código', field: 'code', align: 'left', sortable: true },
  { name: 'name', label: 'Nombre', field: 'name', align: 'left', sortable: true },
  { name: 'input_item_name', label: 'Insumo (entra)', field: 'input_item_name', align: 'left' },
  { name: 'output_item_name', label: 'Producto (sale)', field: 'output_item_name', align: 'left' },
  { name: 'expected_yield_pct', label: 'Rend. esperado', field: (r) => `${r.expected_yield_pct}%`, align: 'right' },
  { name: 'yield_tolerance_pct', label: 'Tolerancia', field: (r) => `±${r.yield_tolerance_pct}%`, align: 'right' },
];

// ---- alta orden ----
const ordenOpen = ref(false);
const fOrden = ref<{
  recipe_id: number | null;
  input_warehouse_id: number | null;
  output_warehouse_id: number | null;
  input_qty: number;
  reference: string;
  note: string;
}>({ recipe_id: null, input_warehouse_id: null, output_warehouse_id: null, input_qty: 0, reference: '', note: '' });
const ordenValida = computed(
  () => !!fOrden.value.recipe_id && !!fOrden.value.input_warehouse_id && !!fOrden.value.output_warehouse_id && fOrden.value.input_qty > 0,
);
function abrirAltaOrden() {
  const defWh = bodegaOpts.value[0]?.value ?? null;
  fOrden.value = { recipe_id: recetaOpts.value[0]?.value ?? null, input_warehouse_id: defWh, output_warehouse_id: defWh, input_qty: 0, reference: '', note: '' };
  ordenOpen.value = true;
}
async function guardarOrden() {
  if (!ordenValida.value) return;
  guardando.value = true;
  try {
    await createOrder({
      recipe_id: fOrden.value.recipe_id as number,
      input_warehouse_id: fOrden.value.input_warehouse_id as number,
      output_warehouse_id: fOrden.value.output_warehouse_id as number,
      input_qty: fOrden.value.input_qty,
      reference: fOrden.value.reference,
      note: fOrden.value.note,
    });
    $q.notify({ type: 'positive', message: 'Orden creada.' });
    ordenOpen.value = false;
    await reloadOrders();
  } catch (e) {
    fail(e, 'No se pudo crear la orden.');
  } finally {
    guardando.value = false;
  }
}

// ---- acciones simples (start/cancel) ----
async function accion(fn: (id: number) => Promise<unknown>, id: number) {
  guardando.value = true;
  try {
    await fn(id);
    await reloadOrders();
  } catch (e) {
    fail(e, 'No se pudo completar la acción.');
  } finally {
    guardando.value = false;
  }
}

// ---- cerrar orden ----
const cierreOpen = ref(false);
const cierreOrden = ref<OrderRow | null>(null);
const cierreOutputQty = ref(0);
function abrirCierre(o: OrderRow) {
  cierreOrden.value = o;
  cierreOutputQty.value = 0;
  cierreOpen.value = true;
}
async function confirmarCierre() {
  if (!cierreOrden.value || cierreOutputQty.value <= 0) return;
  guardando.value = true;
  try {
    await closeOrder(cierreOrden.value.id, cierreOutputQty.value);
    $q.notify({ type: 'positive', message: 'Orden cerrada.' });
    cierreOpen.value = false;
    await reloadOrders();
  } catch (e) {
    fail(e, 'No se pudo cerrar la orden.');
  } finally {
    guardando.value = false;
  }
}

// ---- resultado ----
const resultadoOpen = ref(false);
const resultado = ref<OrderRow | null>(null);
function verResultado(o: OrderRow) {
  resultado.value = o;
  resultadoOpen.value = true;
}

// ---- alta receta ----
const recetaOpen = ref(false);
const fReceta = ref<{
  code: string;
  name: string;
  input_item_id: number | null;
  output_item_id: number | null;
  expected_yield_pct: number;
  yield_tolerance_pct: number;
}>({ code: '', name: '', input_item_id: null, output_item_id: null, expected_yield_pct: 0, yield_tolerance_pct: 5 });
const recetaValida = computed(
  () => !!fReceta.value.code.trim() && !!fReceta.value.name.trim() && !!fReceta.value.input_item_id && !!fReceta.value.output_item_id && fReceta.value.expected_yield_pct > 0,
);
function abrirAltaReceta() {
  fReceta.value = { code: '', name: '', input_item_id: null, output_item_id: null, expected_yield_pct: 0, yield_tolerance_pct: 5 };
  recetaOpen.value = true;
}
async function guardarReceta() {
  if (!recetaValida.value) return;
  guardando.value = true;
  try {
    await createRecipe({
      code: fReceta.value.code.trim(),
      name: fReceta.value.name.trim(),
      input_item_id: fReceta.value.input_item_id as number,
      output_item_id: fReceta.value.output_item_id as number,
      expected_yield_pct: fReceta.value.expected_yield_pct,
      yield_tolerance_pct: fReceta.value.yield_tolerance_pct,
    });
    $q.notify({ type: 'positive', message: 'Receta creada.' });
    recetaOpen.value = false;
    await reloadRecipes();
    await cargarOpciones();
  } catch (e) {
    fail(e, 'No se pudo crear la receta.');
  } finally {
    guardando.value = false;
  }
}

async function cargarOpciones() {
  try {
    const [recs, whs] = await Promise.all([listRecipes(), listWarehouses()]);
    recetaOpts.value = recs.map((r) => ({ label: `${r.code} · ${r.name}`, value: r.id }));
    bodegaOpts.value = whs.filter((w) => w.is_active).map((w) => ({ label: `${w.code} · ${w.name}`, value: w.id }));
  } catch {
    /* noop: la pantalla degrada con tablas vacías */
  }
}

onMounted(cargarOpciones);
</script>

<style scoped>
.dep-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  padding: 2px 0;
  font-size: 0.9rem;
}
.dep-row--hi {
  color: var(--app-primary);
  font-weight: 600;
}
</style>
