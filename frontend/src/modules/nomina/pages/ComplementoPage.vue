<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton :to="`/nomina/periodos/${periodId}`" />
    </div>
    <PageHeader
      title="Complemento de salario"
      subtitle="Pago bruto por convenio personal, desacoplado de la planilla legal (no genera INSS): neto = bruto. SoD: el encargado arma y envía, el aprobador autoriza. Recibo imprimible por hoja."
      :loading="cargando"
      @refresh="cargar"
    />

    <div class="row q-col-gutter-md">
      <!-- Hojas -->
      <div class="col-12 col-md-4">
        <q-card flat bordered class="app-card">
          <q-card-section class="row items-center justify-between">
            <div class="text-subtitle1">Hojas</div>
            <q-btn dense unelevated no-caps color="primary" icon="add" label="Nueva" :loading="creando" @click="crearHoja" />
          </q-card-section>
          <q-separator />
          <q-list separator>
            <q-item
              v-for="h in hojas"
              :key="h.id"
              clickable
              :active="h.id === selId"
              active-class="hoja--activa"
              @click="seleccionar(h.id)"
            >
              <q-item-section>
                <q-item-label>{{ h.name || `Hoja #${h.id}` }}</q-item-label>
                <q-item-label caption>{{ h.lines }} trabajador(es)</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-chip dense square :color="statusColor(h.status)" text-color="white" size="sm" :label="COMPLEMENT_STATUS_LABELS[h.status]" />
              </q-item-section>
            </q-item>
            <q-item v-if="!hojas.length && !cargando">
              <q-item-section class="text-muted">Sin hojas. "Nueva" siembra desde los perfiles con complemento.</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>

      <!-- Detalle -->
      <div class="col-12 col-md-8">
        <q-card v-if="detalle" flat bordered class="app-card">
          <q-card-section class="row items-center justify-between">
            <div>
              <div class="text-h6">{{ detalle.name || `Hoja #${detalle.id}` }}</div>
              <div class="text-caption text-muted">
                Devengado total: <b>{{ detalle.subtotal_nio }}</b> · {{ COMPLEMENT_STATUS_LABELS[detalle.status] }}
              </div>
            </div>
            <div class="q-gutter-xs">
              <q-btn v-if="detalle.status === 'DRAFT'" dense unelevated no-caps color="primary" icon="send" label="Enviar" :loading="acting" @click="accionHoja('submit')" />
              <q-btn v-if="detalle.status === 'SUBMITTED'" dense unelevated no-caps color="positive" icon="verified" label="Aprobar" :loading="acting" @click="accionHoja('approve')" />
              <q-btn dense flat no-caps icon="picture_as_pdf" label="Recibo" @click="descargarRecibo" />
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section>
            <q-table
              :rows="detalle.lines"
              :columns="cols"
              row-key="id"
              flat
              bordered
              dense
              :pagination="{ rowsPerPage: 0 }"
              hide-bottom
              no-data-label="La hoja no tiene líneas (ningún perfil con complemento habilitado)."
            >
              <template #body-cell-recibido="props">
                <q-td :props="props">
                  <q-chip v-if="props.row.received_at" dense square color="positive" text-color="white" size="sm" label="Recibido" />
                  <span v-else class="text-muted">—</span>
                </q-td>
              </template>
              <template #body-cell-acciones="props">
                <q-td :props="props" class="q-gutter-xs">
                  <q-btn v-if="detalle.status === 'DRAFT'" dense flat round size="sm" icon="edit" aria-label="Editar monto" @click="abrirMonto(props.row)" />
                  <q-btn v-if="!props.row.received_at" dense flat no-caps size="sm" color="positive" icon="how_to_reg" label="Recibí" @click="marcarRecibido(props.row)" />
                </q-td>
              </template>
            </q-table>
          </q-card-section>
        </q-card>
        <q-card v-else flat bordered class="app-card">
          <q-card-section class="text-muted">Selecciona una hoja para ver sus líneas.</q-card-section>
        </q-card>
      </div>
    </div>

    <!-- Editar monto de línea -->
    <q-dialog v-model="montoOpen">
      <q-card class="app-dialog" style="min-width: 340px">
        <q-card-section class="text-h6">Monto · {{ montoLinea?.full_name }}</q-card-section>
        <q-card-section>
          <q-input v-model.number="montoValor" type="number" min="0" step="0.01" label="Devengado (C$)" outlined dense autofocus />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn unelevated no-caps color="primary" label="Guardar" :loading="acting" :disable="montoValor < 0" @click="guardarMonto" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import { useRoute } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import { apiErrorMessage } from 'src/core/api';
import {
  COMPLEMENT_STATUS_LABELS,
  complementAction,
  createComplementSheet,
  downloadComplementRecibo,
  getComplementSheet,
  listComplementSheets,
  markComplementReceived,
  setComplementLineAmount,
  type ComplementLine,
  type ComplementSheetDetail,
  type ComplementSheetRow,
  type ComplementStatus,
} from 'src/modules/nomina/api';

const $q = useQuasar();
const route = useRoute();
const periodId = Number(route.params.id);

const hojas = ref<ComplementSheetRow[]>([]);
const detalle = ref<ComplementSheetDetail | null>(null);
const selId = ref<number | null>(null);
const cargando = ref(false);
const creando = ref(false);
const acting = ref(false);

function statusColor(s: ComplementStatus): string {
  return { DRAFT: 'grey', SUBMITTED: 'info', APPROVED: 'positive' }[s];
}

const cols: QTableColumn<ComplementLine>[] = [
  { name: 'full_name', label: 'Trabajador', field: 'full_name', align: 'left', sortable: true },
  { name: 'cargo', label: 'Cargo', field: 'cargo', align: 'left' },
  { name: 'cedula', label: 'Cédula', field: 'cedula', align: 'left' },
  { name: 'devengado_nio', label: 'Devengado', field: 'devengado_nio', align: 'right', sortable: true },
  { name: 'recibido', label: 'Recibido', field: 'received_at', align: 'left' },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

async function cargar() {
  cargando.value = true;
  try {
    hojas.value = await listComplementSheets(periodId);
    if (selId.value && !hojas.value.some((h) => h.id === selId.value)) {
      selId.value = null;
      detalle.value = null;
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudieron cargar las hojas.') });
  } finally {
    cargando.value = false;
  }
}
async function seleccionar(id: number) {
  selId.value = id;
  detalle.value = null;
  try {
    detalle.value = await getComplementSheet(periodId, id);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar la hoja.') });
  }
}
async function refrescar() {
  await cargar();
  if (selId.value) await seleccionar(selId.value);
}

async function crearHoja() {
  creando.value = true;
  try {
    const creada = await createComplementSheet(periodId, {});
    $q.notify({ type: 'positive', message: 'Hoja creada desde los perfiles con complemento.' });
    await cargar();
    selId.value = creada.id;
    detalle.value = creada;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo crear la hoja.') });
  } finally {
    creando.value = false;
  }
}

async function accionHoja(action: 'submit' | 'approve') {
  if (!selId.value) return;
  acting.value = true;
  try {
    detalle.value = await complementAction(periodId, selId.value, action);
    $q.notify({ type: 'positive', message: action === 'submit' ? 'Hoja enviada.' : 'Hoja aprobada.' });
    await cargar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo completar la acción.') });
  } finally {
    acting.value = false;
  }
}

// ---- monto de línea ----
const montoOpen = ref(false);
const montoLinea = ref<ComplementLine | null>(null);
const montoValor = ref(0);
function abrirMonto(l: ComplementLine) {
  montoLinea.value = l;
  montoValor.value = Number(l.devengado_nio);
  montoOpen.value = true;
}
async function guardarMonto() {
  if (!selId.value || !montoLinea.value) return;
  acting.value = true;
  try {
    await setComplementLineAmount(periodId, selId.value, montoLinea.value.id, montoValor.value);
    montoOpen.value = false;
    await refrescar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo guardar el monto.') });
  } finally {
    acting.value = false;
  }
}

async function marcarRecibido(l: ComplementLine) {
  if (!selId.value) return;
  try {
    await markComplementReceived(periodId, selId.value, l.id);
    await refrescar();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo marcar como recibido.') });
  }
}

async function descargarRecibo() {
  if (!selId.value) return;
  try {
    await downloadComplementRecibo(periodId, selId.value);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo generar el recibo.') });
  }
}

onMounted(cargar);
</script>

<style scoped>
.hoja--activa {
  background: var(--app-primary-soft, rgba(0, 0, 0, 0.05));
  font-weight: 600;
}
</style>
