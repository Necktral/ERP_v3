<template>
  <q-page class="app-page">
    <PageHeader
      title="Historial de ventas"
      subtitle="Buscá una factura por fecha, cliente o número. Reimprimí el ticket (marcado como COPIA), iniciá una devolución (nota de crédito) o anulá con motivo. Cada acción queda auditada."
      :loading="cargando"
      @refresh="cargar"
    >
      <template #actions>
        <q-btn flat no-caps icon="point_of_sale" label="Ir a Caja" to="/ventas" />
      </template>
    </PageHeader>

    <!-- Filtros -->
    <div class="hist-filtros">
      <q-input v-model="desde" outlined dense type="date" label="Desde" @update:model-value="cargar" />
      <q-input v-model="hasta" outlined dense type="date" label="Hasta" @update:model-value="cargar" />
      <q-select
        v-model="estado"
        :options="opcionesEstado"
        outlined
        dense
        emit-value
        map-options
        label="Estado"
        class="hist-estado"
        @update:model-value="cargar"
      />
      <q-input
        v-model="busqueda"
        outlined
        dense
        clearable
        debounce="350"
        label="Cliente o número"
        class="hist-buscar"
        @update:model-value="cargar"
      >
        <template #prepend><q-icon name="search" /></template>
      </q-input>
    </div>

    <q-table
      :rows="ventas"
      :columns="columnas"
      row-key="id"
      flat
      :loading="cargando"
      :pagination="{ rowsPerPage: 0 }"
      hide-pagination
      class="app-table"
    >
      <template #body-cell-doc="props">
        <q-td :props="props">
          <div class="hist-num">{{ props.row.series }}-{{ props.row.number }}</div>
          <div class="text-muted hist-fecha">{{ fechaCorta(props.row.issued_at || props.row.created_at) }}</div>
        </q-td>
      </template>
      <template #body-cell-cliente="props">
        <q-td :props="props">
          {{ props.row.customer_party_display_name || props.row.customer_name || 'Consumidor final' }}
        </q-td>
      </template>
      <template #body-cell-total="props">
        <q-td :props="props" class="text-right">
          {{ formatMoney(props.row.total) }}
          <div v-if="Number(props.row.credited_total) > 0" class="text-negative hist-credito">
            NC {{ formatMoney(props.row.credited_total) }}
          </div>
        </q-td>
      </template>
      <template #body-cell-estado="props">
        <q-td :props="props">
          <q-chip dense square :style="{ background: colorEstado(props.row.status), color: '#fff' }" :label="ESTADO_LABELS[props.row.status] ?? props.row.status" />
          <div class="text-muted hist-pago">{{ PAYMENT_STATUS_LABELS[props.row.payment_status] ?? props.row.payment_status }}</div>
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props" class="text-right">
          <q-btn flat dense round icon="visibility" @click="verDetalle(props.row)">
            <q-tooltip>Ver detalle</q-tooltip>
          </q-btn>
          <q-btn
            v-if="props.row.status === 'ISSUED'"
            flat
            dense
            round
            icon="print"
            @click="reimprimir(props.row)"
          >
            <q-tooltip>Reimprimir (COPIA)</q-tooltip>
          </q-btn>
          <q-btn
            v-if="props.row.status === 'ISSUED' && props.row.doc_type === 'INVOICE' && puede('billing.credit_note.issue')"
            flat
            dense
            round
            color="warning"
            icon="assignment_return"
            @click="abrirDevolucion(props.row)"
          >
            <q-tooltip>Devolución (nota de crédito)</q-tooltip>
          </q-btn>
          <q-btn
            v-if="props.row.status === 'ISSUED' && puede('billing.doc.void')"
            flat
            dense
            round
            color="negative"
            icon="block"
            @click="abrirAnulacion(props.row)"
          >
            <q-tooltip>Anular</q-tooltip>
          </q-btn>
        </q-td>
      </template>
      <template #no-data>
        <div class="full-width text-center text-muted q-pa-md">
          No hay ventas con esos filtros.
        </div>
      </template>
    </q-table>

    <!-- Detalle -->
    <q-dialog v-model="dlgDetalle">
      <q-card class="app-dialog hist-detalle">
        <q-card-section class="text-h6 row items-center justify-between">
          <span v-if="detalle">{{ BILLING_DOC_TYPE_LABELS[detalle.doc_type] }} {{ detalle.series }}-{{ detalle.number }}</span>
          <q-chip v-if="detalle" dense square :style="{ background: colorEstado(detalle.status), color: '#fff' }" :label="ESTADO_LABELS[detalle.status] ?? detalle.status" />
        </q-card-section>
        <q-inner-loading :showing="cargandoDetalle" />
        <q-card-section v-if="detalle">
          <div class="hist-detalle__meta">
            <div><span class="text-muted">Cliente:</span> {{ detalle.customer_party_display_name || detalle.customer_name || 'Consumidor final' }}</div>
            <div><span class="text-muted">Fecha:</span> {{ fechaLarga(detalle.issued_at || detalle.created_at) }}</div>
            <div><span class="text-muted">Pago:</span> {{ PAYMENT_METHOD_LABELS[detalle.payment_method] ?? detalle.payment_method }} · {{ PAYMENT_STATUS_LABELS[detalle.payment_status] ?? detalle.payment_status }}</div>
            <div><span class="text-muted">Fiscal:</span> {{ (FISCAL_STATUS_LABELS[detalle.fiscal_status] ?? detalle.fiscal_status) || '—' }}</div>
            <div v-if="detalle.void_reason"><span class="text-negative">Anulada:</span> {{ detalle.void_reason }}</div>
          </div>
          <q-markup-table flat class="app-table q-mt-sm">
            <thead>
              <tr>
                <th class="text-left">Descripción</th>
                <th class="text-right">Cant.</th>
                <th class="text-right">Precio</th>
                <th class="text-right">Desc.%</th>
                <th class="text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="l in detalle.lines" :key="l.id">
                <td>{{ l.description }}</td>
                <td class="text-right">{{ formatQty(l.quantity) }}</td>
                <td class="text-right">{{ formatMoney(l.unit_price) }}</td>
                <td class="text-right">{{ (Number(l.discount_pct) * 100).toFixed(0) }}</td>
                <td class="text-right">{{ formatMoney(l.line_total) }}</td>
              </tr>
            </tbody>
          </q-markup-table>
          <div class="hist-detalle__totales">
            <div><span class="text-muted">Subtotal</span><span>{{ formatMoney(detalle.subtotal) }}</span></div>
            <div><span class="text-muted">IVA</span><span>{{ formatMoney(detalle.tax_total) }}</span></div>
            <div class="hist-detalle__total"><span>TOTAL</span><span>{{ formatMoney(detalle.total) }}</span></div>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-if="detalle && detalle.status === 'ISSUED'" flat no-caps icon="print" label="Reimprimir (COPIA)" @click="reimprimir(detalle)" />
          <q-btn flat no-caps label="Cerrar" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Devolución -->
    <q-dialog v-model="dlgDevolucion">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Devolución (nota de crédito)</q-card-section>
        <q-card-section v-if="objetivo" class="app-form">
          <q-banner dense rounded class="hist-banner">
            Factura {{ objetivo.series }}-{{ objetivo.number }} ·
            {{ objetivo.customer_party_display_name || objetivo.customer_name || 'Consumidor final' }} ·
            {{ formatMoney(objetivo.total) }}
            <span v-if="Number(objetivo.credited_total) > 0" class="text-negative">
              · ya acreditado {{ formatMoney(objetivo.credited_total) }}
            </span>
          </q-banner>
          <q-input v-model="devMotivo" outlined dense label="Motivo *" autofocus />
          <q-toggle v-model="devRestock" label="Reingresar la mercadería al inventario" color="primary" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="warning"
            label="Emitir nota de crédito"
            :loading="enviando"
            :disable="devMotivo.trim().length < 3"
            @click="emitirDevolucion"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Anulación -->
    <q-dialog v-model="dlgAnular">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Anular factura</q-card-section>
        <q-card-section v-if="objetivo" class="app-form">
          <q-banner dense rounded class="hist-banner hist-banner--alerta">
            Vas a anular la factura {{ objetivo.series }}-{{ objetivo.number }} por {{ formatMoney(objetivo.total) }}.
            Esta acción es definitiva y queda auditada.
          </q-banner>
          <q-input v-model="anularMotivo" outlined dense label="Motivo de la anulación *" autofocus />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="negative"
            label="Anular factura"
            :loading="enviando"
            :disable="anularMotivo.trim().length < 3"
            @click="confirmarAnulacion"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatMoney, formatQty } from 'src/core/format';
import {
  BILLING_DOC_TYPE_LABELS,
  FISCAL_STATUS_LABELS,
  PAYMENT_METHOD_LABELS,
  PAYMENT_STATUS_LABELS,
  getBillingDoc,
  issueCreditNote,
  listBillingDocs,
  printBillingDoc,
  voidBillingDoc,
  type BillingDoc,
  type BillingDocRow,
  type BillingDocStatus,
  type BillingFilters,
} from 'src/modules/billing/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const ESTADO_LABELS: Record<string, string> = {
  DRAFT: 'Borrador',
  ISSUED: 'Emitida',
  VOIDED: 'Anulada',
};

/** Color de fondo del chip de estado (paleta de acentos del tema). */
function colorEstado(status: string): string {
  if (status === 'ISSUED') return 'var(--app-accent-teal)';
  if (status === 'VOIDED') return 'var(--app-accent-coral)';
  return 'var(--app-text-muted)';
}

const opcionesEstado = [
  { label: 'Todas', value: '' },
  { label: 'Emitidas', value: 'ISSUED' },
  { label: 'Anuladas', value: 'VOIDED' },
  { label: 'Borrador', value: 'DRAFT' },
];

const columnas: QTableColumn<BillingDocRow>[] = [
  { name: 'doc', label: 'Documento', field: 'number', align: 'left' },
  { name: 'cliente', label: 'Cliente', field: 'customer_name', align: 'left' },
  { name: 'total', label: 'Total', field: 'total', align: 'right' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

/**
 * Fecha de HOY en la zona LOCAL del navegador (YYYY-MM-DD), NO en UTC.
 * Las ventas se filtran por `issued_at` (UTC) pero el rango por defecto debe
 * abarcar el día tal como lo vive el usuario: en Nicaragua (UTC-6) las ventas
 * de la tarde-noche caen en el día UTC siguiente, así que un rango de un día
 * calculado con toISOString() las dejaría fuera. Construimos la fecha con los
 * getters locales para respetar la zona del navegador.
 */
function hoyLocal(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

const hoy = hoyLocal();
const desde = ref(hoy);
const hasta = ref(hoy);
const estado = ref('ISSUED');
const busqueda = ref('');
const ventas = ref<BillingDocRow[]>([]);
const cargando = ref(false);

async function cargar() {
  cargando.value = true;
  try {
    const filtros: BillingFilters = { doc_type: 'INVOICE' };
    if (estado.value) filtros.status = estado.value as BillingDocStatus;
    if (busqueda.value?.trim()) filtros.q = busqueda.value.trim();
    if (desde.value) filtros.date_from = desde.value;
    if (hasta.value) filtros.date_to = hasta.value;
    ventas.value = await listBillingDocs(filtros);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el historial.') });
  } finally {
    cargando.value = false;
  }
}

function fechaCorta(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString('es-NI', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—';
}
function fechaLarga(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString('es-NI') : '—';
}

// --- Detalle ---
const dlgDetalle = ref(false);
const detalle = ref<BillingDoc | null>(null);
const cargandoDetalle = ref(false);

async function verDetalle(row: BillingDocRow) {
  detalle.value = null;
  dlgDetalle.value = true;
  cargandoDetalle.value = true;
  try {
    detalle.value = await getBillingDoc(row.id);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo abrir el detalle.') });
    dlgDetalle.value = false;
  } finally {
    cargandoDetalle.value = false;
  }
}

// --- Reimpresión (marcada como COPIA) ---
async function reimprimir(row: BillingDocRow | BillingDoc) {
  let doc: BillingDoc;
  try {
    doc = 'lines' in row ? row : await getBillingDoc(row.id);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar la factura.') });
    return;
  }
  imprimirCopia(doc);
  // Reimpresión fiscal (queda trazada como un job propio con su responsable).
  if (puede('billing.doc.print')) {
    try {
      await printBillingDoc(doc.id);
    } catch {
      /* la copia en pantalla ya salió; la impresión fiscal es best-effort */
    }
  }
}

function imprimirCopia(doc: BillingDoc) {
  const filas = doc.lines
    .map(
      (l) =>
        `<tr><td>${l.description}</td><td class="n">${formatQty(l.quantity)}</td><td class="n">${Number(l.unit_price).toFixed(2)}</td><td class="n">${Number(l.line_total).toFixed(2)}</td></tr>`,
    )
    .join('');
  const cliente = doc.customer_party_display_name || doc.customer_name || 'Consumidor final';
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Copia ${doc.series}-${doc.number}</title>
<style>
  body { font-family: 'Courier New', monospace; width: 72mm; margin: 0 auto; font-size: 12px; color: #000; }
  h1 { font-size: 14px; text-align: center; margin: 4px 0; }
  .copia { text-align: center; font-weight: bold; border: 1px dashed #000; padding: 2px; margin: 4px 0; }
  .c { text-align: center; margin: 2px 0; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  th, td { text-align: left; padding: 1px 2px; }
  .n { text-align: right; }
  .tot { border-top: 1px dashed #000; font-weight: bold; }
  @media print { @page { margin: 0; size: 80mm auto; } }
</style></head><body>
  <h1>Factura ${doc.series}-${doc.number}</h1>
  <div class="copia">COPIA — REIMPRESIÓN<br>${new Date().toLocaleString('es-NI')}</div>
  <div class="c">Emitida: ${fechaLarga(doc.issued_at || doc.created_at)}</div>
  <div class="c">Cliente: ${cliente}</div>
  <table>
    <thead><tr><th>Producto</th><th class="n">Cant</th><th class="n">Precio</th><th class="n">Total</th></tr></thead>
    <tbody>${filas}</tbody>
    <tfoot>
      <tr><td colspan="3" class="n">Subtotal</td><td class="n">${Number(doc.subtotal).toFixed(2)}</td></tr>
      <tr><td colspan="3" class="n">IVA</td><td class="n">${Number(doc.tax_total).toFixed(2)}</td></tr>
      <tr class="tot"><td colspan="3" class="n">TOTAL C$</td><td class="n">${Number(doc.total).toFixed(2)}</td></tr>
    </tfoot>
  </table>
  <div class="c" style="margin-top:8px">Documento sin valor fiscal (copia)</div>
</body></html>`;
  const win = window.open('', '_blank', 'width=420,height=600');
  if (!win) {
    $q.notify({ type: 'warning', message: 'El navegador bloqueó la ventana de la copia.' });
    return;
  }
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 250);
}

// --- Devolución / Anulación ---
const objetivo = ref<BillingDocRow | null>(null);
const enviando = ref(false);

const dlgDevolucion = ref(false);
const devMotivo = ref('');
const devRestock = ref(true);

function abrirDevolucion(row: BillingDocRow) {
  objetivo.value = row;
  devMotivo.value = '';
  devRestock.value = true;
  dlgDevolucion.value = true;
}

async function emitirDevolucion() {
  if (!objetivo.value) return;
  enviando.value = true;
  try {
    const r = await issueCreditNote(objetivo.value.id, {
      reason: devMotivo.value.trim(),
      restock: devRestock.value,
    });
    dlgDevolucion.value = false;
    $q.notify({
      type: 'positive',
      message: `Nota de crédito #${r.number} por ${formatMoney(r.total)}${devRestock.value ? '; mercadería reingresada' : ''}.`,
    });
    void cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo emitir la devolución.') });
  } finally {
    enviando.value = false;
  }
}

const dlgAnular = ref(false);
const anularMotivo = ref('');

function abrirAnulacion(row: BillingDocRow) {
  objetivo.value = row;
  anularMotivo.value = '';
  dlgAnular.value = true;
}

async function confirmarAnulacion() {
  if (!objetivo.value) return;
  enviando.value = true;
  try {
    await voidBillingDoc(objetivo.value.id, anularMotivo.value.trim());
    dlgAnular.value = false;
    $q.notify({ type: 'positive', message: 'Factura anulada.' });
    void cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo anular.') });
  } finally {
    enviando.value = false;
  }
}

onMounted(cargar);
</script>

<style scoped>
.hist-filtros {
  display: flex;
  gap: var(--app-space-3);
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: var(--app-space-3);
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-left: 5px solid var(--app-primary);
  border-radius: var(--app-radius-md);
  background: color-mix(in srgb, var(--app-primary) 6%, var(--app-surface-strong));
  box-shadow: var(--app-shadow-soft);
}

.hist-estado {
  min-width: 160px;
}

.hist-buscar {
  flex: 1;
  min-width: 220px;
}

.hist-num {
  font-weight: 700;
  color: var(--app-primary);
}

.hist-fecha,
.hist-pago,
.hist-credito {
  font-size: 0.75rem;
}

.hist-detalle {
  width: 620px;
  max-width: 95vw;
}

.hist-detalle__meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 2px var(--app-space-3);
  font-size: 0.88rem;
}

.hist-detalle__totales {
  margin-top: var(--app-space-2);
}

.hist-detalle__totales > div {
  display: flex;
  justify-content: space-between;
  padding: 1px 0;
}

.hist-detalle__total {
  font-size: 1.3rem;
  font-weight: 800;
  color: var(--app-primary);
  border-top: 1px solid var(--app-border);
  margin-top: var(--app-space-1);
  padding-top: var(--app-space-1);
}

.hist-banner {
  background: var(--app-surface-strong);
  border: 1px solid var(--app-border);
}

.hist-banner--alerta {
  border-color: var(--q-negative);
}
</style>
