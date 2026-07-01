<template>
  <q-page class="app-page">
    <PageHeader
      title="Vacaciones"
      subtitle="Saldos por trabajador, acumulación legal (Art. 76 CT: 2.5 días/mes), registro directo y política."
      :loading="cargando"
      @refresh="recargar"
    />

    <!-- Política + acumulación -->
    <div class="vac-top">
      <q-card flat class="vac-card">
        <q-card-section class="vac-card__head">
          <q-icon name="tune" size="22px" />
          <span>Política de acumulación</span>
        </q-card-section>
        <q-card-section class="vac-policy">
          <q-input
            v-model="policy.days_per_month"
            outlined dense label="Días por mes"
            :readonly="!puedeGestionar"
            class="vac-policy__in"
          />
          <q-input
            v-model="policy.max_accrual_days"
            outlined dense label="Tope acumulable (opcional)"
            :readonly="!puedeGestionar"
            class="vac-policy__in"
          />
          <q-btn
            v-if="puedeGestionar"
            unelevated no-caps color="primary" label="Guardar política"
            :loading="accionando" @click="guardarPolitica"
          />
        </q-card-section>
      </q-card>

      <q-card v-if="puedeGestionar" flat class="vac-card">
        <q-card-section class="vac-card__head">
          <q-icon name="event_repeat" size="22px" />
          <span>Acumular mes</span>
        </q-card-section>
        <q-card-section class="vac-accrue">
          <q-input v-model.number="acumular.year" outlined dense type="number" label="Año" class="vac-accrue__in" />
          <q-select
            v-model="acumular.month"
            :options="mesOpts"
            outlined dense emit-value map-options label="Mes"
            class="vac-accrue__in"
          />
          <q-btn
            unelevated no-caps color="secondary" label="Acumular"
            :loading="accionando" @click="acumularMes"
          />
        </q-card-section>
      </q-card>
    </div>

    <q-table
      class="app-table"
      :rows="saldos"
      :columns="columnas"
      row-key="employee_id"
      flat
      :loading="cargando"
      :pagination="{ rowsPerPage: 25 }"
      no-data-label="Sin trabajadores activos."
    >
      <template #body-cell-saldo="props">
        <q-td :props="props">
          <span class="vac-saldo" :class="{ 'vac-saldo--neg': Number(props.row.balance) < 0 }">
            {{ props.row.balance }} días
          </span>
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props" class="text-right">
          <q-btn flat dense no-caps size="sm" icon="history" label="Historial" @click="abrirHistorial(props.row)" />
          <q-btn
            v-if="puedeGestionar"
            flat dense no-caps size="sm" icon="add" label="Registrar" @click="abrirRegistro(props.row)"
          />
          <q-btn
            v-if="puedeGestionar"
            flat dense no-caps size="sm" icon="tune" label="Ajustar" @click="abrirAjuste(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Registrar vacaciones -->
    <q-dialog v-model="dlgReg">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Registrar vacaciones — {{ activo?.employee_name }}</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="reg.start_date" outlined dense type="date" label="Desde *" />
          <q-input v-model="reg.end_date" outlined dense type="date" label="Hasta *" />
          <q-input v-model="reg.reason" outlined dense label="Motivo / observación" />
          <div class="vac-muted">Se descuentan los días hábiles (excluye domingos y feriados). Saldo actual: {{ activo?.balance }} días.</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated no-caps color="primary" label="Registrar" :loading="accionando"
            :disable="!reg.start_date || !reg.end_date" @click="registrar"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Ajustar saldo -->
    <q-dialog v-model="dlgAjuste">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Ajustar saldo — {{ activo?.employee_name }}</q-card-section>
        <q-card-section class="app-form">
          <q-input
            v-model="ajuste.days" outlined dense label="Días (+ acredita / − descuenta) *"
            hint="Ej.: 30 para cargar saldo inicial, −2 para corregir."
          />
          <q-input v-model="ajuste.reason" outlined dense label="Motivo *" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated no-caps color="primary" label="Aplicar ajuste" :loading="accionando"
            :disable="!ajuste.days || !ajuste.reason.trim()" @click="aplicarAjuste"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Historial -->
    <q-dialog v-model="dlgHist">
      <q-card class="vac-hist">
        <q-card-section class="row items-center">
          <div class="text-h6">Historial — {{ activo?.employee_name }}</div>
          <q-space />
          <q-chip dense square color="primary" text-color="white" :label="`Saldo: ${detalle?.balance ?? '—'} días`" />
        </q-card-section>
        <q-card-section v-if="detalle">
          <div class="vac-sub">Solicitudes</div>
          <q-list dense bordered class="vac-list">
            <q-item v-for="r in detalle.requests" :key="r.id">
              <q-item-section>
                <q-item-label>{{ r.start_date }} → {{ r.end_date }} · {{ r.business_days }} días háb.</q-item-label>
                <q-item-label caption>{{ r.status_label }}{{ r.reason ? ' · ' + r.reason : '' }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-btn
                  v-if="puedeGestionar && r.status === 'APROBADA'"
                  flat dense no-caps size="sm" color="negative" icon="cancel" label="Anular"
                  :loading="accionando" @click="anular(r.id)"
                />
              </q-item-section>
            </q-item>
            <q-item v-if="!detalle.requests.length">
              <q-item-section class="vac-muted">Sin solicitudes.</q-item-section>
            </q-item>
          </q-list>

          <div class="vac-sub q-mt-md">Movimientos del saldo</div>
          <q-list dense bordered class="vac-list">
            <q-item v-for="e in detalle.ledger" :key="e.id">
              <q-item-section>
                <q-item-label>{{ e.entry_type_label }} · {{ e.occurred_on }}</q-item-label>
                <q-item-label caption>{{ e.source }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <span :class="Number(e.days) < 0 ? 'vac-saldo--neg' : 'vac-saldo--pos'">{{ e.days }}</span>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cerrar" v-close-popup />
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
import {
  accrueVacationMonth,
  adjustVacationBalance,
  cancelVacation,
  getEmployeeVacations,
  getVacationPolicy,
  getVacationSummary,
  registerVacation,
  updateVacationPolicy,
  type EmployeeVacations,
  type VacationSummaryRow,
} from 'src/modules/hr/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const cargando = ref(false);
const accionando = ref(false);
const saldos = ref<VacationSummaryRow[]>([]);

const policy = reactive({ days_per_month: '2.50', max_accrual_days: '' });
const now = new Date();
const acumular = reactive({ year: now.getFullYear(), month: now.getMonth() + 1 });

const mesOpts = [
  { value: 1, label: 'Enero' }, { value: 2, label: 'Febrero' }, { value: 3, label: 'Marzo' },
  { value: 4, label: 'Abril' }, { value: 5, label: 'Mayo' }, { value: 6, label: 'Junio' },
  { value: 7, label: 'Julio' }, { value: 8, label: 'Agosto' }, { value: 9, label: 'Septiembre' },
  { value: 10, label: 'Octubre' }, { value: 11, label: 'Noviembre' }, { value: 12, label: 'Diciembre' },
];

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}
const puedeGestionar = computed(() => puede('hr.vacation.manage'));

const columnas: QTableColumn<VacationSummaryRow>[] = [
  { name: 'code', label: 'Código', field: 'employee_code', align: 'left' },
  { name: 'nombre', label: 'Trabajador', field: 'employee_name', align: 'left', sortable: true },
  { name: 'saldo', label: 'Saldo', field: 'balance', align: 'left', sortable: true },
  { name: 'acciones', label: '', field: 'employee_id', align: 'right' },
];

async function recargar() {
  cargando.value = true;
  try {
    saldos.value = await getVacationSummary();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar los saldos.') });
  } finally {
    cargando.value = false;
  }
}

async function cargarPolitica() {
  try {
    const p = await getVacationPolicy();
    policy.days_per_month = p.days_per_month;
    policy.max_accrual_days = p.max_accrual_days ?? '';
  } catch {
    /* política opcional */
  }
}

async function guardarPolitica() {
  accionando.value = true;
  try {
    await updateVacationPolicy({
      days_per_month: policy.days_per_month,
      max_accrual_days: policy.max_accrual_days.trim() === '' ? null : policy.max_accrual_days,
      is_active: true,
    });
    $q.notify({ type: 'positive', message: 'Política guardada.' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo guardar la política.') });
  } finally {
    accionando.value = false;
  }
}

async function acumularMes() {
  accionando.value = true;
  try {
    const r = await accrueVacationMonth(acumular.year, acumular.month);
    $q.notify({ type: 'positive', message: `Acumulación aplicada a ${r.created} trabajador(es).` });
    await recargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo acumular.') });
  } finally {
    accionando.value = false;
  }
}

const activo = ref<VacationSummaryRow | null>(null);

// --- Registrar ---
const dlgReg = ref(false);
const reg = reactive({ start_date: '', end_date: '', reason: '' });
function abrirRegistro(row: VacationSummaryRow) {
  activo.value = row;
  Object.assign(reg, { start_date: '', end_date: '', reason: '' });
  dlgReg.value = true;
}
async function registrar() {
  if (!activo.value) return;
  accionando.value = true;
  try {
    const r = await registerVacation(activo.value.employee_id, {
      start_date: reg.start_date,
      end_date: reg.end_date,
      reason: reg.reason,
    });
    $q.notify({ type: 'positive', message: `Vacaciones registradas: ${r.business_days} días hábiles.` });
    dlgReg.value = false;
    await recargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo registrar.') });
  } finally {
    accionando.value = false;
  }
}

// --- Ajuste ---
const dlgAjuste = ref(false);
const ajuste = reactive({ days: '', reason: '' });
function abrirAjuste(row: VacationSummaryRow) {
  activo.value = row;
  Object.assign(ajuste, { days: '', reason: '' });
  dlgAjuste.value = true;
}
async function aplicarAjuste() {
  if (!activo.value) return;
  accionando.value = true;
  try {
    await adjustVacationBalance(activo.value.employee_id, { days: ajuste.days, reason: ajuste.reason.trim() });
    $q.notify({ type: 'positive', message: 'Ajuste aplicado.' });
    dlgAjuste.value = false;
    await recargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo ajustar.') });
  } finally {
    accionando.value = false;
  }
}

// --- Historial ---
const dlgHist = ref(false);
const detalle = ref<EmployeeVacations | null>(null);
async function abrirHistorial(row: VacationSummaryRow) {
  activo.value = row;
  detalle.value = null;
  dlgHist.value = true;
  try {
    detalle.value = await getEmployeeVacations(row.employee_id);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el historial.') });
  }
}
async function anular(requestId: number) {
  accionando.value = true;
  try {
    await cancelVacation(requestId, 'Anulada desde el módulo de vacaciones');
    $q.notify({ type: 'positive', message: 'Solicitud anulada, saldo restaurado.' });
    if (activo.value) detalle.value = await getEmployeeVacations(activo.value.employee_id);
    await recargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo anular.') });
  } finally {
    accionando.value = false;
  }
}

onMounted(async () => {
  await cargarPolitica();
  await recargar();
});
</script>

<style scoped>
.vac-top {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: var(--app-space-4);
  margin-bottom: var(--app-space-4);
}
.vac-card {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}
.vac-card__head {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  font-weight: 700;
  color: var(--app-text);
}
.vac-policy,
.vac-accrue {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  flex-wrap: wrap;
}
.vac-policy__in {
  min-width: 150px;
}
.vac-accrue__in {
  min-width: 130px;
}
.vac-muted,
.vac-list .vac-muted {
  color: var(--app-text-muted);
  font-size: 0.8rem;
}
.vac-saldo {
  font-weight: 700;
  color: var(--app-text);
}
.vac-saldo--neg {
  color: var(--q-negative);
  font-weight: 700;
}
.vac-saldo--pos {
  color: var(--q-positive);
  font-weight: 700;
}
.vac-sub {
  font-weight: 700;
  margin-bottom: var(--app-space-2);
  color: var(--app-text);
}
.vac-hist {
  width: 640px;
  max-width: 95vw;
  background: var(--app-surface-strong);
}
.vac-list {
  border-radius: var(--app-radius-sm);
}
</style>
