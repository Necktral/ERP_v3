<template>
  <q-page class="app-page">
    <PageHeader
      title="Aprobaciones de crédito"
      subtitle="Bandeja del aprobador (checker): pedidos sometidos a crédito pendientes de resolver. Por SoD no podés resolver solicitudes que vos mismo sometiste."
      :loading="loading"
      @refresh="recargarTodo"
    >
      <template #actions>
        <q-btn flat no-caps icon="assignment" label="Pedidos" to="/facturacion/pedidos" />
      </template>
    </PageHeader>

    <q-banner
      v-if="!bitacoraDisponible && hayPedidosSinSolicitud"
      dense
      rounded
      class="bg-warning text-dark q-mb-md"
    >
      No se pudo detectar el número de solicitud de algunos pedidos: al resolver, ingresá el
      número manualmente (el maker lo ve al someter).
    </q-banner>

    <q-table
      v-model:pagination="pagination"
      class="app-table"
      :rows="rows"
      :columns="columns"
      row-key="id"
      flat
      :loading="loading"
      :rows-per-page-options="[10, 25, 50, 100]"
      no-data-label="No hay solicitudes de crédito pendientes."
      @request="onRequest"
    >
      <template #body-cell-solicitud="props">
        <q-td :props="props">
          {{ aprobacionDe(props.row) != null ? `#${aprobacionDe(props.row)}` : '—' }}
        </q-td>
      </template>
      <template #body-cell-cliente="props">
        <q-td :props="props">{{ props.row.customer_name || '—' }}</q-td>
      </template>
      <template #body-cell-total="props">
        <q-td :props="props">{{ formatMoney(props.row.total) }}</q-td>
      </template>
      <template #body-cell-created_at="props">
        <q-td :props="props">{{ formatDate(props.row.created_at) }}</q-td>
      </template>
      <template #body-cell-credito="props">
        <q-td :props="props">
          <EstadoChip :estado="props.row.credit_status" :map="MAPA_CREDITO" />
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props">
          <q-btn
            v-if="puede('billing.order.approve')"
            dense
            flat
            no-caps
            color="positive"
            icon="check_circle"
            label="Aprobar"
            @click="abrirResolver(props.row, true)"
          />
          <q-btn
            v-if="puede('billing.order.approve')"
            dense
            flat
            no-caps
            color="negative"
            icon="cancel"
            label="Rechazar"
            @click="abrirResolver(props.row, false)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Diálogo: resolver solicitud de crédito (checker) -->
    <q-dialog v-model="dlgResolver">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">
          {{ aprobar ? 'Aprobar crédito' : 'Rechazar crédito' }}
        </q-card-section>
        <q-card-section v-if="pedidoResolver" class="app-form">
          <div>
            Pedido #{{ pedidoResolver.id }} — {{ pedidoResolver.customer_name || 'sin cliente' }} —
            <b>{{ formatMoney(pedidoResolver.total) }}</b>
          </div>
          <q-input
            v-if="approvalIdAuto == null"
            v-model.number="approvalIdManual"
            outlined
            dense
            type="number"
            min="1"
            label="N° de solicitud de crédito *"
            hint="El backend no lista solicitudes: usá el número que vio el maker al someter."
          />
          <div v-else class="text-caption text-muted">
            Solicitud de crédito #{{ approvalIdAuto }} (detectada en la bitácora).
          </div>
          <template v-if="aprobar">
            <q-input
              v-model="montoAprobado"
              outlined
              dense
              type="number"
              min="0"
              label="Monto aprobado (vacío = monto solicitado)"
            />
            <q-input
              v-model.number="plazoDias"
              outlined
              dense
              type="number"
              min="0"
              max="365"
              label="Plazo en días (opcional)"
            />
          </template>
          <q-input v-model="notasResolucion" outlined dense autogrow label="Notas de resolución" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            :color="aprobar ? 'positive' : 'negative'"
            :label="aprobar ? 'Aprobar' : 'Rechazar'"
            :loading="resolviendo"
            :disable="approvalIdElegido == null"
            @click="resolver"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import EstadoChip, { type EstadoEstilo } from 'src/components/EstadoChip.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { formatDate, formatMoney } from 'src/core/format';
import { listBitacora } from 'src/modules/audit/api';
import {
  CREDIT_STATUS_LABELS,
  listSalesOrdersPage,
  resolveCreditApproval,
  type SalesOrderRow,
} from 'src/modules/billing/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const MAPA_CREDITO: Record<string, EstadoEstilo> = Object.fromEntries(
  Object.entries(CREDIT_STATUS_LABELS).map(([code, label]) => [
    code,
    {
      label,
      color: code === 'APPROVED' ? 'positive' : code === 'REJECTED' ? 'negative' : 'warning',
      outline: true,
    },
  ]),
);

const { rows, loading, pagination, onRequest, reload } = useListadoServer<SalesOrderRow>(
  (page) => listSalesOrdersPage({ status: 'PENDING_APPROVAL' }, page),
  { errorMessage: 'No se pudieron cargar las solicitudes pendientes.' },
);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const columns: QTableColumn<SalesOrderRow>[] = [
  { name: 'id', label: 'Pedido', field: 'id', align: 'left' },
  { name: 'solicitud', label: 'Solicitud', field: 'id', align: 'left' },
  { name: 'cliente', label: 'Cliente', field: 'customer_name', align: 'left' },
  { name: 'total', label: 'Monto solicitado', field: 'total', align: 'right' },
  { name: 'created_at', label: 'Creado', field: 'created_at', align: 'left' },
  { name: 'credito', label: 'Crédito', field: 'credit_status', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

// --- Mapeo pedido → solicitud de crédito vía bitácora de auditoría ---
// El backend NO expone GET de credit-approvals ni incluye approval_id en el
// payload del pedido; la solicitud se recupera del evento BILLING_CREDIT_REQUESTED
// (subject_id = approval_id, metadata.order_id = pedido). Si el usuario no tiene
// audit.read, se degrada a ingreso manual del número de solicitud.
const aprobacionPorPedido = ref<Map<number, number>>(new Map());
const bitacoraDisponible = ref(true);

function aprobacionDe(row: SalesOrderRow): number | null {
  // Primero lo que manda el backend (pending_approval_id en el payload del
  // pedido); la bitácora queda como fallback para payloads viejos.
  return row.pending_approval_id ?? aprobacionPorPedido.value.get(row.id) ?? null;
}

const hayPedidosSinSolicitud = computed(() => rows.value.some((r) => aprobacionDe(r) === null));

async function cargarMapaAprobaciones() {
  const mapa = new Map<number, number>();
  try {
    let cursor: string | undefined;
    // Los eventos vienen del más reciente al más viejo: la primera aparición de
    // un pedido es su solicitud vigente. Tope de páginas para no paginar infinito.
    for (let pagina = 0; pagina < 5; pagina++) {
      const res = await listBitacora(
        { module: 'BILLING', event_type: 'BILLING_CREDIT_REQUESTED', subject_type: 'CREDIT_APPROVAL' },
        cursor,
      );
      for (const ev of res.results) {
        const approvalId = Number(ev.subject_id);
        const meta = ev.metadata as Record<string, unknown> | null | undefined;
        const orderId = Number(meta?.order_id);
        if (Number.isFinite(orderId) && Number.isFinite(approvalId) && !mapa.has(orderId)) {
          mapa.set(orderId, approvalId);
        }
      }
      const next = res.next;
      if (!next) break;
      // El backend devuelve la URL completa: extraer solo el cursor.
      cursor = new URL(next, window.location.origin).searchParams.get('cursor') ?? undefined;
      if (!cursor) break;
    }
    bitacoraDisponible.value = true;
  } catch {
    // Sin permiso audit.read (u otra falla): la página sigue sirviendo con
    // ingreso manual del número de solicitud.
    bitacoraDisponible.value = false;
  }
  aprobacionPorPedido.value = mapa;
}

void cargarMapaAprobaciones();

async function recargarTodo() {
  await Promise.all([reload(), cargarMapaAprobaciones()]);
}

// --- Resolver (checker, SoD) ---
const dlgResolver = ref(false);
const resolviendo = ref(false);
const pedidoResolver = ref<SalesOrderRow | null>(null);
const aprobar = ref(true);
const approvalIdAuto = ref<number | null>(null);
const approvalIdManual = ref<number | null>(null);
const montoAprobado = ref('');
const plazoDias = ref<number | null>(null);
const notasResolucion = ref('');

const approvalIdElegido = computed<number | null>(() => {
  if (approvalIdAuto.value != null) return approvalIdAuto.value;
  return approvalIdManual.value != null && approvalIdManual.value > 0 ? approvalIdManual.value : null;
});

function abrirResolver(row: SalesOrderRow, aprobado: boolean) {
  pedidoResolver.value = row;
  aprobar.value = aprobado;
  approvalIdAuto.value = aprobacionDe(row);
  approvalIdManual.value = null;
  montoAprobado.value = '';
  plazoDias.value = null;
  notasResolucion.value = '';
  dlgResolver.value = true;
}

async function resolver() {
  const approvalId = approvalIdElegido.value;
  if (approvalId == null) return;
  resolviendo.value = true;
  try {
    const out = await resolveCreditApproval(approvalId, {
      approved: aprobar.value,
      ...(notasResolucion.value.trim() ? { resolution_notes: notasResolucion.value.trim() } : {}),
      ...(aprobar.value && montoAprobado.value !== '' ? { approved_amount: String(montoAprobado.value) } : {}),
      ...(aprobar.value && plazoDias.value != null ? { approved_terms_days: plazoDias.value } : {}),
    });
    dlgResolver.value = false;
    $q.notify({
      type: 'positive',
      message: aprobar.value
        ? `Crédito aprobado (solicitud #${out.approval_id}).`
        : `Crédito rechazado (solicitud #${out.approval_id}).`,
    });
    await recargarTodo();
  } catch (e) {
    // 409 = violación SoD (mismo usuario que sometió); el backend manda el detalle.
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo resolver la solicitud.') });
  } finally {
    resolviendo.value = false;
  }
}
</script>
