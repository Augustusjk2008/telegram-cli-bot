import type { ChatMessage } from "../services/types";

export function resolveMessageVirtualKey(
  messages: readonly ChatMessage[],
  messageId: string,
  messageKey: string,
  getVirtualKey: (message: ChatMessage) => string,
) {
  const item = messages.find((message) => message.id === messageId || getVirtualKey(message) === messageKey);
  return item ? getVirtualKey(item) || item.id : messageKey || messageId;
}
