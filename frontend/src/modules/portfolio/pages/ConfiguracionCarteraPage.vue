<template>
  <q-page class="app-page">
    <PageHeader
      title="Configuración de cartera"
      subtitle="Cómo se comporta la cartera de esta empresa: aplicación de cobros, devengo de intereses, castigo automático e integración con facturación y compras."
      :loading="cargando"
      @refresh="cargar"
    >
      <template #actions>
        <BackButton to="/cartera" />
      </template>
    </PageHeader>

    <q-banner v-if="!cargando && !existe" rounded class="bg-info text-white q-mb-md">
      Esta empresa aún no tiene configuración de cartera guardada: se muestran los valores
      predeterminados. Al guardar se crea la configuración.
    </q-banner>

    <q-card flat bordered class="app-card conf-card">
      <q-card-section class="q-gutter-md">
        <div class="conf-seccion">Aplicación de cobros</div>
        <q-toggle
          v-model="form.auto_allocate_payments"
          label="Aplicar cobros automáticamente"
          :disable="!puedeEditar"
        />
        <div class="conf-ayuda">
          Al registrar un cobro, el sistema lo aplica solo contra los documentos pendientes del
          cliente. Si se apaga, cada pago hay que aplicarlo a mano.
        </div>
        <q-select
          v-model="form.allocation_strategy"
          :options="OPCIONES_ESTRATEGIA"
          label="Estrategia de aplicación"
          outlined
          dense
          emit-value
          map-options
          options-dense
          :disable="!puedeEditar"
          hint="FIFO aplica primero a los documentos más antiguos (única estrategia soportada hoy)."
        />

        <div class="conf-seccion">Intereses de créditos</div>
        <q-select
          v-model="form.interest_accrual_frequency"
          :options="OPCIONES_FRECUENCIA"
          label="Frecuencia de devengo"
          outlined
          dense
          emit-value
          map-options
          options-dense
          :disable="!puedeEditar"
          hint="Cada cuánto el proceso periódico calcula y registra el interés de los créditos activos."
        />
        <q-toggle
          v-model="form.auto_capitalize_interest"
          label="Capitalizar interés automáticamente"
          :disable="!puedeEditar"
        />
        <div class="conf-ayuda">
          Si está activo, el interés devengado se suma al principal del crédito (interés sobre
          interés). Apagado, el interés queda pendiente de cobro sin engrosar el principal.
        </div>

        <div class="conf-seccion">Castigo automático</div>
        <q-toggle
          v-model="form.auto_writeoff_enabled"
          label="Permitir castigo automático"
          :disable="!puedeEditar"
        />
        <div class="conf-ayuda">
          Castigar una cuenta la saca de cobranza de forma irreversible; por eso viene apagado.
        </div>
        <q-input
          v-model.number="form.auto_writeoff_days"
          type="number"
          min="1"
          label="Días de mora para castigo automático"
          outlined
          dense
          :disable="!puedeEditar || !form.auto_writeoff_enabled"
          hint="Una CxC con más días de mora que esto es candidata a castigo automático."
        />

        <div class="conf-seccion">Controles (gates)</div>
        <q-select
          v-model="form.gate_mode"
          :options="OPCIONES_GATE"
          label="Modo de los controles"
          outlined
          dense
          emit-value
          map-options
          options-dense
          :disable="!puedeEditar"
          hint="Bloqueante detiene la operación que viola un control; Advertencia la deja pasar avisando; Apagado no valida."
        />

        <div class="conf-seccion">Moneda</div>
        <q-input
          v-model="form.functional_currency"
          label="Moneda funcional"
          outlined
          dense
          maxlength="8"
          :disable="!puedeEditar"
          hint="Moneda en la que se consolidan los reportes de cartera (ej. NIO)."
        />
        <q-toggle
          v-model="form.auto_convert_currency"
          label="Convertir automáticamente a moneda funcional"
          :disable="!puedeEditar"
        />
        <div class="conf-ayuda">
          Convierte los montos en otra moneda a la funcional usando el tipo de cambio vigente.
        </div>

        <div class="conf-seccion">Integración con otros módulos</div>
        <q-toggle
          v-model="form.sync_with_billing"
          label="Crear CxC desde facturación"
          :disable="!puedeEditar"
        />
        <div class="conf-ayuda">Cada factura al crédito genera su cuenta por cobrar automáticamente.</div>
        <q-toggle
          v-model="form.sync_with_procurement"
          label="Crear CxP desde compras"
          :disable="!puedeEditar"
        />
        <div class="conf-ayuda">Cada compra al crédito genera su cuenta por pagar automáticamente.</div>
        <q-select
          v-model="form.integration_mode"
          :options="OPCIONES_INTEGRACION"
          label="Modo de integración"
          outlined
          dense
          emit-value
          map-options
          options-dense
          :disable="!puedeEditar"
          hint="Asíncrono (recomendado): la cartera se actualiza por eventos. Síncrono: en la misma operación."
        />

        <q-expansion-item dense icon="data_object" label="Avanzado (JSON)" class="q-mt-sm">
          <div class="q-gutter-md q-pt-sm">
            <q-input
              v-model="agingBucketsText"
              type="textarea"
              autogrow
              outlined
              dense
              label="Buckets de antigüedad (JSON)"
              :disable="!puedeEditar"
              :error="!!errorAging"
              :error-message="errorAging"
              hint='Umbral de días → etiqueta del bucket, ej. {"0": "CURRENT", "30": "0-30"}.'
            />
            <q-input
              v-model="settingsText"
              type="textarea"
              autogrow
              outlined
              dense
              label="Configuraciones adicionales (JSON)"
              :disable="!puedeEditar"
              :error="!!errorSettings"
              :error-message="errorSettings"
              hint="Ajustes extra que lee el kernel sin cambiar código."
            />
          </div>
        </q-expansion-item>

        <div v-if="existe" class="text-caption text-muted">
          Última actualización: {{ formatDateTime(form.updated_at) }}
        </div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn
          v-if="puedeEditar"
          unelevated
          no-caps
          color="primary"
          icon="save"
          :label="existe ? 'Guardar cambios' : 'Crear configuración'"
          :loading="guardando"
          @click="guardar"
        />
      </q-card-actions>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import { apiErrorMessage } from 'src/core/api';
import { formatDateTime } from 'src/core/format';
import {
  createPortfolioSettings,
  getPortfolioSettings,
  updatePortfolioSettings,
  type PortfolioSettings,
  type PortfolioSettingsInput,
} from 'src/modules/portfolio/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const OPCIONES_ESTRATEGIA = [{ label: 'FIFO — primero lo más antiguo', value: 'FIFO' }];
const OPCIONES_FRECUENCIA = [
  { label: 'Mensual', value: 'MONTHLY' },
  { label: 'Diaria', value: 'DAILY' },
];
const OPCIONES_GATE = [
  { label: 'Bloqueante', value: 'BLOCKING' },
  { label: 'Advertencia', value: 'WARNING' },
  { label: 'Apagado', value: 'DISABLED' },
];
const OPCIONES_INTEGRACION = [
  { label: 'Asíncrono (por eventos)', value: 'ASYNC' },
  { label: 'Síncrono', value: 'SYNC' },
];

// Defaults espejo del modelo backend: se usan mientras la empresa no tiene settings.
function formPorDefecto(): PortfolioSettings {
  return {
    company: 0,
    aging_buckets_json: {},
    auto_allocate_payments: true,
    allocation_strategy: 'FIFO',
    interest_accrual_frequency: 'MONTHLY',
    auto_capitalize_interest: false,
    auto_writeoff_enabled: false,
    auto_writeoff_days: 365,
    gate_mode: 'BLOCKING',
    functional_currency: 'NIO',
    auto_convert_currency: false,
    sync_with_billing: true,
    sync_with_procurement: true,
    integration_mode: 'ASYNC',
    settings_json: {},
    updated_at: '',
  };
}

const cargando = ref(false);
const guardando = ref(false);
const existe = ref(false);
const form = ref<PortfolioSettings>(formPorDefecto());
const agingBucketsText = ref('{}');
const settingsText = ref('{}');
const errorAging = ref('');
const errorSettings = ref('');

const puedeEditar = computed(() => {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, 'portfolio.settings.write') : false;
});

async function cargar() {
  cargando.value = true;
  try {
    const settings = await getPortfolioSettings();
    existe.value = settings != null;
    form.value = settings ?? formPorDefecto();
    agingBucketsText.value = JSON.stringify(form.value.aging_buckets_json ?? {}, null, 2);
    settingsText.value = JSON.stringify(form.value.settings_json ?? {}, null, 2);
    errorAging.value = '';
    errorSettings.value = '';
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar la configuración.') });
  } finally {
    cargando.value = false;
  }
}

function parseJsonCampo(texto: string, errorRef: { value: string }): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(texto || '{}');
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      errorRef.value = 'Debe ser un objeto JSON, ej. {"clave": "valor"}.';
      return null;
    }
    errorRef.value = '';
    return parsed as Record<string, unknown>;
  } catch {
    errorRef.value = 'JSON inválido.';
    return null;
  }
}

async function guardar() {
  const aging = parseJsonCampo(agingBucketsText.value, errorAging);
  const extras = parseJsonCampo(settingsText.value, errorSettings);
  if (aging === null || extras === null) return;

  const payload: PortfolioSettingsInput = {
    aging_buckets_json: aging as Record<string, string>,
    auto_allocate_payments: form.value.auto_allocate_payments,
    allocation_strategy: form.value.allocation_strategy,
    interest_accrual_frequency: form.value.interest_accrual_frequency,
    auto_capitalize_interest: form.value.auto_capitalize_interest,
    auto_writeoff_enabled: form.value.auto_writeoff_enabled,
    auto_writeoff_days: form.value.auto_writeoff_days,
    gate_mode: form.value.gate_mode,
    functional_currency: form.value.functional_currency.trim().toUpperCase(),
    auto_convert_currency: form.value.auto_convert_currency,
    sync_with_billing: form.value.sync_with_billing,
    sync_with_procurement: form.value.sync_with_procurement,
    integration_mode: form.value.integration_mode,
    settings_json: extras,
  };

  guardando.value = true;
  try {
    form.value = existe.value
      ? await updatePortfolioSettings(form.value.company, payload)
      : await createPortfolioSettings(payload);
    existe.value = true;
    $q.notify({ type: 'positive', message: 'Configuración de cartera guardada.' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo guardar la configuración.') });
  } finally {
    guardando.value = false;
  }
}

onMounted(cargar);
</script>

<style scoped>
.conf-card {
  max-width: 640px;
}

.conf-seccion {
  font-weight: 600;
  margin-top: var(--app-space-3);
  padding-bottom: 2px;
  border-bottom: 1px solid var(--app-border);
}

.conf-ayuda {
  margin-top: -8px;
  font-size: 0.75rem;
  color: var(--app-text-muted);
}
</style>
