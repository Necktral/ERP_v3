<template>
  <q-page class="app-page">
    <PageHeader
      title="Cierre anual"
      subtitle="Cierra el ejercicio: lleva los resultados (ingresos y gastos) a la cuenta de resultados acumulados y sella diciembre. Se puede reabrir (reversa el asiento de cierre)."
      :loading="cargando"
      @refresh="cargar"
    />

    <div class="cierre-filtros">
      <q-input
        v-model.number="anio"
        outlined
        dense
        type="number"
        label="Ejercicio (año)"
        class="cierre-anio"
        @keyup.enter="cargar"
      />
      <q-btn flat no-caps icon="search" label="Ver estado" @click="cargar" />
    </div>

    <div v-if="estado" class="cierre-resumen">
      <div class="cierre-card">
        <div class="text-muted">Estado</div>
        <div class="cierre-cifra">
          <q-chip
            dense
            square
            :class="estado.status === 'CLOSED' ? 'cierre-chip-ok' : estado.status === 'REOPENED' ? 'cierre-chip-warn' : 'cierre-chip-open'"
            :label="estadoLabel"
          />
        </div>
      </div>
      <div class="cierre-card">
        <div class="text-muted">Resultado del ejercicio</div>
        <div class="cierre-cifra" :class="Number(estado.net_result) >= 0 ? 'text-positive' : 'text-negative'">
          {{ formatMoney(estado.net_result) }}
        </div>
        <div class="text-caption text-muted">
          Ingresos {{ formatMoney(estado.revenue) }} − Gastos {{ formatMoney(estado.expense) }}
        </div>
      </div>
      <div class="cierre-card">
        <div class="text-muted">Diciembre</div>
        <div class="cierre-cifra">{{ estado.december_open ? 'Abierto' : 'Cerrado' }}</div>
      </div>
    </div>

    <div v-if="estado" class="cierre-meses">
      <div class="cierre-meses__titulo">Meses del ejercicio</div>
      <div class="cierre-meses__grid">
        <div
          v-for="m in 12"
          :key="m"
          class="cierre-mes"
          :class="estado.months[String(m)] === 'CLOSED' ? 'cierre-mes--closed' : 'cierre-mes--open'"
        >
          <span>{{ NOMBRE_MES[m - 1] }}</span>
          <q-icon :name="estado.months[String(m)] === 'CLOSED' ? 'lock' : 'lock_open'" size="16px" />
        </div>
      </div>
      <div v-if="estado.months_pending_close.length" class="text-caption text-negative q-mt-sm">
        Para cerrar el ejercicio, primero cerrá los meses de enero a noviembre (Períodos). Pendientes:
        {{ estado.months_pending_close.map((m) => NOMBRE_MES[m - 1]).join(', ') }}.
      </div>
    </div>

    <div v-if="estado" class="cierre-acciones">
      <q-btn
        v-if="estado.status !== 'CLOSED'"
        unelevated
        no-caps
        color="primary"
        icon="event_available"
        label="Cerrar ejercicio"
        :loading="accionando"
        :disable="!puedeCerrar"
        @click="confirmarCierre"
      />
      <q-btn
        v-if="estado.status === 'CLOSED'"
        outline
        no-caps
        color="negative"
        icon="lock_open"
        label="Reabrir ejercicio"
        :loading="accionando"
        @click="confirmarReapertura"
      />
      <div v-if="estado.closing_entry_id" class="text-caption text-muted">
        Asiento de cierre: #{{ estado.closing_entry_id }}
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatMoney } from 'src/core/format';
import {
  ACCOUNTING_PLUS_MENSAJES,
  closeFiscalYear,
  getYearEndStatus,
  reopenFiscalYear,
  type YearEndStatus,
} from 'src/modules/accounting/api';

const $q = useQuasar();

const NOMBRE_MES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

const anio = ref(new Date().getFullYear() - 1);
const estado = ref<YearEndStatus | null>(null);
const cargando = ref(false);
const accionando = ref(false);

const estadoLabel = computed(() => {
  if (!estado.value?.status) return 'Abierto';
  return estado.value.status === 'CLOSED' ? 'Cerrado' : 'Reabierto';
});

const puedeCerrar = computed(
  () => estado.value != null && estado.value.months_pending_close.length === 0 && estado.value.december_open,
);

function notificarError(e: unknown, fallback: string) {
  const crudo = apiErrorMessage(e, fallback);
  $q.notify({ type: 'negative', message: ACCOUNTING_PLUS_MENSAJES[crudo] ?? crudo });
}

async function cargar() {
  if (!anio.value) return;
  cargando.value = true;
  try {
    estado.value = await getYearEndStatus(anio.value);
  } catch (e) {
    notificarError(e, 'No se pudo cargar el estado del ejercicio.');
  } finally {
    cargando.value = false;
  }
}

function confirmarCierre() {
  if (!estado.value) return;
  $q.dialog({
    title: `Cerrar ejercicio ${anio.value}`,
    message: `Se generará el asiento de cierre llevando el resultado de ${formatMoney(
      estado.value.net_result,
    )} a resultados acumulados, y se sellará diciembre. ¿Continuar?`,
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'primary', label: 'Cerrar ejercicio' },
    persistent: true,
  }).onOk(() => {
    void ejecutarCierre();
  });
}

async function ejecutarCierre() {
  accionando.value = true;
  try {
    estado.value = await closeFiscalYear(anio.value);
    $q.notify({ type: 'positive', message: `Ejercicio ${anio.value} cerrado.` });
  } catch (e) {
    notificarError(e, 'No se pudo cerrar el ejercicio.');
  } finally {
    accionando.value = false;
  }
}

function confirmarReapertura() {
  $q.dialog({
    title: `Reabrir ejercicio ${anio.value}`,
    message: 'Se reabrirá diciembre y se reversará el asiento de cierre (los resultados vuelven a sus cuentas). Motivo:',
    prompt: { model: '', type: 'text', isValid: (v: string) => v.trim().length >= 5 },
    cancel: { flat: true, noCaps: true, label: 'Cancelar' },
    ok: { unelevated: true, noCaps: true, color: 'negative', label: 'Reabrir' },
    persistent: true,
  }).onOk((motivo: string) => {
    void (async () => {
      accionando.value = true;
      try {
        estado.value = await reopenFiscalYear(anio.value, motivo.trim());
        $q.notify({ type: 'positive', message: `Ejercicio ${anio.value} reabierto.` });
      } catch (e) {
        notificarError(e, 'No se pudo reabrir.');
      } finally {
        accionando.value = false;
      }
    })();
  });
}

onMounted(cargar);
</script>

<style scoped>
.cierre-filtros {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-4);
}

.cierre-anio {
  width: 200px;
}

.cierre-resumen {
  display: flex;
  gap: var(--app-space-3);
  flex-wrap: wrap;
  margin-bottom: var(--app-space-4);
}

.cierre-card {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
  padding: var(--app-space-3) var(--app-space-4);
  min-width: 200px;
}

.cierre-cifra {
  font-size: 1.3rem;
  font-weight: 700;
}

.cierre-meses {
  margin-bottom: var(--app-space-4);
}

.cierre-meses__titulo {
  font-weight: 700;
  color: var(--app-text);
  margin-bottom: var(--app-space-2);
}

.cierre-meses__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: var(--app-space-2);
}

.cierre-mes {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-1);
  padding: var(--app-space-2) var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  font-size: 0.85rem;
}

.cierre-mes--closed {
  color: var(--app-text-muted);
  background: var(--app-surface);
}

.cierre-mes--open {
  color: var(--app-text);
  border-color: var(--app-primary);
}

.cierre-acciones {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
}

.cierre-chip-ok {
  border: 1px solid var(--q-positive);
  color: var(--q-positive);
  background: transparent;
}

.cierre-chip-warn {
  border: 1px solid var(--q-warning);
  color: var(--app-text);
  background: transparent;
}

.cierre-chip-open {
  border: 1px solid var(--app-border);
  color: var(--app-text);
  background: transparent;
}
</style>
