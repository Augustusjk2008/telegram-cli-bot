export type ChatTracePreviewConfig = {
  maxLines: number;
  maxChars: number;
};

const DEFAULT_CHAT_TRACE_PREVIEW_MAX_LINES = 5;
const DEFAULT_CHAT_TRACE_PREVIEW_MAX_CHARS = 200;

function parsePositiveInteger(value: string | undefined, fallback: number) {
  const normalized = String(value ?? "").trim();
  if (!/^\d+$/.test(normalized)) {
    return fallback;
  }

  const parsed = Number.parseInt(normalized, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

export function resolveChatTracePreviewConfig(
  env: Record<string, string | undefined>,
): ChatTracePreviewConfig {
  return {
    maxLines: parsePositiveInteger(
      env.VITE_CHAT_TRACE_PREVIEW_MAX_LINES,
      DEFAULT_CHAT_TRACE_PREVIEW_MAX_LINES,
    ),
    maxChars: parsePositiveInteger(
      env.VITE_CHAT_TRACE_PREVIEW_MAX_CHARS,
      DEFAULT_CHAT_TRACE_PREVIEW_MAX_CHARS,
    ),
  };
}

const PUBLIC_ENV =
  typeof __PUBLIC_ENV__ !== "undefined"
    ? __PUBLIC_ENV__
    : {};

export const CHAT_TRACE_PREVIEW_CONFIG = resolveChatTracePreviewConfig(PUBLIC_ENV);
