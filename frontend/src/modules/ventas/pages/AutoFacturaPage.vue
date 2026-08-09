<template>
  <q-page :padding="!kiosko" class="af" :class="{ 'af--kiosko': kiosko }">
    <PageHeader
      v-if="!kiosko"
      title="Auto-factura"
      subtitle="Armá tu compra vos mismo; pagás al llegar a la caja"
      hide-refresh
    />

    <!-- Encabezado del kiosko (la marca con pulsación larga sale del modo kiosko) -->
    <div v-else class="af-kiosk-top">
      <div
        class="af-kiosk-brand"
        @pointerdown="holdSalir"
        @pointerup="soltarSalir"
        @pointerleave="soltarSalir"
      >
        <img v-if="brand.logoUrl" :src="brand.logoUrl" :alt="brand.name" class="af-kiosk-logo" />
        <span v-else class="af-kiosk-mark" aria-hidden="true">◆</span>
        <span class="af-kiosk-name">{{ brand.name }}</span>
      </div>
      <div class="af-kiosk-title">Auto-factura · armá tu compra y pagás en la caja</div>
    </div>

    <!-- Bienvenida (atractor): el cliente toca para empezar -->
    <div
      v-if="kiosko && mostrarBienvenida && !ticket"
      class="af-bienvenida"
      @click="iniciarCompra"
    >
      <q-icon name="shopping_basket" size="96px" color="primary" />
      <div class="af-bienvenida__titulo">¡Bienvenido!</div>
      <div class="af-bienvenida__sub">Tocá la pantalla para armar tu compra</div>
      <q-btn
        unelevated
        no-caps
        size="xl"
        color="primary"
        icon="touch_app"
        label="Empezar"
        class="af-bienvenida__btn"
        @click.stop="iniciarCompra"
      />
    </div>

    <!-- Pantalla de éxito: código gigante para llevar a caja -->
    <div v-if="ticket" class="af-exito">
      <q-icon name="check_circle" size="56px" color="positive" />
      <div class="af-exito__titulo">¡Listo! Presentá este código en la caja</div>
      <div class="af-exito__codigo">{{ ticket.code }}</div>
      <div class="af-exito__total">
        Total estimado: <strong>{{ formatMoney(ticket.estimated_total) }}</strong>
      </div>
      <div class="af-exito__nota">
        Los precios se confirman en caja. El código vence
        {{ formatDateTime(ticket.expires_at) }}.
      </div>
      <div v-if="kiosko && reinicioSeg > 0" class="af-exito__reinicio">
        Esta pantalla se reinicia en {{ reinicioSeg }} s
      </div>
      <div class="af-exito__acciones">
        <q-btn
          unelevated
          no-caps
          size="lg"
          color="primary"
          icon="shopping_basket"
          label="Nueva compra"
          @click="nuevaCompra"
        />
        <q-btn
          outline
          no-caps
          size="lg"
          icon="receipt"
          label="Imprimir"
          @click="imprimirPreTicket"
        />
        <q-btn
          flat
          no-caps
          size="lg"
          icon="delete"
          label="Cancelar mi ticket"
          :loading="cancelando"
          @click="cancelarTicket"
        />
      </div>
    </div>

    <!-- Pantalla de armado -->
    <template v-else>
      <q-banner dense rounded class="af-aviso">
        <q-icon name="info" class="q-mr-sm" />
        Los precios son estimados: se confirman al pagar en la caja.
      </q-banner>

      <div class="af-escaner">
        <q-input
          ref="inputEscaner"
          v-model="codigoEscaneado"
          outlined
          autofocus
          placeholder="Escaneá el código de barras aquí…"
          class="af-escaner__input"
          @keyup.enter="escanear"
        >
          <template #prepend><q-icon name="qr_code_scanner" /></template>
          <template #append>
            <q-btn flat dense no-caps label="Agregar" :disable="!codigoEscaneado" @click="escanear" />
          </template>
        </q-input>
        <q-input
          v-model="filtroNombre"
          outlined
          clearable
          placeholder="…o buscá por nombre"
          class="af-escaner__buscar"
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>

      <div class="af-cuerpo">
        <!-- Grid táctil -->
        <div class="af-grid">
          <div v-if="categorias.length" class="af-grid__cats">
            <q-chip
              v-for="cat in categorias"
              :key="cat"
              clickable
              class="af-cat"
              :class="{ 'af-cat--activa': categoriaActiva === cat }"
              :style="{ '--acc': accCat(cat) }"
              :label="cat"
              @click="categoriaActiva = categoriaActiva === cat ? '' : cat"
            />
          </div>
          <div class="af-grid__items">
            <button
              v-for="it in articulosGrid"
              :key="it.id"
              class="af-grid__card"
              :style="{ '--acc': accCat(it.category), '--grad': gradCat(it.category) }"
              type="button"
              @click="agregar(it)"
            >
              <span class="af-grid__tile">{{ inicial(it.name) }}</span>
              <span class="af-grid__nombre">{{ it.name }}</span>
              <span class="af-grid__precio">{{ formatMoney(it.sale_price ?? '0') }}</span>
              <span v-if="it.wholesale_price != null" class="af-grid__mayoreo">
                {{ formatMoney(it.wholesale_price) }} ×{{ formatQty(it.wholesale_min_qty ?? '0') }}+
              </span>
            </button>
            <div v-if="!articulosGrid.length" class="text-muted af-grid__vacio">
              No hay productos para mostrar.
            </div>
          </div>
        </div>

        <!-- Mi compra -->
        <div class="af-panel">
          <div class="af-panel__titulo">Mi compra</div>
          <div v-if="!carrito.length" class="text-muted af-panel__vacio">
            Tocá un producto o escaneá su código para empezar.
          </div>
          <div v-for="(ln, i) in carrito" :key="ln.item.id" class="af-linea">
            <div class="af-linea__info">
              <div class="af-linea__nombre">{{ ln.item.name }}</div>
              <div class="af-linea__precio">
                {{ formatMoney(precioUnitario(ln)) }} c/u
                <q-badge v-if="esMayoreo(ln)" color="secondary" label="mayoreo" class="q-ml-xs" />
              </div>
            </div>
            <div class="af-linea__qty">
              <q-btn round unelevated icon="remove" size="md" aria-label="Reducir cantidad" @click="restar(i)" />
              <span class="af-linea__num">{{ ln.quantity }}</span>
              <q-btn round unelevated color="primary" icon="add" size="md" aria-label="Aumentar cantidad" @click="ln.quantity += 1" />
            </div>
            <div class="af-linea__total">{{ formatMoney(totalLinea(ln)) }}</div>
          </div>

          <q-space />
          <div class="af-totales">
            <div class="af-totales__fila">
              <span>Subtotal</span><span>{{ formatMoney(totales.subtotal) }}</span>
            </div>
            <div class="af-totales__fila">
              <span>IVA</span><span>{{ formatMoney(totales.iva) }}</span>
            </div>
            <div class="af-totales__fila af-totales__total">
              <span>Total estimado</span><span>{{ formatMoney(totales.total) }}</span>
            </div>
          </div>
          <q-btn
            unelevated
            no-caps
            color="primary"
            size="xl"
            class="af-generar"
            icon="confirmation_number"
            label="Generar mi ticket"
            :disable="!carrito.length"
            :loading="generando"
            @click="generar"
          />
          <q-btn
            v-if="carrito.length"
            flat
            no-caps
            label="Vaciar"
            icon="delete_sweep"
            @click="vaciar"
          />
        </div>
      </div>
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { useRoute, useRouter } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatDateTime, formatMoney, formatQty } from 'src/core/format';
import { BRAND } from 'src/config/brand';
import {
  findItemByBarcode,
  listItems,
  type InventoryItem,
} from 'src/modules/inventory/api';
import {
  cancelSelfServiceTicket,
  createSelfServiceTicket,
  type SelfServiceTicket,
} from 'src/modules/ventas/api';

const $q = useQuasar();
const route = useRoute();
const router = useRouter();

// --- Modo kiosko (pantalla completa, autoservicio del cliente) ---------------------
const kiosko = computed(() => route.meta.kiosko === true);
const brand = BRAND;

// Color por categoría (estable, mismo criterio que la Caja).
const ACENTOS = ['blue', 'teal', 'violet', 'amber', 'coral'] as const;
function acentoDe(categoria: string): string {
  const cat = (categoria || '').trim();
  if (!cat) return 'blue';
  let h = 0;
  for (let i = 0; i < cat.length; i++) h = (h * 31 + cat.charCodeAt(i)) >>> 0;
  return ACENTOS[h % ACENTOS.length] ?? 'blue';
}
function gradCat(categoria: string): string {
  return `var(--app-stat-${acentoDe(categoria)})`;
}
function accCat(categoria: string): string {
  return `var(--app-accent-${acentoDe(categoria)})`;
}
function inicial(nombre: string): string {
  return (nombre || '?').trim().charAt(0).toUpperCase() || '?';
}

function r2(x: number): number {
  return Math.round((x + Number.EPSILON) * 100) / 100;
}

// --- Carrito del kiosko (sin precios manuales ni descuentos) -------------------
interface LineaKiosko {
  item: InventoryItem;
  quantity: number;
}

const carrito = ref<LineaKiosko[]>([]);
const generando = ref(false);
const cancelando = ref(false);
const ticket = ref<SelfServiceTicket | null>(null);

/** Espejo del servidor: mayoreo automático por cantidad (solo informativo). */
function precioUnitario(ln: LineaKiosko): number {
  const it = ln.item;
  if (
    it.wholesale_price != null &&
    it.wholesale_min_qty != null &&
    ln.quantity >= Number(it.wholesale_min_qty)
  ) {
    return Number(it.wholesale_price);
  }
  return it.sale_price != null ? Number(it.sale_price) : 0;
}

function esMayoreo(ln: LineaKiosko): boolean {
  return (
    ln.item.wholesale_price != null &&
    ln.item.wholesale_min_qty != null &&
    ln.quantity >= Number(ln.item.wholesale_min_qty)
  );
}

function totalLinea(ln: LineaKiosko): number {
  const sub = r2(ln.quantity * precioUnitario(ln));
  return r2(sub + r2(sub * Number(ln.item.default_tax_rate || 0)));
}

const totales = computed(() => {
  let subtotal = 0;
  let iva = 0;
  for (const ln of carrito.value) {
    const sub = r2(ln.quantity * precioUnitario(ln));
    subtotal = r2(subtotal + sub);
    iva = r2(iva + r2(sub * Number(ln.item.default_tax_rate || 0)));
  }
  return { subtotal, iva, total: r2(subtotal + iva) };
});

function agregar(item: InventoryItem) {
  if (item.sale_price == null) {
    $q.notify({ type: 'warning', message: `«${item.name}» no tiene precio; pedilo en caja.` });
    return;
  }
  const existente = carrito.value.find((l) => l.item.id === item.id);
  if (existente) existente.quantity += 1;
  else carrito.value.push({ item, quantity: 1 });
}

function restar(i: number) {
  const ln = carrito.value[i];
  if (!ln) return;
  if (ln.quantity <= 1) carrito.value.splice(i, 1);
  else ln.quantity -= 1;
}

function vaciar() {
  carrito.value = [];
  enfocarEscaner();
}

// --- Escáner -----------------------------------------------------------------
const codigoEscaneado = ref('');
const inputEscaner = ref<{ focus: () => void } | null>(null);

function enfocarEscaner() {
  setTimeout(() => inputEscaner.value?.focus(), 50);
}

async function escanear() {
  const codigo = codigoEscaneado.value.trim();
  codigoEscaneado.value = '';
  if (!codigo) return;
  try {
    const item = await findItemByBarcode(codigo);
    if (!item) {
      $q.notify({ type: 'negative', message: `Código ${codigo}: producto no encontrado.` });
      return;
    }
    agregar(item);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo buscar el producto.') });
  } finally {
    enfocarEscaner();
  }
}

// --- Grid táctil ----------------------------------------------------------------
const articulos = ref<InventoryItem[]>([]);
const categoriaActiva = ref('');
const filtroNombre = ref('');

const categorias = computed(() => {
  const set = new Set<string>();
  for (const it of articulos.value) if (it.category) set.add(it.category);
  return [...set].sort();
});

const articulosGrid = computed(() => {
  let base = categoriaActiva.value
    ? articulos.value.filter((it) => it.category === categoriaActiva.value)
    : articulos.value;
  const filtro = (filtroNombre.value ?? '').trim().toLowerCase();
  if (filtro) base = base.filter((it) => it.name.toLowerCase().includes(filtro));
  return base.slice(0, 60);
});

// --- Generar / cancelar el pre-ticket ----------------------------------------------
const MENSAJES_AF: Record<string, string> = {
  SALES_ITEM_WITHOUT_PRICE: 'Un artículo quedó sin precio en el catálogo; pedí ayuda en caja.',
  SALES_SELF_SERVICE_NOT_OPEN: 'Este ticket ya fue cobrado o cancelado.',
  SALES_SELF_SERVICE_EXPIRED: 'El ticket venció; armá tu compra de nuevo.',
  SALES_SELF_SERVICE_NOT_FOUND: 'No se encontró el ticket.',
};

function mensajeAf(e: unknown, fallback: string): string {
  const crudo = apiErrorMessage(e, fallback);
  return MENSAJES_AF[crudo] ?? crudo;
}

async function generar() {
  if (!carrito.value.length) return;
  generando.value = true;
  try {
    ticket.value = await createSelfServiceTicket(
      carrito.value.map((ln) => ({
        inventory_item_id: ln.item.id,
        quantity: String(ln.quantity),
      })),
    );
    carrito.value = [];
    if (kiosko.value) arrancarReinicio();
  } catch (e) {
    $q.notify({ type: 'negative', message: mensajeAf(e, 'No se pudo generar el ticket.') });
  } finally {
    generando.value = false;
  }
}

async function cancelarTicket() {
  if (!ticket.value) return;
  cancelando.value = true;
  try {
    await cancelSelfServiceTicket(ticket.value.code);
    $q.notify({ type: 'info', message: 'Ticket cancelado.' });
    nuevaCompra();
  } catch (e) {
    $q.notify({ type: 'negative', message: mensajeAf(e, 'No se pudo cancelar el ticket.') });
  } finally {
    cancelando.value = false;
  }
}

function nuevaCompra() {
  detenerReinicio();
  ticket.value = null;
  carrito.value = [];
  if (kiosko.value) mostrarBienvenida.value = true;
  enfocarEscaner();
}

// --- Comportamientos exclusivos del kiosko ----------------------------------------
// Pantalla de bienvenida (atractor): el cliente toca para empezar.
const mostrarBienvenida = ref(false);

function iniciarCompra() {
  mostrarBienvenida.value = false;
  enfocarEscaner();
}

// Auto-reinicio: tras mostrar el código, vuelve solo a la bienvenida.
const REINICIO_SEG = 40;
const reinicioSeg = ref(0);
let reinicioInterval: ReturnType<typeof setInterval> | null = null;

function arrancarReinicio() {
  detenerReinicio();
  reinicioSeg.value = REINICIO_SEG;
  reinicioInterval = setInterval(() => {
    reinicioSeg.value -= 1;
    if (reinicioSeg.value <= 0) nuevaCompra();
  }, 1000);
}

function detenerReinicio() {
  if (reinicioInterval) {
    clearInterval(reinicioInterval);
    reinicioInterval = null;
  }
  reinicioSeg.value = 0;
}

// Timeout de inactividad: si dejan un carrito a medias, se vacía solo.
const IDLE_MS = 90_000;
let idleTimer: ReturnType<typeof setTimeout> | null = null;

function reiniciarIdle() {
  if (idleTimer) clearTimeout(idleTimer);
  if (!kiosko.value) return;
  // Solo cuenta cuando hay carrito y no se está mostrando un código.
  if (!ticket.value && carrito.value.length > 0) {
    idleTimer = setTimeout(() => nuevaCompra(), IDLE_MS);
  }
}

function onInteraccion() {
  reiniciarIdle();
}

// Salir del kiosko: control discreto con pulsación larga (~1.8 s) + confirmación.
let salirTimer: ReturnType<typeof setTimeout> | null = null;

function holdSalir() {
  salirTimer = setTimeout(() => {
    salirTimer = null;
    $q.dialog({
      title: 'Salir del modo kiosko',
      message: 'Esto saca la tableta del modo autoservicio. ¿Continuar?',
      cancel: { label: 'Cancelar', flat: true, noCaps: true },
      ok: { label: 'Salir', color: 'negative', unelevated: true, noCaps: true },
      persistent: true,
    }).onOk(() => {
      detenerReinicio();
      void router.push('/');
    });
  }, 1800);
}

function soltarSalir() {
  if (salirTimer) {
    clearTimeout(salirTimer);
    salirTimer = null;
  }
}

// --- Pre-ticket 80mm (mismo patrón del ticket de la caja) ---------------------------
function imprimirPreTicket() {
  const t = ticket.value;
  if (!t) return;
  const filas = t.lines
    .map(
      (l) =>
        `<tr><td>${l.name}</td><td class="n">${l.quantity}</td><td class="n">${l.unit_price ?? '-'}</td><td class="n">${l.line_total ?? '-'}</td></tr>`,
    )
    .join('');
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Auto-factura ${t.code}</title>
<style>
  body { font-family: 'Courier New', monospace; width: 72mm; margin: 0 auto; font-size: 12px; color: #000; }
  h1 { font-size: 22px; text-align: center; margin: 6px 0; letter-spacing: 4px; }
  .c { text-align: center; margin: 2px 0; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  th, td { text-align: left; padding: 1px 2px; }
  .n { text-align: right; }
  .tot { border-top: 1px dashed #000; font-weight: bold; }
  @media print { @page { margin: 0; size: 80mm auto; } }
</style></head><body>
  <div class="c">AUTO-FACTURA — presentar en caja</div>
  <h1>${t.code}</h1>
  <div class="c">Vence: ${new Date(t.expires_at).toLocaleString('es-NI')}</div>
  <table>
    <thead><tr><th>Producto</th><th class="n">Cant</th><th class="n">Precio</th><th class="n">Total</th></tr></thead>
    <tbody>${filas}</tbody>
    <tfoot>
      <tr class="tot"><td colspan="3" class="n">TOTAL ESTIMADO C$</td><td class="n">${t.estimated_total}</td></tr>
    </tfoot>
  </table>
  <div class="c" style="margin-top:8px">Los precios se confirman en caja.</div>
</body></html>`;
  const win = window.open('', '_blank', 'width=420,height=600');
  if (!win) {
    $q.notify({ type: 'warning', message: 'El navegador bloqueó la ventana del ticket.' });
    return;
  }
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 250);
}

// Reinicia el reloj de inactividad cuando cambia el carrito.
watch(carrito, reiniciarIdle, { deep: true });

onMounted(async () => {
  if (kiosko.value) {
    mostrarBienvenida.value = true;
    window.addEventListener('pointerdown', onInteraccion);
    window.addEventListener('keydown', onInteraccion);
  }
  try {
    const items = await listItems({ is_active: true });
    articulos.value = items.filter((it) => it.sale_price != null);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el catálogo.') });
  }
});

onBeforeUnmount(() => {
  detenerReinicio();
  if (idleTimer) clearTimeout(idleTimer);
  if (salirTimer) clearTimeout(salirTimer);
  window.removeEventListener('pointerdown', onInteraccion);
  window.removeEventListener('keydown', onInteraccion);
});
</script>

<style scoped>
.af-aviso {
  margin-bottom: var(--app-space-3);
  background: var(--app-surface-strong);
  color: var(--app-text-muted);
}

/* Chip de categoría: tintado con su acento; relleno al activarse */
.af-cat {
  background: color-mix(in srgb, var(--acc) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--acc) 42%, transparent);
  color: var(--acc);
  font-weight: 700;
}

.af-cat--activa {
  background: var(--acc);
  border-color: transparent;
  color: #fff;
}

.af-escaner {
  display: flex;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
  flex-wrap: wrap;
}

.af-escaner__input {
  flex: 2 1 280px;
}

.af-escaner__buscar {
  flex: 1 1 200px;
}

.af-cuerpo {
  display: flex;
  gap: var(--app-space-3);
  align-items: flex-start;
  flex-wrap: wrap;
}

.af-grid {
  flex: 2 1 420px;
}

.af-grid__cats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-1);
  margin-bottom: var(--app-space-2);
}

.af-grid__items {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--app-space-2);
}

.af-grid__card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 112px;
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-left: 6px solid var(--acc);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-strong);
  box-shadow: var(--app-shadow-soft);
  color: var(--app-text);
  cursor: pointer;
  text-align: left;
  transition: transform 0.08s ease, box-shadow 0.08s ease, background 0.08s ease;
}

.af-grid__card:hover {
  box-shadow: var(--app-shadow-card);
  transform: translateY(-1px);
}

.af-grid__card:active {
  background: color-mix(in srgb, var(--acc) 10%, var(--app-surface-strong));
  transform: translateY(0);
}

.af-grid__tile {
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--app-radius-sm);
  background: var(--grad);
  color: #fff;
  font-weight: 700;
  margin-bottom: 2px;
}

.af-grid__nombre {
  font-weight: 600;
  line-height: 1.15;
}

.af-grid__precio {
  font-size: 1.05rem;
  color: var(--app-primary);
  font-weight: 700;
}

.af-grid__mayoreo {
  font-size: 0.75rem;
  color: var(--app-text-muted);
}

.af-grid__vacio {
  grid-column: 1 / -1;
  padding: var(--app-space-4);
  text-align: center;
}

.af-panel {
  flex: 1 1 320px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  padding: var(--app-space-4);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface-strong);
  box-shadow: var(--app-shadow-card);
  position: sticky;
  top: var(--app-space-3);
}

.af-panel__titulo {
  font-weight: 700;
  font-size: 1.1rem;
}

.af-panel__vacio {
  padding: var(--app-space-3) 0;
}

.af-linea {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  padding-bottom: var(--app-space-2);
  border-bottom: 1px dashed var(--app-border);
}

.af-linea__info {
  flex: 1;
  min-width: 0;
}

.af-linea__nombre {
  font-weight: 600;
}

.af-linea__precio {
  font-size: 0.85rem;
  color: var(--app-text-muted);
}

.af-linea__qty {
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
}

.af-linea__num {
  min-width: 36px;
  text-align: center;
  font-size: 1.15rem;
  font-weight: 700;
}

.af-linea__total {
  min-width: 88px;
  text-align: right;
  font-weight: 600;
}

.af-totales {
  border-top: 1px solid var(--app-border);
  padding-top: var(--app-space-2);
}

.af-totales__fila {
  display: flex;
  justify-content: space-between;
  color: var(--app-text-muted);
}

.af-totales__total {
  font-size: 1.4rem;
  font-weight: 800;
  color: var(--app-primary);
}

.af-generar {
  width: 100%;
  min-height: 64px;
}

.af-exito {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--app-space-2);
  padding: var(--app-space-6) var(--app-space-3);
  text-align: center;
}

.af-exito__titulo {
  font-size: 1.2rem;
  font-weight: 600;
}

.af-exito__codigo {
  font-size: 4.5rem;
  font-weight: 900;
  letter-spacing: 0.35em;
  padding: var(--app-space-2) var(--app-space-4);
  border: 2px dashed var(--app-primary);
  border-radius: var(--app-radius-lg);
  color: var(--app-primary);
}

.af-exito__total {
  font-size: 1.25rem;
}

.af-exito__nota {
  color: var(--app-text-muted);
}

.af-exito__acciones {
  display: flex;
  gap: var(--app-space-2);
  flex-wrap: wrap;
  justify-content: center;
  margin-top: var(--app-space-3);
}

.af-exito__reinicio {
  margin-top: var(--app-space-2);
  font-weight: 700;
  color: var(--app-primary);
}

/* --- Modo kiosko (pantalla completa, autoservicio) --- */
.af--kiosko {
  padding: var(--app-space-4) var(--app-space-5);
}

.af-kiosk-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  margin-bottom: var(--app-space-4);
  padding-bottom: var(--app-space-3);
  border-bottom: 1px solid var(--app-border);
}

.af-kiosk-brand {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
  cursor: default;
  user-select: none;
  -webkit-user-select: none;
}

.af-kiosk-logo {
  height: 36px;
}

.af-kiosk-mark {
  font-size: 1.6rem;
  color: var(--app-primary);
}

.af-kiosk-name {
  font-family: 'Roboto', 'Segoe UI', system-ui, sans-serif;
  font-weight: 800;
  font-size: 1.3rem;
}

.af-kiosk-title {
  color: var(--app-text-muted);
  font-size: 1.05rem;
}

.af-bienvenida {
  position: fixed;
  inset: 0;
  z-index: 1500;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-3);
  text-align: center;
  padding: var(--app-space-6);
  background: var(--app-bg-gradient);
  background-color: var(--app-bg);
  cursor: pointer;
}

.af-bienvenida__titulo {
  font-family: 'Roboto', 'Segoe UI', system-ui, sans-serif;
  font-size: 2.6rem;
  font-weight: 800;
  color: var(--app-primary);
}

.af-bienvenida__sub {
  font-size: 1.4rem;
  color: var(--app-text-muted);
}

.af-bienvenida__btn {
  margin-top: var(--app-space-3);
  min-width: 240px;
  min-height: 72px;
  font-size: 1.2rem;
}

/* En kiosko, tarjetas y carrito más grandes (uso con dedo) */
.af--kiosko .af-grid__items {
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
}

.af--kiosko .af-grid__card {
  min-height: 132px;
}

.af--kiosko .af-escaner {
  font-size: 1.1rem;
}
</style>
