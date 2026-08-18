<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton to="/financiamiento" />
    </div>
    <PageHeader
      title="Préstamos a productores"
      subtitle="Solicitud → aprobación → desembolso. Estado de cuenta por moneda (C$/US$) y registro de pagos."
      :loading="loadingApps || loadingLoans"
      @refresh="reloadAll"
    />

    <q-tabs v-model="tab" align="left" dense class="text-primary q-mb-md" narrow-indicator>
      <q-tab name="solicitudes" no-caps label="Solicitudes" />
      <q-tab name="prestamos" no-caps label="Préstamos" />
    </q-tabs>

    <!-- ===== SOLICITUDES ===== -->
    <div v-if="tab === 'solicitudes'">
      <div class="q-mb-md">
        <q-btn unelevated no-caps color="primary" icon="add" label="Nueva solicitud" @click="abrirAlta" />
      </div>
      <q-table
        :rows="apps"
        :columns="appCols"
        row-key="id"
        flat
        bordered
        :loading="loadingApps"
        v-model:pagination="appsPagination"
        @request="appsRequest"
        no-data-label="Sin solicitudes."
      >
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-chip dense square :color="appColor(props.row.status)" text-color="white" :label="APPLICATION_STATUS_LABELS[props.row.status]" />
          </q-td>
        </template>
        <template #body-cell-acciones="props">
          <q-td :props="props" class="q-gutter-xs">
            <q-btn v-if="props.row.status === 'DRAFT'" dense flat no-caps size="sm" color="primary" label="Presentar" @click="accion(submitApplication, props.row.id)" />
            <q-btn v-if="props.row.status === 'SUBMITTED'" dense flat no-caps size="sm" color="positive" label="Aprobar" @click="accion(approveApplication, props.row.id)" />
            <q-btn v-if="props.row.status === 'SUBMITTED'" dense flat no-caps size="sm" color="negative" label="Rechazar" @click="abrirRechazo(props.row.id)" />
            <q-btn v-if="props.row.status === 'APPROVED'" dense unelevated no-caps size="sm" color="primary" label="Desembolsar" @click="abrirDesembolso(props.row.id)" />
          </q-td>
        </template>
      </q-table>
    </div>

    <!-- ===== PRÉSTAMOS ===== -->
    <div v-else>
      <q-table
        :rows="loans"
        :columns="loanCols"
        row-key="id"
        flat
        bordered
        :loading="loadingLoans"
        v-model:pagination="loansPagination"
        @request="loansRequest"
        no-data-label="Sin préstamos."
      >
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-chip dense square :color="loanColor(props.row.status)" text-color="white" :label="LOAN_STATUS_LABELS[props.row.status]" />
          </q-td>
        </template>
        <template #body-cell-acciones="props">
          <q-td :props="props" class="q-gutter-xs">
            <q-btn dense flat no-caps size="sm" icon="description" label="Estado" @click="verEstado(props.row)" />
            <q-btn v-if="props.row.status === 'ACTIVE'" dense unelevated no-caps size="sm" color="primary" icon="payments" label="Pago" @click="abrirPago(props.row)" />
          </q-td>
        </template>
      </q-table>
    </div>

    <!-- Alta solicitud -->
    <q-dialog v-model="altaOpen">
      <q-card class="app-dialog" style="min-width: 420px">
        <q-card-section class="text-h6">Nueva solicitud de financiamiento</q-card-section>
        <q-card-section class="q-gutter-md">
          <q-select v-model="fApp.producer_id" :options="prodOpts" label="Productor *" outlined dense emit-value map-options options-dense />
          <div class="row q-col-gutter-md">
            <q-input class="col" v-model.number="fApp.requested_nio" type="number" label="Monto C$" outlined dense />
            <q-input class="col" v-model.number="fApp.requested_usd" type="number" label="Monto US$" outlined dense />
          </div>
          <div class="row q-col-gutter-md">
            <q-input class="col" v-model.number="fApp.term_months" type="number" min="1" label="Plazo (meses) *" outlined dense />
            <q-input class="col" v-model.number="fApp.interest_rate" type="number" step="0.0001" label="Interés (ej. 0.18) *" outlined dense />
          </div>
          <q-select v-model="fApp.disbursement_form" :options="formaOpts" label="Forma de desembolso" outlined dense emit-value map-options options-dense />
          <q-input v-model="fApp.activity" label="Actividad / destino" outlined dense />
          <q-input v-model.number="fApp.guarantee_coffee_qq" type="number" label="Garantía: café (qq)" outlined dense />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Crear" :loading="guardando" :disable="!appValida" @click="guardarApp" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Rechazo -->
    <q-dialog v-model="rechazoOpen">
      <q-card class="app-dialog" style="min-width: 360px">
        <q-card-section class="text-h6">Rechazar solicitud</q-card-section>
        <q-card-section><q-input v-model="rechazoMotivo" type="textarea" autogrow outlined label="Motivo" /></q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="negative" label="Rechazar" :loading="guardando" @click="confirmarRechazo" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Desembolso -->
    <q-dialog v-model="desembOpen">
      <q-card class="app-dialog" style="min-width: 360px">
        <q-card-section class="text-h6">Desembolsar</q-card-section>
        <q-card-section class="q-gutter-md">
          <q-input v-model="fDesemb.disbursement_date" type="date" outlined dense label="Fecha" />
          <q-input v-model="fDesemb.reference" outlined dense label="Referencia (cheque / transf.)" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Desembolsar" :loading="guardando" @click="confirmarDesembolso" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Estado de cuenta -->
    <q-dialog v-model="estadoOpen">
      <q-card class="app-dialog" style="min-width: 420px">
        <q-card-section class="text-h6">Estado de cuenta · {{ estado?.reference }}</q-card-section>
        <q-card-section v-if="estado">
          <div class="text-caption text-muted q-mb-sm">{{ estado.producer }} · vence {{ estado.maturity_date }}</div>
          <div v-for="(bal, ccy) in estado.balances" :key="ccy" class="est-ccy">
            <div class="est-ccy__title">{{ ccy }}</div>
            <div class="dep-row"><span>Principal</span><b>{{ bal.principal }}</b></div>
            <div class="dep-row"><span>Interés</span><b>{{ bal.interest }}</b></div>
            <div class="dep-row"><span>Comisión / mora</span><b>{{ bal.fee }} / {{ bal.penalty }}</b></div>
            <div class="dep-row"><span>Abonado</span><b>{{ bal.allocated }}</b></div>
            <div class="dep-row dep-row--hi"><span>Saldo</span><b>{{ bal.outstanding }}</b><q-chip v-if="bal.days_overdue > 0" dense square color="negative" text-color="white" size="sm" :label="bal.days_overdue + ' d mora'" /></div>
          </div>
          <q-separator class="q-my-sm" v-if="estado.consolidated_nio" />
          <div v-if="estado.consolidated_nio" class="dep-row dep-row--hi">
            <span>Consolidado C$ (tasa {{ estado.rate_used }})</span><b>{{ estado.consolidated_nio }}</b>
          </div>
        </q-card-section>
        <q-card-section v-else class="text-muted">Cargando…</q-card-section>
        <q-card-actions align="right"><q-btn flat no-caps label="Cerrar" v-close-popup /></q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Pago -->
    <q-dialog v-model="pagoOpen">
      <q-card class="app-dialog" style="min-width: 380px">
        <q-card-section class="text-h6">Registrar pago · {{ pagoLoan?.reference }}</q-card-section>
        <q-card-section class="q-gutter-md">
          <q-input v-model.number="fPago.amount" type="number" label="Monto *" outlined dense />
          <q-select v-model="fPago.paid_currency" :options="monedaOpts" label="Moneda pagada *" outlined dense emit-value map-options options-dense />
          <q-select v-model="fPago.target_currency" :options="monedaTargetOpts" label="Aplicar a saldo en" outlined dense emit-value map-options options-dense />
          <q-input v-model.number="fPago.exchange_rate" type="number" step="0.0001" label="Tasa (si cruza moneda)" outlined dense />
          <q-input v-model="fPago.payment_date" type="date" outlined dense label="Fecha" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Registrar" :loading="guardando" :disable="!fPago.amount || !fPago.paid_currency" @click="confirmarPago" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { apiErrorMessage } from 'src/core/api';
import {
  APPLICATION_STATUS_LABELS,
  CURRENCY_LABELS,
  DISBURSEMENT_LABELS,
  LOAN_STATUS_LABELS,
  approveApplication,
  createApplication,
  disburseApplication,
  listApplicationsPage,
  listLoansPage,
  listProducers,
  loanStatement,
  registerLoanPayment,
  rejectApplication,
  submitApplication,
  type ApplicationRow,
  type ApplicationStatus,
  type Currency,
  type DisbursementForm,
  type LoanRow,
  type LoanStatement,
  type LoanStatus,
} from 'src/modules/financiamiento/api';

const $q = useQuasar();
const tab = ref<'solicitudes' | 'prestamos'>('solicitudes');
const appsListado = useListadoServer<ApplicationRow>(listApplicationsPage, { rowsPerPage: 15 });
const loansListado = useListadoServer<LoanRow>(listLoansPage, { rowsPerPage: 15 });
const { rows: apps, loading: loadingApps, pagination: appsPagination, onRequest: appsRequest, reload: reloadApps } = appsListado;
const { rows: loans, loading: loadingLoans, pagination: loansPagination, onRequest: loansRequest, reload: reloadLoans } = loansListado;

function reloadAll() {
  void reloadApps();
  void reloadLoans();
}

interface Opt<T = number> {
  label: string;
  value: T;
}
const prodOpts = ref<Opt[]>([]);
const formaOpts = (Object.keys(DISBURSEMENT_LABELS) as DisbursementForm[]).map((k) => ({ label: DISBURSEMENT_LABELS[k], value: k }));
const monedaOpts = (Object.keys(CURRENCY_LABELS) as Currency[]).map((k) => ({ label: CURRENCY_LABELS[k] ?? k, value: k }));
const monedaTargetOpts: Opt<Currency | ''>[] = [{ label: '(misma)', value: '' }, ...monedaOpts];

function appColor(s: ApplicationStatus): string {
  return { DRAFT: 'grey', SUBMITTED: 'info', APPROVED: 'positive', REJECTED: 'negative', DISBURSED: 'primary' }[s];
}
function loanColor(s: LoanStatus): string {
  return { ACTIVE: 'primary', PAID: 'positive', CANCELLED: 'grey' }[s];
}

const appCols: QTableColumn<ApplicationRow>[] = [
  { name: 'producer_name', label: 'Productor', field: 'producer_name', align: 'left', sortable: true },
  { name: 'requested_nio', label: 'C$', field: 'requested_nio', align: 'right' },
  { name: 'requested_usd', label: 'US$', field: 'requested_usd', align: 'right' },
  { name: 'term_months', label: 'Plazo', field: 'term_months', align: 'right' },
  { name: 'status', label: 'Estado', field: 'status', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];
const loanCols: QTableColumn<LoanRow>[] = [
  { name: 'reference', label: 'Referencia', field: 'reference', align: 'left', sortable: true },
  { name: 'producer_name', label: 'Productor', field: 'producer_name', align: 'left', sortable: true },
  { name: 'maturity_date', label: 'Vence', field: 'maturity_date', align: 'left', sortable: true },
  { name: 'disbursement_form', label: 'Forma', field: (r) => DISBURSEMENT_LABELS[r.disbursement_form], align: 'left' },
  { name: 'status', label: 'Estado', field: 'status', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

const guardando = ref(false);

// ---- alta solicitud ----
const altaOpen = ref(false);
const fApp = ref<{
  producer_id: number | null;
  requested_nio: number;
  requested_usd: number;
  term_months: number;
  interest_rate: number;
  disbursement_form: DisbursementForm;
  activity: string;
  guarantee_coffee_qq: number;
}>({
  producer_id: null,
  requested_nio: 0,
  requested_usd: 0,
  term_months: 12,
  interest_rate: 0.18,
  disbursement_form: 'CASH',
  activity: '',
  guarantee_coffee_qq: 0,
});
const appValida = computed(
  () => !!fApp.value.producer_id && fApp.value.term_months >= 1 && fApp.value.interest_rate > 0 && (fApp.value.requested_nio > 0 || fApp.value.requested_usd > 0),
);
function abrirAlta() {
  fApp.value = { producer_id: null, requested_nio: 0, requested_usd: 0, term_months: 12, interest_rate: 0.18, disbursement_form: 'CASH', activity: '', guarantee_coffee_qq: 0 };
  altaOpen.value = true;
}
async function guardarApp() {
  if (!appValida.value || !fApp.value.producer_id) return;
  guardando.value = true;
  try {
    await createApplication({
      producer_id: fApp.value.producer_id,
      requested_nio: fApp.value.requested_nio,
      requested_usd: fApp.value.requested_usd,
      term_months: fApp.value.term_months,
      interest_rate: fApp.value.interest_rate,
      disbursement_form: fApp.value.disbursement_form,
      activity: fApp.value.activity,
      guarantee_coffee_qq: fApp.value.guarantee_coffee_qq,
    });
    $q.notify({ type: 'positive', message: 'Solicitud creada.' });
    altaOpen.value = false;
    await reloadApps();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear la solicitud.') });
  } finally {
    guardando.value = false;
  }
}

// ---- acciones simples (submit/approve) ----
async function accion(fn: (id: number) => Promise<unknown>, id: number) {
  guardando.value = true;
  try {
    await fn(id);
    await reloadApps();
    await reloadLoans();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo completar la acción.') });
  } finally {
    guardando.value = false;
  }
}

// ---- rechazo ----
const rechazoOpen = ref(false);
const rechazoId = ref<number | null>(null);
const rechazoMotivo = ref('');
function abrirRechazo(id: number) {
  rechazoId.value = id;
  rechazoMotivo.value = '';
  rechazoOpen.value = true;
}
async function confirmarRechazo() {
  if (rechazoId.value == null) return;
  guardando.value = true;
  try {
    await rejectApplication(rechazoId.value, rechazoMotivo.value);
    rechazoOpen.value = false;
    await reloadApps();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo rechazar.') });
  } finally {
    guardando.value = false;
  }
}

// ---- desembolso ----
const desembOpen = ref(false);
const desembId = ref<number | null>(null);
const fDesemb = ref({ disbursement_date: '', reference: '' });
function abrirDesembolso(id: number) {
  desembId.value = id;
  fDesemb.value = { disbursement_date: '', reference: '' };
  desembOpen.value = true;
}
async function confirmarDesembolso() {
  if (desembId.value == null) return;
  guardando.value = true;
  try {
    const body: { disbursement_date?: string; reference?: string } = { reference: fDesemb.value.reference };
    if (fDesemb.value.disbursement_date) body.disbursement_date = fDesemb.value.disbursement_date;
    await disburseApplication(desembId.value, body);
    $q.notify({ type: 'positive', message: 'Préstamo desembolsado.' });
    desembOpen.value = false;
    reloadAll();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo desembolsar.') });
  } finally {
    guardando.value = false;
  }
}

// ---- estado de cuenta ----
const estadoOpen = ref(false);
const estado = ref<LoanStatement | null>(null);
async function verEstado(loan: LoanRow) {
  estado.value = null;
  estadoOpen.value = true;
  try {
    estado.value = await loanStatement(loan.id);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el estado.') });
  }
}

// ---- pago ----
const pagoOpen = ref(false);
const pagoLoan = ref<LoanRow | null>(null);
const fPago = ref<{
  amount: number;
  paid_currency: Currency;
  target_currency: Currency | '';
  exchange_rate: number | null;
  payment_date: string;
}>({ amount: 0, paid_currency: 'NIO', target_currency: '', exchange_rate: null, payment_date: '' });
function abrirPago(loan: LoanRow) {
  pagoLoan.value = loan;
  fPago.value = { amount: 0, paid_currency: 'NIO', target_currency: '', exchange_rate: null, payment_date: '' };
  pagoOpen.value = true;
}
async function confirmarPago() {
  if (!pagoLoan.value || !fPago.value.amount) return;
  guardando.value = true;
  try {
    await registerLoanPayment(pagoLoan.value.id, {
      amount: fPago.value.amount,
      paid_currency: fPago.value.paid_currency,
      target_currency: fPago.value.target_currency,
      exchange_rate: fPago.value.exchange_rate,
      payment_date: fPago.value.payment_date || null,
    });
    $q.notify({ type: 'positive', message: 'Pago registrado.' });
    pagoOpen.value = false;
    reloadAll();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo registrar el pago.') });
  } finally {
    guardando.value = false;
  }
}

onMounted(async () => {
  try {
    const prods = await listProducers();
    prodOpts.value = prods.map((p) => ({ label: `${p.acopio_code ? p.acopio_code + ' · ' : ''}${p.party_name}`, value: p.id }));
  } catch {
    /* noop */
  }
});
</script>

<style scoped>
.dep-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  padding: 2px 0;
  font-size: 0.9rem;
}
.dep-row--hi {
  color: var(--app-primary);
  font-weight: 600;
}
.est-ccy {
  margin-bottom: var(--app-space-3);
}
.est-ccy__title {
  font-weight: 700;
  color: var(--app-secondary);
  margin-bottom: 2px;
}
</style>
