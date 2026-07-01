<template>
  <q-page class="app-page">
    <PageHeader
      title="Centros de costo"
      subtitle="Dimensión analítica para imputar gastos e ingresos en asientos manuales y de cierre, y comparar contra el presupuesto."
      :loading="cargando"
      @refresh="recargar"
    >
      <template #actions>
        <q-btn
          v-if="puede('accounting.cost_center.manage')"
          unelevated
          no-caps
          color="primary"
          icon="add"
          label="Nuevo centro"
          @click="abrirNuevo"
        />
      </template>
    </PageHeader>

    <q-table
      class="app-table"
      :rows="centros"
      :columns="columnas"
      row-key="id"
      flat
      :loading="cargando"
      :pagination="{ rowsPerPage: 50 }"
      no-data-label="Sin centros de costo. Creá el primero."
    >
      <template #body-cell-estado="props">
        <q-td :props="props">
          <q-chip
            dense
            square
            :class="props.row.is_active ? 'cc-chip-on' : 'cc-chip-off'"
            :label="props.row.is_active ? 'Activo' : 'Inactivo'"
          />
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props" class="text-right">
          <q-btn
            v-if="puede('accounting.cost_center.manage')"
            flat
            dense
            no-caps
            size="sm"
            icon="edit"
            label="Editar"
            @click="abrirEditar(props.row)"
          />
          <q-btn
            v-if="puede('accounting.cost_center.manage')"
            flat
            dense
            no-caps
            size="sm"
            :icon="props.row.is_active ? 'toggle_off' : 'toggle_on'"
            :label="props.row.is_active ? 'Desactivar' : 'Activar'"
            @click="alternar(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="dlg">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">{{ editando ? 'Editar centro' : 'Nuevo centro de costo' }}</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="form.code" outlined dense label="Código *" :disable="!!editando" />
          <q-input v-model="form.name" outlined dense label="Nombre *" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Guardar"
            :loading="accionando"
            :disable="!form.code.trim() || !form.name.trim()"
            @click="guardar"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import {
  ACCOUNTING_PLUS_MENSAJES,
  createCostCenter,
  listCostCenters,
  updateCostCenter,
  type CostCenterRow,
} from 'src/modules/accounting/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const centros = ref<CostCenterRow[]>([]);
const cargando = ref(false);
const accionando = ref(false);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}

const columnas: QTableColumn<CostCenterRow>[] = [
  { name: 'code', label: 'Código', field: 'code', align: 'left', sortable: true },
  { name: 'name', label: 'Nombre', field: 'name', align: 'left' },
  { name: 'estado', label: 'Estado', field: 'is_active', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

async function recargar() {
  cargando.value = true;
  try {
    centros.value = await listCostCenters();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar los centros.') });
  } finally {
    cargando.value = false;
  }
}

const dlg = ref(false);
const editando = ref<CostCenterRow | null>(null);
const form = reactive({ code: '', name: '' });

function abrirNuevo() {
  editando.value = null;
  Object.assign(form, { code: '', name: '' });
  dlg.value = true;
}

function abrirEditar(cc: CostCenterRow) {
  editando.value = cc;
  Object.assign(form, { code: cc.code, name: cc.name });
  dlg.value = true;
}

function notificarError(e: unknown, fallback: string) {
  const crudo = apiErrorMessage(e, fallback);
  $q.notify({ type: 'negative', message: ACCOUNTING_PLUS_MENSAJES[crudo] ?? crudo });
}

async function guardar() {
  accionando.value = true;
  try {
    if (editando.value) {
      await updateCostCenter(editando.value.id, { name: form.name.trim() });
    } else {
      await createCostCenter({ code: form.code.trim(), name: form.name.trim() });
    }
    dlg.value = false;
    $q.notify({ type: 'positive', message: 'Centro de costo guardado.' });
    await recargar();
  } catch (e) {
    notificarError(e, 'No se pudo guardar.');
  } finally {
    accionando.value = false;
  }
}

async function alternar(cc: CostCenterRow) {
  try {
    await updateCostCenter(cc.id, { is_active: !cc.is_active });
    await recargar();
  } catch (e) {
    notificarError(e, 'No se pudo cambiar el estado.');
  }
}

onMounted(recargar);
</script>

<style scoped>
.cc-chip-on {
  border: 1px solid var(--q-positive);
  color: var(--q-positive);
  background: transparent;
}

.cc-chip-off {
  border: 1px solid var(--app-border);
  color: var(--app-text-muted);
  background: transparent;
}
</style>
