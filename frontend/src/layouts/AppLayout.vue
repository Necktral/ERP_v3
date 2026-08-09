<template>
  <q-layout view="hHh Lpr lff" class="app-shell">
    <q-header class="app-topbar">
      <q-toolbar class="app-toolbar">
        <!-- App nativa = monopropósito CO-PA: sin menú lateral (no se navega a otros módulos). -->
        <q-btn v-if="!native" flat dense round icon="menu" aria-label="Menú" @click="drawer = !drawer" />
        <q-btn
          v-if="canGoBack && !native"
          flat
          dense
          round
          icon="arrow_back"
          aria-label="Volver"
          @click="goBack"
        >
          <q-tooltip>Volver</q-tooltip>
        </q-btn>

        <div class="app-brand row items-center no-wrap q-ml-sm">
          <img v-if="brand.logoUrl" :src="brand.logoUrl" :alt="brand.name" class="app-brand__logo" />
          <span v-else class="app-brand__mark" aria-hidden="true">◆</span>
          <span class="app-brand__name gt-xs">{{ brand.name }}</span>
        </div>

        <q-space />

        <ConnectivityDot class="q-mr-sm" />

        <!-- Selector multi-empresa: cambia empresa/sucursal y recarga sesión/ACL -->
        <q-btn
          v-if="companyName"
          flat
          dense
          no-caps
          class="app-company"
          icon="business"
          icon-right="expand_more"
          :label="companyLabel"
          :loading="switching"
        >
          <q-tooltip>Cambiar de empresa o sucursal</q-tooltip>
          <q-menu anchor="bottom right" self="top right">
            <q-list class="app-company-menu" dense>
              <q-item-label header>Cambiar de empresa</q-item-label>
              <template v-for="c in acl.companies" :key="c.company_id">
                <q-item
                  clickable
                  v-close-popup
                  :active="esContextoActivo(c.company_id, null)"
                  active-class="app-company-menu--active"
                  @click="cambiarContexto(c.company_id, null)"
                >
                  <q-item-section avatar><q-icon name="business" size="18px" /></q-item-section>
                  <q-item-section>{{ c.company_name }}</q-item-section>
                </q-item>
                <q-item
                  v-for="b in c.branches"
                  :key="`${c.company_id}-${b.branch_id}`"
                  clickable
                  v-close-popup
                  class="app-company-menu__branch"
                  :active="esContextoActivo(c.company_id, b.branch_id)"
                  active-class="app-company-menu--active"
                  @click="cambiarContexto(c.company_id, b.branch_id)"
                >
                  <q-item-section avatar><q-icon name="subdirectory_arrow_right" size="16px" /></q-item-section>
                  <q-item-section>{{ b.branch_name }}</q-item-section>
                </q-item>
              </template>
            </q-list>
          </q-menu>
        </q-btn>

        <q-btn flat dense round :icon="themeIcon" aria-label="Tema">
          <q-tooltip>Tema</q-tooltip>
          <q-menu anchor="bottom right" self="top right">
            <q-list dense style="min-width: 180px">
              <q-item
                clickable
                v-close-popup
                :active="ui.theme === 'cafetalero'"
                @click="ui.setTheme('cafetalero')"
              >
                <q-item-section avatar><q-icon name="local_cafe" size="18px" /></q-item-section>
                <q-item-section>Cafetalero</q-item-section>
              </q-item>
              <q-item
                clickable
                v-close-popup
                :active="ui.theme === 'light'"
                @click="ui.setTheme('light')"
              >
                <q-item-section avatar><q-icon name="light_mode" size="18px" /></q-item-section>
                <q-item-section>Claro</q-item-section>
              </q-item>
              <q-item
                clickable
                v-close-popup
                :active="ui.theme === 'dark'"
                @click="ui.setTheme('dark')"
              >
                <q-item-section avatar><q-icon name="dark_mode" size="18px" /></q-item-section>
                <q-item-section>Oscuro</q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>

        <q-btn flat dense round icon="account_circle" aria-label="Cuenta">
          <q-menu anchor="bottom right" self="top right">
            <div class="app-user-menu">
              <div class="app-user-menu__name">{{ user?.username ?? 'Usuario' }}</div>
              <q-separator spaced />
              <!-- App nativa: "Salir" NO destruye la sesión (minimiza) → al reabrir entra solo, con o
                   sin red. "Cambiar de cajero" sí cierra sesión (para entregar el aparato a otro). -->
              <template v-if="native">
                <q-btn flat dense no-caps icon="logout" label="Salir" @click="salir" />
                <q-btn flat dense no-caps icon="switch_account" label="Cambiar de cajero" @click="logout" />
              </template>
              <q-btn v-else flat dense no-caps icon="logout" label="Cerrar sesión" @click="logout" />
            </div>
          </q-menu>
        </q-btn>
      </q-toolbar>
    </q-header>

    <q-drawer v-if="!native" v-model="drawer" show-if-above bordered class="app-drawer" :width="248">
      <q-list padding>
        <template v-for="grupo in navAgrupado" :key="grupo.section">
          <q-item-label header class="app-drawer__header">{{ grupo.section }}</q-item-label>
          <q-item
            v-for="item in grupo.items"
            :key="item.to"
            clickable
            :to="item.to"
            active-class="app-nav--active"
            class="app-nav"
          >
            <q-item-section avatar>
              <q-icon :name="item.icon" />
            </q-item-section>
            <q-item-section>{{ item.label }}</q-item-section>
          </q-item>
        </template>

        <q-item v-if="navAgrupado.length === 0" class="app-nav">
          <q-item-section class="text-caption text-muted">
            Aún no hay módulos habilitados para tu usuario.
          </q-item-section>
        </q-item>
      </q-list>
    </q-drawer>

    <q-page-container>
      <!-- key por contexto: al cambiar de empresa/sucursal TODAS las páginas se remontan -->
      <router-view :key="`${ctx.activeCompanyId ?? ''}:${ctx.activeBranchId ?? ''}`" />
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useQuasar } from 'quasar';
import ConnectivityDot from 'src/components/ConnectivityDot.vue';
import { BRAND } from 'src/config/brand';
import { useAuthStore } from 'src/stores/auth.store';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';
import { useSessionBootstrapStore } from 'src/stores/session-bootstrap.store';
import { useUiStore } from 'src/stores/ui.store';
import { NAV, NAV_SECTIONS } from 'src/app/nav';
import { isNativeApp } from 'src/core/platform';
import { useConnectivity } from 'src/core/connectivity';
import { switchContextWithRollback } from 'src/core/context-switch';

// App nativa (Capacitor) = monopropósito CO-PA: oculta el drawer y la navegación a otros módulos.
const native = isNativeApp();
const { online } = useConnectivity();

const $q = useQuasar();
const router = useRouter();
const route = useRoute();

// Botón "Volver" del topbar: aparece en toda pantalla que no sea el inicio.
// En el cel es la única forma de volver (el drawer va oculto); en escritorio
// complementa al menú lateral. Vuelve por el historial; si no hay, va al inicio.
const canGoBack = computed(() => route.path !== '/tablero' && route.path !== '/');
function goBack() {
  if (typeof window !== 'undefined' && window.history.length > 1) router.back();
  else void router.push('/tablero');
}
const auth = useAuthStore();
const acl = useAclStore();
const ctx = useContextStore();
const sessionBootstrap = useSessionBootstrapStore();

async function revalidarSesionReconectada() {
  try {
    await sessionBootstrap.loadSession({ force: true });
  } catch {
    // Axios decide 401/403; ante una caída transitoria se conserva la caché vigente.
  }
}

function alReconectar() {
  void revalidarSesionReconectada();
}

onMounted(() => window.addEventListener('necktral:server-online', alReconectar));
onBeforeUnmount(() => window.removeEventListener('necktral:server-online', alReconectar));

// Marca del topbar: branding de la empresa activa (del bootstrap), con fallback a la
// marca por despliegue (VITE_BRAND_*). El "developer" (crédito) siempre es el estático.
const brand = computed(() => {
  const b = sessionBootstrap.branding;
  return {
    name: b?.display_name || BRAND.name,
    tagline: b?.tagline || BRAND.tagline,
    logoUrl: b?.logo_data_url || BRAND.logoUrl,
    developer: BRAND.developer,
  };
});
const ui = useUiStore();

const drawer = ref(true);
const switching = ref(false);

const user = computed(() => auth.user);
const companyName = computed(() => acl.companyName(ctx.activeCompanyId));
const themeIcon = computed(() =>
  ui.theme === 'cafetalero' ? 'local_cafe' : ui.theme === 'dark' ? 'dark_mode' : 'light_mode',
);

const companyLabel = computed(() => {
  const company = acl.companies.find((c) => String(c.company_id) === ctx.activeCompanyId);
  if (!company) return companyName.value ?? '';
  const branch = ctx.activeBranchId
    ? company.branches.find((b) => String(b.branch_id) === ctx.activeBranchId)
    : null;
  return branch ? `${company.company_name} · ${branch.branch_name}` : company.company_name;
});

// Gating multi-empresa: effective = (permisos del usuario) ∩ (módulos que la
// empresa tiene encendidos). allowed_modules queda solo como fallback legacy.
const effectiveModules = computed(
  () =>
    new Set(
      sessionBootstrap.payload?.effective_modules ?? sessionBootstrap.payload?.allowed_modules ?? [],
    ),
);

const visibleNav = computed(() =>
  NAV.filter((item) => {
    const companyId = ctx.activeCompanyId;
    if (!companyId) return false;
    if ($q.platform.is.mobile && !item.mobile) return false; // cel = solo campo
    if (!acl.hasPermission(companyId, item.perm)) return false;
    return item.module === null || effectiveModules.value.has(item.module);
  }),
);

// Drawer agrupado por sección (las secciones sin ítems visibles no se muestran).
const navAgrupado = computed(() =>
  NAV_SECTIONS.map((section) => ({
    section,
    items: visibleNav.value.filter((i) => i.section === section),
  })).filter((g) => g.items.length > 0),
);

function esContextoActivo(companyId: string | number, branchId: string | number | null): boolean {
  if (String(companyId) !== ctx.activeCompanyId) return false;
  return branchId === null ? !ctx.activeBranchId : String(branchId) === ctx.activeBranchId;
}

async function cambiarContexto(companyId: string | number, branchId: string | number | null) {
  // Si se eligió la EMPRESA (sin sucursal), resolver su sucursal por defecto: las
  // pantallas/datasets scope BRANCH exigen X-Branch-Id (que axios inyecta desde el
  // contexto). Sin esto, Analítica (fuel/accounting) y Estación quedan sin contexto.
  const company = acl.companies.find((c) => String(c.company_id) === String(companyId));
  const resolvedBranchId = branchId ?? acl.defaultBranchId(companyId);
  if (esContextoActivo(companyId, resolvedBranchId)) return;
  switching.value = true;
  try {
    await switchContextWithRollback(ctx, companyId, resolvedBranchId, () =>
      sessionBootstrap.loadSession({ force: true }),
    );
    // A la raíz: la ruta actual puede no existir/permitirse en la otra empresa.
    await router.replace('/');
    // BUG-9: una empresa SIN sucursal operativa deja el contexto sin X-Branch-Id, y las
    // pantallas scope BRANCH (ventas, caja, inventario) responderían 400. En vez de dejar
    // al usuario en un estado roto silencioso (o creyendo que opera otra empresa), se le
    // avisa explícitamente. El tablero y Organización (scope empresa) sí funcionan.
    if (!ctx.activeBranchId && !(company?.branches?.length)) {
      $q.notify({
        type: 'warning',
        icon: 'warning',
        message:
          `${company?.company_name ?? 'La empresa'} no tiene sucursal operativa: ` +
          `ventas, caja e inventario no estarán disponibles.`,
        timeout: 6000,
      });
    } else {
      $q.notify({ type: 'positive', message: `Ahora estás en ${companyLabel.value}.` });
    }
  } catch {
    $q.notify({ type: 'negative', message: 'No se pudo cambiar de empresa.' });
  } finally {
    switching.value = false;
  }
}

// "Salir" en la app nativa: minimiza SIN cerrar sesión (la sesión queda cacheada → al reabrir,
// online u offline, el guard restaura y entra solo). Si no se puede minimizar, no hace nada destructivo.
async function salir() {
  try {
    const { App } = await import('@capacitor/app');
    await App.minimizeApp();
  } catch {
    /* no se pudo minimizar: la sesión queda intacta */
  }
}

async function logout() {
  // App nativa = "Cambiar de cajero": destructivo, con confirmación, y solo con conexión (sin red el
  // nuevo cajero no podría loguear y el actual quedaría afuera).
  if (native) {
    if (!online.value) {
      $q.notify({
        type: 'warning',
        message: 'Sin conexión: no podés cambiar de cajero ahora. Para salir usá "Salir" (la sesión queda guardada).',
      });
      return;
    }
    $q.dialog({
      title: 'Cambiar de cajero',
      message: 'Se cerrará la sesión actual. El nuevo cajero necesitará conexión para entrar. ¿Continuar?',
      cancel: { label: 'Cancelar', flat: true },
      ok: { label: 'Cerrar sesión', color: 'primary', unelevated: true },
      persistent: true,
    }).onOk(() => {
      void (async () => {
        await auth.logout();
        await router.replace('/login');
      })();
    });
    return;
  }
  await auth.logout();
  await router.replace('/login');
}
</script>

<style scoped>
.app-shell {
  background: var(--app-bg-gradient);
  background-color: var(--app-bg);
}

.app-topbar {
  background: var(--app-surface-strong);
  color: var(--app-text);
  border-bottom: 1px solid var(--app-border);
}

.app-toolbar {
  min-height: 56px;
}

.app-brand__logo {
  height: 28px;
  width: auto;
  max-width: 120px;
  object-fit: contain;
}

.app-brand__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: var(--app-radius-sm);
  color: #fff;
  font-size: 0.95rem;
  background: linear-gradient(135deg, var(--app-primary), var(--app-secondary));
}

.app-brand__name {
  margin-left: var(--app-space-3);
  font-family: 'Roboto', 'Segoe UI', system-ui, sans-serif;
  font-weight: 800;
  letter-spacing: 0.03em;
  font-size: 1.02rem;
}

.app-company {
  color: var(--app-text-muted);
  border-color: var(--app-border-strong);
}

.app-company-menu {
  min-width: 240px;
}

.app-company-menu__branch {
  padding-left: var(--app-space-5);
}

.app-company-menu--active {
  color: var(--app-primary);
  font-weight: 600;
}

.app-drawer {
  background: var(--app-surface);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.app-drawer__header {
  color: var(--app-text-muted);
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-size: 0.7rem;
}

.app-nav {
  border-radius: var(--app-radius-sm);
  margin: 2px var(--app-space-2);
  color: var(--app-text);
}

.app-nav--active {
  background: var(--app-surface-strong);
  color: var(--app-primary);
  font-weight: 600;
}

.app-user-menu {
  display: flex;
  flex-direction: column;
  padding: var(--app-space-3);
  min-width: 180px;
}

.app-user-menu__name {
  font-weight: 700;
  color: var(--app-text);
  padding: 0 var(--app-space-2) var(--app-space-1);
}

.text-muted {
  color: var(--app-text-muted);
}
</style>
