<template>
  <div class="arqueo">
    <p v-if="ayuda" class="text-caption text-muted arqueo__ayuda">{{ ayuda }}</p>

    <div class="arqueo__grid">
      <div
        v-for="(d, i) in modelValue"
        :key="`${d.denomination_type}-${d.denomination_value}`"
        class="arqueo__fila"
      >
        <span class="arqueo__valor">
          {{ d.denomination_type === 'BILL' ? 'Billete' : 'Moneda' }} {{ formatMoney(d.denomination_value) }}
        </span>
        <q-input
          :model-value="d.quantity"
          dense
          outlined
          type="number"
          min="0"
          inputmode="numeric"
          class="arqueo__cant"
          @update:model-value="setQty(i, $event)"
        />
        <span class="arqueo__sub">{{ formatMoney(Number(d.denomination_value) * (d.quantity || 0)) }}</span>
      </div>
    </div>

    <div class="arqueo__total">
      Contado: <strong>{{ formatMoney(total) }}</strong>
      <template v-if="esperado != null">
        · Esperado: <strong>{{ formatMoney(esperado) }}</strong>
        <span :class="diferencia === 0 ? 'text-positive' : 'text-negative'">
          · Diferencia: <strong>{{ formatMoney(diferencia) }}</strong>
          <template v-if="diferencia !== 0">({{ diferencia > 0 ? 'sobrante' : 'faltante' }})</template>
        </span>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Arqueo de efectivo reutilizable: grilla de denominaciones con cantidad por valor, subtotales y total.
 * `v-model` sobre el array de `Denomination` (se mutan las cantidades). Si se pasa `esperado`, muestra la
 * diferencia (sobrante/faltante). La lista de denominaciones la define el padre (ver `denominations.ts`).
 */
import { computed } from 'vue';
import { formatMoney } from 'src/core/format';
import { totalArqueo } from 'src/modules/payments/denominations';
import type { Denomination } from 'src/modules/payments/api';

const props = defineProps<{
  modelValue: Denomination[];
  esperado?: number | null;
  ayuda?: string;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', v: Denomination[]): void;
  (e: 'total', v: number): void;
}>();

const total = computed(() => totalArqueo(props.modelValue));
const diferencia = computed(() => (props.esperado != null ? total.value - props.esperado : 0));

// No mutar el prop: emitir un array NUEVO con la cantidad actualizada (el padre usa un ref → v-model reasigna).
function setQty(index: number, value: string | number | null) {
  const qty = Math.max(0, Math.trunc(Number(value) || 0));
  const next = props.modelValue.map((d, i) => (i === index ? { ...d, quantity: qty } : d));
  emit('update:modelValue', next);
  emit('total', totalArqueo(next));
}
</script>

<style scoped>
.arqueo__ayuda {
  margin-bottom: var(--app-space-2);
}
.arqueo__grid {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.arqueo__fila {
  display: grid;
  grid-template-columns: 1fr 96px 1fr;
  align-items: center;
  gap: var(--app-space-2);
}
.arqueo__valor {
  color: var(--app-text);
  font-size: 0.9rem;
}
.arqueo__cant :deep(.q-field__control) {
  height: 36px;
}
.arqueo__sub {
  text-align: right;
  color: var(--app-text-muted);
  font-variant-numeric: tabular-nums;
}
.arqueo__total {
  margin-top: var(--app-space-3);
  font-size: 0.95rem;
  color: var(--app-text);
}
</style>
