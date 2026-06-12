import type { ChatMessageMetaInfo, ChatTraceEvent } from "../services/types";
import type { AgUiPermissionRequest, AgUiRunState, NativeAgentTranscriptEntry } from "./agUiRunReducer";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asString(value: unknown) {
  return typeof value === "string" ? value : "";
}

function stringifyValue(value: unknown) {
  if (typeof value === "string") return value;
  if (typeof value === "undefined" || value === null) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function payloadText(trace: ChatTraceEvent) {
  const payload = asRecord(trace.payload);
  return (
    stringifyValue(payload.arguments).trim()
    || stringifyValue(payload.raw_arguments).trim()
    || stringifyValue(payload.output).trim()
    || stringifyValue(payload.content).trim()
  );
}

function pickString(...values: Array<unknown>) {
  for (const value of values) {
    const text = asString(value).trim();
    if (text) {
      return text;
    }
  }
  return undefined;
}

function traceStableKey(trace: ChatTraceEvent) {
  if (trace.id) {
    return `id:${trace.id}`;
  }
  if (typeof trace.ordinal === "number") {
    return `ordinal:${trace.ordinal}`;
  }
  if (typeof trace.sequence === "number") {
    return `sequence:${trace.sequence}`;
  }
  return "";
}

function traceCallKey(trace: ChatTraceEvent) {
  const callId = asString(trace.callId).trim();
  return callId ? `${trace.kind}:${callId}` : "";
}

function traceRichness(trace: ChatTraceEvent) {
  return (
    payloadText(trace).length * 10
    + trace.summary.trim().length * 5
    + (pickString(trace.toolName, trace.title) ? 2 : 0)
    + (typeof trace.payload !== "undefined" ? 1 : 0)
  );
}

function shouldReplaceTraceEvent(current: ChatTraceEvent, incoming: ChatTraceEvent) {
  if (current.kind === incoming.kind && current.kind === "tool_result" && current.callId && current.callId === incoming.callId) {
    return true;
  }
  const currentScore = traceRichness(current);
  const incomingScore = traceRichness(incoming);
  if (incomingScore !== currentScore) {
    return incomingScore > currentScore;
  }
  return true;
}

function mergeTraceEvent(current: ChatTraceEvent, incoming: ChatTraceEvent): ChatTraceEvent {
  const primary = shouldReplaceTraceEvent(current, incoming) ? incoming : current;
  const secondary = primary === incoming ? current : incoming;
  const merged: ChatTraceEvent = {
    kind: primary.kind || secondary.kind || "event",
    summary: primary.summary || secondary.summary || "",
  };
  const id = pickString(current.id, incoming.id);
  const source = pickString(primary.source, secondary.source);
  const rawType = pickString(primary.rawType, secondary.rawType);
  const title = pickString(primary.title, secondary.title);
  const toolName = pickString(primary.toolName, secondary.toolName);
  const callId = pickString(primary.callId, secondary.callId);
  const createdAt = pickString(current.createdAt, incoming.createdAt);
  const payload = typeof primary.payload !== "undefined" ? primary.payload : secondary.payload;

  if (id) {
    merged.id = id;
  }
  if (typeof current.ordinal === "number" || typeof incoming.ordinal === "number") {
    merged.ordinal = typeof current.ordinal === "number" ? current.ordinal : incoming.ordinal;
  }
  if (typeof current.sequence === "number" || typeof incoming.sequence === "number") {
    merged.sequence = typeof current.sequence === "number" ? current.sequence : incoming.sequence;
  }
  if (createdAt) {
    merged.createdAt = createdAt;
  }
  if (source) {
    merged.source = source;
  }
  if (rawType) {
    merged.rawType = rawType;
  }
  if (title) {
    merged.title = title;
  }
  if (toolName) {
    merged.toolName = toolName;
  }
  if (callId) {
    merged.callId = callId;
  }
  if (typeof payload !== "undefined") {
    merged.payload = payload;
  }
  return merged;
}

function permissionId(trace: ChatTraceEvent) {
  const payload = asRecord(trace.payload);
  return asString(payload.permissionId || payload.id || payload.permissionID || payload.permission_id).trim();
}

function permissionFromTrace(trace: ChatTraceEvent, summary: string): AgUiPermissionRequest {
  const payload = asRecord(trace.payload);
  const id = permissionId(trace);
  const uiKind = pickString(payload.uiKind, payload.ui_kind) || "confirm";
  const options = Array.isArray(payload.options) ? payload.options : undefined;
  const message = pickString(payload.message, payload.title, summary);
  return {
    permissionId: id,
    summary,
    state: pickString(payload.state, payload.status) || "",
    content: payload,
    source: pickString(trace.source, payload.source) || "",
    uiKind,
    ...(options ? { options } : {}),
    ...(typeof payload.defaultValue !== "undefined" ? { defaultValue: payload.defaultValue } : {}),
    ...(typeof payload.value !== "undefined" ? { value: payload.value } : {}),
    ...(pickString(payload.placeholder) ? { placeholder: pickString(payload.placeholder) } : {}),
    ...(message ? { message } : {}),
  };
}

function isPermissionPending(trace: ChatTraceEvent) {
  const payload = asRecord(trace.payload);
  const state = asString(payload.state || payload.status).trim().toLowerCase();
  return !state || (
    !state.includes("replied")
    && !state.includes("approved")
    && !state.includes("reject")
    && !state.includes("denied")
    && !state.includes("allow")
  );
}

function entryKind(trace: ChatTraceEvent): NativeAgentTranscriptEntry["kind"] {
  if (trace.kind === "commentary" || trace.kind === "reasoning" || trace.kind === "status") return "process";
  if (trace.kind === "tool_call") return "tool";
  if (trace.kind === "permission") return "permission";
  if (trace.kind === "error") return "error";
  if (trace.kind === "cancelled") return "cancelled";
  return "event";
}

function entryLabel(kind: NativeAgentTranscriptEntry["kind"], trace: ChatTraceEvent) {
  if (kind === "process") return trace.kind === "reasoning" ? "思考" : "过程";
  if (kind === "tool") return trace.toolName || trace.title || "工具";
  if (kind === "permission") return "权限";
  if (kind === "error") return "错误";
  if (kind === "cancelled") return "已取消";
  return trace.kind === "tool_result" ? "工具结果" : "事件";
}

function traceOrder(trace: ChatTraceEvent, index: number) {
  if (typeof trace.ordinal === "number") return trace.ordinal;
  if (typeof trace.sequence === "number") return trace.sequence;
  return index + 1;
}

function normalizeNativeAgentTrace(trace: ChatTraceEvent[]) {
  return trace
    .map((event, index) => ({ event, index }))
    .sort((left, right) => traceOrder(left.event, left.index) - traceOrder(right.event, right.index))
    .map((item) => item.event);
}

function shouldNormalizeAsNativeFlat(trace: ChatTraceEvent[]) {
  const hasNativeSource = trace.some((event) => {
    const source = asString(event.source).trim().toLowerCase();
    return source === "native_agent" || source === "native";
  });
  if (hasNativeSource) {
    return true;
  }
  const hasToolCall = trace.some((event) => event.kind === "tool_call" && asString(event.callId).trim());
  const hasReclassifiedCommentary = trace.some((event) => (
    event.kind === "commentary" && asString(event.rawType).trim() === "message.text.reclassified"
  ));
  return hasToolCall && hasReclassifiedCommentary;
}

export function mergeChatTraceEvents(
  sources: Array<ChatTraceEvent[] | undefined>,
  options: { nativeFlat?: boolean } = {},
): ChatTraceEvent[] | undefined {
  const merged: ChatTraceEvent[] = [];
  const stableIndexMap = new Map<string, number>();
  const callIndexMap = new Map<string, number>();

  for (const source of sources) {
    for (const event of source || []) {
      const stableKey = traceStableKey(event);
      const callKey = traceCallKey(event);
      const existingIndex = (
        (callKey ? callIndexMap.get(callKey) : undefined)
        ?? (stableKey ? stableIndexMap.get(stableKey) : undefined)
      );
      if (typeof existingIndex === "number") {
        merged[existingIndex] = mergeTraceEvent(merged[existingIndex], event);
        const nextStableKey = traceStableKey(merged[existingIndex]);
        const nextCallKey = traceCallKey(merged[existingIndex]);
        if (nextStableKey) {
          stableIndexMap.set(nextStableKey, existingIndex);
        }
        if (nextCallKey) {
          callIndexMap.set(nextCallKey, existingIndex);
        }
        continue;
      }
      const nextIndex = merged.length;
      merged.push(event);
      if (stableKey) {
        stableIndexMap.set(stableKey, nextIndex);
      }
      if (callKey) {
        callIndexMap.set(callKey, nextIndex);
      }
    }
  }

  const normalized = options.nativeFlat || shouldNormalizeAsNativeFlat(merged)
    ? normalizeNativeAgentTrace(merged)
    : merged;
  return normalized.length > 0 ? normalized : undefined;
}

function traceToEntry(trace: ChatTraceEvent, index: number, seq = traceOrder(trace, index)): NativeAgentTranscriptEntry {
  const kind = entryKind(trace);
  const body = kind === "tool" || trace.kind === "tool_result" ? payloadText(trace) : undefined;
  const summary = trace.summary || trace.title || trace.toolName || "";
  const permission = kind === "permission" ? permissionFromTrace(trace, summary) : undefined;
  return {
    id: trace.id || `${trace.kind || "trace"}-${seq}-${index}`,
    seq,
    kind,
    label: entryLabel(kind, trace),
    summary,
    body,
    collapsedByDefault: !["process", "permission", "error", "cancelled"].includes(kind),
    trace,
    ...(permission ? { permissionId: permission.permissionId, pending: isPermissionPending(trace), permission } : {}),
  };
}

export function isNativeAgentMessage(meta?: ChatMessageMetaInfo): boolean {
  const provider = String(meta?.nativeSource?.provider || "").trim().toLowerCase();
  return (
    meta?.tracePresentation === "native_agent_flat"
    || provider === "native_agent"
    || provider === "原生 agent"
  );
}

export function buildNativeAgentTranscriptEntries(input: {
  trace?: ChatTraceEvent[];
  agUiState?: AgUiRunState | null;
}): NativeAgentTranscriptEntry[] {
  const liveTrace = input.agUiState?.entries
    ?.map((entry) => entry.trace)
    .filter((trace): trace is ChatTraceEvent => Boolean(trace));
  const traceSource = input.trace?.length ? input.trace : liveTrace;
  const normalizedTrace = mergeChatTraceEvents([traceSource], { nativeFlat: true });

  if (normalizedTrace?.length) {
    return normalizedTrace.map((trace, index) => traceToEntry(trace, index, index + 1));
  }

  if (input.agUiState?.entries?.length) {
    return [...input.agUiState.entries].sort((left, right) => left.seq - right.seq);
  }

  return [];
}
