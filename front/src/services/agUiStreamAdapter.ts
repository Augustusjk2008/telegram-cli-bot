import { EventType, parseAgUiEvent, type AgUiEvent } from "./agUiProtocol";

const AG_UI_EVENT_TYPES = new Set<string>(Object.values(EventType));

type LegacyTraceEvent = {
  id?: unknown;
  ordinal?: unknown;
  sequence?: unknown;
  created_at?: unknown;
  createdAt?: unknown;
  kind?: unknown;
  summary?: unknown;
  source?: unknown;
  raw_type?: unknown;
  rawType?: unknown;
  title?: unknown;
  tool_name?: unknown;
  toolName?: unknown;
  call_id?: unknown;
  callId?: unknown;
  payload?: unknown;
};

type LegacyStreamEvent = {
  type?: unknown;
  text?: unknown;
  snapshot?: unknown;
  elapsed_seconds?: unknown;
  preview_text?: unknown;
  context_usage?: unknown;
  phase?: unknown;
  message?: unknown;
  lifecycle?: unknown;
  cluster_run_id?: unknown;
  event?: unknown;
  output?: unknown;
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

function normalizePayloadText(payload: unknown) {
  const record = asRecord(payload);
  if ("arguments" in record) {
    return stringifyValue(record.arguments);
  }
  if ("raw_arguments" in record) {
    return stringifyValue(record.raw_arguments);
  }
  if ("output" in record) {
    return stringifyValue(record.output);
  }
  if ("content" in record) {
    return stringifyValue(record.content);
  }
  return stringifyValue(payload);
}

function normalizeSummary(value: unknown, payload?: unknown) {
  const summary = asString(value).trim();
  if (summary) {
    return summary;
  }
  return normalizePayloadText(payload).trim();
}

export function createAgUiStreamAdapter() {
  let sequence = 0;
  let textStarted = false;
  let textEnded = false;
  let runStarted = false;
  const threadId = `legacy-thread-${Date.now().toString(36)}`;
  const runId = `legacy-run-${Date.now().toString(36)}`;
  const messageId = `legacy-message-${Date.now().toString(36)}`;

  const nextId = (prefix: string) => {
    sequence += 1;
    return `${prefix}-${sequence}`;
  };

  const ensureRunStarted = (): AgUiEvent[] => {
    if (runStarted) {
      return [];
    }
    runStarted = true;
    return [{
      type: EventType.RUN_STARTED,
      threadId,
      runId,
    }];
  };

  const ensureTextStarted = (): AgUiEvent[] => {
    if (textStarted) {
      return [];
    }
    textStarted = true;
    return [{
      type: EventType.TEXT_MESSAGE_START,
      messageId,
      role: "assistant",
    }];
  };

  const ensureTextEnded = (): AgUiEvent[] => {
    if (!textStarted || textEnded) {
      return [];
    }
    textEnded = true;
    return [{
      type: EventType.TEXT_MESSAGE_END,
      messageId,
    }];
  };

  const mapLegacyTraceEvent = (traceValue: unknown): AgUiEvent[] => {
    const trace = asRecord(traceValue) as LegacyTraceEvent;
    const kind = asString(trace.kind).trim().toLowerCase();
    const summary = normalizeSummary(trace.summary, trace.payload);
    const rawType = asString(trace.raw_type || trace.rawType).trim();
    const title = asString(trace.title).trim();
    const source = asString(trace.source).trim();
    const toolCallId = asString(trace.call_id || trace.callId).trim() || nextId("tool");
    const toolName = asString(trace.tool_name || trace.toolName).trim() || title || "tool";
    const payload = asRecord(trace.payload);

    if (kind === "tool_call") {
      const argsText = normalizePayloadText(trace.payload).trim();
      return [
        ...ensureRunStarted(),
        {
          type: EventType.TOOL_CALL_START,
          toolCallId,
          toolCallName: toolName,
        },
        ...(argsText ? [{
          type: EventType.TOOL_CALL_ARGS,
          toolCallId,
          delta: argsText,
        } satisfies AgUiEvent] : []),
        {
          type: EventType.TOOL_CALL_END,
          toolCallId,
        },
      ];
    }

    if (kind === "tool_result") {
      return [
        ...ensureRunStarted(),
        {
          type: EventType.TOOL_CALL_RESULT,
          messageId,
          toolCallId,
          content: summary || "已返回，无可显示内容",
        },
      ];
    }

    const activityType = kind === "permission"
      ? "TCB_PERMISSION_REQUEST"
      : `TCB_TRACE_${(kind || "event").toUpperCase()}`;
    return [
      ...ensureRunStarted(),
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId,
        activityType,
        replace: kind === "permission",
        content: {
          ...payload,
          id: asString(trace.id).trim() || payload.id,
          ordinal: typeof trace.ordinal === "number" ? trace.ordinal : payload.ordinal,
          sequence: typeof trace.sequence === "number" ? trace.sequence : payload.sequence,
          createdAt: asString(trace.created_at || trace.createdAt).trim() || payload.createdAt,
          summary,
          source,
          rawType,
          title,
          rawKind: kind || "event",
        },
      },
    ];
  };

  return {
    adapt(raw: unknown): AgUiEvent[] {
      if (typeof raw === "undefined" || raw === null) {
        return [];
      }

      const directRecord = asRecord(raw);
      const rawType = asString(directRecord.type).trim();
      if (!rawType || rawType === "server.connected" || rawType === "server.heartbeat" || rawType.startsWith("server.")) {
        return [];
      }

      if (AG_UI_EVENT_TYPES.has(rawType)) {
        const parsed = parseAgUiEvent(raw);
        if (parsed) {
          runStarted = true;
        }
        if (parsed?.type === EventType.TEXT_MESSAGE_START || parsed?.type === EventType.TEXT_MESSAGE_CONTENT) {
          textStarted = true;
          textEnded = false;
        }
        if (parsed?.type === EventType.TEXT_MESSAGE_END) {
          textStarted = true;
          textEnded = true;
        }
        if (parsed?.type === EventType.RUN_FINISHED) {
          textEnded = textStarted || textEnded;
        }
        return parsed ? [parsed] : [];
      }

      const legacyEvent = directRecord as LegacyStreamEvent;
      if (rawType === "delta") {
        const text = asString(legacyEvent.text);
        if (!text) {
          return [];
        }
        return [
          ...ensureRunStarted(),
          ...ensureTextStarted(),
          {
            type: EventType.TEXT_MESSAGE_CONTENT,
            messageId,
            delta: text,
          },
        ];
      }

      if (rawType === "snapshot") {
        const text = asString(legacyEvent.text) || asString(legacyEvent.snapshot);
        return [
          ...ensureRunStarted(),
          {
            type: EventType.MESSAGES_SNAPSHOT,
            messages: [
              {
                id: messageId,
                role: "assistant",
                content: text,
              },
            ],
          },
        ];
      }

      if (rawType === "meta") {
        const clusterRunId = asString(directRecord.cluster_run_id).trim();
        if (!clusterRunId) {
          return [];
        }
        return [
          ...ensureRunStarted(),
          {
            type: EventType.ACTIVITY_SNAPSHOT,
            messageId,
            activityType: "TCB_META",
            replace: true,
            content: {
              clusterRunId,
            },
          },
        ];
      }

      if (rawType === "status") {
        return [
          ...ensureRunStarted(),
          {
            type: EventType.ACTIVITY_SNAPSHOT,
            messageId,
            activityType: "TCB_STATUS",
            replace: true,
            content: {
              elapsedSeconds: typeof legacyEvent.elapsed_seconds === "number" ? legacyEvent.elapsed_seconds : undefined,
              previewText: asString(legacyEvent.preview_text).trim(),
              contextUsage: asRecord(legacyEvent.context_usage),
              phase: asString(legacyEvent.phase).trim(),
              message: asString(legacyEvent.message).trim(),
              lifecycle: asString(legacyEvent.lifecycle).trim(),
            },
          },
        ];
      }

      if (rawType === "trace") {
        return mapLegacyTraceEvent(directRecord.event);
      }

      if (rawType === "done") {
        const events: AgUiEvent[] = [...ensureRunStarted()];
        const doneMessage = asRecord(directRecord.message);
        const doneMeta = asRecord(doneMessage.meta);
        const output = asString(doneMessage.content).trim() || asString(directRecord.output).trim();
        const elapsedSeconds = typeof directRecord.elapsed_seconds === "number" ? directRecord.elapsed_seconds : undefined;
        const contextUsage = asRecord(doneMeta.context_usage || doneMeta.contextUsage || directRecord.context_usage);
        const messageState = asString(doneMessage.state).trim().toLowerCase();
        const completionState = (
          asString(doneMeta.completion_state || doneMeta.completionState).trim()
          || asString(doneMessage.completion_state || doneMessage.completionState).trim()
          || (["cancelled", "canceled", "error", "failed"].includes(messageState) ? messageState : "")
        );
        if (output && !textStarted) {
          events.push(...ensureTextStarted());
          events.push({
            type: EventType.TEXT_MESSAGE_CONTENT,
            messageId,
            delta: output,
          });
        }
        events.push(...ensureTextEnded());
        events.push({
          type: EventType.RUN_FINISHED,
          threadId,
          runId,
          result: {
            message: doneMessage,
            content: output,
            elapsedSeconds,
            contextUsage,
            ...(completionState ? { completion_state: completionState } : {}),
          },
          outcome: completionState && completionState !== "completed"
            ? { type: "interrupt", interrupts: [{ id: `completion-${completionState}`, reason: completionState }] }
            : { type: "success" },
        });
        return events;
      }

      if (rawType === "error") {
        return [
          ...ensureRunStarted(),
          {
            type: EventType.RUN_ERROR,
            message: asString(directRecord.message).trim() || "流式响应失败",
            code: asString(directRecord.code).trim() || undefined,
          },
        ];
      }

      return [];
    },
  };
}
