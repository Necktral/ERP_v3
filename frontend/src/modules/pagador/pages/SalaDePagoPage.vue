<template>
  <q-page class="app-page sala">
    <!-- Barra superior COMPACTA: solo lo operativo (estado, sincronizar, refrescar) + ⓘ con la
         descripción. La app va sin ruido visual: la pantalla arranca directo en los controles. -->
    <div class="sala-topbar">
      <q-chip
        dense
        square
        :icon="online ? 'wifi' : 'wifi_off'"
        :style="{ background: online ? 'var(--app-accent-teal)' : 'var(--app-accent-coral)', color: '#fff' }"
        :label="online ? 'En línea' : 'Sin conexión'"
      />
      <q-chip dense square outline :icon="backend === 'sqlite' ? 'storage' : 'sd_storage'"
        :label="backend === 'sqlite' ? 'SQLite' : 'Local'">
        <q-tooltip>{{ backend === 'sqlite' ? 'Datos guardados en SQLite del dispositivo' : 'Respaldo local (SQLite no disponible)' }}</q-tooltip>
      </q-chip>
      <q-chip dense square outline icon="schedule" :label="`Sync: ${ultimaSyncLabel}`">
        <q-tooltip>Última sincronización con el servidor: {{ ultimaSyncExacta }}</q-tooltip>
      </q-chip>
      <q-btn
        v-if="cola.pending + cola.failed > 0"
        unelevated
        no-caps
        color="primary"
        icon="sync"
        :label="`Sincronizar (${cola.pending + cola.failed})`"
        :loading="sincronizando"
        @click="sincronizar"
      />
      <q-btn flat round icon="refresh" :loading="cargando" aria-label="Actualizar" @click="cargarResumen" />
      <q-btn flat round icon="info_outline" aria-label="Información">
        <q-menu anchor="bottom right" self="top right">
          <div class="sala-info">
            <div class="sala-info__title">Cobrador-Pagador (CO-PA)</div>
            <div class="sala-info__text">
              Paga al trabajador y cobra sus deudas internas (comisariato, préstamo personal) al pagar.
              El documento legal lleva solo INSS/IR; el cobro es interno y multi-empresa.
            </div>
            <q-separator spaced />
            <div class="sala-info__title">Estado offline</div>
            <div class="sala-estado">
              <div><span>Conexión</span><b>{{ online ? 'En línea' : 'Sin conexión' }}</b></div>
              <div><span>Almacenamiento</span><b>{{ backend === 'sqlite' ? 'SQLite (dispositivo)' : 'Local (respaldo)' }}</b></div>
              <div><span>Pagos en cola</span><b>{{ cola.pending }} pendiente(s) · {{ cola.failed }} fallido(s)</b></div>
              <div><span>Última sincronización</span><b>{{ ultimaSyncExacta }}</b></div>
              <div v-if="storeError" class="sala-estado__warn">SQLite no disponible: {{ storeError }}</div>
            </div>
          </div>
        </q-menu>
      </q-btn>
    </div>

    <!-- Selector de período + búsqueda -->
    <div class="sala-controls">
      <q-select
        v-model="periodoSel"
        outlined
        dense
        emit-value
        map-options
        label="Período a pagar"
        :options="periodoOpciones"
        :loading="cargandoPeriodos"
        style="min-width: 280px"
        @update:model-value="cargarResumen"
      />
      <q-input
        v-model="busqueda"
        outlined
        dense
        clearable
        debounce="200"
        placeholder="Buscar por carnet, nombre o cédula…"
        style="min-width: 280px; flex: 1"
      >
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-toggle v-model="soloPendientes" label="Solo pendientes" left-label dense class="sala-toggle" />
    </div>

    <!-- Totales del período -->
    <div v-if="resumen" class="sala-stats">
      <div class="sala-stat" style="--grad: var(--app-stat-blue)">
        <div class="sala-stat__label">Empleados</div>
        <div class="sala-stat__value">{{ filtradas.length }}</div>
      </div>
      <div class="sala-stat" style="--grad: var(--app-stat-teal)">
        <div class="sala-stat__label">Neto a entregar</div>
        <div class="sala-stat__value">{{ money(totales.neto) }}</div>
      </div>
      <div class="sala-stat" style="--grad: var(--app-stat-amber)">
        <div class="sala-stat__label">Recaudado (cobros)</div>
        <div class="sala-stat__value">{{ money(totales.recaudado) }}</div>
      </div>
      <div class="sala-stat" style="--grad: var(--app-stat-violet)">
        <div class="sala-stat__label">Pendiente de pagar</div>
        <div class="sala-stat__value">{{ money(totales.pendiente) }}</div>
      </div>
    </div>

    <!-- Lista de empleados -->
    <template v-if="resumen">
    <div class="sala-grid">
      <q-card
        v-for="row in filtradasVisibles"
        :key="row.employee_key"
        flat
        bordered
        class="emp-card"
        :style="{ '--acc': accPlanilla(row) }"
        @click="abrirDetalle(row)"
      >
        <div class="emp-card__top">
          <div class="emp-ini" :style="{ background: accPlanilla(row) }">{{ inicial(row.full_name) }}</div>
          <div class="emp-id">
            <div class="emp-nombre">{{ row.full_name }}</div>
            <div class="emp-sub">
              <span v-if="row.worker_code" class="emp-carnet"><q-icon name="badge" size="13px" /> {{ row.worker_code }}</span>
              <span v-if="row.cedula"> · {{ row.cedula }}</span>
              <span v-else-if="row.employee_code"> · #{{ row.employee_code }}</span>
              <span v-if="row.cargo"> · {{ row.cargo }}</span>
            </div>
          </div>
          <q-badge v-if="estadoLocal(row)" :color="estadoLocal(row) === 'pendiente' ? 'orange' : 'green'" align="top">
            {{ estadoLocal(row) === 'pendiente' ? 'por sincronizar' : 'sincronizado' }}
          </q-badge>
        </div>

        <div v-if="row.ubicacion" class="emp-ubic">
          <q-icon name="place" size="14px" />
          <span class="emp-ubic__loc">{{ row.ubicacion }}</span>
          <span v-if="row.sheets.length === 1 && row.sheets[0]" class="emp-ubic__pos">
            · Hoja {{ row.sheets[0].print_page }} · No. {{ row.sheets[0].print_no }}
          </span>
        </div>

        <div class="emp-chips">
          <q-chip
            v-for="p in row.planillas"
            :key="p"
            dense
            square
            :style="{ background: p === 'CON INSS' ? 'var(--app-accent-teal)' : 'var(--app-accent-amber)', color: '#fff' }"
            :label="p"
          />
          <q-chip v-if="row.complement" dense square :style="{ background: 'var(--app-accent-violet)', color: '#fff' }" label="Complemento" />
        </div>

        <div class="emp-neto">
          <span class="emp-neto__label">Neto a entregar</span>
          <span class="emp-neto__value">{{ money(row.totales.neto_total_a_entregar) }}</span>
        </div>
        <div v-if="Number(row.totales.neto_total_a_entregar) <= 0" class="emp-nada">
          <q-icon name="remove_circle_outline" /> Sin neto a entregar
        </div>
        <div v-else-if="Number(row.totales.pendiente) <= 0" class="emp-pagado">
          <q-icon name="check_circle" /> Pagado completo
        </div>
        <div v-else class="emp-pend">Pendiente: {{ money(row.totales.pendiente) }}</div>
      </q-card>
    </div>

    <!-- Render incremental: cargar más tarjetas (planillas grandes) sin trabar el DOM. -->
    <div v-if="hayMas" class="sala-mas">
      <q-btn flat no-caps color="primary" icon="expand_more"
        :label="`Mostrar más (${filtradas.length - filtradasVisibles.length} restantes)`" @click="mostrarMas" />
      <span class="sala-mas__count">Mostrando {{ filtradasVisibles.length }} de {{ filtradas.length }}</span>
    </div>
    </template>

    <q-banner v-else-if="!cargando" rounded class="sala-empty">
      <template #avatar>
        <q-icon :name="periodosError ? 'error' : 'point_of_sale'" :color="periodosError ? 'negative' : 'primary'" />
      </template>
      <span v-if="periodosError">{{ periodosError }}</span>
      <span v-else-if="periodos.length === 0">
        Esta empresa no tiene períodos <strong>aprobados o pagados</strong>. Aprobá una planilla en
        Nómina o cambiá de empresa en la barra de arriba.
      </span>
      <span v-else>
        Elegí un período <strong>aprobado o pagado</strong> para ver el resumen de la sala de pago.
      </span>
      <template v-if="periodosError" #action>
        <q-btn flat no-caps color="primary" label="Reintentar" @click="cargarPeriodos" />
      </template>
    </q-banner>

    <!-- Detalle del empleado -->
    <q-dialog v-model="detalleOpen">
      <q-card v-if="detalle" class="emp-dialog" :style="{ '--acc': accPlanilla(detalle) }">
        <q-card-section class="emp-dialog__head">
          <div class="emp-ini emp-ini--lg" :style="{ background: accPlanilla(detalle) }">{{ inicial(detalle.full_name) }}</div>
          <div>
            <div class="text-h6">{{ detalle.full_name }}</div>
            <div class="emp-sub">
              <span v-if="detalle.worker_code" class="emp-carnet"><q-icon name="badge" size="13px" /> {{ detalle.worker_code }}</span>
              <span v-if="detalle.employee_code"> · #{{ detalle.employee_code }}</span>
              <span v-if="detalle.inss_number"> · INSS {{ detalle.inss_number }}</span>
              <span v-if="detalle.cedula"> · {{ detalle.cedula }}</span>
            </div>
          </div>
        </q-card-section>

        <q-separator />

        <q-card-section class="emp-dialog__body">
          <!-- Planillas legales -->
          <div v-for="s in detalle.sheets" :key="s.entry_id" class="planilla-bloque" :style="{ '--acc': s.has_inss ? 'var(--app-accent-teal)' : 'var(--app-accent-amber)' }">
            <div class="planilla-head">
              <q-chip dense square :style="{ background: 'var(--acc)', color: '#fff' }" :label="s.has_inss ? 'CON INSS' : 'SIN INSS'" />
              <span class="planilla-nombre">{{ s.sheet_name }}</span>
              <q-space />
              <span class="planilla-neto">{{ money(s.net_to_pay) }}</span>
            </div>
            <div class="planilla-ubic">
              <q-icon name="place" size="15px" />
              <span class="planilla-ubic__loc">{{ s.location }}</span>
              <span class="planilla-ubic__pos">Hoja {{ s.print_page }} · No. {{ s.print_no }}</span>
            </div>
            <div class="ded-grid">
              <div><span>Devengado</span><b>{{ money(s.total_devengado) }}</b></div>
              <div v-if="Number(s.deductions.inss_laboral) > 0"><span>INSS laboral</span><b>−{{ money(s.deductions.inss_laboral) }}</b></div>
              <div v-if="Number(s.deductions.ir_amount) > 0"><span>IR</span><b>−{{ money(s.deductions.ir_amount) }}</b></div>
              <div v-if="Number(s.deductions.advance_deduction) > 0"><span>Adelanto</span><b>−{{ money(s.deductions.advance_deduction) }}</b></div>
            </div>
            <div class="planilla-foot">
              <span v-if="Number(s.already_paid) > 0" class="planilla-pagado">Pagado: {{ money(s.already_paid) }}</span>
              <q-space />
              <template v-if="Number(s.remaining) > 0">
                <span class="planilla-rest">Resta {{ money(s.remaining) }}</span>
                <q-btn unelevated no-caps size="sm" color="primary" icon="payments" label="Pagar" @click="abrirPago(detalle, s)" />
              </template>
              <template v-else>
                <q-chip dense square :style="{ background: 'var(--app-accent-teal)', color: '#fff' }" icon="check" label="Pagado" />
                <q-btn v-if="puedeEditarPago(detalle, s)" flat no-caps size="sm" color="primary" icon="edit"
                  label="Editar pago" @click="abrirPago(detalle, s, true)" />
              </template>
            </div>
          </div>

          <!-- Complemento -->
          <div v-if="detalle.complement" class="planilla-bloque" style="--acc: var(--app-accent-violet)">
            <div class="planilla-head">
              <q-chip dense square :style="{ background: 'var(--acc)', color: '#fff' }" label="Complemento" />
              <span class="planilla-nombre">Complemento de salario</span>
              <q-space />
              <span class="planilla-neto">{{ money(detalle.complement.amount_nio) }}</span>
            </div>
            <div class="planilla-foot">
              <q-space />
              <q-chip dense square :color="detalle.complement.received ? 'green' : 'orange'" text-color="white"
                :label="detalle.complement.received ? 'Recibido' : 'Pendiente de entregar'" />
            </div>
          </div>

          <!-- Saldos pendientes (deuda interna viva: comisariato + préstamo personal) -->
          <div v-if="deudaDe(detalle).total > 0" class="saldos">
            <div class="saldos__title">Saldos pendientes</div>
            <div class="saldos__row ded--comisariato" v-if="deudaDe(detalle).comisariato > 0">
              <span><q-icon name="storefront" size="15px" /> Comisariato</span>
              <b>{{ money(deudaDe(detalle).comisariato) }}</b>
            </div>
            <div class="saldos__row ded--prestamo" v-if="deudaDe(detalle).prestamo > 0">
              <span><q-icon name="request_quote" size="15px" /> Préstamo personal</span>
              <b>{{ money(deudaDe(detalle).prestamo) }}</b>
            </div>
            <div class="saldos__total">
              <span>Total pendiente</span>
              <span class="saldos__total-value">{{ money(deudaDe(detalle).total) }}</span>
            </div>
          </div>
          <q-banner v-else-if="!detalle.worker_code && !detalle.cedula" dense class="copa-nodebt">
            Sin <strong>carnet</strong> ni cédula → no se pueden cruzar sus deudas. Asignale el carnet en Recursos Humanos.
          </q-banner>

        </q-card-section>

        <q-separator />

        <q-card-section class="emp-dialog__total">
          <span>NETO A ENTREGAR</span>
          <span class="emp-dialog__total-value">{{ money(detalle.totales.neto_total_a_entregar) }}</span>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat no-caps icon="print" label="Imprimir recibo" @click="imprimirRecibo(detalle)" />
          <q-btn flat no-caps label="Cerrar" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: Cobrar y pagar (asistente por pasos con teclado numérico) -->
    <q-dialog v-model="pagoOpen">
      <q-card v-if="pago" class="pago-dialog">
        <q-card-section class="pago-head">
          <div class="text-h6">{{ pago.modoRectificar ? 'Rectificar pago' : tieneDeuda ? 'Cobrar y pagar' : 'Pagar' }}</div>
          <div class="emp-sub">{{ pago.row.full_name }} — {{ pago.sheet.sheet_name }}</div>
          <q-banner v-if="pago.modoRectificar" dense class="copa-rectaviso">
            Editás un pago ya aplicado: al confirmar se <strong>anula el recibo anterior</strong> y se reimprime el corregido.
          </q-banner>
          <div v-if="pasos.length > 1" class="pago-pasos">
            <span v-for="(p, i) in pasos" :key="p" class="pago-paso" :class="{ 'pago-paso--on': i === pasoIdx, 'pago-paso--done': i < pasoIdx }">
              {{ p === 'comisariato' ? 'Comisariato' : p === 'prestamo' ? 'Préstamo' : 'Resumen' }}
            </span>
          </div>
        </q-card-section>

        <!-- Paso: abono al comisariato -->
        <q-card-section v-if="pasoActual === 'comisariato'" class="app-form">
          <div class="copa-deuda__head" style="--acc: var(--app-accent-coral)">
            <q-icon name="storefront" /> Comisariato · deuda {{ money(pago.comisariato) }}
          </div>
          <div class="kp-display">
            <span class="kp-display__label">Abona al comisariato</span>
            <span class="kp-display__value">C$ {{ pagoForm.abonoComisariato || '0' }}</span>
          </div>
          <NumericKeypad v-model="pagoForm.abonoComisariato" :max="topeComisariato" accent="var(--app-accent-coral)" />
          <div class="kp-hint">Máx. cobrable C$ {{ money(topeComisariato) }} · 0 si no puede abonar.</div>
        </q-card-section>

        <!-- Paso: abono al préstamo personal -->
        <q-card-section v-else-if="pasoActual === 'prestamo'" class="app-form">
          <div class="copa-deuda__head" style="--acc: var(--app-accent-violet)">
            <q-icon name="request_quote" /> Préstamo personal · deuda {{ money(pago.prestamo) }}
          </div>
          <div class="kp-display">
            <span class="kp-display__label">Abona al préstamo</span>
            <span class="kp-display__value">C$ {{ pagoForm.abonoPrestamo || '0' }}</span>
          </div>
          <NumericKeypad v-model="pagoForm.abonoPrestamo" :max="topePrestamo" accent="var(--app-accent-violet)" />
          <div class="kp-hint">Máx. cobrable C$ {{ money(topePrestamo) }} · 0 si no puede abonar.</div>
        </q-card-section>

        <!-- Paso: resumen y confirmación -->
        <q-card-section v-else class="app-form">
          <div class="copa-row"><span>Salario devengado</span><b>{{ money(pago.sheet.total_devengado) }}</b></div>
          <div class="copa-row"><span>Neto legal (devengado − INSS/IR)</span><b>{{ money(pago.netoLegal) }}</b></div>
          <div v-if="Number(pagoForm.abonoComisariato) > 0" class="copa-row ded--comisariato">
            <span>Abono comisariato</span><b>−{{ money(pagoForm.abonoComisariato) }}</b>
          </div>
          <div v-if="Number(pagoForm.abonoPrestamo) > 0" class="copa-row ded--prestamo">
            <span>Abono préstamo</span><b>−{{ money(pagoForm.abonoPrestamo) }}</b>
          </div>
          <q-banner v-if="!tieneDeuda" dense class="copa-nodebt">
            <template v-if="!pago.row.worker_code && !pago.row.cedula">Sin <strong>carnet</strong> ni cédula → no se cruzan deudas. Se entrega el neto completo.</template>
            <template v-else>Sin deudas internas: se entrega el neto completo.</template>
          </q-banner>
          <q-select v-model="pagoForm.method" outlined dense emit-value map-options label="Método de pago" :options="metodos" />
          <q-input v-if="pago.modoRectificar" v-model="pagoForm.motivo" outlined dense type="textarea" autogrow
            label="Motivo de la rectificación" hint="Obligatorio: por qué se corrige (queda en la auditoría y en el recibo)."
            :rules="[(v) => !!(v && v.trim()) || 'Indicá el motivo']" />
          <div class="copa-total">
            <span>Neto a entregar</span>
            <span class="copa-total__value">{{ money(netoEntregar) }}</span>
          </div>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn v-if="pasoIdx > 0" flat no-caps icon="chevron_left" label="Atrás" @click="pasoAtras" />
          <q-btn v-if="!esUltimoPaso" unelevated no-caps color="primary" icon-right="chevron_right" label="Siguiente" @click="pasoSiguiente" />
          <q-btn v-else unelevated no-caps color="primary" :icon="pago.modoRectificar ? 'verified' : 'payments'"
            :label="pago.modoRectificar ? 'Rectificar y reimprimir' : tieneDeuda ? 'Cobrar y pagar' : 'Pagar'"
            :loading="pagando" @click="confirmarPago" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import NumericKeypad from 'src/components/NumericKeypad.vue';
import { useConnectivity } from 'src/core/connectivity';
import { useContextStore } from 'src/stores/context.store';
import { STORAGE_KEYS } from 'src/core/storage/keys';
import { apiErrorMessage } from 'src/core/api';
import { formatMoney } from 'src/core/format';
import { listPeriods, type PayrollPeriod } from 'src/modules/nomina/api';
import {
  cobrarYPagar,
  rectificarCobro,
  getDeudasPlanilla,
  getPaySummary,
  payEntry,
  type DeudaRow,
  type PayMethod,
  type PaySummaryResponse,
  type PaySummaryRow,
  type PaySummarySheet,
} from 'src/modules/pagador/api';
import { getPayrollStore, getStoreError } from 'src/modules/pagador/offline/store';
import {
  buildPaymentCommand,
  drainQueue,
  enqueuePayment,
  periodKey,
  queueStats,
  type PayrollPaymentCommand,
  type PayrollStore,
} from 'src/modules/pagador/offline/queue';

const $q = useQuasar();
const ctx = useContextStore();
const { online } = useConnectivity();

const ACENTOS = ['blue', 'teal', 'violet', 'amber', 'coral'] as const;
const metodos = [
  { label: 'Efectivo', value: 'CASH' as PayMethod },
  { label: 'Transferencia', value: 'BANK_TRANSFER' as PayMethod },
  { label: 'Cheque', value: 'CHECK' as PayMethod },
];
const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];

const cargando = ref(false);
const cargandoPeriodos = ref(false);
const sincronizando = ref(false);
const pagando = ref(false);
const periodos = ref<PayrollPeriod[]>([]);
const periodosError = ref('');
const periodoSel = ref<number | null>(null);
const resumen = ref<PaySummaryResponse | null>(null);
const busqueda = ref('');
const soloPendientes = ref(false);
const backend = ref<'sqlite' | 'memory'>('memory');
const storeError = ref('');
const ultimaSync = ref<string | null>(localStorage.getItem(STORAGE_KEYS.PAGADOR_LAST_SYNC));
const cola = ref({ pending: 0, failed: 0, done: 0 });

// Marca y persiste "última vez que la cola SQLite subió al servidor" (indicador para el cajero).
function marcarSync() {
  const iso = new Date().toISOString();
  ultimaSync.value = iso;
  localStorage.setItem(STORAGE_KEYS.PAGADOR_LAST_SYNC, iso);
}
const ultimaSyncLabel = computed(() => {
  if (!ultimaSync.value) return 'Nunca';
  const d = new Date(ultimaSync.value);
  const min = Math.round((Date.now() - d.getTime()) / 60000);
  if (min < 1) return 'hace instantes';
  if (min < 60) return `hace ${min} min`;
  return d.toLocaleString('es-NI', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
});
const ultimaSyncExacta = computed(() =>
  ultimaSync.value ? new Date(ultimaSync.value).toLocaleString('es-NI') : 'Sin sincronizaciones aún',
);
const comandosPorEntry = ref<Map<number, PayrollPaymentCommand>>(new Map());

const detalleOpen = ref(false);
const detalle = ref<PaySummaryRow | null>(null);
const pagoOpen = ref(false);
const pago = ref<{
  row: PaySummaryRow; sheet: PaySummarySheet; netoLegal: number; comisariato: number; prestamo: number;
  modoRectificar: boolean; // true cuando se EDITA un cobro ya aplicado (anula el recibo previo)
} | null>(null);
const pagoForm = ref<{ method: PayMethod; abonoComisariato: string; abonoPrestamo: string; motivo: string }>({
  method: 'CASH',
  abonoComisariato: '',
  abonoPrestamo: '',
  motivo: '',
});
// Saldos de deuda interna por entry (comisariato/préstamo), para negociar el abono al pagar.
const deudasPorEntry = ref<Map<number, DeudaRow>>(new Map());
// Wizard de cobro: pasos dinámicos (comisariato → préstamo → resumen) con teclado numérico.
const pasoIdx = ref(0);

let store: PayrollStore | null = null;

const companyId = computed(() => Number(ctx.activeCompanyId) || 0);
const branchId = computed(() => (ctx.activeBranchId ? Number(ctx.activeBranchId) : null));

const periodoOpciones = computed(() =>
  periodos.value.map((p) => ({
    label: `${MESES[p.month - 1] ?? p.month} ${p.year} — ${etiquetaTipo(p.period_type)} (${estadoTxt(p.status)})`,
    value: p.id,
  })),
);

const filtradas = computed(() => {
  let rows = resumen.value?.results ?? [];
  if (soloPendientes.value) {
    // Solo los que TIENEN algo por entregar y aún no se pagó completo.
    rows = rows.filter(
      (r) => Number(r.totales.neto_total_a_entregar) > 0 && Number(r.totales.pendiente) > 0,
    );
  }
  const q = busqueda.value.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter(
    (r) =>
      r.full_name.toLowerCase().includes(q) ||
      r.cedula.toLowerCase().includes(q) ||
      (r.worker_code || '').toLowerCase().includes(q) ||
      r.inss_number.toLowerCase().includes(q) ||
      r.employee_code.toLowerCase().includes(q),
  );
});

// Render INCREMENTAL: en planillas grandes (200+) no pintamos todas las tarjetas de golpe (traba el
// DOM). Mostramos un tope y "Mostrar más". Se resetea al cambiar filtro/empresa/período, NO al pagar
// (para no perder la posición mientras se cobra fila por fila).
const LOTE_VISIBLE = 60;
const visibles = ref(LOTE_VISIBLE);
const filtradasVisibles = computed(() => filtradas.value.slice(0, visibles.value));
const hayMas = computed(() => filtradas.value.length > visibles.value);
function mostrarMas() {
  visibles.value += LOTE_VISIBLE;
}
watch([busqueda, soloPendientes, periodoSel], () => {
  visibles.value = LOTE_VISIBLE;
});

// Cobro registrado en una fila = Σ (comisariato + préstamo) de sus hojas (campos del entry).
function cobroDe(row: PaySummaryRow): number {
  return row.sheets.reduce(
    (a, s) => a + Number(s.deductions.store_credit_deduction || 0) + Number(s.deductions.loan_payment || 0),
    0,
  );
}

const totales = computed(() => {
  const rows = filtradas.value;
  const sum = (f: (r: PaySummaryRow) => string) => rows.reduce((acc, r) => acc + Number(f(r) || 0), 0);
  return {
    neto: sum((r) => r.totales.neto_total_a_entregar),
    recaudado: rows.reduce((acc, r) => acc + cobroDe(r), 0),
    pendiente: sum((r) => r.totales.pendiente),
  };
});

function money(v: string | number): string {
  return formatMoney(v);
}

function inicial(name: string): string {
  return (name.trim()[0] ?? '?').toUpperCase();
}

function accPlanilla(row: PaySummaryRow): string {
  const key = row.employee_key || row.full_name;
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return `var(--app-accent-${ACENTOS[h % ACENTOS.length] ?? 'blue'})`;
}

function etiquetaTipo(t: string): string {
  return { FIRST_HALF: '1ª quincena', SECOND_HALF: '2ª quincena', CATORCENA: 'catorcena', MONTHLY: 'mensual' }[t] ?? t;
}

function estadoTxt(s: string): string {
  return { APPROVED: 'aprobado', PAID: 'pagado', CLOSED: 'cerrado' }[s] ?? s;
}

function estadoLocal(row: PaySummaryRow): 'pendiente' | 'sincronizado' | null {
  for (const s of row.sheets) {
    const cmd = comandosPorEntry.value.get(s.entry_id);
    if (cmd && cmd.status !== 'DONE' && cmd.status !== 'FAILED') return 'pendiente';
    if (cmd && cmd.status === 'DONE') return 'sincronizado';
  }
  return null;
}

async function refrescarCola() {
  if (!store) return;
  const cmds = await store.listCommands();
  const map = new Map<number, PayrollPaymentCommand>();
  for (const c of cmds) map.set(c.entry_id, c);
  comandosPorEntry.value = map;
  const stats = queueStats(cmds);
  cola.value = { pending: stats.pending, failed: stats.failed, done: stats.done };
}

// Período RECORDADO, POR EMPRESA: cada empresa recuerda su último período (un mapa
// {company_id: period_id}). Así, al cambiar de empresa NO se pisa el recordado de la otra.
function leerPeriodoGuardado(cid: number): number {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.PAGADOR_PERIOD_ID);
    if (!raw) return 0;
    const map = JSON.parse(raw);
    // Compat: si quedó el formato viejo (un número suelto), úsalo igual.
    if (typeof map === 'number') return map;
    return Number(map?.[String(cid)] || 0);
  } catch {
    return 0;
  }
}
function guardarPeriodo(cid: number, pid: number) {
  if (!cid || !pid) return;
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.PAGADOR_PERIOD_ID);
    let map: Record<string, number> = {};
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') map = parsed as Record<string, number>;
    }
    map[String(cid)] = pid;
    localStorage.setItem(STORAGE_KEYS.PAGADOR_PERIOD_ID, JSON.stringify(map));
  } catch {
    /* almacenamiento no disponible: el período sigue funcionando en memoria */
  }
}

// Caché offline de la lista de períodos por empresa (para que el selector no quede vacío sin red).
function guardarPeriodosCache(cid: number, lista: PayrollPeriod[]) {
  if (!cid) return;
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.PAGADOR_PERIODS);
    const map = raw ? (JSON.parse(raw) as Record<string, PayrollPeriod[]>) : {};
    map[String(cid)] = lista;
    localStorage.setItem(STORAGE_KEYS.PAGADOR_PERIODS, JSON.stringify(map));
  } catch { /* almacenamiento no disponible: la lista sigue en memoria */ }
}
function leerPeriodosCache(cid: number): PayrollPeriod[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.PAGADOR_PERIODS);
    if (!raw) return [];
    return (JSON.parse(raw) as Record<string, PayrollPeriod[]>)[String(cid)] ?? [];
  } catch { return []; }
}
// Caché offline de deudas (comisariato/préstamo) por período, para el wizard de cobro sin red.
function guardarDeudasCache(pid: number, deudas: DeudaRow[]) {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.PAGADOR_DEUDAS);
    const map = raw ? (JSON.parse(raw) as Record<string, DeudaRow[]>) : {};
    map[String(pid)] = deudas;
    localStorage.setItem(STORAGE_KEYS.PAGADOR_DEUDAS, JSON.stringify(map));
  } catch { /* almacenamiento no disponible */ }
}
function leerDeudasCache(pid: number): DeudaRow[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.PAGADOR_DEUDAS);
    if (!raw) return [];
    return (JSON.parse(raw) as Record<string, DeudaRow[]>)[String(pid)] ?? [];
  } catch { return []; }
}
// Período RECORDADO: si ya se eligió uno antes EN ESTA EMPRESA (y sigue disponible), se selecciona
// solo → no re-elegir cada vez. Si no, cae al más reciente.
function seleccionarPeriodoRecordado() {
  if (periodoSel.value) return;
  const guardado = leerPeriodoGuardado(companyId.value);
  const valido = guardado && periodos.value.some((p) => p.id === guardado);
  periodoSel.value = valido ? guardado : (periodos.value[0]?.id ?? null);
}

async function cargarPeriodos() {
  cargandoPeriodos.value = true;
  periodosError.value = '';
  try {
    const aprobados = await listPeriods({ status: 'APPROVED' });
    const pagados = await listPeriods({ status: 'PAID' });
    periodos.value = [...aprobados, ...pagados].sort((a, b) => b.id - a.id);
    guardarPeriodosCache(companyId.value, periodos.value); // cachear para offline
    seleccionarPeriodoRecordado();
  } catch (e) {
    // Offline / red caída: usar la lista cacheada (offline-first) en vez de quedar con el selector vacío.
    const cache = leerPeriodosCache(companyId.value);
    if (cache.length > 0) {
      periodos.value = cache;
      seleccionarPeriodoRecordado();
    } else {
      periodosError.value = apiErrorMessage(e, 'No se pudieron cargar los períodos de planilla.');
      if (online.value) $q.notify({ type: 'negative', message: periodosError.value });
    }
  } finally {
    cargandoPeriodos.value = false;
  }
}

async function cargarResumen() {
  // El resumen ONLINE no debe depender del store offline (en web puede no estar disponible).
  if (!periodoSel.value) return;
  const periodId = periodoSel.value; // fija el período de ESTA carga (evita pisar si el usuario cambia)
  const key = periodKey(companyId.value, branchId.value, periodId);
  cargando.value = true;

  // 1) Caché INSTANTÁNEA (stale-while-revalidate): pinta de inmediato lo último guardado → la
  //    re-entrada se siente instantánea; abajo se revalida y reemplaza con lo fresco.
  if (store) {
    try {
      const cached = await store.readSummary(key);
      if (cached && periodoSel.value === periodId) resumen.value = cached;
    } catch { /* sin caché: sigue */ }
  }

  let deudasP: Promise<void> | null = null;
  try {
    if (online.value) {
      // 2) Deudas en PARALELO y en 2.º plano: solo se usan al abrir el diálogo de pago, NO deben
      //    bloquear el pintado de la lista ni el spinner. Se resuelven después.
      deudasP = getDeudasPlanilla(periodId).then(
        (deudas) => {
          if (periodoSel.value === periodId) deudasPorEntry.value = new Map(deudas.map((d) => [d.entry_id, d]));
          guardarDeudasCache(periodId, deudas); // cachear para el wizard de cobro offline
        },
        () => { if (periodoSel.value === periodId) deudasPorEntry.value = new Map(); },
      );
      // 3) Resumen: apenas vuelve, la lista aparece (el spinner se apaga en finally).
      const data = await getPaySummary(periodId, branchId.value ? { branch: branchId.value } : {});
      if (periodoSel.value === periodId) resumen.value = data;
      if (store) await store.cacheSummary(key, data);
    } else if (store) {
      resumen.value = await store.readSummary(key);
      // Deudas desde caché para poder cobrar offline (degrada a 0 si no hay caché).
      deudasPorEntry.value = new Map(leerDeudasCache(periodId).map((d) => [d.entry_id, d]));
      if (!resumen.value) $q.notify({ type: 'warning', message: 'Sin conexión y sin caché de este período.' });
    } else {
      $q.notify({ type: 'warning', message: 'Sin conexión y sin almacenamiento local disponible.' });
    }
  } catch (e) {
    // Falla la red en medio: conservar la caché ya pintada; si no había, intentar leerla.
    if (!resumen.value) resumen.value = store ? await store.readSummary(key) : null;
    if (!resumen.value) $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el resumen.') });
  } finally {
    await refrescarCola();
    cargando.value = false; // spinner OFF apenas está el resumen (las deudas siguen en 2.º plano)
  }
  if (deudasP) void deudasP; // no se espera: termina sola y actualiza las deudas cuando llegue
}

// Actualización LOCAL optimista tras pagar: la tarjeta queda "Pagado" y la deuda baja AL INSTANTE,
// sin esperar un refetch. La fórmula de deuda (revertir abono viejo + aplicar nuevo) cubre los 3
// casos: cobro (viejo=0), rectificación (viejo=abono previo) y pago simple (abonos=0).
function aplicarPagoLocal(
  sel: { sheet: PaySummarySheet },
  opts: { neto: number; abonoCom: number; abonoPre: number; reemplazaPago?: boolean },
) {
  const s = sel.sheet;
  const oldCom = Number(s.deductions.store_credit_deduction || 0);
  const oldPre = Number(s.deductions.loan_payment || 0);
  s.net_to_pay = opts.neto.toFixed(2);
  s.already_paid = (opts.reemplazaPago ? opts.neto : Number(s.already_paid || 0) + opts.neto).toFixed(2);
  s.remaining = '0.00';
  s.paid = opts.neto > 0;
  s.deductions.store_credit_deduction = opts.abonoCom.toFixed(2);
  s.deductions.loan_payment = opts.abonoPre.toFixed(2);
  const d = deudasPorEntry.value.get(s.entry_id);
  if (d) {
    deudasPorEntry.value.set(s.entry_id, {
      ...d,
      comisariato_saldo: Math.max(0, Number(d.comisariato_saldo || 0) + oldCom - opts.abonoCom).toFixed(2),
      prestamo_saldo: Math.max(0, Number(d.prestamo_saldo || 0) + oldPre - opts.abonoPre).toFixed(2),
    });
  }
}

// Revalidación en 2.º plano: reconcilia con el servidor SIN spinner ni bloqueo, mientras el pagador ya
// hace el siguiente cobro/pago. La guarda de generación evita que una respuesta vieja pise a una nueva.
let revalGen = 0;
async function revalidarSilencioso() {
  if (!periodoSel.value || !online.value) return;
  const periodId = periodoSel.value;
  const gen = ++revalGen;
  try {
    const [data, deudas] = await Promise.all([
      getPaySummary(periodId, branchId.value ? { branch: branchId.value } : {}),
      getDeudasPlanilla(periodId).catch(() => null),
    ]);
    if (gen !== revalGen || periodoSel.value !== periodId) return; // una recarga más nueva ya mandó
    resumen.value = data;
    if (store) void store.cacheSummary(periodKey(companyId.value, branchId.value, periodId), data);
    if (deudas) deudasPorEntry.value = new Map(deudas.map((x) => [x.entry_id, x]));
    await refrescarCola();
  } catch {
    /* silencioso: si falla, queda el estado optimista y se reintenta en la próxima recarga */
  }
}

function abrirDetalle(row: PaySummaryRow) {
  detalle.value = row;
  detalleOpen.value = true;
}

// Deducciones legales (NO cobros): igual que el backend (`non_cobro` = INSS+IR+food+adv+other).
function deduccionesLegales(sheet: PaySummarySheet): number {
  const d = sheet.deductions;
  return (
    Number(d.inss_laboral || 0) + Number(d.ir_amount || 0) + Number(d.food_deduction || 0) +
    Number(d.advance_deduction || 0) + Number(d.other_deductions || 0)
  );
}
// Neto legal = devengado − deducciones legales (= `available` del backend). No usar `remaining`.
function netoLegalDe(sheet: PaySummarySheet): number {
  return Math.max(0, Number(sheet.total_devengado || 0) - deduccionesLegales(sheet));
}
// Deuda interna viva del trabajador (por cédula → de la 1ª hoja con datos, sin doble conteo).
function deudaDe(row: PaySummaryRow): { comisariato: number; prestamo: number; total: number } {
  for (const s of row.sheets) {
    const d = deudasPorEntry.value.get(s.entry_id);
    if (d) {
      const comisariato = Number(d.comisariato_saldo || 0);
      const prestamo = Number(d.prestamo_saldo || 0);
      return { comisariato, prestamo, total: comisariato + prestamo };
    }
  }
  return { comisariato: 0, prestamo: 0, total: 0 };
}

const tieneDeuda = computed(() => !!pago.value && (pago.value.comisariato > 0 || pago.value.prestamo > 0));

// Neto a entregar EN VIVO = neto legal − abonos negociados (nunca negativo).
const netoEntregar = computed(() => {
  if (!pago.value) return 0;
  const a = Number(pagoForm.value.abonoComisariato || 0);
  const b = Number(pagoForm.value.abonoPrestamo || 0);
  return Math.max(0, pago.value.netoLegal - a - b);
});

// Pasos del wizard: solo se incluye una deuda si tiene saldo; el resumen va siempre al final.
const pasos = computed<Array<'comisariato' | 'prestamo' | 'resumen'>>(() => {
  if (!pago.value) return ['resumen'];
  const out: Array<'comisariato' | 'prestamo' | 'resumen'> = [];
  if (pago.value.comisariato > 0) out.push('comisariato');
  if (pago.value.prestamo > 0) out.push('prestamo');
  out.push('resumen');
  return out;
});
const pasoActual = computed(() => pasos.value[Math.min(pasoIdx.value, pasos.value.length - 1)] ?? 'resumen');
const esUltimoPaso = computed(() => pasoIdx.value >= pasos.value.length - 1);

const topeComisariato = computed(() => (pago.value ? Math.min(pago.value.comisariato, pago.value.netoLegal) : 0));
const topePrestamo = computed(() => {
  if (!pago.value) return 0;
  return Math.min(pago.value.prestamo, Math.max(0, pago.value.netoLegal - Number(pagoForm.value.abonoComisariato || 0)));
});

function pasoSiguiente() {
  if (!esUltimoPaso.value) pasoIdx.value += 1;
}
function pasoAtras() {
  if (pasoIdx.value > 0) pasoIdx.value -= 1;
}

// ¿Se puede EDITAR (rectificar) el pago de esta hoja? Solo si ya se pagó algo Y hay un cobro previo
// que corregir o una deuda viva que abonar (el pagador puso mal el monto, o le faltó cobrar).
function cobroPrevioDe(sheet: PaySummarySheet): number {
  return Number(sheet.deductions.store_credit_deduction || 0) + Number(sheet.deductions.loan_payment || 0);
}
function puedeEditarPago(row: PaySummaryRow, sheet: PaySummarySheet): boolean {
  if (Number(sheet.already_paid || 0) <= 0) return false; // aún no se pagó → se usa "Pagar"
  return cobroPrevioDe(sheet) > 0 || deudaDe(row).total > 0;
}

function abrirPago(row: PaySummaryRow, sheet: PaySummarySheet, rectificar = false) {
  const deuda = deudasPorEntry.value.get(sheet.entry_id);
  const netoLegal = netoLegalDe(sheet); // = devengado − INSS/IR/… (igual que el backend)
  const deudaCom = deuda ? Number(deuda.comisariato_saldo) : 0;
  const deudaPre = deuda ? Number(deuda.prestamo_saldo) : 0;
  // Abono previo del cobro (lo que ya se descontó en este entry). En rectificación se REVERSA, así
  // que el monto disponible a re-cobrar = deuda viva + abono previo (la reversa lo devuelve).
  const abonoComPrevio = Number(sheet.deductions.store_credit_deduction || 0);
  const abonoPrePrevio = Number(sheet.deductions.loan_payment || 0);
  const comisariato = rectificar ? deudaCom + abonoComPrevio : deudaCom;
  const prestamo = rectificar ? deudaPre + abonoPrePrevio : deudaPre;
  pago.value = { row, sheet, netoLegal, comisariato, prestamo, modoRectificar: rectificar };
  pagoForm.value = {
    method: 'CASH',
    // En rectificación arranca con el abono PREVIO (para corregirlo); en cobro nuevo arranca en 0.
    abonoComisariato: rectificar && abonoComPrevio > 0 ? abonoComPrevio.toFixed(2) : '',
    abonoPrestamo: rectificar && abonoPrePrevio > 0 ? abonoPrePrevio.toFixed(2) : '',
    motivo: '',
  };
  pasoIdx.value = 0;
  pagoOpen.value = true;
  if (rectificar) detalleOpen.value = false; // se cierra el detalle, queda el asistente
}

async function confirmarPago() {
  const sel = pago.value;
  if (!sel || !periodoSel.value) return;
  const abonoCom = Number(pagoForm.value.abonoComisariato || 0);
  const abonoPre = Number(pagoForm.value.abonoPrestamo || 0);

  // --- RECTIFICAR un cobro ya aplicado: reversa el abono previo, anula el recibo y reemite con el
  //     monto correcto. Caso del pagador equivocado (puso 200 y eran 2000). Requiere motivo. ONLINE.
  if (sel.modoRectificar) {
    if (abonoCom < 0 || abonoPre < 0 || abonoCom > sel.comisariato + 0.001 || abonoPre > sel.prestamo + 0.001) {
      $q.notify({ type: 'warning', message: 'El abono no puede ser negativo ni exceder lo disponible.' });
      return;
    }
    if (abonoCom + abonoPre > sel.netoLegal + 0.001) {
      $q.notify({ type: 'warning', message: 'Los abonos dejan el neto a entregar negativo. Bajá el abono.' });
      return;
    }
    if (!pagoForm.value.motivo.trim()) {
      $q.notify({ type: 'warning', message: 'Indicá el motivo de la rectificación.' });
      return;
    }
    if (!online.value) {
      $q.notify({ type: 'warning', message: 'La rectificación necesita conexión.' });
      return;
    }
    pagando.value = true;
    try {
      const res = await rectificarCobro({
        periodId: periodoSel.value, sheetId: sel.sheet.sheet_id, entryId: sel.sheet.entry_id,
        abonoComisariato: abonoCom.toFixed(2), abonoPrestamo: abonoPre.toFixed(2),
        paymentMethod: pagoForm.value.method, motivo: pagoForm.value.motivo.trim(),
        idempotencyKey: `copa-rec-${sel.sheet.entry_id}-${Date.now()}`,
      });
      pagoOpen.value = false;
      $q.notify({
        type: 'positive', icon: 'verified',
        message: `Rectificado · entregado C$ ${Number(res.neto_entregado).toFixed(2)}. Anula recibo No. ${res.recibo_anulado ?? '—'}.`,
      });
      imprimirReciboCobro({
        row: sel.row, sheet: sel.sheet, netoEntregado: Number(res.neto_entregado),
        abonoCom, abonoPre, saldoComAntes: sel.comisariato, saldoPreAntes: sel.prestamo,
        reciboNo: res.payment_id, reciboAnulado: res.recibo_anulado, motivo: pagoForm.value.motivo.trim(),
      });
      // Optimista: la rectificación REEMPLAZA el pago previo (server anuló+reemitió) → already_paid=neto.
      aplicarPagoLocal(sel, { neto: Number(res.neto_entregado), abonoCom, abonoPre, reemplazaPago: true });
      void revalidarSilencioso(); // reconcilia en 2.º plano mientras se sigue trabajando
    } catch (e) {
      $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo rectificar el pago.') });
    } finally {
      pagando.value = false;
    }
    return;
  }

  // --- COBRO (hay deuda interna): abona comisariato/préstamo + paga el neto. ONLINE (cruza
  //     portfolio y, en el comisariato, otra empresa vía la relación CXC). Recibo del cobro.
  if (tieneDeuda.value) {
    if (abonoCom < 0 || abonoPre < 0 || abonoCom > sel.comisariato + 0.001 || abonoPre > sel.prestamo + 0.001) {
      $q.notify({ type: 'warning', message: 'El abono no puede ser negativo ni exceder la deuda.' });
      return;
    }
    if (abonoCom + abonoPre > sel.netoLegal + 0.001) {
      $q.notify({ type: 'warning', message: 'Los abonos dejan el neto a entregar negativo. Bajá el abono.' });
      return;
    }
    if (!online.value) {
      $q.notify({ type: 'warning', message: 'El cobro de deudas internas necesita conexión.' });
      return;
    }
    pagando.value = true;
    try {
      const res = await cobrarYPagar({
        periodId: periodoSel.value, sheetId: sel.sheet.sheet_id, entryId: sel.sheet.entry_id,
        abonoComisariato: abonoCom.toFixed(2), abonoPrestamo: abonoPre.toFixed(2),
        paymentMethod: pagoForm.value.method, idempotencyKey: `copa-${sel.sheet.entry_id}-${Date.now()}`,
      });
      pagoOpen.value = false;
      $q.notify({
        type: 'positive', icon: 'check',
        message: `Entregado C$ ${Number(res.neto_entregado).toFixed(2)} · abonos: comisariato ${abonoCom.toFixed(2)} / préstamo ${abonoPre.toFixed(2)}.`,
      });
      imprimirReciboCobro({
        row: sel.row, sheet: sel.sheet, netoEntregado: Number(res.neto_entregado),
        abonoCom, abonoPre, saldoComAntes: sel.comisariato, saldoPreAntes: sel.prestamo,
        reciboNo: res.payment_id,
      });
      // Optimista: tarjeta "Pagado" + deuda baja al instante; reconcilia en 2.º plano.
      aplicarPagoLocal(sel, { neto: Number(res.neto_entregado), abonoCom, abonoPre });
      void revalidarSilencioso();
    } catch (e) {
      $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cobrar y pagar.') });
    } finally {
      pagando.value = false;
    }
    return;
  }

  // --- PAGO simple (sin deuda interna): entrega el neto legal. Offline-first (encola).
  const amount = Number(sel.sheet.remaining || 0);
  if (amount <= 0) {
    $q.notify({ type: 'warning', message: 'No hay neto pendiente por entregar.' });
    return;
  }
  pagando.value = true;
  try {
    if (store) {
      const cmd = buildPaymentCommand({
        period_id: periodoSel.value,
        sheet_id: sel.sheet.sheet_id,
        entry_id: sel.sheet.entry_id,
        company_id: companyId.value,
        branch_id: branchId.value ?? 0,
        employee_key: sel.row.employee_key,
        full_name: sel.row.full_name,
        payment_method: pagoForm.value.method,
        amount: amount.toFixed(2),
      });
      const { duplicate } = await enqueuePayment(store, cmd);
      pagoOpen.value = false;
      if (duplicate) {
        $q.notify({ type: 'info', message: 'Ya había un pago pendiente para esta línea.' });
      } else {
        // Optimista: la tarjeta queda "Pagado" al instante; la subida corre en 2.º plano.
        aplicarPagoLocal(sel, { neto: amount, abonoCom: 0, abonoPre: 0 });
        if (online.value) {
          void sincronizar(); // sube la cola sin bloquear (su recarga es silenciosa)
        } else {
          $q.notify({ type: 'positive', icon: 'schedule', message: `Pago encolado C$ ${amount.toFixed(2)} — se enviará al reconectar.` });
        }
      }
      await refrescarCola();
    } else {
      // Sin almacenamiento local: pago online directo, idempotente.
      await payEntry({
        periodId: periodoSel.value,
        sheetId: sel.sheet.sheet_id,
        entryId: sel.sheet.entry_id,
        paymentMethod: pagoForm.value.method,
        amount: amount.toFixed(2),
        idempotencyKey: `copa-${sel.sheet.entry_id}-${Date.now()}`,
      });
      pagoOpen.value = false;
      $q.notify({ type: 'positive', icon: 'check', message: `Entregado C$ ${amount.toFixed(2)}.` });
      // Optimista + reconciliación en 2.º plano (no bloquea el regreso a la lista).
      aplicarPagoLocal(sel, { neto: amount, abonoCom: 0, abonoPre: 0 });
      void revalidarSilencioso();
    }
    imprimirRecibo(sel.row);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo registrar el pago.') });
  } finally {
    pagando.value = false;
  }
}

async function sincronizar() {
  if (!store) return;
  sincronizando.value = true;
  try {
    const res = await drainQueue(store, async (cmd) => {
      await payEntry({
        periodId: cmd.period_id,
        sheetId: cmd.sheet_id,
        entryId: cmd.entry_id,
        paymentMethod: cmd.payment_method,
        amount: cmd.amount,
        idempotencyKey: cmd.id,
      });
    });
    if (res.succeeded > 0) {
      marcarSync(); // subió pagos al servidor → registrar la hora de la última sincronización
      $q.notify({ type: 'positive', message: `${res.succeeded} pago(s) sincronizado(s).` });
      void revalidarSilencioso(); // reconcilia sin bloquear (la cola ya marcó la tarjeta)
    }
    if (res.failed > 0) {
      $q.notify({ type: 'negative', message: `${res.failed} pago(s) rechazado(s) — revisá la cola.` });
    }
  } finally {
    await refrescarCola();
    sincronizando.value = false;
  }
}

// Ciclo de paga (para nombrar el recibo): "Abril 2026 — 2ª quincena".
function cicloTexto(): string {
  const p = resumen.value?.period;
  if (!p) return new Date().toLocaleDateString('es-NI');
  return `${MESES[p.month - 1] ?? p.month} ${p.year} — ${etiquetaTipo(p.period_type)}`;
}
// Nombre AUTOMÁTICO del recibo: "Recibo - <trabajador> - <ciclo>" (apto como nombre de archivo).
function nombreReciboArchivo(nombre: string): string {
  const limpio = (nombre || 'trabajador').replace(/\s+/g, ' ').trim();
  return `Recibo - ${limpio} - ${cicloTexto()}`.replace(/[\\/:*?"<>|]/g, '-');
}
// Guarda el recibo como archivo nombrado, SIN bloquear. En la APP (Capacitor) usa Filesystem para
// persistir en el dispositivo (la descarga Blob NO funciona en el WebView); en web hace la descarga.
// Firma síncrona (dispara una IIFE) para no tocar los call-sites ni dejar promesas flotando.
function guardarRecibo(nombreArchivo: string, html: string) {
  const archivo = `${nombreArchivo}.html`;
  void (async () => {
    // --- APP nativa: guardar en Documentos con Filesystem (no necesita gesto del usuario). ---
    try {
      const { Capacitor } = await import('@capacitor/core');
      if (Capacitor.isNativePlatform()) {
        const { Filesystem, Directory, Encoding } = await import('@capacitor/filesystem');
        await Filesystem.writeFile({
          path: archivo, data: html, directory: Directory.Documents, encoding: Encoding.UTF8, recursive: true,
        });
        $q.notify({ type: 'positive', icon: 'save', message: `Recibo guardado en Documentos: ${nombreArchivo}` });
        return;
      }
    } catch {
      // Si Filesystem no está disponible o falla, caer a la descarga web de abajo.
    }
    // --- Web: descarga directa (Blob). ---
    try {
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = archivo;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      $q.notify({ type: 'positive', icon: 'save', message: `Recibo guardado: ${nombreArchivo}` });
    } catch {
      $q.notify({ type: 'warning', message: 'No se pudo guardar el recibo.' });
    }
  })();
}
// Impresión explícita (botón manual): vía iframe temporal que se auto-elimina → no deja ventana
// congelada como `window.open`.
function imprimirHtml(html: string) {
  const ifr = document.createElement('iframe');
  ifr.style.position = 'fixed';
  ifr.style.right = '0';
  ifr.style.bottom = '0';
  ifr.style.width = '0';
  ifr.style.height = '0';
  ifr.style.border = '0';
  document.body.appendChild(ifr);
  const doc = ifr.contentWindow?.document;
  if (!doc) {
    ifr.remove();
    return;
  }
  doc.open();
  doc.write(html);
  doc.close();
  ifr.contentWindow?.focus();
  ifr.contentWindow?.print();
  setTimeout(() => ifr.remove(), 1000);
}

function imprimirRecibo(row: PaySummaryRow) {
  const filas = row.sheets
    .map((s) => `<tr><td>${s.has_inss ? 'CON INSS' : 'SIN INSS'} · ${esc(s.sheet_name)}</td><td style="text-align:right">${money(s.net_to_pay)}</td></tr>`)
    .join('');
  const comp = row.complement ? `<tr><td>Complemento</td><td style="text-align:right">${money(row.complement.amount_nio)}</td></tr>` : '';
  // Ubicación en la planilla IMPRESA (finca + hoja + No.) para localizar al trabajador en el papel.
  const ubic = row.sheets
    .map((s) => `<div class="ubic-row"><span>${s.has_inss ? 'CON INSS' : 'SIN INSS'} · ${esc(s.location)}</span><b>Hoja ${s.print_page} · No. ${s.print_no}</b></div>`)
    .join('');
  const dd = deudaDe(row);
  const deudaBloque = dd.total > 0
    ? `<div class="sec">Deudas pendientes</div><table>
        ${dd.comisariato > 0 ? `<tr><td>Comisariato</td><td style="text-align:right">${money(dd.comisariato)}</td></tr>` : ''}
        ${dd.prestamo > 0 ? `<tr><td>Préstamo personal</td><td style="text-align:right">${money(dd.prestamo)}</td></tr>` : ''}
        <tr class="tot"><td>DEUDA TOTAL</td><td style="text-align:right">${money(dd.total)}</td></tr></table>`
    : '';
  const titulo = nombreReciboArchivo(row.full_name);
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(titulo)}</title>
    <style>body{font-family:monospace;width:80mm;margin:0 auto;padding:8px;font-size:12px}
    h3{text-align:center;margin:4px 0}.sub{text-align:center;font-size:10px;color:#333;margin-bottom:4px}
    table{width:100%;border-collapse:collapse}td{padding:2px 0;border-bottom:1px dashed #ccc}
    .sec{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:#333;margin:8px 0 2px}
    .tot{font-weight:bold;font-size:14px;border-top:2px solid #000}
    .ubic{margin:6px 0;padding:4px 0;border-top:1px dashed #ccc;border-bottom:1px dashed #ccc}
    .ubic-title{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:#333}
    .ubic-row{display:flex;justify-content:space-between;gap:6px;font-size:11px}
    .firma{margin-top:64px;text-align:center}
    .firma-line{border-top:1px solid #000;width:84%;margin:0 auto 4px}
    .firma-label{font-size:11px}.firma-ced{font-size:10px;color:#333;margin-top:2px}</style></head><body>
    <h3>RECIBO DE PAGO</h3>
    <div class="sub">${esc(cicloTexto())}</div>
    <div>${esc(row.full_name)}</div>
    <div>${row.worker_code ? 'Carnet ' + esc(row.worker_code) : ''}${row.cedula ? ' · ' + esc(row.cedula) : ''}</div>
    <div class="ubic"><div class="ubic-title">Ubicación en planilla impresa</div>${ubic}</div>
    <table>${filas}${comp}
    <tr class="tot"><td>NETO A ENTREGAR</td><td style="text-align:right">${money(row.totales.neto_total_a_entregar)}</td></tr></table>
    ${deudaBloque}
    <div class="firma">
      <div class="firma-line"></div>
      <div class="firma-label">Firma del trabajador</div>
      <div class="firma-ced">${row.cedula ? 'Cédula: ' + esc(row.cedula) : row.worker_code ? 'Carnet: ' + esc(row.worker_code) : ''}</div>
    </div></body></html>`;
  // Al imprimir el recibo se AUTOGUARDA automáticamente (nombre = trabajador + ciclo) y se imprime.
  guardarRecibo(titulo, html);
  imprimirHtml(html);
}

function esc(s: string): string {
  return s.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' })[c] ?? c);
}

// Recibo del COBRO: salario devengado + abonos aplicados + deudas pendientes que le quedan.
// En rectificación, marca el ticket como RECTIFICACIÓN que ANULA el recibo anterior (nota de actualización).
function imprimirReciboCobro(ctx: {
  row: PaySummaryRow;
  sheet: PaySummarySheet;
  netoEntregado: number;
  abonoCom: number;
  abonoPre: number;
  saldoComAntes: number;
  saldoPreAntes: number;
  reciboNo?: number | null;
  reciboAnulado?: number | null;
  motivo?: string;
}) {
  const s = ctx.sheet;
  const d = s.deductions;
  const esRectificacion = ctx.reciboAnulado != null;
  const restoCom = Math.max(0, ctx.saldoComAntes - ctx.abonoCom);
  const restoPre = Math.max(0, ctx.saldoPreAntes - ctx.abonoPre);
  const deudaTotal = restoCom + restoPre;
  const fila = (lbl: string, val: string, cls = '') =>
    `<tr class="${cls}"><td>${lbl}</td><td style="text-align:right">${val}</td></tr>`;
  const abonos = [
    ctx.abonoCom > 0 ? fila('Abono comisariato', '−' + money(ctx.abonoCom), 'ab') : '',
    ctx.abonoPre > 0 ? fila('Abono préstamo personal', '−' + money(ctx.abonoPre), 'ab') : '',
  ].join('');
  const deudas = [
    fila('Comisariato', money(restoCom)),
    fila('Préstamo personal', money(restoPre)),
    fila('DEUDA TOTAL', money(deudaTotal), 'tot'),
  ].join('');
  // Nombre del archivo: en rectificación lo marca como RECTIFICACIÓN para distinguirlo del anulado.
  const tituloBase = nombreReciboArchivo(ctx.row.full_name);
  const titulo = esRectificacion ? `${tituloBase} (RECTIFICACION)` : tituloBase;
  const reciboNoTxt = ctx.reciboNo != null ? `<div class="sub">Recibo No. ${ctx.reciboNo}</div>` : '';
  // Banner + nota de actualización que invalida el ticket anterior (trazabilidad de la corrección).
  const rectBanner = esRectificacion
    ? `<div class="rect">RECTIFICACIÓN<br>ANULA recibo No. ${ctx.reciboAnulado}</div>
       <div class="nota">Nota de actualización: este recibo corrige y reemplaza al recibo No. ${ctx.reciboAnulado}, que queda ANULADO.${ctx.motivo ? ' Motivo: ' + esc(ctx.motivo) + '.' : ''}</div>`
    : '';
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(titulo)}</title>
    <style>body{font-family:monospace;width:80mm;margin:0 auto;padding:8px;font-size:12px}
    h3{text-align:center;margin:4px 0}.sub{text-align:center;font-size:10px;color:#333;margin-bottom:4px}
    table{width:100%;border-collapse:collapse}td{padding:2px 0;border-bottom:1px dashed #ccc}
    .sec{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:#333;margin:8px 0 2px}
    .ab td{color:#b00}.tot{font-weight:bold;font-size:14px;border-top:2px solid #000}
    .rect{margin:6px 0;padding:6px;border:2px solid #b00;color:#b00;text-align:center;font-weight:bold;letter-spacing:.5px}
    .nota{font-size:10px;color:#333;margin:4px 0 6px;text-align:center}
    .ubic{margin:6px 0;padding:4px 0;border-top:1px dashed #ccc;border-bottom:1px dashed #ccc}
    .ubic-row{display:flex;justify-content:space-between;gap:6px;font-size:11px}
    .firma{margin-top:64px;text-align:center}
    .firma-line{border-top:1px solid #000;width:84%;margin:0 auto 4px}
    .firma-label{font-size:11px}.firma-ced{font-size:10px;color:#333;margin-top:2px}</style></head><body>
    <h3>RECIBO DE PAGO</h3>
    <div class="sub">${esc(cicloTexto())}</div>
    ${reciboNoTxt}
    ${rectBanner}
    <div>${esc(ctx.row.full_name)}</div>
    <div>${ctx.row.worker_code ? 'Carnet ' + esc(ctx.row.worker_code) : ''}${ctx.row.cedula ? ' · ' + esc(ctx.row.cedula) : ''}</div>
    <div class="ubic"><div class="ubic-row"><span>${esc(s.location)}</span><b>Hoja ${s.print_page} · No. ${s.print_no}</b></div></div>
    <table>
      ${fila('Salario devengado', money(s.total_devengado))}
      ${Number(d.inss_laboral) > 0 ? fila('INSS laboral', '−' + money(d.inss_laboral)) : ''}
      ${Number(d.ir_amount) > 0 ? fila('IR', '−' + money(d.ir_amount)) : ''}
      ${abonos}
      ${fila('NETO ENTREGADO', money(ctx.netoEntregado), 'tot')}
    </table>
    <div class="sec">Deudas pendientes</div>
    <table>${deudas}</table>
    <div class="firma">
      <div class="firma-line"></div>
      <div class="firma-label">Firma del trabajador</div>
      <div class="firma-ced">${ctx.row.cedula ? 'Cédula: ' + esc(ctx.row.cedula) : ctx.row.worker_code ? 'Carnet: ' + esc(ctx.row.worker_code) : ''}</div>
    </div></body></html>`;
  // Guardado AUTOMÁTICO no bloqueante (nombre = trabajador + ciclo) → vuelve a seguir pagando.
  guardarRecibo(titulo, html);
}

// Al recuperar conexión, drenar la cola pendiente automáticamente.
watch(online, (v) => {
  if (v && cola.value.pending > 0) void sincronizar();
});

// Período RECORDADO: persistir la selección POR EMPRESA para que la próxima vez quede elegida sola.
watch(periodoSel, (v) => {
  if (v) guardarPeriodo(companyId.value, v);
});

onMounted(async () => {
  // 1) El selector de períodos NO debe depender del store offline: cargarlo primero.
  await cargarPeriodos();
  // 2) Store offline (SQLite en tableta / localStorage en web): si tarda o falla, no debe
  //    bloquear la sala. getPayrollStore ya cae a respaldo con timeout, pero por las dudas.
  try {
    store = await getPayrollStore();
    backend.value = store.backend();
    storeError.value = getStoreError(); // si cayó a respaldo, el motivo queda visible en el detalle
  } catch (e) {
    console.warn('[pagador] store offline no disponible; la sala funciona solo online:', e);
  }
  await cargarResumen();
});
</script>

<style scoped>
/* Barra superior compacta: solo lo operativo + ⓘ, alineada a la esquina (sin ruido visual). */
.sala-topbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  margin-bottom: var(--app-space-3);
}

/* Popup de información (nombre + descripción): angosto, con tokens del tema. */
.sala-info {
  max-width: 320px;
  padding: var(--app-space-3);
  background: var(--app-surface);
  color: var(--app-text);
}
.sala-info__title {
  font-weight: 800;
  margin-bottom: var(--app-space-1);
}
.sala-info__text {
  color: var(--app-text-muted);
  font-size: 0.85rem;
  line-height: 1.4;
}
.sala-estado {
  font-size: 0.82rem;
  color: var(--app-text);
}
.sala-estado > div {
  display: flex;
  justify-content: space-between;
  gap: var(--app-space-3);
  padding: 2px 0;
}
.sala-estado > div > span {
  color: var(--app-text-muted);
}
.sala-estado__warn {
  margin-top: var(--app-space-1);
  color: var(--app-accent-coral);
  font-weight: 600;
}

.sala-controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-4);
}

.sala-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-4);
}

.sala-stat {
  border-radius: var(--app-radius-md);
  padding: var(--app-space-3) var(--app-space-4);
  color: #fff;
  background: var(--grad, var(--app-stat-blue));
  box-shadow: var(--app-shadow-card);
}

.sala-stat__label {
  font-size: 0.78rem;
  opacity: 0.92;
}

.sala-stat__value {
  font-size: 1.35rem;
  font-weight: 800;
}

.sala-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: var(--app-space-3);
}

.emp-card {
  cursor: pointer;
  background: var(--app-surface-strong);
  border-left: 5px solid var(--acc, var(--app-primary));
  box-shadow: var(--app-shadow-soft);
  padding: var(--app-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  transition: box-shadow 0.15s ease, transform 0.1s ease;
}

.emp-card:hover {
  box-shadow: var(--app-shadow-card);
  transform: translateY(-1px);
}

.emp-card__top {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}

.emp-ini {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #fff;
  font-weight: 800;
  flex-shrink: 0;
}

.emp-ini--lg {
  width: 52px;
  height: 52px;
  font-size: 1.3rem;
}

.emp-id {
  min-width: 0;
  flex: 1;
}

.emp-nombre {
  font-weight: 700;
  line-height: 1.1;
}

.emp-sub {
  font-size: 0.78rem;
  color: var(--app-text-muted);
}

/* Carnet (ID único de persona): se resalta porque es la clave del cobro entre empresas. */
.emp-carnet {
  font-weight: 700;
  color: var(--app-primary);
}

.emp-ubic {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  font-size: 0.78rem;
  color: var(--app-text-muted);
}

.emp-ubic__loc {
  font-weight: 700;
  color: var(--app-text);
}

.emp-ubic__pos {
  color: var(--app-primary);
  font-weight: 600;
}

.emp-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.emp-neto {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-top: 1px dashed var(--app-border);
  padding-top: var(--app-space-2);
}

.emp-neto__label {
  font-size: 0.8rem;
  color: var(--app-text-muted);
}

.emp-neto__value {
  font-weight: 800;
  font-size: 1.15rem;
  color: var(--app-primary);
}

.emp-pagado {
  color: var(--app-accent-teal);
  font-weight: 700;
  font-size: 0.85rem;
}

.emp-pend {
  color: var(--app-accent-amber);
  font-weight: 600;
  font-size: 0.82rem;
}

.emp-nada {
  color: var(--app-text-muted);
  font-weight: 600;
  font-size: 0.82rem;
}

.sala-toggle {
  color: var(--app-text-muted);
}

.sala-mas {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-3);
  padding: var(--app-space-3) 0;
  flex-wrap: wrap;
}
.sala-mas__count {
  font-size: 0.8rem;
  color: var(--app-text-muted);
}

.sala-empty {
  border: 1px solid var(--app-border-strong);
  background: var(--app-surface-strong);
}

/* Diálogo */
.emp-dialog {
  width: 560px;
  max-width: 96vw;
  background: var(--app-surface-strong);
}

.emp-dialog__head {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
}

.emp-dialog__body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  max-height: 60vh;
  overflow: auto;
}

.planilla-bloque {
  border: 1px solid var(--app-border);
  border-left: 4px solid var(--acc, var(--app-primary));
  border-radius: var(--app-radius-sm);
  padding: var(--app-space-2) var(--app-space-3);
}

.planilla-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}

.planilla-nombre {
  font-weight: 600;
}

.planilla-ubic {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 4px;
  font-size: 0.82rem;
  color: var(--app-text-muted);
}

.planilla-ubic__loc {
  font-weight: 700;
  color: var(--app-text);
}

.planilla-ubic__pos {
  margin-left: auto;
  font-weight: 800;
  color: var(--app-primary);
  background: color-mix(in srgb, var(--app-primary) 12%, transparent);
  border-radius: var(--app-radius-sm);
  padding: 1px 8px;
}

.planilla-neto {
  font-weight: 800;
  color: var(--app-primary);
}

.ded-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 2px var(--app-space-3);
  margin: var(--app-space-2) 0;
  font-size: 0.82rem;
}

.ded-grid div {
  display: flex;
  justify-content: space-between;
}

.ded-grid span {
  color: var(--app-text-muted);
}

.planilla-foot {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}

.planilla-pagado {
  font-size: 0.8rem;
  color: var(--app-accent-teal);
}

.planilla-rest {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--app-accent-amber);
}

.emp-dialog__total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 700;
}

.emp-dialog__total-value {
  font-size: 1.5rem;
  font-weight: 900;
  color: var(--app-primary);
}

.pago-dialog {
  width: 420px;
  max-width: 94vw;
  background: var(--app-surface-strong);
}

.app-form {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.copa-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  color: var(--app-text-muted);
  font-size: 0.9rem;
}

.copa-row b {
  color: var(--app-text);
  font-size: 1.05rem;
}

.copa-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 2px solid var(--app-border-strong);
  padding-top: var(--app-space-2);
  font-weight: 700;
}

.copa-total__value {
  font-size: 1.4rem;
  font-weight: 900;
  color: var(--app-primary);
}

.pago-head {
  padding-bottom: var(--app-space-2);
}

.ded--comisariato b {
  color: var(--app-accent-coral);
}

.ded--prestamo b {
  color: var(--app-accent-violet);
}

/* Saldos pendientes (detalle) */
.saldos {
  border: 1px solid var(--app-border);
  border-left: 4px solid var(--app-accent-coral);
  border-radius: var(--app-radius-sm);
  padding: var(--app-space-2) var(--app-space-3);
  background: color-mix(in srgb, var(--app-accent-coral) 6%, transparent);
}

.saldos__title {
  font-weight: 700;
  font-size: 0.82rem;
  margin-bottom: 4px;
}

.saldos__row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.9rem;
}

.saldos__total {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-top: 1px dashed var(--app-border);
  margin-top: 4px;
  padding-top: 4px;
  font-weight: 700;
}

.saldos__total-value {
  font-size: 1.2rem;
  font-weight: 900;
  color: var(--app-accent-coral);
}

.copa-deuda__head {
  font-weight: 700;
  font-size: 0.9rem;
  color: var(--acc, var(--app-text));
}

.copa-nodebt {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  color: var(--app-text-muted);
  font-size: 0.85rem;
}

/* Aviso de rectificación: edita un pago ya aplicado (anula el recibo anterior). */
.copa-rectaviso {
  margin-top: var(--app-space-2);
  background: var(--app-surface);
  border: 1px solid var(--app-accent-coral);
  color: var(--app-text);
  font-size: 0.82rem;
}

/* Wizard de cobro: pasos */
.pago-pasos {
  display: flex;
  gap: 6px;
  margin-top: var(--app-space-2);
  flex-wrap: wrap;
}

.pago-paso {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  color: var(--app-text-muted);
}

.pago-paso--on {
  background: var(--app-primary);
  border-color: var(--app-primary);
  color: #fff;
}

.pago-paso--done {
  color: var(--app-accent-teal);
  border-color: var(--app-accent-teal);
}

/* Teclado numérico: display del monto */
.kp-display {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--app-space-2);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.kp-display__label {
  font-size: 0.78rem;
  color: var(--app-text-muted);
}

.kp-display__value {
  font-size: 2rem;
  font-weight: 900;
  color: var(--app-primary);
  letter-spacing: 0.5px;
}

.kp-hint {
  font-size: 0.78rem;
  color: var(--app-text-muted);
  text-align: center;
}
</style>
