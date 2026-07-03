<template>
  <q-page class="app-page">
    <header class="per-head">
      <div class="per-head__main">
        <BackButton to="/nomina" />
        <div>
          <div class="per-head__title">
            {{ periodo ? etiquetaPeriodo(periodo) : 'Período' }}
            <q-chip
              v-if="periodo"
              dense
              :color="statusColor(periodo.status)"
              text-color="white"
              :label="statusLabel(periodo.status)"
            />
          </div>
          <div class="per-head__subtitle" v-if="periodo">
            {{ periodo.start_date }} → {{ periodo.end_date }} · {{ periodo.working_days }} días ·
            tasa USD {{ periodo.exchange_rate_usd }}
          </div>
        </div>
      </div>
      <div class="row items-center q-gutter-xs">
        <q-btn flat no-caps icon="account_balance" label="INSS" :to="`/nomina/periodos/${periodId}/inss`">
          <q-tooltip>Régimen INSS del período: resolver CON/SIN INSS y clasificar planillas</q-tooltip>
        </q-btn>
        <q-btn flat no-caps icon="volunteer_activism" label="Complemento" :to="`/nomina/periodos/${periodId}/complemento`">
          <q-tooltip>Planilla de complemento de salario (convenio personal, bruto en recibo)</q-tooltip>
        </q-btn>
        <q-btn flat round icon="refresh" :loading="loading" aria-label="Actualizar" @click="reload" />
      </div>
    </header>

    <!-- Planillas del período -->
    <section class="per-section">
      <div class="per-section__head">
        <div class="per-section__title">Planillas</div>
        <q-btn unelevated no-caps color="primary" icon="post_add" label="Nueva planilla" @click="openNewSheet" />
      </div>

      <div class="per-sheets">
        <q-card
          v-for="s in sheets"
          :key="s.id"
          flat
          class="per-sheet"
          :class="{ 'per-sheet--active': s.id === sheetActiva?.id }"
          @click="seleccionarSheet(s)"
        >
          <q-card-section class="per-sheet__body">
            <div class="per-sheet__name">
              {{ s.sheet_name }}
              <q-chip dense :color="sheetColor(s.status)" text-color="white" :label="sheetLabel(s.status)" />
            </div>
            <div class="per-sheet__meta">
              {{ s.has_inss ? 'Con INSS' : 'Sin INSS' }} · {{ s.entry_count }} trabajadores
            </div>
            <div class="per-sheet__actions" @click.stop>
              <q-btn flat dense no-caps size="sm" icon="agriculture" label="Aplicar asistencia" :loading="acting === `apply-${s.id}`" @click="doApply(s)">
                <q-tooltip>Trae los días trabajados desde la asistencia de campo aprobada</q-tooltip>
              </q-btn>
              <q-btn flat dense no-caps size="sm" icon="calculate" label="Calcular" :loading="acting === `compute-${s.id}`" @click="doAction(s, 'compute')" />
              <q-btn
                v-if="s.status === 'DRAFT'"
                flat dense no-caps size="sm" icon="send" label="Enviar"
                :loading="acting === `submit-${s.id}`"
                @click="doAction(s, 'submit')"
              />
              <q-btn
                v-if="s.status === 'SUBMITTED' || s.status === 'REVIEWED'"
                flat dense no-caps size="sm" color="secondary" icon="task_alt" label="Aprobar"
                :loading="acting === `approve-${s.id}`"
                @click="doAction(s, 'approve')"
              />
              <q-btn flat dense no-caps size="sm" icon="grid_on" label="XLSX" @click="doDownload(s, 'xlsx')" />
              <q-btn flat dense no-caps size="sm" icon="picture_as_pdf" label="PDF" @click="doDownload(s, 'pdf')" />
            </div>
          </q-card-section>
        </q-card>

        <div v-if="!loading && sheets.length === 0" class="per-empty">
          Sin planillas. Creá una (p. ej. «Planilla general») y aplicale la asistencia del campo.
        </div>
      </div>
    </section>

    <!-- Entradas de la planilla seleccionada -->
    <section v-if="sheetActiva" class="per-section">
      <div class="per-section__head">
        <div class="per-section__title">
          Trabajadores en «{{ sheetActiva.sheet_name }}»
          <span class="per-muted">({{ paginacionEntradas.rowsNumber }})</span>
        </div>
        <div class="row items-center q-gutter-sm">
          <q-input v-model="busqueda" outlined dense clearable debounce="250" placeholder="Buscar…" style="width: 220px" @update:model-value="cargarEntradas">
            <template #prepend><q-icon name="search" size="18px" /></template>
          </q-input>
          <q-btn unelevated no-caps color="primary" icon="person_add" label="Agregar" @click="openNewEntry" />
        </div>
      </div>

      <q-table
        v-model:pagination="paginacionEntradas"
        class="app-table"
        :rows="entries"
        :columns="entryCols"
        row-key="id"
        flat
        dense
        :loading="loadingEntries"
        :rows-per-page-options="[10, 25, 50, 100]"
        no-data-label="Sin trabajadores: aplicá la asistencia de campo o agregalos manualmente."
        @request="onRequestEntradas"
      >
        <template #body-cell-no="props">
          <!-- Numeración corrida entre páginas (offset + posición en la página) -->
          <q-td :props="props" class="text-center per-muted">
            {{ (paginacionEntradas.page - 1) * paginacionEntradas.rowsPerPage + props.rowIndex + 1 }}
          </q-td>
        </template>
        <template #body-cell-acciones="props">
          <q-td :props="props" class="per-row-actions">
            <template v-if="planillaEditable">
              <q-btn flat dense round size="sm" icon="event_available" aria-label="Asistencia día por día" @click="openAttendance(props.row)">
                <q-tooltip>Asistencia día por día + alimentos (planilla fiel)</q-tooltip>
              </q-btn>
              <q-btn flat dense round size="sm" icon="edit" aria-label="Editar línea" @click="openEditEntry(props.row)">
                <q-tooltip>Editar (horas extra, otros ingresos, deducciones)</q-tooltip>
              </q-btn>
              <q-btn flat dense round size="sm" color="negative" icon="delete_outline" aria-label="Quitar línea" @click="confirmDelete(props.row)">
                <q-tooltip>Quitar de la planilla</q-tooltip>
              </q-btn>
            </template>
            <q-icon v-else name="lock" size="16px" class="per-muted">
              <q-tooltip>La planilla ya no es borrador</q-tooltip>
            </q-icon>
          </q-td>
        </template>
      </q-table>
    </section>

    <!-- Diálogo: nueva planilla -->
    <q-dialog v-model="newSheetOpen">
      <q-card class="per-dialog">
        <q-card-section class="text-h6">Nueva planilla</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="sheetForm.sheet_name" outlined dense autofocus label="Nombre (p. ej. Planilla general)" />
          <q-toggle v-model="sheetForm.has_inss" label="Planilla con INSS" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Crear" :loading="saving" :disable="!sheetForm.sheet_name.trim()" @click="doCreateSheet" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: agregar trabajador (del expediente RH o manual) -->
    <q-dialog v-model="newEntryOpen">
      <q-card class="per-dialog">
        <q-card-section>
          <div class="text-h6">Agregar trabajador a la planilla</div>
          <div class="per-muted">El cálculo (INSS, IR, provisiones) se hace solo al guardar.</div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-btn-toggle
            v-model="entryMode"
            no-caps
            unelevated
            toggle-color="primary"
            :options="[
              { label: 'Del expediente (RH)', value: 'expediente' },
              { label: 'Manual (sin expediente)', value: 'manual' },
            ]"
          />
        </q-card-section>

        <!-- Del expediente: se elige al trabajador y todo se llena solo -->
        <q-card-section v-if="entryMode === 'expediente'" class="app-form">
          <q-select
            v-model="selectedEmployee"
            outlined
            dense
            autofocus
            use-input
            input-debounce="0"
            label="Buscar trabajador *"
            hint="Solo personal activo de Recursos Humanos"
            :options="employeeOptions"
            :loading="loadingEmployees"
            option-label="label"
            no-error-icon
            @filter="filterEmployees"
          >
            <template #no-option>
              <q-item><q-item-section class="per-muted">Sin coincidencias. ¿Ya lo creaste en Recursos Humanos?</q-item-section></q-item>
            </template>
          </q-select>

          <div v-if="selectedEmployee" class="per-expediente">
            <div class="per-expediente__row"><span>Cédula</span><b>{{ selectedEmployee.emp.cedula || '—' }}</b></div>
            <div class="per-expediente__row"><span>No. INSS</span><b>{{ selectedEmployee.emp.inss_number || '—' }}</b></div>
            <div class="per-expediente__row"><span>Género</span><b>{{ selectedEmployee.emp.gender === 'F' ? 'Femenino' : selectedEmployee.emp.gender === 'M' ? 'Masculino' : '—' }}</b></div>
            <div class="per-expediente__row"><span>Cargo</span><b>{{ selectedEmployee.emp.active_assignments.map((a) => a.position_name).join(' / ') || '—' }}</b></div>
            <div class="per-expediente__row">
              <span>Salario</span>
              <b>{{ selectedEmployee.emp.salary_type === 'DAILY' ? `Jornal C$ ${selectedEmployee.emp.daily_rate_nio}` : `Mensual C$ ${selectedEmployee.emp.monthly_salary_nio}` }}</b>
            </div>
            <q-banner v-if="salarioExpedienteEsCero" dense rounded class="per-banner-warn q-mt-sm">
              Este trabajador no tiene salario en su expediente: la línea saldrá en C$ 0.00.
              Completalo en Recursos Humanos → su perfil → Datos de planilla.
            </q-banner>
          </div>

          <div class="per-form__row">
            <q-input v-model.number="entryForm.days_in_period" outlined dense type="number" label="Días del período" />
            <q-input v-model="entryForm.days_worked" outlined dense type="number" step="0.5" label="Días trabajados" />
          </div>
        </q-card-section>

        <!-- Manual: la excepción (gente sin expediente, p. ej. eventual de un día) -->
        <q-card-section v-else class="app-form">
          <q-input v-model="entryForm.full_name" outlined dense autofocus label="Nombre completo *" />
          <div class="per-form__row">
            <q-input v-model="entryForm.cedula" outlined dense label="Cédula" />
            <q-input v-model="entryForm.cargo" outlined dense label="Cargo" />
          </div>
          <div class="per-form__row">
            <q-select
              v-model="entryForm.salary_type"
              outlined dense emit-value map-options label="Tipo de salario"
              :options="[
                { label: 'Por día (jornal)', value: 'DAILY' },
                { label: 'Mensual', value: 'MONTHLY' },
              ]"
            />
            <q-input v-model="entryForm.base_salary_nio" outlined dense type="number" step="0.01" :label="entryForm.salary_type === 'DAILY' ? 'Jornal diario C$' : 'Salario mensual C$'" />
          </div>
          <div class="per-form__row">
            <q-input v-model.number="entryForm.days_in_period" outlined dense type="number" label="Días del período" />
            <q-input v-model="entryForm.days_worked" outlined dense type="number" step="0.5" label="Días trabajados" />
          </div>
          <q-toggle v-model="entryForm.has_inss" label="Cotiza INSS" />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Agregar y calcular"
            :loading="saving"
            :disable="entryMode === 'expediente' ? !selectedEmployee : !entryForm.full_name.trim()"
            @click="doCreateEntry"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: editar línea (asistencia, horas extra, otros ingresos, deducciones) -->
    <q-dialog v-model="editEntryOpen">
      <q-card class="per-dialog">
        <q-card-section>
          <div class="text-h6">Editar línea de planilla</div>
          <div class="per-muted" v-if="editingEntry">
            {{ editingEntry.full_name }}<span v-if="editingEntry.cedula"> · {{ editingEntry.cedula }}</span>
          </div>
          <div class="per-muted">El cálculo (INSS, IR, neto) se rehace al guardar.</div>
        </q-card-section>

        <q-card-section class="app-form">
          <div class="per-form__subtitle">Asistencia</div>
          <div class="per-form__row">
            <q-input v-model.number="editForm.days_in_period" outlined dense type="number" label="Días del período" />
            <q-input v-model="editForm.days_worked" outlined dense type="number" step="0.5" label="Días trabajados" />
          </div>

          <div class="per-form__subtitle">Ingresos adicionales</div>
          <div class="per-form__row">
            <q-input v-model="editForm.overtime_hours" outlined dense type="number" step="0.5" min="0" label="Horas extra" hint="Se pagan al doble de la hora" />
            <q-input v-model="editForm.other_income" outlined dense type="number" step="0.01" min="0" label="Otros ingresos (C$)" hint="Viáticos, bonos" />
          </div>
          <div v-if="esJornaleroEnEdicion" class="per-form__row per-form__row--3">
            <q-input v-model.number="editForm.sunday_worked_days" outlined dense type="number" min="0" label="Domingos laborados" />
            <q-input v-model="editForm.seventh_day_days" outlined dense type="number" step="0.5" min="0" label="Séptimo día" />
            <q-input v-model="editForm.holiday_worked_days" outlined dense type="number" step="0.5" min="0" label="Feriados laborados" />
          </div>

          <div class="per-form__subtitle">Deducciones manuales</div>
          <div class="per-form__row per-form__row--3">
            <q-input v-model="editForm.advance_deduction" outlined dense type="number" step="0.01" min="0" label="Adelanto finca (C$)" />
            <q-input v-model="editForm.food_deduction" outlined dense type="number" step="0.01" min="0" label="Alimentación (C$)" />
            <q-input v-model="editForm.other_deductions" outlined dense type="number" step="0.01" min="0" label="Otras deducciones (C$)" />
          </div>
          <div class="per-muted per-form__note">
            Crédito comisariato y abono de préstamos se llenan solos por integración.
          </div>

          <q-input v-model="editForm.notes" outlined dense type="textarea" autogrow label="Notas" />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Guardar y recalcular" :loading="saving" @click="doUpdateEntry" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: captura de asistencia DÍA-POR-DÍA (planilla fiel al Excel) -->
    <q-dialog v-model="attOpen">
      <q-card class="att-dialog">
        <q-card-section class="att-head">
          <div class="text-h6">Asistencia día por día</div>
          <div class="per-muted">{{ attEntry?.full_name }} — {{ periodo?.start_date }} → {{ periodo?.end_date }}</div>
          <div class="att-legend">
            <span v-for="m in MARK_OPTS" :key="m.code" class="att-legend__item">
              <b :style="{ color: m.color }">{{ m.code }}</b> {{ m.label }}
            </span>
          </div>
        </q-card-section>
        <q-card-section class="att-grid">
          <div v-for="d in periodDays" :key="d.iso" class="att-day" :class="{ 'att-day--sun': d.sunday }">
            <div class="att-day__lbl">{{ d.day }} <small>{{ d.dow }}</small></div>
            <q-select
              :model-value="attMarks[d.iso] || ''"
              @update:model-value="(v) => setMark(d.iso, v)"
              :options="MARK_OPTIONS"
              emit-value
              map-options
              dense
              outlined
              options-dense
              class="att-day__sel"
            />
          </div>
        </q-card-section>
        <q-card-section class="att-foot">
          <q-input v-model="attAlimentos" outlined dense type="number" min="0" label="Alimentos (alimentación de la empresa, suma al neto) C$" style="max-width: 360px" />
          <div class="per-muted att-sum">
            Presentes: <b>{{ attResumen.presentes }}</b> · medios: <b>{{ attResumen.medios }}</b> · ausencias: <b>{{ attResumen.ausencias }}</b>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Guardar y recalcular" :loading="attSaving" @click="doSaveAttendance" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import BackButton from 'src/components/BackButton.vue';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import {
  applyFieldAttendance,
  createEntry,
  createSheet,
  deleteEntry,
  downloadPlanilla,
  listEntriesPage,
  listPeriods,
  listSheets,
  setDailyAttendance,
  sheetAction,
  updateEntry,
  type EntryUpdateInput,
  type PayrollEntry,
  type PayrollPeriod,
  type PayrollSheet,
} from 'src/modules/nomina/api';
import { listEmployees, type EmployeeRow } from 'src/modules/hr/api';

const $q = useQuasar();
const route = useRoute();
const periodId = computed(() => Number(route.params.id));

const loading = ref(false);
const saving = ref(false);
const acting = ref<string | null>(null);

const periodo = ref<PayrollPeriod | null>(null);
const sheets = ref<PayrollSheet[]>([]);
const sheetActiva = ref<PayrollSheet | null>(null);
const busqueda = ref('');

// Trabajadores de la planilla: paginación server-side (la cuadrilla crece sin
// límite en temporada). auto:false — solo se consulta cuando hay planilla
// seleccionada (mismo patrón que KardexPage).
const {
  rows: entries,
  loading: loadingEntries,
  pagination: paginacionEntradas,
  onRequest: onRequestEntradas,
  reload: recargarEntradas,
} = useListadoServer<PayrollEntry>(
  (page) =>
    listEntriesPage(periodId.value, sheetActiva.value?.id as number, busqueda.value || '', page),
  { errorMessage: 'No se pudieron cargar los trabajadores.', auto: false, rowsPerPage: 50 },
);

/** Re-consulta desde la página 1; no hace nada si aún no hay planilla elegida. */
async function cargarEntradas() {
  if (!sheetActiva.value) return;
  await recargarEntradas();
}

// --- Captura de asistencia DÍA-POR-DÍA (planilla fiel al Excel) ---
const MARK_OPTS = [
  { code: 'P', label: 'Presente', color: '#16a34a' },
  { code: 'M', label: 'Medio día', color: '#d97706' },
  { code: 'D', label: 'Domingo lab.', color: '#0d9488' },
  { code: 'S', label: 'Subsidio', color: '#2563eb' },
  { code: 'V', label: 'Vacación', color: '#7c3aed' },
  { code: 'F', label: 'Feriado', color: '#6b7280' },
  { code: 'A', label: 'Ausente', color: '#dc2626' },
];
const MARK_OPTIONS = [
  { label: '—', value: '' },
  ...MARK_OPTS.map((m) => ({ label: `${m.code} · ${m.label}`, value: m.code })),
];
const DOW_ES = ['L', 'M', 'M', 'J', 'V', 'S', 'D']; // lunes..domingo

const attOpen = ref(false);
const attEntry = ref<PayrollEntry | null>(null);
const attMarks = reactive<Record<string, string>>({});
const attAlimentos = ref('0');
const attSaving = ref(false);

const periodDays = computed(() => {
  const out: { iso: string; day: number; dow: string; sunday: boolean }[] = [];
  if (!periodo.value) return out;
  const start = new Date(periodo.value.start_date + 'T00:00:00');
  const end = new Date(periodo.value.end_date + 'T00:00:00');
  for (const d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const jsDow = d.getDay(); // 0=domingo..6=sábado
    out.push({
      iso: d.toLocaleDateString('en-CA'), // YYYY-MM-DD local
      day: d.getDate(),
      dow: DOW_ES[(jsDow + 6) % 7] ?? '',
      sunday: jsDow === 0,
    });
  }
  return out;
});
const attResumen = computed(() => {
  let presentes = 0;
  let medios = 0;
  let ausencias = 0;
  for (const c of Object.values(attMarks)) {
    if (c === 'P' || c === 'D') presentes += 1;
    else if (c === 'M') medios += 1;
    else if (c === 'A') ausencias += 1;
  }
  return { presentes, medios, ausencias };
});

function openAttendance(row: PayrollEntry) {
  attEntry.value = row;
  for (const k of Object.keys(attMarks)) delete attMarks[k];
  Object.assign(attMarks, row.daily_attendance || {});
  attAlimentos.value = row.alimentacion_amount || '0';
  attOpen.value = true;
}
function setMark(iso: string, code: string) {
  if (code) attMarks[iso] = code;
  else delete attMarks[iso];
}
async function doSaveAttendance() {
  if (!attEntry.value || !sheetActiva.value) return;
  attSaving.value = true;
  try {
    await setDailyAttendance(periodId.value, sheetActiva.value.id, attEntry.value.id, { ...attMarks });
    const ali = Number(attAlimentos.value || 0);
    if (ali !== Number(attEntry.value.alimentacion_amount || 0)) {
      await updateEntry(periodId.value, sheetActiva.value.id, attEntry.value.id, {
        alimentacion_amount: ali.toFixed(2),
      });
    }
    attOpen.value = false;
    $q.notify({ type: 'positive', message: 'Asistencia y alimentos guardados.' });
    await cargarEntradas();
  } catch {
    $q.notify({ type: 'negative', message: 'No se pudo guardar la asistencia.' });
  } finally {
    attSaving.value = false;
  }
}

const MESES_ES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
];

const PERIOD_STATUS: Record<string, { label: string; color: string }> = {
  DRAFT: { label: 'Borrador', color: 'grey-7' },
  IN_REVIEW: { label: 'En revisión', color: 'info' },
  APPROVED: { label: 'Aprobado', color: 'secondary' },
  PAID: { label: 'Pagado', color: 'positive' },
  CLOSED: { label: 'Cerrado', color: 'primary' },
};

const SHEET_STATUS: Record<string, { label: string; color: string }> = {
  DRAFT: { label: 'Borrador', color: 'grey-7' },
  SUBMITTED: { label: 'Enviada', color: 'info' },
  REVIEWED: { label: 'Revisada', color: 'warning' },
  APPROVED: { label: 'Aprobada', color: 'positive' },
  REJECTED: { label: 'Rechazada', color: 'negative' },
};

const TIPOS: Record<string, string> = {
  FIRST_HALF: 'Primera quincena',
  SECOND_HALF: 'Segunda quincena',
  CATORCENA: 'Catorcena',
  MONTHLY: 'Mensual',
};

function etiquetaPeriodo(p: PayrollPeriod): string {
  return `${MESES_ES[p.month - 1]} ${p.year} — ${TIPOS[p.period_type] ?? p.period_type}`;
}

const statusLabel = (s: string) => PERIOD_STATUS[s]?.label ?? s;
const statusColor = (s: string) => PERIOD_STATUS[s]?.color ?? 'grey-7';
const sheetLabel = (s: string) => SHEET_STATUS[s]?.label ?? s;
const sheetColor = (s: string) => SHEET_STATUS[s]?.color ?? 'grey-7';

function money(v: string): string {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString('es-NI', { minimumFractionDigits: 2 }) : v;
}

function totalBasico(r: PayrollEntry): string {
  return money(
    String(Number(r.quincenal_salary || 0) + Number(r.seventh_day_amount || 0) + Number(r.holiday_amount || 0)),
  );
}
// Total Devengado (tras retención de ley) = devengado − INSS − IR. ALIMENTOS suma DESPUÉS (Total a Pagar).
function totalDevengadoNeto(r: PayrollEntry): string {
  return money(String(Number(r.total_devengado || 0) - Number(r.inss_laboral || 0) - Number(r.ir_amount || 0)));
}

// SIN INSS: layout previo (segunda pasada para hacerlo fiel también).
// SIN INSS: FIEL al Excel "COMISARIATO SIN INSS" (planilla_export._SIN_INSS_COLUMNS) — SIN grilla de
// días y SIN columnas de INSS/IR ni costos patronales (en SIN INSS el INSS es 0 y la patronal no
// aplica); con ALIMENTACIÓN (suma al neto) y Recibí Conforme. Números legales (el IR se resta aunque
// no tenga columna). NO lleva Cédula/No.INSS ni cobros internos (eso es lógica del CO-PA).
// Sin `sortable`: con paginación server-side el orden lo fija el backend
// (siempre por nombre; el endpoint no acepta `ordering`).
const entryColsSin: QTableColumn<PayrollEntry>[] = [
  { name: 'no', label: 'No.', field: () => '', align: 'center' },
  { name: 'full_name', label: 'Nombres y Apellidos', field: 'full_name', align: 'left' },
  { name: 'gender', label: 'Género', field: 'gender', align: 'center' },
  { name: 'cargo', label: 'Cargo', field: 'cargo', align: 'left' },
  { name: 'daily_rate_nio', label: 'Salario Diario', field: (r) => money(r.daily_rate_nio), align: 'right' },
  { name: 'base_salary_nio', label: 'Salario Mensual', field: (r) => money(r.base_salary_nio), align: 'right' },
  { name: 'quincenal_salary', label: 'Salario Quincenal', field: (r) => money(r.quincenal_salary), align: 'right' },
  { name: 'days_worked', label: 'Días Laborados', field: 'days_worked', align: 'right' },
  { name: 'total_basico', label: 'Total Básico', field: totalBasico, align: 'right' },
  { name: 'vacation_provision', label: 'Vacaciones', field: (r) => money(r.vacation_provision), align: 'right' },
  { name: 'thirteenth_month_provision', label: '13vo Mes', field: (r) => money(r.thirteenth_month_provision), align: 'right' },
  { name: 'total_income', label: 'Total Ingresos', field: (r) => money(r.total_income), align: 'right' },
  { name: 'alimentacion_amount', label: 'Alimentación', field: (r) => money(r.alimentacion_amount), align: 'right' },
  { name: 'net_to_pay', label: 'Total a Pagar', field: (r) => money(r.net_to_pay), align: 'right' },
  { name: 'recibi_conforme', label: 'Recibí Conforme', field: () => '', align: 'center' },
  { name: 'acciones', label: '', field: () => '', align: 'center' },
];

// CON INSS: FIEL al documento (planilla_export._con_inss_columns): identidad + grilla de días +
// ingresos legales + INSS/IR + Total Devengado + ALIMENTOS (suma) + Total a Pagar + Recibe Conforme.
// NO lleva cobros internos (comisariato/préstamo/adelanto) ni costos patronales — no van en el documento.
const entryColsCon = computed<QTableColumn<PayrollEntry>[]>(() => [
  { name: 'no', label: 'No.', field: () => '', align: 'center' },
  { name: 'base_salary_nio', label: 'Salario', field: (r) => money(r.base_salary_nio), align: 'right' },
  { name: 'full_name', label: 'Nombres y Apellidos', field: 'full_name', align: 'left' },
  { name: 'gender', label: 'Género', field: 'gender', align: 'center' },
  { name: 'daily_rate_nio', label: 'Salario Diario', field: (r) => money(r.daily_rate_nio), align: 'right' },
  { name: 'cargo', label: 'Actividad', field: 'cargo', align: 'left' },
  ...periodDays.value.map((d) => ({
    name: `day_${d.iso}`,
    label: `${d.day} ${d.dow}`,
    field: (r: PayrollEntry) => r.daily_attendance?.[d.iso] || '',
    align: 'center' as const,
    headerClasses: d.sunday ? 'per-day-sun' : '',
    classes: d.sunday ? 'per-day-sun' : '',
  })),
  { name: 'suma_dias', label: 'Suma Días', field: (r) => String(Number(r.days_worked || 0) + Number(r.seventh_day_days || 0)), align: 'right' },
  { name: 'dias_lab', label: 'Días Lab', field: 'days_worked', align: 'right' },
  { name: 'quincenal_salary', label: 'Salario Básico', field: (r) => money(r.quincenal_salary), align: 'right' },
  { name: 'seventh_day_amount', label: 'Sept Día', field: (r) => money(r.seventh_day_amount), align: 'right' },
  { name: 'total_basico', label: 'TOTAL', field: totalBasico, align: 'right' },
  { name: 'vacation_provision', label: 'Vacaciones', field: (r) => money(r.vacation_provision), align: 'right' },
  { name: 'thirteenth_month_provision', label: '13vo Mes', field: (r) => money(r.thirteenth_month_provision), align: 'right' },
  { name: 'total_income', label: 'Total Ingresos', field: (r) => money(r.total_income), align: 'right' },
  { name: 'inss_laboral', label: 'INSS', field: (r) => money(r.inss_laboral), align: 'right' },
  { name: 'ir_amount', label: 'IR', field: (r) => money(r.ir_amount), align: 'right' },
  { name: 'total_devengado_neto', label: 'Total Devengado', field: totalDevengadoNeto, align: 'right' },
  { name: 'alimentacion_amount', label: 'Alimentos', field: (r) => money(r.alimentacion_amount), align: 'right' },
  { name: 'net_to_pay', label: 'Total a Pagar', field: (r) => money(r.net_to_pay), align: 'right' },
  { name: 'recibi_conforme', label: 'Recibe Conforme', field: () => '', align: 'center' },
  { name: 'acciones', label: '', field: () => '', align: 'center' },
]);

const entryCols = computed<QTableColumn<PayrollEntry>[]>(() =>
  sheetActiva.value?.has_inss ? entryColsCon.value : entryColsSin,
);

// Una planilla en borrador todavía se puede ajustar línea por línea; ya enviada/aprobada es estable.
const planillaEditable = computed(() => sheetActiva.value?.status === 'DRAFT');

async function reload() {
  loading.value = true;
  try {
    const [allPeriods, sheetRows] = await Promise.all([listPeriods(), listSheets(periodId.value)]);
    periodo.value = allPeriods.find((p) => p.id === periodId.value) ?? null;
    sheets.value = sheetRows;
    if (sheetRows.length && !sheetActiva.value) {
      sheetActiva.value = sheetRows[0] ?? null;
    } else if (sheetActiva.value) {
      sheetActiva.value = sheetRows.find((s) => s.id === sheetActiva.value?.id) ?? sheetRows[0] ?? null;
    }
    if (sheetActiva.value) await cargarEntradas();
  } catch {
    $q.notify({ type: 'negative', message: 'No se pudo cargar el período.' });
  } finally {
    loading.value = false;
  }
}

function seleccionarSheet(s: PayrollSheet) {
  sheetActiva.value = s;
  void cargarEntradas();
}

// --- nueva planilla ---
const newSheetOpen = ref(false);
const sheetForm = reactive({ sheet_name: '', has_inss: true });

function openNewSheet() {
  sheetForm.sheet_name = sheets.value.length === 0 ? 'Planilla general' : '';
  sheetForm.has_inss = true;
  newSheetOpen.value = true;
}

async function doCreateSheet() {
  saving.value = true;
  try {
    const created = await createSheet(periodId.value, {
      sheet_name: sheetForm.sheet_name.trim(),
      has_inss: sheetForm.has_inss,
    });
    newSheetOpen.value = false;
    sheetActiva.value = created;
    $q.notify({ type: 'positive', message: 'Planilla creada.' });
    await reload();
  } catch {
    $q.notify({ type: 'negative', message: 'No se pudo crear la planilla.' });
  } finally {
    saving.value = false;
  }
}

// --- acciones de planilla ---
async function doAction(s: PayrollSheet, action: 'submit' | 'approve' | 'compute') {
  acting.value = `${action}-${s.id}`;
  try {
    const result = await sheetAction(periodId.value, s.id, action);
    const msgs = {
      submit: 'Planilla enviada a revisión.',
      approve: 'Planilla aprobada.',
      compute: `Cálculo hecho: ${result.computed ?? 0} líneas.`,
    };
    $q.notify({ type: 'positive', message: msgs[action] });
    await reload();
  } catch (e) {
    const err = e as { response?: { data?: { detail?: string } } };
    $q.notify({ type: 'negative', message: err.response?.data?.detail || 'No se pudo completar la acción.' });
  } finally {
    acting.value = null;
  }
}

async function doApply(s: PayrollSheet) {
  acting.value = `apply-${s.id}`;
  try {
    await applyFieldAttendance(s.id);
    $q.notify({ type: 'positive', message: 'Asistencia de campo aplicada a la planilla.' });
    await reload();
  } catch (e) {
    const err = e as { response?: { data?: { detail?: string } } };
    $q.notify({
      type: 'negative',
      message:
        err.response?.data?.detail ||
        'No se pudo aplicar (la asistencia del período debe estar consolidada y aprobada).',
    });
  } finally {
    acting.value = null;
  }
}

async function doDownload(s: PayrollSheet, format: 'xlsx' | 'pdf') {
  try {
    await downloadPlanilla(periodId.value, s.id, format);
  } catch {
    $q.notify({ type: 'negative', message: `No se pudo descargar el ${format.toUpperCase()}.` });
  }
}

// --- agregar trabajador manual ---
const newEntryOpen = ref(false);
const entryForm = reactive<{
  full_name: string;
  cedula: string;
  cargo: string;
  has_inss: boolean;
  salary_type: 'DAILY' | 'MONTHLY';
  base_salary_nio: string;
  days_in_period: number;
  days_worked: string;
}>({
  full_name: '',
  cedula: '',
  cargo: '',
  has_inss: true,
  salary_type: 'DAILY',
  base_salary_nio: '',
  days_in_period: 15,
  days_worked: '15',
});

// --- Selector del expediente RH (la fuente normal de trabajadores) ----------
interface EmployeeOption {
  label: string;
  emp: EmployeeRow;
}

const entryMode = ref<'expediente' | 'manual'>('expediente');
const selectedEmployee = ref<EmployeeOption | null>(null);
const loadingEmployees = ref(false);
const allEmployees = ref<EmployeeOption[]>([]);
const employeeOptions = ref<EmployeeOption[]>([]);

const salarioExpedienteEsCero = computed(() => {
  const emp = selectedEmployee.value?.emp;
  if (!emp) return false;
  const monto = emp.salary_type === 'DAILY' ? emp.daily_rate_nio : emp.monthly_salary_nio;
  return !Number(monto);
});

async function loadEmployeesOnce() {
  if (allEmployees.value.length > 0 || loadingEmployees.value) return;
  loadingEmployees.value = true;
  try {
    const rows = await listEmployees();
    allEmployees.value = rows
      .filter((e) => e.is_active && e.employment_status === 'ACTIVO')
      .map((e) => ({
        label: `${e.first_name} ${e.last_name}`.trim() + (e.employee_code ? ` (${e.employee_code})` : ''),
        emp: e,
      }));
    employeeOptions.value = allEmployees.value;
  } catch {
    $q.notify({
      type: 'warning',
      message: 'No se pudo cargar el personal de RH; podés agregar en modo manual.',
    });
    entryMode.value = 'manual';
  } finally {
    loadingEmployees.value = false;
  }
}

function filterEmployees(input: string, update: (fn: () => void) => void) {
  update(() => {
    const q = input.trim().toLowerCase();
    employeeOptions.value = !q
      ? allEmployees.value
      : allEmployees.value.filter(
          (o) => o.label.toLowerCase().includes(q) || o.emp.cedula.toLowerCase().includes(q),
        );
  });
}

function openNewEntry() {
  entryMode.value = 'expediente';
  selectedEmployee.value = null;
  entryForm.full_name = '';
  entryForm.cedula = '';
  entryForm.cargo = '';
  entryForm.has_inss = true;
  entryForm.salary_type = 'DAILY';
  entryForm.base_salary_nio = '';
  entryForm.days_in_period = periodo.value?.working_days ?? 15;
  entryForm.days_worked = String(periodo.value?.working_days ?? 15);
  newEntryOpen.value = true;
  void loadEmployeesOnce();
}

async function doCreateEntry() {
  if (!sheetActiva.value) return;
  saving.value = true;
  try {
    if (entryMode.value === 'expediente') {
      if (!selectedEmployee.value) return;
      // El backend copia del expediente: cédula, INSS, género, cargo, salario y
      // resuelve si cotiza INSS por su afiliación vigente.
      await createEntry(periodId.value, sheetActiva.value.id, {
        employee_id: selectedEmployee.value.emp.id,
        payment_frequency: periodo.value?.period_type ?? 'FIRST_HALF',
        days_in_period: entryForm.days_in_period,
        days_worked: entryForm.days_worked || '0',
      });
    } else {
      await createEntry(periodId.value, sheetActiva.value.id, {
        full_name: entryForm.full_name.trim(),
        cedula: entryForm.cedula.trim(),
        cargo: entryForm.cargo.trim(),
        has_inss: entryForm.has_inss,
        salary_type: entryForm.salary_type,
        payment_frequency: periodo.value?.period_type ?? 'FIRST_HALF',
        // El campo del form es "Jornal diario" para DAILY y "Salario mensual" para MONTHLY:
        // cada uno viaja por su casilla del contrato (el backend convierte el jornal).
        ...(entryForm.salary_type === 'DAILY'
          ? { daily_rate_nio: entryForm.base_salary_nio || '0' }
          : { base_salary_nio: entryForm.base_salary_nio || '0' }),
        days_in_period: entryForm.days_in_period,
        days_worked: entryForm.days_worked || '0',
      });
    }
    newEntryOpen.value = false;
    $q.notify({ type: 'positive', message: 'Trabajador agregado y calculado.' });
    await reload();
  } catch (e) {
    const err = e as { response?: { data?: Record<string, unknown> } };
    const detail = err.response?.data ? JSON.stringify(err.response.data).slice(0, 140) : '';
    $q.notify({ type: 'negative', message: detail || 'No se pudo agregar.' });
  } finally {
    saving.value = false;
  }
}

// --- editar / quitar una línea (planilla en borrador) ---
const editEntryOpen = ref(false);
const editingEntry = ref<PayrollEntry | null>(null);
const editForm = reactive<{
  days_in_period: number;
  days_worked: string;
  overtime_hours: string;
  sunday_worked_days: number;
  seventh_day_days: string;
  holiday_worked_days: string;
  other_income: string;
  advance_deduction: string;
  food_deduction: string;
  other_deductions: string;
  notes: string;
}>({
  days_in_period: 15,
  days_worked: '0',
  overtime_hours: '0',
  sunday_worked_days: 0,
  seventh_day_days: '0',
  holiday_worked_days: '0',
  other_income: '0',
  advance_deduction: '0',
  food_deduction: '0',
  other_deductions: '0',
  notes: '',
});

const esJornaleroEnEdicion = computed(() => editingEntry.value?.salary_type === 'DAILY');

function openEditEntry(row: PayrollEntry) {
  editingEntry.value = row;
  editForm.days_in_period = row.days_in_period;
  editForm.days_worked = row.days_worked;
  editForm.overtime_hours = row.overtime_hours;
  editForm.sunday_worked_days = row.sunday_worked_days;
  editForm.seventh_day_days = row.seventh_day_days;
  editForm.holiday_worked_days = row.holiday_worked_days;
  editForm.other_income = row.other_income;
  editForm.advance_deduction = row.advance_deduction;
  editForm.food_deduction = row.food_deduction;
  editForm.other_deductions = row.other_deductions;
  editForm.notes = row.notes;
  editEntryOpen.value = true;
}

async function doUpdateEntry() {
  if (!sheetActiva.value || !editingEntry.value) return;
  saving.value = true;
  try {
    const payload: EntryUpdateInput = {
      days_in_period: editForm.days_in_period,
      days_worked: editForm.days_worked || '0',
      overtime_hours: editForm.overtime_hours || '0',
      other_income: editForm.other_income || '0',
      advance_deduction: editForm.advance_deduction || '0',
      food_deduction: editForm.food_deduction || '0',
      other_deductions: editForm.other_deductions || '0',
      notes: editForm.notes,
      // Domingos/séptimo/feriados solo aplican a jornaleros (DAILY).
      ...(esJornaleroEnEdicion.value
        ? {
            sunday_worked_days: editForm.sunday_worked_days,
            seventh_day_days: editForm.seventh_day_days || '0',
            holiday_worked_days: editForm.holiday_worked_days || '0',
          }
        : {}),
    };
    await updateEntry(periodId.value, sheetActiva.value.id, editingEntry.value.id, payload);
    editEntryOpen.value = false;
    $q.notify({ type: 'positive', message: 'Línea actualizada y recalculada.' });
    await cargarEntradas();
  } catch (e) {
    const err = e as { response?: { data?: { detail?: string } } };
    $q.notify({ type: 'negative', message: err.response?.data?.detail || 'No se pudo actualizar la línea.' });
  } finally {
    saving.value = false;
  }
}

function confirmDelete(row: PayrollEntry) {
  $q.dialog({
    title: 'Quitar de la planilla',
    message: `¿Quitar a «${row.full_name}» de esta planilla? Se puede volver a agregar.`,
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'negative', label: 'Quitar' },
  }).onOk(() => {
    void doDeleteEntry(row);
  });
}

async function doDeleteEntry(row: PayrollEntry) {
  if (!sheetActiva.value) return;
  try {
    await deleteEntry(periodId.value, sheetActiva.value.id, row.id);
    $q.notify({ type: 'positive', message: 'Línea quitada de la planilla.' });
    await reload();
  } catch (e) {
    const err = e as { response?: { data?: { detail?: string } } };
    $q.notify({ type: 'negative', message: err.response?.data?.detail || 'No se pudo quitar la línea.' });
  }
}

onMounted(reload);
</script>

<style scoped>

.per-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-4);
}

.per-head__main {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}

.per-head__title {
  font-family: 'Manrope', 'IBM Plex Sans', sans-serif;
  font-size: 1.35rem;
  font-weight: 800;
  color: var(--app-text);
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-wrap: wrap;
}

.per-head__subtitle {
  color: var(--app-text-muted);
  font-size: 0.84rem;
}

.per-section {
  margin-bottom: var(--app-space-6);
}

.per-section__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  flex-wrap: wrap;
  margin-bottom: var(--app-space-3);
}

.per-section__title {
  font-weight: 800;
  color: var(--app-text);
  font-size: 1.05rem;
}

.per-muted {
  color: var(--app-text-muted);
  font-weight: 400;
  font-size: 0.85rem;
}

.per-sheets {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: var(--app-space-3);
}

.per-sheet {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  cursor: pointer;
}

.per-sheet--active {
  border-color: var(--app-primary);
  box-shadow: var(--app-shadow-card);
}

.per-sheet__name {
  font-weight: 800;
  color: var(--app-text);
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-wrap: wrap;
}

.per-sheet__meta {
  color: var(--app-text-muted);
  font-size: 0.8rem;
  margin: var(--app-space-1) 0 var(--app-space-2);
}

.per-sheet__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

.per-empty {
  color: var(--app-text-muted);
  padding: var(--app-space-5);
}


/* Planilla completa (mismas casillas que el Excel): scroll horizontal, sin cortar rótulos */
.app-table :deep(th),
.app-table :deep(td) {
  white-space: nowrap;
}

.app-table :deep(thead th) {
  font-weight: 700;
}

.per-dialog {
  width: 520px;
  max-width: 94vw;
  background: var(--app-surface-strong);
}


.per-form__row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--app-space-3);
}

.per-form__row--3 {
  grid-template-columns: 1fr 1fr 1fr;
}

.per-form__subtitle {
  font-weight: 700;
  color: var(--app-text);
  font-size: 0.85rem;
  margin-top: var(--app-space-2);
}

.per-form__note {
  font-size: 0.78rem;
}

.per-row-actions {
  white-space: nowrap;
}

/* Vista del expediente seleccionado (solo lectura) */
.per-expediente {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-strong);
  padding: var(--app-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}

.per-expediente__row {
  display: flex;
  justify-content: space-between;
  gap: var(--app-space-3);
  font-size: 0.85rem;
}

.per-expediente__row span {
  color: var(--app-text-muted);
}

.per-expediente__row b {
  color: var(--app-text);
  text-align: right;
}

.per-banner-warn {
  background: color-mix(in srgb, var(--app-warning, #b45309) 14%, transparent);
  color: var(--app-text);
  border: 1px solid var(--app-border-strong);
  font-size: 0.8rem;
}

/* Captura de asistencia día-por-día */
.att-dialog {
  width: 760px;
  max-width: 94vw;
  background: var(--app-surface-strong);
}
.att-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.att-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 0.78rem;
  margin-top: 4px;
}
.att-legend__item b {
  font-weight: 800;
}
.att-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(108px, 1fr));
  gap: var(--app-space-2);
}
.att-day {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  padding: 6px;
  background: var(--app-surface);
}
.att-day--sun {
  border-color: var(--app-accent-coral);
  background: color-mix(in srgb, var(--app-accent-coral) 7%, transparent);
}
.att-day__lbl {
  font-weight: 700;
  font-size: 0.82rem;
  margin-bottom: 4px;
}
.att-day__lbl small {
  color: var(--app-text-muted);
  font-weight: 600;
}
.att-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
}
.att-sum b {
  color: var(--app-text);
}

/* Columnas de domingo en la grilla de días de la planilla CON INSS */
.app-table :deep(.per-day-sun) {
  background: color-mix(in srgb, var(--app-accent-coral) 10%, transparent);
  color: var(--app-accent-coral);
  font-weight: 700;
}
</style>
