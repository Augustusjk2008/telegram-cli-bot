import type { ConversationSelectResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

/** Announces a main-agent CLI conversation created outside the chat screen, so mounted chats can follow it. */
export const CONVERSATION_CREATED_EVENT = "tcb-conversation-created";

export type ConversationCreatedDetail = {
  botAlias: string;
  result: ConversationSelectResult;
};

export function isConversationCreatedEvent(event: Event): event is CustomEvent<ConversationCreatedDetail> {
  return event instanceof CustomEvent && event.type === CONVERSATION_CREATED_EVENT;
}

/**
 * A different CLI cannot resume the previous CLI's session, so switching CLI type starts a fresh
 * main-agent conversation. Chats that are not mounted load it as the active conversation on open.
 */
export async function startConversationAfterCliSwitch(client: WebBotClient, botAlias: string) {
  const result = await client.createConversation(botAlias);
  window.dispatchEvent(new CustomEvent<ConversationCreatedDetail>(CONVERSATION_CREATED_EVENT, {
    detail: { botAlias, result },
  }));
  return result;
}
