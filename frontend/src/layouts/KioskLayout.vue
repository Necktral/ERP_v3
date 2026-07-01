<template>
  <!-- Layout de kiosko: pantalla completa, sin menú ni topbar (el cliente no navega). -->
  <q-layout view="hHh lpR fFf" class="kiosk-shell">
    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
// Sin lógica: solo encuadra la pantalla del kiosko a pantalla completa.
</script>

<style scoped>
.kiosk-shell {
  min-height: 100vh;
  background: var(--app-bg-gradient);
  background-color: var(--app-bg);
}
</style>
