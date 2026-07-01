<template>
  <q-page class="app-page">
    <PageHeader
      title="Diario contable"
      subtitle="Borradores generados por la operación (SoD: quien aprueba no es quien generó) y asientos posteados con reversa."
      :loading="cargando"
      @refresh="recargar"
    >
      <template #actions>
        <q-btn
          v-if="puede('accounting.manual_journal.create')"
          unelevated
          no-caps
          color="primary"
          icon="post_add"
          label="Nuevo asiento manual"
          @click="abrirAsientoManual"
        />
        <q-btn
          v-if="puede('accounting.journal_draft.approve')"
          outline
          no-caps
          color="primary"
          icon="task_alt"
          label="Aprobar validados"
          :loading="accionando"
          @click="aprobar"
        />
        <q-btn
          v-if="puede('accounting.journal_draft.post')"
          unelevated
          no-caps
          color="primary"
          icon="publish"
          label="Postear aprobados"
          :loading="accionando"
          @click="postear"
        />
        <q-btn
          v-if="puede('accounting.journal_entry.reverse')"
          outline
          no-caps
          color="negative"
          icon="undo"
          label="Reversar lote (período)"
          @click="dlgReversaLote = true"
        />
      </template>
    </PageHeader>

    <q-tabs
      v-model="tab"
      dense
      no-caps
      align="left"
      class="dia-tabs"
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab name="borradores" icon="edit_note" label="Borradores" />
      <q-tab v-if="puede('accounting.journal_entry.read')" name="asientos" icon="menu_book" label="Asientos" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <q-tab-panels v-model="tab" animated class="dia-panels">
      <q-tab-panel name="borradores" class="q-pa-none">
        <div class="dia-filtros">
          <q-select
            v-model="filtroEstado"
            :options="opcionesEstado"
            dense
            outlined
            emit-value
            map-options
            clearable
            label="Estado"
            class="dia-filtros__sel"
            @update:model-value="recargar"
          />
        </div>
        <q-table
          class="app-table"
          :rows="borradores"
          :columns="columnasBorrador"
          row-key="id"
          flat
          :loading="cargando"
          :pagination="{ rowsPerPage: 25 }"
          no-data-label="Sin borradores con ese filtro."
        >
          <template #body-cell-estado="props">
            <q-td :props="props">
              <EstadoChip :estado="props.row.state" :map="MAPA_DRAFT" />
              <q-icon
                v-if="props.row.validation_passed === false"
                name="error"
                color="negative"
                size="18px"
              >
                <q-tooltip>La validación falló</q-tooltip>
              </q-icon>
            </q-td>
          </template>
          <template #body-cell-debe="props">
            <q-td :props="props">{{ formatMoney(props.row.total_debit) }}</q-td>
          </template>
          <template #body-cell-haber="props">
            <q-td :props="props">{{ formatMoney(props.row.total_credit) }}</q-td>
          </template>
          <template #body-cell-generado="props">
            <q-td :props="props">{{ formatDateTime(props.row.generated_at) }}</q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <q-tab-panel name="asientos" class="q-pa-none">
        <q-table
          class="app-table"
          :rows="asientos"
          :columns="columnasAsiento"
          row-key="id"
          flat
          :loading="cargando"
          :pagination="{ rowsPerPage: 25 }"
          no-data-label="Sin asientos posteados."
        >
          <template #body-cell-fecha="props">
            <q-td :props="props">{{ formatDate(props.row.entry_date) }}</q-td>
          </template>
          <template #body-cell-debe="props">
            <q-td :props="props">{{ formatMoney(props.row.debit_total) }}</q-td>
          </template>
          <template #body-cell-haber="props">
            <q-td :props="props">{{ formatMoney(props.row.credit_total) }}</q-td>
          </template>
          <template #body-cell-acciones="props">
            <q-td :props="props" class="text-right">
              <q-btn
                v-if="puede('accounting.journal_entry.reverse')"
                flat
                dense
                no-caps
                size="sm"
                color="negative"
                icon="undo"
                label="Reversar"
                @click="reversar(props.row)"
              />
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>
    </q-tab-panels>

    <!-- Diálogo: nuevo asiento manual -->
    <q-dialog v-model="dlgManual">
      <q-card class="app-dialog dia-manual-dlg">
        <q-card-section class="text-h6">Nuevo asiento manual</q-card-section>
        <q-card-section class="app-form">
          <div class="row q-col-gutter-sm">
            <q-input v-model="manual.entry_date" outlined dense type="date" label="Fecha *" class="col" />
            <q-input v-model="manual.memo" outlined dense label="Concepto" class="col-8" />
          </div>

          <div class="dia-manual-head">
            Líneas
            <q-btn flat dense no-caps size="sm" icon="add" label="Agregar línea" @click="agregarLinea" />
          </div>
          <div v-for="(ln, i) in manual.lines" :key="i" class="dia-manual-linea">
            <q-select
              v-model="ln.account_code"
              :options="opcionesCuenta"
              outlined
              dense
              emit-value
              map-options
              use-input
              input-debounce="0"
              @filter="filtrarCuentas"
              label="Cuenta"
              class="dia-manual-linea__cta"
            />
            <q-select
              v-model="ln.side"
              :options="[{ value: 'DEBIT', label: 'Debe' }, { value: 'CREDIT', label: 'Haber' }]"
              outlined
              dense
              emit-value
              map-options
              class="dia-manual-linea__side"
            />
            <q-input v-model="ln.amount" outlined dense type="number" label="Monto" class="dia-manual-linea__monto" />
            <q-select
              v-model="ln.cost_center_id"
              :options="opcionesCentro"
              outlined
              dense
              emit-value
              map-options
              clearable
              label="Centro"
              class="dia-manual-linea__cc"
            />
            <q-btn flat dense round size="sm" icon="close" @click="manual.lines.splice(i, 1)" />
          </div>

          <div class="dia-manual-totales" :class="cuadrado ? 'text-positive' : 'text-negative'">
            Debe <strong>{{ formatMoney(totalDebe) }}</strong> · Haber <strong>{{ formatMoney(totalHaber) }}</strong>
            <span v-if="!cuadrado"> · descuadre {{ formatMoney(totalDebe - totalHaber) }}</span>
            <span v-else> · cuadra ✓</span>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear borrador"
            :loading="accionando"
            :disable="!cuadrado || totalDebe <= 0"
            @click="guardarAsientoManual"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: reversa por lote (período) -->
    <q-dialog v-model="dlgReversaLote">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Reversar lote por período</q-card-section>
        <q-card-section class="app-form">
          <div class="row q-col-gutter-sm">
            <q-input v-model.number="reversaLote.year" outlined dense type="number" label="Año *" class="col" />
            <q-input v-model.number="reversaLote.month" outlined dense type="number" min="1" max="12" label="Mes *" class="col" />
          </div>
          <q-input v-model="reversaLote.reason" outlined dense label="Motivo *" type="textarea" autogrow />
          <div class="text-caption text-muted">
            Genera el asiento contrario de TODOS los asientos posteados del período elegido.
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="negative"
            label="Reversar lote"
            :loading="accionando"
            :disable="!reversaLote.year || !reversaLote.month || reversaLote.reason.trim().length < 5"
            @click="reversarLote"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import EstadoChip, { type EstadoEstilo } from 'src/components/EstadoChip.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatDate, formatDateTime, formatMoney } from 'src/core/format';
import {
  ACCOUNTING_PLUS_MENSAJES,
  approveDrafts,
  createManualJournalDraft,
  DRAFT_STATE_LABELS,
  getChartOfAccounts,
  listCostCenters,
  listJournalDrafts,
  listJournalEntries,
  postDrafts,
  reverseJournalBatch,
  reverseJournalEntry,
  type CoARow,
  type CostCenterRow,
  type JournalDraftRow,
  type JournalEntryRow,
  type ManualLineInput,
} from 'src/modules/accounting/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

function estiloDraft(code: string, label: string): EstadoEstilo {
  const estilo: EstadoEstilo = {
    label,
    color:
      code === 'POSTED'
        ? 'secondary'
        : code === 'EXCEPTION'
          ? 'negative'
          : code === 'APPROVED_FOR_POSTING'
            ? 'primary'
            : 'grey-7',
    outline: code !== 'POSTED',
  };
  if (code === 'POSTED') {
    estilo.textColor = 'white';
  }
  return estilo;
}

const MAPA_DRAFT: Record<string, EstadoEstilo> = Object.fromEntries(
  Object.entries(DRAFT_STATE_LABELS).map(([code, label]) => [code, estiloDraft(code, label)]),
);

const tab = ref('borradores');
const cargando = ref(false);
const accionando = ref(false);
const filtroEstado = ref<string | null>(null);
const borradores = ref<JournalDraftRow[]>([]);
const asientos = ref<JournalEntryRow[]>([]);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const opcionesEstado = Object.entries(DRAFT_STATE_LABELS).map(([value, label]) => ({ value, label }));

const columnasBorrador: QTableColumn<JournalDraftRow>[] = [
  { name: 'id', label: '#', field: 'id', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'state', align: 'left' },
  { name: 'debe', label: 'Debe', field: 'total_debit', align: 'right' },
  { name: 'haber', label: 'Haber', field: 'total_credit', align: 'right' },
  { name: 'generado', label: 'Generado', field: 'generated_at', align: 'left' },
  { name: 'evento', label: 'Evento', field: 'economic_event_id', align: 'left' },
];

const columnasAsiento: QTableColumn<JournalEntryRow>[] = [
  { name: 'id', label: '#', field: 'id', align: 'left' },
  { name: 'fecha', label: 'Fecha', field: 'entry_date', align: 'left' },
  { name: 'descripcion', label: 'Descripción', field: 'description', align: 'left' },
  { name: 'debe', label: 'Debe', field: 'debit_total', align: 'right' },
  { name: 'haber', label: 'Haber', field: 'credit_total', align: 'right' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

async function recargar() {
  cargando.value = true;
  try {
    const tareas: Promise<void>[] = [
      listJournalDrafts(filtroEstado.value ?? undefined).then((r) => {
        borradores.value = r;
      }),
    ];
    if (puede('accounting.journal_entry.read')) {
      tareas.push(
        listJournalEntries().then((r) => {
          asientos.value = r;
        }),
      );
    }
    await Promise.all(tareas);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el diario.') });
  } finally {
    cargando.value = false;
  }
}

async function aprobar() {
  accionando.value = true;
  try {
    const r = await approveDrafts();
    $q.notify({
      type: 'positive',
      message: `Aprobados ${r.approved} de ${r.attempted} (omitidos ${r.skipped}).`,
    });
    await recargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo aprobar (¿SoD: vos generaste estos borradores?).') });
  } finally {
    accionando.value = false;
  }
}

async function postear() {
  accionando.value = true;
  try {
    await postDrafts();
    $q.notify({ type: 'positive', message: 'Borradores aprobados posteados al diario.' });
    await recargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo postear.') });
  } finally {
    accionando.value = false;
  }
}

function reversar(a: JournalEntryRow) {
  $q.dialog({
    title: `Reversar asiento #${a.id}`,
    message: 'Motivo de la reversa (genera el asiento contrario):',
    prompt: { model: '', type: 'text', isValid: (v: string) => v.trim().length >= 5 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'negative', label: 'Reversar' },
    persistent: true,
  }).onOk((motivo: string) => {
    void (async () => {
      try {
        await reverseJournalEntry(a.id, motivo.trim());
        $q.notify({ type: 'positive', message: 'Asiento reversado.' });
        await recargar();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo reversar.') });
      }
    })();
  });
}

// --- Reversa por lote (período) ---
const now = new Date();
const dlgReversaLote = ref(false);
const reversaLote = ref<{ year: number; month: number; reason: string }>({
  year: now.getFullYear(),
  month: now.getMonth() + 1,
  reason: '',
});

async function reversarLote() {
  accionando.value = true;
  try {
    const r = await reverseJournalBatch({
      year: reversaLote.value.year,
      month: reversaLote.value.month,
      reason: reversaLote.value.reason.trim(),
    });
    dlgReversaLote.value = false;
    const n = typeof r.reversed === 'number' ? r.reversed : typeof r.count === 'number' ? r.count : null;
    $q.notify({ type: 'positive', message: `Lote reversado${n !== null ? ` (${n} asientos)` : ''}.` });
    await recargar();
  } catch (e) {
    const crudo = apiErrorMessage(e, 'No se pudo reversar el lote.');
    $q.notify({ type: 'negative', message: ACCOUNTING_PLUS_MENSAJES[crudo] ?? crudo });
  } finally {
    accionando.value = false;
  }
}

// --- Asiento manual ---
interface LineaManual {
  account_code: string | null;
  side: 'DEBIT' | 'CREDIT';
  amount: string;
  cost_center_id: number | null;
}

const dlgManual = ref(false);
const cuentas = ref<CoARow[]>([]);
const centros = ref<CostCenterRow[]>([]);
const opcionesCuentaAll = ref<{ value: string; label: string }[]>([]);
const opcionesCuenta = ref<{ value: string; label: string }[]>([]);
const manual = ref<{ entry_date: string; memo: string; lines: LineaManual[] }>({
  entry_date: new Date().toISOString().slice(0, 10),
  memo: '',
  lines: [],
});

const opcionesCentro = computed(() =>
  centros.value.filter((c) => c.is_active).map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` })),
);

const totalDebe = computed(() =>
  manual.value.lines.filter((l) => l.side === 'DEBIT').reduce((a, l) => a + Number(l.amount || 0), 0),
);
const totalHaber = computed(() =>
  manual.value.lines.filter((l) => l.side === 'CREDIT').reduce((a, l) => a + Number(l.amount || 0), 0),
);
const cuadrado = computed(() => totalDebe.value > 0 && totalDebe.value.toFixed(2) === totalHaber.value.toFixed(2));

function filtrarCuentas(val: string, update: (cb: () => void) => void) {
  update(() => {
    const needle = val.toLowerCase();
    opcionesCuenta.value = needle
      ? opcionesCuentaAll.value.filter((o) => o.label.toLowerCase().includes(needle))
      : opcionesCuentaAll.value;
  });
}

function agregarLinea() {
  manual.value.lines.push({ account_code: null, side: 'DEBIT', amount: '', cost_center_id: null });
}

async function abrirAsientoManual() {
  manual.value = {
    entry_date: new Date().toISOString().slice(0, 10),
    memo: '',
    lines: [
      { account_code: null, side: 'DEBIT', amount: '', cost_center_id: null },
      { account_code: null, side: 'CREDIT', amount: '', cost_center_id: null },
    ],
  };
  dlgManual.value = true;
  try {
    const [coa, ccs] = await Promise.all([getChartOfAccounts(), listCostCenters()]);
    cuentas.value = coa.results.filter((c) => c.is_postable);
    opcionesCuentaAll.value = cuentas.value.map((c) => ({ value: c.code, label: `${c.code} · ${c.name}` }));
    opcionesCuenta.value = opcionesCuentaAll.value;
    centros.value = ccs;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el catálogo.') });
  }
}

async function guardarAsientoManual() {
  accionando.value = true;
  try {
    const lines: ManualLineInput[] = manual.value.lines
      .filter((l) => l.account_code && Number(l.amount) > 0)
      .map((l) => ({
        account_code: l.account_code as string,
        side: l.side,
        amount: Number(l.amount).toFixed(2),
        ...(l.cost_center_id ? { cost_center_id: l.cost_center_id } : {}),
      }));
    await createManualJournalDraft({
      entry_date: manual.value.entry_date,
      memo: manual.value.memo,
      lines,
    });
    dlgManual.value = false;
    $q.notify({
      type: 'positive',
      message: 'Asiento manual creado como borrador. Otra persona debe aprobarlo y postearlo (SoD).',
      timeout: 6000,
    });
    await recargar();
  } catch (e) {
    const crudo = apiErrorMessage(e, 'No se pudo crear el asiento.');
    $q.notify({ type: 'negative', message: ACCOUNTING_PLUS_MENSAJES[crudo] ?? crudo });
  } finally {
    accionando.value = false;
  }
}

onMounted(recargar);
</script>

<style scoped>
.dia-tabs {
  color: var(--app-text-muted);
}

.dia-panels {
  background: transparent;
}

.dia-filtros {
  margin-bottom: var(--app-space-3);
}

.dia-filtros__sel {
  width: 220px;
}
</style>
