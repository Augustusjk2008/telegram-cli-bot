import { EventType, type AgUiEvent } from "../services/agUiProtocol";
import type {
  ChatMessageContextUsage,
  ChatMessageMetaInfo,
  ChatTraceEvent,
} from "../services/types";
import { isSyntheticLegacyMessageId } from "../services/agUiStreamAdapter";
import { mapChatMessageContextUsage } from "./contextUsage";
import { mergeChatTraceEvents } from "./nativeAgentTranscript";

export type AgUiActivityItem = {
  id: string;
  activityType: string;
  summary: string;
  content: Record<string, unknown>;
};

export type AgUiToolCallItem = {
  toolCallId: string;
  toolCallName: string;
  argsText: string;
  resultText: string;
  status: "running" | "completed";
};

export type AgUiPermissionRequest = {
  permissionId: string;
  summary: string;
  state: string;
  content: Record<string, unknown>;
  source: string;
  uiKind?: string;
  options?: unknown[];
  defaultValue?: unknown;
  value?: unknown;
  placeholder?: string;
  message?: string;
};

export type NativeAgentPermissionReply = {
  requestId: string;
  accepted: boolean;
  value?: unknown;
};

export type AgUiReasoningItem = {
  messageId: string;
  text: string;
};

export type NativeAgentTranscriptEntry = {
  id: string;
  seq: number;
  kind: "process" | "tool" | "event" | "permission" | "error" | "cancelled";
  label: string;
  summary: string;
  body?: string;
  collapsedByDefault: boolean;
  trace?: ChatTraceEvent;
  permissionId?: string;
  pending?: boolean;
  permission?: AgUiPermissionRequest;
};

export type AgUiRunState = {
  threadId: string;
  runId: string;
  messageId: string;
  assistantText: string;
  running: boolean;
  completed: boolean;
  activities: AgUiActivityItem[];
  toolCalls: AgUiToolCallItem[];
  permissionRequests: AgUiPermissionRequest[];
  reasoning: AgUiReasoningItem[];
  traceEvents: ChatTraceEvent[];
  entries: NativeAgentTranscriptEntry[];
  nextEntrySeq: number;
  nativeAgent: boolean;
  previewText?: string;
  clusterRunId?: string;
  elapsedSeconds?: number;
  contextUsage?: ChatMessageContextUsage;
  completionState?: string;
  error?: {
    message: string;
    code?: string;
  };
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asString(value: unknown) {
  return typeof value === "string" ? value : "";
}

function stringifyValue(value: unknown) {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "undefined" || value === null) {
    return "";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function cloneJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(cloneJsonValue);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .map(([key, entry]) => [key, cloneJsonValue(entry)]),
    );
  }
  return value;
}

function cloneRecord(value: Record<string, unknown>) {
  return asRecord(cloneJsonValue(value));
}

function decodeJsonPointerSegment(segment: string) {
  return segment.replace(/~1/g, "/").replace(/~0/g, "~");
}

function jsonPointerSegments(pathValue: unknown) {
  const path = asString(pathValue);
  if (!path.startsWith("/")) {
    return [];
  }
  const segments = path.slice(1).split("/").map(decodeJsonPointerSegment);
  return segments[0] === "content" ? segments.slice(1) : segments;
}

function isArrayIndex(segment: string) {
  return segment === "-" || /^(0|[1-9]\d*)$/.test(segment);
}

function ensureJsonPointerParent(target: Record<string, unknown>, segments: string[]) {
  let current: unknown = target;
  for (let index = 0; index < segments.length - 1; index += 1) {
    const segment = segments[index];
    const nextSegment = segments[index + 1] || "";
    const created: unknown[] | Record<string, unknown> = isArrayIndex(nextSegment) ? [] : {};
    if (Array.isArray(current)) {
      const arrayIndex = segment === "-" ? current.length : Number(segment);
      if (!Number.isInteger(arrayIndex) || arrayIndex < 0) {
        return null;
      }
      if (!current[arrayIndex] || typeof current[arrayIndex] !== "object") {
        current[arrayIndex] = created;
      }
      current = current[arrayIndex];
    } else if (current && typeof current === "object") {
      const record = current as Record<string, unknown>;
      if (!record[segment] || typeof record[segment] !== "object") {
        record[segment] = created;
      }
      current = record[segment];
    } else {
      return null;
    }
  }
  return current && typeof current === "object" ? current : null;
}

function setJsonPointerValue(
  target: Record<string, unknown>,
  segments: string[],
  value: unknown,
  operation: "add" | "replace",
) {
  const parent = ensureJsonPointerParent(target, segments);
  const key = segments[segments.length - 1];
  const nextValue = cloneJsonValue(value);
  if (Array.isArray(parent)) {
    if (key === "-") {
      parent.push(nextValue);
      return;
    }
    const index = Number(key);
    if (!Number.isInteger(index) || index < 0) {
      return;
    }
    if (operation === "add") {
      parent.splice(Math.min(index, parent.length), 0, nextValue);
    } else if (index < parent.length) {
      parent[index] = nextValue;
    }
    return;
  }
  if (parent && typeof parent === "object") {
    (parent as Record<string, unknown>)[key] = nextValue;
  }
}

function removeJsonPointerValue(target: Record<string, unknown>, segments: string[]) {
  const parent = ensureJsonPointerParent(target, segments);
  const key = segments[segments.length - 1];
  if (Array.isArray(parent)) {
    const index = Number(key);
    if (Number.isInteger(index) && index >= 0 && index < parent.length) {
      parent.splice(index, 1);
    }
    return;
  }
  if (parent && typeof parent === "object") {
    delete (parent as Record<string, unknown>)[key];
  }
}

function valueAtJsonPointer(target: Record<string, unknown>, segments: string[]) {
  let current: unknown = target;
  for (const segment of segments) {
    if (Array.isArray(current)) {
      const index = Number(segment);
      current = Number.isInteger(index) && index >= 0 ? current[index] : undefined;
    } else if (current && typeof current === "object") {
      current = (current as Record<string, unknown>)[segment];
    } else {
      return undefined;
    }
  }
  return current;
}

export function applyAgUiActivityPatch(baseContent: Record<string, unknown>, patch: unknown) {
  let nextContent = cloneRecord(baseContent);
  if (!Array.isArray(patch)) {
    return nextContent;
  }
  for (const item of patch) {
    const operation = asRecord(item);
    const op = asString(operation.op).trim().toLowerCase();
    const segments = jsonPointerSegments(operation.path);
    if (!op) {
      continue;
    }
    if (segments.length === 0) {
      if (op === "remove") {
        nextContent = {};
      } else if (op === "add" || op === "replace") {
        nextContent = cloneRecord(asRecord(operation.value));
      }
      continue;
    }
    if (op === "remove") {
      removeJsonPointerValue(nextContent, segments);
    } else if (op === "add" || op === "replace") {
      setJsonPointerValue(nextContent, segments, operation.value, op);
    } else if (op === "copy" || op === "move") {
      const sourceSegments = jsonPointerSegments(operation.from);
      const sourceValue = valueAtJsonPointer(nextContent, sourceSegments);
      if (typeof sourceValue !== "undefined") {
        setJsonPointerValue(nextContent, segments, sourceValue, "replace");
        if (op === "move") {
          removeJsonPointerValue(nextContent, sourceSegments);
        }
      }
    }
  }
  return nextContent;
}

export function findAgUiActivityForDelta(
  activities: AgUiActivityItem[],
  activityType: string,
  messageId: string,
) {
  const typedActivities = activities.filter((item) => item.activityType === activityType);
  return typedActivities.find((item) => (
    item.id === messageId
    || asString(item.content.id).trim() === messageId
    || asString(item.content.messageId || item.content.message_id).trim() === messageId
  )) || (typedActivities.length === 1 ? typedActivities[0] : undefined);
}

function interruptReason(value: unknown) {
  const record = asRecord(value);
  const interrupts = Array.isArray(record.interrupts) ? record.interrupts : [];
  for (const item of interrupts) {
    const reason = asString(asRecord(item).reason).trim();
    if (reason) {
      return reason;
    }
  }
  return "";
}

function completionStateFromRunFinished(event: { outcome?: unknown }, result: Record<string, unknown>) {
  const explicit = asString(result.completion_state || result.completionState).trim();
  if (explicit) {
    return explicit;
  }
  const outcome = asRecord(event.outcome);
  if (asString(outcome.type).trim().toLowerCase() === "interrupt") {
    const reason = interruptReason(outcome).trim().toLowerCase();
    if (reason.includes("cancel")) {
      return "cancelled";
    }
    if (reason.includes("error") || reason.includes("fail")) {
      return "error";
    }
    return reason || "interrupted";
  }
  return "completed";
}

function traceEventKey(event: ChatTraceEvent) {
  return [
    event.kind || "",
    event.rawType || "",
    event.callId || "",
    event.summary || "",
  ].join("|");
}

export type AgUiRunAccumulatorDiagnostics = {
  indexBuilds: number;
  indexedEntries: number;
  lookupProbes: number;
  fullScanItems: number;
  materializedArraySlots: number;
  disposed: boolean;
};

function traceIdentifier(value: unknown) {
  if (typeof value === "string" || typeof value === "number" || typeof value === "bigint") {
    return String(value).trim();
  }
  return "";
}

function liveTraceStableKey(trace: ChatTraceEvent) {
  const id = traceIdentifier(trace.id);
  if (id) return `id:${id}`;
  if (typeof trace.ordinal === "number") return `ordinal:${trace.ordinal}`;
  if (typeof trace.sequence === "number") return `sequence:${trace.sequence}`;
  return "";
}

function liveTraceCallKey(trace: ChatTraceEvent) {
  const callId = asString(trace.callId).trim();
  return callId ? `${trace.kind}:${callId}` : "";
}

function liveTraceAnonymousBaseKey(trace: ChatTraceEvent) {
  const kind = asString(trace.kind).trim();
  if (!kind) return "";
  const rawSource = asString(trace.source).trim().toLowerCase();
  const source = rawSource === "native_agent" ? "native" : rawSource;
  return [
    kind,
    source,
    asString(trace.callId).trim(),
    asString(trace.title).trim(),
    asString(trace.toolName).trim(),
  ].join("\u001f");
}

function liveTraceAnonymousKey(trace: ChatTraceEvent) {
  const base = liveTraceAnonymousBaseKey(trace);
  const rawType = asString(trace.rawType).trim();
  const summary = asString(trace.summary).trim().replace(/\s+/g, " ");
  return base && summary ? `${base}\u001f${rawType}\u001f${summary}` : "";
}

function liveTraceFallbackKey(trace: ChatTraceEvent) {
  const source = asString(trace.source).trim().toLowerCase();
  const rawType = asString(trace.rawType).trim();
  if (source === "native_agent" || source === "native" || rawType === "message.text.reclassified") {
    return "";
  }
  const callId = asString(trace.callId).trim();
  const summary = asString(trace.summary).trim();
  if (!rawType && !callId && !summary) return "";
  return `${trace.kind}:${rawType}:${callId}:${summary}`;
}

function hasLiveTraceOrder(trace: ChatTraceEvent) {
  return typeof trace.ordinal === "number" || typeof trace.sequence === "number";
}

function liveTraceOrderValue(trace: ChatTraceEvent) {
  if (typeof trace.ordinal === "number") return trace.ordinal;
  if (typeof trace.sequence === "number") return trace.sequence;
  return Number.POSITIVE_INFINITY;
}

type LiveTraceToken = {
  entryIndex?: number;
};

type LiveAgUiProjection = {
  trace: ChatTraceEvent[];
  toolCallCount: number;
  processCount: number;
  entryIndexes: Map<number, number>;
};

const liveProjectionByState = new WeakMap<AgUiRunState, LiveAgUiProjection>();
const LIVE_ANONYMOUS_CANDIDATE_LIMIT = 8;

class LiveTraceIndex {
  events: ChatTraceEvent[];
  private readonly tokens: LiveTraceToken[];
  private readonly stableIndexes = new Map<string, number>();
  private readonly callIndexes = new Map<string, number>();
  private readonly fallbackIndexes = new Map<string, number>();
  private readonly anonymousIndexes = new Map<string, number>();
  private readonly anonymousBaseIndexes = new Map<string, number[]>();
  private readonly orderedIndexes: number[] = [];
  private readonly implicitIndexes: number[] = [];
  private orderedIndexesSorted = true;
  private orderingDirty = false;

  constructor(
    initial: ChatTraceEvent[],
    private readonly work: AgUiRunAccumulatorDiagnostics,
  ) {
    this.events = [...initial];
    this.tokens = this.events.map(() => ({}));
    this.work.fullScanItems += initial.length;
    this.rebuildIndexes();
  }

  private rememberAnonymousIndex(event: ChatTraceEvent, index: number) {
    if (liveTraceStableKey(event)) return;
    const exactKey = liveTraceAnonymousKey(event);
    if (exactKey) this.anonymousIndexes.set(exactKey, index);
    const baseKey = liveTraceAnonymousBaseKey(event);
    if (baseKey) {
      const indexes = (this.anonymousBaseIndexes.get(baseKey) || [])
        .filter((item) => item !== index);
      indexes.push(index);
      indexes.sort((left, right) => left - right);
      if (indexes.length > LIVE_ANONYMOUS_CANDIDATE_LIMIT) {
        indexes.splice(0, indexes.length - LIVE_ANONYMOUS_CANDIDATE_LIMIT);
      }
      this.anonymousBaseIndexes.set(baseKey, indexes);
    }
  }

  private rememberIndex(event: ChatTraceEvent, index: number) {
    const stableKey = liveTraceStableKey(event);
    const callKey = liveTraceCallKey(event);
    const fallbackKey = liveTraceFallbackKey(event);
    if (stableKey) this.stableIndexes.set(stableKey, index);
    if (callKey) this.callIndexes.set(callKey, index);
    if (fallbackKey) this.fallbackIndexes.set(fallbackKey, index);
    this.rememberAnonymousIndex(event, index);
  }

  private forgetIndex(event: ChatTraceEvent, index: number) {
    const stableKey = liveTraceStableKey(event);
    const callKey = liveTraceCallKey(event);
    const fallbackKey = liveTraceFallbackKey(event);
    if (stableKey && this.stableIndexes.get(stableKey) === index) this.stableIndexes.delete(stableKey);
    if (callKey && this.callIndexes.get(callKey) === index) this.callIndexes.delete(callKey);
    if (fallbackKey && this.fallbackIndexes.get(fallbackKey) === index) this.fallbackIndexes.delete(fallbackKey);
    if (!stableKey) {
      const exactKey = liveTraceAnonymousKey(event);
      if (exactKey && this.anonymousIndexes.get(exactKey) === index) {
        this.anonymousIndexes.delete(exactKey);
      }
      const baseKey = liveTraceAnonymousBaseKey(event);
      const indexes = baseKey ? this.anonymousBaseIndexes.get(baseKey) : undefined;
      if (baseKey && indexes) {
        const nextIndexes = indexes.filter((item) => item !== index);
        if (nextIndexes.length > 0) this.anonymousBaseIndexes.set(baseKey, nextIndexes);
        else this.anonymousBaseIndexes.delete(baseKey);
      }
    }
  }

  private rebuildIndexes() {
    this.stableIndexes.clear();
    this.callIndexes.clear();
    this.fallbackIndexes.clear();
    this.anonymousIndexes.clear();
    this.anonymousBaseIndexes.clear();
    this.events.forEach((event, index) => this.rememberIndex(event, index));
    this.rebuildOrderIndexes();
  }

  private rebuildOrderIndexes() {
    this.orderedIndexes.length = 0;
    this.implicitIndexes.length = 0;
    this.orderedIndexesSorted = true;
    let lastOrder = Number.NEGATIVE_INFINITY;
    this.events.forEach((event, index) => {
      if (!hasLiveTraceOrder(event)) {
        this.implicitIndexes.push(index);
        return;
      }
      const order = liveTraceOrderValue(event);
      if (order < lastOrder) this.orderedIndexesSorted = false;
      lastOrder = order;
      this.orderedIndexes.push(index);
    });
    this.orderingDirty = false;
  }

  private insert(event: ChatTraceEvent, token: LiveTraceToken) {
    const index = this.events.length;
    this.events.push(event);
    this.tokens.push(token);
    this.rememberIndex(event, index);
    if (!hasLiveTraceOrder(event)) {
      this.implicitIndexes.push(index);
      return;
    }
    const previousIndex = this.orderedIndexes[this.orderedIndexes.length - 1];
    if (
      typeof previousIndex === "number"
      && liveTraceOrderValue(event) < liveTraceOrderValue(this.events[previousIndex])
    ) {
      this.orderedIndexesSorted = false;
    }
    this.orderedIndexes.push(index);
  }

  private pairMerge(current: ChatTraceEvent, incoming: ChatTraceEvent) {
    return mergeChatTraceEvents([[current], [incoming]], {
      nativeFlat: true,
      dedupeAnonymous: true,
    }) || [];
  }

  private findIndex(event: ChatTraceEvent) {
    const callKey = liveTraceCallKey(event);
    const stableKey = liveTraceStableKey(event);
    const fallbackKey = liveTraceFallbackKey(event);
    this.work.lookupProbes += 2;
    let index = (
      (callKey ? this.callIndexes.get(callKey) : undefined)
      ?? (stableKey ? this.stableIndexes.get(stableKey) : undefined)
      ?? (fallbackKey ? this.fallbackIndexes.get(fallbackKey) : undefined)
    );
    if (typeof index === "number" || stableKey) return index;

    const exactKey = liveTraceAnonymousKey(event);
    const exactIndex = exactKey ? this.anonymousIndexes.get(exactKey) : undefined;
    this.work.lookupProbes += 1;
    if (typeof exactIndex === "number") return exactIndex;

    const baseKey = liveTraceAnonymousBaseKey(event);
    const baseIndexes = baseKey ? this.anonymousBaseIndexes.get(baseKey) || [] : [];
    for (let cursor = baseIndexes.length - 1; cursor >= 0; cursor -= 1) {
      this.work.lookupProbes += 1;
      const candidateIndex = baseIndexes[cursor];
      if (this.pairMerge(this.events[candidateIndex], event).length === 1) {
        index = candidateIndex;
        break;
      }
    }
    return index;
  }

  upsert(event: ChatTraceEvent) {
    const existingIndex = this.findIndex(event);
    if (typeof existingIndex === "number") {
      const previous = this.events[existingIndex];
      this.forgetIndex(previous, existingIndex);
      const merged = this.pairMerge(previous, event);
      this.events[existingIndex] = merged[0] || event;
      this.rememberIndex(this.events[existingIndex], existingIndex);
      if (
        hasLiveTraceOrder(previous) !== hasLiveTraceOrder(this.events[existingIndex])
        || liveTraceOrderValue(previous) !== liveTraceOrderValue(this.events[existingIndex])
      ) {
        this.orderingDirty = true;
      }
      return this.tokens[existingIndex];
    }
    const token = {};
    this.insert(event, token);
    return token;
  }

  append(event: ChatTraceEvent) {
    const fallbackKey = liveTraceFallbackKey(event);
    const previousFallbackIndex = fallbackKey ? this.fallbackIndexes.get(fallbackKey) : undefined;
    const token = {};
    this.insert(event, token);
    if (fallbackKey && typeof previousFallbackIndex === "number") {
      this.fallbackIndexes.set(fallbackKey, previousFallbackIndex);
    }
    return token;
  }

  tokenFor(event: ChatTraceEvent) {
    const index = this.findIndex(event);
    return typeof index === "number" ? this.tokens[index] : undefined;
  }

  materialize() {
    if (this.orderingDirty) this.rebuildOrderIndexes();
    const orderedIndexes = this.orderedIndexesSorted
      ? this.orderedIndexes
      : [...this.orderedIndexes].sort((left, right) => (
          liveTraceOrderValue(this.events[left]) - liveTraceOrderValue(this.events[right])
          || left - right
        ));
    return [
      ...orderedIndexes.map((index) => this.events[index]),
      ...this.implicitIndexes.map((index) => this.events[index]),
    ];
  }

  releaseIndexes() {
    this.events = [];
    this.tokens.length = 0;
    this.stableIndexes.clear();
    this.callIndexes.clear();
    this.fallbackIndexes.clear();
    this.anonymousIndexes.clear();
    this.anonymousBaseIndexes.clear();
    this.orderedIndexes.length = 0;
    this.implicitIndexes.length = 0;
    this.orderedIndexesSorted = true;
    this.orderingDirty = false;
  }

  indexedEntryCount() {
    return this.stableIndexes.size
      + this.callIndexes.size
      + this.fallbackIndexes.size
      + this.anonymousIndexes.size
      + this.anonymousBaseIndexes.size;
  }
}

type AgUiRunAccumulatorContext = {
  work: AgUiRunAccumulatorDiagnostics;
  traces: LiveTraceIndex;
  permissionEntryById: Map<string, number>;
  toolResultEntryByCallId: Map<string, number>;
  toolEntryByCallId: Map<string, number>;
  activityByKey: Map<string, number>;
  activityByMessageKey: Map<string, number>;
  permissionById: Map<string, number>;
  toolCallById: Map<string, number>;
  reasoningByMessageId: Map<string, number>;
  projection: LiveAgUiProjection;
};

function activityKey(activity: Pick<AgUiActivityItem, "id" | "activityType">) {
  return `${activity.activityType}\u001f${activity.id}`;
}

function activityMessageKey(activityType: string, messageId: string) {
  return `${activityType}\u001f${messageId}`;
}

function findIndexedActivityForDelta(
  activities: AgUiActivityItem[],
  activityType: string,
  messageId: string,
  context: AgUiRunAccumulatorContext,
) {
  const indexed = context.activityByMessageKey.get(activityMessageKey(activityType, messageId));
  if (typeof indexed === "number") return activities[indexed];
  const direct = context.activityByKey.get(activityKey({ id: messageId, activityType }));
  if (typeof direct === "number") return activities[direct];
  return findAgUiActivityForDelta(activities, activityType, messageId);
}

function updateLiveProjection(context: AgUiRunAccumulatorContext, index: number, entry: NativeAgentTranscriptEntry) {
  if (!entry.trace) return;
  const nextTrace = {
    ...entry.trace,
    sequence: typeof entry.trace.sequence === "number" ? entry.trace.sequence : entry.seq,
  };
  const existingIndex = context.projection.entryIndexes.get(index);
  if (typeof existingIndex === "number") {
    const previous = context.projection.trace[existingIndex];
    if (previous.kind === "tool_call") context.projection.toolCallCount -= 1;
    if (previous.kind !== "tool_call" && previous.kind !== "tool_result") context.projection.processCount -= 1;
    context.projection.trace[existingIndex] = nextTrace;
  } else {
    context.projection.entryIndexes.set(index, context.projection.trace.length);
    context.projection.trace.push(nextTrace);
  }
  if (nextTrace.kind === "tool_call") context.projection.toolCallCount += 1;
  if (nextTrace.kind !== "tool_call" && nextTrace.kind !== "tool_result") context.projection.processCount += 1;
}

function cloneRunStateForAccumulator(state: AgUiRunState): AgUiRunState {
  return {
    ...state,
    activities: [...state.activities],
    toolCalls: [...state.toolCalls],
    permissionRequests: [...state.permissionRequests],
    reasoning: [...state.reasoning],
    traceEvents: [...state.traceEvents],
    entries: [...state.entries],
  };
}

function upsertTraceEvent(
  traceEvents: ChatTraceEvent[],
  nextEvent: ChatTraceEvent,
  match?: (event: ChatTraceEvent) => boolean,
  context?: AgUiRunAccumulatorContext,
) {
  if (context) {
    context.traces.upsert(nextEvent);
    return context.traces.events;
  }
  if (!match) {
    const merged = mergeChatTraceEvents([traceEvents, [nextEvent]], {
      nativeFlat: true,
      dedupeAnonymous: true,
    });
    return merged || [];
  }
  const index = match
    ? traceEvents.findIndex(match)
    : traceEvents.findIndex((item) => traceEventKey(item) === traceEventKey(nextEvent));
  if (index < 0) {
    return [...traceEvents, nextEvent];
  }
  const nextTrace = traceEvents.slice();
  nextTrace[index] = {
    ...traceEvents[index],
    ...nextEvent,
  };
  return nextTrace;
}

function summarizeActivity(activityType: string, content: Record<string, unknown>) {
  const summary = asString(content.summary).trim();
  if (summary) {
    return summary;
  }
  if (activityType === "TCB_STATUS") {
    return (
      asString(content.previewText).trim()
      || asString(content.message).trim()
      || asString(content.phase).trim()
      || asString(content.lifecycle).trim()
    );
  }
  if (activityType === "TCB_PERMISSION_REQUEST") {
    return (
      asString(content.message).trim()
      || asString(content.prompt).trim()
      || asString(content.reason).trim()
      || "等待权限确认"
    );
  }
  return (
    asString(content.message).trim()
    || asString(content.title).trim()
    || (activityType === "TCB_NATIVE_AGENT_TRACE" ? "" : stringifyValue(content).trim())
  );
}

function resolveActivityTraceKind(activityType: string, content: Record<string, unknown>): ChatTraceEvent["kind"] | "" {
  if (activityType === "TCB_META") {
    return "";
  }
  if (activityType === "TCB_PERMISSION_REQUEST") {
    const uiKind = permissionUiKind(content);
    return isNonInteractiveUiKind(uiKind) ? (asString(content.rawKind).trim() || "status") : "permission";
  }
  if (activityType === "TCB_STATUS") {
    return "status";
  }
  const rawKind = asString(content.rawKind).trim();
  return rawKind || "event";
}

function getPermissionId(content: Record<string, unknown>) {
  return asString(content.permissionId || content.id || content.permissionID || content.permission_id).trim();
}

function permissionUiKind(content: Record<string, unknown>) {
  return asString(content.uiKind || content.ui_kind).trim();
}

function isNonInteractiveUiKind(uiKind: string) {
  return ["notify", "setstatus", "setwidget"].includes(uiKind.trim().toLowerCase());
}

function isPermissionPending(content: Record<string, unknown>) {
  const state = asString(content.state || content.status).trim().toLowerCase();
  return !state || (
    !state.includes("replied")
    && !state.includes("approved")
    && !state.includes("reject")
    && !state.includes("denied")
    && !state.includes("allow")
  );
}

function buildPermissionRequest(permissionId: string, summary: string, content: Record<string, unknown>): AgUiPermissionRequest {
  const uiKind = permissionUiKind(content) || "confirm";
  const options = Array.isArray(content.options) ? content.options : undefined;
  const message = asString(content.message || content.title || content.summary).trim();
  return {
    permissionId,
    summary,
    state: asString(content.state || content.status).trim(),
    content,
    source: asString(content.source).trim(),
    uiKind,
    ...(options ? { options } : {}),
    ...(typeof content.defaultValue !== "undefined" ? { defaultValue: content.defaultValue } : {}),
    ...(typeof content.value !== "undefined" ? { value: content.value } : {}),
    ...(asString(content.placeholder).trim() ? { placeholder: asString(content.placeholder).trim() } : {}),
    ...(message ? { message } : {}),
  };
}

function nativeEntryKindForTrace(event: ChatTraceEvent): NativeAgentTranscriptEntry["kind"] {
  if (event.kind === "commentary" || event.kind === "reasoning" || event.kind === "status") {
    return "process";
  }
  if (event.kind === "tool_call") {
    return "tool";
  }
  if (event.kind === "permission") {
    return "permission";
  }
  if (event.kind === "error") {
    return "error";
  }
  if (event.kind === "cancelled") {
    return "cancelled";
  }
  return "event";
}

function nativeEntryLabel(kind: NativeAgentTranscriptEntry["kind"], trace?: ChatTraceEvent) {
  if (kind === "process") return "过程";
  if (kind === "tool") return trace?.toolName || trace?.title || "工具";
  if (kind === "permission") return "权限";
  if (kind === "error") return "错误";
  if (kind === "cancelled") return "已取消";
  return trace?.kind === "tool_result" ? "工具结果" : "事件";
}

function appendNativeEntry(
  state: AgUiRunState,
  entry: Omit<NativeAgentTranscriptEntry, "id" | "seq"> & { id?: string },
  context?: AgUiRunAccumulatorContext,
  traceToken?: LiveTraceToken,
): AgUiRunState {
  const seq = state.nextEntrySeq;
  const nextEntry: NativeAgentTranscriptEntry = {
    ...entry,
    id: entry.id || `native-entry-${seq}`,
    seq,
  };
  if (context) {
    state.entries.push(nextEntry);
    const index = state.entries.length - 1;
    if (nextEntry.kind === "permission" && nextEntry.permissionId) {
      context.permissionEntryById.set(nextEntry.permissionId, index);
    }
    if (nextEntry.trace?.kind === "tool_result" && nextEntry.trace.callId) {
      context.toolResultEntryByCallId.set(nextEntry.trace.callId, index);
    }
    if (nextEntry.kind === "tool" && nextEntry.trace?.callId) {
      context.toolEntryByCallId.set(nextEntry.trace.callId, index);
    }
    if (nextEntry.trace) {
      const token = traceToken || context.traces.tokenFor(nextEntry.trace);
      if (token) token.entryIndex = index;
    }
    updateLiveProjection(context, index, nextEntry);
    return {
      ...state,
      entries: state.entries,
      nextEntrySeq: seq + 1,
    };
  }
  return {
    ...state,
    entries: [...state.entries, nextEntry],
    nextEntrySeq: seq + 1,
  };
}

function appendTraceEntry(
  state: AgUiRunState,
  trace: ChatTraceEvent,
  options: Partial<Omit<NativeAgentTranscriptEntry, "id" | "seq" | "trace">> = {},
  context?: AgUiRunAccumulatorContext,
): AgUiRunState {
  const kind = options.kind || nativeEntryKindForTrace(trace);
  const summary = options.summary ?? trace.summary ?? "";
  const entry = {
    kind,
    label: options.label || nativeEntryLabel(kind, trace),
    summary,
    body: options.body,
    collapsedByDefault: options.collapsedByDefault ?? !["process", "permission", "error", "cancelled"].includes(kind),
    trace,
    permissionId: options.permissionId,
    pending: options.pending,
    permission: options.permission,
  };
  const traceToken = context?.traces.tokenFor(trace);
  const matchingEntryIndex = kind === "permission" && options.permissionId
    ? -1
    : context && traceToken
      ? traceToken.entryIndex ?? -1
      : state.entries.findIndex((item) => {
      if (!item.trace) {
        return false;
      }
      const merged = mergeChatTraceEvents([[item.trace], [trace]], {
        nativeFlat: true,
        dedupeAnonymous: true,
      });
      return merged?.length === 1;
    });
  if (matchingEntryIndex >= 0) {
    if (context) {
      state.entries[matchingEntryIndex] = {
        ...state.entries[matchingEntryIndex],
        ...entry,
        id: state.entries[matchingEntryIndex].id,
        seq: state.entries[matchingEntryIndex].seq,
      };
      updateLiveProjection(context, matchingEntryIndex, state.entries[matchingEntryIndex]);
      return { ...state, entries: state.entries };
    }
    return {
      ...state,
      entries: state.entries.map((item, index) => (
        index === matchingEntryIndex
          ? { ...item, ...entry, id: item.id, seq: item.seq }
          : item
      )),
    };
  }
  if (kind === "permission" && options.permissionId) {
    const entryIndex = context
      ? context.permissionEntryById.get(options.permissionId) ?? -1
      : state.entries.findIndex((item) => item.kind === "permission" && item.permissionId === options.permissionId);
    if (entryIndex >= 0) {
      if (context) {
        state.entries[entryIndex] = {
          ...state.entries[entryIndex],
          ...entry,
          id: state.entries[entryIndex].id,
          seq: state.entries[entryIndex].seq,
        };
        updateLiveProjection(context, entryIndex, state.entries[entryIndex]);
        return { ...state, entries: state.entries };
      }
      return {
        ...state,
        entries: state.entries.map((item, index) => (
          index === entryIndex
            ? { ...item, ...entry, id: item.id, seq: item.seq }
            : item
        )),
      };
    }
  }
  if (trace.kind === "tool_result" && trace.callId) {
    const entryIndex = context
      ? context.toolResultEntryByCallId.get(trace.callId) ?? -1
      : state.entries.findIndex((item) => item.trace?.kind === "tool_result" && item.trace.callId === trace.callId);
    if (entryIndex >= 0) {
      if (context) {
        state.entries[entryIndex] = {
          ...state.entries[entryIndex],
          ...entry,
          id: state.entries[entryIndex].id,
          seq: state.entries[entryIndex].seq,
        };
        updateLiveProjection(context, entryIndex, state.entries[entryIndex]);
        return { ...state, entries: state.entries };
      }
      return {
        ...state,
        entries: state.entries.map((item, index) => (
          index === entryIndex
            ? { ...item, ...entry, id: item.id, seq: item.seq }
            : item
        )),
      };
    }
  }
  return appendNativeEntry(state, entry, context, traceToken);
}

function updateNativeToolEntryBody(
  state: AgUiRunState,
  toolCallId: string,
  body: string,
  context?: AgUiRunAccumulatorContext,
): AgUiRunState {
  if (context) {
    const index = context.toolEntryByCallId.get(toolCallId);
    if (typeof index !== "number") return state;
    const entry = state.entries[index];
    state.entries[index] = {
      ...entry,
      body,
      trace: entry.trace
        ? {
            ...entry.trace,
            summary: body || entry.trace.summary,
            payload: {
              ...asRecord(entry.trace.payload),
              arguments: body,
            },
          }
        : entry.trace,
    };
    updateLiveProjection(context, index, state.entries[index]);
    return { ...state, entries: state.entries };
  }
  return {
    ...state,
    entries: state.entries.map((entry) => (
      entry.kind === "tool" && entry.trace?.callId === toolCallId
        ? {
            ...entry,
            body,
            trace: entry.trace
              ? {
                  ...entry.trace,
                  summary: body || entry.trace.summary,
                  payload: {
                    ...asRecord(entry.trace.payload),
                    arguments: body,
                  },
                }
              : entry.trace,
          }
        : entry
    )),
  };
}

export function createAgUiRunState(): AgUiRunState {
  return {
    threadId: "",
    runId: "",
    messageId: "",
    assistantText: "",
    running: false,
    completed: false,
    activities: [],
    toolCalls: [],
    permissionRequests: [],
    reasoning: [],
    traceEvents: [],
    entries: [],
    nextEntrySeq: 1,
    nativeAgent: false,
  };
}

export function createAgUiRunAccumulator(initialState?: AgUiRunState) {
  const work: AgUiRunAccumulatorDiagnostics = {
    indexBuilds: 0,
    indexedEntries: 0,
    lookupProbes: 0,
    fullScanItems: 0,
    materializedArraySlots: 0,
    disposed: false,
  };
  let state = cloneRunStateForAccumulator(initialState || createAgUiRunState());
  const traces = new LiveTraceIndex(state.traceEvents, work);
  const context: AgUiRunAccumulatorContext = {
    work,
    traces,
    permissionEntryById: new Map(),
    toolResultEntryByCallId: new Map(),
    toolEntryByCallId: new Map(),
    activityByKey: new Map(),
    activityByMessageKey: new Map(),
    permissionById: new Map(),
    toolCallById: new Map(),
    reasoningByMessageId: new Map(),
    projection: {
      trace: [],
      toolCallCount: 0,
      processCount: 0,
      entryIndexes: new Map(),
    },
  };
  work.indexBuilds = 1;
  state.traceEvents = traces.events;
  state.activities.forEach((item, index) => context.activityByKey.set(activityKey(item), index));
  state.permissionRequests.forEach((item, index) => context.permissionById.set(item.permissionId, index));
  state.toolCalls.forEach((item, index) => context.toolCallById.set(item.toolCallId, index));
  state.reasoning.forEach((item, index) => context.reasoningByMessageId.set(item.messageId, index));
  state.entries.forEach((entry, index) => {
    const token = entry.trace ? traces.tokenFor(entry.trace) : undefined;
    if (token) token.entryIndex = index;
    if (entry.permissionId) context.permissionEntryById.set(entry.permissionId, index);
    if (entry.trace?.kind === "tool_result" && entry.trace.callId) context.toolResultEntryByCallId.set(entry.trace.callId, index);
    if (entry.kind === "tool" && entry.trace?.callId) context.toolEntryByCallId.set(entry.trace.callId, index);
    updateLiveProjection(context, index, entry);
  });
  liveProjectionByState.set(state, context.projection);

  const reduce = (events: readonly AgUiEvent[] | AgUiEvent) => {
    if (work.disposed) return state;
    const input = Array.isArray(events) ? events : [events];
    for (const event of input) {
      state = reduceAgUiRunEventInternal(state, event, context);
    }
    state.traceEvents = traces.events;
    liveProjectionByState.set(state, context.projection);
    work.indexedEntries = traces.indexedEntryCount();
    return state;
  };

  return {
    reduce,
    snapshot: () => {
      const traceEvents = traces.materialize();
      work.materializedArraySlots += (
        state.activities.length
        + state.toolCalls.length
        + state.permissionRequests.length
        + state.reasoning.length
        + traceEvents.length
        + state.entries.length
      );
      const snapshot = {
        ...state,
        activities: [...state.activities],
        toolCalls: [...state.toolCalls],
        permissionRequests: [...state.permissionRequests],
        reasoning: [...state.reasoning],
        traceEvents,
        entries: [...state.entries],
      };
      liveProjectionByState.set(snapshot, {
        trace: [...context.projection.trace],
        toolCallCount: context.projection.toolCallCount,
        processCount: context.projection.processCount,
        entryIndexes: new Map(context.projection.entryIndexes),
      });
      return snapshot;
    },
    diagnostics: () => ({ ...work, indexedEntries: traces.indexedEntryCount() }),
    dispose: () => {
      if (work.disposed) return;
      traces.releaseIndexes();
      context.permissionEntryById.clear();
      context.toolResultEntryByCallId.clear();
      context.toolEntryByCallId.clear();
      context.activityByKey.clear();
      context.activityByMessageKey.clear();
      context.permissionById.clear();
      context.toolCallById.clear();
      context.reasoningByMessageId.clear();
      state = createAgUiRunState();
      context.projection = {
        trace: [],
        toolCallCount: 0,
        processCount: 0,
        entryIndexes: new Map(),
      };
      work.disposed = true;
      work.indexedEntries = 0;
    },
  };
}

export function reduceAgUiRunEvent(state: AgUiRunState, event: AgUiEvent): AgUiRunState {
  return reduceAgUiRunEventInternal(state, event);
}

function reduceAgUiRunEventInternal(
  state: AgUiRunState,
  event: AgUiEvent,
  context?: AgUiRunAccumulatorContext,
): AgUiRunState {
  if (event.type === EventType.RUN_STARTED) {
    const nextState: AgUiRunState = {
      ...state,
      threadId: event.threadId,
      runId: event.runId,
      running: true,
      completed: false,
      error: undefined,
    };
    return nextState;
  }

  if (event.type === EventType.TEXT_MESSAGE_START) {
    return {
      ...state,
      messageId: event.messageId,
      running: true,
    };
  }

  if (event.type === EventType.TEXT_MESSAGE_CONTENT) {
    return {
      ...state,
      messageId: event.messageId,
      assistantText: state.assistantText + event.delta,
      running: true,
    };
  }

  if (event.type === EventType.TEXT_MESSAGE_END) {
    return {
      ...state,
      messageId: event.messageId,
    };
  }

  if (event.type === EventType.MESSAGES_SNAPSHOT) {
    const assistantMessage = [...event.messages].reverse().find((message) => message.role === "assistant");
    const messageId = asString(assistantMessage?.id).trim() || state.messageId;
    const content = asString(assistantMessage?.content);
    return {
      ...state,
      messageId,
      ...(assistantMessage ? { assistantText: content } : {}),
      running: true,
    };
  }

  if (event.type === EventType.ACTIVITY_SNAPSHOT || event.type === EventType.ACTIVITY_DELTA) {
    const previousActivity = event.type === EventType.ACTIVITY_DELTA
      ? context
        ? findIndexedActivityForDelta(state.activities, event.activityType, event.messageId, context)
        : findAgUiActivityForDelta(state.activities, event.activityType, event.messageId)
      : undefined;
    const content = event.type === EventType.ACTIVITY_SNAPSHOT
      ? asRecord(event.content)
      : applyAgUiActivityPatch(
          previousActivity?.content || {},
          event.patch,
        );
    const summary = summarizeActivity(event.activityType, content);
    const activityId = event.activityType === "TCB_PERMISSION_REQUEST"
      ? getPermissionId(content) || event.activityType
      : asString(content.id).trim() || event.messageId || event.activityType;
    const nextActivity: AgUiActivityItem = {
      id: activityId,
      activityType: event.activityType,
      summary,
      content,
    };
    const nextActivityKey = activityKey(nextActivity);
    const activityIndex = context
      ? context.activityByKey.get(nextActivityKey)
        ?? -1
      : state.activities.findIndex((item) => item.id === nextActivity.id && item.activityType === nextActivity.activityType);
    const activities = context
      ? (() => {
          if (activityIndex < 0) {
            state.activities.push(nextActivity);
            context.activityByKey.set(nextActivityKey, state.activities.length - 1);
          } else {
            state.activities[activityIndex] = nextActivity;
          }
          const resolvedIndex = activityIndex < 0 ? state.activities.length - 1 : activityIndex;
          context.activityByKey.set(nextActivityKey, resolvedIndex);
          if (event.messageId) {
            const messageKey = activityMessageKey(event.activityType, event.messageId);
            if (!context.activityByMessageKey.has(messageKey)) {
              context.activityByMessageKey.set(messageKey, resolvedIndex);
            }
          }
          for (const alias of [
            asString(content.id).trim(),
            asString(content.messageId).trim(),
            asString(content.message_id).trim(),
          ]) {
            if (alias) {
              const aliasKey = activityMessageKey(event.activityType, alias);
              if (!context.activityByMessageKey.has(aliasKey)) {
                context.activityByMessageKey.set(aliasKey, resolvedIndex);
              }
              context.activityByKey.set(activityKey({ id: alias, activityType: event.activityType }), resolvedIndex);
            }
          }
          return state.activities;
        })()
      : activityIndex < 0
        ? [...state.activities, nextActivity]
        : state.activities.map((item, index) => index === activityIndex ? nextActivity : item);

    const permissionId = getPermissionId(content);
    const permissionActivity = event.activityType === "TCB_PERMISSION_REQUEST"
      && Boolean(permissionId)
      && !isNonInteractiveUiKind(permissionUiKind(content));
    const nextPermissionRequest = permissionActivity
      ? buildPermissionRequest(permissionId, summary, content)
      : undefined;
    const traceKind = resolveActivityTraceKind(event.activityType, content);
    const activityMessageId = asString(event.messageId).trim();
    const activityTraceId = asString(content.id).trim()
      || (isSyntheticLegacyMessageId(activityMessageId) ? "" : activityMessageId);
    const activityTraceEvent: ChatTraceEvent | null = traceKind
      ? {
          ...(activityTraceId ? { id: activityTraceId } : {}),
          ...(typeof content.ordinal === "number" ? { ordinal: content.ordinal } : {}),
          ...(typeof content.sequence === "number" ? { sequence: content.sequence } : {}),
          ...(asString(content.createdAt || content.created_at).trim()
            ? { createdAt: asString(content.createdAt || content.created_at).trim() }
            : {}),
          kind: traceKind,
          summary,
          source: asString(content.source).trim(),
          rawType: asString(content.rawType).trim() || event.activityType,
          title: asString(content.title).trim() || undefined,
          toolName: asString(content.toolName || content.tool_name).trim() || undefined,
          callId: asString(content.callId || content.call_id).trim() || undefined,
          payload: content,
        }
      : null;
    const traceEvents = activityTraceEvent
      ? upsertTraceEvent(state.traceEvents, activityTraceEvent, undefined, context)
      : state.traceEvents;

    const permissionRequests = nextPermissionRequest
      ? (() => {
          const permissionIndex = context
            ? context.permissionById.get(nextPermissionRequest.permissionId) ?? -1
            : state.permissionRequests.findIndex((item) => item.permissionId === nextPermissionRequest.permissionId);
          if (context) {
            if (permissionIndex < 0) {
              state.permissionRequests.push(nextPermissionRequest);
              context.permissionById.set(nextPermissionRequest.permissionId, state.permissionRequests.length - 1);
            } else {
              state.permissionRequests[permissionIndex] = nextPermissionRequest;
            }
            return state.permissionRequests;
          }
          return permissionIndex < 0
            ? [...state.permissionRequests, nextPermissionRequest]
            : state.permissionRequests.map((item, index) => index === permissionIndex ? nextPermissionRequest : item);
        })()
      : state.permissionRequests;

    const nextState: AgUiRunState = {
      ...state,
      messageId: event.messageId,
      activities,
      permissionRequests,
      traceEvents,
      nativeAgent: state.nativeAgent
        || event.activityType === "TCB_NATIVE_AGENT_TRACE"
        || ["native", "native_agent"].includes(asString(content.source).trim().toLowerCase()),
      ...(event.activityType === "TCB_STATUS"
        ? {
            previewText: asString(content.previewText).trim() || asString(content.message).trim() || state.previewText,
            elapsedSeconds: typeof content.elapsedSeconds === "number" ? content.elapsedSeconds : state.elapsedSeconds,
            contextUsage: mapChatMessageContextUsage(content.contextUsage ?? content.context_usage) || state.contextUsage,
          }
        : {}),
      ...(event.activityType === "TCB_META"
        ? {
            clusterRunId: asString(content.clusterRunId).trim() || state.clusterRunId,
          }
        : {}),
    };
    if (!activityTraceEvent?.summary.trim()) {
      return nextState;
    }
    return appendTraceEntry(nextState, activityTraceEvent, {
      ...(activityTraceEvent.kind === "permission"
        ? {
            permissionId,
            pending: isPermissionPending(content),
            permission: nextPermissionRequest,
            collapsedByDefault: false,
          }
        : {}),
    }, context);
  }

  if (event.type === EventType.TOOL_CALL_START) {
    const nextToolCall: AgUiToolCallItem = {
      toolCallId: event.toolCallId,
      toolCallName: event.toolCallName,
      argsText: "",
      resultText: "",
      status: "running",
    };
    const traceEvent: ChatTraceEvent = {
      kind: "tool_call",
      summary: "",
      title: event.toolCallName,
      toolName: event.toolCallName,
      callId: event.toolCallId,
      payload: {
        arguments: "",
      },
    };
    const toolCallIndex = context ? context.toolCallById.get(event.toolCallId) ?? -1 : -1;
    const toolCalls = context
      ? (() => {
          if (toolCallIndex < 0) {
            state.toolCalls.push(nextToolCall);
            context.toolCallById.set(event.toolCallId, state.toolCalls.length - 1);
          } else {
            state.toolCalls[toolCallIndex] = nextToolCall;
          }
          return state.toolCalls;
        })()
      : [...state.toolCalls.filter((item) => item.toolCallId !== event.toolCallId), nextToolCall];
    const nextState: AgUiRunState = {
      ...state,
      toolCalls,
      traceEvents: upsertTraceEvent(
        state.traceEvents,
        traceEvent,
        (item) => item.kind === "tool_call" && item.callId === event.toolCallId,
        context,
      ),
    };
    return appendTraceEntry(nextState, traceEvent, {
      kind: "tool",
      label: event.toolCallName || "工具",
      summary: event.toolCallName || "工具调用",
      body: "",
      collapsedByDefault: true,
    }, context);
  }

  if (event.type === EventType.TOOL_CALL_ARGS) {
    const currentToolCallIndex = context ? context.toolCallById.get(event.toolCallId) ?? -1 : -1;
    const currentToolCall = context
      ? state.toolCalls[currentToolCallIndex]
      : state.toolCalls.find((item) => item.toolCallId === event.toolCallId);
    const nextArgsText = `${currentToolCall?.argsText || ""}${event.delta}`;
    const toolCalls = context
      ? (() => {
          if (currentToolCallIndex >= 0) {
            state.toolCalls[currentToolCallIndex] = {
              ...state.toolCalls[currentToolCallIndex],
              argsText: nextArgsText,
            };
          }
          return state.toolCalls;
        })()
      : state.toolCalls.map((item) => item.toolCallId === event.toolCallId ? {
          ...item,
          argsText: nextArgsText,
        } : item);
    const nextState: AgUiRunState = {
      ...state,
      toolCalls,
      traceEvents: upsertTraceEvent(state.traceEvents, {
        kind: "tool_call",
        summary: nextArgsText,
        title: currentToolCall?.toolCallName,
        toolName: currentToolCall?.toolCallName,
        callId: event.toolCallId,
        payload: {
          arguments: nextArgsText,
        },
      }, (item) => item.kind === "tool_call" && item.callId === event.toolCallId, context),
    };
    return updateNativeToolEntryBody(nextState, event.toolCallId, nextArgsText, context);
  }

  if (event.type === EventType.TOOL_CALL_END) {
    if (context) {
      const index = context.toolCallById.get(event.toolCallId);
      if (typeof index === "number") {
        const item = state.toolCalls[index];
        state.toolCalls[index] = {
          ...item,
          status: item.resultText ? "completed" : item.status,
        };
      }
      return { ...state, toolCalls: state.toolCalls };
    }
    return {
      ...state,
      toolCalls: state.toolCalls.map((item) => item.toolCallId === event.toolCallId ? {
        ...item,
        status: item.resultText ? "completed" : item.status,
      } : item),
    };
  }

  if (event.type === EventType.TOOL_CALL_RESULT) {
    const currentToolCallIndex = context ? context.toolCallById.get(event.toolCallId) ?? -1 : -1;
    const currentToolCall = context
      ? state.toolCalls[currentToolCallIndex]
      : state.toolCalls.find((item) => item.toolCallId === event.toolCallId);
    const traceEvent: ChatTraceEvent = {
      kind: "tool_result",
      summary: event.content,
      title: currentToolCall?.toolCallName,
      toolName: currentToolCall?.toolCallName,
      callId: event.toolCallId,
      payload: {
        output: event.content,
      },
    };
    const toolCalls = context
      ? (() => {
          if (currentToolCallIndex >= 0) {
            state.toolCalls[currentToolCallIndex] = {
              ...state.toolCalls[currentToolCallIndex],
              resultText: event.content,
              status: "completed",
            };
          }
          return state.toolCalls;
        })()
      : state.toolCalls.map((item) => item.toolCallId === event.toolCallId ? {
          ...item,
          resultText: event.content,
          status: "completed" as const,
        } : item);
    const nextState: AgUiRunState = {
      ...state,
      messageId: event.messageId,
      toolCalls,
      traceEvents: upsertTraceEvent(
        state.traceEvents,
        traceEvent,
        (item) => item.kind === "tool_result" && item.callId === event.toolCallId,
        context,
      ),
    };
    return appendTraceEntry(nextState, traceEvent, {
      kind: "event",
      label: "工具结果",
      summary: event.content || currentToolCall?.toolCallName || "工具结果",
      body: event.content,
      collapsedByDefault: true,
    }, context);
  }

  if (event.type === EventType.REASONING_START || event.type === EventType.REASONING_MESSAGE_START) {
    const messageId = "messageId" in event ? event.messageId : state.messageId || "reasoning";
    const reasoningIndex = context ? context.reasoningByMessageId.get(messageId) ?? -1 : -1;
    const current = context
      ? state.reasoning[reasoningIndex]
      : state.reasoning.find((item) => item.messageId === messageId);
    if (current) {
      return state;
    }
    if (context) {
      state.reasoning.push({ messageId, text: "" });
      context.reasoningByMessageId.set(messageId, state.reasoning.length - 1);
      return { ...state, reasoning: state.reasoning };
    }
    return {
      ...state,
      reasoning: [...state.reasoning, {
        messageId,
        text: "",
      }],
    };
  }

  if (event.type === EventType.REASONING_MESSAGE_CONTENT) {
    const reasoningIndex = context ? context.reasoningByMessageId.get(event.messageId) ?? -1 : -1;
    const current = context
      ? state.reasoning[reasoningIndex]
      : state.reasoning.find((item) => item.messageId === event.messageId);
    const nextText = `${current?.text || ""}${event.delta}`;
    const reasoning = context
      ? (() => {
          if (reasoningIndex >= 0) {
            state.reasoning[reasoningIndex] = { ...state.reasoning[reasoningIndex], text: nextText };
          } else {
            state.reasoning.push({ messageId: event.messageId, text: event.delta });
            context.reasoningByMessageId.set(event.messageId, state.reasoning.length - 1);
          }
          return state.reasoning;
        })()
      : current
        ? state.reasoning.map((item) => item.messageId === event.messageId ? { ...item, text: nextText } : item)
        : [...state.reasoning, { messageId: event.messageId, text: event.delta }];
    return {
      ...state,
      reasoning,
    };
  }

  if (event.type === EventType.REASONING_MESSAGE_END || event.type === EventType.REASONING_END) {
    const messageId = event.messageId;
    const reasoningItem = context
      ? state.reasoning[context.reasoningByMessageId.get(messageId) ?? -1]
      : state.reasoning.find((item) => item.messageId === messageId);
    if (!reasoningItem?.text.trim()) {
      return state;
    }
    const traceEvent: ChatTraceEvent = {
      kind: "reasoning",
      summary: reasoningItem.text,
      source: "reasoning",
      rawType: EventType.REASONING_MESSAGE_END,
    };
    const nextState: AgUiRunState = {
      ...state,
      traceEvents: upsertTraceEvent(
        state.traceEvents,
        traceEvent,
        (item) => item.kind === "reasoning" && item.rawType === EventType.REASONING_MESSAGE_END && item.summary === reasoningItem.text,
        context,
      ),
    };
    return appendTraceEntry(nextState, traceEvent, {
      kind: "process",
      label: "思考",
      summary: reasoningItem.text,
      collapsedByDefault: false,
    }, context);
  }

  if (event.type === EventType.RUN_FINISHED) {
    const result = asRecord(event.result);
    const resultMessage = asRecord(result.message);
    const resultMeta = asRecord(resultMessage.meta);
    const completionState = completionStateFromRunFinished(event, result);
    const elapsedSeconds = typeof result.elapsedSeconds === "number"
      ? result.elapsedSeconds
      : typeof result.elapsed_seconds === "number"
        ? result.elapsed_seconds
        : state.elapsedSeconds;
    const contextUsage = (
      mapChatMessageContextUsage(result.contextUsage)
      || mapChatMessageContextUsage(result.context_usage)
      || mapChatMessageContextUsage(resultMeta.contextUsage)
      || mapChatMessageContextUsage(resultMeta.context_usage)
      || state.contextUsage
    );
    const cancelledTrace = completionState === "cancelled"
      ? [{
        kind: "cancelled",
        summary: "用户终止输出",
        rawType: EventType.RUN_FINISHED,
      } satisfies ChatTraceEvent]
      : [];
    const nextState: AgUiRunState = {
      ...state,
      threadId: event.threadId,
      runId: event.runId,
      running: false,
      completed: true,
      completionState,
      elapsedSeconds,
      contextUsage,
      traceEvents: cancelledTrace.length
        ? upsertTraceEvent(
          state.traceEvents,
          cancelledTrace[0],
          (item) => item.kind === "cancelled" && item.rawType === EventType.RUN_FINISHED,
          context,
        )
        : state.traceEvents,
    };
    return cancelledTrace.length
      ? appendTraceEntry(nextState, cancelledTrace[0], {
          kind: "cancelled",
          label: "已取消",
          summary: "用户终止输出",
          collapsedByDefault: false,
        }, context)
      : nextState;
  }

  if (event.type === EventType.RUN_ERROR) {
    const errorCode = event.code || "";
    const traceEvent: ChatTraceEvent = {
      kind: "error",
      summary: event.message,
      rawType: errorCode,
    };
    const nextState: AgUiRunState = {
      ...state,
      running: false,
      completed: true,
      error: {
        message: event.message,
          ...(errorCode ? { code: errorCode } : {}),
      },
      traceEvents: context
        ? (() => {
            context.traces.append(traceEvent);
            return context.traces.events;
          })()
        : [...state.traceEvents, traceEvent],
    };
    return appendTraceEntry(nextState, traceEvent, {
      kind: "error",
      label: "错误",
      summary: event.message,
      collapsedByDefault: false,
    }, context);
  }

  return state;
}

export function buildAgUiMessageMeta(state: AgUiRunState, options: { nativeAgent?: boolean } = {}): ChatMessageMetaInfo | undefined {
  const projection = liveProjectionByState.get(state);
  const entryTrace = projection && projection.trace.length > 0
    ? projection.trace
    : state.entries
      .filter((entry) => entry.trace)
      .map((entry) => ({
        ...entry.trace!,
        sequence: typeof entry.trace!.sequence === "number" ? entry.trace!.sequence : entry.seq,
      }));
  const trace = entryTrace.length > 0
    ? entryTrace
    : state.traceEvents.length > 0
      ? state.traceEvents
      : undefined;
  const usingLiveProjection = Boolean(projection && entryTrace === projection.trace);
  const toolCallCount = usingLiveProjection
    ? projection?.toolCallCount
    : trace?.filter((event) => event.kind === "tool_call").length;
  const processCount = usingLiveProjection
    ? projection?.processCount
    : trace?.filter((event) => event.kind !== "tool_call" && event.kind !== "tool_result").length;
  const meta: ChatMessageMetaInfo = {
    completionState: state.error ? "error" : state.completionState || (state.completed ? "completed" : state.running ? "streaming" : undefined),
    traceVersion: trace ? 1 : undefined,
    traceCount: trace?.length,
    toolCallCount,
    processCount,
    contextUsage: state.contextUsage,
    trace,
    ...(options.nativeAgent || state.nativeAgent ? { tracePresentation: "native_agent_flat" as const } : {}),
  };
  return Object.values(meta).some((value) => typeof value !== "undefined") ? meta : undefined;
}
