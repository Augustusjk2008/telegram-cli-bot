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
  let pendingChunk: {
    event: Extract<ChatStreamRenderEvent, { kind: "chunk" }>;
    parts: string[];
  } | null = null;

  const flushChunk = () => {
    if (!pendingChunk) {
      return;
    }
    events.push({ ...pendingChunk.event, chunk: pendingChunk.parts.join("") });
    pendingChunk = null;
  };

  for (const event of input) {
    if (event.kind === "chunk") {
      if (pendingChunk && sameTarget(pendingChunk.event, event)) {
        pendingChunk.parts.push(event.chunk);
      } else {
        flushChunk();
        pendingChunk = { event, parts: [event.chunk] };
      }
      continue;
    }
    flushChunk();
    const previous = events[events.length - 1];
    if (
      event.kind === "status"
      && previous?.kind === "status"
      && sameTarget(previous, event)
      && !isChatStreamBarrier(previous)
      && !isChatStreamBarrier(event)
    ) {
      events[events.length - 1] = { ...previous, status: { ...previous.status, ...event.status } };
      continue;
    }
    events.push(event);
  }
  flushChunk();
  return { events };
}
