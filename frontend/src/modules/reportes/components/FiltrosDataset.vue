<template>
  <div class="fds-filtros">
    <template v-for="campo in campos" :key="campo.nombre">
      <q-input
        v-if="campo.tipo === 'date'"
        :model-value="valorTexto(campo.nombre)"
        dense
        outlined
        type="date"
        stack-label
        :label="etiqueta(campo)"
        class="fds-filtros__fecha"
        @update:model-value="(v) => setValor(campo.nombre, v)"
      />
      <q-input
        v-else-if="campo.tipo === 'int'"
        :model-value="valorNumero(campo.nombre)"
        dense
        outlined
        type="number"
        :label="etiqueta(campo)"
        class="fds-filtros__num"
        @update:model-value="(v) => setValor(campo.nombre, v === null || v === '' ? null : Number(v))"
      />
      <q-input
        v-else
        :model-value="valorTexto(campo.nombre)"
        dense
        outlined
        :label="etiqueta(campo)"
        class="fds-filtros__texto"
        @update:model-value="(v) => setValor(campo.nombre, v)"
      />
    </template>
    <div v-if="!campos.length" class="fds-filtros__vacio">Este reporte no lleva filtros.</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { FiltroSchemaCampo } from 'src/modules/reportes/api';
import { pretty } from 'src/modules/reportes/labels';

/**
 * Filtros dinámicos de un dataset a partir de su filters_schema del catálogo
 * ({ campo: { type: 'int'|'date'|'str', required } }). Emite el dict de filtros
 * listo para runDataset/generateSnapshot (sin claves vacías).
 */
const props = defineProps<{
  schema: Record<string, FiltroSchemaCampo>;
  modelValue: Record<string, unknown>;
}>();

const emit = defineEmits<{ 'update:modelValue': [value: Record<string, unknown>] }>();

interface Campo {
  nombre: string;
  tipo: string;
  requerido: boolean;
}

const campos = computed<Campo[]>(() =>
  Object.entries(props.schema ?? {}).map(([nombre, def]) => ({
    nombre,
    tipo: String(def?.type ?? 'str'),
    requerido: Boolean(def?.required),
  })),
);

function etiqueta(campo: Campo): string {
  return campo.requerido ? `${pretty(campo.nombre)} *` : pretty(campo.nombre);
}

function valorTexto(nombre: string): string {
  const v = props.modelValue[nombre];
  return typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' ? String(v) : '';
}

function valorNumero(nombre: string): number | null {
  const v = props.modelValue[nombre];
  return typeof v === 'number' ? v : null;
}

function setValor(nombre: string, valor: unknown) {
  const next = { ...props.modelValue };
  if (valor === null || valor === undefined || valor === '' || Number.isNaN(valor)) {
    delete next[nombre];
  } else {
    next[nombre] = valor;
  }
  emit('update:modelValue', next);
}
</script>

<style scoped>
.fds-filtros {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-3);
}

.fds-filtros__fecha {
  width: 160px;
}

.fds-filtros__num {
  width: 110px;
}

.fds-filtros__texto {
  width: 200px;
}

.fds-filtros__vacio {
  color: var(--app-text-muted);
  font-size: 0.82rem;
}
</style>
