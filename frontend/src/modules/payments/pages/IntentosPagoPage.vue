<template>
  <q-page class="app-page">
    <PageHeader
      title="Intentos de pago"
      subtitle="Ciclo de cobro: creado → autorizado → cobrado. El reembolso lo solicita una persona y lo aprueba otra."
      :loading="loading"
      @refresh="reload"
    >
      <template #actions>
        <BackButton to="/caja" />
        <q-btn
          v-if="puedeOperar"
          unelevated
          no-caps
          color="primary"
          icon="add_card"
          label="Nuevo intento"
          @click="abrirCrear"
        />
      </template>
    </PageHeader>

    <!-- SoD checker: reembolsos solicitados en esta sesión, pendientes de aprobación -->
    <q-card v-if="reembolsosPendientes.length" flat bordered class="app-card q-mb-md">
      <q-card-section class="row items-center justify-between">
        <div class="text-subtitle1">Reembolsos pendientes de aprobación</div>
        <q-chip dense square color="warning" text-color="white" :label="String(reembolsosPendientes.length)" />
      </q-card-section>
      <q-separator />
      <q-list separator>
        <q-item v-for="p in reembolsosPendientes" :key="p.requestId">
          <q-item-section>
            <q-item-label>{{ p.ref || p.paymentId.slice(0, 8) }} · {{ formatMoney(p.amount) }}</q-item-label>
            <q-item-label caption>Solicitud {{ p.requestId.slice(0, 8) }} — la aprueba una persona distinta al solicitante (SoD)</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn
              v-if="puedeAprobarReembolso"
              unelevated
              no-caps
              size="sm"
              color="positive"
              icon="verified"
              label="Aprobar"
              :loading="aprobando === p.requestId"
              @click="aprobarReembolso(p)"
            />
            <span v-else class="text-muted text-caption">Sin permiso para aprobar</span>
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>

    <q-table
      v-model:pagination="pagination"
      class="app-table"
      :rows="rows"
      :columns="columns"
      row-key="payment_id"
      flat
      :loading="loading"
      :rows-per-page-options="[10, 25, 50, 100]"
      no-data-label="No hay intentos de pago."
      @request="onRequest"
    >
      <template #body-cell-monto="props">
        <q-td :props="props">{{ formatMoney(props.row.amount) }}</q-td>
      </template>
      <template #body-cell-metodo="props">
        <q-td :props="props">
          {{ PAYMENT_METHOD_LABELS[props.row.payment_method] ?? props.row.payment_method ?? '—' }}
        </q-td>
      </template>
      <template #body-cell-estado="props">
        <q-td :props="props">
          {{ INTENT_STATUS_LABELS[props.row.status] ?? props.row.status }}
        </q-td>
      </template>
      <template #body-cell-fecha="props">
        <q-td :props="props">{{ formatDateTime(props.row.created_at) }}</q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props" class="text-right ipg-acciones">
          <template v-if="puedeOperar">
            <q-btn
              v-if="props.row.status === 'INTENDED'"
              flat
              dense
              no-caps
              size="sm"
              label="Autorizar"
              @click="accion(props.row, 'authorize')"
            />
            <q-btn
              v-if="props.row.status === 'INTENDED' || props.row.status === 'AUTHORIZED'"
              flat
              dense
              no-caps
              size="sm"
              color="primary"
              label="Cobrar"
              @click="accion(props.row, 'capture')"
            />
            <q-btn
              v-if="props.row.status === 'CAPTURED' || props.row.status === 'PARTIALLY_CAPTURED'"
              flat
              dense
              no-caps
              size="sm"
              color="warning"
              label="Reembolso"
              @click="pedirReembolso(props.row)"
            />
            <q-btn
              v-if="puedeOperar && (props.row.status === 'CAPTURED' || props.row.status === 'PARTIALLY_CAPTURED')"
              flat
              dense
              no-caps
              size="sm"
              color="negative"
              label="Reversar captura"
              @click="reversarCaptura(props.row)"
            />
            <q-btn
              v-if="props.row.status === 'INTENDED' || props.row.status === 'AUTHORIZED'"
              flat
              dense
              no-caps
              size="sm"
              color="negative"
              label="Cancelar"
              @click="accion(props.row, 'cancel')"
            />
          </template>
        </q-td>
      </template>
    </q-table>

    <!-- Diálogo: nuevo intento -->
    <q-dialog v-model="dlgCrear">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Nuevo intento de pago</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="form.amount" outlined dense type="number" min="0" label="Monto C$ *" autofocus />
          <q-select
            v-model="form.payment_method"
            :options="opcionesPago"
            label="Método"
            outlined
            dense
            emit-value
            map-options
            clearable
          />
          <q-input v-model="form.external_ref" outlined dense label="Referencia externa (factura…)" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear"
            :loading="accionando"
            :disable="!form.amount || Number(form.amount) <= 0"
            @click="crear"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import BackButton from 'src/components/BackButton.vue';
import { computed, reactive, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { formatDateTime, formatMoney } from 'src/core/format';
import { PAYMENT_METHOD_LABELS } from 'src/modules/billing/api';
import {
  approveRefund,
  authorizeIntent,
  cancelIntent,
  captureIntent,
  createPaymentIntent,
  INTENT_STATUS_LABELS,
  listPaymentIntentsPage,
  requestRefund,
  reverseCapturedIntent,
  type PaymentIntentRow,
} from 'src/modules/payments/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

// Paginación server-side: los intentos de pago crecen sin límite.
const { rows, loading, pagination, onRequest, reload } = useListadoServer<PaymentIntentRow>(
  (page) => listPaymentIntentsPage(page),
  { errorMessage: 'No se pudieron cargar los intentos de pago.' },
);

const puedeOperar = computed(() => {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, 'payments.intent.create') : false;
});
const puedeAprobarReembolso = computed(() => {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, 'payments.refund.approve') : false;
});

// Cola en memoria (igual que la reapertura de caja): el backend no lista aprobaciones
// pendientes, así que mostramos las solicitadas en esta sesión para que el checker apruebe.
interface ReembolsoPendiente {
  requestId: string;
  paymentId: string;
  amount: string;
  ref: string;
}
const reembolsosPendientes = ref<ReembolsoPendiente[]>([]);
const aprobando = ref<string | null>(null);

const opcionesPago = Object.entries(PAYMENT_METHOD_LABELS).map(([value, label]) => ({ value, label }));

const columns: QTableColumn<PaymentIntentRow>[] = [
  { name: 'external_ref', label: 'Referencia', field: 'external_ref', align: 'left' },
  { name: 'monto', label: 'Monto', field: 'amount', align: 'right' },
  { name: 'metodo', label: 'Método', field: 'payment_method', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'fecha', label: 'Creado', field: 'created_at', align: 'left' },
  { name: 'acciones', label: '', field: 'payment_id', align: 'right' },
];

const accionando = ref(false);

async function accion(row: PaymentIntentRow, tipo: 'authorize' | 'capture' | 'cancel') {
  try {
    if (tipo === 'authorize') await authorizeIntent(row.payment_id);
    else if (tipo === 'capture') await captureIntent(row.payment_id);
    else await cancelIntent(row.payment_id);
    $q.notify({ type: 'positive', message: 'Listo.' });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo ejecutar la acción.') });
  }
}

function reversarCaptura(row: PaymentIntentRow) {
  $q.dialog({
    title: 'Reversar captura',
    message: `Reversa TOTAL del cobro de ${formatMoney(row.amount)} (distinto del reembolso parcial). Indicá el motivo.`,
    prompt: { model: '', type: 'text', isValid: (v) => v.trim().length > 0 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'negative', label: 'Reversar' },
    persistent: true,
  }).onOk((motivo: string) => {
    void (async () => {
      try {
        await reverseCapturedIntent(row.payment_id, motivo.trim());
        $q.notify({ type: 'positive', message: 'Captura reversada.' });
        await reload();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo reversar la captura.') });
      }
    })();
  });
}

function pedirReembolso(row: PaymentIntentRow) {
  $q.dialog({
    title: 'Solicitar reembolso',
    message: `Monto a reembolsar (cobrado: ${formatMoney(row.amount)}). Otra persona debe aprobarlo.`,
    prompt: { model: row.amount, type: 'number', isValid: (v) => Number(v) > 0 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'warning', label: 'Solicitar' },
    persistent: true,
  }).onOk((monto: string) => {
    void (async () => {
      try {
        const r = await requestRefund(row.payment_id, { amount: Number(monto).toFixed(2) });
        reembolsosPendientes.value.push({
          requestId: r.approval_request_id,
          paymentId: row.payment_id,
          amount: Number(monto).toFixed(2),
          ref: row.external_ref,
        });
        $q.notify({ type: 'info', message: 'Reembolso solicitado; pendiente de aprobación (SoD).' });
        await reload();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo solicitar.') });
      }
    })();
  });
}

/** SoD checker: aprueba un reembolso pendiente (lo ejecuta otra persona distinta al solicitante). */
async function aprobarReembolso(p: ReembolsoPendiente) {
  aprobando.value = p.requestId;
  try {
    await approveRefund(p.requestId);
    reembolsosPendientes.value = reembolsosPendientes.value.filter((x) => x.requestId !== p.requestId);
    $q.notify({ type: 'positive', message: 'Reembolso aprobado y ejecutado.' });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo aprobar el reembolso.') });
  } finally {
    aprobando.value = null;
  }
}

// --- Crear ---
const dlgCrear = ref(false);
const form = reactive<{ amount: string; payment_method: string | null; external_ref: string }>({
  amount: '',
  payment_method: 'CASH',
  external_ref: '',
});

function abrirCrear() {
  Object.assign(form, { amount: '', payment_method: 'CASH', external_ref: '' });
  dlgCrear.value = true;
}

async function crear() {
  accionando.value = true;
  try {
    await createPaymentIntent({
      amount: Number(form.amount).toFixed(2),
      ...(form.payment_method ? { payment_method: form.payment_method } : {}),
      ...(form.external_ref ? { external_ref: form.external_ref } : {}),
    });
    dlgCrear.value = false;
    $q.notify({ type: 'positive', message: 'Intento de pago creado.' });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear.') });
  } finally {
    accionando.value = false;
  }
}
</script>

<style scoped>
.ipg-acciones {
  white-space: nowrap;
}
</style>
