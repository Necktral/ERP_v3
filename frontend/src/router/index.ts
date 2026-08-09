import { route } from 'quasar/wrappers';
import {
  createMemoryHistory,
  createRouter,
  createWebHashHistory,
  createWebHistory,
} from 'vue-router';
import routes from './routes';
import { useAuthStore } from 'src/stores/auth.store';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';
import { useSessionBootstrapStore } from 'src/stores/session-bootstrap.store';
import { isAxiosError } from 'axios';
import { hasRequiredModule, isAllowedInNativeShell } from 'src/router/access';
import { isNativeApp } from 'src/core/platform';

export default route(function () {
  const createHistory = process.env.SERVER
    ? createMemoryHistory
    : process.env.VUE_ROUTER_MODE === 'history'
      ? createWebHistory
      : createWebHashHistory;

  const Router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,
    history: createHistory(process.env.VUE_ROUTER_BASE),
  });

  Router.beforeEach(async (to) => {
    const auth = useAuthStore();
    const acl = useAclStore();
    const ctx = useContextStore();
    const sessionBootstrap = useSessionBootstrapStore();

    auth.initFromStorage();
    ctx.initFromStorage();

    // OFFLINE-FIRST: restaurar la sesión cacheada ANTES de tocar la red. Así, con un login online
    // previo, reabrir SIN red entra al instante y NO se cuelga esperando un server caído (las
    // llamadas de red de abajo solo corren si NO hay sesión = primer ingreso). Refresco en 2.º plano.
    if (!sessionBootstrap.loaded && sessionBootstrap.restoreFromCache()) {
      void sessionBootstrap.loadSession({ force: true }).catch(() => {
        /* offline o server caído: se sigue con la caché; al volver la red se refresca */
      });
    }

    // 0) Bootstrap (BD vacía / setup requerido). Solo si NO hay sesión (primer uso): evita que un
    //    await de red cuelgue el arranque offline cuando ya hay sesión restaurada.
    if (!sessionBootstrap.loaded) {
      try {
        await auth.checkBootstrap();
      } catch {
        // intencional: si el backend no responde, no bloqueamos navegación
      }

      // Si el sistema está fresh, no debe haber llamadas a endpoints protegidos.
      if (auth.bootstrapState.is_fresh) {
        if (to.path !== '/login' && !to.path.startsWith('/bootstrap')) {
          return { path: '/login' };
        }
        return true;
      }
    }

    const requiresAuth = Boolean(to.meta?.requiresAuth);
    const requiresContext = Boolean(to.meta?.requiresContext);

    // Si la ruta NO requiere auth, no disparamos llamadas protegidas en background.
    // Esto evita 401 molestos en /login cuando hay tokens viejos (DB reseteada).
    if (!requiresAuth) {
      return true;
    }

    if (isNativeApp() && !isAllowedInNativeShell(to.path)) {
      return { path: '/nomina/sala-de-pago' };
    }

    // 1) Bootstrap de sesión ONLINE: solo el PRIMER ingreso (sin caché) llega acá. Si falla:
    //    401/403 reales → sesión inválida → /login; sin respuesta (offline) → /login (no hay caché).
    if (!sessionBootstrap.loaded) {
      try {
        await sessionBootstrap.loadSession();
      } catch (error) {
        if (isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) {
          auth.hardClearLocal();
        }
        return { path: '/login' };
      }
    }

    // 2) Redirecciones de seguridad y setup se deciden solo desde bootstrap.
    if (auth.user?.must_change_password) {
      if (to.path !== '/password-change' && to.path !== '/logout') {
        return { path: '/password-change' };
      }
    }

    if (sessionBootstrap.payload?.bootstrap_state?.setup_required) {
      if (!to.path.startsWith('/bootstrap') && to.path !== '/logout') {
        return { path: '/bootstrap' };
      }
    }

    if (!acl.loaded) {
      return { path: '/login' };
    }

    // 3) Contexto operativo requerido
    const requiresContextSelection =
      sessionBootstrap.payload?.effective_context?.requires_context_selection ?? false;
    if (requiresContextSelection && !ctx.activeCompanyId && to.path !== '/select-context') {
      return { path: '/select-context' };
    }

    if (requiresContext && !ctx.activeCompanyId) {
      if (to.path !== '/select-context') return { path: '/select-context' };
      return true;
    }

    const effectiveModules =
      sessionBootstrap.payload?.effective_modules ?? sessionBootstrap.payload?.allowed_modules ?? [];
    if (!hasRequiredModule(to.path, effectiveModules)) {
      return { path: '/403' };
    }

    // 4) ACL por ruta
    const required = to.meta?.requiredPermissions as string[] | undefined;
    if (required && required.length > 0) {
      const companyId = ctx.activeCompanyId;
      if (!companyId) return { path: '/select-context' };

      const ok = required.every((p) => acl.hasPermission(companyId, p));
      if (!ok) return { path: '/403' };
    }

    return true;
  });

  return Router;
});
