import { defineStore } from 'pinia';
import { api } from 'src/boot/axios';
import { useAclStore, type AclSnapshot } from 'src/stores/acl.store';
import { useAuthStore } from 'src/stores/auth.store';
import { useContextStore } from 'src/stores/context.store';
import { STORAGE_KEYS } from 'src/core/storage/keys';
import { createSessionCache, readValidSessionCache } from 'src/core/storage/session-cache';

type ShellMode = 'desktop' | 'mobile';
type DeviceClass = 'desktop' | 'mobile';

type BootstrapSessionResponse = {
  user: {
    id: number;
    username: string;
    must_change_password: boolean;
    is_setup_complete: boolean;
  };
  device: {
    device_class: DeviceClass;
    source_device: string;
  };
  bootstrap_state: {
    is_fresh: boolean;
    setup_required: boolean;
  };
  effective_context: {
    company_id: string | null;
    branch_id: string | null;
    recommended_company_id: string | null;
    recommended_branch_id: string | null;
    requires_context_selection: boolean;
  };
  capabilities: {
    acl_snapshot: AclSnapshot;
  };
  allowed_modules: string[];
  enabled_modules: string[];
  /** allowed ∩ enabled: lo que el frontend debe MOSTRAR para la empresa activa. */
  effective_modules: string[];
  feature_flags: Record<string, boolean>;
  shell_mode: ShellMode;
  trace: {
    request_id: string;
    audit_event_id: string;
    channel: string;
    source_device: string;
  };
  /** Marca de la empresa activa (hereda del holding); null = usar la marca por despliegue. */
  branding?: {
    display_name: string;
    tagline: string;
    logo_data_url: string;
    logo_mime: string;
  } | null;
};

export type SessionBranding = NonNullable<BootstrapSessionResponse['branding']>;

function detectDeviceClass(): DeviceClass {
  if (typeof window === 'undefined') return 'desktop';

  // Solo sugiere `device_class` al servidor; la decision final de `shell_mode`
  // siempre la toma backend en `/auth/bootstrap/session/`.
  const byViewport = window.matchMedia?.('(max-width: 1023px)').matches ?? false;
  const ua = navigator.userAgent || '';
  const byUserAgent = /android|iphone|ipad|ipod|mobile/i.test(ua);
  return byViewport || byUserAgent ? 'mobile' : 'desktop';
}

function hasContextInAcl(snapshot: AclSnapshot, companyId: string): boolean {
  return snapshot.companies.some((company) => String(company.company_id) === String(companyId));
}

interface SessionBootstrapState {
  loaded: boolean;
  loading: boolean;
  payload: BootstrapSessionResponse | null;
}

export const useSessionBootstrapStore = defineStore('sessionBootstrap', {
  state: (): SessionBootstrapState => ({
    loaded: false,
    loading: false,
    payload: null,
  }),

  getters: {
    shellMode: (s): ShellMode => s.payload?.shell_mode ?? 'desktop',
    isMobileShell(): boolean {
      return this.shellMode === 'mobile';
    },
    user: (s) => s.payload?.user ?? null,
    effectiveContext: (s) => s.payload?.effective_context ?? null,
    branding: (s) => s.payload?.branding ?? null,
  },

  actions: {
    clear() {
      this.loaded = false;
      this.loading = false;
      this.payload = null;
      try {
        localStorage.removeItem(STORAGE_KEYS.SESSION_PAYLOAD);
      } catch {
        /* storage no disponible: ignorar */
      }
    },

    /**
     * Hidrata auth + acl + contexto desde un payload de bootstrap (venga de red o de la caché).
     * Reúne la lógica común para que `loadSession` (online) y `restoreFromCache` (offline) hagan lo mismo.
     */
    applyPayload(data: BootstrapSessionResponse) {
      const ctx = useContextStore();
      const auth = useAuthStore();
      const acl = useAclStore();

      this.payload = data;
      this.loaded = true;

      auth.applyBootstrapUser(data.user);
      acl.hydrateSnapshot(data.capabilities.acl_snapshot);

      const currentCompanyId = ctx.activeCompanyId;
      if (currentCompanyId && !hasContextInAcl(data.capabilities.acl_snapshot, currentCompanyId)) {
        ctx.clear();
      }
      if (!ctx.activeCompanyId && data.effective_context.recommended_company_id) {
        const companyId = data.effective_context.recommended_company_id;
        const branchId =
          data.effective_context.recommended_branch_id ?? acl.defaultBranchId(companyId);
        ctx.setContext(companyId, branchId);
      }
      if (!ctx.activeCompanyId && acl.companies.length > 0) {
        const first = acl.companies[0];
        if (first) ctx.setContext(first.company_id, acl.defaultBranchId(first.company_id));
      }
      if (ctx.activeCompanyId && !ctx.activeBranchId) {
        const branchId = acl.defaultBranchId(ctx.activeCompanyId);
        if (branchId) ctx.setContext(ctx.activeCompanyId, branchId);
      }
    },

    /**
     * Offline-first: restaura la sesión desde la caché en localStorage (guardada en el último
     * `loadSession` exitoso). Permite ENTRAR a la app sin red tras haberse logueado online una vez.
     * Devuelve true si había caché válida y se restauró.
     */
    restoreFromCache(): boolean {
      try {
        const raw = localStorage.getItem(STORAGE_KEYS.SESSION_PAYLOAD);
        if (!raw) return false;
        const data = readValidSessionCache<BootstrapSessionResponse>(raw);
        if (!data?.user || !data?.capabilities?.acl_snapshot) {
          localStorage.removeItem(STORAGE_KEYS.SESSION_PAYLOAD);
          return false;
        }
        this.applyPayload(data);
        return true;
      } catch {
        return false;
      }
    },

    async loadSession(options?: { force?: boolean }) {
      if (this.loading) return this.payload;
      if (this.loaded && !options?.force) return this.payload;

      this.loading = true;
      try {
        const ctx = useContextStore();
        const deviceClass = detectDeviceClass();
        const sourceDevice = `web-spa-${deviceClass}`;
        const bootstrapHeaders: Record<string, string> = {
          'X-Device-Class': deviceClass,
          'X-Source-Device': sourceDevice,
          'X-Channel': 'web',
        };

        if (ctx.activeCompanyId) {
          bootstrapHeaders['X-Company-Id'] = String(ctx.activeCompanyId);
        }
        if (ctx.activeBranchId) {
          bootstrapHeaders['X-Branch-Id'] = String(ctx.activeBranchId);
        }

        const { data } = await api.get<BootstrapSessionResponse>('/auth/bootstrap/session/', {
          headers: bootstrapHeaders,
        });

        this.applyPayload(data);
        // Offline-first: cachear el payload para poder ENTRAR sin red la próxima vez.
        try {
          localStorage.setItem(
            STORAGE_KEYS.SESSION_PAYLOAD,
            JSON.stringify(createSessionCache(data)),
          );
        } catch {
          /* storage lleno/no disponible: la sesión sigue en memoria */
        }
        return data;
      } finally {
        this.loading = false;
      }
    },
  },
});
