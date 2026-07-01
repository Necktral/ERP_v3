<template>
  <q-page class="app-page dev-page">
    <PageHeader
      title="Asistente de código (desarrollo)"
      subtitle="Conversá con el LLM local sobre cómo está cableado un flujo. Exportá la charla y llevala a Claude para reparar."
      hide-refresh
    />

    <div ref="hilo" class="dev-hilo">
      <div v-if="!mensajes.length" class="dev-intro">
        <div class="dev-intro__title">¿Qué flujo querés rastrear?</div>
        <div class="dev-intro__hint">
          Ej.: «¿cómo se crea y asigna un cargo a un usuario?», «¿por qué no carga?», «¿cuál de esas
          vías es la real?». El asistente local te explica cómo está cableado usando el código
          indexado. Para reparar de fondo, <b>Exportá</b> la conversación y traémela a Claude.
        </div>
      </div>

      <div
        v-for="(m, i) in mensajes"
        :key="i"
        class="dev-msg"
        :class="m.role === 'user' ? 'dev-msg--user' : 'dev-msg--bot'"
      >
        <q-icon v-if="m.role === 'assistant'" name="smart_toy" size="20px" class="dev-msg__avatar" />
        <div class="dev-bubble">{{ m.content }}</div>
      </div>

      <div v-if="enviando" class="dev-msg dev-msg--bot">
        <q-icon name="smart_toy" size="20px" class="dev-msg__avatar" />
        <div class="dev-bubble dev-bubble--typing"><q-spinner-dots size="22px" /> rastreando el código…</div>
      </div>
    </div>

    <div v-if="archivos.length" class="dev-files">
      <q-icon name="folder_open" size="16px" /> Archivos tocados: {{ archivos.join(' · ') }}
    </div>

    <div class="dev-input">
      <q-input
        v-model="entrada"
        outlined
        autogrow
        placeholder="Preguntá por un flujo… (ej. ¿cómo se asigna un cargo a un usuario?)"
        class="dev-input__field"
        :disable="enviando"
        @keyup.enter="enviarActual"
      >
        <template #prepend><q-icon name="travel_explore" /></template>
      </q-input>
      <q-btn
        unelevated
        round
        color="primary"
        icon="send"
        :loading="enviando"
        :disable="!entrada.trim() || enviando"
        @click="enviarActual"
      />
      <q-btn
        outline
        color="primary"
        icon="download"
        label="Exportar"
        :disable="!mensajes.length || exportando"
        :loading="exportando"
        @click="exportar"
      />
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import { devChat, devFeedbackExport, type DevChatFragment } from 'src/modules/knowledge/api';

type Msg = { role: 'user' | 'assistant'; content: string };

const mensajes = ref<Msg[]>([]);
const entrada = ref('');
const enviando = ref(false);
const exportando = ref(false);
const hilo = ref<HTMLElement | null>(null);
const fragmentos = ref<DevChatFragment[]>([]);
const archivos = ref<string[]>([]);

async function scrollAbajo() {
  await nextTick();
  if (hilo.value) hilo.value.scrollTop = hilo.value.scrollHeight;
}

function mergeFragmentos(nuevos: DevChatFragment[]) {
  for (const f of nuevos) {
    const key = `${f.source_path}#${f.heading}`;
    if (!fragmentos.value.some((x) => `${x.source_path}#${x.heading}` === key)) {
      fragmentos.value.push(f);
    }
    if (!archivos.value.includes(f.source_path)) archivos.value.push(f.source_path);
  }
}

async function enviarActual() {
  const texto = entrada.value.trim();
  if (!texto || enviando.value) return;
  mensajes.value.push({ role: 'user', content: texto });
  entrada.value = '';
  enviando.value = true;
  await scrollAbajo();
  try {
    const r = await devChat(mensajes.value);
    mensajes.value.push({ role: 'assistant', content: r.reply || 'No tengo respuesta para eso.' });
    mergeFragmentos(r.fragments || []);
  } catch (e) {
    mensajes.value.push({ role: 'assistant', content: apiErrorMessage(e, 'No se pudo consultar el código.') });
  } finally {
    enviando.value = false;
    await scrollAbajo();
  }
}

async function exportar() {
  if (!mensajes.value.length || exportando.value) return;
  exportando.value = true;
  try {
    const firstUser = mensajes.value.find((m) => m.role === 'user');
    const title = firstUser ? firstUser.content.slice(0, 80) : 'Feedback de código';
    const { markdown, filename } = await devFeedbackExport(mensajes.value, fragmentos.value, title);
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    mensajes.value.push({ role: 'assistant', content: apiErrorMessage(e, 'No se pudo exportar la conversación.') });
  } finally {
    exportando.value = false;
  }
}
</script>

<style scoped>
.dev-page {
  display: flex;
  flex-direction: column;
}

.dev-hilo {
  flex: 1;
  overflow-y: auto;
  padding: var(--app-space-2) 0 var(--app-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.dev-intro {
  padding: var(--app-space-4);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
}

.dev-intro__title {
  font-weight: 800;
  color: var(--app-text);
  font-size: 1.05rem;
  margin-bottom: var(--app-space-2);
}

.dev-intro__hint {
  font-size: 0.9rem;
  color: var(--app-text-muted);
  line-height: 1.5;
}

.dev-msg {
  display: flex;
  align-items: flex-end;
  gap: var(--app-space-2);
  max-width: 85%;
}

.dev-msg--user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.dev-msg--bot {
  align-self: flex-start;
}

.dev-msg__avatar {
  color: var(--app-primary);
  margin-bottom: 2px;
}

.dev-bubble {
  padding: var(--app-space-3) var(--app-space-4);
  border-radius: var(--app-radius-lg);
  white-space: pre-wrap;
  line-height: 1.45;
  font-size: 0.95rem;
  border: 1px solid var(--app-border);
  background: var(--app-surface-strong);
  color: var(--app-text);
}

.dev-msg--user .dev-bubble {
  background: var(--app-primary);
  border-color: var(--app-primary);
  color: #fff;
}

.dev-bubble--typing {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--app-text-muted);
}

.dev-files {
  font-size: 0.78rem;
  color: var(--app-text-muted);
  padding: var(--app-space-1) 0;
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
  flex-wrap: wrap;
}

.dev-input {
  display: flex;
  align-items: flex-end;
  gap: var(--app-space-2);
  padding-top: var(--app-space-3);
  border-top: 1px solid var(--app-border);
}

.dev-input__field {
  flex: 1;
}
</style>
