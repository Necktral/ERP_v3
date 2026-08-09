<template>
  <q-page class="login-page">
    <div class="login-card app-fade-up">
      <div class="login-brand">
        <img v-if="brand.logoUrl" :src="brand.logoUrl" :alt="brand.name" class="login-logo" />
        <span v-else class="login-mark" aria-hidden="true">◆</span>
        <div class="login-brand__text">
          <div class="login-brand__name">{{ brand.name }}</div>
          <div class="login-brand__claim">{{ brand.tagline }}</div>
        </div>
      </div>

      <q-banner v-if="bootstrapChecked && isFresh" class="login-banner login-banner--info" rounded>
        <div class="text-weight-medium">Primer arranque: aún no hay usuarios.</div>
        <div class="text-caption">Crea el usuario administrador inicial y configura tu organización.</div>
        <template #action>
          <q-btn unelevated color="primary" label="Crear usuario inicial" to="/bootstrap" />
        </template>
      </q-banner>

      <q-form class="login-form" @submit.prevent="onSubmit">
        <q-input
          v-model="username"
          label="Usuario"
          autocomplete="username"
          outlined
          :autofocus="!usuarioRecordado"
          :disable="isFresh"
        >
          <template #prepend>
            <q-icon name="person" />
          </template>
        </q-input>

        <q-input
          v-model="password"
          label="Contraseña"
          :type="showPassword ? 'text' : 'password'"
          autocomplete="current-password"
          outlined
          :autofocus="usuarioRecordado"
          :disable="isFresh"
        >
          <template #prepend>
            <q-icon name="lock" />
          </template>
          <template #append>
            <q-icon
              :name="showPassword ? 'visibility_off' : 'visibility'"
              class="cursor-pointer"
              :aria-label="showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'"
              @click="showPassword = !showPassword"
            />
          </template>
        </q-input>

        <q-checkbox
          v-model="rememberUser"
          label="Recordar usuario"
          dense
          class="login-remember"
          :disable="isFresh"
        />

        <q-btn
          :loading="loading"
          type="submit"
          label="Ingresar"
          color="primary"
          unelevated
          class="login-submit full-width"
          :disable="isFresh"
        />
      </q-form>

      <!-- Offline-first: si ya hubo un login online en este aparato, se puede ENTRAR sin red con la
           última sesión guardada (sin volver a teclear credenciales). -->
      <q-btn
        v-if="haySesionGuardada"
        flat
        no-caps
        icon="wifi_off"
        label="Entrar sin conexión (última sesión)"
        color="primary"
        class="login-offline full-width"
        @click="entrarConUltimaSesion"
      />

      <q-banner v-if="errorMsg" class="login-banner login-banner--error" rounded>
        {{ errorMsg }}
        <template #action>
          <q-btn flat label="Cerrar" @click="errorMsg = null" />
        </template>
      </q-banner>

      <button v-if="isNative" type="button" class="login-server" @click="openServerDialog">
        <q-icon name="dns" size="16px" />
        <span class="login-server__label">{{ currentServerLabel }}</span>
        <q-icon name="expand_more" size="16px" />
      </button>

      <div class="login-credit">Desarrollado por {{ brand.developer }}</div>
    </div>

    <q-dialog v-model="showServerDialog">
      <q-card class="server-dialog">
        <q-card-section class="server-dialog__title">Servidor</q-card-section>
        <q-card-section class="server-dialog__body">
          <q-option-group
            v-model="serverMode"
            :options="serverModeOptions"
            color="primary"
            @update:model-value="probeMsg = ''"
          />
          <q-input
            v-if="serverMode === 'lan'"
            v-model="lanUrl"
            outlined
            dense
            label="Dirección del servidor en la red local"
            hint="Ej: http://192.168.1.13:8000"
            @update:model-value="probeMsg = ''"
          />
          <q-banner
            v-if="probeMsg"
            :class="probeOk ? 'server-banner server-banner--ok' : 'server-banner server-banner--bad'"
            rounded
            dense
          >
            {{ probeMsg }}
          </q-banner>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Probar conexión" :loading="probing" @click="testServer" />
          <q-btn flat label="Cancelar" v-close-popup />
          <q-btn unelevated color="primary" label="Guardar" @click="saveServer" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { isAxiosError } from 'axios';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { Notify } from 'quasar';
import { useAuthStore } from 'src/stores/auth.store';
import { useSessionBootstrapStore } from 'src/stores/session-bootstrap.store';
import { BRAND } from 'src/config/brand';
import { isNativeApp } from 'src/core/platform';
import { STORAGE_KEYS } from 'src/core/storage/keys';
import { apiErrorMessage } from 'src/core/api';
import {
  DEFAULT_SERVER_ORIGIN,
  SUGGESTED_LAN_ORIGIN,
  getServerOrigin,
  getApiBaseUrl,
  setServerOrigin,
  normalizeOrigin,
  probeServer,
} from 'src/core/storage/server';

const brand = BRAND;

// --- Selector de servidor (solo en la app nativa) ---------------------------
const isNative = isNativeApp();
const showServerDialog = ref(false);
const serverMode = ref<'internet' | 'lan'>('internet');
const lanUrl = ref(SUGGESTED_LAN_ORIGIN);
const probing = ref(false);
const probeMsg = ref('');
const probeOk = ref(false);

const serverModeOptions = [
  { label: 'Internet (wiscontext-sync.org)', value: 'internet' },
  { label: 'Red local (LAN)', value: 'lan' },
];

function hostOf(origin: string): string {
  try {
    return new URL(origin).host;
  } catch {
    return origin;
  }
}
// ref (no computed): getServerOrigin() lee localStorage (no reactivo) → el chip no refrescaría tras
// Guardar. Se actualiza explícitamente en saveServer().
const currentServerLabel = ref(hostOf(getServerOrigin()));

function targetOrigin(): string {
  return serverMode.value === 'internet' ? DEFAULT_SERVER_ORIGIN : normalizeOrigin(lanUrl.value);
}

function openServerDialog() {
  const current = getServerOrigin();
  if (current === DEFAULT_SERVER_ORIGIN) {
    serverMode.value = 'internet';
  } else {
    serverMode.value = 'lan';
    lanUrl.value = current;
  }
  probeMsg.value = '';
  showServerDialog.value = true;
}

async function testServer() {
  const target = targetOrigin();
  if (!target) {
    probeOk.value = false;
    probeMsg.value = 'Ingresá una dirección válida.';
    return;
  }
  probing.value = true;
  probeMsg.value = '';
  try {
    const ok = await probeServer(target);
    probeOk.value = ok;
    probeMsg.value = ok
      ? `Conectado a ${target}`
      : `No respondió ${target}. Revisá la red o la dirección.`;
  } finally {
    probing.value = false;
  }
}

function saveServer() {
  const target = targetOrigin();
  if (!target) {
    Notify.create({ type: 'negative', message: 'Dirección de servidor inválida.' });
    return;
  }
  setServerOrigin(target);
  currentServerLabel.value = hostOf(target);
  showServerDialog.value = false;
  Notify.create({ type: 'positive', message: `Servidor: ${target}` });
}

const router = useRouter();
const auth = useAuthStore();
const sessionBootstrap = useSessionBootstrapStore();

// Offline-first: ¿hay una sesión guardada de un login online previo en este aparato?
const haySesionGuardada = ref(isNative && !!localStorage.getItem(STORAGE_KEYS.SESSION_PAYLOAD));
async function entrarConUltimaSesion() {
  if (sessionBootstrap.restoreFromCache()) {
    await router.replace('/');
  } else {
    haySesionGuardada.value = false;
    Notify.create({
      type: 'warning',
      message: 'No hay una sesión guardada. Necesitás conexión para el primer ingreso.',
    });
  }
}

// Recordar usuario: SOLO el nombre (jamás la contraseña), en este navegador.
const REMEMBER_KEY = 'nt_remembered_username';
const savedUsername = localStorage.getItem(REMEMBER_KEY);
const usuarioRecordado = !!savedUsername;

const username = ref(savedUsername ?? '');
const password = ref('');
const showPassword = ref(false);
const rememberUser = ref(usuarioRecordado);

const loading = ref(false);
const errorMsg = ref<string | null>(null);

const bootstrapChecked = ref(false);
const isFresh = computed(() => auth.bootstrapState.is_fresh);

onMounted(async () => {
  try {
    await auth.checkBootstrap();
  } finally {
    bootstrapChecked.value = true;
  }
});

async function onSubmit() {
  loading.value = true;
  errorMsg.value = null;

  try {
    await auth.login(username.value.trim(), password.value);

    // Login correcto: persistir (o borrar) el usuario según el checkbox.
    if (rememberUser.value) {
      localStorage.setItem(REMEMBER_KEY, username.value.trim());
    } else {
      localStorage.removeItem(REMEMBER_KEY);
    }

    if (auth.isTwoFactorRequired) {
      await router.replace('/login/2fa');
      return;
    }

    // Carril privado canónico: resolver sesión/contexto/capacidades desde bootstrap único.
    await sessionBootstrap.loadSession({ force: true });

    if (auth.user?.must_change_password) {
      await router.replace('/password-change');
      return;
    }

    if (sessionBootstrap.payload?.bootstrap_state?.setup_required) {
      await router.replace('/bootstrap');
      return;
    }

    // Frontend en reconstrucción: el app gated arranca en RR.HH.
    await router.replace('/');
  } catch (e: unknown) {
    if (isAxiosError(e) && !e.response) {
      // Sin respuesta HTTP = no se pudo conectar (servidor mal elegido, sin internet, etc.).
      // Nombrar la URL destino convierte el "network error" opaco en algo accionable.
      errorMsg.value = isNative
        ? `No se pudo conectar a ${getApiBaseUrl()}. El PRIMER ingreso necesita conexión; después la app abre sin red. Revisá el Servidor (abajo) y tu conexión.`
        : 'No se pudo conectar con el servidor. Revisá tu conexión.';
    } else if (isAxiosError(e)) {
      errorMsg.value = apiErrorMessage(e, 'No pudimos iniciar sesión.');
    } else {
      errorMsg.value = apiErrorMessage(e, 'No pudimos iniciar sesión.');
    }
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--app-space-4);
  background: var(--app-bg-gradient);
  background-color: var(--app-bg);
}

.login-card {
  width: 100%;
  max-width: 420px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-5);
  padding: var(--app-space-8) var(--app-space-6);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  box-shadow: var(--app-shadow-card);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.login-brand {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
}

.login-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--app-radius-md);
  font-size: 1.25rem;
  color: #fff;
  background: linear-gradient(135deg, var(--app-primary), var(--app-secondary));
  box-shadow: var(--app-shadow-soft);
}

.login-brand__name {
  font-family: 'Roboto', 'Segoe UI', system-ui, sans-serif;
  font-size: 1.35rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  line-height: 1.1;
  color: var(--app-text);
}

.login-brand__claim {
  font-size: 0.82rem;
  color: var(--app-text-muted);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}

.login-remember {
  align-self: flex-start;
  color: var(--app-text-muted);
  font-size: 0.85rem;
}

.login-submit {
  height: 44px;
  font-weight: 600;
}

.login-offline {
  border: 1px dashed var(--app-border-strong);
  border-radius: var(--app-radius-md);
  font-weight: 600;
}

.login-banner {
  border: 1px solid var(--app-border);
  background: var(--app-surface-strong);
}

.login-banner--error {
  border-color: rgba(193, 56, 56, 0.4);
}

.login-logo {
  height: 44px;
  width: auto;
  max-width: 160px;
  object-fit: contain;
}

.login-credit {
  margin-top: var(--app-space-1);
  text-align: center;
  font-size: 0.72rem;
  letter-spacing: 0.02em;
  color: var(--app-text-muted);
}

.login-server {
  align-self: center;
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
  padding: 4px 10px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-strong);
  color: var(--app-text-muted);
  font-size: 0.78rem;
  cursor: pointer;
}

.login-server__label {
  font-weight: 600;
  color: var(--app-text);
}

.server-dialog {
  width: 100%;
  max-width: 420px;
  background: var(--app-surface);
  color: var(--app-text);
}

.server-dialog__title {
  font-weight: 700;
  font-size: 1.05rem;
}

.server-dialog__body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.server-banner {
  font-size: 0.82rem;
}

.server-banner--ok {
  border: 1px solid rgba(38, 153, 102, 0.4);
  background: var(--app-surface-strong);
}

.server-banner--bad {
  border: 1px solid rgba(193, 56, 56, 0.4);
  background: var(--app-surface-strong);
}
</style>
