<template>
  <q-page class="app-page">
    <PageHeader
      title="Tickets del POS"
      subtitle="Histórico de tickets: estado del cobro y compensaciones pendientes (cuando una venta quedó a medio camino)."
      :loading="loading"
      @refresh="reload"
    >
      <template #actions>
        <BackButton to="/pos" />
      </template>
    </PageHeader>

    <q-table
      v-model:pagination="pagination"
      class="app-table"
      :rows="rows"
      :columns="columns"
      row-key="id"
      flat
      :loading="loading"
      :rows-per-page-options="[10, 25, 50, 100]"
      no-data-label="Aún no hay tickets."
      @request="onRequest"
    >
      <template #body-cell-estado="props">
        <q-td :props="props">
          {{ POS_TICKET_STATUS_LABELS[props.row.status] ?? props.row.status }}
          <q-chip
            v-if="props.row.compensation_pending"
            dense
            outline
            color="warning"
            label="Compensación pendiente"
          />
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props" class="text-right">
          <q-btn
            v-if="puedeCheckout && props.row.compensation_pending"
            flat
            dense
            no-caps
            size="sm"
            color="warning"
            icon="refresh"
            label="Reintentar compensación"
            @click="reintentar(props.row)"
          />
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup lang="ts">
import BackButton from 'src/components/BackButton.vue';
import { computed } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { FUEL_PAYMENT_LABELS, FUEL_SALE_TYPE_LABELS } from 'src/modules/fuel/api';
import {
  listPosTicketsPage,
  POS_TICKET_STATUS_LABELS,
  retryPosCompensation,
  type PosTicket,
} from 'src/modules/pos/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

// Paginación server-side: el histórico de tickets crece sin límite (antes truncaba a 200).
const { rows, loading, pagination, onRequest, reload } = useListadoServer<PosTicket>(
  (page) => listPosTicketsPage(page),
  { errorMessage: 'No se pudieron cargar los tickets.' },
);

const puedeCheckout = computed(() => {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, 'retail.pos.ticket.checkout') : false;
});

const columns: QTableColumn<PosTicket>[] = [
  { name: 'id', label: '#', field: 'id', align: 'left' },
  {
    name: 'tipo',
    label: 'Tipo',
    field: (r) => FUEL_SALE_TYPE_LABELS[r.sale_type] ?? r.sale_type,
    align: 'left',
  },
  {
    name: 'pago',
    label: 'Pago',
    field: (r) => FUEL_PAYMENT_LABELS[r.payment_method] ?? r.payment_method,
    align: 'left',
  },
  { name: 'cliente', label: 'Cliente', field: 'customer_name', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

async function reintentar(t: PosTicket) {
  try {
    await retryPosCompensation(t.id);
    $q.notify({ type: 'positive', message: 'Reintento encolado.' });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo reintentar.') });
  }
}
</script>
