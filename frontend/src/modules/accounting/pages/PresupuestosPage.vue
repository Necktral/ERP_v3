<template>
  <q-page class="app-page">
    <PageHeader
      title="Presupuestos"
      subtitle="Presupuesto mensual por cuenta y centro de costo, y comparación contra lo realmente registrado."
      :loading="cargando"
      @refresh="recargar"
    >
      <template #actions>
        <q-btn
          v-if="puede('accounting.budget.manage')"
          unelevated
          no-caps
          color="primary"
          icon="add"
          label="Nuevo presupuesto"
          @click="abrirNuevo"
        />
      </template>
    </PageHeader>

    <div class="pre-cols">
      <!-- Lista de presupuestos -->
      <div class="pre-lista">
        <q-list bordered separator>
          <q-item
            v-for="b in presupuestos"
            :key="b.id"
            clickable
            :active="seleccionado?.id === b.id"
            active-class="pre-activo"
            @click="seleccionar(b)"
          >
            <q-item-section>
              <q-item-label>{{ b.name }}</q-item-label>
              <q-item-label caption>{{ b.fiscal_year }} · {{ b.currency }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-chip
                dense
                square
                :class="`pre-chip pre-chip--${b.status}`"
                :label="BUDGET_STATUS_LABELS[b.status] ?? b.status"
              />
            </q-item-section>
          </q-item>
          <q-item v-if="!presupuestos.length">
            <q-item-section class="text-caption text-muted">Sin presupuestos.</q-item-section>
          </q-item>
        </q-list>
      </div>

      <!-- Detalle -->
      <div v-if="detalle" class="pre-detalle">
        <div class="pre-detalle__head">
          <div>
            <div class="text-h6">{{ detalle.name }} · {{ detalle.fiscal_year }}</div>
            <q-chip
              dense
              square
              :class="`pre-chip pre-chip--${detalle.status}`"
              :label="BUDGET_STATUS_LABELS[detalle.status] ?? detalle.status"
            />
          </div>
          <div class="pre-detalle__acciones">
            <q-btn
              v-if="detalle.status === 'DRAFT' && puede('accounting.budget.manage')"
              outline
              no-caps
              size="sm"
              color="primary"
              icon="add"
              label="Agregar línea"
              @click="agregarLinea"
            />
            <q-btn
              v-if="detalle.status === 'DRAFT' && puede('accounting.budget.manage')"
              unelevated
              no-caps
              size="sm"
              color="primary"
              icon="save"
              label="Guardar líneas"
              :loading="accionando"
              @click="guardarLineas"
            />
            <q-btn
              v-if="detalle.status === 'DRAFT' && puede('accounting.budget.manage')"
              unelevated
              no-caps
              size="sm"
              color="positive"
              icon="task_alt"
              label="Aprobar"
              :loading="accionando"
              @click="aprobar"
            />
          </div>
        </div>

        <q-tabs v-model="tab" dense no-caps align="left" active-color="primary" indicator-color="primary">
          <q-tab name="lineas" icon="table_rows" label="Líneas" />
          <q-tab name="comparar" icon="balance" label="Presupuesto vs real" />
        </q-tabs>
        <q-separator class="q-mb-md" />

        <!-- Líneas -->
        <div v-if="tab === 'lineas'">
          <q-markup-table flat dense class="app-table pre-grid">
            <thead>
              <tr>
                <th class="text-left">Cuenta</th>
                <th class="text-left">Centro</th>
                <th v-for="m in 12" :key="m" class="text-right">{{ NOMBRE_MES[m - 1] }}</th>
                <th class="text-right">Anual</th>
                <th v-if="editable"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(ln, i) in lineasEdit" :key="i">
                <td>
                  <q-select
                    v-if="editable"
                    v-model="ln.account_code"
                    :options="opcionesCuenta"
                    dense
                    options-dense
                    emit-value
                    map-options
                    use-input
                    input-debounce="0"
                    @filter="filtrarCuentas"
                    class="pre-sel-cta"
                  />
                  <span v-else>{{ ln.account_code }}</span>
                </td>
                <td>
                  <q-select
                    v-if="editable"
                    v-model="ln.cost_center_id"
                    :options="opcionesCentro"
                    dense
                    options-dense
                    emit-value
                    map-options
                    clearable
                    class="pre-sel-cc"
                  />
                  <span v-else>{{ ln.cost_center_code ?? '—' }}</span>
                </td>
                <td v-for="m in 12" :key="m" class="text-right">
                  <q-input
                    v-if="editable"
                    v-model="ln.monthly[String(m)]"
                    dense
                    borderless
                    type="number"
                    input-class="text-right pre-mes-input"
                  />
                  <span v-else>{{ formatMoney(ln.monthly[String(m)] || '0') }}</span>
                </td>
                <td class="text-right text-weight-bold">{{ formatMoney(anual(ln)) }}</td>
                <td v-if="editable" class="text-right">
                  <q-btn flat dense round size="sm" icon="close" @click="lineasEdit.splice(i, 1)" />
                </td>
              </tr>
              <tr v-if="!lineasEdit.length">
                <td :colspan="15" class="text-center text-muted">Sin líneas.</td>
              </tr>
            </tbody>
          </q-markup-table>
        </div>

        <!-- Comparación -->
        <div v-else>
          <div class="pre-comp-filtros">
            <q-input v-model.number="mesDesde" outlined dense type="number" label="Mes desde" class="pre-mes" />
            <q-input v-model.number="mesHasta" outlined dense type="number" label="Mes hasta" class="pre-mes" />
            <q-select
              v-model="filtroCentro"
              :options="opcionesCentro"
              outlined
              dense
              emit-value
              map-options
              clearable
              label="Centro de costo"
              class="pre-filtro-cc"
            />
            <q-btn outline no-caps color="primary" icon="refresh" label="Comparar" :loading="comparando" @click="comparar" />
            <q-btn v-if="vs" flat no-caps icon="print" label="Imprimir" @click="imprimir" />
          </div>

          <div v-if="vs" class="pre-comp-totales">
            Presupuesto <strong>{{ formatMoney(vs.total_budget) }}</strong> · Real
            <strong>{{ formatMoney(vs.total_actual) }}</strong> · Variación
            <strong :class="Number(vs.total_variance) >= 0 ? 'text-positive' : 'text-negative'">
              {{ formatMoney(vs.total_variance) }}
            </strong>
          </div>

          <q-table
            v-if="vs"
            class="app-table"
            :rows="vs.rows"
            :columns="columnasVs"
            row-key="account_code"
            flat
            :pagination="{ rowsPerPage: 50 }"
            no-data-label="Sin datos para el rango."
          >
            <template #body-cell-variance="props">
              <q-td :props="props" :class="Number(props.row.variance) >= 0 ? 'text-positive' : 'text-negative'">
                {{ formatMoney(props.row.variance) }}
                <span v-if="props.row.variance_pct" class="text-caption"> ({{ props.row.variance_pct }}%)</span>
              </q-td>
            </template>
          </q-table>
        </div>
      </div>
      <div v-else class="pre-vacio text-muted">Elegí un presupuesto para ver su detalle.</div>
    </div>

    <!-- Diálogo nuevo presupuesto -->
    <q-dialog v-model="dlgNuevo">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Nuevo presupuesto</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model.number="formNuevo.fiscal_year" outlined dense type="number" label="Año *" />
          <q-input v-model="formNuevo.name" outlined dense label="Nombre * (ej. Operativo 2026)" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear"
            :loading="accionando"
            :disable="!formNuevo.name.trim() || !formNuevo.fiscal_year"
            @click="crear"
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
import { formatMoney } from 'src/core/format';
import {
  ACCOUNTING_PLUS_MENSAJES,
  approveBudget,
  BUDGET_STATUS_LABELS,
  createBudget,
  getBudget,
  getBudgetVsActual,
  getChartOfAccounts,
  listBudgets,
  listCostCenters,
  setBudgetLines,
  type BudgetDetail,
  type BudgetRow,
  type BudgetVsActual,
  type BudgetVsActualRow,
  type CostCenterRow,
} from 'src/modules/accounting/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const NOMBRE_MES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

const presupuestos = ref<BudgetRow[]>([]);
const seleccionado = ref<BudgetRow | null>(null);
const detalle = ref<BudgetDetail | null>(null);
const cargando = ref(false);
const accionando = ref(false);
const tab = ref('lineas');

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const editable = computed(() => detalle.value?.status === 'DRAFT' && puede('accounting.budget.manage'));

interface LineaEdit {
  account_code: string | null;
  cost_center_id: number | null;
  cost_center_code: string | null;
  monthly: Record<string, string>;
}
const lineasEdit = ref<LineaEdit[]>([]);

const centros = ref<CostCenterRow[]>([]);
const opcionesCuentaAll = ref<{ value: string; label: string }[]>([]);
const opcionesCuenta = ref<{ value: string; label: string }[]>([]);
const opcionesCentro = computed(() =>
  centros.value.filter((c) => c.is_active).map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` })),
);

function anual(ln: LineaEdit): number {
  let t = 0;
  for (let m = 1; m <= 12; m++) t += Number(ln.monthly[String(m)] || 0);
  return t;
}

function filtrarCuentas(val: string, update: (cb: () => void) => void) {
  update(() => {
    const needle = val.toLowerCase();
    opcionesCuenta.value = needle
      ? opcionesCuentaAll.value.filter((o) => o.label.toLowerCase().includes(needle))
      : opcionesCuentaAll.value;
  });
}

function notificarError(e: unknown, fallback: string) {
  const crudo = apiErrorMessage(e, fallback);
  $q.notify({ type: 'negative', message: ACCOUNTING_PLUS_MENSAJES[crudo] ?? crudo });
}

async function recargar() {
  cargando.value = true;
  try {
    const [bs, ccs, coa] = await Promise.all([listBudgets(), listCostCenters(), getChartOfAccounts()]);
    presupuestos.value = bs;
    centros.value = ccs;
    opcionesCuentaAll.value = coa.results
      .filter((c) => c.is_postable)
      .map((c) => ({ value: c.code, label: `${c.code} · ${c.name}` }));
    opcionesCuenta.value = opcionesCuentaAll.value;
    if (seleccionado.value) {
      const aun = bs.find((b) => b.id === seleccionado.value?.id);
      if (aun) await seleccionar(aun);
      else {
        seleccionado.value = null;
        detalle.value = null;
      }
    }
  } catch (e) {
    notificarError(e, 'No se pudieron cargar los presupuestos.');
  } finally {
    cargando.value = false;
  }
}

async function seleccionar(b: BudgetRow) {
  seleccionado.value = b;
  vs.value = null;
  tab.value = 'lineas';
  try {
    detalle.value = await getBudget(b.id);
    lineasEdit.value = detalle.value.lines.map((l) => ({
      account_code: l.account_code,
      cost_center_id: l.cost_center_id,
      cost_center_code: l.cost_center_code,
      monthly: { ...l.monthly },
    }));
  } catch (e) {
    notificarError(e, 'No se pudo cargar el presupuesto.');
  }
}

function nuevaLineaVacia(): LineaEdit {
  const monthly: Record<string, string> = {};
  for (let m = 1; m <= 12; m++) monthly[String(m)] = '0';
  return { account_code: null, cost_center_id: null, cost_center_code: null, monthly };
}

function agregarLinea() {
  lineasEdit.value.push(nuevaLineaVacia());
}

async function guardarLineas() {
  if (!detalle.value) return;
  accionando.value = true;
  try {
    const lines = lineasEdit.value
      .filter((l) => l.account_code)
      .map((l) => ({
        account_code: l.account_code as string,
        cost_center_id: l.cost_center_id,
        monthly: l.monthly,
      }));
    await setBudgetLines(detalle.value.id, lines);
    $q.notify({ type: 'positive', message: 'Líneas guardadas.' });
    await seleccionar(seleccionado.value as BudgetRow);
  } catch (e) {
    notificarError(e, 'No se pudieron guardar las líneas.');
  } finally {
    accionando.value = false;
  }
}

async function aprobar() {
  if (!detalle.value) return;
  accionando.value = true;
  try {
    await approveBudget(detalle.value.id);
    $q.notify({ type: 'positive', message: 'Presupuesto aprobado.' });
    await recargar();
  } catch (e) {
    notificarError(e, 'No se pudo aprobar.');
  } finally {
    accionando.value = false;
  }
}

// --- Nuevo ---
const dlgNuevo = ref(false);
const formNuevo = reactive({ fiscal_year: new Date().getFullYear(), name: '' });

function abrirNuevo() {
  Object.assign(formNuevo, { fiscal_year: new Date().getFullYear(), name: '' });
  dlgNuevo.value = true;
}

async function crear() {
  accionando.value = true;
  try {
    const b = await createBudget({ fiscal_year: formNuevo.fiscal_year, name: formNuevo.name.trim() });
    dlgNuevo.value = false;
    $q.notify({ type: 'positive', message: 'Presupuesto creado.' });
    await recargar();
    const fresh = presupuestos.value.find((x) => x.id === b.id);
    if (fresh) await seleccionar(fresh);
  } catch (e) {
    notificarError(e, 'No se pudo crear.');
  } finally {
    accionando.value = false;
  }
}

// --- Comparación ---
const mesDesde = ref(1);
const mesHasta = ref(12);
const filtroCentro = ref<number | null>(null);
const vs = ref<BudgetVsActual | null>(null);
const comparando = ref(false);

const columnasVs: QTableColumn<BudgetVsActualRow>[] = [
  { name: 'cuenta', label: 'Cuenta', field: (r) => `${r.account_code} · ${r.account_name}`, align: 'left' },
  { name: 'centro', label: 'Centro', field: (r) => r.cost_center_code ?? '—', align: 'left' },
  { name: 'budget', label: 'Presupuesto', field: (r) => formatMoney(r.budget), align: 'right' },
  { name: 'actual', label: 'Real', field: (r) => formatMoney(r.actual), align: 'right' },
  { name: 'variance', label: 'Variación', field: 'variance', align: 'right' },
];

async function comparar() {
  if (!detalle.value) return;
  comparando.value = true;
  try {
    vs.value = await getBudgetVsActual(detalle.value.id, {
      month_from: mesDesde.value,
      month_to: mesHasta.value,
      cost_center_id: filtroCentro.value,
    });
  } catch (e) {
    notificarError(e, 'No se pudo comparar.');
  } finally {
    comparando.value = false;
  }
}

function imprimir() {
  window.print();
}

onMounted(recargar);
</script>

<style scoped>
.pre-cols {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: var(--app-space-4);
}

.pre-activo {
  background: var(--app-surface-2, var(--app-surface));
  border-left: 3px solid var(--app-primary);
}

.pre-detalle__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--app-space-3);
  gap: var(--app-space-3);
}

.pre-detalle__acciones {
  display: flex;
  gap: var(--app-space-2);
  flex-wrap: wrap;
}

.pre-grid :deep(th),
.pre-grid :deep(td) {
  padding: 2px 6px;
  font-size: 0.8rem;
}

.pre-sel-cta {
  min-width: 150px;
}

.pre-sel-cc {
  min-width: 110px;
}

.pre-mes-input {
  width: 64px;
}

.pre-comp-filtros {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-wrap: wrap;
  margin-bottom: var(--app-space-3);
}

.pre-mes {
  width: 110px;
}

.pre-filtro-cc {
  width: 220px;
}

.pre-comp-totales {
  margin-bottom: var(--app-space-3);
  color: var(--app-text);
}

.pre-vacio {
  padding: var(--app-space-5);
}

.pre-chip {
  border: 1px solid var(--app-border);
  background: transparent;
  color: var(--app-text);
}

.pre-chip--APPROVED {
  border-color: var(--q-positive);
  color: var(--q-positive);
}

.pre-chip--ARCHIVED {
  color: var(--app-text-muted);
}
</style>
