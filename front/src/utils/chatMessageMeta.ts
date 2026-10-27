import type { ChatEndlessEvent, ChatMessageMetaInfo, ChatTraceEvent } from "../services/types";
import { isNativeAgentMessage, mergeChatTraceEvents } from "./nativeAgentTranscript";

function pickTraceCount(incomingValue?: number, baseValue?: number, summaryValue?: number) {
  if (typeof incomingValue === "number" && Number.isFinite(incomingValue)) {
    return incomingValue;
  }
  if (typeof summaryValue === "number" && Number.isFinite(summaryValue)) {
    return summaryValue;
  }
  return typeof baseValue === "number" && Number.isFinite(baseValue) ? baseValue : undefined;
}

function pickLoadedTraceCount(incomingValue?: number, baseValue?: number) {
  const values = [incomingValue, baseValue]
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  return values.length > 0 ? Math.max(...values) : undefined;
}

function pickEndlessContinueCount(
  incomingValue: number | undefined,
  baseValue: number | undefined,
  events?: ChatEndlessEvent[],
) {
  const eventCount = (events || []).filter((event) => event.kind === "continue").length;
  return Math.max(
    typeof incomingValue === "number" && Number.isFinite(incomingValue) ? Math.max(0, Math.floor(incomingValue)) : 0,
    typeof baseValue === "number" && Number.isFinite(baseValue) ? Math.max(0, Math.floor(baseValue)) : 0,
    eventCount,
  );
}

function mergeEndlessEvents(
  sources: Array<ChatEndlessEvent[] | undefined>,
) {
  const merged: ChatEndlessEvent[] = [];
  const seen = new Set<string>();
  sources.forEach((source) => {
    (source || []).forEach((event, index) => {
      if (!event || (event.kind !== "error" && event.kind !== "continue")) {
        return;
      }
      const sequence = typeof event.sequence === "number" && Number.isFinite(event.sequence)
        ? Math.max(1, Math.floor(event.sequence))
        : merged.length + index + 1;
      const text = String(event.text || "").trim();
      if (!text) {
        return;
      }
      const normalized: ChatEndlessEvent = {
        kind: event.kind,
        sequence,
        attempt: typeof event.attempt === "number" && Number.isFinite(event.attempt)
          ? Math.max(0, Math.floor(event.attempt))
          : 0,
        text,
        ...(event.code ? { code: String(event.code) } : {}),
      };
      const key = `${normalized.sequence}:${normalized.kind}:${normalized.attempt}:${normalized.code || ""}:${normalized.text}`;
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      merged.push(normalized);
    });
  });
  merged.sort((left, right) => left.sequence - right.sequence);
  return merged.length > 0 ? merged : undefined;
}

function isTerminalCompletionState(value?: string) {
  const state = String(value || "").trim().toLowerCase();
  return Boolean(state && !["streaming", "running", "in_progress", "in-progress"].includes(state));
}

export type MergeMessageMetaOptions = {
  reconcileTraceSnapshots?: boolean;
  dedupeAnonymous?: boolean;
  traceMode?: "merge" | "replace";
};

export function summarizeTrace(trace?: ChatTraceEvent[]) {
  return {
    traceCount: trace?.length || 0,
    toolCallCount: (trace || []).filter((item) => item.kind === "tool_call").length,
    processCount: (trace || []).filter((item) => item.kind !== "tool_call" && item.kind !== "tool_result").length,
  };
}

export function compactCompletedMessageMeta(meta?: ChatMessageMetaInfo): ChatMessageMetaInfo | undefined {
  if (!meta) {
    return undefined;
  }
  const traceSummary = meta.trace ? summarizeTrace(meta.trace) : undefined;
  const retainedTrace = meta.trace?.filter((event) => ["permission", "error", "cancelled"].includes(event.kind));
  const {
    trace: _trace,
    traceLoadedCount: _traceLoadedCount,
    agUiRunState: _agUiRunState,
    ...persistentMeta
  } = meta;
  const compactMeta: ChatMessageMetaInfo = {
    ...persistentMeta,
    traceCount: pickTraceCount(meta.traceCount, undefined, traceSummary?.traceCount),
    toolCallCount: pickTraceCount(meta.toolCallCount, undefined, traceSummary?.toolCallCount),
    processCount: pickTraceCount(meta.processCount, undefined, traceSummary?.processCount),
    trace: retainedTrace && retainedTrace.length > 0 ? retainedTrace : undefined,
    endlessEvents: meta.endlessEvents,
    endlessContinueCount: meta.endlessContinueCount,
    endlessGroupId: meta.endlessGroupId,
  };
  return Object.values(compactMeta).some((value) => typeof value !== "undefined") ? compactMeta : undefined;
}

export function mergeMessageMeta(
  base?: ChatMessageMetaInfo,
  incoming?: ChatMessageMetaInfo,
  streamedTrace?: ChatTraceEvent[],
  options: MergeMessageMetaOptions = {},
): ChatMessageMetaInfo | undefined {
  const isNativeSource = isNativeAgentMessage(incoming) || isNativeAgentMessage(base);
  const tracePresentation = incoming?.tracePresentation || base?.tracePresentation || (isNativeSource ? "native_agent_flat" : undefined);
  const nativeFlatTrace = tracePresentation === "native_agent_flat";
  const trace = options.traceMode === "replace"
    ? incoming?.trace || base?.trace || streamedTrace
    : mergeChatTraceEvents(
        [base?.trace, incoming?.trace, streamedTrace],
        {
          nativeFlat: nativeFlatTrace,
          autoNativeFlat: nativeFlatTrace,
          reconcileTraceSnapshots: options.reconcileTraceSnapshots,
          dedupeAnonymous: options.dedupeAnonymous,
        },
      );
  const hasIncomingTraceSummary = options.traceMode === "replace"
    && Boolean(incoming?.trace)
    && [incoming?.traceCount, incoming?.toolCallCount, incoming?.processCount]
      .every((value) => typeof value === "number" && Number.isFinite(value));
  const traceSummary = trace && !hasIncomingTraceSummary ? summarizeTrace(trace) : undefined;
  const endlessEvents = mergeEndlessEvents([base?.endlessEvents, incoming?.endlessEvents]);
  const endlessContinueCount = pickEndlessContinueCount(
    incoming?.endlessContinueCount,
    base?.endlessContinueCount,
    endlessEvents,
  );
  const hasEndlessMeta = Boolean(endlessEvents)
    || typeof incoming?.endlessContinueCount === "number"
    || typeof base?.endlessContinueCount === "number";
  const incomingRunState = incoming?.agUiRunState && typeof incoming.agUiRunState === "object"
    ? incoming.agUiRunState as { completed?: boolean }
    : undefined;
  const baseRunState = base?.agUiRunState && typeof base.agUiRunState === "object"
    ? base.agUiRunState as { completed?: boolean }
    : undefined;
  const transientRunState = incoming?.agUiRunState || base?.agUiRunState;
  const agUiRunState = isNativeSource
    && !isTerminalCompletionState(incoming?.completionState)
    && !incomingRunState?.completed
    && !baseRunState?.completed
    ? transientRunState
    : undefined;
  const meta: ChatMessageMetaInfo = {
    completionState: incoming?.completionState || base?.completionState,
    summaryKind: incoming?.summaryKind || base?.summaryKind,
    renderKey: incoming?.renderKey || base?.renderKey,
    traceVersion: incoming?.traceVersion ?? base?.traceVersion ?? (trace ? 1 : undefined),
    traceCount: pickTraceCount(incoming?.traceCount, base?.traceCount, traceSummary?.traceCount),
    traceLoadedCount: pickLoadedTraceCount(incoming?.traceLoadedCount, base?.traceLoadedCount),
    toolCallCount: pickTraceCount(incoming?.toolCallCount, base?.toolCallCount, traceSummary?.toolCallCount),
    processCount: pickTraceCount(incoming?.processCount, base?.processCount, traceSummary?.processCount),
    nativeSource: incoming?.nativeSource || base?.nativeSource,
    contextUsage: incoming?.contextUsage || base?.contextUsage,
    endlessEvents,
    endlessContinueCount: hasEndlessMeta ? endlessContinueCount : undefined,
    endlessGroupId: incoming?.endlessGroupId || base?.endlessGroupId,
    agUiRunState,
    tracePresentation,
    trace,
    workspaceHistoryHead: incoming?.workspaceHistoryHead ?? base?.workspaceHistoryHead,
    linearIndex: incoming?.linearIndex ?? base?.linearIndex,
    rollbackSupported: incoming?.rollbackSupported ?? base?.rollbackSupported,
    degraded: incoming?.degraded ?? base?.degraded,
    degradedReason: incoming?.degradedReason ?? base?.degradedReason,
  };

  return Object.values(meta).some((value) => typeof value !== "undefined") ? meta : undefined;
}
