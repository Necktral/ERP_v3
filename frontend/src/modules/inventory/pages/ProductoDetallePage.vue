<template>
  <q-page class="app-page">
    <PageHeader
      :title="item ? item.name : 'Ficha de producto'"
      :subtitle="item ? `${item.sku}${item.barcode ? ' · código ' + item.barcode : ''}` : 'Cargando…'"
      :loading="cargando"
      @refresh="cargar"
    >
      <template #actions>
        <BackButton to="/inventario" label="Existencias" />
        <q-btn
          v-if="item"
          flat
          no-caps
          icon="receipt_long"
          label="Kardex completo"
          :to="`/inventario/kardex?item_id=${item.id}`"
        />
      </template>
    </PageHeader>

    <div v-if="item" class="ficha">
      <!-- Encabezado: chips de estado -->
      <div class="ficha-chips">
        <q-chip dense square :style="{ background: item.is_active ? 'var(--app-accent-teal)' : 'var(--app-text-muted)', color: '#fff' }" :label="item.is_active ? 'Activo' : 'Inactivo'" />
        <q-chip v-if="item.category" dense square :style="{ background: accCat(item.category), color: '#fff' }" :label="item.category" />
        <q-chip dense square outline :label="UOM_LABELS[item.uom] ?? item.uom" />
        <q-chip v-if="item.track_lots" dense square :style="{ background: 'var(--app-accent-violet)', color: '#fff' }" label="Por lotes" />
        <q-chip v-if="item.is_controlled" dense square :style="{ background: 'var(--app-accent-coral)', color: '#fff' }" label="Controlado" />
        <q-chip v-if="stockBajoTotal" dense square :style="{ background: 'var(--app-accent-amber)', color: '#fff' }" icon="warning" label="Bajo punto de reorden" />
      </div>

      <div class="ficha-cols">
        <!-- Datos + precios -->
        <q-card flat bordered class="ficha-card" style="--acc: var(--app-accent-teal)">
          <q-card-section class="text-subtitle2 ficha-titulo">Precios</q-card-section>
          <q-list dense>
            <q-item>
              <q-item-section>Precio de venta</q-item-section>
              <q-item-section side>{{ item.sale_price != null ? formatMoney(item.sale_price) : 'sin precio' }}</q-item-section>
            </q-item>
            <q-item v-if="item.wholesale_price != null">
              <q-item-section>Mayoreo (≥ {{ formatQty(item.wholesale_min_qty ?? '0') }})</q-item-section>
              <q-item-section side>{{ formatMoney(item.wholesale_price) }}</q-item-section>
            </q-item>
            <q-item>
              <q-item-section>IVA</q-item-section>
              <q-item-section side>{{ (Number(item.default_tax_rate) * 100).toFixed(0) }}%</q-item-section>
            </q-item>
          </q-list>
          <q-separator />
          <q-card-section class="text-subtitle2 ficha-titulo">Niveles</q-card-section>
          <q-list dense>
            <q-item>
              <q-item-section>Punto de reorden</q-item-section>
              <q-item-section side>{{ formatQty(item.reorder_point) }}</q-item-section>
            </q-item>
            <q-item>
              <q-item-section>Stock mínimo</q-item-section>
              <q-item-section side>{{ formatQty(item.min_stock_qty) }}</q-item-section>
            </q-item>
            <q-item v-if="item.max_stock_qty != null">
              <q-item-section>Stock máximo</q-item-section>
              <q-item-section side>{{ formatQty(item.max_stock_qty) }}</q-item-section>
            </q-item>
          </q-list>
        </q-card>

        <!-- Existencias por bodega -->
        <q-card flat bordered class="ficha-card ficha-card--ancha" style="--acc: var(--app-accent-blue)">
          <q-card-section class="text-subtitle2 ficha-titulo row items-center justify-between">
            <span>Existencias por bodega</span>
            <span class="ficha-total">Total: {{ formatQty(String(totalDisponible)) }} {{ UOM_LABELS[item.uom] ?? '' }}</span>
          </q-card-section>
          <q-markup-table flat class="app-table">
            <thead>
              <tr>
                <th class="text-left">Bodega</th>
                <th class="text-right">Disponible</th>
                <th class="text-right">En mano</th>
                <th class="text-right">Costo prom.</th>
                <th class="text-right">Valor</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in existencias" :key="s.id" :class="{ 'ficha-row--bajo': filaBaja(s) }">
                <td>
                  {{ s.warehouse_name }}
                  <q-icon v-if="filaBaja(s)" name="warning" color="warning" size="14px" />
                </td>
                <td class="text-right text-weight-bold">{{ formatQty(s.qty_available) }}</td>
                <td class="text-right">{{ formatQty(s.qty_on_hand) }}</td>
                <td class="text-right">{{ formatMoney(s.avg_cost) }}</td>
                <td class="text-right">{{ formatMoney(Number(s.qty_on_hand) * Number(s.avg_cost)) }}</td>
              </tr>
              <tr v-if="!existencias.length">
                <td colspan="5" class="text-center text-muted q-pa-md">Sin existencias en ninguna bodega.</td>
              </tr>
            </tbody>
          </q-markup-table>
        </q-card>
      </div>

      <!-- Movimientos recientes -->
      <q-card flat bordered class="ficha-card ficha-card--full" style="--acc: var(--app-accent-violet)">
        <q-card-section class="text-subtitle2 ficha-titulo">Últimos movimientos</q-card-section>
        <q-markup-table flat class="app-table">
          <thead>
            <tr>
              <th class="text-left">Fecha</th>
              <th class="text-left">Tipo</th>
              <th class="text-left">Bodega</th>
              <th class="text-right">Cantidad</th>
              <th class="text-right">Costo unit.</th>
              <th class="text-left">Nota</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in kardex" :key="m.id">
              <td>{{ fechaCorta(m.created_at) }}</td>
              <td>{{ MOVEMENT_TYPE_LABELS[m.movement_type] ?? m.movement_type }}</td>
              <td>{{ m.warehouse_name }}</td>
              <td class="text-right" :class="Number(m.qty_delta) >= 0 ? 'text-positive' : 'text-negative'">
                {{ Number(m.qty_delta) >= 0 ? '+' : '' }}{{ formatQty(m.qty_delta) }}
              </td>
              <td class="text-right">{{ formatMoney(m.unit_cost) }}</td>
              <td class="text-muted">{{ m.note || '—' }}</td>
            </tr>
            <tr v-if="!kardex.length">
              <td colspan="6" class="text-center text-muted q-pa-md">Sin movimientos registrados.</td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card>
    </div>

    <q-inner-loading :showing="cargando" />
  </q-page>
</template>

<script setup lang="ts">
import BackButton from 'src/components/BackButton.vue';
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import { useRoute } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatMoney, formatQty } from 'src/core/format';
import {
  MOVEMENT_TYPE_LABELS,
  UOM_LABELS,
  getItem,
  getKardex,
  getStock,
  type InventoryItem,
  type KardexRow,
  type StockRow,
} from 'src/modules/inventory/api';

const $q = useQuasar();
const route = useRoute();

const itemId = Number(route.params.itemId);
const item = ref<InventoryItem | null>(null);
const existencias = ref<StockRow[]>([]);
const kardex = ref<KardexRow[]>([]);
const cargando = ref(false);

const totalDisponible = computed(() =>
  Math.round(existencias.value.reduce((s, r) => s + Number(r.qty_available), 0) * 10000) / 10000,
);

const stockBajoTotal = computed(() => {
  if (!item.value) return false;
  const reorden = Number(item.value.reorder_point || 0);
  return reorden > 0 && totalDisponible.value <= reorden;
});

function filaBaja(s: StockRow): boolean {
  if (!item.value) return false;
  const reorden = Number(item.value.reorder_point || 0);
  return Number(s.qty_available) <= 0 || (reorden > 0 && Number(s.qty_available) <= reorden);
}

function fechaCorta(iso: string): string {
  return new Date(iso).toLocaleString('es-NI', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// Acento sólido estable por categoría (mismo criterio que en la Caja).
const ACENTOS = ['blue', 'teal', 'violet', 'amber', 'coral'] as const;
function accCat(categoria: string): string {
  const cat = (categoria || '').trim();
  if (!cat) return 'var(--app-accent-blue)';
  let h = 0;
  for (let i = 0; i < cat.length; i++) h = (h * 31 + cat.charCodeAt(i)) >>> 0;
  return `var(--app-accent-${ACENTOS[h % ACENTOS.length] ?? 'blue'})`;
}

async function cargar() {
  cargando.value = true;
  try {
    const [it, stock, kx] = await Promise.all([
      getItem(itemId),
      getStock({ item_id: itemId }),
      getKardex({ item_id: itemId }),
    ]);
    item.value = it;
    existencias.value = stock;
    kardex.value = kx;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar la ficha del producto.') });
  } finally {
    cargando.value = false;
  }
}

onMounted(cargar);
</script>

<style scoped>
.ficha {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}

.ficha-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-1);
}

.ficha-cols {
  display: flex;
  gap: var(--app-space-4);
  flex-wrap: wrap;
  align-items: flex-start;
}

.ficha-card {
  flex: 1;
  min-width: 280px;
  background: var(--app-surface-strong);
  border-left: 5px solid var(--acc, var(--app-primary));
  box-shadow: var(--app-shadow-soft);
}

/* Encabezado de sección con el acento de su tarjeta */
.ficha-titulo {
  color: var(--acc, var(--app-primary));
  font-weight: 700;
  background: color-mix(in srgb, var(--acc, var(--app-primary)) 8%, transparent);
}

.ficha-card--ancha {
  flex: 2;
  min-width: 360px;
}

.ficha-card--full {
  width: 100%;
}

.ficha-total {
  font-weight: 800;
  color: var(--app-primary);
}

.ficha-row--bajo td {
  background: color-mix(in srgb, var(--app-accent-amber) 12%, transparent);
}
</style>
