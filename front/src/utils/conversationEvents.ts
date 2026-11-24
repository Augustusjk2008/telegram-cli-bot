import type { ConversationSelectResult, ConversationSummary } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

/** Announces a main-agent conversation selected or created outside the chat screen. */
export const CONVERSATION_CREATED_EVENT = "tcb-conversation-created";

export type ConversationCreatedDetail = {
  botAlias: string;
  result: ConversationSelectResult;
};

export type CliSwitchConversationResult = ConversationSelectResult & {
  reused: boolean;
};

export function isConversationCreatedEvent(event: Event): event is CustomEvent<ConversationCreatedDetail> {
  return event instanceof CustomEvent && event.type === CONVERSATION_CREATED_EVENT;
}

function conversationTimestamp(conversation: ConversationSummary) {
  const updatedAt = Date.parse(conversation.updatedAt || "");
  if (Number.isFinite(updatedAt)) {
    return updatedAt;
  }
  const createdAt = Date.parse(conversation.createdAt || "");
  return Number.isFinite(createdAt) ? createdAt : 0;
}

/**
 * A different CLI cannot resume the previous CLI's native session. Reuse the newest historical
 * conversation owned by the selected CLI when one exists, and create one only as a fallback.
 */
export async function startConversationAfterCliSwitch(
  client: WebBotClient,
  botAlias: string,
  cliType?: string,
): Promise<CliSwitchConversationResult> {
  const normalizedCliType = String(cliType || "").trim().toLowerCase();
  const listed = await client.listConversations(botAlias);
  const historical = normalizedCliType
    ? listed.items
      .filter((conversation) => (
        String(conversation.cliType || "").trim().toLowerCase() === normalizedCliType
        && String(conversation.agentId || "main").trim().toLowerCase() === "main"
      ))
      .sort((left, right) => conversationTimestamp(right) - conversationTimestamp(left))[0]
    : undefined;
  const result = historical
    ? await client.selectConversation(botAlias, historical.id)
    : await client.createConversation(botAlias);
  window.dispatchEvent(new CustomEvent<ConversationCreatedDetail>(CONVERSATION_CREATED_EVENT, {
    detail: { botAlias, result },
  }));
  return { ...result, reused: Boolean(historical) };
}
