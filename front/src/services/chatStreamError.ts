import type { ChatMessage } from "./types";

type ChatStreamIncompleteErrorOptions = {
  partialMessage: ChatMessage;
  turnId?: string;
  assistantMessageId?: string;
};

export class ChatStreamIncompleteError extends Error {
  readonly name = "ChatStreamIncompleteError";
  readonly partialMessage: ChatMessage;
  readonly turnId: string;
  readonly assistantMessageId: string;

  constructor({ partialMessage, turnId = "", assistantMessageId = "" }: ChatStreamIncompleteErrorOptions) {
    super("聊天响应在收到结束事件前中断，正在从历史记录恢复");
    this.partialMessage = partialMessage;
    this.turnId = turnId;
    this.assistantMessageId = assistantMessageId;
  }
}

export function isChatStreamIncompleteError(error: unknown): error is ChatStreamIncompleteError {
  return error instanceof ChatStreamIncompleteError;
}
