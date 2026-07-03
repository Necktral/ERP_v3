<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton to="/financiamiento" />
    </div>
    <PageHeader
      title="Riesgo de cartera"
      subtitle="Análisis ASESOR (solo lectura): probabilidad de incumplimiento (PD) por préstamo y simulación Monte Carlo de pérdidas con factor sistémico del café — pérdida esperada y VaR. No registra nada."
      :loading="cargando"
      @refresh="cargar"
    />

    <!-- Controles de simulación -->
    <q-card flat bordered class="app-card q-mb-md">
      <q-card-section class="row items-center q-col-gutter-md">
        <q-input class="col-auto" v-model.number="simulations" type="number" min="1" max="100000" label="Simulaciones" outlined dense style="width: 150px" />
        <q-input class="col-auto" v-model.number="seed" type="number" label="Semilla (reproducible)" outlined dense style="width: 200px" />
        <q-btn unelevated no-caps color="primary" icon="refresh" label="Recalcular" :loading="cargando" @click="cargar" />
        <q-space />
        <q-chip v-if="paquete" dense square :color="paquete.ai_used ? 'primary' : 'grey'" text-color="white" :icon="paquete.ai_used ? 'smart_toy' : 'functions'" :label="paquete.ai_used ? 'PD por modelo (Random Forest)' : 'PD heurística'" />
      </q-card-section>
    </q-card>

    <template v-if="paquete">
      <!-- KPIs -->
      <div class="row q-col-gutter-md q-mb-md">
        <div class="col-6 col-md-3">
          <q-card flat bordered class="app-card kpi">
            <div class="kpi__label">Exposición total</div>
            <div class="kpi__value">{{ paquete.exposicion_total }}</div>
            <div class="kpi__sub">{{ paquete.prestamos_activos }} préstamo(s) · tasa {{ paquete.tipo_cambio }}</div>
          </q-card>
        </div>
        <div class="col-6 col-md-3">
          <q-card flat bordered class="app-card kpi kpi--warn">
            <div class="kpi__label">Pérdida esperada</div>
            <div class="kpi__value">{{ paquete.simulacion?.perdida_esperada ?? '—' }}</div>
            <div class="kpi__sub">{{ paquete.perdida_esperada_pct != null ? paquete.perdida_esperada_pct + '% de la exposición' : 'sin préstamos activos' }}</div>
          </q-card>
        </div>
        <div class="col-6 col-md-3">
          <q-card flat bordered class="app-card kpi kpi--danger">
            <div class="kpi__label">VaR 95%</div>
            <div class="kpi__value">{{ paquete.simulacion?.var_95 ?? '—' }}</div>
            <div class="kpi__sub">pérdida no superada en 95% de escenarios</div>
          </q-card>
        </div>
        <div class="col-6 col-md-3">
          <q-card flat bordered class="app-card kpi kpi--danger">
            <div class="kpi__label">VaR 99%</div>
            <div class="kpi__value">{{ paquete.simulacion?.var_99 ?? '—' }}</div>
            <div class="kpi__sub">cola extrema · máx {{ paquete.simulacion?.perdida_maxima ?? '—' }}</div>
          </q-card>
        </div>
      </div>

      <!-- Detalle por préstamo (módulo dormido: carga completa client-side a propósito) -->
      <q-table
        :rows="paquete.detalle"
        :columns="cols"
        row-key="referencia"
        flat
        bordered
        :pagination="{ rowsPerPage: 20, sortBy: 'pd', descending: true }"
        no-data-label="No hay préstamos activos para analizar."
      >
        <template #body-cell-pd="props">
          <q-td :props="props">
            <q-chip dense square :color="pdColor(props.row.pd)" text-color="white" :label="pctNum(props.row.pd)" />
          </q-td>
        </template>
        <template #body-cell-fuente="props">
          <q-td :props="props">
            <span class="text-muted">{{ props.row.fuente_pd === 'modelo' ? 'Modelo' : 'Heurística' }}</span>
          </q-td>
        </template>
      </q-table>

      <div class="text-caption text-muted q-mt-sm">
        Monte Carlo: {{ paquete.simulacion?.simulaciones ?? 0 }} simulaciones · ρ={{ paquete.simulacion?.rho ?? '—' }} ·
        semilla {{ paquete.simulacion?.seed ?? '—' }} (misma semilla ⇒ mismo resultado). El VaR puede ser 0 aunque la
        pérdida esperada sea positiva cuando la mora es rara: no es un error.
      </div>
    </template>

    <q-card v-else-if="!cargando" flat bordered class="app-card">
      <q-card-section class="text-muted">
        {{ mensaje || 'Sin datos de riesgo.' }}
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import { apiErrorMessage } from 'src/core/api';
import { getPortfolioRisk, type RiskLoanRow, type RiskPackage } from 'src/modules/financiamiento/api';

const $q = useQuasar();
const paquete = ref<RiskPackage | null>(null);
const cargando = ref(false);
const mensaje = ref('');
const simulations = ref(5000);
const seed = ref(42);

function pctNum(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}
function pdColor(pd: number): string {
  if (pd >= 0.5) return 'negative';
  if (pd >= 0.2) return 'warning';
  return 'positive';
}

const cols: QTableColumn<RiskLoanRow>[] = [
  { name: 'referencia', label: 'Referencia', field: 'referencia', align: 'left', sortable: true },
  { name: 'productor', label: 'Productor', field: 'productor', align: 'left', sortable: true },
  { name: 'exposicion', label: 'Exposición', field: 'exposicion', align: 'right', sortable: true },
  { name: 'pd', label: 'PD', field: 'pd', align: 'right', sortable: true },
  { name: 'lgd', label: 'LGD', field: (r) => pctNum(r.lgd), align: 'right' },
  { name: 'fuente', label: 'Fuente PD', field: 'fuente_pd', align: 'left' },
];

async function cargar() {
  cargando.value = true;
  mensaje.value = '';
  try {
    paquete.value = await getPortfolioRisk({ simulations: simulations.value, seed: seed.value });
  } catch (e) {
    paquete.value = null;
    mensaje.value = apiErrorMessage(e, 'No se pudo calcular el riesgo de la cartera.');
    $q.notify({ type: 'negative', message: mensaje.value });
  } finally {
    cargando.value = false;
  }
}

onMounted(cargar);
</script>

<style scoped>
.kpi {
  padding: var(--app-space-4);
}
.kpi__label {
  font-size: 0.78rem;
  color: var(--app-text-muted, #888);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.kpi__value {
  font-size: 1.6rem;
  font-weight: 700;
  font-family: 'Manrope', sans-serif;
  margin-top: 2px;
}
.kpi__sub {
  font-size: 0.78rem;
  color: var(--app-text-muted, #888);
  margin-top: 2px;
}
.kpi--warn .kpi__value {
  color: var(--app-warning, #b8860b);
}
.kpi--danger .kpi__value {
  color: var(--app-negative, #c0392b);
}
</style>
