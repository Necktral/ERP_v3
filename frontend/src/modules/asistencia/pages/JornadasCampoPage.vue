<template>
  <q-page class="app-page">
    <PageHeader
      title="Jornadas de campo"
      subtitle="Días de trabajo del campo: el capataz abre la jornada, pasa lista, arma cuadrillas y al final consolida para aprobación."
      :loading="loading"
      @refresh="reload"
    >
      <template #actions>
        <q-btn
          flat
          no-caps
          icon="how_to_vote"
          label="Aprobaciones"
          to="/asistencia/campo/aprobaciones"
        />
        <q-btn
          v-if="puede('nomina.field.capture')"
          unelevated
          no-caps
          color="primary"
          icon="add"
          label="Abrir jornada"
          @click="abrirCrear"
        />
      </template>
    </PageHeader>

    <div class="row q-col-gutter-sm q-mb-md">
      <div class="col-12 col-sm-4 col-md-3">
        <q-select
          v-model="filtroEstado"
          outlined
          dense
          clearable
          emit-value
          map-options
          label="Estado"
          :options="opcionesEstado"
          @update:model-value="reload"
        />
      </div>
      <div class="col-12 col-sm-4 col-md-3">
        <q-input
          v-model="filtroFecha"
          outlined
          dense
          clearable
          type="date"
          label="Fecha"
          @update:model-value="reload"
        />
      </div>
    </div>

    <q-table
      v-model:pagination="pagination"
      class="app-table"
      :rows="rows"
      :columns="columns"
      row-key="id"
      flat
      :loading="loading"
      :rows-per-page-options="[10, 25, 50, 100]"
      no-data-label="No hay jornadas de campo. Abrí la del día para empezar."
      @request="onRequest"
      @row-click="(_evt: Event, row: FieldWorkDay) => verDetalle(row)"
    >
      <template #body-cell-work_date="props">
        <q-td :props="props">{{ formatDate(props.row.work_date) }}</q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props">
          <EstadoChip :estado="props.row.status" :map="MAPA_ESTADO_JORNADA" />
        </q-td>
      </template>
      <template #body-cell-periodo="props">
        <q-td :props="props">
          {{ props.row.payroll_period_id != null ? `#${props.row.payroll_period_id}` : '—' }}
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props">
          <q-btn
            dense
            flat
            no-caps
            color="primary"
            icon="chevron_right"
            label="Abrir"
            @click.stop="verDetalle(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Diálogo: abrir jornada del día -->
    <q-dialog v-model="dlgCrear">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Abrir jornada de campo</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="nuevaFecha" outlined dense type="date" label="Fecha de trabajo *" />
          <q-select
            v-model="nuevaSucursal"
            outlined
            dense
            clearable
            emit-value
            map-options
            label="Sucursal / finca (opcional)"
            :options="opcionesSucursal"
            :loading="cargandoSucursales"
          />
          <q-select
            v-model="nuevoPeriodo"
            outlined
            dense
            clearable
            emit-value
            map-options
            label="Período de planilla (opcional)"
            hint="Podés elegirlo después, al consolidar."
            :options="opcionesPeriodo"
            :loading="cargandoPeriodos"
          />
          <q-input v-model="nuevasNotas" outlined dense autogrow label="Notas" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Abrir jornada"
            :loading="creando"
            :disable="!nuevaFecha"
            @click="crearJornada"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import EstadoChip from 'src/components/EstadoChip.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { formatDate } from 'src/core/format';
import {
  createFieldWorkDay,
  listFieldWorkDays,
  WORK_DAY_STATUS_LABELS,
  type FieldWorkDay,
} from 'src/modules/asistencia/api';
import { etiquetaPeriodo, MAPA_ESTADO_JORNADA } from 'src/modules/asistencia/ui';
import { listBranches, type Branch } from 'src/modules/hr/api';
import { listPeriods } from 'src/modules/nomina/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const router = useRouter();
const acl = useAclStore();
const ctx = useContextStore();

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

// --- listado (server-side) ---
const filtroEstado = ref<string | null>(null);
const filtroFecha = ref<string | null>(null);

const opcionesEstado = Object.entries(WORK_DAY_STATUS_LABELS).map(([value, label]) => ({
  value,
  label,
}));

const { rows, loading, pagination, onRequest, reload } = useListadoServer<FieldWorkDay>(
  (page) =>
    listFieldWorkDays(
      {
        ...(filtroEstado.value ? { status: filtroEstado.value } : {}),
        ...(filtroFecha.value ? { work_date: filtroFecha.value } : {}),
      },
      page,
    ),
  { errorMessage: 'No se pudieron cargar las jornadas de campo.' },
);

const columns: QTableColumn<FieldWorkDay>[] = [
  { name: 'id', label: 'N°', field: 'id', align: 'left' },
  { name: 'work_date', label: 'Fecha', field: 'work_date', align: 'left' },
  { name: 'status', label: 'Estado', field: 'status', align: 'left' },
  { name: 'periodo', label: 'Período', field: 'payroll_period_id', align: 'left' },
  { name: 'notes', label: 'Notas', field: 'notes', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

function verDetalle(row: FieldWorkDay) {
  void router.push(`/asistencia/campo/${row.id}`);
}

// --- crear jornada ---
const dlgCrear = ref(false);
const creando = ref(false);
const nuevaFecha = ref('');
const nuevaSucursal = ref<number | null>(null);
const nuevoPeriodo = ref<number | null>(null);
const nuevasNotas = ref('');

const opcionesSucursal = ref<{ label: string; value: number }[]>([]);
const opcionesPeriodo = ref<{ label: string; value: number }[]>([]);
const cargandoSucursales = ref(false);
const cargandoPeriodos = ref(false);

function hoyIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function abrirCrear() {
  nuevaFecha.value = hoyIso();
  nuevaSucursal.value = null;
  nuevoPeriodo.value = null;
  nuevasNotas.value = '';
  dlgCrear.value = true;
  void cargarSelects();
}

async function cargarSelects() {
  cargandoSucursales.value = true;
  cargandoPeriodos.value = true;
  try {
    const branches: Branch[] = await listBranches();
    opcionesSucursal.value = branches.map((b) => ({ label: b.name, value: b.id }));
  } catch {
    opcionesSucursal.value = [];
  } finally {
    cargandoSucursales.value = false;
  }
  try {
    const periodos = (await listPeriods()).filter(
      (p) => p.status === 'DRAFT' || p.status === 'IN_REVIEW',
    );
    opcionesPeriodo.value = periodos.map((p) => ({ label: etiquetaPeriodo(p), value: p.id }));
  } catch {
    opcionesPeriodo.value = [];
  } finally {
    cargandoPeriodos.value = false;
  }
}

async function crearJornada() {
  if (!nuevaFecha.value) return;
  creando.value = true;
  try {
    const jornada = await createFieldWorkDay({
      work_date: nuevaFecha.value,
      ...(nuevaSucursal.value != null ? { branch_id: nuevaSucursal.value } : {}),
      ...(nuevoPeriodo.value != null ? { payroll_period_id: nuevoPeriodo.value } : {}),
      ...(nuevasNotas.value.trim() ? { notes: nuevasNotas.value.trim() } : {}),
    });
    dlgCrear.value = false;
    $q.notify({ type: 'positive', message: `Jornada #${jornada.id} abierta.` });
    void router.push(`/asistencia/campo/${jornada.id}`);
  } catch (e) {
    // 400 típico: ya existe la jornada de esa fecha/sucursal.
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo abrir la jornada.') });
  } finally {
    creando.value = false;
  }
}
</script>
