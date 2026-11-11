import type { ChatEndlessEvent, ChatTraceEvent } from "../services/types";

export type CliTranscriptEntry = {
  id: string;
  seq: number;
  kind: "process" | "tool" | "event" | "error" | "cancelled" | "endless_error" | "endless_continue";
  label: string;
  summary: string;
  body?: string;
  collapsedByDefault: boolean;
  trace?: ChatTraceEvent;
  attempt?: number;
  createdAt?: string;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asString(value: unknown) {
  return typeof value === "string" ? value : "";
}

function identifierText(value: unknown) {
  if (typeof value === "string" || typeof value === "number" || typeof value === "bigint") {
    return String(value).trim();
  }
  return "";
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
  const wrappedPayloadText = (
    stringifyValue(payload.arguments).trim()
    || stringifyValue(payload.raw_arguments).trim()
    || stringifyValue(payload.output).trim()
    || stringifyValue(payload.content).trim()
  );
  const hasWrappedPayload = ["arguments", "raw_arguments", "output", "content"]
    .some((key) => Object.prototype.hasOwnProperty.call(payload, key));
  return wrappedPayloadText || (hasWrappedPayload ? "" : stringifyValue(trace.payload).trim());
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
  const id = identifierText(trace.id);
  if (id) {
    return `id:${id}`;
  }
  if (typeof trace.ordinal === "number") {
    return `ordinal:${trace.ordinal}`;
  }
  if (typeof trace.sequence === "number") {
    return `sequence:${trace.sequence}`;
  }
  return "";
}

function normalizeTraceSummary(value: unknown) {
  return asString(value).trim().replace(/\s+/g, " ");
}

function stableSerialize(value: unknown, seen = new WeakSet<object>()): string {
  if (typeof value === "undefined") return "undefined";
  if (value === null) return "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
    return String(value);
  }
  if (typeof value === "function" || typeof value === "symbol") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item, seen)).join(",")}]`;
  }
  if (typeof value === "object") {
    if (seen.has(value)) return "[Circular]";
    seen.add(value);
    const record = value as Record<string, unknown>;
    const serialized = `{${Object.keys(record)
      .filter((key) => typeof record[key] !== "undefined")
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableSerialize(record[key], seen)}`)
      .join(",")}}`;
    seen.delete(value);
    return serialized;
  }
  return String(value);
}

export function traceEventFingerprint(trace: ChatTraceEvent) {
  return stableSerialize(trace);
}

export function traceEventsEquivalent(left: ChatTraceEvent, right: ChatTraceEvent) {
  return traceEventFingerprint(left) === traceEventFingerprint(right);
}

function traceCallKey(trace: ChatTraceEvent) {
  const callId = asString(trace.callId).trim();
  return callId ? `${trace.kind}:${callId}` : "";
}

function traceFallbackKey(trace: ChatTraceEvent) {
  const rawType = asString(trace.rawType).trim();
  const callId = asString(trace.callId).trim();
  const summary = asString(trace.summary).trim();
  if (!rawType && !callId && !summary) {
    return "";
  }
  return `${trace.kind}:${rawType}:${callId}:${summary}`;
}

function traceReconciliationKey(trace: ChatTraceEvent) {
  const kind = asString(trace.kind).trim();
  const rawType = asString(trace.rawType).trim();
  const callId = asString(trace.callId).trim();
  const summary = asString(trace.summary).trim().replace(/\s+/g, " ");
  if (!kind || (!rawType && !callId && !summary)) {
    return "";
  }
  return `${kind}:${rawType}:${callId}:${summary}`;
}

function traceRichness(trace: ChatTraceEvent) {
  return (
    payloadText(trace).length * 10
    + trace.summary.trim().length * 5
    + (pickString(trace.toolName, trace.title) ? 2 : 0)
    + (typeof trace.payload !== "undefined" ? 1 : 0)
  );
}

function shouldReplaceTraceEvent(current: ChatTraceEvent, incoming: ChatTraceEvent, preferCurrentOnEqualAnonymous = false) {
  if (current.kind === incoming.kind && current.kind === "tool_result" && current.callId && current.callId === incoming.callId) {
    return true;
  }
  const currentScore = traceRichness(current);
  const incomingScore = traceRichness(incoming);
  if (incomingScore !== currentScore) {
    return incomingScore > currentScore;
  }
  if (
    preferCurrentOnEqualAnonymous
    &&
    !traceStableKey(current)
    && !traceStableKey(incoming)
    && normalizeTraceSummary(current.summary) === normalizeTraceSummary(incoming.summary)
  ) {
    return false;
  }
  return true;
}

function mergeTraceEvent(current: ChatTraceEvent, incoming: ChatTraceEvent, preferCurrentOnEqualAnonymous = false): ChatTraceEvent {
  const primary = shouldReplaceTraceEvent(current, incoming, preferCurrentOnEqualAnonymous) ? incoming : current;
  const secondary = primary === incoming ? current : incoming;
  const merged: ChatTraceEvent = {
    kind: primary.kind || secondary.kind || "event",
    summary: primary.summary || secondary.summary || "",
  };
  const id = identifierText(current.id) || identifierText(incoming.id);
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

function entryKind(trace: ChatTraceEvent): CliTranscriptEntry["kind"] {
  if (trace.kind === "commentary" || trace.kind === "reasoning" || trace.kind === "status") return "process";
  if (trace.kind === "tool_call") return "tool";
  if (trace.kind === "error") return "error";
  if (trace.kind === "cancelled") return "cancelled";
  return "event";
}

function entryLabel(kind: CliTranscriptEntry["kind"], trace: ChatTraceEvent) {
  if (kind === "process") return trace.kind === "reasoning" ? "思考" : "过程";
  if (kind === "tool") return trace.toolName || trace.title || "工具";
  if (kind === "error") return "错误";
  if (kind === "cancelled") return "已取消";
  return trace.kind === "tool_result" ? "工具结果" : "事件";
}

function traceOrder(trace: ChatTraceEvent, index: number) {
  if (typeof trace.ordinal === "number") return trace.ordinal;
  if (typeof trace.sequence === "number") return trace.sequence;
  return index + 1;
}

function normalizeTranscriptText(value: string) {
  return value
    .replace(/<thinking\b[^>]*>[\s\S]*?<\/thinking>/gi, "")
    .replace(/<thinking\b[^>]*>[\s\S]*$/gi, "")
    .replace(/<\/thinking>/gi, "")
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

export function isDuplicateFinalProcessTrace(trace: ChatTraceEvent, finalText: string) {
  const kind = String(trace.kind || "").trim();
  const normalizedFinalText = normalizeTranscriptText(finalText);
  if (!normalizedFinalText || (kind && kind !== "commentary" && kind !== "reasoning")) {
    return false;
  }
  return normalizeTranscriptText(trace.summary || "") === normalizedFinalText;
}

export function mergeChatTraceEvents(
  sources: Array<ChatTraceEvent[] | undefined>,
  options: {

    reconcileTraceSnapshots?: boolean;

  } = {},
): ChatTraceEvent[] | undefined {
  const merged: ChatTraceEvent[] = [];
  const stableIndexMap = new Map<string, number>();
  const callIndexMap = new Map<string, number>();
  const fallbackIndexMap = new Map<string, number>();
  for (const source of sources) {
    const reconciliationCandidates = new Map<string, number[]>();
    const semanticallyMatchedIndexes = new Set<number>();
    if (options.reconcileTraceSnapshots) {
      merged.forEach((event, index) => {
        const key = traceReconciliationKey(event);
        if (!key) {
          return;
        }
        const candidates = reconciliationCandidates.get(key) || [];
        candidates.push(index);
        reconciliationCandidates.set(key, candidates);
      });
    }
    for (const event of source || []) {
      const stableKey = traceStableKey(event);
      const callKey = traceCallKey(event);
      const fallbackKey = traceFallbackKey(event);
      let existingIndex = (
        (callKey ? callIndexMap.get(callKey) : undefined)
        ?? (stableKey ? stableIndexMap.get(stableKey) : undefined)
        ?? (fallbackKey ? fallbackIndexMap.get(fallbackKey) : undefined)
      );

      if (typeof existingIndex !== "number" && options.reconcileTraceSnapshots) {
        const reconciliationKey = traceReconciliationKey(event);
        const candidates = reconciliationKey ? reconciliationCandidates.get(reconciliationKey) || [] : [];
        existingIndex = candidates.find((index) => !semanticallyMatchedIndexes.has(index));
      }
      if (typeof existingIndex === "number") {
        semanticallyMatchedIndexes.add(existingIndex);
        merged[existingIndex] = mergeTraceEvent(
          merged[existingIndex],
          event,
          false,
        );
        const nextStableKey = traceStableKey(merged[existingIndex]);
        const nextCallKey = traceCallKey(merged[existingIndex]);
        const nextFallbackKey = traceFallbackKey(merged[existingIndex]);
        if (nextStableKey) {
          stableIndexMap.set(nextStableKey, existingIndex);
        }
        if (nextCallKey) {
          callIndexMap.set(nextCallKey, existingIndex);
        }
        if (nextFallbackKey) {
          fallbackIndexMap.set(nextFallbackKey, existingIndex);
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
      if (fallbackKey) {
        fallbackIndexMap.set(fallbackKey, nextIndex);
      }
    }
  }

  return merged.length > 0 ? merged : undefined;
}

function traceToEntry(trace: ChatTraceEvent, index: number, seq = traceOrder(trace, index)): CliTranscriptEntry {
  const kind = entryKind(trace);
  const body = kind === "tool" || trace.kind === "tool_result" ? payloadText(trace) : undefined;
  const summary = trace.summary || trace.title || trace.toolName || "";
  return {
    id: trace.id || `${trace.kind || "trace"}-${seq}-${index}`,
    seq,
    kind,
    label: entryLabel(kind, trace),
    summary,
    body,
    collapsedByDefault: !["process", "error", "cancelled"].includes(kind),
    trace,
    ...(trace.createdAt ? { createdAt: trace.createdAt } : {}),
  };
}

function endlessEventToEntry(event: ChatEndlessEvent): CliTranscriptEntry {
  const kind = event.kind === "error" ? "endless_error" : "endless_continue";
  return {
    id: `endless-${event.sequence}-${kind}`,
    seq: event.sequence,
    kind,
    label: event.kind === "error" ? "错误" : "Continue",
    summary: event.text,
    collapsedByDefault: true,
    attempt: event.attempt,
    ...((event.createdAt || event.created_at) ? { createdAt: event.createdAt || event.created_at } : {}),
  };
}

function transcriptEntryTime(entry: CliTranscriptEntry) {
  const value = Date.parse(String(entry.createdAt || ""));
  return Number.isNaN(value) ? undefined : value;
}

function sortTranscriptEntries(entries: CliTranscriptEntry[]) {
  const indexed = entries.map((entry, index) => ({
    entry,
    index,
    time: transcriptEntryTime(entry),
  }));
  if (!indexed.some((item) => typeof item.time === "number")) {
    return entries;
  }
  return indexed
    .sort((left, right) => {
      const leftOrder = left.time ?? left.entry.seq;
      const rightOrder = right.time ?? right.entry.seq;
      return leftOrder - rightOrder || left.index - right.index;
    })
    .map((item) => item.entry);
}

export function buildCliTranscriptEntries(input: {
  trace?: ChatTraceEvent[];
  endlessEvents?: ChatEndlessEvent[];
}): CliTranscriptEntry[] {
  const trace = mergeChatTraceEvents([input.trace]);
  const processEntries = (trace || []).map((event, index) => traceToEntry(event, index, index + 1));
  return sortTranscriptEntries([...processEntries, ...(input.endlessEvents || []).map(endlessEventToEntry)]);
}
