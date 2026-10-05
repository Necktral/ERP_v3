<template>
  <q-page class="app-page">
    <PageHeader
      title="Diagnóstico"
      subtitle="Supervisión técnica: errores de runtime por clase de riesgo, hallazgos de seguridad, gate de release y kill switch de IA."
      :loading="cargando"
      @refresh="recargar"
    >
      <template #actions>
        <q-toggle
          v-if="puede('diagnostics.ai_control.manage')"
          :model-value="iaEncendida"
          checked-icon="smart_toy"
          color="primary"
          label="IA"
          @update:model-value="toggleIA"
        >
          <q-tooltip>Kill switch de IA (apaga toda síntesis/análisis IA)</q-tooltip>
        </q-toggle>
      </template>
    </PageHeader>

    <div v-if="readiness" class="dgx-readiness" :class="readinessOk ? 'is-ok' : 'is-block'">
      <q-icon :name="readinessOk ? 'verified' : 'block'" size="20px" />
      {{ readinessOk ? 'Listo para release: sin errores C1 abiertos.' : 'Release BLOQUEADO: hay errores C1 abiertos.' }}
    </div>

    <q-tabs
      v-model="tab"
      dense
      no-caps
      align="left"
      class="dgx-tabs"
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab name="errores" icon="bug_report" label="Errores" />
      <q-tab v-if="puede('diagnostics.finding.read')" name="seguridad" icon="security" label="Seguridad" />
      <q-tab v-if="puede('diagnostics.diagnose.read')" name="diagnosticos" icon="troubleshoot" label="Diagnósticos" />
      <q-tab name="cobertura" icon="fact_check" label="Cobertura" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <q-tab-panels v-model="tab" animated class="dgx-panels">
      <q-tab-panel name="errores" class="q-pa-none">
        <div class="dgx-filtros">
          <q-select
            v-model="filtroRiesgo"
            :options="opcionesRiesgo"
            dense
            outlined
            emit-value
            map-options
            clearable
            label="Riesgo"
            class="dgx-filtros__sel"
            @update:model-value="recargar"
          />
          <q-select
            v-model="filtroEstado"
            :options="opcionesEstadoError"
            dense
            outlined
            emit-value
            map-options
            clearable
            label="Estado"
            class="dgx-filtros__sel"
            @update:model-value="recargar"
          />
        </div>
        <q-table
          class="app-table"
          :rows="errores"
          :columns="columnasError"
          row-key="error_id"
          flat
          dense
          :loading="erroresListado.loading.value"
          v-model:pagination="erroresListado.pagination.value"
          @request="erroresListado.onRequest"
          no-data-label="Sin errores con esos filtros. Excelente."
        >
          <template #body-cell-riesgo="props">
            <q-td :props="props">
              <q-chip
                dense
                :color="props.row.risk_class === 'C1' ? 'negative' : props.row.risk_class === 'C2' ? 'warning' : 'grey-7'"
                text-color="white"
                :label="props.row.risk_class"
              />
            </q-td>
          </template>
          <template #body-cell-estado="props">
            <q-td :props="props">{{ ERROR_STATUS_LABELS[props.row.status] ?? props.row.status }}</q-td>
          </template>
          <template #body-cell-acciones="props">
            <q-td :props="props" class="text-right dgx-acciones">
              <q-btn
                v-if="puede('diagnostics.diagnose.run')"
                flat
                dense
                no-caps
                size="sm"
                icon="troubleshoot"
                label="Diagnosticar"
                @click="diagnosticar(props.row)"
              />
              <q-btn
                v-if="puede('diagnostics.error.triage') && props.row.status === 'open'"
                flat
                dense
                no-caps
                size="sm"
                label="Triage"
                @click="triage(props.row)"
              />
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <q-tab-panel name="seguridad" class="q-pa-none">
        <q-table
          class="app-table"
          :rows="hallazgos"
          :columns="columnasHallazgo"
          row-key="finding_id"
          flat
          dense
          :loading="hallazgosListado.loading.value"
          v-model:pagination="hallazgosListado.pagination.value"
          @request="hallazgosListado.onRequest"
          no-data-label="Sin hallazgos de seguridad."
        >
          <template #body-cell-acciones="props">
            <q-td :props="props" class="text-right">
              <q-btn
                v-if="puede('diagnostics.finding.triage') && props.row.status === 'open'"
                flat
                dense
                no-caps
                size="sm"
                label="Triage"
                @click="triageSeguridad(props.row)"
              />
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <q-tab-panel name="diagnosticos" class="q-pa-none">
        <q-table
          class="app-table"
          :rows="diagnosticos"
          :columns="columnasDiag"
          row-key="run_id"
          flat
          dense
          :loading="diagnosticosListado.loading.value"
          v-model:pagination="diagnosticosListado.pagination.value"
          @request="diagnosticosListado.onRequest"
          no-data-label="Sin diagnósticos. Genera uno con «Diagnosticar» en un error."
        >
          <template #body-cell-riesgo="props">
            <q-td :props="props">
              <q-chip dense :color="props.row.risk_class === 'C1' ? 'negative' : props.row.risk_class === 'C2' ? 'warning' : 'grey-7'" text-color="white" :label="props.row.risk_class || '—'" />
            </q-td>
          </template>
          <template #body-cell-ia="props">
            <q-td :props="props">
              <q-icon v-if="props.row.ai_assisted" name="smart_toy" color="primary" size="18px"><q-tooltip>Con análisis IA</q-tooltip></q-icon>
              <span v-else class="text-muted">—</span>
            </q-td>
          </template>
          <template #body-cell-acciones="props">
            <q-td :props="props" class="text-right dgx-acciones">
              <q-btn flat dense no-caps size="sm" icon="visibility" label="Ver" @click="verDiagnostico(props.row)" />
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <q-tab-panel name="cobertura" class="q-pa-none">
        <q-table
          class="app-table"
          :rows="cobertura"
          :columns="columnasCobertura"
          row-key="path"
          flat
          dense
          :loading="coberturaListado.loading.value"
          v-model:pagination="coberturaListado.pagination.value"
          @request="coberturaListado.onRequest"
          no-data-label="Sin evidencia de cobertura registrada."
        >
          <template #body-cell-cobertura="props">
            <q-td :props="props">
              <q-chip dense :color="coberturaColor(props.row.coverage_state)" text-color="white" :label="COVERAGE_LABELS[props.row.coverage_state] ?? props.row.coverage_state" />
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>
    </q-tab-panels>

    <q-dialog v-model="dlgDiag">
      <q-card class="app-dialog dgx-detalle">
        <q-card-section class="text-h6">Diagnóstico</q-card-section>
        <q-card-section>
          <pre class="dgx-json">{{ textoDiag }}</pre>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cerrar" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Detalle de un diagnóstico (run) + análisis IA -->
    <q-dialog v-model="dlgRun">
      <q-card class="app-dialog dgx-detalle">
        <q-card-section class="row items-center justify-between">
          <div class="text-h6">Diagnóstico · {{ runSel?.subject_type }} {{ runSel?.subject_id }}</div>
          <q-chip v-if="runSel" dense :color="runSel.ai_assisted ? 'primary' : 'grey-6'" text-color="white" :icon="runSel.ai_assisted ? 'smart_toy' : 'functions'" :label="runSel.ai_assisted ? 'Con IA' : 'Determinista'" />
        </q-card-section>
        <q-card-section v-if="runSel" class="dgx-run">
          <div class="dgx-run__meta">
            Dominio <b>{{ runSel.domain || '—' }}</b> · Riesgo <b>{{ runSel.risk_class || '—' }}</b> ·
            Confianza <b>{{ CONFIDENCE_LABELS[runSel.confidence] ?? (runSel.confidence || '—') }}</b> ·
            {{ formatDateTime(runSel.created_at) }}
          </div>
          <div v-if="runSel.summary" class="dgx-run__block"><div class="dgx-run__h">Resumen</div>{{ runSel.summary }}</div>
          <div v-if="runSel.root_cause_hypothesis" class="dgx-run__block"><div class="dgx-run__h">Hipótesis de causa raíz</div>{{ runSel.root_cause_hypothesis }}</div>
          <div v-if="runSel.recommended_tests" class="dgx-run__block"><div class="dgx-run__h">Pruebas recomendadas</div>{{ runSel.recommended_tests }}</div>
          <div v-if="runSel.recommended_fix" class="dgx-run__block"><div class="dgx-run__h">Corrección recomendada</div>{{ runSel.recommended_fix }}</div>
          <div v-if="tieneDetalle(runSel.blast_radius)" class="dgx-run__block"><div class="dgx-run__h">Radio de impacto</div><pre class="dgx-json">{{ pretty(runSel.blast_radius) }}</pre></div>
          <div v-if="tieneDetalle(runSel.evidence)" class="dgx-run__block"><div class="dgx-run__h">Evidencia</div><pre class="dgx-json">{{ pretty(runSel.evidence) }}</pre></div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn
            v-if="puede('diagnostics.ai_diagnose.run')"
            unelevated
            no-caps
            color="primary"
            icon="smart_toy"
            label="Analizar con IA"
            :loading="analizandoIA"
            :disable="!iaEncendida"
            @click="analizarIA"
          >
            <q-tooltip v-if="!iaEncendida">La IA está apagada (kill switch)</q-tooltip>
          </q-btn>
          <q-btn flat no-caps label="Cerrar" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { formatDateTime } from 'src/core/format';
import {
  aiAnalyzeDiagnosis,
  CONFIDENCE_LABELS,
  COVERAGE_LABELS,
  diagnoseError,
  ERROR_STATUS_LABELS,
  getAiControl,
  getDiagnosis,
  getReleaseReadiness,
  listCodeEvidencePage,
  listDiagnosesPage,
  listErrorsPage,
  listSecurityFindingsPage,
  RISK_LABELS,
  setAiControl,
  triageError,
  triageSecurityFinding,
  type CodeEvidenceRow,
  type DiagnosisRow,
  type ErrorEventRow,
  type SecurityFindingRow,
} from 'src/modules/diagnostics/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const tab = ref('errores');
const filtroRiesgo = ref<string | null>(null);
const filtroEstado = ref<string | null>(null);
const readiness = ref<Record<string, unknown> | null>(null);
const iaEncendida = ref(false);

const erroresListado = useListadoServer(
  (page) => listErrorsPage(page, {
    ...(filtroRiesgo.value ? { risk_class: filtroRiesgo.value } : {}),
    ...(filtroEstado.value ? { status: filtroEstado.value } : {}),
  }),
  { auto: false, errorMessage: 'No se pudieron cargar los errores.' },
);
const hallazgosListado = useListadoServer(listSecurityFindingsPage, {
  auto: false,
  errorMessage: 'No se pudieron cargar los hallazgos de seguridad.',
});
const diagnosticosListado = useListadoServer(
  (page) => listDiagnosesPage(page, filtroRiesgo.value ? { risk_class: filtroRiesgo.value } : {}),
  { auto: false, errorMessage: 'No se pudieron cargar los diagnósticos.' },
);
const coberturaListado = useListadoServer(listCodeEvidencePage, {
  auto: false,
  errorMessage: 'No se pudo cargar la evidencia de cobertura.',
});
const errores = erroresListado.rows;
const hallazgos = hallazgosListado.rows;
const diagnosticos = diagnosticosListado.rows;
const cobertura = coberturaListado.rows;
const cargandoAuxiliar = ref(false);
const cargando = computed(() => cargandoAuxiliar.value
  || erroresListado.loading.value
  || hallazgosListado.loading.value
  || diagnosticosListado.loading.value
  || coberturaListado.loading.value);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const readinessOk = computed(() => {
  const r = readiness.value;
  if (!r) return true;
  if (typeof r.blocked === 'boolean') return !r.blocked;
  return true;
});

const opcionesRiesgo = Object.entries(RISK_LABELS).map(([value, label]) => ({ value, label }));
const opcionesEstadoError = Object.entries(ERROR_STATUS_LABELS).map(([value, label]) => ({ value, label }));

const columnasError: QTableColumn<ErrorEventRow>[] = [
  { name: 'riesgo', label: 'Riesgo', field: 'risk_class', align: 'left' },
  { name: 'domain', label: 'Dominio', field: (r) => r.domain || '—', align: 'left' },
  {
    name: 'mensaje',
    label: 'Error',
    field: (r) => [r.exception_type, r.file_path ? `${r.file_path}:${r.line_number ?? ''}` : '']
      .filter(Boolean).join(' · ') || '—',
    align: 'left',
  },
  { name: 'veces', label: 'Veces', field: (r) => r.occurrence_count ?? 1, align: 'right' },
  {
    name: 'ultima',
    label: 'Última vez',
    field: (r) => (r.last_seen_at ? formatDateTime(String(r.last_seen_at)) : '—'),
    align: 'left',
  },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'acciones', label: '', field: 'error_id', align: 'right' },
];

const columnasHallazgo: QTableColumn<SecurityFindingRow>[] = [
  { name: 'title', label: 'Hallazgo', field: (r) => r.vuln_id || r.cve_id || r.package || '—', align: 'left' },
  { name: 'severity', label: 'Severidad', field: (r) => r.severity_raw || '—', align: 'left' },
  { name: 'source', label: 'Fuente', field: (r) => r.source_tool || '—', align: 'left' },
  { name: 'status', label: 'Estado', field: (r) => ERROR_STATUS_LABELS[r.status] ?? r.status, align: 'left' },
  { name: 'acciones', label: '', field: 'finding_id', align: 'right' },
];

const columnasDiag: QTableColumn<DiagnosisRow>[] = [
  { name: 'asunto', label: 'Asunto', field: (r) => `${r.subject_type} ${r.subject_id}`.trim() || '—', align: 'left' },
  { name: 'domain', label: 'Dominio', field: (r) => r.domain || '—', align: 'left' },
  { name: 'riesgo', label: 'Riesgo', field: 'risk_class', align: 'left' },
  { name: 'estado', label: 'Estado', field: (r) => r.status || '—', align: 'left' },
  { name: 'confianza', label: 'Confianza', field: (r) => CONFIDENCE_LABELS[r.confidence] ?? (r.confidence || '—'), align: 'left' },
  { name: 'ia', label: 'IA', field: 'ai_assisted', align: 'center' },
  { name: 'creado', label: 'Creado', field: (r) => formatDateTime(r.created_at), align: 'left' },
  { name: 'acciones', label: '', field: 'run_id', align: 'right' },
];

const columnasCobertura: QTableColumn<CodeEvidenceRow>[] = [
  { name: 'path', label: 'Archivo', field: 'path', align: 'left' },
  { name: 'symbol', label: 'Símbolo', field: (r) => r.symbol || '—', align: 'left' },
  { name: 'lineas', label: 'Líneas', field: (r) => (r.line_start ? `${r.line_start}–${r.line_end}` : '—'), align: 'left' },
  { name: 'domain', label: 'Dominio', field: (r) => r.domain || '—', align: 'left' },
  { name: 'cobertura', label: 'Cobertura', field: 'coverage_state', align: 'left' },
  { name: 'refs', label: 'Refs', field: (r) => `${r.error_refs?.length ?? 0} err · ${r.security_refs?.length ?? 0} seg`, align: 'left' },
];

function coberturaColor(state: string): string {
  return { covered: 'positive', partial: 'warning', uncovered: 'negative', unknown: 'grey-6' }[state] ?? 'grey-6';
}
function tieneDetalle(v: unknown): boolean {
  return !!v && typeof v === 'object' && Object.keys(v).length > 0;
}
function pretty(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

async function recargar() {
  cargandoAuxiliar.value = true;
  try {
    const tareas: Promise<void>[] = [
      erroresListado.reload(),
      getReleaseReadiness()
        .then((r) => {
          readiness.value = r;
        })
        .catch(() => {
          readiness.value = null;
        }),
    ];
    if (puede('diagnostics.finding.read')) {
      tareas.push(
        hallazgosListado.reload(),
      );
    }
    if (puede('diagnostics.ai_control.read')) {
      tareas.push(
        getAiControl()
          .then((r) => {
            iaEncendida.value = Boolean(r.enabled);
          })
          .catch(() => undefined),
      );
    }
    if (puede('diagnostics.diagnose.read')) {
      tareas.push(
        diagnosticosListado.reload(),
      );
    }
    tareas.push(coberturaListado.reload());
    await Promise.all(tareas);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el diagnóstico.') });
  } finally {
    cargandoAuxiliar.value = false;
  }
}

async function toggleIA(valor: boolean) {
  try {
    await setAiControl(valor, valor ? 'encendido desde panel' : 'apagado desde panel');
    iaEncendida.value = valor;
    $q.notify({
      type: valor ? 'positive' : 'warning',
      message: valor ? 'IA encendida.' : 'IA APAGADA (kill switch).',
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cambiar el kill switch.') });
  }
}

const dlgDiag = ref(false);
const textoDiag = ref('');

async function diagnosticar(err: ErrorEventRow) {
  textoDiag.value = 'Corriendo diagnóstico determinista…';
  dlgDiag.value = true;
  try {
    const r = await diagnoseError(err.error_id);
    textoDiag.value = JSON.stringify(r, null, 2);
    if (puede('diagnostics.diagnose.read')) {
      void diagnosticosListado.reload();
    }
  } catch (e) {
    textoDiag.value = apiErrorMessage(e, 'No se pudo diagnosticar.');
  }
}

// ---- detalle de un diagnóstico + análisis IA ----
const dlgRun = ref(false);
const runSel = ref<DiagnosisRow | null>(null);
const analizandoIA = ref(false);

async function verDiagnostico(row: DiagnosisRow) {
  runSel.value = row;
  dlgRun.value = true;
  try {
    runSel.value = await getDiagnosis(row.run_id);
  } catch {
    /* noop: ya mostramos la fila de la lista */
  }
}

async function analizarIA() {
  if (!runSel.value) return;
  analizandoIA.value = true;
  try {
    runSel.value = await aiAnalyzeDiagnosis(runSel.value.run_id);
    $q.notify({ type: 'positive', message: 'Análisis IA completado.' });
    await recargar();
  } catch (e) {
    const status = (e as { response?: { status?: number } })?.response?.status;
    $q.notify({
      type: 'negative',
      message: status === 409 ? 'La IA está apagada (kill switch).' : apiErrorMessage(e, 'No se pudo analizar con IA.'),
    });
  } finally {
    analizandoIA.value = false;
  }
}

function triage(err: ErrorEventRow) {
  $q.dialog({
    title: `Triage del error #${err.error_id.slice(0, 8)}`,
    message: 'Decisión:',
    options: {
      type: 'radio',
      model: 'confirmed',
      items: [
        { label: 'Confirmado (es un bug real)', value: 'confirmed' },
        { label: 'Corregido', value: 'fixed' },
        { label: 'Riesgo aceptado', value: 'accepted_risk' },
        { label: 'Falso positivo', value: 'false_positive' },
      ],
    },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'primary', label: 'Aplicar' },
  }).onOk((decision: string) => {
    void (async () => {
      try {
        await triageError(err.error_id, decision);
        $q.notify({ type: 'positive', message: 'Triage aplicado.' });
        await recargar();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo aplicar.') });
      }
    })();
  });
}

function triageSeguridad(f: SecurityFindingRow) {
  $q.dialog({
    title: `Triage del hallazgo #${f.finding_id.slice(0, 8)}`,
    message: 'Decisión:',
    options: {
      type: 'radio',
      model: 'confirmed',
      items: [
        { label: 'Confirmado', value: 'confirmed' },
        { label: 'Corregido', value: 'fixed' },
        { label: 'Riesgo aceptado', value: 'accepted_risk' },
        { label: 'Falso positivo', value: 'false_positive' },
      ],
    },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'primary', label: 'Aplicar' },
  }).onOk((decision: string) => {
    void (async () => {
      try {
        await triageSecurityFinding(f.finding_id, decision);
        $q.notify({ type: 'positive', message: 'Triage aplicado.' });
        await recargar();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo aplicar.') });
      }
    })();
  });
}

onMounted(recargar);
</script>

<style scoped>
.dgx-readiness {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  padding: var(--app-space-3) var(--app-space-4);
  border-radius: var(--app-radius-md);
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  margin-bottom: var(--app-space-4);
  font-weight: 600;
  color: var(--app-text);
}

.dgx-readiness.is-block {
  border-color: var(--app-border-strong);
  color: var(--app-text);
}

.dgx-tabs {
  color: var(--app-text-muted);
}

.dgx-panels {
  background: transparent;
}

.dgx-filtros {
  display: flex;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}

.dgx-filtros__sel {
  width: 200px;
}

.dgx-acciones {
  white-space: nowrap;
}

.dgx-detalle {
  width: 680px;
}

.dgx-json {
  margin: 0;
  max-height: 60vh;
  overflow: auto;
  font-size: 0.75rem;
  color: var(--app-text);
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  padding: var(--app-space-3);
  white-space: pre-wrap;
}

.dgx-run {
  max-height: 64vh;
  overflow: auto;
}
.dgx-run__meta {
  font-size: 0.8rem;
  color: var(--app-text-muted);
  margin-bottom: var(--app-space-3);
}
.dgx-run__block {
  margin-bottom: var(--app-space-3);
  white-space: pre-wrap;
  color: var(--app-text);
  font-size: 0.9rem;
}
.dgx-run__h {
  font-weight: 700;
  color: var(--app-secondary);
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: 2px;
}
</style>
