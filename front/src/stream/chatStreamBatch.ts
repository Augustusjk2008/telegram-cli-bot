import type { ChatStatusUpdate, ChatTraceEvent } from "../services/types";

export type ChatStreamEventBase = {
  sendVersion: number;
  assistantId: string;
  assistantMessageId?: string;
  turnId?: string;
  streamStartedAtMs: number;
};

export type ChatStreamInputEvent =
  | (ChatStreamEventBase & { kind: "chunk"; chunk: string })
  | (ChatStreamEventBase & { kind: "status"; status: ChatStatusUpdate; userMessageId: string })
  | (ChatStreamEventBase & { kind: "trace"; trace: ChatTraceEvent; usingPreviewReplace: boolean });

export type ChatStreamRenderEvent = ChatStreamInputEvent;

function sameTarget(left: ChatStreamEventBase, right: ChatStreamEventBase) {
  return left.sendVersion === right.sendVersion
    && left.assistantId === right.assistantId
    && left.streamStartedAtMs === right.streamStartedAtMs;
}

export function isChatStreamBarrier(event: ChatStreamInputEvent) {
  return event.kind === "status" && typeof event.status.replaceText === "string";
}

export function reduceChatStreamBatch(input: readonly ChatStreamInputEvent[]) {
  const events: ChatStreamRenderEvent[] = [];
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
    events.push(event);
  }
  return { events };
}
