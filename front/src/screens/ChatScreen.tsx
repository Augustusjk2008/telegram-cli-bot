import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { History, LoaderCircle, Maximize2, Minimize2, Network, Paperclip, Plus, Square, Trash2 } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { AgentSwitcher } from "../components/AgentSwitcher";
import { BotIdentity } from "../components/BotIdentity";
import { ChatAvatar } from "../components/ChatAvatar";
import { ChatComposer } from "../components/ChatComposer";
import { ChatMessageMeta } from "../components/ChatMessageMeta";
import { ChatMarkdownMessage } from "../components/ChatMarkdownMessage";
import { ChatPlainTextMessage } from "../components/ChatPlainTextMessage";
import { ChatTracePanel } from "../components/ChatTracePanel";
import { ConversationHistoryPanel } from "../components/ConversationHistoryPanel";
import { FilePreviewDialog } from "../components/FilePreviewDialog";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  AssistantRuntimePendingRun,
  AgentMention,
  AgentSummary,
  BotOverview,
  BotSummary,
  ChatAttachmentUploadResult,
  ClusterAgentTask,
  ClusterTaskStatus,
  ChatMessage,
  ChatMessageMetaInfo,
  ChatSendOptions,
  ChatStatusUpdate,
  CliParamsPayload,
  ChatTraceEvent,
  ConversationSummary,
  FileReadResult,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  ASSISTANT_CRON_RUN_ENQUEUED_EVENT,
  isAssistantCronRunEnqueuedEvent,
  type AssistantCronRunEnqueuedDetail,
} from "../utils/assistantCronEvents";
import {
  ASSISTANT_PROPOSAL_PATCH_REQUESTED_EVENT,
  dispatchAssistantProposalPatchCompleted,
  isAssistantProposalPatchRequestedEvent,
} from "../utils/assistantProposalPatchEvents";
import { delightMotion, resolveMotionProps } from "../motion/premiumMotion";
import { resolvePreviewFilePath } from "../utils/fileLinks";
import {
  getFilePreviewStatusText,
  isFilePreviewFullyLoaded,
  isFilePreviewTooLarge,
} from "../utils/filePreview";
import type { BotActivityChange } from "../app/botActivity";
import type { ChatWorkbenchStatus } from "../workbench/workbenchTypes";

type Props = {
  botAlias: string;
  client?: WebBotClient;
  botAvatarName?: string;
  userAvatarName?: string;
  readOnly?: boolean;
  allowTrace?: boolean;
  isVisible?: boolean;
  isImmersive?: boolean;
  embedded?: boolean;
  focused?: boolean;
  onToggleFocus?: () => void;
  onToggleImmersive?: () => void;
  onUnreadResult?: (botAlias: string) => void;
  onBotActivityChange?: (botAlias: string, activity: BotActivityChange) => void;
  onWorkbenchStatusChange?: (status: ChatWorkbenchStatus) => void;
  onRequestDesktopPreview?: (path: string) => void;
};

type PendingChatAttachment = ChatAttachmentUploadResult & {
  id: string;
};

type ParsedUserAttachment = {
  filename: string;
  savedPath: string;
};

const ACTIVE_ASSISTANT_POLL_INTERVAL_MS = 1000;
const IDLE_ASSISTANT_POLL_INTERVAL_MS = 5000;
const CLUSTER_TASK_POLL_INTERVAL_MS = 1200;
const SSE_STALL_RECOVERY_DELAY_MS = 2500;
const CHAT_ATTACHMENT_LINE_RE = /^附件路径为[:：]\s*(.+?)\s*$/;
const MODEL_OPTION_NONE = "none";

function fallbackAgents(): AgentSummary[] {
  return [{ id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true }];
}

function activeAgentStorageKey(botAlias: string) {
  return `tcb.activeAgent.${botAlias}`;
}

function readStoredAgentId(botAlias: string) {
  if (typeof window === "undefined") {
    return "main";
  }
  return window.localStorage.getItem(activeAgentStorageKey(botAlias)) || "main";
}

function agentOptions(agentId?: string) {
  return agentId && agentId !== "main" ? { agentId } : undefined;
}

function getScopedOverview(client: WebBotClient, botAlias: string, agentId: string) {
  const options = agentOptions(agentId);
  return options ? client.getBotOverview(botAlias, options) : client.getBotOverview(botAlias);
}

function listScopedMessages(client: WebBotClient, botAlias: string, agentId: string) {
  const options = agentOptions(agentId);
  return options ? client.listMessages(botAlias, options) : client.listMessages(botAlias);
}

function listScopedMessageDelta(client: WebBotClient, botAlias: string, afterId: string, limit: number, agentId: string) {
  const options = agentOptions(agentId);
  return options
    ? client.listMessageDelta(botAlias, afterId, limit, options)
    : client.listMessageDelta(botAlias, afterId, limit);
}

function getScopedMessageTrace(client: WebBotClient, botAlias: string, messageId: string, agentId: string) {
  const options = agentOptions(agentId);
  return options
    ? client.getMessageTrace(botAlias, messageId, options)
    : client.getMessageTrace(botAlias, messageId);
}

function listScopedConversations(client: WebBotClient, botAlias: string, query: string, agentId: string) {
  const options = agentOptions(agentId);
  return options
    ? client.listConversations(botAlias, query, options)
    : client.listConversations(botAlias, query);
}

function selectScopedConversation(client: WebBotClient, botAlias: string, conversationId: string, agentId: string) {
  const options = agentOptions(agentId);
  return options
    ? client.selectConversation(botAlias, conversationId, options)
    : client.selectConversation(botAlias, conversationId);
}

function createScopedConversation(client: WebBotClient, botAlias: string, agentId: string) {
  const options = agentOptions(agentId);
  return options ? client.createConversation(botAlias, "", options) : client.createConversation(botAlias);
}

function pendingCronUserId(runId: string) {
  return `assistant-cron-user-${runId}`;
}

function toModelOptionValue(value: unknown, options: string[]) {
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  return options.includes(MODEL_OPTION_NONE) ? MODEL_OPTION_NONE : "";
}

function pendingCronAssistantId(runId: string) {
  return `assistant-cron-assistant-${runId}`;
}

function summarizeRuntimeText(text: string | undefined, limit = 28) {
  const value = (text || "").trim();
  if (!value) {
    return "";
  }
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, limit).trimEnd()}...`;
}

function assistantRuntimeSourceLabel(run: AssistantRuntimePendingRun) {
  if (run.taskMode === "proposal_patch") {
    return run.interactive ? "生成 Patch" : "后台生成 Patch";
  }
  if (run.source === "cron") {
    return run.taskMode === "dream" ? "定时 dream" : "定时任务";
  }
  if (run.source === "manual") {
    return run.interactive ? "手动执行" : "后台手动任务";
  }
  return run.interactive ? "聊天消息" : "后台任务";
}

function assistantRuntimeRunLabel(run: AssistantRuntimePendingRun) {
  const detail = summarizeRuntimeText(run.jobTitle || run.visibleText);
  if (!detail) {
    return assistantRuntimeSourceLabel(run);
  }
  return `${assistantRuntimeSourceLabel(run)} · ${detail}`;
}

function mergePendingCronRuns(items: ChatMessage[], pendingRuns: AssistantCronRunEnqueuedDetail[]) {
  if (pendingRuns.length === 0) {
    return items;
  }

  const nextItems = items.filter((item) => (
    !pendingRuns.some((pendingRun) => (
      item.id === pendingCronUserId(pendingRun.runId) || item.id === pendingCronAssistantId(pendingRun.runId)
    ))
  ));

  for (const pendingRun of pendingRuns) {
    const hasUserMessage = nextItems.some((item) => item.role === "user" && item.text === pendingRun.prompt);
    if (!hasUserMessage) {
      nextItems.push({
        id: pendingCronUserId(pendingRun.runId),
        role: "user",
        text: pendingRun.prompt,
        createdAt: pendingRun.queuedAt,
        state: "done",
      });
    }

    nextItems.push({
      id: pendingCronAssistantId(pendingRun.runId),
      role: "assistant",
      text: "",
      createdAt: pendingRun.queuedAt,
      state: "streaming",
    });
  }

  return nextItems;
}

function normalizeInactiveStreamingRows(items: ChatMessage[], runtimeActive: boolean) {
  if (runtimeActive) {
    return items;
  }
  return items
    .filter((item) => !(item.role === "assistant" && item.state === "streaming" && !item.text.trim()))
    .map((item) => {
      if (item.role !== "assistant" || item.state !== "streaming") {
        return item;
      }
      return {
        ...item,
        state: "done" as const,
      };
    });
}

function countPersistedHistoryItems(items: ChatMessage[]) {
  return items.filter((item) => !item.id.startsWith("assistant-cron-")).length;
}

function hasPersistedStreamingAssistant(items: ChatMessage[]) {
  return items.some((item) => (
    !item.id.startsWith("assistant-cron-")
    && item.role === "assistant"
    && item.state === "streaming"
  ));
}

function resolvePendingCronRuns(
  pendingRuns: AssistantCronRunEnqueuedDetail[],
  items: ChatMessage[],
) {
  if (pendingRuns.length === 0) {
    return pendingRuns;
  }

  return pendingRuns.filter((pendingRun) => {
    const hasPromptUserMessage = items.some((item) => item.role === "user" && item.text === pendingRun.prompt);
    const hasAssistantMessage = items.some((item) => item.role === "assistant");
    return !(hasPromptUserMessage && hasAssistantMessage);
  });
}

function resolveStreamStartMs(items: ChatMessage[], elapsedSeconds?: number) {
  const streamingItem = [...items].reverse().find((item) => item.role === "assistant" && item.state === "streaming");
  if (streamingItem?.createdAt) {
    const parsed = Date.parse(streamingItem.createdAt);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  if (typeof elapsedSeconds === "number") {
    return Date.now() - elapsedSeconds * 1000;
  }
  return Date.now();
}

function traceEventKey(event: ChatTraceEvent) {
  return [
    event.kind || "",
    event.rawType || "",
    event.callId || "",
    event.summary || "",
  ].join("|");
}

function mergeTraceEvents(...sources: Array<ChatTraceEvent[] | undefined>) {
  const merged: ChatTraceEvent[] = [];
  const seen = new Set<string>();

  for (const source of sources) {
    for (const event of source || []) {
      const key = traceEventKey(event);
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      merged.push(event);
    }
  }

  return merged.length > 0 ? merged : undefined;
}

function maxDefinedNumber(...values: Array<number | undefined>) {
  const definedValues = values.filter((value): value is number => (
    typeof value === "number" && Number.isFinite(value)
  ));
  return definedValues.length > 0 ? Math.max(...definedValues) : undefined;
}

function mergeMessageMeta(base?: ChatMessageMetaInfo, incoming?: ChatMessageMetaInfo): ChatMessageMetaInfo | undefined {
  const trace = mergeTraceEvents(base?.trace, incoming?.trace);
  const meta: ChatMessageMetaInfo = {
    completionState: incoming?.completionState || base?.completionState,
    summaryKind: incoming?.summaryKind || base?.summaryKind,
    traceVersion: incoming?.traceVersion ?? base?.traceVersion ?? (trace ? 1 : undefined),
    traceCount: maxDefinedNumber(incoming?.traceCount, base?.traceCount, trace?.length),
    toolCallCount: maxDefinedNumber(
      incoming?.toolCallCount,
      base?.toolCallCount,
      trace?.filter((event) => event.kind === "tool_call").length,
    ),
    processCount: maxDefinedNumber(
      incoming?.processCount,
      base?.processCount,
      trace?.filter((event) => event.kind !== "tool_call" && event.kind !== "tool_result").length,
    ),
    nativeSource: incoming?.nativeSource || base?.nativeSource,
    trace,
  };

  return Object.values(meta).some((value) => typeof value !== "undefined") ? meta : undefined;
}

function buildComposedMessageText(text: string, attachments: PendingChatAttachment[]) {
  const trimmedText = text.trim();
  const attachmentBlock = attachments
    .map((attachment) => `附件路径为：${attachment.savedPath}`)
    .join("\n");

  if (trimmedText && attachmentBlock) {
    return `${trimmedText}\n\n${attachmentBlock}`;
  }
  return trimmedText || attachmentBlock;
}

function isAbsoluteAttachmentPath(path: string) {
  return /^[A-Za-z]:[\\/]/.test(path) || path.startsWith("/") || path.startsWith("\\\\");
}

function getAttachmentFilename(savedPath: string) {
  const parts = savedPath.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || savedPath;
}

function parseUserMessageDisplay(text: string) {
  const attachments: ParsedUserAttachment[] = [];
  const visibleLines: string[] = [];

  for (const line of text.split(/\r?\n/)) {
    const matched = line.match(CHAT_ATTACHMENT_LINE_RE);
    const savedPath = matched?.[1]?.trim() || "";
    if (savedPath && isAbsoluteAttachmentPath(savedPath)) {
      attachments.push({
        filename: getAttachmentFilename(savedPath),
        savedPath,
      });
      continue;
    }
    visibleLines.push(line);
  }

  return {
    visibleText: visibleLines.join("\n").trim(),
    attachments,
  };
}

function getRenderedAttachmentStateKey(messageId: string, savedPath: string) {
  return `${messageId}|${savedPath}`;
}

function getMessageClientStateKey(item: ChatMessage) {
  const provider = item.meta?.nativeSource?.provider || "";
  const sessionId = item.meta?.nativeSource?.sessionId || "";
  if (item.role === "assistant" && (provider || sessionId) && item.createdAt) {
    return [
      item.role,
      provider,
      sessionId,
      item.createdAt,
    ].join("|");
  }
  return `${item.role}|${item.id}`;
}

function appendTraceToMessage(item: ChatMessage, traceEvent: ChatTraceEvent): ChatMessage {
  return {
    ...item,
    meta: mergeMessageMeta(item.meta, {
      trace: [traceEvent],
      traceVersion: 1,
    }),
  };
}

function updateMessageById(
  items: ChatMessage[],
  messageId: string,
  updater: (item: ChatMessage) => ChatMessage,
) {
  const index = items.findIndex((item) => item.id === messageId);
  if (index < 0) {
    return items;
  }

  const current = items[index];
  const next = updater(current);
  if (next === current) {
    return items;
  }

  const nextItems = items.slice();
  nextItems[index] = next;
  return nextItems;
}

function updateMessageByClientStateKey(
  items: ChatMessage[],
  messageClientStateKey: string,
  updater: (item: ChatMessage) => ChatMessage,
) {
  const index = items.findIndex((item) => getMessageClientStateKey(item) === messageClientStateKey);
  if (index < 0) {
    return items;
  }

  const current = items[index];
  const next = updater(current);
  if (next === current) {
    return items;
  }

  const nextItems = items.slice();
  nextItems[index] = next;
  return nextItems;
}

function updateMessageByIdOrClientStateKey(
  items: ChatMessage[],
  messageId: string,
  messageClientStateKey: string,
  updater: (item: ChatMessage) => ChatMessage,
) {
  const updatedById = updateMessageById(items, messageId, updater);
  if (updatedById !== items) {
    return updatedById;
  }
  return updateMessageByClientStateKey(items, messageClientStateKey, updater);
}

function updateLatestAssistantMessage(
  items: ChatMessage[],
  preferredMessageId: string,
  streamStartedAtMs: number,
  updater: (item: ChatMessage) => ChatMessage,
) {
  const updatedById = updateMessageById(items, preferredMessageId, updater);
  if (updatedById !== items) {
    return updatedById;
  }

  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.role !== "assistant") {
      continue;
    }

    const createdAtMs = Date.parse(item.createdAt || "");
    const isRecentAssistant = !Number.isNaN(createdAtMs) && createdAtMs >= streamStartedAtMs - 1000;
    if (item.state !== "streaming" && !isRecentAssistant) {
      continue;
    }

    const next = updater(item);
    if (next === item) {
      return items;
    }

    const nextItems = items.slice();
    nextItems[index] = next;
    return nextItems;
  }

  return items;
}

function mergeMessagesPreservingClientState(previousItems: ChatMessage[], nextItems: ChatMessage[]) {
  if (previousItems.length === 0 || nextItems.length === 0) {
    return nextItems;
  }

  const previousById = new Map(previousItems.map((item) => [item.id, item]));
  const previousByClientStateKey = new Map(previousItems.map((item) => [getMessageClientStateKey(item), item]));

  return nextItems.map((item) => {
    const previousItem = previousById.get(item.id) || previousByClientStateKey.get(getMessageClientStateKey(item));
    if (!previousItem) {
      return item;
    }

    const mergedMeta = mergeMessageMeta(previousItem.meta, item.meta);
    const nextElapsedSeconds = typeof item.elapsedSeconds === "number" ? item.elapsedSeconds : previousItem.elapsedSeconds;
    const nextState = item.state ?? previousItem.state;

    return {
      ...item,
      ...(typeof nextState !== "undefined" ? { state: nextState } : {}),
      ...(typeof nextElapsedSeconds === "number" ? { elapsedSeconds: nextElapsedSeconds } : {}),
      ...(mergedMeta ? { meta: mergedMeta } : {}),
    };
  });
}

function clusterTaskStatusText(task: ClusterAgentTask) {
  if (task.status === "completed") return "已完成";
  if (task.status === "failed") return "失败";
  if (task.status === "running") return "运行中";
  if (task.status === "queued") return "排队中";
  if (task.status === "cancelled") return "已取消";
  return task.status || "未知";
}

function clusterTaskStatusClass(task: ClusterAgentTask) {
  if (task.status === "completed") return "bg-emerald-100 text-emerald-700";
  if (task.status === "failed") return "bg-red-100 text-red-700";
  if (task.status === "running") return "bg-amber-100 text-amber-700";
  return "bg-slate-100 text-slate-700";
}

function ClusterTaskPanel({ status, agents }: { status: ClusterTaskStatus; agents: AgentSummary[] }) {
  if (status.tasks.length === 0) {
    return null;
  }
  const agentNameMap = new Map(agents.map((agent) => [agent.id, agent.name || agent.id]));
  return (
    <section className="rounded-lg border border-emerald-200 bg-emerald-50/70 px-4 py-3 text-sm text-emerald-950">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">智能体集群任务</span>
        {status.pendingCount > 0 ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-xs text-emerald-800">
            <LoaderCircle className="h-3 w-3 animate-spin" />
            {status.pendingCount} 项进行中
          </span>
        ) : (
          <span className="rounded-full bg-white px-2 py-0.5 text-xs text-emerald-800">已汇总</span>
        )}
      </div>
      <div className="mt-3 space-y-2">
        {status.tasks.map((task) => {
          const agentId = task.agentId || "agent";
          const agentName = agentNameMap.get(agentId) || "";
          return (
            <div key={task.taskId} className="rounded-md border border-emerald-100 bg-white px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">@{agentId}</span>
                {agentName && agentName !== agentId ? (
                  <span className="text-xs text-emerald-800">{agentName}</span>
                ) : null}
                <span className={`rounded-full px-2 py-0.5 text-xs ${clusterTaskStatusClass(task)}`}>
                  {clusterTaskStatusText(task)}
                </span>
                {task.modelTier ? <span className="text-xs text-emerald-800">{task.modelTier}</span> : null}
              </div>
              {task.error ? (
                <p className="mt-2 whitespace-pre-wrap break-words text-xs text-red-700">{task.error}</p>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

type ChatMessageRowProps = {
  item: ChatMessage;
  messageClientStateKey: string;
  assistantName: string;
  assistantAvatarName?: string;
  userAvatarName?: string;
  allowTrace: boolean;
  deletedAttachmentKeys: Record<string, boolean>;
  deletingAttachmentKeys: Record<string, boolean>;
  tracePanelExpanded: boolean;
  traceLoadState?: { loading: boolean; error?: string };
  onDeleteAttachment: (messageId: string, savedPath: string) => void;
  onFileLinkClick: (href: string) => void;
  onLoadTrace: (messageId: string) => void;
  onToggleTracePanel: (messageClientStateKey: string) => void;
};

const ChatMessageRow = memo(function ChatMessageRow({
  item,
  messageClientStateKey,
  assistantName,
  assistantAvatarName,
  userAvatarName,
  allowTrace,
  deletedAttachmentKeys,
  deletingAttachmentKeys,
  tracePanelExpanded,
  traceLoadState,
  onDeleteAttachment,
  onFileLinkClick,
  onLoadTrace,
  onToggleTracePanel,
}: ChatMessageRowProps) {
  const reduceMotion = useReducedMotion();

  if (item.role === "system") {
    return (
      <div className="flex justify-center">
        <div className="rounded-2xl border border-slate-200 bg-slate-100 px-4 py-2 text-slate-700 whitespace-pre-wrap break-all">
          {item.text}
        </div>
      </div>
    );
  }

  const isUser = item.role === "user";
  const messageName = isUser ? "你" : assistantName;
  const parsedUserMessage = isUser ? parseUserMessageDisplay(item.text) : null;
  const visibleUserText = parsedUserMessage?.visibleText || "";
  const userAttachments = parsedUserMessage?.attachments || [];
  const trace = item.meta?.trace;
  const traceCount = typeof item.meta?.traceCount === "number" ? item.meta.traceCount : trace?.length ?? 0;
  const hasTracePanel = allowTrace && item.role === "assistant" && traceCount > 0;
  const inlineAvatar = (
    <ChatAvatar
      alt={`${messageName} 头像`}
      avatarName={isUser ? userAvatarName : assistantAvatarName}
      kind={isUser ? "user" : "bot"}
      size={24}
    />
  );

  return (
    <motion.div
      className={isUser ? "flex justify-end" : "flex justify-start"}
      {...resolveMotionProps(delightMotion.messagePop, reduceMotion)}
    >
      <div className="min-w-0 max-w-[96%] sm:max-w-[90%]">
        <ChatMessageMeta
          name={messageName}
          createdAt={item.createdAt}
          align={isUser ? "right" : "left"}
          avatar={inlineAvatar}
        />
        <div
          data-streaming={item.state === "streaming" ? "true" : "false"}
          className={[
            "chat-message-bubble-delight",
            isUser
              ? "rounded-2xl bg-[var(--accent)] px-4 py-2 text-[var(--accent-foreground)]"
              : item.state === "error"
                ? "rounded-2xl border border-red-200 bg-red-50 px-4 py-2 text-red-700"
                : "min-w-0 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-[var(--text)]",
          ].join(" ")}
        >
          {item.role === "assistant" && item.state !== "streaming" && item.state !== "error" ? (
            <ChatMarkdownMessage content={item.text} onFileLinkClick={onFileLinkClick} />
          ) : isUser ? (
            <div className={userAttachments.length > 0 && visibleUserText ? "space-y-2" : undefined}>
              {visibleUserText ? (
                <ChatPlainTextMessage content={visibleUserText} className="text-[var(--accent-foreground)]" />
              ) : null}
              {userAttachments.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {userAttachments.map((attachment) => {
                    const attachmentStateKey = getRenderedAttachmentStateKey(item.id, attachment.savedPath);
                    const isDeleted = Boolean(deletedAttachmentKeys[attachmentStateKey]);
                    const isDeleting = Boolean(deletingAttachmentKeys[attachmentStateKey]);

                    return (
                      <span
                        key={attachment.savedPath}
                        title={attachment.savedPath}
                        className={isDeleted
                          ? "inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--accent-foreground)]/20 bg-[var(--accent-foreground)]/10 px-3 py-1 text-xs text-[var(--accent-foreground)]/70"
                          : "inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--accent-foreground)]/25 bg-[var(--accent-foreground)]/10 px-3 py-1 text-xs text-[var(--accent-foreground)]"}
                      >
                        <Paperclip className="h-3.5 w-3.5 shrink-0" />
                        <span className="truncate">{attachment.filename}</span>
                        {isDeleted ? (
                          <span className="rounded-full bg-[var(--accent-foreground)]/10 px-1.5 py-0.5 text-[10px] text-[var(--accent-foreground)]/80">已删除</span>
                        ) : (
                          <button
                            type="button"
                            aria-label={`删除附件文件 ${attachment.filename}`}
                            disabled={isDeleting}
                            onClick={() => onDeleteAttachment(item.id, attachment.savedPath)}
                            className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[var(--accent-foreground)]/80 hover:bg-[var(--accent-foreground)]/15 disabled:opacity-60"
                          >
                            {isDeleting ? (
                              <LoaderCircle className="h-3 w-3 animate-spin" />
                            ) : (
                              <Trash2 className="h-3 w-3" />
                            )}
                          </button>
                        )}
                      </span>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ) : (
            <ChatPlainTextMessage
              content={item.text || (item.state === "streaming" ? "正在输出..." : "")}
              className={isUser ? "text-[var(--accent-foreground)]" : item.state === "error" ? "text-red-700" : "text-[var(--text)]"}
            />
          )}
        </div>
        {item.role === "assistant" && item.state === "streaming" ? (
          <div className="mt-2 inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs text-amber-700">
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            <span>正在输出</span>
          </div>
        ) : null}
        {hasTracePanel ? (
          <ChatTracePanel
            messageId={item.id}
            trace={trace}
            traceCount={traceCount}
            toolCallCount={item.meta?.toolCallCount}
            processCount={item.meta?.processCount}
            expanded={tracePanelExpanded}
            onToggleExpanded={() => onToggleTracePanel(messageClientStateKey)}
            isLoading={Boolean(traceLoadState?.loading)}
            loadError={traceLoadState?.error}
            onLoadTrace={() => void onLoadTrace(item.id)}
          />
        ) : null}
      </div>
    </motion.div>
  );
});

export function ChatScreen({
  botAlias,
  client = new MockWebBotClient(),
  botAvatarName,
  userAvatarName,
  readOnly = false,
  allowTrace = true,
  isVisible = true,
  isImmersive = false,
  embedded = false,
  focused = false,
  onToggleFocus,
  onToggleImmersive,
  onUnreadResult,
  onBotActivityChange,
  onWorkbenchStatusChange,
  onRequestDesktopPreview,
}: Props) {
  const [items, setItems] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamMode, setStreamMode] = useState<"" | "sse" | "poll">("");
  const [streamStartedAtMs, setStreamStartedAtMs] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [workingDir, setWorkingDir] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [actionLoading, setActionLoading] = useState<"" | "kill">("");
  const [cliParams, setCliParams] = useState<CliParamsPayload | null>(null);
  const [modelSaving, setModelSaving] = useState(false);
  const [pendingAttachments, setPendingAttachments] = useState<PendingChatAttachment[]>([]);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);
  const [previewName, setPreviewName] = useState("");
  const [previewContent, setPreviewContent] = useState("");
  const [previewMode, setPreviewMode] = useState<"preview" | "full">("preview");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewResult, setPreviewResult] = useState<FileReadResult | null>(null);
  const [botOverview, setBotOverview] = useState<BotOverview | null>(null);
  const [pendingCronRuns, setPendingCronRuns] = useState<AssistantCronRunEnqueuedDetail[]>([]);
  const [deletedAttachmentKeys, setDeletedAttachmentKeys] = useState<Record<string, boolean>>({});
  const [deletingAttachmentKeys, setDeletingAttachmentKeys] = useState<Record<string, boolean>>({});
  const [expandedTracePanels, setExpandedTracePanels] = useState<Record<string, boolean>>({});
  const [traceLoadState, setTraceLoadState] = useState<Record<string, { loading: boolean; error?: string }>>({});
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false);
  const [conversationQuery, setConversationQuery] = useState("");
  const [conversationLoading, setConversationLoading] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [agents, setAgents] = useState<AgentSummary[]>(fallbackAgents());
  const [activeAgentId, setActiveAgentId] = useState(() => readStoredAgentId(botAlias));
  const [clusterRunId, setClusterRunId] = useState("");
  const [clusterTaskStatus, setClusterTaskStatus] = useState<ClusterTaskStatus | null>(null);
  const [clusterTaskError, setClusterTaskError] = useState("");
  const [clusterSaving, setClusterSaving] = useState(false);
  const [composerPulseKey, setComposerPulseKey] = useState(0);
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null);
  const scrollContainerRef = useRef<HTMLElement | null>(null);
  const scrollContentRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const forceAutoScrollRef = useRef(true);
  const isVisibleRef = useRef(isVisible);
  const loadingRef = useRef(loading);
  const isStreamingRef = useRef(isStreaming);
  const streamModeRef = useRef(streamMode);
  const itemsRef = useRef<ChatMessage[]>([]);
  const traceLoadStateRef = useRef<Record<string, { loading: boolean; error?: string }>>({});
  const workingDirRef = useRef("");
  const botOverviewRef = useRef<BotOverview | null>(null);
  const pendingCronRunsRef = useRef<AssistantCronRunEnqueuedDetail[]>([]);
  const agentsRef = useRef<AgentSummary[]>(fallbackAgents());
  const activeAgentIdRef = useRef(activeAgentId);
  const assistantPollTimerRef = useRef<number | null>(null);
  const sseRecoveryTimerRef = useRef<number | null>(null);
  const sseLastActivityAtRef = useRef<number | null>(null);
  const pollAssistantStateRef = useRef<(() => Promise<void>) | null>(null);
  const clusterTaskPollTimerRef = useRef<number | null>(null);
  const clusterRunIdRef = useRef("");
  const assistantSendVersionRef = useRef(0);
  const hasActivatedRef = useRef(false);
  const activationTargetRef = useRef<{ botAlias: string; client: WebBotClient } | null>(null);
  const isSseStreaming = () => streamModeRef.current === "sse";

  useEffect(() => {
    isVisibleRef.current = isVisible;
  }, [isVisible]);

  useEffect(() => {
    setHistoryPanelOpen(false);
    setConversationQuery("");
    setConversations([]);
    if (clusterTaskPollTimerRef.current !== null) {
      window.clearTimeout(clusterTaskPollTimerRef.current);
      clusterTaskPollTimerRef.current = null;
    }
    setClusterRunId("");
    setClusterTaskStatus(null);
    setClusterTaskError("");
    clusterRunIdRef.current = "";
    const storedAgentId = readStoredAgentId(botAlias);
    setActiveAgentId(storedAgentId);
    activeAgentIdRef.current = storedAgentId;
  }, [botAlias]);

  useEffect(() => {
    loadingRef.current = loading;
  }, [loading]);

  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  useEffect(() => {
    streamModeRef.current = streamMode;
  }, [streamMode]);

  useEffect(() => () => {
    if (clusterTaskPollTimerRef.current !== null) {
      window.clearTimeout(clusterTaskPollTimerRef.current);
      clusterTaskPollTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  useEffect(() => {
    traceLoadStateRef.current = traceLoadState;
  }, [traceLoadState]);

  useEffect(() => {
    workingDirRef.current = workingDir;
  }, [workingDir]);

  useEffect(() => {
    botOverviewRef.current = botOverview;
  }, [botOverview]);

  useEffect(() => {
    pendingCronRunsRef.current = pendingCronRuns;
  }, [pendingCronRuns]);

  useEffect(() => {
    agentsRef.current = agents;
  }, [agents]);

  useEffect(() => {
    activeAgentIdRef.current = activeAgentId;
  }, [activeAgentId]);

  useEffect(() => {
    clusterRunIdRef.current = clusterRunId;
  }, [clusterRunId]);

  useEffect(() => {
    let active = true;
    setCliParams(null);

    void client.getCliParams(botAlias)
      .then((payload) => {
        if (active) {
          setCliParams(payload);
        }
      })
      .catch(() => {
        if (active) {
          setCliParams(null);
        }
      });

    return () => {
      active = false;
    };
  }, [botAlias, client]);

  const applyHistoryView = useCallback((
    messages: ChatMessage[],
    overview: BotOverview,
    pendingRuns: AssistantCronRunEnqueuedDetail[],
  ) => {
    const runtimeActive = Boolean(
      overview.isProcessing
      || pendingRuns.length > 0
      || (overview.assistantRuntime?.pendingCount || 0) > 0
    );
    const nextItems = normalizeInactiveStreamingRows(mergePendingCronRuns(messages, pendingRuns), runtimeActive);
    const hasStreamingRow = runtimeActive
      && nextItems.some((item) => item.role === "assistant" && item.state === "streaming");
    const shouldPoll = Boolean(overview.isProcessing || hasStreamingRow || pendingRuns.length > 0);

    setItems((prev) => mergeMessagesPreservingClientState(prev, nextItems));
    setIsStreaming(shouldPoll);
    setStreamMode(shouldPoll ? "poll" : "");
    if (shouldPoll) {
      setStreamStartedAtMs((prev) => prev ?? resolveStreamStartMs(nextItems));
    } else {
      setStreamStartedAtMs(null);
    }

    return { nextItems, shouldPoll };
  }, []);

  const stopAssistantPoll = useCallback(() => {
    if (assistantPollTimerRef.current !== null) {
      window.clearTimeout(assistantPollTimerRef.current);
      assistantPollTimerRef.current = null;
    }
  }, []);

  const stopSseRecoveryWatch = useCallback(() => {
    if (sseRecoveryTimerRef.current !== null) {
      window.clearTimeout(sseRecoveryTimerRef.current);
      sseRecoveryTimerRef.current = null;
    }
  }, []);

  const stopClusterTaskPoll = useCallback(() => {
    if (clusterTaskPollTimerRef.current !== null) {
      window.clearTimeout(clusterTaskPollTimerRef.current);
      clusterTaskPollTimerRef.current = null;
    }
  }, []);

  const pollClusterTasks = useCallback(async () => {
    const runId = clusterRunIdRef.current;
    if (!runId) {
      return;
    }
    try {
      const status = await client.getClusterTaskStatus(botAlias, runId);
      if (clusterRunIdRef.current !== runId) {
        return;
      }
      setClusterTaskStatus(status);
      setClusterTaskError("");
      if (status.pendingCount > 0 || isSseStreaming()) {
        stopClusterTaskPoll();
        clusterTaskPollTimerRef.current = window.setTimeout(() => {
          clusterTaskPollTimerRef.current = null;
          void pollClusterTasks();
        }, CLUSTER_TASK_POLL_INTERVAL_MS);
      }
    } catch (err) {
      if (clusterRunIdRef.current !== runId) {
        return;
      }
      setClusterTaskError(err instanceof Error ? err.message : "集群任务状态获取失败");
    }
  }, [botAlias, client, stopClusterTaskPoll]);

  const restoreClusterRunFromOverview = useCallback((overview: BotOverview) => {
    const activeRun = overview.activeClusterRun;
    if (!activeRun?.runId || activeAgentIdRef.current !== "main") {
      return;
    }
    if (clusterRunIdRef.current !== activeRun.runId) {
      clusterRunIdRef.current = activeRun.runId;
      setClusterRunId(activeRun.runId);
    }
    if (activeRun.tasks) {
      setClusterTaskStatus(activeRun.tasks);
    }
    setClusterTaskError("");
    void pollClusterTasks();
  }, [pollClusterTasks]);

  const scheduleAssistantPoll = useCallback((delayMs = ACTIVE_ASSISTANT_POLL_INTERVAL_MS) => {
    stopAssistantPoll();
    assistantPollTimerRef.current = window.setTimeout(() => {
      assistantPollTimerRef.current = null;
      void pollAssistantStateRef.current?.();
    }, delayMs);
  }, [stopAssistantPoll]);

  const scheduleSseRecoveryWatch = useCallback(() => {
    stopSseRecoveryWatch();
    if (!isSseStreaming() || !isVisibleRef.current) {
      return;
    }

    const lastActivityAt = sseLastActivityAtRef.current ?? Date.now();
    const delayMs = Math.max(200, SSE_STALL_RECOVERY_DELAY_MS - (Date.now() - lastActivityAt));
    sseRecoveryTimerRef.current = window.setTimeout(() => {
      sseRecoveryTimerRef.current = null;
      const sendVersion = assistantSendVersionRef.current;

      void (async () => {
        if (!isSseStreaming() || !isVisibleRef.current) {
          return;
        }

        try {
          const agentId = activeAgentIdRef.current;
          const overview = await getScopedOverview(client, botAlias, agentId);
          if (sendVersion !== assistantSendVersionRef.current || !isSseStreaming()) {
            return;
          }

          setBotOverview(overview);
          setWorkingDir(overview.workingDir || "");
          restoreClusterRunFromOverview(overview);
          const runtimePendingCount = overview.assistantRuntime?.pendingCount || 0;

          if (overview.isProcessing || runtimePendingCount > 0) {
            sseLastActivityAtRef.current = Date.now();
            scheduleSseRecoveryWatch();
            return;
          }

          const messages = await listScopedMessages(client, botAlias, agentId);
          if (sendVersion !== assistantSendVersionRef.current || !isSseStreaming()) {
            return;
          }

          const refreshedPendingRuns = resolvePendingCronRuns(
            pendingCronRunsRef.current,
            messages,
          );
          if (refreshedPendingRuns.length !== pendingCronRunsRef.current.length) {
            setPendingCronRuns(refreshedPendingRuns);
          }
          assistantSendVersionRef.current += 1;
          applyHistoryView(messages, overview, refreshedPendingRuns);
        } catch {
          sseLastActivityAtRef.current = Date.now();
          scheduleSseRecoveryWatch();
        }
      })();
    }, delayMs);
  }, [applyHistoryView, botAlias, client, restoreClusterRunFromOverview, stopSseRecoveryWatch]);

  const markSseActivity = useCallback(() => {
    sseLastActivityAtRef.current = Date.now();
    if (isSseStreaming()) {
      scheduleSseRecoveryWatch();
    }
  }, [scheduleSseRecoveryWatch]);

  pollAssistantStateRef.current = async () => {
    const sendVersion = assistantSendVersionRef.current;
    if (isSseStreaming()) {
      return;
    }

    try {
      const agentId = activeAgentIdRef.current;
      const overview = await getScopedOverview(client, botAlias, agentId);
      if (sendVersion !== assistantSendVersionRef.current || isSseStreaming()) {
        return;
      }

      setBotOverview(overview);
      setWorkingDir(overview.workingDir || "");
      restoreClusterRunFromOverview(overview);
      const previousItems = itemsRef.current.filter((item) => !item.id.startsWith("assistant-cron-"));
      const previousCount = countPersistedHistoryItems(itemsRef.current);
      const hasStreamingAssistant = hasPersistedStreamingAssistant(previousItems);

      const nextPendingRuns = resolvePendingCronRuns(
        pendingCronRunsRef.current,
        itemsRef.current,
      );
      if (nextPendingRuns.length !== pendingCronRunsRef.current.length) {
        setPendingCronRuns(nextPendingRuns);
      }

      const shouldRefreshMessages = Boolean(
        overview.isProcessing
        || (overview.assistantRuntime?.pendingCount || 0) > 0
        || overview.runningReply
        || nextPendingRuns.length > 0
        || hasStreamingAssistant
        || (typeof overview.historyCount === "number" && overview.historyCount !== previousCount),
      );

      let messages = previousItems;
      if (shouldRefreshMessages) {
        const afterId = previousItems[previousItems.length - 1]?.id || "";
        if (hasStreamingAssistant) {
          messages = await listScopedMessages(client, botAlias, agentId);
        } else if (afterId) {
          const delta = await listScopedMessageDelta(client, botAlias, afterId, 50, agentId);
          messages = delta.reset ? delta.items : [...previousItems, ...delta.items];
        } else {
          messages = await listScopedMessages(client, botAlias, agentId);
        }
      }
      if (sendVersion !== assistantSendVersionRef.current || isSseStreaming()) {
        return;
      }

      const refreshedPendingRuns = resolvePendingCronRuns(nextPendingRuns, messages);
      if (refreshedPendingRuns.length !== nextPendingRuns.length) {
        setPendingCronRuns(refreshedPendingRuns);
      }

      const { nextItems, shouldPoll } = applyHistoryView(messages, overview, refreshedPendingRuns);
      if (!isVisibleRef.current && !shouldPoll && nextItems.length > previousCount) {
        onUnreadResult?.(botAlias);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "恢复任务状态失败");
      setIsStreaming(false);
      setStreamMode("");
      setStreamStartedAtMs(null);
    } finally {
      const shouldContinue = isVisibleRef.current && (
        streamModeRef.current === "poll"
        || (Boolean(botOverviewRef.current?.botMode) && botOverviewRef.current?.botMode === "assistant" && !loadingRef.current && !isStreamingRef.current)
      );
      if (shouldContinue) {
        const nextDelay = streamModeRef.current === "poll" || botOverviewRef.current?.isProcessing
          ? ACTIVE_ASSISTANT_POLL_INTERVAL_MS
          : IDLE_ASSISTANT_POLL_INTERVAL_MS;
        scheduleAssistantPoll(nextDelay);
      } else {
        stopAssistantPoll();
      }
    }
  };

  function appendSystemMessage(text: string) {
    setItems((prev) => [
      ...prev,
      {
        id: `system-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        role: "system",
        text,
        createdAt: new Date().toISOString(),
        state: "done",
      },
    ]);
  }

  useEffect(() => {
    const activatedTarget = activationTargetRef.current;
    if (!activatedTarget || activatedTarget.botAlias !== botAlias || activatedTarget.client !== client) {
      activationTargetRef.current = { botAlias, client };
      hasActivatedRef.current = false;
    }
    if (!isVisible && !hasActivatedRef.current) {
      return;
    }
    if (hasActivatedRef.current) {
      return;
    }
    hasActivatedRef.current = true;

    let cancelled = false;
    setLoading(true);
    setError("");
    setItems([]);
    setWorkingDir("");
    setIsStreaming(false);
    setStreamMode("");
    setStreamStartedAtMs(null);
    setPreviewName("");
    setPreviewContent("");
    setPreviewResult(null);
    setBotOverview(null);
    setPendingCronRuns([]);
    setPendingAttachments([]);
    setUploadingAttachments(false);
    setDeletedAttachmentKeys({});
    setDeletingAttachmentKeys({});
    setExpandedTracePanels({});
    setTraceLoadState({});
    sseLastActivityAtRef.current = null;
    stopSseRecoveryWatch();
    shouldStickToBottomRef.current = true;
    forceAutoScrollRef.current = true;

    const requestedAgentId = activeAgentIdRef.current || "main";
    const loadAgents = typeof client.listAgents === "function"
      ? client.listAgents(botAlias).catch(() => ({ items: fallbackAgents() }))
      : Promise.resolve({ items: fallbackAgents() });

    Promise.all([
      loadAgents,
      listScopedMessages(client, botAlias, requestedAgentId),
      getScopedOverview(client, botAlias, requestedAgentId),
    ])
      .then(async ([agentData, initialMessages, initialOverview]) => {
        if (cancelled) return;
        const nextAgents = agentData.items.length > 0 ? agentData.items : fallbackAgents();
        const nextAgentId = nextAgents.some((agent) => agent.id === requestedAgentId) ? requestedAgentId : "main";
        let messages = initialMessages;
        let overview = initialOverview;
        if (nextAgentId !== requestedAgentId) {
          setActiveAgentId(nextAgentId);
          activeAgentIdRef.current = nextAgentId;
          window.localStorage.setItem(activeAgentStorageKey(botAlias), nextAgentId);
          [messages, overview] = await Promise.all([
            listScopedMessages(client, botAlias, nextAgentId),
            getScopedOverview(client, botAlias, nextAgentId),
          ]);
          if (cancelled || activeAgentIdRef.current !== nextAgentId) {
            return;
          }
        }
        setAgents(nextAgents);
        setBotOverview(overview);
        setWorkingDir(overview.workingDir || "");
        restoreClusterRunFromOverview(overview);
        applyHistoryView(messages, overview, []);
        setLoading(false);
        if (isVisibleRef.current && (overview.isProcessing || overview.botMode === "assistant")) {
          scheduleAssistantPoll(
            overview.isProcessing ? ACTIVE_ASSISTANT_POLL_INTERVAL_MS : IDLE_ASSISTANT_POLL_INTERVAL_MS,
          );
        } else {
          stopAssistantPoll();
        }
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || "加载历史失败");
        setLoading(false);
      });

    return () => {
      cancelled = true;
      stopAssistantPoll();
      stopSseRecoveryWatch();
    };
  }, [
    applyHistoryView,
    botAlias,
    client,
    isVisible,
    restoreClusterRunFromOverview,
    scheduleAssistantPoll,
    stopAssistantPoll,
    stopSseRecoveryWatch,
  ]);

  useEffect(() => {
    const handleAssistantCronRunEnqueued = (event: Event) => {
      if (!isAssistantCronRunEnqueuedEvent(event)) {
        return;
      }

      const detail = event.detail;
      if (!detail || detail.botAlias !== botAlias) {
        return;
      }

      setError("");
      forceAutoScrollRef.current = true;
      shouldStickToBottomRef.current = true;
      setPendingCronRuns((prev) => {
        if (prev.some((item) => item.runId === detail.runId)) {
          return prev;
        }
        return [...prev, detail];
      });
      const nextItems = mergePendingCronRuns(itemsRef.current, [detail]);
      setItems(nextItems);
      setIsStreaming(true);
      setStreamMode("poll");
      setStreamStartedAtMs(resolveStreamStartMs(nextItems));
      scheduleAssistantPoll();
    };

    window.addEventListener(ASSISTANT_CRON_RUN_ENQUEUED_EVENT, handleAssistantCronRunEnqueued);
    return () => {
      window.removeEventListener(ASSISTANT_CRON_RUN_ENQUEUED_EVENT, handleAssistantCronRunEnqueued);
    };
  }, [botAlias, scheduleAssistantPoll]);

  useEffect(() => {
    if (!isStreaming || !streamStartedAtMs) {
      setElapsedSeconds(0);
      return;
    }

    const updateElapsed = () => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - streamStartedAtMs) / 1000)));
    };
    updateElapsed();
    const timer = window.setInterval(() => {
      updateElapsed();
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [isStreaming, streamStartedAtMs]);

  const isAssistantBot = botOverview?.botMode === "assistant";
  const assistantRuntime = botOverview?.assistantRuntime || null;
  const assistantRuntimeActive = assistantRuntime?.active || null;
  const assistantRuntimeQueuedCount = assistantRuntime?.queuedCount || 0;
  const assistantRuntimeQueueLabels = (assistantRuntime?.queue || []).slice(0, 2).map(assistantRuntimeRunLabel);
  const showAssistantRuntimeBanner = Boolean(
    isAssistantBot
    && assistantRuntime
    && (
      assistantRuntimeQueuedCount > 0
      || (assistantRuntimeActive && !assistantRuntimeActive.interactive)
    ),
  );
  let assistantRuntimeHeadline = "";
  if (assistantRuntimeActive && assistantRuntimeQueuedCount > 0) {
    assistantRuntimeHeadline = `assistant 串行队列忙碌中：1 项执行，${assistantRuntimeQueuedCount} 项排队`;
  } else if (assistantRuntimeActive && !assistantRuntimeActive.interactive) {
    assistantRuntimeHeadline = "assistant 后台任务执行中，新消息会等待当前任务完成";
  } else if (assistantRuntimeQueuedCount > 0) {
    assistantRuntimeHeadline = `assistant 队列中 ${assistantRuntimeQueuedCount} 项，新消息会按顺序执行`;
  }
  const assistantRuntimeActiveLabel = assistantRuntimeActive ? assistantRuntimeRunLabel(assistantRuntimeActive) : "";

  useEffect(() => {
    onWorkbenchStatusChange?.({
      state: error ? "error" : isStreaming ? "running" : loading ? "waiting" : "idle",
      processing: isStreaming,
      elapsedSeconds: isStreaming ? elapsedSeconds : undefined,
      lastError: error || undefined,
    });
  }, [elapsedSeconds, error, isStreaming, loading, onWorkbenchStatusChange]);

  useEffect(() => {
    if (streamMode !== "sse" || !isVisible) {
      stopSseRecoveryWatch();
      return;
    }
    scheduleSseRecoveryWatch();
    return () => {
      stopSseRecoveryWatch();
    };
  }, [isVisible, scheduleSseRecoveryWatch, stopSseRecoveryWatch, streamMode]);

  useLayoutEffect(() => {
    const shouldPoll = streamMode === "poll" || (Boolean(isAssistantBot) && isVisible && !loading && !isStreaming);
    if (!shouldPoll) {
      stopAssistantPoll();
      return;
    }
    scheduleAssistantPoll(streamMode === "poll" ? ACTIVE_ASSISTANT_POLL_INTERVAL_MS : IDLE_ASSISTANT_POLL_INTERVAL_MS);
  }, [isAssistantBot, isStreaming, isVisible, loading, scheduleAssistantPoll, stopAssistantPoll, streamMode]);

  const lastItem = items[items.length - 1];

  const scrollToBottom = useCallback(() => {
    if (scrollContainerRef.current) {
      try {
        scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
      } catch {
        // Tests may replace scrollTop with a getter-only descriptor; browsers keep this writable.
      }
    }
    if (bottomAnchorRef.current && typeof bottomAnchorRef.current.scrollIntoView === "function") {
      bottomAnchorRef.current.scrollIntoView({ block: "end" });
    }
  }, []);

  useEffect(() => {
    if (!isVisible) {
      return;
    }
    shouldStickToBottomRef.current = true;
    forceAutoScrollRef.current = true;
  }, [isVisible]);

  useEffect(() => {
    if (!isVisible || loading) {
      return;
    }
    if (!forceAutoScrollRef.current && !shouldStickToBottomRef.current) {
      return;
    }
    scrollToBottom();
    forceAutoScrollRef.current = false;
  }, [isVisible, isStreaming, lastItem?.id, lastItem?.state, lastItem?.text, loading, items.length, scrollToBottom]);

  useEffect(() => {
    if (!isVisible || loading || typeof window.ResizeObserver !== "function") {
      return;
    }
    const content = scrollContentRef.current;
    if (!content) {
      return;
    }

    const observer = new window.ResizeObserver(() => {
      if (!forceAutoScrollRef.current && !shouldStickToBottomRef.current) {
        return;
      }
      scrollToBottom();
      forceAutoScrollRef.current = false;
    });
    observer.observe(content);
    return () => {
      observer.disconnect();
    };
  }, [isVisible, loading, scrollToBottom]);

  function updateAutoScrollStickiness() {
    const container = scrollContainerRef.current;
    if (!container) {
      return;
    }
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldStickToBottomRef.current = distanceFromBottom <= 96;
  }

  const loadPreview = useCallback(async (name: string, mode: "preview" | "full") => {
    setPreviewLoading(true);
    setError("");
    try {
      const result = mode === "full"
        ? await client.readFileFull(botAlias, name)
        : await client.readFile(botAlias, name);
      setPreviewName(name);
      setPreviewMode(result.mode === "cat" ? "full" : "preview");
      setPreviewResult(result);
      setPreviewContent(result.previewKind === "image" ? "" : result.content || "文件为空");
    } catch (err) {
      setError(err instanceof Error ? err.message : mode === "full" ? "读取全文失败" : "预览文件失败");
    } finally {
      setPreviewLoading(false);
    }
  }, [botAlias, client]);

  const previewStatusText = getFilePreviewStatusText(previewResult);
  const canLoadFull = !isFilePreviewFullyLoaded(previewResult) && !isFilePreviewTooLarge(previewResult);
  const shouldUseInlinePreview = !(embedded && onRequestDesktopPreview);

  const handleFileLinkClick = useCallback((href: string) => {
    const nextPath = resolvePreviewFilePath(href, workingDirRef.current);
    if (!nextPath) {
      setError("暂不支持预览该文件链接");
      return;
    }
    if (embedded && onRequestDesktopPreview) {
      onRequestDesktopPreview(nextPath);
      return;
    }
    void loadPreview(nextPath, "preview");
  }, [embedded, loadPreview, onRequestDesktopPreview]);

  const handleToggleTracePanel = useCallback((messageClientStateKey: string) => {
    setExpandedTracePanels((prev) => {
      const nextExpanded = !prev[messageClientStateKey];
      if (nextExpanded) {
        return {
          ...prev,
          [messageClientStateKey]: true,
        };
      }

      if (!prev[messageClientStateKey]) {
        return prev;
      }

      const nextState = { ...prev };
      delete nextState[messageClientStateKey];
      return nextState;
    });
  }, []);

  const loadMessageTrace = useCallback(async (messageId: string) => {
    const currentMessage = itemsRef.current.find((item) => item.id === messageId);
    if (!currentMessage || currentMessage.role !== "assistant") {
      return;
    }
    const messageClientStateKey = getMessageClientStateKey(currentMessage);
    const loadedTraceCount = (currentMessage.meta?.trace || []).length;
    const expectedTraceCount = currentMessage.meta?.traceCount || 0;
    if (expectedTraceCount > 0 && loadedTraceCount >= expectedTraceCount) {
      return;
    }
    if ((traceLoadStateRef.current[messageClientStateKey]?.loading)) {
      return;
    }
    if (!(currentMessage.meta?.traceCount || 0)) {
      return;
    }

    setTraceLoadState((prev) => ({
      ...prev,
      [messageClientStateKey]: {
        loading: true,
      },
    }));

    try {
      const traceDetails = await getScopedMessageTrace(client, botAlias, messageId, activeAgentIdRef.current);
      setItems((prev) => updateMessageByIdOrClientStateKey(prev, messageId, messageClientStateKey, (item) => ({
        ...item,
        meta: mergeMessageMeta(item.meta, {
          trace: traceDetails.trace,
          traceCount: traceDetails.traceCount,
          toolCallCount: traceDetails.toolCallCount,
          processCount: traceDetails.processCount,
          traceVersion: 1,
        }),
      })));
      setTraceLoadState((prev) => ({
        ...prev,
        [messageClientStateKey]: {
          loading: false,
        },
      }));
    } catch (err) {
      setTraceLoadState((prev) => ({
        ...prev,
        [messageClientStateKey]: {
          loading: false,
          error: err instanceof Error ? err.message : "加载过程详情失败",
        },
      }));
    }
  }, [botAlias, client]);

  const loadConversations = useCallback(async (query = "") => {
    setConversationLoading(true);
    setError("");
    try {
      const data = await listScopedConversations(client, botAlias, query, activeAgentIdRef.current);
      setConversations(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载历史会话失败");
    } finally {
      setConversationLoading(false);
    }
  }, [botAlias, client]);

  async function handleOpenHistoryPanel() {
    setHistoryPanelOpen(true);
    await loadConversations(conversationQuery);
  }

  async function handleSelectConversation(conversationId: string) {
    if (isStreaming) {
      setError("当前任务运行中，先终止或等待完成");
      return;
    }
    setConversationLoading(true);
    setError("");
    try {
      const data = await selectScopedConversation(client, botAlias, conversationId, activeAgentIdRef.current);
      stopAssistantPoll();
      stopSseRecoveryWatch();
      stopClusterTaskPoll();
      setClusterRunId("");
      setClusterTaskStatus(null);
      setClusterTaskError("");
      clusterRunIdRef.current = "";
      setExpandedTracePanels({});
      setTraceLoadState({});
      setItems(data.messages);
      setConversations((prev) => prev.map((item) => ({ ...item, active: item.id === conversationId })));
      setHistoryPanelOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换会话失败");
    } finally {
      setConversationLoading(false);
    }
  }

  async function handleNewConversation() {
    if (isStreaming) {
      setError("当前任务运行中，先终止或等待完成");
      return;
    }
    if (botOverview?.cluster?.enabled && activeAgentIdRef.current !== "main") {
      setError("子 agent 仅支持查看历史，请切回主 agent 后继续");
      return;
    }
    setConversationLoading(true);
    setError("");
    try {
      const data = await createScopedConversation(client, botAlias, activeAgentIdRef.current);
      stopAssistantPoll();
      stopSseRecoveryWatch();
      stopClusterTaskPoll();
      setClusterRunId("");
      setClusterTaskStatus(null);
      setClusterTaskError("");
      clusterRunIdRef.current = "";
      setExpandedTracePanels({});
      setTraceLoadState({});
      setItems(data.messages);
      setConversations((prev) => [data.conversation, ...prev.map((item) => ({ ...item, active: false }))]);
      setHistoryPanelOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建会话失败");
    } finally {
      setConversationLoading(false);
    }
  }

  const handleSelectAgent = useCallback((agentId: string) => {
    const normalized = agentId || "main";
    activeAgentIdRef.current = normalized;
    setActiveAgentId(normalized);
    window.localStorage.setItem(activeAgentStorageKey(botAlias), normalized);
    assistantSendVersionRef.current += 1;
    stopAssistantPoll();
    stopSseRecoveryWatch();
    stopClusterTaskPoll();
    setLoading(true);
    setError("");
    setItems([]);
    setClusterRunId("");
    setClusterTaskStatus(null);
    setClusterTaskError("");
    clusterRunIdRef.current = "";
    setConversations([]);
    setExpandedTracePanels({});
    setTraceLoadState({});
    setPendingAttachments([]);
    setHistoryPanelOpen(false);
    setIsStreaming(false);
    setStreamMode("");
    setStreamStartedAtMs(null);

    Promise.all([
      listScopedMessages(client, botAlias, normalized),
      getScopedOverview(client, botAlias, normalized),
    ])
      .then(([messages, overview]) => {
        if (activeAgentIdRef.current !== normalized) {
          return;
        }
        setBotOverview(overview);
        setWorkingDir(overview.workingDir || "");
        restoreClusterRunFromOverview(overview);
        if (overview.agents && overview.agents.length > 0) {
          setAgents(overview.agents);
        }
        applyHistoryView(messages, overview, []);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (activeAgentIdRef.current !== normalized) {
          return;
        }
        setError(err.message || "切换 agent 失败");
        setLoading(false);
      });
  }, [applyHistoryView, botAlias, client, restoreClusterRunFromOverview, stopAssistantPoll, stopClusterTaskPoll, stopSseRecoveryWatch]);

  const handleAttachFiles = useCallback(async (files: File[]) => {
    if (files.length === 0) {
      return;
    }

    setError("");
    setUploadingAttachments(true);
    try {
      const uploadedAttachments: PendingChatAttachment[] = [];
      for (const file of files) {
        const uploaded = await client.uploadChatAttachment(botAlias, file);
        uploadedAttachments.push({
          ...uploaded,
          id: `${uploaded.savedPath}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        });
      }
      setPendingAttachments((prev) => [...prev, ...uploadedAttachments]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传附件失败");
    } finally {
      setUploadingAttachments(false);
    }
  }, [botAlias, client]);

  const handleRemoveAttachment = useCallback((attachmentId: string) => {
    const removedAttachment = pendingAttachments.find((attachment) => attachment.id === attachmentId);
    if (!removedAttachment) {
      return;
    }

    setPendingAttachments((prev) => prev.filter((attachment) => attachment.id !== attachmentId));
    setError("");
    void client.deleteChatAttachment(botAlias, removedAttachment.savedPath).catch((err) => {
      setError(err instanceof Error ? err.message : "删除附件失败");
      setPendingAttachments((prev) => (
        prev.some((attachment) => attachment.id === removedAttachment.id)
          ? prev
          : [...prev, removedAttachment]
      ));
    });
  }, [botAlias, client, pendingAttachments]);

  const handleDeleteAttachment = useCallback(async (messageId: string, savedPath: string) => {
    const attachmentStateKey = getRenderedAttachmentStateKey(messageId, savedPath);

    setDeletingAttachmentKeys((prev) => ({
      ...prev,
      [attachmentStateKey]: true,
    }));
    setError("");

    try {
      await client.deleteChatAttachment(botAlias, savedPath);
      setDeletedAttachmentKeys((prev) => ({
        ...prev,
        [attachmentStateKey]: true,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除附件失败");
    } finally {
      setDeletingAttachmentKeys((prev) => {
        if (!prev[attachmentStateKey]) {
          return prev;
        }
        const nextState = { ...prev };
        delete nextState[attachmentStateKey];
        return nextState;
      });
    }
  }, [botAlias, client]);

  const sendMessageInternal = useCallback(async (
    text: string,
    options: {
      attachments?: PendingChatAttachment[];
      clearPendingAttachments?: boolean;
      sendOptions?: ChatSendOptions;
      onSuccess?: (message: ChatMessage) => void;
      onError?: (message: string) => void;
    } = {},
  ) => {
    const composedText = buildComposedMessageText(text, options.attachments || []);
    if (!composedText) {
      return;
    }

    const localStartedAtMs = Date.now();
    assistantSendVersionRef.current += 1;
    const sendVersion = assistantSendVersionRef.current;
    const displayUserText = options.sendOptions?.visibleText || composedText;
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      text: displayUserText,
      createdAt: new Date().toISOString(),
      state: "done",
    };
    const assistantId = `assistant-${Date.now()}`;
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      text: "",
      createdAt: new Date().toISOString(),
      state: "streaming",
    };

    setError("");
    if (options.clearPendingAttachments) {
      setPendingAttachments([]);
    }
    stopAssistantPoll();
    stopSseRecoveryWatch();
    stopClusterTaskPoll();
    setClusterRunId("");
    setClusterTaskStatus(null);
    setClusterTaskError("");
    clusterRunIdRef.current = "";
    forceAutoScrollRef.current = true;
    shouldStickToBottomRef.current = true;
    setItems((prev) => [...prev, userMessage, assistantMessage]);
    setIsStreaming(true);
    setStreamMode("sse");
    setStreamStartedAtMs(localStartedAtMs);
    sseLastActivityAtRef.current = localStartedAtMs;
    emitBotActivityForActiveAgent("busy");

    try {
      let usingPreviewReplace = false;
      let usingTracePreview = false;
      const onChunk = (chunk: string) => {
        if (sendVersion !== assistantSendVersionRef.current) {
          return;
        }
        markSseActivity();
        if (usingPreviewReplace) {
          return;
        }
        setItems((prev) => updateLatestAssistantMessage(prev, assistantId, localStartedAtMs, (item) => ({
          ...item,
          text: item.text + chunk,
          state: "streaming",
        })));
      };
      const onStatus = (status: ChatStatusUpdate) => {
        if (sendVersion !== assistantSendVersionRef.current) {
          return;
        }
        markSseActivity();
        if (typeof status.elapsedSeconds === "number") {
          setStreamStartedAtMs(resolveStreamStartMs(itemsRef.current, status.elapsedSeconds));
        }
        if (status.clusterRunId && status.clusterRunId !== clusterRunIdRef.current) {
          clusterRunIdRef.current = status.clusterRunId;
          setClusterRunId(status.clusterRunId);
          setClusterTaskStatus(null);
          setClusterTaskError("");
          void pollClusterTasks();
        }
        if (status.previewText) {
          usingPreviewReplace = true;
          usingTracePreview = false;
          setItems((prev) => updateLatestAssistantMessage(prev, assistantId, localStartedAtMs, (item) => ({
            ...item,
            text: status.previewText || item.text,
            state: "streaming",
          })));
        }
      };
      const onTrace = (traceEvent: ChatTraceEvent) => {
        if (sendVersion !== assistantSendVersionRef.current) {
          return;
        }
        markSseActivity();
        setItems((prev) => updateLatestAssistantMessage(
          prev,
          assistantId,
          localStartedAtMs,
          (item) => {
            const nextItem = appendTraceToMessage(item, traceEvent);
            const canUseTracePreview = traceEvent.kind === "commentary"
              && Boolean(traceEvent.summary.trim())
              && !usingPreviewReplace
              && (!item.text.trim() || usingTracePreview);
            if (!canUseTracePreview) {
              return nextItem;
            }
            usingTracePreview = true;
            return {
              ...nextItem,
              text: traceEvent.summary,
              state: "streaming",
            };
          },
        ));
      };
      const finalMessage = options.sendOptions
        ? await client.sendMessage(
          botAlias,
          composedText,
          onChunk,
          onStatus,
          onTrace,
          options.sendOptions.cluster || activeAgentIdRef.current === "main"
            ? options.sendOptions
            : { ...options.sendOptions, agentId: activeAgentIdRef.current },
        )
        : (
          activeAgentIdRef.current === "main"
            ? await client.sendMessage(botAlias, composedText, onChunk, onStatus, onTrace)
            : await client.sendMessage(botAlias, composedText, onChunk, onStatus, onTrace, {
              agentId: activeAgentIdRef.current,
            })
        );

      if (sendVersion !== assistantSendVersionRef.current) {
        return;
      }

      const elapsedSeconds = typeof finalMessage.elapsedSeconds === "number"
        ? finalMessage.elapsedSeconds
        : Math.max(0, Math.floor((Date.now() - localStartedAtMs) / 1000));
      const finalizedMessage: ChatMessage = {
        ...finalMessage,
        elapsedSeconds,
      };

      setItems((prev) => updateLatestAssistantMessage(prev, assistantId, localStartedAtMs, (item) => ({
        ...finalizedMessage,
        meta: mergeMessageMeta(item.meta, finalizedMessage.meta),
      })));
      options.onSuccess?.(finalizedMessage);
      if (!isVisibleRef.current) {
        onUnreadResult?.(botAlias);
      }
      if (clusterRunIdRef.current) {
        void pollClusterTasks();
      }
    } catch (err) {
      if (sendVersion !== assistantSendVersionRef.current) {
        return;
      }
      const message = err instanceof Error ? err.message : "发送失败";
      setError(message);
      setItems((prev) => updateLatestAssistantMessage(prev, assistantId, localStartedAtMs, (item) => ({
        ...item,
        text: message,
        state: "error",
      })));
      options.onError?.(message);
    } finally {
      if (sendVersion !== assistantSendVersionRef.current) {
        return;
      }
      stopSseRecoveryWatch();
      sseLastActivityAtRef.current = null;
      setIsStreaming(false);
      setStreamMode("");
      setStreamStartedAtMs(null);
      emitBotActivityForActiveAgent("idle");
    }
  }, [botAlias, client, markSseActivity, onUnreadResult, pollClusterTasks, stopAssistantPoll, stopClusterTaskPoll, stopSseRecoveryWatch]);

  const handleSend = useCallback(async (text: string, mentions: AgentMention[] = []) => {
    const clusterMode = Boolean(botOverview?.cluster?.enabled);
    if (clusterMode && activeAgentIdRef.current !== "main") {
      setError("子 agent 仅支持查看历史，请切回主 agent 后继续");
      return;
    }
    const clusterSend = clusterMode || mentions.length > 0;
    setComposerPulseKey((value) => value + 1);
    await sendMessageInternal(text, {
      attachments: pendingAttachments,
      clearPendingAttachments: true,
      sendOptions: clusterSend ? { cluster: true, mentions } : undefined,
    });
  }, [botOverview?.cluster?.enabled, pendingAttachments, sendMessageInternal]);

  async function handleToggleClusterMode() {
    if (!botOverview?.cluster || clusterSaving) {
      return;
    }

    const current = botOverview.cluster;
    const nextEnabled = !current.enabled;
    setClusterSaving(true);
    setError("");
    try {
      const result = await client.updateClusterConfig(botAlias, {
        enabled: nextEnabled,
        writePolicy: current.writePolicy,
        conflictPolicy: current.conflictPolicy,
        maxParallelAgents: current.maxParallelAgents,
        defaultTimeoutSeconds: current.defaultTimeoutSeconds,
        modelTiers: { ...current.modelTiers },
      });
      setBotOverview((prev) => prev ? { ...prev, cluster: result.cluster } : prev);
      if (!nextEnabled) {
        stopClusterTaskPoll();
        setClusterRunId("");
        setClusterTaskStatus(null);
        setClusterTaskError("");
        clusterRunIdRef.current = "";
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "集群模式切换失败");
    } finally {
      setClusterSaving(false);
    }
  }

  useEffect(() => {
    const handleAssistantProposalPatchRequested = (event: Event) => {
      if (!isAssistantProposalPatchRequestedEvent(event)) {
        return;
      }

      const detail = event.detail;
      if (!detail || detail.botAlias !== botAlias) {
        return;
      }
      if (loadingRef.current || isStreamingRef.current) {
        const message = "聊天正忙，等会再试";
        setError(message);
        dispatchAssistantProposalPatchCompleted({
          botAlias,
          proposalId: detail.proposalId,
          ok: false,
          targetAlias: detail.targetAlias,
          summary: message,
          error: message,
        });
        return;
      }

      void sendMessageInternal(detail.visibleText, {
        sendOptions: {
          taskMode: "proposal_patch",
          taskPayload: {
            proposalId: detail.proposalId,
            targetAlias: detail.targetAlias,
            regenerate: Boolean(detail.regenerate),
          },
          visibleText: detail.visibleText,
        },
        onSuccess: (message) => {
          dispatchAssistantProposalPatchCompleted({
            botAlias,
            proposalId: detail.proposalId,
            ok: true,
            targetAlias: detail.targetAlias,
            summary: message.text,
          });
        },
        onError: (message) => {
          dispatchAssistantProposalPatchCompleted({
            botAlias,
            proposalId: detail.proposalId,
            ok: false,
            targetAlias: detail.targetAlias,
            summary: message,
            error: message,
          });
        },
      });
    };

    window.addEventListener(ASSISTANT_PROPOSAL_PATCH_REQUESTED_EVENT, handleAssistantProposalPatchRequested);
    return () => {
      window.removeEventListener(ASSISTANT_PROPOSAL_PATCH_REQUESTED_EVENT, handleAssistantProposalPatchRequested);
    };
  }, [botAlias, sendMessageInternal]);

  async function handleKillTask() {
    setActionLoading("kill");
    setError("");
    try {
      const message = await client.killTask(botAlias);
      appendSystemMessage(message || "已发送终止任务请求");
    } catch (err) {
      setError(err instanceof Error ? err.message : "终止任务失败");
    } finally {
      setActionLoading("");
    }
  }
  async function handleModelChange(nextModel: string) {
    if (!cliParams || !nextModel || nextModel === selectedModel) {
      return;
    }

    setModelSaving(true);
    setError("");
    try {
      const next = await client.updateCliParam(botAlias, "model", nextModel, cliParams.cliType);
      setCliParams(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "模型切换失败");
    } finally {
      setModelSaving(false);
    }
  }

  const killTaskActive = isStreaming || actionLoading === "kill";
  const assistantName = botAlias;
  const assistantAvatarName = botOverview?.avatarName || botAvatarName;
  const activeAgent = agents.find((agent) => agent.id === activeAgentId) || agents[0] || fallbackAgents()[0];
  const clusterMode = Boolean(botOverview?.cluster?.enabled);
  const activeClusterChildReadOnly = clusterMode && activeAgentId !== "main";
  const chatMutationsDisabled = readOnly || activeClusterChildReadOnly;
  const killTaskDisabled = chatMutationsDisabled || !isStreaming || actionLoading === "kill";
  const clusterAgents = agents.filter((agent) => !agent.isMain && agent.enabled);
  const showAgentSwitcher = agents.length > 1;
  const showClusterToggle = Boolean(botOverview?.cluster) && botOverview?.botMode !== "assistant";
  const showTopChrome = !embedded && !isImmersive;
  const showActionBar = !isImmersive;
  const showImmersiveButton = !embedded && isVisible && Boolean(onToggleImmersive);
  const modelOptions = cliParams?.schema.model?.enum ?? [];
  const selectedModel = toModelOptionValue(cliParams?.params.model, modelOptions);
  const visibleModelOptions = selectedModel && !modelOptions.includes(selectedModel)
    ? [selectedModel, ...modelOptions]
    : modelOptions;

  function emitBotActivityForActiveAgent(activityStatus: "idle" | "busy") {
    const agentId = activeAgentIdRef.current || "main";
    const agent = agentsRef.current.find((item) => item.id === agentId) || activeAgent;
    const agentName = agent.name || agentId;
    onBotActivityChange?.(botAlias, {
      activityStatus,
      agentId,
      agentName,
      busyAgentIds: activityStatus === "busy" ? [agentId] : [],
      busyAgentNames: activityStatus === "busy" ? [agentName] : [],
      busyAgentCount: activityStatus === "busy" ? 1 : 0,
    });
  }

  return (
    <main className="relative flex flex-col h-full">
      {showTopChrome ? (
        <header className="p-4 border-b border-[var(--border)] bg-[var(--surface-strong)]">
          <BotIdentity
            alias={botAlias}
            avatarName={assistantAvatarName}
            size={32}
            nameClassName="truncate text-lg font-semibold text-[var(--text)]"
          />
          {isStreaming ? (
            <div className="mt-2 inline-flex items-center gap-2 rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700">
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              <span>已等待 {elapsedSeconds} 秒</span>
            </div>
          ) : null}
        </header>
      ) : null}
      {showActionBar ? (
        <section className="border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {visibleModelOptions.length > 0 ? (
              <select
                aria-label="模型"
                value={selectedModel}
                disabled={modelSaving || readOnly}
                onChange={(event) => void handleModelChange(event.target.value)}
                className="h-9 shrink-0 rounded-full border border-[var(--border)] bg-[var(--bg)] px-3 text-sm font-medium text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                {visibleModelOptions.map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            ) : null}
            {showAgentSwitcher ? (
              <AgentSwitcher
                agents={agents}
                activeAgentId={activeAgentId}
                disabled={loading}
                onSelect={handleSelectAgent}
              />
            ) : null}
            {showClusterToggle ? (
              <button
                type="button"
                aria-pressed={clusterMode}
                aria-label={clusterMode ? "关闭集群模式" : "开启集群模式"}
                onClick={() => void handleToggleClusterMode()}
                disabled={loading || isStreaming || clusterSaving || readOnly}
                className={clusterMode
                  ? "inline-flex h-9 shrink-0 items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-60"
                  : "inline-flex h-9 shrink-0 items-center gap-2 rounded-full border border-[var(--border)] px-3 text-sm font-medium text-[var(--muted)] hover:bg-[var(--surface-strong)] disabled:opacity-60"}
              >
                {clusterSaving ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Network className="h-4 w-4" />
                )}
                {clusterSaving ? "保存中" : (clusterMode ? "集群开" : "集群关")}
              </button>
            ) : null}
            {embedded && onToggleFocus ? (
              <button
                type="button"
                aria-label={focused ? "退出聚焦聊天" : "聚焦聊天"}
                title={focused ? "退出聚焦聊天" : "聚焦聊天"}
                onClick={onToggleFocus}
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
              >
                {focused ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => void handleOpenHistoryPanel()}
              className="inline-flex shrink-0 items-center gap-2 rounded-full border border-[var(--border)] px-3 py-2 text-sm font-medium hover:bg-[var(--surface-strong)]"
            >
              <History className="h-4 w-4" />
              历史
            </button>
            <button
              type="button"
              onClick={() => void handleNewConversation()}
              disabled={conversationLoading || isStreaming || chatMutationsDisabled}
              className="inline-flex shrink-0 items-center gap-2 rounded-full border border-[var(--border)] px-3 py-2 text-sm font-medium hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              <Plus className="h-4 w-4" />
              {conversationLoading ? "新建中..." : "新会话"}
            </button>
            <button
              type="button"
              onClick={() => void handleKillTask()}
              disabled={killTaskDisabled}
              className={killTaskActive
                ? "inline-flex shrink-0 items-center gap-2 rounded-full border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-60"
                : "inline-flex shrink-0 items-center gap-2 rounded-full border border-[var(--border)] px-3 py-2 text-sm font-medium text-[var(--muted)] disabled:opacity-60"}
            >
              <Square className="h-4 w-4" />
              {actionLoading === "kill" ? "终止中..." : "终止任务"}
            </button>
          </div>
        </section>
      ) : null}
      {showAssistantRuntimeBanner ? (
        <section
          data-workbench-status="active"
          className="chat-runtime-banner border-b border-amber-200 bg-amber-50 px-4 py-3 text-amber-900"
        >
          <div className="flex items-center gap-2 text-sm font-medium">
            <LoaderCircle className="h-4 w-4 animate-spin" />
            <span
              key={assistantRuntimeHeadline}
              data-runtime-status-settle="true"
            >
              {assistantRuntimeHeadline}
            </span>
          </div>
          {assistantRuntimeActiveLabel ? (
            <p className="mt-1 text-xs text-amber-800 break-all">当前：{assistantRuntimeActiveLabel}</p>
          ) : null}
          {assistantRuntimeQueueLabels.length > 0 ? (
            <p className="mt-1 text-xs text-amber-800 break-all">
              排队：{assistantRuntimeQueueLabels.join("；")}
              {assistantRuntimeQueuedCount > assistantRuntimeQueueLabels.length
                ? `；还有 ${assistantRuntimeQueuedCount - assistantRuntimeQueueLabels.length} 项`
                : ""}
            </p>
          ) : null}
        </section>
      ) : null}
      <section
        ref={scrollContainerRef}
        data-testid="chat-scroll-container"
        onScroll={updateAutoScrollStickiness}
        className={isImmersive ? "flex-1 overflow-y-auto px-4 pb-24 pt-4" : "flex-1 overflow-y-auto p-4"}
      >
        <div ref={scrollContentRef} className="space-y-4">
          {loading ? (
            <div className="text-center text-[var(--muted)] mt-10">加载中...</div>
          ) : null}
          {error ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : null}
          {items.length === 0 && !isStreaming && !loading ? (
            <div className="text-center text-[var(--muted)] mt-10">
              暂无消息，开始聊天吧
            </div>
          ) : null}
          {items.map((item) => {
            const messageClientStateKey = getMessageClientStateKey(item);
            return (
              <ChatMessageRow
                key={item.id}
                item={item}
                messageClientStateKey={messageClientStateKey}
                assistantName={assistantName}
                assistantAvatarName={assistantAvatarName}
                userAvatarName={userAvatarName}
                allowTrace={allowTrace}
                deletedAttachmentKeys={deletedAttachmentKeys}
                deletingAttachmentKeys={deletingAttachmentKeys}
                tracePanelExpanded={Boolean(expandedTracePanels[messageClientStateKey])}
                traceLoadState={traceLoadState[messageClientStateKey]}
                onDeleteAttachment={handleDeleteAttachment}
                onFileLinkClick={handleFileLinkClick}
                onLoadTrace={loadMessageTrace}
                onToggleTracePanel={handleToggleTracePanel}
              />
            );
          })}
          {clusterTaskStatus ? (
            <ClusterTaskPanel
              status={clusterTaskStatus}
              agents={botOverview?.agents && botOverview.agents.length > 0 ? botOverview.agents : agents}
            />
          ) : null}
          {clusterTaskError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {clusterTaskError}
            </div>
          ) : null}
          <div ref={bottomAnchorRef} aria-hidden="true" />
        </div>
      </section>
      <ConversationHistoryPanel
        open={historyPanelOpen}
        loading={conversationLoading}
        conversations={conversations}
        query={conversationQuery}
        disabled={isStreaming}
        onQueryChange={(nextQuery) => {
          setConversationQuery(nextQuery);
          void loadConversations(nextQuery);
        }}
        onClose={() => setHistoryPanelOpen(false)}
        onNewConversation={() => void handleNewConversation()}
        onSelectConversation={(conversationId) => void handleSelectConversation(conversationId)}
      />
      {showImmersiveButton ? (
        <button
          type="button"
          onClick={onToggleImmersive}
          aria-label={isImmersive ? "退出沉浸模式" : "进入沉浸模式"}
          className="absolute bottom-20 right-4 z-20 inline-flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] shadow-[var(--shadow-card)] backdrop-blur hover:bg-[var(--surface-strong)]"
        >
          {isImmersive ? <Minimize2 className="h-5 w-5" /> : <Maximize2 className="h-5 w-5" />}
        </button>
      ) : null}
      <div className="border-t border-[var(--border)] bg-[var(--surface)]">
        {chatMutationsDisabled ? (
          <p className="px-4 pt-3 text-xs text-[var(--muted)]">只读模式</p>
        ) : null}
        <ChatComposer
          key={`composer-${composerPulseKey}`}
          onSend={handleSend}
          onAttachFiles={handleAttachFiles}
          onRemoveAttachment={handleRemoveAttachment}
          attachments={pendingAttachments}
          pulse={composerPulseKey > 0}
          agents={clusterAgents}
          clusterMode={clusterMode}
          disabled={chatMutationsDisabled || isStreaming || loading}
          compact={isImmersive || embedded}
          uploadingAttachments={uploadingAttachments}
          placeholder={clusterMode ? "@ 可指定智能体集群" : (showAgentSwitcher ? `发给 ${activeAgent.name}...` : "输入消息")}
        />
      </div>

      {shouldUseInlinePreview && previewName ? (
        <FilePreviewDialog
          title={previewName}
          content={previewContent}
          mode={previewMode}
          botAlias={botAlias}
          previewKind={previewResult?.previewKind}
          contentType={previewResult?.contentType}
          contentBase64={previewResult?.contentBase64}
          loading={previewLoading}
          statusText={previewStatusText}
          onClose={() => {
            setPreviewName("");
            setPreviewContent("");
            setPreviewResult(null);
          }}
          onLoadFull={previewMode !== "full" && canLoadFull ? () => void loadPreview(previewName, "full") : undefined}
          onDownload={() => void client.downloadFile(botAlias, previewName)}
        />
      ) : null}
    </main>
  );
}
