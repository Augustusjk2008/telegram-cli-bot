import type { AgUiEvent } from "../services/agUiProtocol";
import type { ChatStatusUpdate, ChatTraceEvent } from "../services/types";
import {
  createAgUiRunState,
  reduceAgUiRunEvent,
  type AgUiRunState,
} from "../utils/agUiRunReducer";

export type ChatStreamEventBase = {
  sendVersion: number;
  assistantId: string;
  streamStartedAtMs: number;
};

export type ChatStreamInputEvent =
  | (ChatStreamEventBase & { kind: "chunk"; chunk: string })
  | (ChatStreamEventBase & { kind: "status"; status: ChatStatusUpdate; userMessageId: string })
  | (ChatStreamEventBase & {
      kind: "trace";
      trace: ChatTraceEvent;
      nativeTrace: boolean;
      usingPreviewReplace: boolean;
    })
  | (ChatStreamEventBase & { kind: "ag_ui"; event: AgUiEvent; nativeAgent: boolean });

export type ChatStreamRenderEvent =
  | Exclude<ChatStreamInputEvent, { kind: "ag_ui" }>
  | (ChatStreamEventBase & { kind: "ag_ui"; state: AgUiRunState; nativeAgent: boolean });

function sameTarget(left: ChatStreamEventBase, right: ChatStreamEventBase) {
  return left.sendVersion === right.sendVersion
    && left.assistantId === right.assistantId
    && left.streamStartedAtMs === right.streamStartedAtMs;
}

export function isChatStreamBarrier(event: ChatStreamInputEvent) {
  return event.kind === "status" && typeof event.status.replaceText === "string";
}

export function reduceChatStreamBatch(
  input: readonly ChatStreamInputEvent[],
  initialAgUiState: AgUiRunState | null,
  reduceAgUiBatch: (
    state: AgUiRunState | null,
    events: readonly AgUiEvent[],
  ) => AgUiRunState = (state, events) => events.reduce(
    (current, event) => reduceAgUiRunEvent(current, event),
    state || createAgUiRunState(),
  ),
) {
  const events: ChatStreamRenderEvent[] = [];
  let agUiState = initialAgUiState;
  let sawAgUiEvent = false;

  const agUiGroups = new Map<string, AgUiEvent[]>();
  for (const event of input) {
    if (event.kind === "ag_ui") {
      const key = `${event.sendVersion}/${event.assistantId}/${event.streamStartedAtMs}`;
      const group = agUiGroups.get(key) || [];
      group.push(event.event);
      agUiGroups.set(key, group);
    }
  }
  const reducedAgUiGroups = new Map<string, AgUiRunState>();
  for (const [key, group] of agUiGroups) {
    agUiState = reduceAgUiBatch(agUiState, group);
    reducedAgUiGroups.set(key, agUiState);
  }

  for (const event of input) {
    const previous = events[events.length - 1];
    if (event.kind === "chunk" && previous?.kind === "chunk" && sameTarget(previous, event)) {
      previous.chunk += event.chunk;
      continue;
    }
    if (event.kind === "status" && previous?.kind === "status" && sameTarget(previous, event)) {
      previous.status = { ...previous.status, ...event.status };
      continue;
    }
    if (event.kind === "ag_ui") {
      sawAgUiEvent = true;
      const key = `${event.sendVersion}/${event.assistantId}/${event.streamStartedAtMs}`;
      agUiState = reducedAgUiGroups.get(key) || agUiState;
      const { event: _event, ...eventBase } = event;
      const nextEvent: ChatStreamRenderEvent = {
        ...eventBase,
        state: agUiState,
      };
      if (previous?.kind === "ag_ui" && sameTarget(previous, event)) {
        events[events.length - 1] = nextEvent;
      } else {
        events.push(nextEvent);
      }
      continue;
    }
    events.push(event);
  }

  return { events, agUiState, sawAgUiEvent };
}
