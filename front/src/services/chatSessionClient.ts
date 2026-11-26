import { WebApiClientError } from "./types";
import type { WebBotClient } from "./webBotClient";

const chatMethods = new Set<keyof WebBotClient>([
  "getBotOverview", "sendMessage", "steerMessage", "killTask",
  "listMessages", "listMessageDelta", "getMessageTrace", "getMessageTraceEvent",
  "retryAnswerTranslation", "executePlan", "listFavoriteAnswers", "favoriteAnswer",
  "deleteFavoriteAnswer", "listConversations", "createConversation", "selectConversation",
  "deleteConversation", "archiveConversation", "deleteAllConversations",
]);

const unsupportedMethods = new Set<keyof WebBotClient>([
  "listAgents", "getClusterStatus", "getClusterTaskStatus", "prepareClusterSetup",
  "updateClusterConfig", "connectCodexVoice", "resetSession",
]);

/** A bound view shares its owner's account, workspace and notifications. Only chat
 * methods run on the session-specific receiver, including throughout async streams. */
export function bindChatSession<T extends WebBotClient>(
  owner: T,
  cache: Map<string, WebBotClient>,
  botAlias: string,
  sessionId: string,
  createChatReceiver: () => T,
): WebBotClient {
  if (sessionId === "main") return owner;
  if (!sessionId.trim() || sessionId === "." || sessionId === "..") {
    throw new Error("无效的聊天会话 ID");
  }
  const key = JSON.stringify([botAlias, sessionId]);
  const existing = cache.get(key);
  if (existing) return existing;

  const chat = createChatReceiver();
  const methods = new Map<PropertyKey, unknown>();
  const view = new Proxy(owner, {
    get(target, property: keyof WebBotClient) {
      if (methods.has(property)) return methods.get(property);
      const method = target[property];
      if (typeof method !== "function") return method;
      let bound;
      if (unsupportedMethods.has(property)) {
        const unsupported = () => {
          throw new WebApiClientError("此会话不支持该操作", { code: "chat_session_unsupported", status: 409 });
        };
        bound = property === "connectCodexVoice" ? unsupported : async () => unsupported();
      } else if (chatMethods.has(property)) {
        bound = async (alias: string, ...args: unknown[]) => {
          if (alias !== botAlias) throw new Error("聊天会话与 Bot 不匹配");
          return Reflect.apply(method, chat, [alias, ...args]);
        };
      } else {
        bound = method.bind(target);
      }
      methods.set(property, bound);
      return bound;
    },
  });
  cache.set(key, view);
  return view;
}
