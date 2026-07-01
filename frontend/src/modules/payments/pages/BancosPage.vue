<template>
  <q-page class="app-page">
    <PageHeader
      title="Bancos"
      subtitle="Cuentas bancarias y conciliación de extractos: cada línea del banco se cruza contra los pagos del sistema (transferencias, cheques, tarjetas). El efectivo se controla con el arqueo de caja."
      :loading="cargando"
      @refresh="recargar"
    />

    <q-tabs
      v-model="tab"
      dense
      no-caps
      align="left"
      class="ban-tabs"
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab name="cuentas" icon="account_balance" label="Cuentas" />
      <q-tab name="extractos" icon="receipt_long" label="Extractos" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <q-tab-panels v-model="tab" animated class="ban-panels">
      <!-- ============ Cuentas ============ -->
      <q-tab-panel name="cuentas" class="q-pa-none">
        <div class="q-mb-sm">
          <q-btn
            v-if="puede('payments.bank.manage')"
            unelevated
            no-caps
            color="primary"
            icon="add"
            label="Nueva cuenta"
            @click="abrirNuevaCuenta"
          />
        </div>
        <q-table
          class="app-table"
          :rows="cuentas"
          :columns="columnasCuenta"
          row-key="id"
          flat
          :loading="cargando"
          :pagination="{ rowsPerPage: 25 }"
          no-data-label="Sin cuentas bancarias. Registrá la primera."
        />
      </q-tab-panel>

      <!-- ============ Extractos ============ -->
      <q-tab-panel name="extractos" class="q-pa-none">
        <div class="q-mb-sm">
          <q-btn
            v-if="puede('payments.bank.manage')"
            unelevated
            no-caps
            color="primary"
            icon="upload_file"
            label="Cargar extracto"
            :disable="!cuentas.length"
            @click="abrirNuevoExtracto"
          />
          <span v-if="!cuentas.length" class="text-caption text-muted q-ml-sm">
            Primero registrá una cuenta bancaria.
          </span>
        </div>
        <q-table
          class="app-table"
          :rows="extractos"
          :columns="columnasExtracto"
          row-key="id"
          flat
          :loading="cargando"
          :pagination="{ rowsPerPage: 25 }"
          no-data-label="Sin extractos cargados."
        >
          <template #body-cell-estado="props">
            <q-td :props="props">
              <q-chip
                dense
                square
                :class="props.row.status === 'RECONCILED' ? 'ban-chip-ok' : 'ban-chip-open'"
                :label="BANK_STATEMENT_STATUS_LABELS[props.row.status] ?? props.row.status"
              />
            </q-td>
          </template>
          <template #body-cell-acciones="props">
            <q-td :props="props" class="text-right">
              <q-btn
                flat
                dense
                no-caps
                size="sm"
                icon="rule"
                :label="props.row.status === 'OPEN' ? 'Conciliar' : 'Ver'"
                @click="abrirConciliacion(props.row.id)"
              />
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>
    </q-tab-panels>

    <!-- Diálogo: nueva cuenta -->
    <q-dialog v-model="dlgCuenta">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Nueva cuenta bancaria</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="formCuenta.bank_name" outlined dense label="Banco *" />
          <q-input v-model="formCuenta.name" outlined dense label="Nombre de la cuenta * (ej. Corriente córdobas)" />
          <q-input v-model="formCuenta.account_number" outlined dense label="Número de cuenta *" />
          <q-input v-model="formCuenta.currency" outlined dense label="Moneda" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Registrar"
            :loading="accionando"
            :disable="!formCuenta.bank_name.trim() || !formCuenta.name.trim() || !formCuenta.account_number.trim()"
            @click="crearCuenta"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: nuevo extracto -->
    <q-dialog v-model="dlgExtracto">
      <q-card class="app-dialog ban-dlg-extracto">
        <q-card-section class="text-h6">Cargar extracto bancario</q-card-section>
        <q-card-section class="app-form">
          <q-select
            v-model="formExt.bank_account_id"
            :options="opcionesCuenta"
            outlined
            dense
            emit-value
            map-options
            label="Cuenta *"
          />
          <div class="row q-col-gutter-sm">
            <q-input v-model="formExt.period_start" outlined dense type="date" label="Desde *" class="col" />
            <q-input v-model="formExt.period_end" outlined dense type="date" label="Hasta *" class="col" />
          </div>
          <div class="row q-col-gutter-sm">
            <q-input v-model="formExt.opening_balance" outlined dense type="number" label="Saldo inicial *" class="col" />
            <q-input v-model="formExt.closing_balance" outlined dense type="number" label="Saldo final *" class="col" />
          </div>

          <q-input
            v-model="csv"
            outlined
            dense
            type="textarea"
            rows="5"
            label="Pegar líneas (CSV: fecha,descripción,referencia,monto)"
            hint="Una línea por movimiento. Fecha AAAA-MM-DD; monto con signo: + depósito, − retiro. Ej: 2026-06-10,Transferencia recibida,TRX123,1500.00"
            @update:model-value="parsearCsv"
          />
          <div v-if="errorCsv" class="text-caption text-negative">{{ errorCsv }}</div>

          <div class="ban-lineas-head">
            Líneas ({{ formExt.lines.length }})
            <q-btn flat dense no-caps size="sm" icon="add" label="Agregar línea" @click="agregarLinea" />
          </div>
          <div v-for="(ln, i) in formExt.lines" :key="i" class="ban-linea">
            <q-input v-model="ln.line_date" dense outlined type="date" class="ban-linea__fecha" />
            <q-input v-model="ln.description" dense outlined placeholder="Descripción" class="ban-linea__desc" />
            <q-input v-model="ln.reference" dense outlined placeholder="Ref." class="ban-linea__ref" />
            <q-input v-model="ln.amount" dense outlined type="number" placeholder="Monto ±" class="ban-linea__monto" />
            <q-btn flat dense round size="sm" icon="close" @click="formExt.lines.splice(i, 1)" />
          </div>
          <div class="text-caption text-muted">
            Suma de líneas: <strong>{{ formatMoney(sumaLineas) }}</strong> · Inicial + líneas =
            <strong>{{ formatMoney(Number(formExt.opening_balance || 0) + sumaLineas) }}</strong>
            (debe dar el saldo final para poder conciliar)
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Cargar extracto"
            :loading="accionando"
            :disable="!extractoValido"
            @click="crearExtracto"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: conciliación -->
    <q-dialog v-model="dlgConciliar" maximized>
      <q-card class="app-dialog">
        <q-card-section class="row items-center">
          <div class="text-h6">
            Conciliación — {{ detalle?.bank_name }} · {{ detalle ? formatDate(detalle.period_start) : '' }}
            → {{ detalle ? formatDate(detalle.period_end) : '' }}
          </div>
          <q-space />
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>

        <q-card-section v-if="detalle" class="q-pt-none">
          <div class="ban-progreso">
            <div>
              Saldo inicial <strong>{{ formatMoney(detalle.opening_balance) }}</strong> · Saldo final
              <strong>{{ formatMoney(detalle.closing_balance) }}</strong> ·
              <q-chip
                dense
                square
                :class="detalle.status === 'RECONCILED' ? 'ban-chip-ok' : 'ban-chip-open'"
                :label="BANK_STATEMENT_STATUS_LABELS[detalle.status] ?? detalle.status"
              />
            </div>
            <div class="ban-progreso__barra">
              <q-linear-progress
                :value="detalle.lines_total ? detalle.lines_resolved / detalle.lines_total : 0"
                size="10px"
                rounded
              />
              <span class="text-caption">{{ detalle.lines_resolved }}/{{ detalle.lines_total }} líneas resueltas</span>
            </div>
            <div v-if="detalle.status === 'OPEN' && puedeConciliar" class="row q-gutter-sm">
              <q-btn
                outline
                no-caps
                color="primary"
                icon="auto_fix_high"
                label="Sugerir matches"
                :loading="sugiriendo"
                @click="sugerir"
              />
              <q-btn
                unelevated
                no-caps
                color="positive"
                icon="task_alt"
                label="Conciliar extracto"
                :loading="accionando"
                :disable="detalle.lines_resolved !== detalle.lines_total"
                @click="conciliar"
              />
            </div>
          </div>

          <q-table
            class="app-table"
            :rows="detalle.lines"
            :columns="columnasLinea"
            row-key="id"
            flat
            :pagination="{ rowsPerPage: 50 }"
            no-data-label="El extracto no tiene líneas."
          >
            <template #body-cell-monto="props">
              <q-td
                :props="props"
                :class="Number(props.row.amount) < 0 ? 'text-negative' : 'text-positive'"
                class="text-weight-bold"
              >
                {{ formatMoney(props.row.amount) }}
              </q-td>
            </template>
            <template #body-cell-estado="props">
              <q-td :props="props">
                <q-chip
                  dense
                  square
                  :class="{
                    'ban-chip-ok': props.row.status === 'MATCHED',
                    'ban-chip-open': props.row.status === 'UNMATCHED',
                    'ban-chip-warn': props.row.status === 'EXCLUDED',
                  }"
                  :label="BANK_LINE_STATUS_LABELS[props.row.status] ?? props.row.status"
                />
              </q-td>
            </template>
            <template #body-cell-match="props">
              <q-td :props="props">
                <template v-if="props.row.status === 'MATCHED'">
                  {{ props.row.matched_method }} · {{ props.row.matched_external_ref || props.row.matched_payment_id?.slice(0, 8) }}
                </template>
                <template v-else-if="props.row.status === 'EXCLUDED'">
                  <span class="text-muted">{{ props.row.excluded_reason }}</span>
                </template>
                <template v-else-if="sugerencias.get(props.row.id)?.length">
                  <q-btn
                    v-for="c in sugerencias.get(props.row.id)"
                    :key="c.payment_id"
                    outline
                    dense
                    no-caps
                    size="sm"
                    color="primary"
                    class="q-mr-xs"
                    :label="`${c.method} ${formatMoney(c.amount)} · ${c.external_ref || c.payment_id.slice(0, 8)}`"
                    @click="confirmarMatch(props.row, c.payment_id)"
                  />
                </template>
              </q-td>
            </template>
            <template #body-cell-acciones="props">
              <q-td :props="props" class="text-right ban-acciones">
                <template v-if="detalle.status === 'OPEN' && puedeConciliar">
                  <q-btn
                    v-if="props.row.status === 'UNMATCHED'"
                    flat
                    dense
                    no-caps
                    size="sm"
                    icon="link"
                    label="Match manual"
                    @click="abrirMatchManual(props.row)"
                  />
                  <q-btn
                    v-if="props.row.status === 'UNMATCHED'"
                    flat
                    dense
                    no-caps
                    size="sm"
                    icon="block"
                    label="Excluir"
                    @click="excluir(props.row)"
                  />
                  <q-btn
                    v-if="props.row.status !== 'UNMATCHED'"
                    flat
                    dense
                    no-caps
                    size="sm"
                    icon="undo"
                    label="Deshacer"
                    @click="deshacer(props.row)"
                  />
                </template>
              </q-td>
            </template>
          </q-table>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Diálogo: match manual -->
    <q-dialog v-model="dlgMatchManual">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Match manual</q-card-section>
        <q-card-section class="app-form">
          <div v-if="lineaObjetivo" class="text-caption">
            Línea: {{ formatDate(lineaObjetivo.line_date) }} · {{ lineaObjetivo.description }} ·
            <strong>{{ formatMoney(lineaObjetivo.amount) }}</strong>
          </div>
          <q-select
            v-model="matchPaymentId"
            :options="opcionesIntent"
            outlined
            dense
            emit-value
            map-options
            label="Pago del sistema *"
            :loading="cargandoIntents"
            hint="Solo pagos capturados por transferencia/cheque/tarjeta que aún no respaldan otra línea."
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Conciliar línea"
            :loading="accionando"
            :disable="!matchPaymentId"
            @click="matchManual"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, reactive, ref, onMounted } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatDate, formatMoney } from 'src/core/format';
import { MENSAJES_BANCOS } from 'src/modules/payments/messages';
import {
  BANK_LINE_STATUS_LABELS,
  BANK_STATEMENT_STATUS_LABELS,
  createBankAccount,
  createBankStatement,
  excludeBankLine,
  getBankStatement,
  listBankAccounts,
  listBankStatements,
  listPaymentIntents,
  matchBankLine,
  reconcileBankStatement,
  suggestBankMatches,
  unmatchBankLine,
  type BankAccountRow,
  type BankMatchCandidate,
  type BankStatementDetail,
  type BankStatementLineInput,
  type BankStatementLineRow,
  type BankStatementRow,
} from 'src/modules/payments/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const tab = ref('cuentas');
const cargando = ref(false);
const accionando = ref(false);

const cuentas = ref<BankAccountRow[]>([]);
const extractos = ref<BankStatementRow[]>([]);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}
const puedeConciliar = puede('payments.bank.reconcile');

function notificarError(e: unknown, fallback: string) {
  const crudo = apiErrorMessage(e, fallback);
  $q.notify({ type: 'negative', message: MENSAJES_BANCOS[crudo] ?? crudo });
}

const columnasCuenta: QTableColumn<BankAccountRow>[] = [
  { name: 'banco', label: 'Banco', field: 'bank_name', align: 'left', sortable: true },
  { name: 'nombre', label: 'Cuenta', field: 'name', align: 'left' },
  { name: 'numero', label: 'Número', field: 'account_number', align: 'left' },
  { name: 'moneda', label: 'Moneda', field: 'currency', align: 'center' },
];

const columnasExtracto: QTableColumn<BankStatementRow>[] = [
  { name: 'cuenta', label: 'Cuenta', field: (r) => `${r.bank_name} · ${r.bank_account_name}`, align: 'left' },
  { name: 'periodo', label: 'Período', field: (r) => `${formatDate(r.period_start)} → ${formatDate(r.period_end)}`, align: 'left' },
  { name: 'inicial', label: 'Saldo inicial', field: (r) => formatMoney(r.opening_balance), align: 'right' },
  { name: 'final', label: 'Saldo final', field: (r) => formatMoney(r.closing_balance), align: 'right' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

const columnasLinea: QTableColumn<BankStatementLineRow>[] = [
  { name: 'fecha', label: 'Fecha', field: (r) => formatDate(r.line_date), align: 'left' },
  { name: 'descripcion', label: 'Descripción', field: 'description', align: 'left' },
  { name: 'referencia', label: 'Referencia', field: 'reference', align: 'left' },
  { name: 'monto', label: 'Monto', field: 'amount', align: 'right' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'match', label: 'Pago / razón', field: 'matched_payment_id', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

async function recargar() {
  cargando.value = true;
  try {
    const tareas: Promise<void>[] = [
      listBankAccounts().then((r) => {
        cuentas.value = r;
      }),
      listBankStatements().then((r) => {
        extractos.value = r;
      }),
    ];
    await Promise.all(tareas);
  } catch (e) {
    notificarError(e, 'No se pudieron cargar los bancos.');
  } finally {
    cargando.value = false;
  }
}

// --- Nueva cuenta ---
const dlgCuenta = ref(false);
const formCuenta = reactive({ name: '', bank_name: '', account_number: '', currency: 'NIO' });

function abrirNuevaCuenta() {
  Object.assign(formCuenta, { name: '', bank_name: '', account_number: '', currency: 'NIO' });
  dlgCuenta.value = true;
}

async function crearCuenta() {
  accionando.value = true;
  try {
    await createBankAccount({
      name: formCuenta.name.trim(),
      bank_name: formCuenta.bank_name.trim(),
      account_number: formCuenta.account_number.trim(),
      currency: formCuenta.currency.trim() || 'NIO',
    });
    dlgCuenta.value = false;
    $q.notify({ type: 'positive', message: 'Cuenta bancaria registrada.' });
    await recargar();
  } catch (e) {
    notificarError(e, 'No se pudo registrar la cuenta.');
  } finally {
    accionando.value = false;
  }
}

// --- Nuevo extracto ---
const dlgExtracto = ref(false);
const csv = ref('');
const errorCsv = ref('');
const formExt = reactive<{
  bank_account_id: number | null;
  period_start: string;
  period_end: string;
  opening_balance: string;
  closing_balance: string;
  lines: BankStatementLineInput[];
}>({
  bank_account_id: null,
  period_start: '',
  period_end: '',
  opening_balance: '0.00',
  closing_balance: '',
  lines: [],
});

const opcionesCuenta = computed(() =>
  cuentas.value.map((c) => ({ value: c.id, label: `${c.bank_name} · ${c.name} (${c.account_number})` })),
);

const sumaLineas = computed(() => formExt.lines.reduce((acc, ln) => acc + Number(ln.amount || 0), 0));

const extractoValido = computed(
  () =>
    formExt.bank_account_id != null &&
    !!formExt.period_start &&
    !!formExt.period_end &&
    formExt.closing_balance !== '' &&
    formExt.lines.length > 0 &&
    formExt.lines.every((ln) => ln.line_date && Number(ln.amount) !== 0),
);

function abrirNuevoExtracto() {
  csv.value = '';
  errorCsv.value = '';
  Object.assign(formExt, {
    bank_account_id: cuentas.value[0]?.id ?? null,
    period_start: '',
    period_end: '',
    opening_balance: '0.00',
    closing_balance: '',
    lines: [],
  });
  dlgExtracto.value = true;
}

function agregarLinea() {
  formExt.lines.push({ line_date: formExt.period_end || '', description: '', reference: '', amount: '' });
}

/** CSV simple: fecha,descripción,referencia,monto — sin comillas anidadas (v1). */
function parsearCsv() {
  errorCsv.value = '';
  const texto = csv.value.trim();
  if (!texto) return;
  const nuevas: BankStatementLineInput[] = [];
  for (const [idx, cruda] of texto.split(/\r?\n/).entries()) {
    const linea = cruda.trim();
    if (!linea) continue;
    const partes = linea.split(',').map((p) => p.trim());
    if (partes.length < 2) {
      errorCsv.value = `Línea ${idx + 1}: se esperaba al menos fecha y monto separados por coma.`;
      return;
    }
    const fecha = partes[0] ?? '';
    const monto = partes[partes.length - 1] ?? '';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(fecha)) {
      errorCsv.value = `Línea ${idx + 1}: la fecha "${fecha}" no es AAAA-MM-DD.`;
      return;
    }
    if (Number.isNaN(Number(monto)) || Number(monto) === 0) {
      errorCsv.value = `Línea ${idx + 1}: el monto "${monto}" no es válido (con signo, distinto de 0).`;
      return;
    }
    nuevas.push({
      line_date: fecha,
      description: partes.length > 2 ? (partes[1] ?? '') : '',
      reference: partes.length > 3 ? (partes[2] ?? '') : '',
      amount: Number(monto).toFixed(2),
    });
  }
  formExt.lines = nuevas;
}

async function crearExtracto() {
  if (formExt.bank_account_id == null) return;
  accionando.value = true;
  try {
    const st = await createBankStatement({
      bank_account_id: formExt.bank_account_id,
      period_start: formExt.period_start,
      period_end: formExt.period_end,
      opening_balance: Number(formExt.opening_balance || 0).toFixed(2),
      closing_balance: Number(formExt.closing_balance).toFixed(2),
      lines: formExt.lines.map((ln) => ({
        line_date: ln.line_date,
        description: ln.description ?? '',
        reference: ln.reference ?? '',
        amount: Number(ln.amount).toFixed(2),
      })),
    });
    dlgExtracto.value = false;
    $q.notify({ type: 'positive', message: 'Extracto cargado. Ahora a conciliarlo.' });
    await recargar();
    abrirConciliacion(st.id);
  } catch (e) {
    notificarError(e, 'No se pudo cargar el extracto.');
  } finally {
    accionando.value = false;
  }
}

// --- Conciliación ---
const dlgConciliar = ref(false);
const detalle = ref<BankStatementDetail | null>(null);
const sugerencias = ref(new Map<number, BankMatchCandidate[]>());
const sugiriendo = ref(false);

function abrirConciliacion(statementId: number) {
  sugerencias.value = new Map();
  detalle.value = null;
  dlgConciliar.value = true;
  void refrescarDetalle(statementId);
}

async function refrescarDetalle(statementId: number) {
  try {
    detalle.value = await getBankStatement(statementId);
  } catch (e) {
    notificarError(e, 'No se pudo cargar el extracto.');
  }
}

async function sugerir() {
  if (!detalle.value) return;
  sugiriendo.value = true;
  try {
    const res = await suggestBankMatches(detalle.value.id);
    sugerencias.value = new Map(res.map((s) => [s.line_id, s.candidates]));
    const conCandidatos = res.filter((s) => s.candidates.length).length;
    $q.notify({
      type: conCandidatos ? 'positive' : 'info',
      message: conCandidatos
        ? `${conCandidatos} línea(s) con candidato: confirmá cada match.`
        : 'No se encontraron pagos que calcen por monto y fecha.',
    });
  } catch (e) {
    notificarError(e, 'No se pudieron sugerir matches.');
  } finally {
    sugiriendo.value = false;
  }
}

async function confirmarMatch(linea: BankStatementLineRow, paymentId: string) {
  if (!detalle.value) return;
  try {
    await matchBankLine(detalle.value.id, linea.id, paymentId);
    sugerencias.value.delete(linea.id);
    await refrescarDetalle(detalle.value.id);
  } catch (e) {
    notificarError(e, 'No se pudo conciliar la línea.');
  }
}

function excluir(linea: BankStatementLineRow) {
  $q.dialog({
    title: 'Excluir línea',
    message: `"${linea.description || formatMoney(linea.amount)}" no corresponde a un pago del sistema (comisión, interés, etc.). Razón:`,
    prompt: { model: '', type: 'text', isValid: (v: string) => v.trim().length >= 3 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'primary', label: 'Excluir' },
    persistent: true,
  }).onOk((razon: string) => {
    void (async () => {
      if (!detalle.value) return;
      try {
        await excludeBankLine(detalle.value.id, linea.id, razon.trim());
        await refrescarDetalle(detalle.value.id);
      } catch (e) {
        notificarError(e, 'No se pudo excluir la línea.');
      }
    })();
  });
}

async function deshacer(linea: BankStatementLineRow) {
  if (!detalle.value) return;
  try {
    await unmatchBankLine(detalle.value.id, linea.id);
    await refrescarDetalle(detalle.value.id);
  } catch (e) {
    notificarError(e, 'No se pudo deshacer.');
  }
}

async function conciliar() {
  if (!detalle.value) return;
  accionando.value = true;
  try {
    detalle.value = await reconcileBankStatement(detalle.value.id);
    $q.notify({ type: 'positive', message: 'Extracto conciliado. Quedó inmutable.' });
    await recargar();
  } catch (e) {
    notificarError(e, 'No se pudo conciliar el extracto.');
  } finally {
    accionando.value = false;
  }
}

// --- Match manual ---
const dlgMatchManual = ref(false);
const lineaObjetivo = ref<BankStatementLineRow | null>(null);
const matchPaymentId = ref<string | null>(null);
const intents = ref<{ payment_id: string; amount: string; payment_method: string; external_ref: string; status: string }[]>([]);
const cargandoIntents = ref(false);

const opcionesIntent = computed(() =>
  intents.value
    .filter(
      (i) =>
        i.status === 'CAPTURED' &&
        ['TRANSFER', 'CHECK', 'CARD'].includes(i.payment_method) &&
        (lineaObjetivo.value ? Number(i.amount) === Math.abs(Number(lineaObjetivo.value.amount)) : true),
    )
    .map((i) => ({
      value: i.payment_id,
      label: `${i.payment_method} · ${formatMoney(i.amount)} · ${i.external_ref || i.payment_id.slice(0, 8)}`,
    })),
);

function abrirMatchManual(linea: BankStatementLineRow) {
  lineaObjetivo.value = linea;
  matchPaymentId.value = null;
  dlgMatchManual.value = true;
  cargandoIntents.value = true;
  listPaymentIntents()
    .then((r) => {
      intents.value = r;
    })
    .catch((e: unknown) => {
      notificarError(e, 'No se pudieron cargar los pagos.');
    })
    .finally(() => {
      cargandoIntents.value = false;
    });
}

async function matchManual() {
  if (!detalle.value || !lineaObjetivo.value || !matchPaymentId.value) return;
  accionando.value = true;
  try {
    await matchBankLine(detalle.value.id, lineaObjetivo.value.id, matchPaymentId.value);
    dlgMatchManual.value = false;
    await refrescarDetalle(detalle.value.id);
  } catch (e) {
    notificarError(e, 'No se pudo conciliar la línea.');
  } finally {
    accionando.value = false;
  }
}

onMounted(recargar);
</script>

<style scoped>
.ban-tabs {
  color: var(--app-text-muted);
}

.ban-panels {
  background: transparent;
}

.ban-dlg-extracto {
  width: 760px;
  max-width: 95vw;
}

.ban-lineas-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 700;
  color: var(--app-text);
}

.ban-linea {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}

.ban-linea__fecha {
  width: 150px;
}

.ban-linea__desc {
  flex: 2;
}

.ban-linea__ref {
  flex: 1;
}

.ban-linea__monto {
  width: 130px;
}

.ban-progreso {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin-bottom: var(--app-space-3);
}

.ban-progreso__barra {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  max-width: 480px;
}

.ban-acciones {
  white-space: nowrap;
}

.ban-chip-ok {
  border: 1px solid var(--q-positive);
  color: var(--q-positive);
  background: transparent;
}

.ban-chip-open {
  border: 1px solid var(--app-border);
  color: var(--app-text);
  background: transparent;
}

.ban-chip-warn {
  border: 1px solid var(--q-warning);
  color: var(--app-text);
  background: transparent;
}
</style>
