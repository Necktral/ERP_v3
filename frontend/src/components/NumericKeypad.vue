<template>
  <div class="keypad" :style="{ '--kp-acc': accent }">
    <q-btn
      v-for="k in TECLAS"
      :key="k.v"
      unelevated
      no-caps
      class="keypad__key"
      :class="{ 'keypad__key--action': k.action }"
      :icon="k.icon"
      :label="k.label"
      @click="pulsar(k.v)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

/**
 * Teclado numérico en pantalla (táctil, para tableta). Edita un monto como string con hasta
 * 2 decimales. Si se pasa `max`, nunca deja superar ese tope (botón "Máx" lo rellena).
 */
const props = withDefaults(
  defineProps<{ modelValue: string; max?: number; accent?: string }>(),
  { accent: 'var(--app-primary)' },
);
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>();

type Tecla = { v: string; label?: string; icon?: string; action?: boolean };
const TECLAS: Tecla[] = [
  { v: '7', label: '7' }, { v: '8', label: '8' }, { v: '9', label: '9' },
  { v: '4', label: '4' }, { v: '5', label: '5' }, { v: '6', label: '6' },
  { v: '1', label: '1' }, { v: '2', label: '2' }, { v: '3', label: '3' },
  { v: '.', label: ',' }, { v: '0', label: '0' }, { v: 'back', icon: 'backspace', action: true },
  { v: 'clear', label: 'C', action: true }, { v: 'max', label: 'Máx', action: true },
];

const tope = computed(() => (props.max === undefined ? Infinity : props.max));

function clamp(raw: string): string {
  const n = Number(raw || 0);
  if (Number.isFinite(tope.value) && n > tope.value) return tope.value.toFixed(2);
  return raw;
}

function pulsar(v: string) {
  let s = props.modelValue || '';
  if (v === 'clear') {
    emit('update:modelValue', '');
    return;
  }
  if (v === 'max') {
    emit('update:modelValue', Number.isFinite(tope.value) ? tope.value.toFixed(2) : s);
    return;
  }
  if (v === 'back') {
    emit('update:modelValue', s.slice(0, -1));
    return;
  }
  if (v === '.') {
    if (s.includes('.')) return; // una sola coma decimal
    s = s === '' ? '0.' : s + '.';
    emit('update:modelValue', s);
    return;
  }
  // dígito 0-9: respetar 2 decimales como máximo
  const dot = s.indexOf('.');
  if (dot >= 0 && s.length - dot > 2) return;
  s = s === '0' ? v : s + v; // evitar ceros a la izquierda
  emit('update:modelValue', clamp(s));
}
</script>

<style scoped>
.keypad {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--app-space-2);
}

.keypad__key {
  font-size: 1.5rem;
  font-weight: 800;
  height: 60px;
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
  color: var(--app-text);
  border: 1px solid var(--app-border);
}

.keypad__key:hover {
  background: color-mix(in srgb, var(--kp-acc) 10%, var(--app-surface));
}

.keypad__key--action {
  background: color-mix(in srgb, var(--kp-acc) 14%, transparent);
  color: var(--kp-acc);
  font-size: 1.05rem;
}
</style>
