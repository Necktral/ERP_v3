<template>
  <q-btn
    flat
    :round="!label"
    :dense="!label"
    :no-caps="!!label"
    icon="arrow_back"
    :label="label"
    :to="to"
    :aria-label="ariaLabel"
  />
</template>

<script setup lang="ts">
// Botón "Volver" estándar. Unifica el patrón repetido en ~19 páginas de detalle
// (q-btn flat round dense icon=arrow_back to=...). Con `label` se muestra como
// botón con texto; sin él, como botón redondo de ícono.
withDefaults(
  defineProps<{
    to: string;
    label?: string;
    ariaLabel?: string;
  }>(),
  { label: '', ariaLabel: 'Volver' },
);
</script>
