<template>
  <router-view />
</template>

<script setup lang="ts">
import { watch } from 'vue';
import { Dark } from 'quasar';
import { useUiStore } from 'src/stores/ui.store';

const ui = useUiStore();
ui.initFromStorage();

let systemMql: MediaQueryList | null = null;
let systemListener: ((e: MediaQueryListEvent) => void) | null = null;

function detachSystemListener() {
  if (!systemMql || !systemListener) return;
  systemMql.removeEventListener('change', systemListener);
  systemMql = null;
  systemListener = null;
}

function applyTheme(mode: 'cafetalero' | 'light' | 'dark' | 'system') {
  detachSystemListener();

  // El tema cafetalero usa una clase propia en <body>; la limpiamos siempre
  // antes de decidir, para que el cambio entre temas sea consistente.
  document.body.classList.toggle('theme-cafetalero', mode === 'cafetalero');

  if (mode === 'cafetalero') {
    Dark.set(false); // base clara (crema)
    document.documentElement.dataset.necktralTheme = 'cafetalero';
    return;
  }

  if (mode === 'light') {
    Dark.set(false);
    document.documentElement.dataset.necktralTheme = 'light';
    return;
  }

  if (mode === 'dark') {
    Dark.set(true);
    document.documentElement.dataset.necktralTheme = 'dark';
    return;
  }

  // system
  document.documentElement.dataset.necktralTheme = 'system';
  systemMql = window.matchMedia('(prefers-color-scheme: dark)');

  const setFromSystem = () => Dark.set(Boolean(systemMql && systemMql.matches));
  setFromSystem();

  systemListener = () => setFromSystem();

  systemMql.addEventListener('change', systemListener);
}

function applyDensity(mode: 'comfortable' | 'compact') {
  document.documentElement.dataset.necktralDensity = mode;
  document.body.classList.toggle('density-compact', mode === 'compact');
}

watch(
  () => ui.theme,
  (v) => applyTheme(v),
  { immediate: true },
);

watch(
  () => ui.density,
  (v) => applyDensity(v),
  { immediate: true },
);
</script>
