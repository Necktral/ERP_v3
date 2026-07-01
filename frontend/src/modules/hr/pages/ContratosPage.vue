<template>
  <q-page class="app-page">
    <PageHeader
      title="Contratos laborales"
      subtitle="Roster a nivel empresa: emisión, firmas, renovaciones, adendas y alertas de vencimiento."
      :loading="cargando"
      @refresh="recargar"
    />

    <q-banner v-if="porVencer.length" class="ctr-alert" rounded>
      <template #avatar><q-icon name="warning" color="warning" /></template>
      Hay <b>{{ porVencer.length }}</b> contrato(s) por vencer en los próximos {{ ventana }} días.
      <q-btn flat dense no-caps color="primary" label="Ver" @click="tab = 'vencer'" />
    </q-banner>

    <q-tabs v-model="tab" no-caps align="left" class="ctr-tabs">
      <q-tab name="todos" label="Todos" />
      <q-tab name="vencer" label="Por vencer" />
    </q-tabs>

    <div v-if="tab === 'todos'" class="ctr-filtros">
      <q-select
        v-model="filtroEstado"
        :options="estadoOpts"
        outlined
        dense
        emit-value
        map-options
        clearable
        label="Estado"
        class="ctr-filtro"
        @update:model-value="recargar"
      />
      <q-select
        v-model="filtroTipo"
        :options="tipoOpts"
        outlined
        dense
        emit-value
        map-options
        clearable
        label="Tipo"
        class="ctr-filtro"
        @update:model-value="recargar"
      />
    </div>

    <q-table
      class="app-table"
      :rows="tab === 'todos' ? contratos : porVencer"
      :columns="columnas"
      row-key="id"
      flat
      :loading="cargando"
      :pagination="{ rowsPerPage: 25 }"
      no-data-label="Sin contratos para mostrar."
    >
      <template #body-cell-estado="props">
        <q-td :props="props">
          <q-chip dense square :class="`ctr-st ctr-st--${props.row.status}`" :label="estadoLabel(props.row.status)" />
        </q-td>
      </template>
      <template #body-cell-firmas="props">
        <q-td :props="props">
          <q-icon
            v-if="props.row.fully_signed_at"
            name="verified"
            color="positive"
            size="20px"
          >
            <q-tooltip>Firmado por ambas partes</q-tooltip>
          </q-icon>
          <span v-else class="ctr-muted">
            {{ firmasResumen(props.row) }}
          </span>
        </q-td>
      </template>
      <template #body-cell-fin="props">
        <q-td :props="props">
          {{ props.row.end_date || '—' }}
          <q-badge
            v-if="tab === 'vencer' && props.row.days_to_expire != null"
            :color="props.row.days_to_expire < 0 ? 'negative' : 'warning'"
            :label="props.row.days_to_expire < 0 ? 'Vencido' : `${props.row.days_to_expire} d`"
            class="q-ml-xs"
          />
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props" class="text-right">
          <q-btn flat dense no-caps size="sm" icon="visibility" label="Ver" @click="abrirDetalle(props.row)" />
          <q-btn
            v-if="puedeGestionar && props.row.status === 'EMITIDO'"
            flat dense no-caps size="sm" icon="draw" label="Firmar" @click="abrirFirma(props.row)"
          />
          <q-btn
            v-if="puedeGestionar && props.row.status === 'EMITIDO'"
            flat dense no-caps size="sm" icon="note_add" label="Adenda" @click="abrirAdenda(props.row)"
          />
          <q-btn
            v-if="puedeGestionar && ['EMITIDO', 'FINALIZADO'].includes(props.row.status)"
            flat dense no-caps size="sm" icon="autorenew" label="Renovar" @click="abrirRenovar(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Detalle -->
    <q-dialog v-model="dlgDetalle">
      <q-card class="ctr-dialog">
        <q-card-section class="row items-center">
          <div class="text-h6">Contrato #{{ sel?.id }} — {{ sel?.contract_type_label }}</div>
          <q-space />
          <q-chip v-if="sel" dense square :class="`ctr-st ctr-st--${sel.status}`" :label="estadoLabel(sel.status)" />
        </q-card-section>
        <q-card-section v-if="sel" class="ctr-detalle">
          <div class="ctr-meta">
            <span><b>Trabajador:</b> {{ sel.employee_name }}</span>
            <span><b>Inicio:</b> {{ sel.start_date }}</span>
            <span><b>Fin:</b> {{ sel.end_date || '—' }}</span>
            <span v-if="sel.salary_amount"><b>Salario:</b> C$ {{ sel.salary_amount }} ({{ sel.salary_period }})</span>
          </div>
          <div v-if="sel.signatures?.length" class="ctr-firmas-box">
            <div class="ctr-sub">Firmas</div>
            <div v-for="s in sel.signatures" :key="s.party_role" class="ctr-firma">
              <q-icon name="check_circle" color="positive" size="18px" />
              {{ s.party_role_label }}: {{ s.signer_name }}
              <span class="ctr-muted">({{ fecha(s.signed_at) }})</span>
            </div>
          </div>
          <div v-if="sel.versions?.length" class="ctr-firmas-box">
            <div class="ctr-sub">Versiones</div>
            <div v-for="v in sel.versions" :key="v.version_no" class="ctr-muted">
              v{{ v.version_no }} — {{ v.reason || 'Sin motivo' }} ({{ fecha(v.created_at) }})
            </div>
          </div>
          <pre class="ctr-body">{{ sel.body }}</pre>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn
            v-if="puedeGestionar && sel?.status === 'BORRADOR'"
            unelevated no-caps color="primary" label="Emitir"
            :loading="accionando" @click="emitir(sel)"
          />
          <q-btn flat no-caps label="Cerrar" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Firma -->
    <q-dialog v-model="dlgFirma">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Registrar firma</q-card-section>
        <q-card-section class="app-form">
          <q-select
            v-model="firma.party_role"
            :options="rolFirmaOpts"
            outlined dense emit-value map-options label="Parte que firma *"
          />
          <q-input v-model="firma.signer_name" outlined dense label="Nombre de quien firma *" />
          <q-select
            v-model="firma.method"
            :options="metodoFirmaOpts"
            outlined dense emit-value map-options label="Método"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated no-caps color="primary" label="Firmar" :loading="accionando"
            :disable="!firma.party_role || !firma.signer_name.trim()" @click="firmar"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Adenda -->
    <q-dialog v-model="dlgAdenda">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Adenda al contrato</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="adenda.reason" outlined dense label="Motivo de la adenda *" />
          <q-input v-model="adenda.body" outlined type="textarea" autogrow label="Texto de la adenda *" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated no-caps color="primary" label="Guardar adenda" :loading="accionando"
            :disable="!adenda.reason.trim() || !adenda.body.trim()" @click="guardarAdenda"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Renovar -->
    <q-dialog v-model="dlgRenovar">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Renovar contrato</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="renovar.start_date" outlined dense type="date" label="Nuevo inicio *" />
          <q-input v-model="renovar.end_date" outlined dense type="date" label="Nueva fecha de fin" />
          <q-input v-model="renovar.salary_amount" outlined dense label="Salario (opcional)" />
          <div class="ctr-muted">Se finaliza el contrato actual y se crea un borrador encadenado.</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated no-caps color="primary" label="Renovar" :loading="accionando"
            :disable="!renovar.start_date" @click="renovarContrato"
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
import {
  amendContract,
  annulContract,
  getContract,
  getExpiringContracts,
  getHrCatalogs,
  issueContract,
  listContracts,
  renewContract,
  signContract,
  type ContractRow,
  type CatalogChoice,
} from 'src/modules/hr/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const cargando = ref(false);
const accionando = ref(false);
const tab = ref<'todos' | 'vencer'>('todos');
const ventana = 30;

const contratos = ref<ContractRow[]>([]);
const porVencer = ref<ContractRow[]>([]);
const estadoOpts = ref<CatalogChoice[]>([]);
const tipoOpts = ref<CatalogChoice[]>([]);
const rolFirmaOpts = ref<CatalogChoice[]>([]);
const metodoFirmaOpts = ref<CatalogChoice[]>([]);
const filtroEstado = ref<string | null>(null);
const filtroTipo = ref<string | null>(null);

const labelTipo = ref<Record<string, string>>({});
const labelEstado = ref<Record<string, string>>({});

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}
const puedeGestionar = computed(() => puede('hr.contract.manage'));

const columnas: QTableColumn<ContractRow>[] = [
  { name: 'trabajador', label: 'Trabajador', field: (r) => r.employee_name || '', align: 'left' },
  { name: 'tipo', label: 'Tipo', field: 'contract_type_label', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'status', align: 'left' },
  { name: 'inicio', label: 'Inicio', field: 'start_date', align: 'left' },
  { name: 'fin', label: 'Fin', field: 'end_date', align: 'left' },
  { name: 'firmas', label: 'Firmas', field: 'fully_signed_at', align: 'center' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

function estadoLabel(s: string): string {
  return labelEstado.value[s] ?? s;
}
function firmasResumen(c: ContractRow): string {
  const p = [];
  if (c.signed_employer_at) p.push('Empleador');
  if (c.signed_employee_at) p.push('Trabajador');
  return p.length ? p.join(' + ') : 'Sin firmar';
}
function fecha(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString('es-NI') : '—';
}

async function recargar() {
  cargando.value = true;
  try {
    const filtros: { status?: string; contract_type?: string } = {};
    if (filtroEstado.value) filtros.status = filtroEstado.value;
    if (filtroTipo.value) filtros.contract_type = filtroTipo.value;
    const [lista, venc] = await Promise.all([
      listContracts(filtros),
      getExpiringContracts(ventana),
    ]);
    contratos.value = lista;
    porVencer.value = venc;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar los contratos.') });
  } finally {
    cargando.value = false;
  }
}

async function cargarCatalogos() {
  try {
    const cat = await getHrCatalogs();
    estadoOpts.value = cat.contract_statuses;
    tipoOpts.value = cat.contract_types;
    rolFirmaOpts.value = cat.signature_roles;
    metodoFirmaOpts.value = cat.signature_methods;
    labelTipo.value = Object.fromEntries(cat.contract_types.map((c) => [c.value, c.label]));
    labelEstado.value = Object.fromEntries(cat.contract_statuses.map((c) => [c.value, c.label]));
  } catch {
    /* catálogos opcionales */
  }
}

// --- Detalle ---
const dlgDetalle = ref(false);
const sel = ref<ContractRow | null>(null);
async function abrirDetalle(row: ContractRow) {
  try {
    sel.value = await getContract(row.id);
    dlgDetalle.value = true;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo abrir el contrato.') });
  }
}

async function emitir(c: ContractRow | null) {
  if (!c) return;
  accionando.value = true;
  try {
    await issueContract(c.id);
    $q.notify({ type: 'positive', message: 'Contrato emitido.' });
    dlgDetalle.value = false;
    await recargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo emitir.') });
  } finally {
    accionando.value = false;
  }
}

// --- Firma ---
const dlgFirma = ref(false);
const firma = reactive({ id: 0, party_role: '', signer_name: '', method: 'FISICA' });
function abrirFirma(row: ContractRow) {
  Object.assign(firma, { id: row.id, party_role: '', signer_name: row.employee_name || '', method: 'FISICA' });
  dlgFirma.value = true;
}
async function firmar() {
  accionando.value = true;
  try {
    await signContract(firma.id, {
      party_role: firma.party_role,
      signer_name: firma.signer_name.trim(),
      method: firma.method,
    });
    $q.notify({ type: 'positive', message: 'Firma registrada.' });
    dlgFirma.value = false;
    await recargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo registrar la firma.') });
  } finally {
    accionando.value = false;
  }
}

// --- Adenda ---
const dlgAdenda = ref(false);
const adenda = reactive({ id: 0, reason: '', body: '' });
function abrirAdenda(row: ContractRow) {
  Object.assign(adenda, { id: row.id, reason: '', body: '' });
  dlgAdenda.value = true;
}
async function guardarAdenda() {
  accionando.value = true;
  try {
    await amendContract(adenda.id, { reason: adenda.reason.trim(), body: adenda.body.trim() });
    $q.notify({ type: 'positive', message: 'Adenda guardada.' });
    dlgAdenda.value = false;
    await recargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo guardar la adenda.') });
  } finally {
    accionando.value = false;
  }
}

// --- Renovar ---
const dlgRenovar = ref(false);
const renovar = reactive({ id: 0, start_date: '', end_date: '', salary_amount: '' });
function abrirRenovar(row: ContractRow) {
  Object.assign(renovar, { id: row.id, start_date: '', end_date: '', salary_amount: row.salary_amount || '' });
  dlgRenovar.value = true;
}
async function renovarContrato() {
  accionando.value = true;
  try {
    await renewContract(renovar.id, {
      start_date: renovar.start_date,
      end_date: renovar.end_date || null,
      salary_amount: renovar.salary_amount || null,
    });
    $q.notify({ type: 'positive', message: 'Contrato renovado (borrador creado).' });
    dlgRenovar.value = false;
    await recargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo renovar.') });
  } finally {
    accionando.value = false;
  }
}

// annulContract queda disponible para uso futuro desde el detalle.
void annulContract;

onMounted(async () => {
  await cargarCatalogos();
  await recargar();
});
</script>

<style scoped>
.ctr-alert {
  margin-bottom: var(--app-space-4);
  border: 1px solid var(--app-border-strong);
  background: var(--app-surface-strong);
}
.ctr-tabs {
  margin-bottom: var(--app-space-3);
}
.ctr-filtros {
  display: flex;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
  flex-wrap: wrap;
}
.ctr-filtro {
  min-width: 200px;
}
.ctr-muted {
  color: var(--app-text-muted);
  font-size: 0.82rem;
}
.ctr-st {
  border: 1px solid var(--app-border);
  background: transparent;
}
.ctr-st--BORRADOR {
  color: var(--app-text-muted);
}
.ctr-st--EMITIDO {
  color: var(--app-primary);
  border-color: var(--app-primary);
}
.ctr-st--FINALIZADO {
  color: var(--app-text-muted);
  border-color: var(--app-border-strong);
}
.ctr-st--ANULADO {
  color: var(--q-negative);
  border-color: var(--q-negative);
}
.ctr-dialog {
  width: 720px;
  max-width: 95vw;
  background: var(--app-surface-strong);
}
.ctr-detalle {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}
.ctr-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-3);
  font-size: 0.88rem;
}
.ctr-sub {
  font-weight: 700;
  margin-bottom: var(--app-space-1);
}
.ctr-firma {
  font-size: 0.85rem;
}
.ctr-firmas-box {
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
}
.ctr-body {
  white-space: pre-wrap;
  font-family: inherit;
  font-size: 0.84rem;
  line-height: 1.5;
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  max-height: 320px;
  overflow: auto;
}
</style>
