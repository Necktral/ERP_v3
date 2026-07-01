<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card class="app-dialog pago-prov-dlg">
      <q-card-section class="text-h6">Pago a proveedor</q-card-section>
      <q-card-section class="app-form">
        <PartySelect
          v-if="!payablePreseleccionada"
          v-model="partyId"
          role="SUPPLIER"
          label="Proveedor *"
          @selected="cargarCxpProveedor"
        />
        <q-select
          v-if="!payablePreseleccionada"
          v-model="payableId"
          :options="opcionesCxp"
          outlined
          dense
          emit-value
          map-options
          label="Cuenta por pagar *"
          :loading="cargandoCxp"
          :disable="!opcionesCxp.length"
          @update:model-value="onCxpElegida"
        />
        <div
          v-if="!payablePreseleccionada && partyId != null && !cargandoCxp && !opcionesCxp.length"
          class="text-caption text-muted"
        >
          Este proveedor no tiene cuentas por pagar abiertas.
        </div>
        <div v-if="seleccionada" class="pago-prov-resumen">
          Saldo pendiente: <strong>{{ formatMoney(seleccionada.outstanding_amount) }}</strong>
          <span v-if="seleccionada.supplier_invoice_number">
            · Factura {{ seleccionada.supplier_invoice_number }}</span
          >
        </div>
        <q-input
          v-model="form.amount"
          outlined
          dense
          type="number"
          min="0.01"
          label="Monto a pagar *"
        />
        <q-select
          v-model="form.method"
          :options="opcionesMetodo"
          outlined
          dense
          emit-value
          map-options
          label="Método *"
          hint="El efectivo sale de la sesión de caja abierta; transferencia/cheque no la tocan."
        />
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat no-caps label="Cancelar" v-close-popup />
        <q-btn
          unelevated
          no-caps
          color="primary"
          icon="payments"
          label="Pagar"
          :loading="pagando"
          :disable="payableId == null || !form.amount || Number(form.amount) <= 0"
          @click="pagar"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { apiErrorMessage } from 'src/core/api';
import { formatMoney } from 'src/core/format';
import PartySelect from 'src/modules/parties/components/PartySelect.vue';
import { MENSAJES_PAGO_CXP } from 'src/modules/procurement/messages';
import { payPayable } from 'src/modules/procurement/api';
import { listPayables, type Payable } from 'src/modules/portfolio/api';
import { POS_PAYMENT_METHOD_LABELS } from 'src/modules/ventas/api';

const props = defineProps<{
  modelValue: boolean;
  /** CxP preseleccionada (p. ej. desde la tabla de Cartera); null = elegir proveedor. */
  payablePreseleccionada?: Payable | null;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'pagado'): void;
}>();

const $q = useQuasar();

const partyId = ref<number | null>(null);
const payableId = ref<number | null>(null);
const cxpProveedor = ref<Payable[]>([]);
const cargandoCxp = ref(false);
const pagando = ref(false);
const form = reactive({ amount: '', method: 'CASH' });

const opcionesMetodo = ['CASH', 'TRANSFER', 'CARD', 'CHECK'].map((value) => ({
  value,
  label: POS_PAYMENT_METHOD_LABELS[value] ?? value,
}));

const opcionesCxp = computed(() =>
  cxpProveedor.value
    .filter((p) => Number(p.outstanding_amount) > 0)
    .map((p) => ({
      value: p.id,
      label: `${p.supplier_invoice_number || `Ref ${p.reference_type} #${p.reference_id}`} · saldo ${formatMoney(p.outstanding_amount)}${p.is_overdue ? ' · VENCIDA' : ''}`,
    })),
);

const seleccionada = computed(() => {
  if (props.payablePreseleccionada) return props.payablePreseleccionada;
  return cxpProveedor.value.find((p) => p.id === payableId.value) ?? null;
});

watch(
  () => props.modelValue,
  (abierto) => {
    if (!abierto) return;
    partyId.value = null;
    cxpProveedor.value = [];
    Object.assign(form, { amount: '', method: 'CASH' });
    if (props.payablePreseleccionada) {
      payableId.value = props.payablePreseleccionada.id;
      form.amount = Number(props.payablePreseleccionada.outstanding_amount).toFixed(2);
    } else {
      payableId.value = null;
    }
  },
);

async function cargarCxpProveedor() {
  payableId.value = null;
  cxpProveedor.value = [];
  if (partyId.value == null) return;
  cargandoCxp.value = true;
  try {
    cxpProveedor.value = await listPayables({ party: partyId.value });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar las CxP.') });
  } finally {
    cargandoCxp.value = false;
  }
}

function onCxpElegida(id: number | null) {
  const pay = cxpProveedor.value.find((p) => p.id === id);
  if (pay) form.amount = Number(pay.outstanding_amount).toFixed(2);
}

async function pagar() {
  if (payableId.value == null) return;
  pagando.value = true;
  try {
    const out = await payPayable({
      payable_id: payableId.value,
      amount: Number(form.amount).toFixed(2),
      method: form.method,
      idempotency_key: crypto.randomUUID(),
    });
    emit('update:modelValue', false);
    $q.notify({
      type: 'positive',
      message: `Pago aplicado · saldo restante ${formatMoney(out.outstanding_after)}.`,
    });
    emit('pagado');
  } catch (e) {
    const crudo = apiErrorMessage(e, 'No se pudo aplicar el pago.');
    $q.notify({ type: 'negative', message: MENSAJES_PAGO_CXP[crudo] ?? crudo });
  } finally {
    pagando.value = false;
  }
}
</script>

<style scoped>
.pago-prov-dlg {
  width: 480px;
}

.pago-prov-resumen {
  color: var(--app-text);
  font-size: 0.9rem;
}
</style>
