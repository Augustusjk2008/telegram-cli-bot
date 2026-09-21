import type { ChatMessage, ChatStatusUpdate, ChatTranslation, ChatTranslationConfig } from "../services/types";

export const DEFAULT_CHAT_TRANSLATION_CONFIG: ChatTranslationConfig = {
  reasoning_effort: "none",
  user_prompt: "",
  assistant_prompt: "",
  translate_user_enabled: false,
  translate_assistant_enabled: false,
  base_url: "",
  api_key_configured: false,
  model: "",
  request_timeout_seconds: 15,
};

export function mapChatTranslation(value: unknown): ChatTranslation | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  if (raw.status !== "pending" && raw.status !== "completed" && raw.status !== "failed") return null;
  if (typeof raw.source_digest !== "string" || typeof raw.target_language !== "string") return null;
  return {
    status: raw.status,
    target_language: raw.target_language,
    source_digest: raw.source_digest,
    ...(typeof raw.text === "string" ? { text: raw.text } : {}),
    ...(typeof raw.completed_at === "string" ? { completed_at: raw.completed_at } : {}),
    ...(typeof raw.error === "string" ? { error: raw.error } : {}),
  };
}

export function mergeTranslation(previous: ChatMessage["translation"], next: ChatMessage["translation"]) {
  if (next === undefined) return previous;
  if (next === null && previous?.status === "completed") return previous;
  if (previous && next && previous.source_digest === next.source_digest
    && previous.target_language === next.target_language
    && (previous.status === "completed" || (previous.status === "failed" && next.status === "pending"))) {
    return previous;
  }
  return next;
}

export function mergeMessageTranslation(previous: ChatMessage, next: ChatMessage): Partial<ChatMessage> {
  const sameSource = previous.text === next.text;
  return {
    translation: sameSource ? mergeTranslation(previous.translation, next.translation) : next.translation,
    agentInputText: next.agentInputText === undefined && sameSource ? previous.agentInputText : next.agentInputText,
    translationView: previous.translationView ?? next.translationView,
  };
}

export function translatedMessageText(item: ChatMessage) {
  return item.translationView !== "original" && item.translation?.status === "completed" && item.translation.text?.trim()
    ? item.translation.text : item.text;
}

/** Both CLI meta/status and AG-UI RUN_STARTED/CUSTOM carry these extension fields. */
export function mapUserTranslationUpdate(value: unknown): ChatStatusUpdate {
  if (!value || typeof value !== "object") return {};
  const event = value as Record<string, unknown>;
  const nested = event.type === "CUSTOM" && event.value && typeof event.value === "object"
    ? event.value as Record<string, unknown> : {};
  const raw = { ...event, ...nested };
  return {
    ...(typeof raw.turn_id === "string" && raw.turn_id ? { turnId: raw.turn_id } : {}),
    ...(typeof raw.assistant_message_id === "string" && raw.assistant_message_id ? { assistantMessageId: raw.assistant_message_id } : {}),
    ...(typeof raw.user_message_id === "string" && raw.user_message_id ? { userMessageId: raw.user_message_id } : {}),
    ...("user_translation" in raw ? { userTranslation: mapChatTranslation(raw.user_translation) } : {}),
    ...(typeof raw.agent_input_text === "string" || raw.agent_input_text === null ? { agentInputText: raw.agent_input_text as string | null } : {}),
  };
}

export function applyUserTranslationUpdate(items: ChatMessage[], localId: string, status: ChatStatusUpdate) {
  if (!status.userMessageId && !status.turnId && status.userTranslation === undefined && status.agentInputText === undefined) return items;
  const index = items.findIndex((item) => item.role === "user" && (
    item.id === localId || item.id === status.userMessageId || Boolean(status.turnId && item.turnId === status.turnId)
  ));
  if (index < 0) return items;
  const item = items[index];
  const next = items.slice();
  next[index] = {
    ...item,
    ...(status.userMessageId ? { id: status.userMessageId } : {}),
    ...(status.turnId ? { turnId: status.turnId } : {}),
    ...(status.userTranslation !== undefined ? { translation: mergeTranslation(item.translation, status.userTranslation) } : {}),
    ...(status.agentInputText !== undefined ? { agentInputText: status.agentInputText } : {}),
  };
  return next;
}
