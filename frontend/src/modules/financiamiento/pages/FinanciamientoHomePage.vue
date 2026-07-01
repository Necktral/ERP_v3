<template>
  <q-page class="app-page-container">
    <PageHeader
      title="Acopio y Financiamiento"
      subtitle="Café en custodia y préstamos a productores (US$/C$). Productores, recibos, fijación de precio y liquidación."
      hide-refresh
    />

    <div class="fin-grid">
      <q-card
        v-for="c in cards"
        :key="c.to"
        flat
        bordered
        clickable
        class="fin-card"
        @click="$router.push(c.to)"
      >
        <q-card-section class="fin-card__head">
          <q-icon :name="c.icon" size="26px" class="fin-card__icon" />
          <div class="fin-card__title">{{ c.title }}</div>
        </q-card-section>
        <q-card-section class="fin-card__desc">{{ c.desc }}</q-card-section>
      </q-card>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';

const cards = [
  {
    to: '/financiamiento/productores',
    icon: 'badge',
    title: 'Productores',
    desc: 'Ficha de cada productor (carnet de acopio), certificaciones y depósito de café.',
  },
  {
    to: '/financiamiento/acopio',
    icon: 'scale',
    title: 'Recibos de café',
    desc: 'Recepción en custodia: sacos, peso bruto/tara → neto en quintales. Pensado para la báscula.',
  },
  {
    to: '/financiamiento/prestamos',
    icon: 'request_quote',
    title: 'Préstamos',
    desc: 'Solicitud → aprobación → desembolso, estado de cuenta y registro de pagos.',
  },
  {
    to: '/financiamiento/liquidaciones',
    icon: 'receipt_long',
    title: 'Fijación y liquidación',
    desc: 'Fijar precio del quintal y liquidar entregas (aplica a préstamo, retenciones).',
  },
];
</script>

<style scoped>
.fin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--app-space-4);
}
.fin-card {
  border-radius: var(--app-radius-md);
  border-color: var(--app-border);
  background: var(--app-surface-strong);
  box-shadow: var(--app-shadow-soft);
  transition: box-shadow 0.15s ease;
}
.fin-card:hover {
  box-shadow: var(--app-shadow-card);
}
.fin-card__head {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  padding-bottom: var(--app-space-2);
}
.fin-card__icon {
  color: var(--app-primary);
}
.fin-card__title {
  font-family: 'Manrope', 'IBM Plex Sans', sans-serif;
  font-weight: 700;
  font-size: 1.05rem;
  color: var(--app-text);
}
.fin-card__desc {
  color: var(--app-text-muted);
  font-size: 0.85rem;
  padding-top: 0;
}
</style>
