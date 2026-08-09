<template>
  <q-page class="row items-center justify-center">
    <q-card style="width: 420px; max-width: 92vw">
      <q-card-section>
        <div class="text-h6">Verificación 2FA</div>
        <div class="text-caption text-grey-7">Ingresa el código de tu aplicación TOTP.</div>
      </q-card-section>

      <q-separator />

      <q-card-section>
        <q-form @submit.prevent="onSubmit">
          <q-input v-model="code" label="Código" autocomplete="one-time-code" outlined />

          <div class="q-mt-lg">
            <q-btn
              :loading="loading"
              type="submit"
              label="Verificar"
              color="primary"
              class="full-width"
            />
          </div>
        </q-form>

        <q-banner v-if="errorMsg" class="q-mt-md" dense rounded inline-actions>
          {{ errorMsg }}
          <template #action>
            <q-btn flat label="Cerrar" @click="errorMsg = null" />
          </template>
        </q-banner>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from 'src/stores/auth.store';
import { useContextStore } from 'src/stores/context.store';
import { useSessionBootstrapStore } from 'src/stores/session-bootstrap.store';
import { apiErrorMessage } from 'src/core/api';
import { AUTHENTICATED_HOME_ROUTE } from 'src/modules/auth/navigation';

const router = useRouter();
const auth = useAuthStore();
const ctx = useContextStore();
const sessionBootstrap = useSessionBootstrapStore();

const code = ref('');
const loading = ref(false);
const errorMsg = ref<string | null>(null);

async function onSubmit() {
  loading.value = true;
  errorMsg.value = null;

  try {
    await auth.verifyTwoFactor(code.value.trim());

    await sessionBootstrap.loadSession({ force: true });

    if (auth.user?.must_change_password) {
      await router.replace('/password-change');
      return;
    }

    if (sessionBootstrap.payload?.bootstrap_state?.setup_required) {
      await router.replace('/bootstrap');
      return;
    }

    if (ctx.activeCompanyId) {
      await router.replace(AUTHENTICATED_HOME_ROUTE);
      return;
    }

    await router.replace('/select-context');
  } catch (e: unknown) {
    errorMsg.value = apiErrorMessage(e, 'No se pudo verificar el código.');
  } finally {
    loading.value = false;
  }
}
</script>
