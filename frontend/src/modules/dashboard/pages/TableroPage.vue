<template>
  <q-page class="app-page-container">
    <PageHeader title="Tablero del holding" :subtitle="subtitle" :loading="loading" @refresh="reload" />

    <div v-if="boards.length">
      <section v-for="b in boards" :key="b.companyId" class="tablero-empresa">
        <div class="tablero-empresa__head">
          <q-icon name="business" size="20px" class="tablero-empresa__icon" />
          <span class="tablero-empresa__name">{{ b.companyName }}</span>
          <q-chip v-if="b.isActive" dense square size="sm" color="primary" text-color="white" label="Activa" />
          <q-chip v-if="b.error" dense square size="sm" outline color="grey" icon="lock" label="Sin acceso" />
        </div>

        <div v-if="b.secciones.length" class="tablero-grid">
          <q-card v-for="sec in b.secciones" :key="sec.skill" flat bordered class="tablero-card">
            <q-card-section class="tablero-card__head">
              <q-icon :name="iconFor(sec.skill)" size="20px" class="tablero-card__icon" />
              <div class="tablero-card__title">{{ sec.etiqueta }}</div>
            </q-card-section>
            <q-separator />
            <q-card-section class="tablero-card__body">{{ sec.answer }}</q-card-section>
          </q-card>
        </div>
        <div v-else-if="!b.error" class="tablero-empresa__vacio">Sin datos del día.</div>
      </section>
    </div>

    <q-banner v-else-if="!loading" class="tablero-empty">
      <template #avatar><q-icon name="info" color="primary" /></template>
      Sin empresas con resumen disponible (o sin permiso). Usá el menú de la izquierda para entrar a
      un área.
    </q-banner>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import { getDailySummary, type SummarySection } from 'src/modules/dashboard/api';
import { apiErrorMessage } from 'src/core/api';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';

interface Board {
  companyId: string;
  companyName: string;
  secciones: SummarySection[];
  isActive: boolean;
  error: boolean;
}

const $q = useQuasar();
const acl = useAclStore();
const ctx = useContextStore();

const boards = ref<Board[]>([]);
const loading = ref(false);
const lastUpdated = ref<Date | null>(null);

// "Tiempo real": refresco automático cada 60s + manual (botón del header).
const REFRESH_MS = 60_000;
let timer: ReturnType<typeof setInterval> | null = null;

// Empresas del holding a las que el usuario pertenece (las del switcher). Se
// consultan TODAS; las que no autoricen el resumen se marcan "sin acceso"
// (allSettled). Así el superusuario/holding ve el holding completo apenas
// existan más empresas, sin depender de permisos pre-listados en el snapshot.
const empresas = computed(() => {
  const activeId = ctx.activeCompanyId ?? '';
  const list = acl.companies.length
    ? acl.companies
    : acl.companies.filter((c) => String(c.company_id) === activeId);
  // Empresa activa primero.
  return [...list].sort((a, b) => {
    if (String(a.company_id) === activeId) return -1;
    if (String(b.company_id) === activeId) return 1;
    return a.company_name.localeCompare(b.company_name);
  });
});

const subtitle = computed(() => {
  const n = boards.value.length;
  const base = n === 1 ? '1 empresa' : `${n} empresas`;
  if (!lastUpdated.value) return `Resumen en vivo · ${base}`;
  const hh = lastUpdated.value.toLocaleTimeString('es-NI', { hour: '2-digit', minute: '2-digit' });
  return `Resumen en vivo · ${base} · actualizado ${hh}`;
});

const ICONS: Record<string, string> = {
  ventas: 'point_of_sale',
  caja: 'payments',
  cobros: 'paid',
  pagos: 'paid',
  inventario: 'inventory',
  stock: 'inventory',
  comisariato: 'storefront',
  combustible: 'local_gas_station',
  finca: 'agriculture',
  nomina: 'groups',
};

function iconFor(skill: string): string {
  const key = Object.keys(ICONS).find((k) => skill.includes(k));
  return key ? ICONS[key]! : 'insights';
}

async function reload(background = false) {
  loading.value = true;
  const activeId = ctx.activeCompanyId ?? '';
  const list = empresas.value;
  try {
    // El refresco del timer es background: un 403 no debe expulsar del tablero.
    const results = await Promise.allSettled(list.map((c) => getDailySummary(c.company_id, { background })));
    const nuevos: Board[] = list.map((c, i) => {
      const r = results[i];
      const isActive = String(c.company_id) === activeId;
      if (r && r.status === 'fulfilled') {
        return {
          companyId: String(c.company_id),
          companyName: r.value.empresa || c.company_name,
          secciones: r.value.secciones,
          isActive,
          error: false,
        };
      }
      return {
        companyId: String(c.company_id),
        companyName: c.company_name,
        secciones: [],
        isActive,
        error: true,
      };
    });
    // En el poll de 60s, si nada cambió no se reasigna boards: evita re-render
    // de todo el tablero cada minuto. El reload manual siempre pinta.
    if (!background || JSON.stringify(nuevos) !== JSON.stringify(boards.value)) {
      boards.value = nuevos;
    }
    lastUpdated.value = new Date();
  } catch (e) {
    if (!lastUpdated.value) {
      $q.notify({ type: 'negative', message: apiErrorMessage(e, 'No se pudo cargar el tablero.') });
    }
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void reload();
  timer = setInterval(() => void reload(true), REFRESH_MS);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<style scoped>
.tablero-empresa {
  margin-bottom: var(--app-space-8);
}

.tablero-empresa__head {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  margin-bottom: var(--app-space-4);
}

.tablero-empresa__icon {
  color: var(--app-secondary);
}

.tablero-empresa__name {
  font-family: 'Manrope', 'IBM Plex Sans', sans-serif;
  font-weight: 800;
  font-size: 1.05rem;
  color: var(--app-text);
}

.tablero-empresa__vacio {
  color: var(--app-text-muted);
  font-size: 0.85rem;
}

.tablero-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--app-space-4);
}

.tablero-card {
  border-radius: var(--app-radius-md);
  border-color: var(--app-border);
  background: var(--app-surface-strong);
  box-shadow: var(--app-shadow-soft);
}

.tablero-card__head {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  padding-bottom: var(--app-space-3);
}

.tablero-card__icon {
  color: var(--app-primary);
}

.tablero-card__title {
  font-family: 'Manrope', 'IBM Plex Sans', sans-serif;
  font-weight: 700;
  color: var(--app-text);
}

.tablero-card__body {
  color: var(--app-text-muted);
  font-size: 0.9rem;
  white-space: pre-line;
}

.tablero-empty {
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
  color: var(--app-text);
}
</style>
