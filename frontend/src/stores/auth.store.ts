import { defineStore } from 'pinia';
import { isAxiosError } from 'axios';
import { api, authApi } from 'src/boot/axios';
import { clearTokens, readTokens, writeTokens } from 'src/core/storage/auth';
import { isNativeApp } from 'src/core/platform';
import { useAclStore } from 'src/stores/acl.store';
import { useContextStore } from 'src/stores/context.store';
import { useSessionBootstrapStore } from 'src/stores/session-bootstrap.store';

interface AuthUser {
  id: number;
  username: string;
  must_change_password: boolean;
  is_setup_complete: boolean;
}

interface AuthState {
  hydrated: boolean;
  status: 'anonymous' | 'authenticated' | 'refreshing' | 'two_factor';
  user: AuthUser | null;
  twoFactor: {
    required: boolean;
    challenge: string | null;
  };
  bootstrapState: {
    is_fresh: boolean;
    setup_required: boolean;
  };
  bootstrapChecked: boolean;
  // lock interno para refresh concurrente
  refreshInFlight: Promise<void> | null;
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    hydrated: false,
    status: 'anonymous',
    user: null,
    twoFactor: {
      required: false,
      challenge: null,
    },
    bootstrapState: {
      is_fresh: false,
      setup_required: false,
    },
    bootstrapChecked: false,
    refreshInFlight: null,
  }),

  getters: {
    isAuthenticated: (s) => s.status === 'authenticated',
    isTwoFactorRequired: (s) => s.status === 'two_factor',
  },

  actions: {
    applyBootstrapUser(user: {
      id: number;
      username: string;
      must_change_password: boolean;
      is_setup_complete: boolean;
    }) {
      this.user = user;
      this.status = 'authenticated';
      // El admin ya fue creado: el sistema deja de estar "fresh". Refrescamos el estado
      // de bootstrap cacheado para que el guard de ruta NO rebote al admin recién creado
      // (ya autenticado) de vuelta a /login al terminar el wizard. (BUG-001)
      this.bootstrapState = {
        is_fresh: false,
        setup_required: !user.is_setup_complete,
      };
      this.bootstrapChecked = true;
    },

    initFromStorage() {
      if (this.hydrated) return;
      this.status = 'anonymous';
      this.hydrated = true;
    },

    async ensureSession() {
      if (this.isAuthenticated) return;
      try {
        await this.fetchMe();
        this.status = 'authenticated';
      } catch {
        this.status = 'anonymous';
      }
    },

    async login(username: string, password: string) {
      const { data } = await authApi.post('/auth/login/', { username, password });
      if (data && typeof data === 'object' && '2fa_required' in data) {
        this.status = 'two_factor';
        this.twoFactor.required = true;
        this.twoFactor.challenge = (data as { challenge?: string }).challenge ?? null;
        return;
      }

      // App nativa: el login responde {access, refresh} (modo header) → persistir en el dispositivo.
      this.persistTokensFromResponse(data);
      this.status = 'authenticated';

      // Fetch user details immediately to check flags
      await this.fetchMe();
    },

    async verifyTwoFactor(code: string) {
      const challenge = this.twoFactor.challenge;
      if (!challenge) throw new Error('2FA challenge missing');
      const { data } = await authApi.post('/auth/2fa/verify/', { challenge, code });
      this.persistTokensFromResponse(data);
      this.status = 'authenticated';
      this.twoFactor.required = false;
      this.twoFactor.challenge = null;
      await this.fetchMe();
    },

    /** En la app nativa guarda los tokens del body; en web es no-op (auth por cookie, sin tokens). */
    persistTokensFromResponse(data: unknown) {
      if (!isNativeApp()) return;
      if (data && typeof data === 'object' && 'access' in data) {
        const d = data as { access?: string; refresh?: string };
        writeTokens(d.access ?? null, d.refresh ?? null);
      }
    },

    async fetchMe() {
      try {
        const { data } = await api.get('/auth/me/');
        this.user = data;
        this.status = 'authenticated';
      } catch (e) {
        // Si hay tokens viejos (DB reseteada), /me devuelve 401.
        // En ese caso limpiamos sesión para evitar loops de refresh/401.
        if (isAxiosError(e)) {
          const status = e.response?.status;
          if (status === 401 || status === 403) {
            this.hardClearLocal();
          }
        }
        throw e;
      }
    },

    async checkBootstrap() {
      try {
        if (this.bootstrapChecked) return this.bootstrapState;
        const { data } = await authApi.get('/auth/bootstrap/status/');
        this.bootstrapState = data;
        this.bootstrapChecked = true;

        // Si el sistema está fresh, aseguramos no mantener tokens/contexto previos.
        if (data?.is_fresh) {
          this.hardClearLocal();
        }
        return data;
      } catch {
        // quiet fail
      }
    },

    async refresh() {
      // lock: si ya hay refresh en progreso, esperar el mismo
      if (this.refreshInFlight) return this.refreshInFlight;

      this.status = 'refreshing';
      this.refreshInFlight = (async () => {
        try {
          if (isNativeApp()) {
            // Modo header: el refresh viaja en el body y la respuesta trae tokens nuevos
            // (SIMPLE_JWT puede rotar el refresh → guardamos el que venga, o el anterior).
            const { refresh } = readTokens();
            if (!refresh) throw new Error('Sin refresh token local');
            const { data } = await authApi.post('/auth/refresh/', { refresh });
            this.persistTokensFromResponse(data);
          } else {
            await authApi.post('/auth/refresh/', {});
          }
          this.status = 'authenticated';
        } finally {
          this.refreshInFlight = null;
        }
      })();

      return this.refreshInFlight;
    },

    async logout() {
      // En nativo, capturar el refresh ANTES de limpiar para poder invalidarlo en el backend.
      const refreshForLogout = isNativeApp() ? readTokens().refresh : null;
      // limpiar stores primero para cortar UI rapido
      this.hardClearLocal();
      try {
        // Best-effort: avisar al backend aunque no haya refresh en el cliente.
        await authApi.post('/auth/logout/', refreshForLogout ? { refresh: refreshForLogout } : {});
      } catch {
        // intencional: no bloqueamos el logout local
      }
    },

    hardClearLocal() {
      const acl = useAclStore();
      const ctx = useContextStore();
      const sessionBootstrap = useSessionBootstrapStore();

      this.status = 'anonymous';
      this.user = null;
      this.twoFactor.required = false;
      this.twoFactor.challenge = null;
      clearTokens();

      acl.clearAcl();
      ctx.clear();
      sessionBootstrap.clear();
    },
  },
});
