<template>
  <div>
    <div class="text-caption text-muted q-mb-sm">
      Clientes con saldo VENCIDO. El nivel sube con la mora (1: aviso, 2: reclamo, 3: última
      instancia) y nunca baja respecto del último recordatorio. La carta se imprime y queda
      registrada.
    </div>
    <q-table
      class="app-table"
      :rows="filas"
      :columns="columnas"
      row-key="party_id"
      flat
      :loading="cargando"
      :pagination="{ rowsPerPage: 25 }"
      no-data-label="Nadie debe nada vencido. 🎉"
    >
      <template #body-cell-saldo="props">
        <q-td :props="props" class="text-weight-bold text-negative">
          {{ formatMoney(props.row.total_outstanding) }} {{ props.row.currency !== 'NIO' ? props.row.currency : '' }}
        </q-td>
      </template>
      <template #body-cell-ultimo="props">
        <q-td :props="props">
          <template v-if="props.row.last_reminder">
            Nivel {{ props.row.last_reminder.level }} · {{ formatDate(props.row.last_reminder.date) }}
          </template>
          <span v-else class="text-muted">Nunca</span>
        </q-td>
      </template>
      <template #body-cell-sugerido="props">
        <q-td :props="props">
          <q-chip
            dense
            square
            :class="`cob-nivel cob-nivel--${props.row.suggested_level}`"
            :label="`Nivel ${props.row.suggested_level}`"
          />
          <q-chip
            v-if="props.row.cooldown_active"
            dense
            square
            outline
            icon="schedule"
            label="Recordado hace poco"
          />
        </q-td>
      </template>
      <template #body-cell-acciones="props">
        <q-td :props="props" class="text-right cob-acciones">
          <q-btn
            flat
            dense
            no-caps
            size="sm"
            icon="history"
            label="Historial"
            @click="verHistorial(props.row)"
          />
          <q-btn
            v-if="puedeRecordar"
            unelevated
            dense
            no-caps
            size="sm"
            color="primary"
            icon="campaign"
            label="Generar recordatorio"
            @click="abrirRecordatorio(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Diálogo: generar recordatorio -->
    <q-dialog v-model="dlgRecordatorio">
      <q-card class="app-dialog cob-dlg">
        <q-card-section class="text-h6">Generar recordatorio de cobro</q-card-section>
        <q-card-section class="app-form">
          <div v-if="objetivo" class="text-caption">
            {{ objetivo.party_name }} · {{ objetivo.docs }} documento(s) vencido(s) ·
            <strong>{{ formatMoney(objetivo.total_outstanding) }}</strong>
          </div>
          <q-banner v-if="objetivo?.cooldown_active" dense class="cob-banner">
            A este cliente ya se le recordó hace menos de 7 días. Podés generar otro igual, pero
            considerá darle tiempo.
          </q-banner>
          <q-select
            v-model="formRec.level"
            :options="opcionesNivel"
            outlined
            dense
            emit-value
            map-options
            label="Nivel *"
          />
          <q-input v-model="formRec.notes" outlined dense label="Notas (van en la carta)" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cancelar" v-close-popup />
          <q-btn
            unelevated
            no-caps
            color="primary"
            icon="print"
            label="Generar e imprimir"
            :loading="generando"
            @click="generarRecordatorio"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Diálogo: historial -->
    <q-dialog v-model="dlgHistorial">
      <q-card class="app-dialog cob-dlg">
        <q-card-section class="text-h6">
          Recordatorios — {{ objetivo?.party_name }}
        </q-card-section>
        <q-card-section>
          <q-list dense separator>
            <q-item v-for="r in historial" :key="r.id">
              <q-item-section>
                <q-item-label>Nivel {{ r.level }} · {{ formatDate(r.reminder_date) }}</q-item-label>
                <q-item-label caption>
                  {{ r.receivables.length }} documento(s) · {{ formatMoney(r.total_outstanding) }}
                  <template v-if="r.generated_by"> · por {{ r.generated_by }}</template>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-btn flat dense no-caps size="sm" icon="print" label="Reimprimir" @click="imprimirCarta(r)" />
              </q-item-section>
            </q-item>
            <q-item v-if="!historial.length">
              <q-item-section class="text-caption text-muted">
                Sin recordatorios todavía.
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Cerrar" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import { apiErrorMessage } from 'src/core/api';
import { formatDate, formatMoney } from 'src/core/format';
import { MENSAJES_CARTERA } from 'src/modules/portfolio/messages';
import {
  createCollectionReminder,
  getCollectionsWorkbench,
  listCollectionReminders,
  type CollectionReminder,
  type CollectionsWorkbenchRow,
} from 'src/modules/portfolio/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const filas = ref<CollectionsWorkbenchRow[]>([]);
const cargando = ref(false);
const generando = ref(false);

const puedeRecordar = (() => {
  const companyId = ctx.activeCompanyId;
  return companyId ? acl.hasPermission(companyId, 'portfolio.collections.remind') : false;
})();

const columnas: QTableColumn<CollectionsWorkbenchRow>[] = [
  { name: 'cliente', label: 'Cliente', field: 'party_name', align: 'left', sortable: true },
  { name: 'docs', label: 'Docs vencidos', field: 'docs', align: 'center' },
  { name: 'saldo', label: 'Saldo vencido', field: 'total_outstanding', align: 'right' },
  {
    name: 'mora',
    label: 'Mora máx.',
    field: (r) => `${r.max_days_overdue} días`,
    align: 'right',
    sortable: true,
  },
  { name: 'ultimo', label: 'Último recordatorio', field: 'party_id', align: 'left' },
  { name: 'sugerido', label: 'Sugerido', field: 'suggested_level', align: 'left' },
  { name: 'acciones', label: '', field: 'party_id', align: 'right' },
];

const opcionesNivel = [
  { value: 1, label: 'Nivel 1 — Aviso amable' },
  { value: 2, label: 'Nivel 2 — Reclamo formal' },
  { value: 3, label: 'Nivel 3 — Última instancia' },
];

async function recargar() {
  cargando.value = true;
  try {
    filas.value = await getCollectionsWorkbench();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar la cobranza.') });
  } finally {
    cargando.value = false;
  }
}

// --- Generar recordatorio ---
const dlgRecordatorio = ref(false);
const objetivo = ref<CollectionsWorkbenchRow | null>(null);
const formRec = reactive({ level: 1, notes: '' });

function abrirRecordatorio(row: CollectionsWorkbenchRow) {
  objetivo.value = row;
  Object.assign(formRec, { level: row.suggested_level, notes: '' });
  dlgRecordatorio.value = true;
}

async function generarRecordatorio() {
  if (!objetivo.value) return;
  generando.value = true;
  try {
    const reminder = await createCollectionReminder({
      party_id: objetivo.value.party_id,
      currency: objetivo.value.currency,
      level: formRec.level,
      ...(formRec.notes.trim() ? { notes: formRec.notes.trim() } : {}),
    });
    dlgRecordatorio.value = false;
    $q.notify({ type: 'positive', message: `Recordatorio nivel ${reminder.level} registrado.` });
    imprimirCarta(reminder);
    await recargar();
  } catch (e) {
    const crudo = apiErrorMessage(e, 'No se pudo generar el recordatorio.');
    $q.notify({ type: 'negative', message: MENSAJES_CARTERA[crudo] ?? crudo });
  } finally {
    generando.value = false;
  }
}

// --- Historial ---
const dlgHistorial = ref(false);
const historial = ref<CollectionReminder[]>([]);

async function verHistorial(row: CollectionsWorkbenchRow) {
  objetivo.value = row;
  historial.value = [];
  dlgHistorial.value = true;
  try {
    historial.value = await listCollectionReminders(row.party_id);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el historial.') });
  }
}

// --- Carta imprimible ---
const TEXTO_NIVEL: Record<number, string> = {
  1: 'Le recordamos amablemente que los siguientes documentos se encuentran vencidos. Si ya realizó el pago, haga caso omiso de este aviso.',
  2: 'A la fecha, los siguientes documentos permanecen vencidos pese a nuestro aviso anterior. Le solicitamos regularizar su cuenta a la brevedad para evitar la suspensión del crédito.',
  3: 'ÚLTIMA INSTANCIA: los documentos detallados continúan impagos. De no recibir el pago en los próximos 5 días hábiles, la cuenta pasará a gestión de cobro externa y se suspenderá todo crédito.',
};

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function imprimirCarta(r: CollectionReminder) {
  const empresa = acl.companyName(ctx.activeCompanyId) ?? '';
  const filasDocs = r.receivables
    .map(
      (d) => `<tr>
        <td>${esc(d.invoice_number || d.obligation_id.slice(0, 8))}</td>
        <td>${formatDate(d.due_date)}</td>
        <td class="num">${d.days_overdue}</td>
        <td class="num">${formatMoney(d.outstanding)}</td>
      </tr>`,
    )
    .join('');
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Recordatorio de cobro</title>
  <style>
    body { font-family: Georgia, 'Times New Roman', serif; color: #111; margin: 48px; }
    h1 { font-size: 16px; margin: 0; } .sub { color: #555; font-size: 12px; }
    .nivel { margin: 16px 0 4px; font-size: 13px; font-weight: bold; text-transform: uppercase; }
    p { font-size: 13px; line-height: 1.5; }
    table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 12px; }
    th, td { border: 1px solid #999; padding: 6px 8px; text-align: left; }
    .num { text-align: right; }
    tfoot td { font-weight: bold; }
    .firma { margin-top: 64px; font-size: 12px; }
    .firma .linea { border-top: 1px solid #111; width: 260px; padding-top: 4px; }
    @media print { body { margin: 24px; } }
  </style></head><body>
  <h1>${esc(empresa)}</h1>
  <div class="sub">Recordatorio de cobro · ${formatDate(r.reminder_date)}</div>
  <div class="nivel">Nivel ${r.level} de 3</div>
  <p>Estimado(a) <strong>${esc(r.party_name)}</strong>:</p>
  <p>${TEXTO_NIVEL[r.level] ?? ''}</p>
  ${r.notes ? `<p><em>${esc(r.notes)}</em></p>` : ''}
  <table>
    <thead><tr><th>Documento</th><th>Venció</th><th class="num">Días de mora</th><th class="num">Saldo</th></tr></thead>
    <tbody>${filasDocs}</tbody>
    <tfoot><tr><td colspan="3">Total vencido</td><td class="num">${formatMoney(r.total_outstanding)} ${r.currency !== 'NIO' ? esc(r.currency) : ''}</td></tr></tfoot>
  </table>
  <p>Puede pasar a cancelar en caja o coordinar su pago con nuestro personal. Gracias por su atención.</p>
  <div class="firma"><div class="linea">Gestión de cobranza — ${esc(empresa)}</div></div>
  </body></html>`;
  const w = window.open('', '_blank', 'width=820,height=900');
  if (!w) {
    $q.notify({ type: 'warning', message: 'El navegador bloqueó la ventana de impresión.' });
    return;
  }
  w.document.write(html);
  w.document.close();
  setTimeout(() => w.print(), 300);
}

onMounted(recargar);
defineExpose({ recargar });
</script>

<style scoped>
.cob-acciones {
  white-space: nowrap;
}

.cob-dlg {
  width: 560px;
  max-width: 95vw;
}

.cob-banner {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-2, var(--app-surface));
  color: var(--app-text);
}

.cob-nivel {
  color: var(--app-text);
  background: var(--app-surface);
  border: 1px solid var(--app-border);
}

.cob-nivel--2 {
  border-color: var(--q-warning);
}

.cob-nivel--3 {
  border-color: var(--q-negative);
  color: var(--q-negative);
}
</style>
