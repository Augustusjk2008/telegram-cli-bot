import type { ChatMessageContextUsage } from "../services/types";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function firstString(raw: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = asString(raw[key]);
    if (value) {
      return value;
    }
  }
  return "";
}

function firstNumber(raw: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = raw[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return undefined;
}

function displayContextProvider(provider: string) {
  const normalized = provider.trim().toLowerCase();
  if (normalized === "native_agent" || normalized === "opencode") {
    return "原生 agent";
  }
  return provider || undefined;
}

export function mapChatMessageContextUsage(value: unknown): ChatMessageContextUsage | undefined {
  const raw = asRecord(value);
  const provider = displayContextProvider(firstString(raw, "provider"));
  const source = firstString(raw, "source");
  const sessionId = firstString(raw, "sessionId", "session_id");
  const usedTokens = firstNumber(raw, "usedTokens", "used_tokens");
  const contextWindow = firstNumber(raw, "contextWindow", "context_window");
  const contextLeftPercent = firstNumber(raw, "contextLeftPercent", "context_left_percent");
  const contextUsed = firstNumber(raw, "contextUsed", "context_used");
  const contextUsedPercent = firstNumber(raw, "contextUsedPercent", "context_used_percent");
  const inputTokens = firstNumber(raw, "inputTokens", "input_tokens");
  const cacheReadTokens = firstNumber(raw, "cacheReadTokens", "cache_read_tokens");
  const cacheWriteTokens = firstNumber(raw, "cacheWriteTokens", "cache_write_tokens");
  const outputTokens = firstNumber(raw, "outputTokens", "output_tokens");
  const reasoningTokens = firstNumber(raw, "reasoningTokens", "reasoning_tokens");
  const model = firstString(raw, "model");
  const usedDisplay = firstString(raw, "usedDisplay", "used_display");
  const windowDisplay = firstString(raw, "windowDisplay", "window_display");
  const statusText = firstString(raw, "statusText", "status_text");
  const compactionCount = firstNumber(raw, "compactionCount", "compaction_count");

  const contextUsage: ChatMessageContextUsage = {
    ...(provider ? { provider } : {}),
    ...(source ? { source } : {}),
    ...(sessionId ? { sessionId } : {}),
    ...(typeof usedTokens === "number" ? { usedTokens } : {}),
    ...(typeof contextWindow === "number" ? { contextWindow } : {}),
    ...(typeof contextLeftPercent === "number" ? { contextLeftPercent } : {}),
    ...(typeof contextUsed === "number" ? { contextUsed } : {}),
    ...(typeof contextUsedPercent === "number" ? { contextUsedPercent } : {}),
    ...(typeof inputTokens === "number" ? { inputTokens } : {}),
    ...(typeof cacheReadTokens === "number" ? { cacheReadTokens } : {}),
    ...(typeof cacheWriteTokens === "number" ? { cacheWriteTokens } : {}),
    ...(typeof outputTokens === "number" ? { outputTokens } : {}),
    ...(typeof reasoningTokens === "number" ? { reasoningTokens } : {}),
    ...(model ? { model } : {}),
    ...(usedDisplay ? { usedDisplay } : {}),
    ...(windowDisplay ? { windowDisplay } : {}),
    ...(statusText ? { statusText } : {}),
    ...(typeof compactionCount === "number" && compactionCount > 0 ? { compactionCount } : {}),
  };

  return Object.keys(contextUsage).length > 0 ? contextUsage : undefined;
}
