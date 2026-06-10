import { EventType, type AgUiEvent } from "../services/agUiProtocol";
import type {
  ChatMessageContextUsage,
  ChatMessageMetaInfo,
  ChatTraceEvent,
} from "../services/types";
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

function upsertTraceEvent(traceEvents: ChatTraceEvent[], nextEvent: ChatTraceEvent, match?: (event: ChatTraceEvent) => boolean) {
  if (!match) {
    const merged = mergeChatTraceEvents([traceEvents, [nextEvent]], { nativeFlat: true });
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
    || stringifyValue(content).trim()
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
): AgUiRunState {
  const seq = state.nextEntrySeq;
  const nextEntry: NativeAgentTranscriptEntry = {
    ...entry,
    id: entry.id || `native-entry-${seq}`,
    seq,
  };
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
  if (kind === "permission" && options.permissionId) {
    const entryIndex = state.entries.findIndex((item) => item.kind === "permission" && item.permissionId === options.permissionId);
    if (entryIndex >= 0) {
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
    const entryIndex = state.entries.findIndex((item) => item.trace?.kind === "tool_result" && item.trace.callId === trace.callId);
    if (entryIndex >= 0) {
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
  return appendNativeEntry(state, entry);
}

function updateNativeToolEntryBody(state: AgUiRunState, toolCallId: string, body: string): AgUiRunState {
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

export function reduceAgUiRunEvent(state: AgUiRunState, event: AgUiEvent): AgUiRunState {
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
    const content = event.type === EventType.ACTIVITY_SNAPSHOT
      ? asRecord(event.content)
      : {
          patch: Array.isArray(event.patch) ? event.patch : [],
        };
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
    const activityIndex = state.activities.findIndex((item) => item.id === nextActivity.id && item.activityType === nextActivity.activityType);
    const activities = activityIndex < 0
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
    const activityTraceEvent: ChatTraceEvent | null = traceKind
      ? {
          ...(asString(content.id).trim() ? { id: asString(content.id).trim() } : {}),
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
      ? upsertTraceEvent(state.traceEvents, activityTraceEvent)
      : state.traceEvents;

    const permissionRequests = nextPermissionRequest
      ? (() => {
          const permissionIndex = state.permissionRequests.findIndex((item) => item.permissionId === nextPermissionRequest.permissionId);
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
        || asString(content.source).trim().toLowerCase() === "native_agent",
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
    });
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
    const nextState: AgUiRunState = {
      ...state,
      toolCalls: [...state.toolCalls.filter((item) => item.toolCallId !== event.toolCallId), nextToolCall],
      traceEvents: upsertTraceEvent(state.traceEvents, traceEvent, (item) => item.kind === "tool_call" && item.callId === event.toolCallId),
    };
    return appendTraceEntry(nextState, traceEvent, {
      kind: "tool",
      label: event.toolCallName || "工具",
      summary: event.toolCallName || "工具调用",
      body: "",
      collapsedByDefault: true,
    });
  }

  if (event.type === EventType.TOOL_CALL_ARGS) {
    const currentToolCall = state.toolCalls.find((item) => item.toolCallId === event.toolCallId);
    const nextArgsText = `${currentToolCall?.argsText || ""}${event.delta}`;
    const nextState: AgUiRunState = {
      ...state,
      toolCalls: state.toolCalls.map((item) => item.toolCallId === event.toolCallId ? {
        ...item,
        argsText: nextArgsText,
      } : item),
      traceEvents: upsertTraceEvent(state.traceEvents, {
        kind: "tool_call",
        summary: nextArgsText,
        title: currentToolCall?.toolCallName,
        toolName: currentToolCall?.toolCallName,
        callId: event.toolCallId,
        payload: {
          arguments: nextArgsText,
        },
      }, (item) => item.kind === "tool_call" && item.callId === event.toolCallId),
    };
    return updateNativeToolEntryBody(nextState, event.toolCallId, nextArgsText);
  }

  if (event.type === EventType.TOOL_CALL_END) {
    return {
      ...state,
      toolCalls: state.toolCalls.map((item) => item.toolCallId === event.toolCallId ? {
        ...item,
        status: item.resultText ? "completed" : item.status,
      } : item),
    };
  }

  if (event.type === EventType.TOOL_CALL_RESULT) {
    const currentToolCall = state.toolCalls.find((item) => item.toolCallId === event.toolCallId);
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
    const nextState: AgUiRunState = {
      ...state,
      messageId: event.messageId,
      toolCalls: state.toolCalls.map((item) => item.toolCallId === event.toolCallId ? {
        ...item,
        resultText: event.content,
        status: "completed",
      } : item),
      traceEvents: upsertTraceEvent(
        state.traceEvents,
        traceEvent,
        (item) => item.kind === "tool_result" && item.callId === event.toolCallId,
      ),
    };
    return appendTraceEntry(nextState, traceEvent, {
      kind: "event",
      label: "工具结果",
      summary: event.content || currentToolCall?.toolCallName || "工具结果",
      body: event.content,
      collapsedByDefault: true,
    });
  }

  if (event.type === EventType.REASONING_START || event.type === EventType.REASONING_MESSAGE_START) {
    const messageId = "messageId" in event ? event.messageId : state.messageId || "reasoning";
    const current = state.reasoning.find((item) => item.messageId === messageId);
    if (current) {
      return state;
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
    const current = state.reasoning.find((item) => item.messageId === event.messageId);
    const nextText = `${current?.text || ""}${event.delta}`;
    const reasoning = current
      ? state.reasoning.map((item) => item.messageId === event.messageId ? { ...item, text: nextText } : item)
      : [...state.reasoning, { messageId: event.messageId, text: event.delta }];
    return {
      ...state,
      reasoning,
    };
  }

  if (event.type === EventType.REASONING_MESSAGE_END || event.type === EventType.REASONING_END) {
    const messageId = event.messageId;
    const reasoningItem = state.reasoning.find((item) => item.messageId === messageId);
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
      ),
    };
    return appendTraceEntry(nextState, traceEvent, {
      kind: "process",
      label: "思考",
      summary: reasoningItem.text,
      collapsedByDefault: false,
    });
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
        )
        : state.traceEvents,
    };
    return cancelledTrace.length
      ? appendTraceEntry(nextState, cancelledTrace[0], {
          kind: "cancelled",
          label: "已取消",
          summary: "用户终止输出",
          collapsedByDefault: false,
        })
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
      traceEvents: [...state.traceEvents, traceEvent],
    };
    return appendTraceEntry(nextState, traceEvent, {
      kind: "error",
      label: "错误",
      summary: event.message,
      collapsedByDefault: false,
    });
  }

  return state;
}

export function buildAgUiMessageMeta(state: AgUiRunState, options: { nativeAgent?: boolean } = {}): ChatMessageMetaInfo | undefined {
  const entryTrace = state.entries
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
  const toolCallCount = trace?.filter((event) => event.kind === "tool_call").length;
  const processCount = trace?.filter((event) => event.kind !== "tool_call" && event.kind !== "tool_result").length;
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
