<template>
  <div>
    <div class="req-filtros">
      <q-select
        v-model="filtroEstado"
        :options="opcionesEstado"
        dense
        outlined
        emit-value
        map-options
        clearable
        label="Estado"
        class="req-filtros__sel"
        @update:model-value="reload"
      />
      <q-space />
      <q-btn
        v-if="puedeCrear"
        unelevated
        no-caps
        color="primary"
        icon="post_add"
        label="Nueva requisición"
        @click="abrirCrear"
      />
    </div>

    <q-list bordered separator class="rounded-borders">
      <q-item v-if="!rows.length && !loading">
        <q-item-section class="text-muted">No hay requisiciones.</q-item-section>
      </q-item>
      <q-expansion-item v-for="r in rows" :key="r.id" group="reqs">
        <template #header>
          <q-item-section>
            <q-item-label>
              Requisición #{{ r.id }}
              <span v-if="r.notes" class="text-muted">· {{ r.notes }}</span>
            </q-item-label>
            <q-item-label caption>
              {{ r.lines.length }} líneas · pedida por {{ r.requested_by || '—' }} ·
              {{ formatDate(r.created_at) }}
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <EstadoChip :estado="r.status" :map="MAPA_REQ" />
          </q-item-section>
        </template>

        <q-card>
          <q-card-section>
            <q-markup-table flat dense class="app-table">
              <thead>
                <tr>
                  <th class="text-left">Artículo</th>
                  <th class="text-right">Cantidad</th>
                  <th class="text-left">Nota</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="ln in r.lines" :key="ln.id">
                  <td>{{ ln.item_name }} <span class="text-muted">({{ ln.item_sku }})</span></td>
                  <td class="text-right">{{ formatQty(ln.qty) }}</td>
                  <td>{{ ln.note || '—' }}</td>
                </tr>
              </tbody>
            </q-markup-table>

            <q-banner v-if="r.status === 'REJECTED'" dense rounded class="q-mt-sm">
              Rechazada por {{ r.decided_by }}: {{ r.rejection_reason }}
            </q-banner>
            <q-banner v-if="r.status === 'CONVERTED' && r.converted_order_id" dense rounded class="q-mt-sm">
              Convertida a la orden de compra
              <q-btn
                flat
                dense
                no-caps
                color="primary"
                :label="`OC #${r.converted_order_id}`"
                @click="$router.push(`/compras/oc/${r.converted_order_id}`)"
              />
            </q-banner>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn
              v-if="r.status === 'DRAFT' && puedeCrear"
              flat
              no-caps
              color="primary"
              icon="send"
              label="Enviar a aprobación"
              @click="accion(() => submitRequisition(r.id))"
            />
            <template v-if="r.status === 'SUBMITTED' && puedeAprobar">
              <q-btn
                flat
                no-caps
                color="positive"
                icon="check"
                label="Aprobar"
                @click="accion(() => approveRequisition(r.id))"
              />
              <q-btn flat no-caps color="negative" icon="block" label="Rechazar" @click="abrirRechazo(r)" />
            </template>
            <q-btn
              v-if="r.status === 'APPROVED' && puedeCrearOC"
              flat
              no-caps
              color="primary"
              icon="shopping_cart_checkout"
              label="Convertir a OC"
              @click="abrirConvertir(r)"
            />
          </q-card-actions>
        </q-card>
      </q-expansion-item>
    </q-list>

    <!-- Diálogo: crear -->
    <q-dialog v-model="dlgCrear">
      <q-card class="app-dialog req-dialogo">
        <q-card-section class="text-h6">Nueva requisición</q-card-section>
        <q-card-section class="app-form">
          <div v-for="(ln, i) in lineas" :key="i" class="req-linea">
            <ItemSelect v-model="ln.item_id" class="req-linea__item" />
            <q-input v-model="ln.qty" outlined dense type="number" min="0.0001" label="Cantidad *" class="req-linea__num" />
            <q-btn flat dense round icon="close" aria-label="Eliminar línea de requisición" :disable="lineas.length === 1" @click="lineas.splice(i, 1)" />
          </div>
          <q-btn flat no-caps icon="add" label="Agregar línea" @click="lineas.push({ item_id: null, qty: '1' })" />
          <q-input v-model="notas" outlined dense label="Notas (para qué se necesita)" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Crear"
            :loading="guardando"
            :disable="!formValido"
            @click="crear"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: rechazo con motivo -->
    <q-dialog v-model="dlgRechazo">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Rechazar requisición #{{ reqActiva?.id }}</q-card-section>
        <q-card-section class="app-form">
          <q-input v-model="motivoRechazo" outlined dense autofocus label="Motivo *" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="negative"
            label="Rechazar"
            :disable="motivoRechazo.trim().length < 3"
            @click="rechazar"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: convertir a OC (elige proveedor) -->
    <q-dialog v-model="dlgConvertir">
      <q-card class="app-dialog">
        <q-card-section class="text-h6">Convertir a orden de compra</q-card-section>
        <q-card-section class="app-form">
          <PartySelect v-model="proveedorConvertir" role="SUPPLIER" label="Proveedor *" />
          <div class="text-caption text-muted">
            Los costos salen del precio registrado del proveedor (acordado o último costo);
            si falta alguno, registralo primero en la pestaña «Precios proveedor».
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            label="Convertir"
            :disable="proveedorConvertir == null"
            @click="convertir"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import EstadoChip from 'src/components/EstadoChip.vue';
import { apiErrorMessage } from 'src/core/api';
import { useListado } from 'src/core/composables/useListado';
import { formatDate, formatQty } from 'src/core/format';
import ItemSelect from 'src/modules/inventory/components/ItemSelect.vue';
import PartySelect from 'src/modules/parties/components/PartySelect.vue';
import { MENSAJES_COMPRAS } from 'src/modules/procurement/messages';
import {
  approveRequisition,
  convertRequisition,
  createRequisition,
  listRequisitions,
  rejectRequisition,
  REQUISITION_STATUS_LABELS,
  submitRequisition,
  type Requisition,
  type RequisitionStatus,
} from 'src/modules/procurement/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const router = useRouter();
const acl = useAclStore();
const ctx = useContextStore();

const MAPA_REQ = {
  DRAFT: { color: 'grey-7', label: REQUISITION_STATUS_LABELS.DRAFT },
  SUBMITTED: { color: 'orange-8', label: REQUISITION_STATUS_LABELS.SUBMITTED },
  APPROVED: { color: 'teal-7', label: REQUISITION_STATUS_LABELS.APPROVED },
  REJECTED: { color: 'negative', label: REQUISITION_STATUS_LABELS.REJECTED },
  CONVERTED: { color: 'positive', label: REQUISITION_STATUS_LABELS.CONVERTED },
};

const filtroEstado = ref<RequisitionStatus | null>(null);
const { rows, loading, reload } = useListado<Requisition>(
  () => listRequisitions({ status: filtroEstado.value ?? '' }),
  { errorMessage: 'No se pudieron cargar las requisiciones.' },
);

function puede(code: string): boolean {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, code) : false;
}
const puedeCrear = computed(() => puede('procurement.requisition.create'));
const puedeAprobar = computed(() => puede('procurement.requisition.approve'));
const puedeCrearOC = computed(() => puede('procurement.order.create'));

const opcionesEstado = Object.entries(REQUISITION_STATUS_LABELS).map(([value, label]) => ({
  value,
  label,
}));

function notificarError(e: unknown, fallback: string) {
  const crudo = apiErrorMessage(e, fallback);
  $q.notify({ type: 'negative', message: MENSAJES_COMPRAS[crudo] ?? crudo });
}

async function accion(fn: () => Promise<unknown>) {
  try {
    await fn();
    await reload();
  } catch (e) {
    notificarError(e, 'No se pudo completar la acción.');
  }
}

// --- Crear ---
const dlgCrear = ref(false);
const guardando = ref(false);
const notas = ref('');
const lineas = ref<{ item_id: number | null; qty: string }[]>([{ item_id: null, qty: '1' }]);

const formValido = computed(() =>
  lineas.value.every((ln) => ln.item_id != null && Number(ln.qty) > 0),
);

function abrirCrear() {
  notas.value = '';
  lineas.value = [{ item_id: null, qty: '1' }];
  dlgCrear.value = true;
}

async function crear() {
  if (!formValido.value) return;
  guardando.value = true;
  try {
    await createRequisition({
      lines: lineas.value.map((ln) => ({ item_id: ln.item_id as number, qty: String(ln.qty) })),
      ...(notas.value ? { notes: notas.value } : {}),
    });
    dlgCrear.value = false;
    $q.notify({ type: 'positive', message: 'Requisición creada como borrador.' });
    await reload();
  } catch (e) {
    notificarError(e, 'No se pudo crear la requisición.');
  } finally {
    guardando.value = false;
  }
}

// --- Rechazo / conversión ---
const dlgRechazo = ref(false);
const dlgConvertir = ref(false);
const reqActiva = ref<Requisition | null>(null);
const motivoRechazo = ref('');
const proveedorConvertir = ref<number | null>(null);

function abrirRechazo(r: Requisition) {
  reqActiva.value = r;
  motivoRechazo.value = '';
  dlgRechazo.value = true;
}

async function rechazar() {
  if (!reqActiva.value) return;
  try {
    await rejectRequisition(reqActiva.value.id, motivoRechazo.value.trim());
    dlgRechazo.value = false;
    await reload();
  } catch (e) {
    notificarError(e, 'No se pudo rechazar.');
  }
}

function abrirConvertir(r: Requisition) {
  reqActiva.value = r;
  proveedorConvertir.value = null;
  dlgConvertir.value = true;
}

async function convertir() {
  if (!reqActiva.value || proveedorConvertir.value == null) return;
  try {
    const out = await convertRequisition(reqActiva.value.id, proveedorConvertir.value);
    dlgConvertir.value = false;
    $q.notify({ type: 'positive', message: `Orden de compra #${out.order_id} creada.` });
    if (out.order_id) await router.push(`/compras/oc/${out.order_id}`);
  } catch (e) {
    notificarError(e, 'No se pudo convertir.');
  }
}
</script>

<style scoped>
.req-filtros {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}

.req-filtros__sel {
  width: 220px;
}

.req-dialogo {
  min-width: min(620px, 95vw);
}

.req-linea {
  display: flex;
  gap: var(--app-space-2);
  align-items: center;
  margin-bottom: var(--app-space-1);
}

.req-linea__item {
  flex: 1;
}

.req-linea__num {
  width: 130px;
}
</style>
