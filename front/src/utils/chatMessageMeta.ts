import type { ChatMessageMetaInfo, ChatTraceEvent } from "../services/types";
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

export type MergeMessageMetaOptions = {
  reconcileTraceSnapshots?: boolean;
  dedupeAnonymous?: boolean;
};

export function summarizeTrace(trace?: ChatTraceEvent[]) {
  return {
    traceCount: trace?.length || 0,
    toolCallCount: (trace || []).filter((item) => item.kind === "tool_call").length,
    processCount: (trace || []).filter((item) => item.kind !== "tool_call" && item.kind !== "tool_result").length,
  };
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
  const trace = mergeChatTraceEvents(
    [base?.trace, incoming?.trace, streamedTrace],
    {
      nativeFlat: nativeFlatTrace,
      autoNativeFlat: nativeFlatTrace,
      reconcileTraceSnapshots: options.reconcileTraceSnapshots,
      dedupeAnonymous: options.dedupeAnonymous,
    },
  );
  const traceSummary = trace ? summarizeTrace(trace) : undefined;
  const meta: ChatMessageMetaInfo = {
    completionState: incoming?.completionState || base?.completionState,
    summaryKind: incoming?.summaryKind || base?.summaryKind,
    traceVersion: incoming?.traceVersion ?? base?.traceVersion ?? (trace ? 1 : undefined),
    traceCount: pickTraceCount(incoming?.traceCount, base?.traceCount, traceSummary?.traceCount),
    traceLoadedCount: pickLoadedTraceCount(incoming?.traceLoadedCount, base?.traceLoadedCount),
    toolCallCount: pickTraceCount(incoming?.toolCallCount, base?.toolCallCount, traceSummary?.toolCallCount),
    processCount: pickTraceCount(incoming?.processCount, base?.processCount, traceSummary?.processCount),
    nativeSource: incoming?.nativeSource || base?.nativeSource,
    contextUsage: incoming?.contextUsage || base?.contextUsage,
    agUiRunState: isNativeSource ? incoming?.agUiRunState || base?.agUiRunState : undefined,
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
