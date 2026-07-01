<template>
  <q-page class="app-page">
    <PageHeader
      :title="oc ? `Orden de compra ${oc.series}-${oc.number}` : 'Orden de compra'"
      :subtitle="oc ? `${oc.supplier_display_name} · ${PO_STATUS_LABELS[oc.status]}` : ''"
      :loading="cargando"
      @refresh="cargar"
    >
      <template #actions>
        <BackButton to="/compras" />
      </template>
    </PageHeader>

    <template v-if="oc">
      <!-- Resumen -->
      <div class="ocd-resumen">
        <q-card flat bordered class="ocd-card">
          <q-card-section>
            <div class="text-muted">Estado</div>
            <EstadoChip :estado="oc.status" :map="MAPA_OC" />
            <div v-if="oc.submitted_by" class="text-caption text-muted q-mt-xs">
              Enviada por {{ oc.submitted_by }}
              <span v-if="oc.approved_by"> · aprobada por {{ oc.approved_by }}</span>
            </div>
          </q-card-section>
        </q-card>
        <q-card flat bordered class="ocd-card">
          <q-card-section>
            <div class="text-muted">Total de la orden</div>
            <div class="ocd-monto">{{ formatMoney(oc.total) }}</div>
            <div class="text-caption text-muted">
              Subtotal {{ formatMoney(oc.subtotal) }} · IVA {{ formatMoney(oc.tax_total) }}
            </div>
          </q-card-section>
        </q-card>
        <q-card flat bordered class="ocd-card">
          <q-card-section>
            <div class="text-muted">Recibido pendiente de facturar</div>
            <div class="ocd-monto">{{ formatMoney(oc.pending_to_invoice) }}</div>
            <div class="text-caption text-muted">Base del cruce OC ↔ recepción ↔ factura</div>
          </q-card-section>
        </q-card>
      </div>

      <!-- Botonera por estado -->
      <div class="ocd-acciones">
        <template v-if="oc.status === 'DRAFT'">
          <q-btn
            v-if="puede('procurement.order.submit')"
            unelevated no-caps color="primary" icon="send"
            label="Enviar a aprobación" @click="accion(() => submitPurchaseOrder(oc!.id))"
          />
          <q-btn
            v-if="puede('procurement.order.close')"
            flat no-caps color="negative" icon="cancel" label="Cancelar" @click="cancelar"
          />
        </template>
        <template v-else-if="oc.status === 'PENDING_APPROVAL'">
          <q-btn
            v-if="puede('procurement.order.approve')"
            unelevated no-caps color="positive" icon="check"
            label="Aprobar" @click="accion(() => approvePurchaseOrder(oc!.id))"
          />
          <q-btn
            v-if="puede('procurement.order.close')"
            flat no-caps color="negative" icon="cancel" label="Cancelar" @click="cancelar"
          />
        </template>
        <template v-else-if="oc.status === 'APPROVED'">
          <q-btn
            v-if="puede('procurement.order.send')"
            unelevated no-caps color="primary" icon="local_shipping"
            label="Marcar enviada al proveedor" @click="accion(() => sendPurchaseOrder(oc!.id))"
          />
          <q-btn
            v-if="puede('procurement.order.close')"
            flat no-caps color="negative" icon="cancel" label="Cancelar" @click="cancelar"
          />
        </template>
        <template v-else-if="oc.status === 'SENT' || oc.status === 'PARTIALLY_RECEIVED'">
          <q-btn
            v-if="puede('procurement.order.receive')"
            unelevated no-caps color="primary" icon="inventory"
            label="Recibir mercadería" @click="abrirRecepcion"
          />
          <q-btn
            v-if="puede('procurement.doc.create')"
            outline no-caps color="primary" icon="receipt_long"
            label="Registrar factura" @click="abrirFactura"
          />
          <q-btn
            v-if="puede('procurement.order.close')"
            flat no-caps icon="lock" label="Cerrar" @click="accion(() => closePurchaseOrder(oc!.id))"
          />
        </template>
        <template v-else-if="oc.status === 'RECEIVED'">
          <q-btn
            v-if="puede('procurement.doc.create')"
            unelevated no-caps color="primary" icon="receipt_long"
            label="Registrar factura" @click="abrirFactura"
          />
          <q-btn
            v-if="puede('procurement.order.close')"
            flat no-caps icon="lock" label="Cerrar" @click="accion(() => closePurchaseOrder(oc!.id))"
          />
        </template>
      </div>

      <!-- Líneas -->
      <div class="text-subtitle1 q-mt-md">Líneas</div>
      <q-markup-table flat class="app-table">
        <thead>
          <tr>
            <th class="text-left">Artículo</th>
            <th class="text-right">Pedida</th>
            <th class="text-right">Recibida</th>
            <th class="text-right">Pendiente</th>
            <th class="text-right">Costo unit.</th>
            <th class="text-right">IVA</th>
            <th class="text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ln in oc.lines" :key="ln.id">
            <td>
              {{ ln.item_name }} <span class="text-muted">({{ ln.item_sku }})</span>
            </td>
            <td class="text-right">{{ formatQty(ln.qty_ordered) }}</td>
            <td class="text-right">{{ formatQty(ln.qty_received) }}</td>
            <td class="text-right" :class="Number(ln.qty_pending) > 0 ? 'text-warning' : ''">
              {{ formatQty(ln.qty_pending) }}
            </td>
            <td class="text-right">{{ formatMoney(ln.unit_cost) }}</td>
            <td class="text-right">{{ (Number(ln.tax_rate) * 100).toFixed(0) }}%</td>
            <td class="text-right">{{ formatMoney(ln.line_total) }}</td>
          </tr>
        </tbody>
      </q-markup-table>

      <!-- Recepciones -->
      <div class="text-subtitle1 q-mt-md">Recepciones ({{ oc.receipts.length }})</div>
      <q-list v-if="oc.receipts.length" bordered separator class="rounded-borders">
        <q-expansion-item v-for="r in oc.receipts" :key="r.id">
          <template #header>
            <q-item-section>
              <q-item-label>RC-{{ r.number }} · {{ r.warehouse_name }}</q-item-label>
              <q-item-label caption>
                {{ formatDateTime(r.posted_at) }} · recibió {{ r.received_by || '—' }}
              </q-item-label>
            </q-item-section>
          </template>
          <q-card>
            <q-card-section>
              <div v-for="(rl, i) in r.lines" :key="i" class="ocd-recline">
                {{ rl.item_name }} — {{ formatQty(rl.qty) }} × {{ formatMoney(rl.unit_cost) }}
              </div>
            </q-card-section>
          </q-card>
        </q-expansion-item>
      </q-list>
      <div v-else class="text-muted">Aún sin recepciones.</div>

      <!-- Facturas ligadas -->
      <div class="text-subtitle1 q-mt-md">Facturas del proveedor ({{ oc.invoices.length }})</div>
      <q-markup-table v-if="oc.invoices.length" flat class="app-table">
        <thead>
          <tr>
            <th class="text-left">Número</th>
            <th class="text-left">Ref. proveedor</th>
            <th class="text-right">Total</th>
            <th class="text-left">Estado</th>
            <th class="text-left">Fecha</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in oc.invoices" :key="f.id">
            <td>{{ f.number > 0 ? `${f.series}-${f.number}` : 'borrador' }}</td>
            <td>{{ f.supplier_ref || '—' }}</td>
            <td class="text-right">{{ formatMoney(f.total) }}</td>
            <td><EstadoChip :estado="f.status" /></td>
            <td>{{ formatDate(f.created_at) }}</td>
            <td>
              <q-btn flat dense no-caps label="Abrir" @click="$router.push(`/compras/${f.id}`)" />
            </td>
          </tr>
        </tbody>
      </q-markup-table>
      <div v-else class="text-muted">Aún sin facturas.</div>
    </template>

    <!-- Diálogo: recibir mercadería -->
    <q-dialog v-model="dlgRecibir">
      <q-card class="app-dialog ocd-dialogo">
        <q-card-section class="text-h6">Recibir mercadería</q-card-section>
        <q-card-section class="app-form">
          <q-select
            v-model="recBodega"
            :options="opcionesBodega"
            outlined
            dense
            emit-value
            map-options
            label="Bodega de destino *"
          />
          <q-markup-table flat dense class="app-table">
            <thead>
              <tr>
                <th class="text-left">Artículo</th>
                <th class="text-right">Pendiente</th>
                <th class="text-right" style="width: 130px">Recibir ahora</th>
                <th class="text-right" style="width: 130px">Costo real</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ln in recLineas" :key="ln.order_line_id">
                <td>{{ ln.nombre }}</td>
                <td class="text-right">{{ formatQty(ln.pendiente) }}</td>
                <td>
                  <q-input v-model="ln.qty" dense borderless type="number" min="0" :max="ln.pendiente" input-class="text-right" />
                </td>
                <td>
                  <q-input v-model="ln.unit_cost" dense borderless type="number" min="0" input-class="text-right" />
                </td>
              </tr>
            </tbody>
          </q-markup-table>
          <div class="text-caption text-muted">
            Cada línea recibida entra al inventario (kardex) al costo real y actualiza el último
            costo del proveedor. Dejá en 0 lo que no llegó.
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Postear recepción"
            :loading="recibiendo"
            :disable="!recValida"
            @click="recibir"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: registrar factura con 3-way match -->
    <q-dialog v-model="dlgFactura">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Factura del proveedor</q-card-section>
        <q-card-section class="app-form">
          <q-banner dense rounded class="ocd-banner">
            Recibido pendiente de facturar: <strong>{{ formatMoney(oc?.pending_to_invoice ?? '0') }}</strong>
            (tolerancia ±2%). Si hay un borrador de factura previo, ya consume ese valor.
          </q-banner>
          <q-input v-model="facRef" outlined dense label="Nº de factura física del proveedor" />
          <q-input v-model="facSubtotal" outlined dense type="number" min="0" label="Subtotal C$ *" />
          <q-input v-model="facIva" outlined dense type="number" min="0" label="Impuesto C$" />
          <q-input :model-value="formatMoney(facTotal)" outlined dense readonly label="Total (subtotal + impuesto)" />
          <q-toggle
            v-if="puede('procurement.invoice.match_override')"
            v-model="facForzar"
            color="warning"
            label="Forzar fuera de tolerancia (queda auditado)"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear borrador de factura"
            :loading="facturando"
            :disable="facSubtotal === ''"
            @click="facturar"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: cancelar -->
    <q-dialog v-model="dlgCancelar">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Cancelar orden</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="motivoCancelar" outlined dense autofocus label="Motivo" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps v-close-popup />
          <q-btn
            unelevated no-caps color="negative" label="Cancelar la orden"
            @click="accion(() => cancelPurchaseOrder(oc!.id, motivoCancelar), () => (dlgCancelar = false))"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import BackButton from 'src/components/BackButton.vue';
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import EstadoChip from 'src/components/EstadoChip.vue';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatDate, formatDateTime, formatMoney, formatQty } from 'src/core/format';
import { listWarehouses, type Warehouse } from 'src/modules/inventory/api';
import { MENSAJES_COMPRAS } from 'src/modules/procurement/messages';
import {
  approvePurchaseOrder,
  cancelPurchaseOrder,
  closePurchaseOrder,
  getPurchaseOrder,
  invoicePurchaseOrder,
  PO_STATUS_LABELS,
  receivePurchaseOrder,
  sendPurchaseOrder,
  submitPurchaseOrder,
  type PurchaseOrderDetail,
} from 'src/modules/procurement/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const route = useRoute();
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

const ocId = computed(() => Number(route.params.id));
const oc = ref<PurchaseOrderDetail | null>(null);
const cargando = ref(false);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

function notificarError(e: unknown, fallback: string) {
  const crudo = apiErrorMessage(e, fallback);
  $q.notify({ type: 'negative', message: MENSAJES_COMPRAS[crudo] ?? crudo });
}

async function cargar() {
  cargando.value = true;
  try {
    oc.value = await getPurchaseOrder(ocId.value);
  } catch (e) {
    notificarError(e, 'No se pudo cargar la orden.');
    await router.push('/compras');
  } finally {
    cargando.value = false;
  }
}

async function accion(fn: () => Promise<unknown>, despues?: () => void) {
  try {
    await fn();
    despues?.();
    await cargar();
  } catch (e) {
    notificarError(e, 'No se pudo completar la acción.');
  }
}

// --- Cancelar ---
const dlgCancelar = ref(false);
const motivoCancelar = ref('');

function cancelar() {
  motivoCancelar.value = '';
  dlgCancelar.value = true;
}

// --- Recepción ---
interface RecLinea {
  order_line_id: number;
  nombre: string;
  pendiente: string;
  qty: string;
  unit_cost: string;
}

const dlgRecibir = ref(false);
const recibiendo = ref(false);
const recBodega = ref<number | null>(null);
const recLineas = ref<RecLinea[]>([]);
const bodegas = ref<Warehouse[]>([]);
const opcionesBodega = computed(() => bodegas.value.map((w) => ({ label: w.name, value: w.id })));

const recValida = computed(
  () =>
    recBodega.value != null &&
    recLineas.value.some((ln) => Number(ln.qty) > 0) &&
    recLineas.value.every(
      (ln) => Number(ln.qty) >= 0 && Number(ln.qty) <= Number(ln.pendiente) && Number(ln.unit_cost) >= 0,
    ),
);

function abrirRecepcion() {
  if (!oc.value) return;
  recLineas.value = oc.value.lines
    .filter((ln) => Number(ln.qty_pending) > 0)
    .map((ln) => ({
      order_line_id: ln.id,
      nombre: `${ln.item_name} (${ln.item_sku})`,
      pendiente: ln.qty_pending,
      qty: ln.qty_pending,
      unit_cost: ln.unit_cost,
    }));
  recBodega.value = bodegas.value.find((w) => w.is_default)?.id ?? bodegas.value[0]?.id ?? null;
  dlgRecibir.value = true;
}

async function recibir() {
  if (!oc.value || recBodega.value == null) return;
  recibiendo.value = true;
  try {
    const out = await receivePurchaseOrder(oc.value.id, {
      warehouse_id: recBodega.value,
      lines: recLineas.value
        .filter((ln) => Number(ln.qty) > 0)
        .map((ln) => ({
          order_line_id: ln.order_line_id,
          qty: String(ln.qty),
          unit_cost: Number(ln.unit_cost).toFixed(4),
        })),
    });
    dlgRecibir.value = false;
    $q.notify({
      type: 'positive',
      message: `Recepción RC-${out.number} posteada; la orden quedó ${PO_STATUS_LABELS[out.order_status]}.`,
    });
    await cargar();
  } catch (e) {
    notificarError(e, 'No se pudo postear la recepción.');
  } finally {
    recibiendo.value = false;
  }
}

// --- Factura (3-way match) ---
const dlgFactura = ref(false);
const facturando = ref(false);
const facRef = ref('');
const facSubtotal = ref('');
const facIva = ref('');
const facForzar = ref(false);
const facTotal = computed(() => Number(facSubtotal.value || 0) + Number(facIva.value || 0));

function abrirFactura() {
  facRef.value = '';
  facSubtotal.value = '';
  facIva.value = '';
  facForzar.value = false;
  dlgFactura.value = true;
}

async function facturar() {
  if (!oc.value) return;
  facturando.value = true;
  try {
    const out = await invoicePurchaseOrder(oc.value.id, {
      subtotal: Number(facSubtotal.value || 0).toFixed(2),
      tax_total: Number(facIva.value || 0).toFixed(2),
      total: facTotal.value.toFixed(2),
      ...(facRef.value ? { supplier_ref: facRef.value } : {}),
      ...(facForzar.value ? { match_override: true } : {}),
    });
    dlgFactura.value = false;
    $q.notify({
      type: 'positive',
      message: 'Borrador de factura creado; postealo en Documentos para generar la cuenta por pagar.',
    });
    await router.push(`/compras/${out.doc_id}`);
  } catch (e) {
    notificarError(e, 'No se pudo registrar la factura.');
  } finally {
    facturando.value = false;
  }
}

onMounted(async () => {
  await cargar();
  try {
    bodegas.value = await listWarehouses();
  } catch {
    bodegas.value = [];
  }
});
</script>

<style scoped>
.ocd-resumen {
  display: flex;
  gap: var(--app-space-3);
  flex-wrap: wrap;
  margin-bottom: var(--app-space-3);
}

.ocd-card {
  flex: 1 1 220px;
}

.ocd-monto {
  font-size: 1.4rem;
  font-weight: 700;
}

.ocd-acciones {
  display: flex;
  gap: var(--app-space-2);
  flex-wrap: wrap;
  margin-bottom: var(--app-space-2);
}

.ocd-dialogo {
  min-width: min(720px, 95vw);
}

.ocd-banner {
  background: var(--app-surface-2);
}

.ocd-recline {
  padding: 2px 0;
}
</style>
