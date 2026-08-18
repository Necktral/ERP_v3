<template>
  <q-page class="app-page-container">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <BackButton to="/financiamiento" />
    </div>
    <PageHeader
      title="Recibos de café"
      subtitle="Recepción de café en custodia. Pesá los sacos: neto = bruto − tara. El café entra a la bodega de custodia del productor."
      :loading="loading"
      @refresh="reload"
    />

    <!-- Captura (grande, apta para tablet en la báscula) -->
    <q-card flat bordered class="recibo-form q-mb-lg">
      <q-card-section class="recibo-form__grid">
        <q-select
          v-model="form.producer_id"
          :options="prodOpts"
          label="Productor *"
          outlined
          emit-value
          map-options
          options-dense
          class="recibo-field"
        />
        <q-select
          v-model="form.quality_id"
          :options="calOpts"
          label="Calidad *"
          outlined
          emit-value
          map-options
          options-dense
          class="recibo-field"
        />
        <q-select
          v-model="form.physical_state"
          :options="estadoOpts"
          label="Estado físico"
          outlined
          emit-value
          map-options
          options-dense
          class="recibo-field"
        />
        <q-input v-model.number="form.sacks" type="number" min="1" label="Sacos *" outlined class="recibo-field" />
        <q-input v-model.number="form.gross_lb" type="number" label="Peso bruto (lb) *" outlined class="recibo-field">
          <template #append>
            <q-btn flat dense round icon="scale" :loading="leyendoBascula" aria-label="Leer báscula" @click="leerBascula">
              <q-tooltip>Leer de la báscula (USB) — experimental</q-tooltip>
            </q-btn>
          </template>
        </q-input>
        <q-input v-model.number="form.tare_lb" type="number" label="Tara (lb)" outlined class="recibo-field" hint="Vacío = tara por calidad" />
        <q-input v-model="form.reference" label="Referencia / N° recibo" outlined class="recibo-field" />
      </q-card-section>
      <q-card-section class="recibo-form__foot">
        <div class="recibo-neto">
          Neto estimado: <b>{{ netoEstimado }}</b> lb
          <span class="recibo-neto__qq">≈ {{ netoQq }} qq</span>
        </div>
        <q-btn
          unelevated
          no-caps
          size="lg"
          color="primary"
          icon="save"
          label="Registrar recibo"
          :loading="guardando"
          :disable="!form.producer_id || !form.quality_id || !form.sacks || !form.gross_lb"
          @click="guardar"
        />
      </q-card-section>
    </q-card>

    <q-table
      :rows="rows"
      :columns="cols"
      row-key="id"
      flat
      bordered
      :loading="loading"
      v-model:pagination="pagination"
      @request="onRequest"
      no-data-label="Aún no hay recibos de café."
    >
      <template #body-cell-physical_state="props">
        <q-td :props="props">{{ PHYSICAL_STATE_LABELS[props.row.physical_state] ?? props.row.physical_state }}</q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props" class="text-right">
          <q-btn flat dense no-caps size="sm" icon="print" label="Recibo" @click="imprimirRecibo(props.row)" />
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import BackButton from 'src/components/BackButton.vue';
import { useListadoServer } from 'src/core/composables/useListadoServer';
import { apiErrorMessage } from 'src/core/api';
import {
  createReception,
  listProducers,
  listQualities,
  listReceptionsPage,
  PHYSICAL_STATE_LABELS,
  type PhysicalState,
  type ReceptionRow,
} from 'src/modules/financiamiento/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();
const empresaNombre = computed(() => acl.companyName(ctx.activeCompanyId) ?? 'Empresa');
const { rows, loading, pagination, onRequest, reload } = useListadoServer<ReceptionRow>(listReceptionsPage, { rowsPerPage: 15 });

interface Opt {
  label: string;
  value: number;
}
const prodOpts = ref<Opt[]>([]);
const calOpts = ref<Opt[]>([]);
const tareByQuality = new Map<number, number>();

const estadoOpts = (Object.keys(PHYSICAL_STATE_LABELS) as PhysicalState[]).map((k) => ({
  label: PHYSICAL_STATE_LABELS[k],
  value: k,
}));

const form = ref<{
  producer_id: number | null;
  quality_id: number | null;
  physical_state: PhysicalState;
  sacks: number | null;
  gross_lb: number | null;
  tare_lb: number | null;
  reference: string;
}>({
  producer_id: null,
  quality_id: null,
  physical_state: 'HUMEDO',
  sacks: null,
  gross_lb: null,
  tare_lb: null,
  reference: '',
});

const netoEstimado = computed(() => {
  const gross = Number(form.value.gross_lb) || 0;
  if (!gross) return '0.00';
  let tare = Number(form.value.tare_lb);
  if (!form.value.tare_lb && form.value.quality_id != null) {
    const pct = tareByQuality.get(form.value.quality_id) ?? 0;
    tare = (gross * pct) / 100;
  }
  return Math.max(0, gross - (tare || 0)).toFixed(2);
});
const netoQq = computed(() => (Number(netoEstimado.value) / 100).toFixed(2));

const cols: QTableColumn<ReceptionRow>[] = [
  { name: 'reception_date', label: 'Fecha', field: 'reception_date', align: 'left', sortable: true },
  { name: 'reference', label: 'Recibo', field: 'reference', align: 'left' },
  { name: 'producer_name', label: 'Productor', field: 'producer_name', align: 'left', sortable: true },
  { name: 'quality_code', label: 'Calidad', field: 'quality_code', align: 'left' },
  { name: 'physical_state', label: 'Estado', field: 'physical_state', align: 'left' },
  { name: 'sacks', label: 'Sacos', field: 'sacks', align: 'right' },
  { name: 'gross_lb', label: 'Bruto lb', field: 'gross_lb', align: 'right' },
  { name: 'net_lb', label: 'Neto lb', field: 'net_lb', align: 'right', sortable: true },
  { name: 'acciones', label: '', field: 'id', align: 'right' },
];

async function cargarCatalogos() {
  try {
    const [prods, cals] = await Promise.all([listProducers(), listQualities()]);
    prodOpts.value = prods.map((p) => ({
      label: `${p.acopio_code ? p.acopio_code + ' · ' : ''}${p.party_name}`,
      value: p.id,
    }));
    calOpts.value = cals.map((c) => ({ label: `${c.code} — ${c.name}`, value: c.id }));
    tareByQuality.clear();
    for (const c of cals) tareByQuality.set(c.id, Number(c.default_tare_pct) || 0);
  } catch {
    /* el listado principal ya notifica si falla */
  }
}

async function guardar() {
  if (!form.value.producer_id || !form.value.quality_id || !form.value.sacks || !form.value.gross_lb) return;
  guardando.value = true;
  try {
    const creado = await createReception({
      producer_id: form.value.producer_id,
      quality_id: form.value.quality_id,
      physical_state: form.value.physical_state,
      sacks: form.value.sacks,
      gross_lb: form.value.gross_lb,
      tare_lb: form.value.tare_lb ?? null,
      reference: form.value.reference,
    });
    $q.notify({ type: 'positive', message: 'Recibo registrado.' });
    imprimirRecibo(creado); // el productor se lleva su comprobante
    form.value.sacks = null;
    form.value.gross_lb = null;
    form.value.tare_lb = null;
    form.value.reference = '';
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo registrar el recibo.') });
  } finally {
    guardando.value = false;
  }
}

const guardando = ref(false);

// --- Recibo imprimible (comprobante para el productor) ---
function esc(v: string | number | null | undefined): string {
  return String(v ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c] as string);
}
function imprimirRecibo(r: ReceptionRow) {
  const neto = Number(r.net_lb) || 0;
  const qq = (neto / 100).toFixed(2);
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>Recibo de café</title>
  <style>
    *{font-family:'DejaVu Sans',Arial,sans-serif} body{margin:24px;color:#111}
    h2{margin:0;text-align:center} .sub{text-align:center;color:#555;margin:2px 0 14px;font-size:13px}
    table{width:100%;border-collapse:collapse;font-size:14px} td{padding:4px 2px}
    .lbl{color:#555} .val{text-align:right;font-weight:bold}
    .neto{border-top:1.5px solid #333;margin-top:10px;padding-top:8px;font-size:16px}
    .firma{margin-top:48px;display:flex;justify-content:space-between}
    .firma div{border-top:1px solid #333;padding-top:4px;width:45%;text-align:center;font-size:12px}
  </style></head><body>
    <h2>${esc(empresaNombre.value)}</h2>
    <div class="sub">RECIBO DE CAFÉ EN CUSTODIA${r.reference ? ' &middot; N° ' + esc(r.reference) : ''}</div>
    <table>
      <tr><td class="lbl">Fecha</td><td class="val">${esc(r.reception_date)}</td></tr>
      <tr><td class="lbl">Productor</td><td class="val">${esc(r.producer_name)}</td></tr>
      <tr><td class="lbl">Calidad</td><td class="val">${esc(r.quality_code)}</td></tr>
      <tr><td class="lbl">Estado físico</td><td class="val">${esc(PHYSICAL_STATE_LABELS[r.physical_state] ?? r.physical_state)}</td></tr>
      <tr><td class="lbl">Sacos</td><td class="val">${esc(r.sacks)}</td></tr>
      <tr><td class="lbl">Peso bruto (lb)</td><td class="val">${esc(r.gross_lb)}</td></tr>
      <tr><td class="lbl">Tara (lb)</td><td class="val">${esc(r.tare_lb)}</td></tr>
    </table>
    <div class="neto"><table><tr><td class="lbl">NETO</td><td class="val">${neto.toFixed(2)} lb &nbsp;≈&nbsp; ${qq} qq</td></tr></table></div>
    <div class="firma"><div>Entregó (productor)</div><div>Recibió (acopio)</div></div>
  </body></html>`;
  const w = window.open('', '_blank', 'width=420,height=600');
  if (!w) {
    $q.notify({ type: 'warning', message: 'Permití las ventanas emergentes para imprimir el recibo.' });
    return;
  }
  w.document.write(html);
  w.document.close();
  w.focus();
  w.print();
}

// --- Báscula por Web Serial (experimental; respaldo = ingreso manual) ---
interface SerialPortLike {
  open(o: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
  readable: ReadableStream<Uint8Array> | null;
}
interface SerialLike { requestPort(): Promise<SerialPortLike> }

const leyendoBascula = ref(false);
async function leerBascula() {
  const serial = (navigator as unknown as { serial?: SerialLike }).serial;
  if (!serial) {
    $q.notify({ type: 'warning', message: 'Este navegador no soporta lectura de báscula (Web Serial). Ingresá el peso a mano.' });
    return;
  }
  leyendoBascula.value = true;
  let port: SerialPortLike | null = null;
  try {
    port = await serial.requestPort();
    await port.open({ baudRate: 9600 });
    const reader = port.readable!.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    const deadline = Date.now() + 4000;
    let peso: number | null = null;
    while (Date.now() < deadline) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value);
      const nums = buf.match(/-?\d+(?:\.\d+)?/g);
      if (nums && nums.length && /[\r\n]/.test(buf)) {
        peso = Number(nums[nums.length - 1]); // última cifra estable de la línea
        break;
      }
    }
    reader.releaseLock();
    if (peso != null && Number.isFinite(peso) && peso > 0) {
      form.value.gross_lb = peso;
      $q.notify({ type: 'positive', message: `Peso leído: ${peso} lb` });
    } else {
      $q.notify({ type: 'warning', message: 'No se pudo leer un peso. Ingresalo a mano.' });
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo conectar a la báscula.') });
  } finally {
    try { await port?.close(); } catch { /* ignore */ }
    leyendoBascula.value = false;
  }
}

onMounted(() => {
  void cargarCatalogos();
});
</script>

<style scoped>
.recibo-form {
  border-radius: var(--app-radius-md);
  border-color: var(--app-border);
  background: var(--app-surface-strong);
}
.recibo-form__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--app-space-4);
}
.recibo-form__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--app-space-3);
  border-top: 1px solid var(--app-border);
}
.recibo-neto {
  font-size: 1.1rem;
  color: var(--app-text);
}
.recibo-neto__qq {
  color: var(--app-text-muted);
  font-size: 0.9rem;
  margin-left: var(--app-space-3);
}
</style>
