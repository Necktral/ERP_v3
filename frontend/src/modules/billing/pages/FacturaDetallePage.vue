<template>
  <q-page class="app-page">
    <PageHeader :title="titulo" :subtitle="subtitulo" :loading="loading" @refresh="cargar">
      <template #actions>
        <BackButton to="/facturacion" />
        <q-btn
          v-if="doc?.status === 'DRAFT' && puede('billing.doc.issue')"
          unelevated
          no-caps
          color="primary"
          icon="task_alt"
          label="Emitir"
          :loading="accionando"
          @click="abrirEmitir"
        />
        <q-btn
          v-if="doc?.status === 'ISSUED' && doc.is_fiscal && puede('billing.doc.print')"
          outline
          no-caps
          color="primary"
          icon="print"
          label="Imprimir"
          :loading="accionando"
          @click="imprimir"
        />
        <q-btn
          v-if="doc?.doc_type === 'QUOTE' && doc.status !== 'VOIDED' && puede('billing.doc.create')"
          unelevated
          no-caps
          color="secondary"
          icon="receipt_long"
          label="Convertir a factura"
          :loading="accionando"
          @click="convertir"
        />
        <q-btn
          v-if="doc?.doc_type === 'INVOICE' && doc.status === 'ISSUED' && puede('billing.credit_note.issue')"
          outline
          no-caps
          color="warning"
          icon="assignment_return"
          label="Nota de crédito"
          @click="abrirNotaCredito"
        />
        <q-btn
          v-if="doc?.status === 'ISSUED' && puede('billing.doc.void')"
          outline
          no-caps
          color="negative"
          icon="block"
          label="Anular"
          :loading="accionando"
          @click="confirmarAnular"
        />
      </template>
    </PageHeader>

    <div v-if="doc" class="facd-grid">
      <div class="facd-card">
        <div class="facd-card__title">
          Documento
          <EstadoChip :estado="doc.status" />
        </div>
        <dl class="facd-dl">
          <dt>Número</dt>
          <dd>{{ doc.number > 0 ? `${doc.series}-${doc.number}` : 'Sin número (borrador)' }}</dd>
          <dt>Tipo</dt>
          <dd>{{ BILLING_DOC_TYPE_LABELS[doc.doc_type] }}</dd>
          <dt>Método de pago</dt>
          <dd>{{ PAYMENT_METHOD_LABELS[doc.payment_method] ?? doc.payment_method ?? '—' }}</dd>
          <dt>Emitido</dt>
          <dd>{{ formatDateTime(doc.issued_at) }}</dd>
          <dt v-if="doc.voided_at">Anulado</dt>
          <dd v-if="doc.voided_at">{{ formatDateTime(doc.voided_at) }} — {{ doc.void_reason }}</dd>
        </dl>
      </div>

      <div class="facd-card">
        <div class="facd-card__title">Cliente</div>
        <dl class="facd-dl">
          <dt>Nombre</dt>
          <dd>{{ doc.customer_party_display_name || doc.customer_name || '—' }}</dd>
          <dt>Referencia</dt>
          <dd>{{ doc.customer_ref || '—' }}</dd>
        </dl>
      </div>

      <!-- Abonos / estado de pago -->
      <div
        v-if="doc.doc_type === 'INVOICE' && doc.status === 'ISSUED' && puede('billing.payment.read')"
        class="facd-card"
      >
        <div class="facd-card__title">
          Pagos
          <EstadoChip :estado="doc.payment_status" :map="MAPA_PAGO" />
        </div>
        <dl class="facd-dl">
          <dt>Pagado</dt>
          <dd>{{ formatMoney(doc.amount_paid) }} de {{ formatMoney(doc.total) }}</dd>
          <dt v-if="Number(doc.credited_total) > 0">Acreditado (NC)</dt>
          <dd v-if="Number(doc.credited_total) > 0">{{ formatMoney(doc.credited_total) }}</dd>
        </dl>
        <q-list v-if="abonos.length" dense separator class="q-mt-sm">
          <q-item v-for="p in abonos" :key="p.id">
            <q-item-section>
              <q-item-label>
                {{ formatMoney(p.amount) }} · {{ PAYMENT_METHOD_LABELS[p.payment_method] ?? p.payment_method }}
              </q-item-label>
              <q-item-label caption>
                {{ p.payment_date }}{{ p.reference ? ` · ${p.reference}` : '' }}
                <span v-if="p.status === 'REVERSED'" class="text-negative"> · REVERTIDO</span>
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn
                v-if="p.status === 'CONFIRMED' && puede('billing.payment.reverse')"
                flat
                dense
                no-caps
                size="sm"
                color="negative"
                label="Revertir"
                @click="revertirAbono(p.id)"
              />
            </q-item-section>
          </q-item>
        </q-list>
        <q-btn
          v-if="puede('billing.payment.create') && doc.payment_status !== 'PAID'"
          unelevated
          no-caps
          dense
          color="primary"
          icon="add_card"
          label="Registrar abono"
          class="q-mt-sm"
          @click="abrirAbono"
        />
      </div>

      <div v-if="doc.is_fiscal" class="facd-card">
        <div class="facd-card__title">
          Fiscal
          <EstadoChip v-if="doc.fiscal?.status" :estado="doc.fiscal.status" :map="MAPA_FISCAL" />
        </div>
        <dl class="facd-dl">
          <dt>Referencia</dt>
          <dd>{{ doc.fiscal?.reference || '—' }}</dd>
          <dt>Impreso</dt>
          <dd>{{ formatDateTime(doc.fiscal?.printed_at) }}</dd>
          <dt>Intentos</dt>
          <dd>{{ doc.fiscal?.attempts ?? 0 }}</dd>
          <dt v-if="doc.fiscal?.last_error">Último error</dt>
          <dd v-if="doc.fiscal?.last_error" class="text-negative">{{ doc.fiscal.last_error }}</dd>
          <dt v-if="doc.fiscal?.contingency_reason">Contingencia</dt>
          <dd v-if="doc.fiscal?.contingency_reason">{{ doc.fiscal.contingency_reason }}</dd>
        </dl>
        <div class="q-mt-sm" v-if="doc.status === 'ISSUED'">
          <q-btn
            v-if="doc.fiscal?.status !== 'CONTINGENCY' && puede('billing.doc.contingency')"
            flat
            dense
            no-caps
            size="sm"
            icon="warning"
            color="warning"
            label="Marcar contingencia"
            @click="marcarContingencia"
          />
          <template v-if="doc.fiscal?.status === 'CONTINGENCY' && puede('billing.doc.contingency.resolve')">
            <q-btn
              flat
              dense
              no-caps
              size="sm"
              icon="refresh"
              color="primary"
              label="Reintentar impresión"
              @click="resolverContingencia('RETRY_PRINT')"
            />
            <q-btn
              flat
              dense
              no-caps
              size="sm"
              icon="block"
              color="negative"
              label="Anular por contingencia"
              @click="resolverContingencia('VOID')"
            />
          </template>
        </div>
      </div>

      <div class="facd-card facd-card--ancho">
        <div class="facd-card__title">Líneas</div>
        <q-markup-table flat dense class="facd-lineas">
          <thead>
            <tr>
              <th class="text-left">Descripción</th>
              <th class="text-right">Cantidad</th>
              <th class="text-right">Precio</th>
              <th class="text-right">IVA</th>
              <th class="text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="l in doc.lines" :key="l.id">
              <td class="text-left">{{ l.description }}</td>
              <td class="text-right">{{ formatQty(l.quantity) }}</td>
              <td class="text-right">{{ formatMoney(l.unit_price) }}</td>
              <td class="text-right">{{ formatMoney(l.line_tax) }}</td>
              <td class="text-right">{{ formatMoney(l.line_total) }}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td colspan="3"></td>
              <td class="text-right text-muted">Subtotal</td>
              <td class="text-right">{{ formatMoney(doc.subtotal) }}</td>
            </tr>
            <tr>
              <td colspan="3"></td>
              <td class="text-right text-muted">IVA</td>
              <td class="text-right">{{ formatMoney(doc.tax_total) }}</td>
            </tr>
            <tr>
              <td colspan="3"></td>
              <td class="text-right text-weight-bold">Total</td>
              <td class="text-right text-weight-bold">{{ formatMoney(doc.total) }}</td>
            </tr>
          </tfoot>
        </q-markup-table>
      </div>
    </div>

    <!-- Diálogo: emitir -->
    <q-dialog v-model="dlgEmitir">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Emitir documento</q-card-section>
        <q-card-section class="app-form">
          <div class="text-caption text-muted">
            Al emitir, el documento toma número{{ doc?.is_fiscal ? ' fiscal' : '' }} y queda en firme.
          </div>
          <q-toggle
            v-model="emitirForm.apply_inventory"
            label="Bajar inventario (líneas con artículo)"
            color="primary"
          />
          <q-select
            v-if="emitirForm.apply_inventory"
            v-model="emitirForm.warehouse_id"
            :options="opcionesBodega"
            label="Bodega de despacho *"
            outlined
            dense
            emit-value
            map-options
          />
          <q-toggle
            v-if="doc?.is_fiscal"
            v-model="emitirForm.print_after_issue"
            label="Imprimir al emitir"
            color="primary"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Emitir"
            :loading="accionando"
            :disable="emitirForm.apply_inventory && emitirForm.warehouse_id == null"
            @click="emitir"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: registrar abono -->
    <q-dialog v-model="dlgAbono">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Registrar abono</q-card-section>
        <q-card-section class="app-form">
          <div class="text-caption text-muted">
            Saldo pendiente: {{ formatMoney(saldoPendiente) }}
          </div>
          <q-select
            v-model="abonoForm.payment_method"
            :options="opcionesMetodoAbono"
            label="Método *"
            outlined
            dense
            emit-value
            map-options
          />
          <q-input
            v-model="abonoForm.amount"
            outlined
            dense
            type="number"
            min="0.01"
            label="Monto *"
            autofocus
          />
          <q-input v-model="abonoForm.reference" outlined dense label="Referencia (recibo, transferencia…)" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Registrar"
            :loading="accionando"
            :disable="!abonoForm.amount || Number(abonoForm.amount) <= 0"
            @click="registrarAbono"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: nota de crédito (devolución) -->
    <q-dialog v-model="dlgNC">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Nota de crédito (devolución)</q-card-section>
        <q-card-section class="app-form">
          <div class="text-caption text-muted">
            Acredita el TOTAL del documento ({{ formatMoney(doc?.total ?? 0) }}). Para devoluciones
            parciales usá líneas desde la API (próxima fase).
          </div>
          <q-input
            v-model="ncForm.reason"
            outlined
            dense
            label="Motivo *"
            hint="Ej: producto devuelto, error de facturación."
            autofocus
          />
          <q-toggle
            v-model="ncForm.restock"
            label="Reingresar la mercadería al inventario (mismo costo y lote)"
            color="primary"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="warning"
            label="Emitir nota de crédito"
            :loading="accionando"
            :disable="ncForm.reason.trim().length < 3"
            @click="emitirNotaCredito"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import BackButton from 'src/components/BackButton.vue';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import EstadoChip, { type EstadoEstilo } from 'src/components/EstadoChip.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatDateTime, formatMoney, formatQty } from 'src/core/format';
import {
  BILLING_DOC_TYPE_LABELS,
  convertQuoteToInvoice,
  createDocPayment,
  FISCAL_STATUS_LABELS,
  getBillingDoc,
  issueBillingDoc,
  issueCreditNote,
  listDocPayments,
  PAYMENT_METHOD_LABELS,
  PAYMENT_STATUS_LABELS,
  printBillingDoc,
  resolveBillingContingency,
  reverseDocPayment,
  setBillingContingency,
  voidBillingDoc,
  type BillingDoc,
  type BillingPayment,
} from 'src/modules/billing/api';
import { listWarehouses, type Warehouse } from 'src/modules/inventory/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const route = useRoute();
const router = useRouter();
const acl = useAclStore();
const ctx = useContextStore();

const MAPA_FISCAL: Record<string, EstadoEstilo> = Object.fromEntries(
  Object.entries(FISCAL_STATUS_LABELS).map(([code, label]) => [
    code,
    {
      label,
      color: code === 'PRINTED' || code === 'ISSUED' ? 'secondary' : code === 'NUMBER_RESERVED' ? 'grey-7' : 'warning',
      outline: true,
    },
  ]),
);

const MAPA_PAGO: Record<string, EstadoEstilo> = Object.fromEntries(
  Object.entries(PAYMENT_STATUS_LABELS).map(([code, label]) => [
    code,
    {
      label,
      color: code === 'PAID' ? 'positive' : code === 'PARTIAL' ? 'warning' : code === 'OVERPAID' ? 'negative' : 'grey-7',
      outline: true,
    },
  ]),
);

const docId = computed(() => Number(route.params.id));
const doc = ref<BillingDoc | null>(null);
const loading = ref(false);
const accionando = ref(false);
const bodegas = ref<Warehouse[]>([]);
const abonos = ref<BillingPayment[]>([]);

const titulo = computed(() =>
  doc.value
    ? doc.value.number > 0
      ? `${BILLING_DOC_TYPE_LABELS[doc.value.doc_type]} ${doc.value.series}-${doc.value.number}`
      : `${BILLING_DOC_TYPE_LABELS[doc.value.doc_type]} (borrador #${doc.value.id})`
    : 'Documento',
);
const subtitulo = computed(() =>
  doc.value ? `${doc.value.customer_party_display_name || doc.value.customer_name || 'Sin cliente'} · ${formatMoney(doc.value.total)}` : '',
);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const opcionesBodega = computed(() => bodegas.value.map((w) => ({ value: w.id, label: w.name })));

async function cargar() {
  loading.value = true;
  try {
    doc.value = await getBillingDoc(docId.value);
    if (
      doc.value.doc_type === 'INVOICE' &&
      doc.value.status === 'ISSUED' &&
      puede('billing.payment.read')
    ) {
      abonos.value = (await listDocPayments(docId.value)).results;
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el documento.') });
  } finally {
    loading.value = false;
  }
}

// --- Abonos ---
const dlgAbono = ref(false);
const abonoForm = reactive({ payment_method: 'CASH', amount: '', reference: '' });
const opcionesMetodoAbono = ['CASH', 'TRANSFER', 'CARD', 'CHECK'].map((value) => ({
  value,
  label: PAYMENT_METHOD_LABELS[value] ?? value,
}));

const saldoPendiente = computed(() =>
  doc.value ? Number(doc.value.total) - Number(doc.value.amount_paid) : 0,
);

function abrirAbono() {
  Object.assign(abonoForm, {
    payment_method: 'CASH',
    amount: saldoPendiente.value.toFixed(2),
    reference: '',
  });
  dlgAbono.value = true;
}

async function registrarAbono() {
  accionando.value = true;
  try {
    const r = await createDocPayment(docId.value, {
      payment_method: abonoForm.payment_method,
      amount: String(abonoForm.amount),
      reference: abonoForm.reference,
    });
    dlgAbono.value = false;
    $q.notify({
      type: 'positive',
      message: `Abono registrado · ${PAYMENT_STATUS_LABELS[r.payment_status] ?? r.payment_status}.`,
    });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo registrar el abono.') });
  } finally {
    accionando.value = false;
  }
}

function revertirAbono(paymentId: number) {
  $q.dialog({
    title: 'Revertir abono',
    message: 'Motivo de la reversa:',
    prompt: { model: '', type: 'text', isValid: (v: string) => v.trim().length >= 3 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'negative', label: 'Revertir' },
  }).onOk((motivo: string) => {
    void (async () => {
      try {
        await reverseDocPayment(docId.value, paymentId, motivo.trim());
        $q.notify({ type: 'positive', message: 'Abono revertido.' });
        await cargar();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo revertir.') });
      }
    })();
  });
}

// --- Nota de crédito ---
const dlgNC = ref(false);
const ncForm = reactive({ reason: '', restock: true });

function abrirNotaCredito() {
  Object.assign(ncForm, { reason: '', restock: true });
  dlgNC.value = true;
}

async function emitirNotaCredito() {
  accionando.value = true;
  try {
    const r = await issueCreditNote(docId.value, { reason: ncForm.reason.trim(), restock: ncForm.restock });
    dlgNC.value = false;
    $q.notify({
      type: 'positive',
      message: `Nota de crédito #${r.number} por ${formatMoney(r.total)} emitida${ncForm.restock ? '; mercadería reingresada' : ''}.`,
    });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo emitir la nota de crédito.') });
  } finally {
    accionando.value = false;
  }
}

// --- Convertir cotización ---
async function convertir() {
  accionando.value = true;
  try {
    const nuevoId = await convertQuoteToInvoice(docId.value);
    $q.notify({ type: 'positive', message: 'Factura creada desde la cotización.' });
    await router.push(`/facturacion/${nuevoId}`);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo convertir.') });
  } finally {
    accionando.value = false;
  }
}

// --- Emitir ---
const dlgEmitir = ref(false);
const emitirForm = reactive<{
  apply_inventory: boolean;
  warehouse_id: number | null;
  print_after_issue: boolean;
}>({ apply_inventory: false, warehouse_id: null, print_after_issue: false });

async function abrirEmitir() {
  if (bodegas.value.length === 0) {
    try {
      bodegas.value = await listWarehouses();
    } catch {
      /* sin bodegas: emitir sin inventario */
    }
  }
  Object.assign(emitirForm, { apply_inventory: false, warehouse_id: null, print_after_issue: false });
  dlgEmitir.value = true;
}

async function emitir() {
  accionando.value = true;
  try {
    const r = await issueBillingDoc(docId.value, {
      apply_inventory: emitirForm.apply_inventory,
      ...(emitirForm.warehouse_id != null ? { warehouse_id: emitirForm.warehouse_id } : {}),
      print_after_issue: emitirForm.print_after_issue,
    });
    dlgEmitir.value = false;
    $q.notify({ type: 'positive', message: `Documento emitido${r.number ? ` con número ${r.number}` : ''}.` });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo emitir.') });
  } finally {
    accionando.value = false;
  }
}

async function imprimir() {
  accionando.value = true;
  try {
    await printBillingDoc(docId.value);
    $q.notify({ type: 'positive', message: 'Impresión encolada.' });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo imprimir.') });
  } finally {
    accionando.value = false;
  }
}

function confirmarAnular() {
  $q.dialog({
    title: 'Anular documento',
    message:
      'La anulación es un control sensible (puede requerir aprobación de otra persona). Motivo:',
    prompt: { model: '', type: 'text', isValid: (v: string) => v.trim().length >= 3 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'negative', label: 'Anular' },
    persistent: true,
  }).onOk((motivo: string) => {
    void anular(motivo.trim());
  });
}

async function anular(motivo: string) {
  accionando.value = true;
  try {
    await voidBillingDoc(docId.value, motivo);
    $q.notify({ type: 'positive', message: 'Anulación registrada.' });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo anular.') });
  } finally {
    accionando.value = false;
  }
}

function marcarContingencia() {
  $q.dialog({
    title: 'Marcar contingencia',
    message: 'Motivo (ej. impresora fiscal sin papel / sin energía):',
    prompt: { model: '', type: 'text', isValid: (v: string) => v.trim().length >= 3 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'warning', label: 'Marcar' },
  }).onOk((motivo: string) => {
    void (async () => {
      try {
        await setBillingContingency(docId.value, motivo.trim());
        $q.notify({ type: 'warning', message: 'Documento en contingencia.' });
        await cargar();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo marcar.') });
      }
    })();
  });
}

async function resolverContingencia(action: 'RETRY_PRINT' | 'VOID') {
  accionando.value = true;
  try {
    await resolveBillingContingency(docId.value, action);
    $q.notify({ type: 'positive', message: action === 'RETRY_PRINT' ? 'Reintento encolado.' : 'Anulado por contingencia.' });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo resolver la contingencia.') });
  } finally {
    accionando.value = false;
  }
}

onMounted(cargar);
watch(docId, () => {
  void cargar();
});
</script>

<style scoped>
.facd-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: var(--app-space-4);
}

.facd-card {
  padding: var(--app-space-4);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
}

.facd-card--ancho {
  grid-column: 1 / -1;
}

.facd-card__title {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  font-weight: 800;
  color: var(--app-text);
  margin-bottom: var(--app-space-3);
}

.facd-dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--app-space-1) var(--app-space-4);
  margin: 0;
}

.facd-dl dt {
  color: var(--app-text-muted);
  font-size: 0.82rem;
}

.facd-dl dd {
  margin: 0;
  color: var(--app-text);
  font-size: 0.88rem;
}

.facd-lineas {
  background: transparent;
}
</style>
