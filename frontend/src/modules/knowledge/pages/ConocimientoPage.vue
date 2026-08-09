<template>
  <q-page class="app-page kno-page">
    <PageHeader
      title="Asistente"
      subtitle="Conversá: preguntá datos de tu sistema, cómo se usa, o pedí ideas para mejorar un flujo."
      hide-refresh
    />

    <div ref="hilo" class="kno-hilo">
      <!-- Menú inicial: aparece al entrar (sin mensajes) — "¿con qué te puedo ayudar?" -->
      <div v-if="!mensajes.length && sugerencias.length" class="kno-sugerencias">
        <div class="kno-sugerencias__head">¿Con qué te puedo ayudar?</div>
        <div v-for="g in sugerencias" :key="g.topic" class="kno-grupo">
          <div class="kno-grupo__tema">
            <q-icon :name="g.icon" size="20px" color="primary" />
            <span>{{ g.topic }}</span>
          </div>
          <div class="kno-grupo__chips">
            <q-chip
              v-for="p in g.questions"
              :key="p"
              clickable
              outline
              color="primary"
              @click="enviar(p)"
            >
              {{ p }}
            </q-chip>
          </div>
        </div>
        <div class="kno-sugerencias__hint">Elegí una pregunta o escribí la tuya. Puedo recordar el hilo de la charla.</div>
      </div>

      <!-- Conversación -->
      <div
        v-for="(m, i) in mensajes"
        :key="i"
        class="kno-msg"
        :class="m.role === 'user' ? 'kno-msg--user' : 'kno-msg--bot'"
      >
        <q-icon v-if="m.role === 'assistant'" name="smart_toy" size="20px" class="kno-msg__avatar" />
        <div class="kno-bubble">{{ m.content }}</div>
      </div>

      <div v-if="enviando" class="kno-msg kno-msg--bot">
        <q-icon name="smart_toy" size="20px" class="kno-msg__avatar" />
        <div class="kno-bubble kno-bubble--typing">
          <q-spinner-dots size="22px" /> pensando…
        </div>
      </div>
    </div>

    <!-- Entrada -->
    <div class="kno-input">
      <q-input
        v-model="entrada"
        outlined
        autogrow
        placeholder="Escribí tu mensaje… (ej. ¿cómo va el día?, ¿cuánto me deben?, ¿cómo registro un empleado?)"
        class="kno-input__field"
        :disable="enviando"
        @keyup.enter="enviarActual"
      >
        <template #prepend><q-icon name="forum" /></template>
      </q-input>
      <q-btn
        unelevated
        round
        color="primary"
        icon="send"
        aria-label="Enviar mensaje"
        :loading="enviando"
        :disable="!entrada.trim() || enviando"
        @click="enviarActual"
      />
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue';
import PageHeader from 'src/components/PageHeader.vue';
import { apiErrorMessage } from 'src/core/api';
import {
  chatAssistant,
  getKnowledgeSuggestions,
  type ChatMessage,
  type KnowledgeSuggestionGroup,
} from 'src/modules/knowledge/api';

const mensajes = ref<ChatMessage[]>([]);
const entrada = ref('');
const enviando = ref(false);
const sugerencias = ref<KnowledgeSuggestionGroup[]>([]);
const hilo = ref<HTMLElement | null>(null);

onMounted(async () => {
  try {
    sugerencias.value = await getKnowledgeSuggestions();
  } catch {
    // El menú es opcional; si falla, el chat sigue funcionando igual.
  }
});

async function scrollAbajo() {
  await nextTick();
  const el = hilo.value;
  if (el) el.scrollTop = el.scrollHeight;
}

function enviar(texto: string) {
  entrada.value = texto;
  void enviarActual();
}

async function enviarActual() {
  const texto = entrada.value.trim();
  if (!texto || enviando.value) return;
  mensajes.value.push({ role: 'user', content: texto });
  entrada.value = '';
  enviando.value = true;
  await scrollAbajo();
  try {
    const r = await chatAssistant(mensajes.value);
    mensajes.value.push({ role: 'assistant', content: r.reply || 'No tengo una respuesta para eso.' });
  } catch (e) {
    mensajes.value.push({
      role: 'assistant',
      content: apiErrorMessage(e, 'No se pudo responder. Intentá de nuevo.'),
    });
  } finally {
    enviando.value = false;
    await scrollAbajo();
  }
}
</script>

<style scoped>
.kno-page {
  display: flex;
  flex-direction: column;
}

.kno-hilo {
  flex: 1;
  overflow-y: auto;
  padding: var(--app-space-2) 0 var(--app-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.kno-msg {
  display: flex;
  align-items: flex-end;
  gap: var(--app-space-2);
  max-width: 80%;
}

.kno-msg--user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.kno-msg--bot {
  align-self: flex-start;
}

.kno-msg__avatar {
  color: var(--app-primary);
  margin-bottom: 2px;
}

.kno-bubble {
  padding: var(--app-space-3) var(--app-space-4);
  border-radius: var(--app-radius-lg);
  white-space: pre-wrap;
  line-height: 1.45;
  font-size: 1rem;
  border: 1px solid var(--app-border);
  background: var(--app-surface-strong);
  color: var(--app-text);
}

.kno-msg--user .kno-bubble {
  background: var(--app-primary);
  border-color: var(--app-primary);
  color: #fff;
}

.kno-bubble--typing {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--app-text-muted);
}

.kno-input {
  display: flex;
  align-items: flex-end;
  gap: var(--app-space-3);
  padding-top: var(--app-space-3);
  border-top: 1px solid var(--app-border);
}

.kno-input__field {
  flex: 1;
}

/* Menú inicial de sugerencias */
.kno-sugerencias {
  padding: var(--app-space-4);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
}

.kno-sugerencias__head {
  font-weight: 800;
  color: var(--app-text);
  font-size: 1.05rem;
  margin-bottom: var(--app-space-3);
}

.kno-grupo {
  margin-bottom: var(--app-space-3);
}

.kno-grupo__tema {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  font-weight: 700;
  color: var(--app-text);
  margin-bottom: var(--app-space-1);
}

.kno-grupo__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-1);
}

.kno-sugerencias__hint {
  margin-top: var(--app-space-3);
  font-size: 0.82rem;
  color: var(--app-text-muted);
}
</style>
