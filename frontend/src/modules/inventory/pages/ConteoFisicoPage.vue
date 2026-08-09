<template>
  <q-page class="app-page">
    <PageHeader
      title="Conteo físico y valorización"
      subtitle="Hoja de conteo con lo esperado → se cuenta lo real → las varianzas se aprueban (quien cuenta no aprueba) y se ajusta el kardex. La valorización muestra cuánto vale el inventario hoy."
      :loading="loading"
      @refresh="recargarTodo"
    >
      <template #actions>
        <q-btn
          v-if="puede('inventory.count.create') && tab === 'conteos'"
          unelevated
          no-caps
          color="primary"
          icon="post_add"
          label="Nueva hoja de conteo"
          @click="abrirCrear"
        />
      </template>
    </PageHeader>

    <q-tabs
      v-model="tab"
      dense
      no-caps
      align="left"
      active-color="primary"
      indicator-color="primary"
      class="cf-tabs"
    >
      <q-tab name="conteos" label="Conteos" />
      <q-tab name="valorizacion" label="Valorización" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <!-- ============== TAB CONTEOS ============== -->
    <template v-if="tab === 'conteos'">
      <q-table
        v-model:pagination="pagination"
        class="app-table"
        :rows="rows"
        :columns="columns"
        row-key="id"
        flat
        :loading="loading"
        :rows-per-page-options="[10, 25, 50, 100]"
        no-data-label="No hay hojas de conteo. Generá una para empezar."
        @request="onRequest"
        @row-click="(_, row) => abrirDetalle(row as PhysicalCountRow)"
      >
        <template #body-cell-estado="props">
          <q-td :props="props">
            <EstadoChip :estado="props.row.status" :map="MAPA_CONTEO" />
          </q-td>
        </template>
        <template #body-cell-fecha="props">
          <q-td :props="props">{{ formatDate(props.row.created_at) }}</q-td>
        </template>
      </q-table>

      <!-- Diálogo: nueva hoja -->
      <q-dialog v-model="dlgCrear">
        <q-card class="app-dialog">
          <q-card-section class="text-h6">Nueva hoja de conteo</q-card-section>
          <q-card-section class="app-form">
            <q-select
              v-model="formBodega"
              :options="opcionesBodega"
              outlined
              dense
              emit-value
              map-options
              label="Bodega *"
            />
            <q-input
              v-model="formCategoria"
              outlined
              dense
              label="Categoría (vacío = toda la bodega)"
            />
            <q-input v-model="formNotas" outlined dense label="Notas" />
            <div class="text-caption text-muted">
              La hoja congela lo ESPERADO al momento de generarla; después se captura lo
              contado sin que el sistema sugiera el valor (conteo ciego honesto).
            </div>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn flat no-caps label="Cancelar" v-close-popup />
            <q-btn
              unelevated
              no-caps
              color="primary"
              label="Generar hoja"
              :loading="guardando"
              :disable="formBodega == null"
              @click="crear"
            />
          </q-card-actions>
        </q-card>
      </q-dialog>

      <!-- Diálogo: detalle / captura / aprobación -->
      <q-dialog v-model="dlgDetalle" :maximized="$q.platform.is.mobile">
        <q-card class="app-dialog cf-detalle">
          <q-card-section class="row items-center">
            <div class="text-h6">
              Conteo #{{ detalle?.id }} · {{ detalle?.warehouse_name }}
            </div>
            <q-space />
            <EstadoChip v-if="detalle" :estado="detalle.status" :map="MAPA_CONTEO" />
          </q-card-section>
          <q-card-section v-if="detalle">
            <div class="text-caption text-muted q-mb-sm">
              Generada por {{ detalle.created_by || '—' }}
              <span v-if="detalle.counted_by"> · contó {{ detalle.counted_by }}</span>
              <span v-if="detalle.approved_by"> · aprobó {{ detalle.approved_by }}</span>
            </div>
            <q-markup-table flat dense class="app-table">
              <thead>
                <tr>
                  <th class="text-left">Artículo</th>
                  <th class="text-right">Esperado</th>
                  <th class="text-right" style="width: 130px">Contado</th>
                  <th class="text-right">Varianza</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="ln in detalle.lines" :key="ln.id">
                  <td>{{ ln.item_name }} <span class="text-muted">({{ ln.item_sku }})</span></td>
                  <td class="text-right">{{ formatQty(ln.qty_expected) }}</td>
                  <td>
                    <q-input
                      v-if="editable"
                      v-model="capturas[ln.id]"
                      dense
                      borderless
                      type="number"
                      min="0"
                      input-class="text-right"
                      placeholder="—"
                    />
                    <span v-else class="block text-right">
                      {{ ln.qty_counted != null ? formatQty(ln.qty_counted) : '—' }}
                    </span>
                  </td>
                  <td class="text-right" :class="claseVarianza(ln)">
                    {{ ln.variance != null ? formatQty(ln.variance) : '—' }}
                  </td>
                </tr>
              </tbody>
            </q-markup-table>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn
              v-if="detalle && editable && puede('inventory.count.create')"
              flat
              no-caps
              color="negative"
              label="Cancelar hoja"
              @click="cancelarHoja"
            />
            <q-btn flat no-caps label="Cerrar" v-close-popup />
            <q-btn
              v-if="detalle && editable && puede('inventory.count.capture')"
              unelevated
              no-caps
              color="primary"
              icon="save"
              label="Guardar lo contado"
              :loading="capturando"
              @click="capturar"
            />
            <q-btn
              v-if="detalle?.status === 'COUNTED' && puede('inventory.count.approve')"
              unelevated
              no-caps
              color="positive"
              icon="check"
              label="Aprobar y ajustar kardex"
              :loading="aprobando"
              @click="aprobar"
            />
          </q-card-actions>
        </q-card>
      </q-dialog>
    </template>

    <!-- ============== TAB VALORIZACIÓN ============== -->
    <template v-else>
      <div class="cf-val-filtros">
        <q-select
          v-model="valBodega"
          :options="[{ label: 'Todas las bodegas', value: null }, ...opcionesBodega]"
          outlined
          dense
          emit-value
          map-options
          label="Bodega"
          class="cf-val-filtros__sel"
          @update:model-value="cargarValorizacion"
        />
        <q-btn flat no-caps icon="print" label="Imprimir" @click="imprimirValorizacion" />
      </div>

      <div v-if="valorizacion" class="cf-val">
        <q-card flat bordered class="cf-val__total">
          <q-card-section>
            <div class="text-muted">Valor total del inventario (existencia × costo promedio)</div>
            <div class="cf-val__monto">{{ formatMoney(valorizacion.total_value) }}</div>
          </q-card-section>
        </q-card>

        <div class="cf-val__grupos">
          <q-markup-table flat dense class="app-table">
            <thead>
              <tr><th class="text-left">Bodega</th><th class="text-right">Artículos</th><th class="text-right">Valor</th></tr>
            </thead>
            <tbody>
              <tr v-for="g in valorizacion.by_warehouse" :key="g.warehouse_id">
                <td>{{ g.warehouse_name }}</td>
                <td class="text-right">{{ g.items }}</td>
                <td class="text-right">{{ formatMoney(g.value) }}</td>
              </tr>
            </tbody>
          </q-markup-table>
          <q-markup-table flat dense class="app-table">
            <thead>
              <tr><th class="text-left">Categoría</th><th class="text-right">Artículos</th><th class="text-right">Valor</th></tr>
            </thead>
            <tbody>
              <tr v-for="g in valorizacion.by_category" :key="g.category">
                <td>{{ g.category }}</td>
                <td class="text-right">{{ g.items }}</td>
                <td class="text-right">{{ formatMoney(g.value) }}</td>
              </tr>
            </tbody>
          </q-markup-table>
        </div>

        <q-table
          class="app-table q-mt-md"
          :rows="valorizacion.detail"
          :columns="columnasValor"
          row-key="item_id"
          flat
          dense
          :pagination="{ rowsPerPage: 25 }"
          no-data-label="Sin existencias con valor."
        >
          <template #body-cell-existencia="props">
            <q-td :props="props">{{ formatQty(props.row.qty_on_hand) }}</q-td>
          </template>
          <template #body-cell-costo="props">
            <q-td :props="props">{{ formatMoney(props.row.avg_cost) }}</q-td>
          </template>
          <template #body-cell-valor="props">
            <q-td :props="props" class="text-weight-bold">{{ formatMoney(props.row.value) }}</q-td>
          </template>
        </q-table>
      </div>
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import type { QTableColumn } from 'quasar';
import EstadoChip from 'src/components/EstadoChip.vue';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { formatDate, formatMoney, formatQty } from 'src/core/format';
import {
  approvePhysicalCount,
  cancelPhysicalCount,
  capturePhysicalCount,
  COUNT_STATUS_LABELS,
  createPhysicalCount,
  getInventoryValuation,
  getPhysicalCount,
  listPhysicalCountsPage,
  listWarehouses,
  type InventoryValuation,
  type PhysicalCountDetail,
  type PhysicalCountLine,
  type PhysicalCountRow,
  type Warehouse,
} from 'src/modules/inventory/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const MAPA_CONTEO = {
  OPEN: { color: 'blue-7', label: COUNT_STATUS_LABELS.OPEN },
  COUNTED: { color: 'orange-8', label: COUNT_STATUS_LABELS.COUNTED },
  POSTED: { color: 'positive', label: COUNT_STATUS_LABELS.POSTED },
  CANCELLED: { color: 'negative', label: COUNT_STATUS_LABELS.CANCELLED, outline: true },
};

const MENSAJES_CONTEO: Record<string, string> = {
  INVENTORY_COUNT_SOD_SELF_APPROVAL: 'Quien contó no puede aprobar: debe aprobar otra persona.',
  INVENTORY_COUNT_NO_ITEMS: 'Esa bodega (o categoría) no tiene existencias registradas para contar.',
  INVENTORY_COUNT_NOT_OPEN: 'La hoja ya no está abierta.',
  INVENTORY_COUNT_NOT_COUNTED: 'La hoja aún no está contada por completo (o ya fue posteada).',
  INVENTORY_COUNT_QTY_INVALID: 'Hay una cantidad contada inválida.',
  INVENTORY_COUNT_NOT_FOUND: 'No se encontró la hoja de conteo.',
};

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

function notificarError(e: unknown, fallback: string) {
  const crudo = apiErrorMessage(e, fallback);
  $q.notify({ type: 'negative', message: MENSAJES_CONTEO[crudo] ?? crudo });
}

const tab = ref('conteos');

// --- Conteos ---
// Paginación server-side: las hojas de conteo se acumulan (antes truncaba a 200).
const { rows, loading, pagination, onRequest, reload } = useListadoServer<PhysicalCountRow>(
  (page) => listPhysicalCountsPage({}, page),
  { errorMessage: 'No se pudieron cargar los conteos.' },
);

const columns: QTableColumn<PhysicalCountRow>[] = [
  { name: 'id', label: '#', field: 'id', align: 'left' },
  { name: 'bodega', label: 'Bodega', field: 'warehouse_name', align: 'left' },
  { name: 'categoria', label: 'Categoría', field: (r) => r.category || 'toda la bodega', align: 'left' },
  { name: 'lineas', label: 'Líneas', field: 'lines', align: 'right' },
  { name: 'conto', label: 'Contó', field: (r) => r.counted_by ?? '—', align: 'left' },
  { name: 'fecha', label: 'Creada', field: 'created_at', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
];

// --- Bodegas (compartidas entre crear y valorización) ---
const bodegas = ref<Warehouse[]>([]);
const opcionesBodega = computed(() => bodegas.value.map((w) => ({ label: w.name, value: w.id })));

// --- Crear ---
const dlgCrear = ref(false);
const guardando = ref(false);
const formBodega = ref<number | null>(null);
const formCategoria = ref('');
const formNotas = ref('');

function abrirCrear() {
  formBodega.value = bodegas.value.find((w) => w.is_default)?.id ?? bodegas.value[0]?.id ?? null;
  formCategoria.value = '';
  formNotas.value = '';
  dlgCrear.value = true;
}

async function crear() {
  if (formBodega.value == null) return;
  guardando.value = true;
  try {
    const det = await createPhysicalCount({
      warehouse_id: formBodega.value,
      ...(formCategoria.value ? { category: formCategoria.value } : {}),
      ...(formNotas.value ? { notes: formNotas.value } : {}),
    });
    dlgCrear.value = false;
    $q.notify({ type: 'positive', message: `Hoja #${det.id} generada con ${det.lines.length} líneas.` });
    await reload();
    mostrarDetalle(det);
  } catch (e) {
    notificarError(e, 'No se pudo generar la hoja.');
  } finally {
    guardando.value = false;
  }
}

// --- Detalle / captura / aprobación ---
const dlgDetalle = ref(false);
const detalle = ref<PhysicalCountDetail | null>(null);
const capturas = ref<Record<number, string>>({});
const capturando = ref(false);
const aprobando = ref(false);

const editable = computed(
  () => detalle.value?.status === 'OPEN' || detalle.value?.status === 'COUNTED',
);

function claseVarianza(ln: PhysicalCountLine): string {
  if (ln.variance == null) return '';
  const v = Number(ln.variance);
  return v === 0 ? 'text-positive' : 'text-negative text-weight-bold';
}

function mostrarDetalle(det: PhysicalCountDetail) {
  detalle.value = det;
  capturas.value = Object.fromEntries(
    det.lines.map((ln) => [ln.id, ln.qty_counted != null ? String(Number(ln.qty_counted)) : '']),
  );
  dlgDetalle.value = true;
}

async function abrirDetalle(row: PhysicalCountRow) {
  try {
    mostrarDetalle(await getPhysicalCount(row.id));
  } catch (e) {
    notificarError(e, 'No se pudo cargar el conteo.');
  }
}

async function capturar() {
  if (!detalle.value) return;
  const lines = Object.entries(capturas.value)
    .filter(([, v]) => v !== '' && v != null)
    .map(([id, v]) => ({ line_id: Number(id), qty_counted: String(v) }));
  if (!lines.length) {
    $q.notify({ type: 'warning', message: 'No hay cantidades capturadas.' });
    return;
  }
  capturando.value = true;
  try {
    const det = await capturePhysicalCount(detalle.value.id, lines);
    mostrarDetalle(det);
    await reload();
    $q.notify({
      type: det.status === 'COUNTED' ? 'positive' : 'info',
      message:
        det.status === 'COUNTED'
          ? 'Conteo completo: revisá las varianzas y mandá a aprobar.'
          : `Guardado; faltan ${det.pending_lines} líneas por contar.`,
    });
  } catch (e) {
    notificarError(e, 'No se pudo guardar lo contado.');
  } finally {
    capturando.value = false;
  }
}

async function aprobar() {
  if (!detalle.value) return;
  aprobando.value = true;
  try {
    const det = await approvePhysicalCount(detalle.value.id);
    mostrarDetalle(det);
    await reload();
    $q.notify({
      type: 'positive',
      message: `Conteo aprobado: ${det.adjusted_lines} ajuste(s) posteados al kardex.`,
    });
  } catch (e) {
    notificarError(e, 'No se pudo aprobar el conteo.');
  } finally {
    aprobando.value = false;
  }
}

async function cancelarHoja() {
  if (!detalle.value) return;
  try {
    await cancelPhysicalCount(detalle.value.id);
    dlgDetalle.value = false;
    await reload();
    $q.notify({ type: 'info', message: 'Hoja cancelada.' });
  } catch (e) {
    notificarError(e, 'No se pudo cancelar.');
  }
}

// --- Valorización ---
const valorizacion = ref<InventoryValuation | null>(null);
const valBodega = ref<number | null>(null);

const columnasValor: QTableColumn[] = [
  { name: 'sku', label: 'SKU', field: 'sku', align: 'left' },
  { name: 'nombre', label: 'Artículo', field: 'name', align: 'left' },
  { name: 'categoria', label: 'Categoría', field: (r) => r.category || '—', align: 'left' },
  { name: 'bodega', label: 'Bodega', field: 'warehouse_name', align: 'left' },
  { name: 'existencia', label: 'Existencia', field: 'qty_on_hand', align: 'right' },
  { name: 'costo', label: 'Costo prom.', field: 'avg_cost', align: 'right' },
  { name: 'valor', label: 'Valor', field: 'value', align: 'right' },
];

async function cargarValorizacion() {
  try {
    valorizacion.value = await getInventoryValuation(valBodega.value ?? undefined);
  } catch (e) {
    notificarError(e, 'No se pudo cargar la valorización.');
  }
}

function imprimirValorizacion() {
  window.print();
}

async function recargarTodo() {
  await Promise.all([reload(), cargarValorizacion()]);
}

onMounted(async () => {
  try {
    bodegas.value = await listWarehouses();
  } catch {
    bodegas.value = [];
  }
  void cargarValorizacion();
});
</script>

<style scoped>
.cf-tabs {
  margin-bottom: var(--app-space-1);
}

.cf-detalle {
  min-width: min(760px, 95vw);
}

.cf-val-filtros {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}

.cf-val-filtros__sel {
  width: 260px;
}

.cf-val__total {
  margin-bottom: var(--app-space-3);
  max-width: 480px;
}

.cf-val__monto {
  font-size: 1.6rem;
  font-weight: 800;
}

.cf-val__grupos {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: var(--app-space-3);
}
</style>
