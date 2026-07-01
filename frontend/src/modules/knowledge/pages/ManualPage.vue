<template>
  <q-page class="app-page manual-page">
    <PageHeader
      title="Manual del sistema"
      subtitle="Guía interactiva de todos los módulos: primeros pasos, conceptos, roles y cada área de negocio."
      hide-refresh
    >
      <template #actions>
        <q-btn
          unelevated
          color="primary"
          icon="open_in_new"
          label="Abrir en pestaña nueva"
          :href="manualUrl"
          target="_blank"
          rel="noopener"
        />
      </template>
    </PageHeader>

    <div class="manual-frame">
      <iframe
        :src="manualUrl"
        class="manual-frame__iframe"
        title="Manual interactivo del sistema"
        loading="lazy"
      />
    </div>
  </q-page>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';

// El manual es un HTML autónomo servido como asset estático (public/manual/).
// Quasar lo publica en la raíz del despliegue; se respeta el base path del build.
const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');
const manualUrl = `${base}/manual/manual-interactivo.html`;
</script>

<style scoped lang="scss">
.manual-page {
  display: flex;
  flex-direction: column;
}

.manual-frame {
  flex: 1;
  min-height: 0;
  margin-top: 12px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  overflow: hidden;
  background: var(--app-surface);
}

.manual-frame__iframe {
  width: 100%;
  height: 100%;
  min-height: 70vh;
  border: 0;
  display: block;
}
</style>
