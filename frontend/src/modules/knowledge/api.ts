/**
 * Conocimiento — búsqueda determinista en la documentación interna (FTS español);
 * síntesis con IA opcional (si el kill switch está encendido).
 */
import { api } from 'src/boot/axios';

export interface KnowledgeResult {
  source_path: string;
  heading: string;
  content: string;
  order: number;
}

export interface KnowledgeResponse {
  query: string;
  results: KnowledgeResult[];
  answer: string | null;
  ai_used: boolean;
}

export async function searchKnowledge(
  q: string,
  opts: { limit?: number; synthesize?: boolean } = {},
): Promise<KnowledgeResponse> {
  const params: Record<string, string | number> = { q, limit: opts.limit ?? 8 };
  if (opts.synthesize) params.synthesize = 1;
  const { data } = await api.get<KnowledgeResponse>('/knowledge/search/', { params });
  return data;
}

/** Respuesta del asistente del sistema: datos reales o documentación. */
export interface AssistantResponse {
  kind: 'data' | 'docs';
  answer: string | null;
  data?: Record<string, unknown>;
  skill?: string;
  results?: KnowledgeResult[];
  sources?: { n: number; source_path: string; heading: string }[] | null;
  ai_used: boolean;
}

export async function askAssistant(q: string): Promise<AssistantResponse> {
  const { data } = await api.get<AssistantResponse>('/knowledge/assistant/', { params: { q } });
  return data;
}

/** Asistente CONVERSACIONAL (multi-turno). El frontend manda el historial. */
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatReply {
  reply: string | null;
  used_skills: string[];
  sources?: { source_path: string; heading: string }[] | null;
  ai_used: boolean;
}

export async function chatAssistant(messages: ChatMessage[]): Promise<ChatReply> {
  const { data } = await api.post<ChatReply>('/knowledge/chat/', { messages });
  return data;
}

/** Sugerencias iniciales del asistente ("¿con qué te puedo ayudar?"). */
export interface KnowledgeSuggestionGroup {
  topic: string;
  icon: string;
  questions: string[];
}

export async function getKnowledgeSuggestions(): Promise<KnowledgeSuggestionGroup[]> {
  const { data } = await api.get<{ groups: KnowledgeSuggestionGroup[] }>('/knowledge/suggestions/');
  return data.groups;
}

/**
 * Asistente de DESARROLLO (solo dev/dueño, permiso `knowledge.dev.read`): ubica en el
 * CÓDIGO fuente indexado los fragmentos de un flujo y, opcionalmente, una nota del LLM
 * local que señala huecos. Retrieval determinista siempre; la nota IA respeta el kill switch.
 */
export interface DevCodeResult {
  source_path: string;
  heading: string;
  excerpt: string;
  content: string;
  rank: number;
}

export interface DevCodeFeedbackResponse {
  query: string;
  results: DevCodeResult[];
  answer: { text: string; sources: { n: number; source_path: string; heading: string }[] } | null;
  ai_used: boolean;
}

export async function devCodeFeedback(
  q: string,
  opts: { limit?: number; synthesize?: boolean } = {},
): Promise<DevCodeFeedbackResponse> {
  const params: Record<string, string | number> = { q, limit: opts.limit ?? 8 };
  if (opts.synthesize) params.synthesize = 1;
  const { data } = await api.get<DevCodeFeedbackResponse>('/knowledge/dev/feedback/', { params });
  return data;
}

/**
 * Asistente de desarrollo CONVERSACIONAL sobre el código (loop de 3): el LLM local explica
 * cómo está cableado un flujo usando los fragmentos reales; luego se exporta y se lleva a Claude.
 */
export interface DevChatFragment {
  source_path: string;
  heading: string;
  content: string;
}

export interface DevChatReply {
  reply: string | null;
  used_files: string[];
  fragments: DevChatFragment[];
  ai_used: boolean;
}

export async function devChat(
  messages: { role: 'user' | 'assistant'; content: string }[],
): Promise<DevChatReply> {
  const { data } = await api.post<DevChatReply>('/knowledge/dev/chat/', { messages });
  return data;
}

/** Exporta la conversación + los fragmentos de código reales como un .md para llevar a Claude. */
export async function devFeedbackExport(
  messages: { role: string; content: string }[],
  fragments: DevChatFragment[],
  title: string,
): Promise<{ markdown: string; filename: string }> {
  const { data } = await api.post<{ markdown: string; filename: string }>(
    '/knowledge/dev/feedback-export/',
    { messages, fragments, title },
  );
  return data;
}
