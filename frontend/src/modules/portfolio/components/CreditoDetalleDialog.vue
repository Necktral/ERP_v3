<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card class="app-dialog cred-det-card">
      <q-card-section class="text-h6">
        Detalle del crédito
        <span v-if="credito" class="text-muted">· {{ credito.contract_number || `#${credito.id}` }}</span>
      </q-card-section>

      <q-card-section v-if="cargando" class="text-center">
        <q-spinner size="2em" color="primary" />
      </q-card-section>

      <q-card-section v-else-if="credito" class="q-pt-none">
        <div class="cred-det-grid">
          <div class="text-muted">Estado</div>
          <div>{{ CREDIT_STATUS_LABELS[credito.credit_status] ?? credito.credit_status }}</div>
          <div class="text-muted">Tipo</div>
          <div>{{ credito.credit_type }}</div>
          <div class="text-muted">Deudor</div>
          <div>{{ nombreParte(credito.borrower_party) }}</div>
          <div class="text-muted">Prestamista</div>
          <div>{{ nombreParte(credito.lender_party) }}</div>
          <div v-if="credito.guarantor_party" class="text-muted">Garante</div>
          <div v-if="credito.guarantor_party">{{ nombreParte(credito.guarantor_party) }}</div>

          <div class="text-muted">Aprobado</div>
          <div>{{ formatMoney(credito.approved_amount) }}</div>
          <div class="text-muted">Desembolsado</div>
          <div>{{ formatMoney(credito.disbursed_amount) }}</div>
          <div class="text-muted">Interés acumulado</div>
          <div>{{ formatMoney(credito.interest_amount) }}</div>
          <div class="text-muted">Abonado</div>
          <div>{{ formatMoney(credito.allocated_amount) }}</div>
          <div class="text-muted">Saldo</div>
          <div class="text-weight-bold">{{ formatMoney(credito.outstanding_amount) }}</div>

          <div class="text-muted">Tasa</div>
          <div>
            {{ credito.interest_rate }} % anual
            <span v-if="credito.interest_calculation_method" class="text-caption text-muted">
              ({{ credito.interest_calculation_method }})
            </span>
          </div>
          <div class="text-muted">Plazo</div>
          <div>
            {{ credito.term_months != null ? `${credito.term_months} meses` : '—' }}
            <span v-if="credito.grace_period_months > 0" class="text-caption text-muted">
              (+{{ credito.grace_period_months }} de gracia)
            </span>
          </div>
          <div class="text-muted">Aprobación</div>
          <div>{{ formatDate(credito.approval_date) }}</div>
          <div class="text-muted">Desembolso</div>
          <div>{{ formatDate(credito.disbursement_date) }}</div>
          <div class="text-muted">Vencimiento</div>
          <div :class="credito.days_past_due > 0 ? 'text-negative' : ''">
            {{ formatDate(credito.maturity_date) }}
            <span v-if="credito.days_past_due > 0" class="text-caption">
              (+{{ credito.days_past_due }} d de mora)
            </span>
          </div>

          <div v-if="credito.collateral_type" class="text-muted">Garantía</div>
          <div v-if="credito.collateral_type">
            {{ credito.collateral_type }}
            <span v-if="credito.collateral_value"> · {{ formatMoney(credito.collateral_value) }}</span>
            <span v-if="credito.loan_to_value_ratio" class="text-caption text-muted">
              (LTV {{ credito.loan_to_value_ratio }} %)
            </span>
          </div>
          <div v-if="credito.restructure_count > 0" class="text-muted">Reestructuras</div>
          <div v-if="credito.restructure_count > 0">{{ credito.restructure_count }}</div>
          <div v-if="credito.notes" class="text-muted">Notas</div>
          <div v-if="credito.notes">{{ credito.notes }}</div>
        </div>

        <template v-if="puedeVerIntereses">
          <div class="cred-det-subtitulo">
            Devengos de interés
            <q-btn
              flat
              dense
              no-caps
              size="sm"
              icon="percent"
              label="Ver todos"
              to="/cartera/intereses"
            />
          </div>
          <q-table
            class="app-table"
            :rows="devengos"
            :columns="columnasDevengo"
            row-key="id"
            flat
            dense
            :loading="cargandoDevengos"
            :pagination="{ rowsPerPage: 5 }"
            no-data-label="Este crédito no tiene devengos registrados."
          />
        </template>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat no-caps label="Cerrar" v-close-popup />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import { apiErrorMessage } from 'src/core/api';
import { formatDate, formatMoney } from 'src/core/format';
import {
  CREDIT_STATUS_LABELS,
  getCredit,
  listInterestAccruals,
  type Credit,
  type InterestAccrual,
} from 'src/modules/portfolio/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const props = defineProps<{
  modelValue: boolean;
  /** Id del crédito a detallar (se refresca del backend al abrir). */
  creditoId: number | null;
  /** Nombres de terceros ya cargados por la página (opcional). */
  nombresParte?: Map<number, string>;
}>();

const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>();

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const cargando = ref(false);
const cargandoDevengos = ref(false);
const credito = ref<Credit | null>(null);
const devengos = ref<InterestAccrual[]>([]);

const puedeVerIntereses = ref(false);

function nombreParte(partyId: number): string {
  return props.nombresParte?.get(partyId) ?? `Tercero #${partyId}`;
}

const columnasDevengo: QTableColumn<InterestAccrual>[] = [
  { name: 'fecha', label: 'Devengo', field: (r) => formatDate(r.accrual_date), align: 'left' },
  {
    name: 'periodo',
    label: 'Período',
    field: (r) => `${formatDate(r.period_start)} – ${formatDate(r.period_end)}`,
    align: 'left',
  },
  { name: 'interes', label: 'Interés', field: (r) => formatMoney(r.accrued_interest), align: 'right' },
  {
    name: 'capitalizado',
    label: 'Capitalización',
    field: (r) => (r.is_capitalized ? 'Capitalizado' : 'Pendiente'),
    align: 'left',
  },
];

async function cargar(id: number) {
  const companyId = ctx.activeCompanyId;
  puedeVerIntereses.value = companyId
    ? acl.hasPermission(companyId, 'portfolio.interest.read')
    : false;

  credito.value = null;
  devengos.value = [];
  cargando.value = true;
  try {
    credito.value = await getCredit(id);
  } catch (e) {
    emit('update:modelValue', false);
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el crédito.') });
    return;
  } finally {
    cargando.value = false;
  }

  if (puedeVerIntereses.value) {
    cargandoDevengos.value = true;
    try {
      devengos.value = await listInterestAccruals({ credit: id });
    } catch {
      /* los devengos son complemento: el detalle del crédito ya está pintado */
    } finally {
      cargandoDevengos.value = false;
    }
  }
}

watch(
  () => [props.modelValue, props.creditoId] as const,
  ([abierto, id]) => {
    if (abierto && id != null) void cargar(id);
  },
);
</script>

<style scoped>
.cred-det-card {
  width: 640px;
  max-width: 95vw;
}

.cred-det-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 16px;
}

.cred-det-subtitulo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  margin-top: var(--app-space-3);
  margin-bottom: var(--app-space-2);
}
</style>
