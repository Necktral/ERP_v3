<template>
  <q-page class="app-page">
    <PageHeader
      title="Intercompañía"
      subtitle="Cruces entre tus empresas (cada una con su RUC): creada → confirmada → conciliada → liquidada → cerrada."
      :loading="loading"
      @refresh="reload"
    >
      <template #actions>
        <q-btn
          v-if="puede('accounting.intercompany.write')"
          unelevated
          no-caps
          color="primary"
          icon="add"
          label="Nuevo cruce"
          @click="abrirCrear"
        />
      </template>
    </PageHeader>

    <q-table
      class="app-table"
      :rows="rows"
      :columns="columns"
      row-key="id"
      flat
      :loading="loading"
      :pagination="{ rowsPerPage: 25 }"
      no-data-label="Sin transacciones intercompañía."
    >
      <template #body-cell-monto="props">
        <q-td :props="props">{{ formatMoney(props.row.amount) }}</q-td>
      </template>
      <template #body-cell-estado="props">
        <q-td :props="props">{{ IC_STATUS_LABELS[props.row.status] ?? props.row.status }}</q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props" class="text-right ic-acciones">
          <q-btn
            v-if="puede('accounting.intercompany.write') && props.row.status === 'CREATED'"
            flat
            dense
            no-caps
            size="sm"
            label="Confirmar"
            @click="accion(props.row, 'confirm')"
          />
          <q-btn
            v-if="puede('accounting.intercompany.reconcile') && props.row.status === 'CONFIRMED'"
            flat
            dense
            no-caps
            size="sm"
            label="Conciliar"
            @click="accion(props.row, 'reconcile')"
          />
          <q-btn
            v-if="puede('accounting.intercompany.settle') && props.row.status === 'RECONCILED'"
            flat
            dense
            no-caps
            size="sm"
            color="primary"
            label="Liquidar"
            @click="accion(props.row, 'settle')"
          />
          <q-btn
            v-if="puede('accounting.intercompany.write') && props.row.status === 'SETTLED'"
            flat
            dense
            no-caps
            size="sm"
            label="Cerrar"
            @click="accion(props.row, 'close')"
          />
          <q-btn
            v-if="puede('accounting.intercompany.dispute') && ['CONFIRMED', 'RECONCILED'].includes(props.row.status)"
            flat
            dense
            no-caps
            size="sm"
            color="negative"
            label="Disputar"
            @click="disputar(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <div class="ic-disputas">
      <div class="ic-disputas__title">Disputas intercompañía</div>
      <q-table
        class="app-table"
        :rows="disputas"
        :columns="colsDisputa"
        row-key="case_id"
        flat
        :loading="cargandoDisputas"
        :pagination="{ rowsPerPage: 10 }"
        no-data-label="Sin disputas registradas."
      >
        <template #body-cell-estado="props">
          <q-td :props="props">{{ DISPUTE_STATUS_LABELS[props.row.status] ?? props.row.status }}</q-td>
        </template>
        <template #body-cell-acciones="props">
          <q-td :props="props" class="text-right">
            <q-btn
              v-if="puede('accounting.intercompany.dispute') && props.row.status !== 'APPROVED' && props.row.status !== 'REJECTED'"
              flat
              dense
              no-caps
              size="sm"
              color="primary"
              label="Revisar"
              @click="abrirRevision(props.row)"
            />
          </q-td>
        </template>
      </q-table>
    </div>

    <q-dialog v-model="dlgCrear">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Nuevo cruce intercompañía</q-card-section>
        <q-card-section class="app-form">
          <q-select
            v-model="form.target_company_id"
            :options="opcionesEmpresa"
            label="Empresa destino *"
            outlined
            dense
            emit-value
            map-options
          />
          <q-input v-model="form.amount" outlined dense type="number" min="0" label="Monto C$ *" />
          <q-input v-model="form.source_account_code" outlined dense label="Cuenta origen (código) *" />
          <q-input v-model="form.target_account_code" outlined dense label="Cuenta destino (código) *" />
          <q-input v-model="form.description" outlined dense label="Descripción" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear cruce"
            :loading="guardando"
            :disable="form.target_company_id == null || !form.amount || !form.source_account_code || !form.target_account_code"
            @click="crear"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="dlgRevision">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Revisar disputa</q-card-section>
        <q-card-section class="app-form">
          <div class="text-caption text-muted">Caso {{ revision.case_id }} · cruce {{ revision.tx_id }}</div>
          <q-select
            v-model="revision.action"
            :options="opcionesRevision"
            label="Resolución *"
            outlined
            dense
            emit-value
            map-options
          />
          <q-input v-model="revision.note" outlined dense type="textarea" autogrow label="Nota" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Guardar"
            :loading="guardandoRevision"
            @click="guardarRevision"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListado } from 'src/core/composables/useListado';
import { formatMoney } from 'src/core/format';
import {
  createIntercompanyTx,
  disputeIntercompanyTx,
  IC_STATUS_LABELS,
  intercompanyAction,
  listIntercompanyDisputes,
  listIntercompanyTxs,
  reviewIntercompanyDispute,
  type DisputeCase,
  type IntercompanyTx,
} from 'src/modules/accounting/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const { rows, loading, reload } = useListado<IntercompanyTx>(() => listIntercompanyTxs(), {
  errorMessage: 'No se pudieron cargar los cruces.',
});

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const opcionesEmpresa = computed(() =>
  acl.companies
    .filter((c) => String(c.company_id) !== ctx.activeCompanyId)
    .map((c) => ({ value: Number(c.company_id), label: c.company_name })),
);

const columns: QTableColumn<IntercompanyTx>[] = [
  { name: 'id', label: '#', field: 'id', align: 'left' },
  { name: 'descripcion', label: 'Descripción', field: (r) => (r.description as string) || (r.reference_code as string) || '—', align: 'left' },
  { name: 'monto', label: 'Monto', field: 'amount', align: 'right' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

const dlgCrear = ref(false);
const guardando = ref(false);
const form = reactive<{
  target_company_id: number | null;
  amount: string;
  source_account_code: string;
  target_account_code: string;
  description: string;
}>({ target_company_id: null, amount: '', source_account_code: '', target_account_code: '', description: '' });

function abrirCrear() {
  Object.assign(form, {
    target_company_id: null,
    amount: '',
    source_account_code: '',
    target_account_code: '',
    description: '',
  });
  dlgCrear.value = true;
}

async function crear() {
  guardando.value = true;
  try {
    await createIntercompanyTx({
      target_company_id: form.target_company_id!,
      amount: Number(form.amount).toFixed(2),
      source_account_code: form.source_account_code.trim(),
      target_account_code: form.target_account_code.trim(),
      ...(form.description ? { description: form.description } : {}),
    });
    dlgCrear.value = false;
    $q.notify({ type: 'positive', message: 'Cruce creado.' });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear el cruce.') });
  } finally {
    guardando.value = false;
  }
}

async function accion(tx: IntercompanyTx, a: 'confirm' | 'reconcile' | 'settle' | 'close') {
  try {
    await intercompanyAction(tx.id, a);
    $q.notify({ type: 'positive', message: 'Listo.' });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo ejecutar la acción.') });
  }
}

// --- Bandeja de disputas (cierra #4) ---
const DISPUTE_STATUS_LABELS: Record<string, string> = {
  OPEN: 'Abierta',
  UNDER_REVIEW: 'En revisión',
  APPROVED: 'Aprobada',
  REJECTED: 'Rechazada',
  CANCELLED: 'Cancelada',
};
const opcionesRevision = [
  { value: 'UNDER_REVIEW', label: 'En revisión' },
  { value: 'APPROVED', label: 'Aprobar' },
  { value: 'REJECTED', label: 'Rechazar' },
  { value: 'CANCELLED', label: 'Cancelar' },
];
const colsDisputa: QTableColumn<DisputeCase>[] = [
  { name: 'case_id', label: 'Caso', field: 'case_id', align: 'left' },
  { name: 'tx_id', label: 'Cruce', field: 'tx_id', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'motivo', label: 'Motivo', field: 'reason_code', align: 'left' },
  { name: 'resumen', label: 'Resumen', field: 'summary', align: 'left' },
  { name: 'acciones', label: '', field: 'case_id', align: 'right' },
];
const disputas = ref<DisputeCase[]>([]);
const cargandoDisputas = ref(false);
const dlgRevision = ref(false);
const guardandoRevision = ref(false);
const revision = reactive<{
  case_id: string;
  tx_id: string;
  action: 'UNDER_REVIEW' | 'APPROVED' | 'REJECTED' | 'CANCELLED';
  note: string;
}>({ case_id: '', tx_id: '', action: 'UNDER_REVIEW', note: '' });

async function cargarDisputas() {
  if (!puede('accounting.intercompany.read')) return;
  cargandoDisputas.value = true;
  try {
    disputas.value = await listIntercompanyDisputes();
  } catch {
    disputas.value = [];
  } finally {
    cargandoDisputas.value = false;
  }
}

function abrirRevision(c: DisputeCase) {
  revision.case_id = c.case_id;
  revision.tx_id = c.tx_id;
  revision.action = 'UNDER_REVIEW';
  revision.note = '';
  dlgRevision.value = true;
}

async function guardarRevision() {
  guardandoRevision.value = true;
  try {
    await reviewIntercompanyDispute(revision.case_id, revision.action, revision.note.trim());
    dlgRevision.value = false;
    $q.notify({ type: 'positive', message: 'Disputa actualizada.' });
    await cargarDisputas();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo actualizar la disputa.') });
  } finally {
    guardandoRevision.value = false;
  }
}

onMounted(cargarDisputas);

function disputar(tx: IntercompanyTx) {
  $q.dialog({
    title: `Disputar cruce #${tx.id}`,
    message: 'Motivo de la disputa:',
    prompt: { model: '', type: 'text', isValid: (v: string) => v.trim().length >= 5 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'negative', label: 'Disputar' },
    persistent: true,
  }).onOk((motivo: string) => {
    void (async () => {
      try {
        await disputeIntercompanyTx(tx.id, motivo.trim());
        $q.notify({ type: 'warning', message: 'Cruce en disputa.' });
        await reload();
        await cargarDisputas();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo disputar.') });
      }
    })();
  });
}
</script>

<style scoped>
.ic-acciones {
  white-space: nowrap;
}

.ic-disputas {
  margin-top: var(--app-space-6);
}

.ic-disputas__title {
  font-family: 'Manrope', 'IBM Plex Sans', sans-serif;
  font-weight: 800;
  color: var(--app-text);
  margin-bottom: var(--app-space-3);
}
</style>
