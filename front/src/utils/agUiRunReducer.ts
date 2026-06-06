import { EventType, type AgUiEvent } from "../services/agUiProtocol";
import type {
  ChatMessageContextUsage,
  ChatMessageMetaInfo,
  ChatTraceEvent,
} from "../services/types";

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
};

export type AgUiReasoningItem = {
  messageId: string;
  text: string;
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

function completionStateFromRunFinished(event: Extract<AgUiEvent, { type: EventType.RUN_FINISHED }>, result: Record<string, unknown>) {
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
    return "permission";
  }
  if (activityType === "TCB_STATUS") {
    return "status";
  }
  const rawKind = asString(content.rawKind).trim();
  return rawKind || "event";
}

function mapContextUsage(value: unknown): ChatMessageContextUsage | undefined {
  const raw = asRecord(value);
  const provider = asString(raw.provider);
  const source = asString(raw.source);
  const sessionId = asString(raw.sessionId || raw.session_id);
  const usedTokens = typeof raw.usedTokens === "number"
    ? raw.usedTokens
    : typeof raw.used_tokens === "number"
      ? raw.used_tokens
      : undefined;
  const contextWindow = typeof raw.contextWindow === "number"
    ? raw.contextWindow
    : typeof raw.context_window === "number"
      ? raw.context_window
      : undefined;
  const contextLeftPercent = typeof raw.contextLeftPercent === "number"
    ? raw.contextLeftPercent
    : typeof raw.context_left_percent === "number"
      ? raw.context_left_percent
      : undefined;
  const usedDisplay = asString(raw.usedDisplay || raw.used_display);
  const windowDisplay = asString(raw.windowDisplay || raw.window_display);
  const statusText = asString(raw.statusText || raw.status_text);
  const compactionCount = typeof raw.compactionCount === "number"
    ? raw.compactionCount
    : typeof raw.compaction_count === "number"
      ? raw.compaction_count
      : undefined;
  const nextValue: ChatMessageContextUsage = {
    ...(provider ? { provider } : {}),
    ...(source ? { source } : {}),
    ...(sessionId ? { sessionId } : {}),
    ...(typeof usedTokens === "number" ? { usedTokens } : {}),
    ...(typeof contextWindow === "number" ? { contextWindow } : {}),
    ...(typeof contextLeftPercent === "number" ? { contextLeftPercent } : {}),
    ...(usedDisplay ? { usedDisplay } : {}),
    ...(windowDisplay ? { windowDisplay } : {}),
    ...(statusText ? { statusText } : {}),
    ...(typeof compactionCount === "number" ? { compactionCount } : {}),
  };
  return Object.keys(nextValue).length > 0 ? nextValue : undefined;
}

function getPermissionId(content: Record<string, unknown>) {
  return asString(content.permissionId || content.id || content.permissionID || content.permission_id).trim();
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
  };
}

export function reduceAgUiRunEvent(state: AgUiRunState, event: AgUiEvent): AgUiRunState {
  if (event.type === EventType.RUN_STARTED) {
    return {
      ...state,
      threadId: event.threadId,
      runId: event.runId,
      running: true,
      completed: false,
      error: undefined,
    };
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

    const traceKind = resolveActivityTraceKind(event.activityType, content);
    const traceEvents = traceKind
      ? upsertTraceEvent(
        state.traceEvents,
        {
          kind: traceKind,
          summary,
          source: asString(content.source).trim() || (traceKind === "permission" ? "native_agent" : ""),
          rawType: asString(content.rawType).trim() || event.activityType,
          title: asString(content.title).trim() || undefined,
          payload: content,
        },
        (item) => (
          traceKind === "permission"
            ? item.kind === "permission" && getPermissionId(asRecord(item.payload)) === getPermissionId(content)
            : item.kind === traceKind && item.rawType === (asString(content.rawType).trim() || event.activityType) && item.summary === summary
        ),
      )
      : state.traceEvents;

    const permissionId = getPermissionId(content);
    const permissionRequests = event.activityType === "TCB_PERMISSION_REQUEST" && permissionId
      ? (() => {
          const nextPermission: AgUiPermissionRequest = {
            permissionId,
            summary,
            state: asString(content.state || content.status).trim(),
            content,
            source: asString(content.source).trim() || "native_agent",
          };
          const permissionIndex = state.permissionRequests.findIndex((item) => item.permissionId === permissionId);
          return permissionIndex < 0
            ? [...state.permissionRequests, nextPermission]
            : state.permissionRequests.map((item, index) => index === permissionIndex ? nextPermission : item);
        })()
      : state.permissionRequests;

    return {
      ...state,
      messageId: event.messageId,
      activities,
      permissionRequests,
      traceEvents,
      ...(event.activityType === "TCB_STATUS"
        ? {
            previewText: asString(content.previewText).trim() || asString(content.message).trim() || state.previewText,
            elapsedSeconds: typeof content.elapsedSeconds === "number" ? content.elapsedSeconds : state.elapsedSeconds,
            contextUsage: mapContextUsage(content.contextUsage) || state.contextUsage,
          }
        : {}),
      ...(event.activityType === "TCB_META"
        ? {
            clusterRunId: asString(content.clusterRunId).trim() || state.clusterRunId,
          }
        : {}),
    };
  }

  if (event.type === EventType.TOOL_CALL_START) {
    const nextToolCall: AgUiToolCallItem = {
      toolCallId: event.toolCallId,
      toolCallName: event.toolCallName,
      argsText: "",
      resultText: "",
      status: "running",
    };
    return {
      ...state,
      toolCalls: [...state.toolCalls.filter((item) => item.toolCallId !== event.toolCallId), nextToolCall],
      traceEvents: upsertTraceEvent(state.traceEvents, {
        kind: "tool_call",
        summary: "",
        title: event.toolCallName,
        toolName: event.toolCallName,
        callId: event.toolCallId,
        payload: {
          arguments: "",
        },
      }, (item) => item.kind === "tool_call" && item.callId === event.toolCallId),
    };
  }

  if (event.type === EventType.TOOL_CALL_ARGS) {
    const currentToolCall = state.toolCalls.find((item) => item.toolCallId === event.toolCallId);
    const nextArgsText = `${currentToolCall?.argsText || ""}${event.delta}`;
    return {
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
    return {
      ...state,
      messageId: event.messageId,
      toolCalls: state.toolCalls.map((item) => item.toolCallId === event.toolCallId ? {
        ...item,
        resultText: event.content,
        status: "completed",
      } : item),
      traceEvents: [
        ...state.traceEvents,
        {
          kind: "tool_result",
          summary: event.content,
          title: currentToolCall?.toolCallName,
          toolName: currentToolCall?.toolCallName,
          callId: event.toolCallId,
          payload: {
            output: event.content,
          },
        },
      ],
    };
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
    return {
      ...state,
      traceEvents: upsertTraceEvent(state.traceEvents, {
        kind: "reasoning",
        summary: reasoningItem.text,
        source: "reasoning",
        rawType: EventType.REASONING_MESSAGE_END,
      }, (item) => item.kind === "reasoning" && item.rawType === EventType.REASONING_MESSAGE_END && item.summary === reasoningItem.text),
    };
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
      mapContextUsage(result.contextUsage)
      || mapContextUsage(result.context_usage)
      || mapContextUsage(resultMeta.contextUsage)
      || mapContextUsage(resultMeta.context_usage)
      || state.contextUsage
    );
    const cancelledTrace = completionState === "cancelled"
      ? [{
        kind: "cancelled",
        summary: "用户终止输出",
        rawType: EventType.RUN_FINISHED,
      } satisfies ChatTraceEvent]
      : [];
    return {
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
  }

  if (event.type === EventType.RUN_ERROR) {
    return {
      ...state,
      running: false,
      completed: true,
      error: {
        message: event.message,
        ...(event.code ? { code: event.code } : {}),
      },
      traceEvents: [...state.traceEvents, {
        kind: "error",
        summary: event.message,
        rawType: event.code,
      }],
    };
  }

  return state;
}

export function buildAgUiMessageMeta(state: AgUiRunState): ChatMessageMetaInfo | undefined {
  const trace = state.traceEvents.length > 0 ? state.traceEvents : undefined;
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
  };
  return Object.values(meta).some((value) => typeof value !== "undefined") ? meta : undefined;
}
