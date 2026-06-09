import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { LoaderCircle, Maximize2, Minimize2, Paperclip, Trash2 } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { ChatAvatar } from "../components/ChatAvatar";
import { ChatActionBar, type ChatModelOption } from "../components/ChatActionBar";
import { ChatComposer } from "../components/ChatComposer";
import { ChatMessageMeta } from "../components/ChatMessageMeta";
import { ChatMarkdownMessage } from "../components/ChatMarkdownMessage";
import { ChatPlainTextMessage } from "../components/ChatPlainTextMessage";
import { ChatTracePanel } from "../components/ChatTracePanel";
import { ConversationHistoryPanel } from "../components/ConversationHistoryPanel";
import { FilePreviewDialog } from "../components/FilePreviewDialog";
import { NativeAgentTranscript } from "../components/NativeAgentTranscript";
import { PlanDraftCard } from "../components/PlanDraftCard";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError } from "../services/types";
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
  ChatExecutionMode,
  ChatSendOptions,
  ChatStatusUpdate,
  CliParamsPayload,
  ChatTraceEvent,
  ConversationSummary,
  FileDownloadProgress,
  FileReadResult,
  PromptPreset,
  NativeAgentModelsPayload,
  NativeAgentModelOption,
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
import { copyText } from "../utils/clipboard";
import {
  getFilePreviewStatusText,
  isFilePreviewFullyLoaded,
  isFilePreviewTooLarge,
  shouldAutoLoadFullHtmlPreview,
  withDetectedPreviewKind,
} from "../utils/filePreview";
import type { BotActivityChange } from "../app/botActivity";
import type { ChatWorkbenchStatus } from "../workbench/workbenchTypes";
import { extractPlanDraft, stripPlanDraftTags } from "../utils/planDraft";
import type { AgUiEvent } from "../services/agUiProtocol";
import {
  buildAgUiMessageMeta,
  createAgUiRunState,
  reduceAgUiRunEvent,
  type AgUiRunState,
} from "../utils/agUiRunReducer";
import {
  buildNativeAgentTranscriptEntries,
  isNativeAgentMessage,
  mergeChatTraceEvents,
} from "../utils/nativeAgentTranscript";

type Props = {
  botAlias: string;
  accountId?: string;
  client?: WebBotClient;
  botAvatarName?: string;
  userAvatarName?: string;
  readOnly?: boolean;
  readOnlyReason?: string;
  disabledReason?: string;
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

type QueuedChatMessage = {
  text: string;
  attachments: PendingChatAttachment[];
  sendOptions?: ChatSendOptions;
};

type ParsedUserAttachment = {
  filename: string;
  savedPath: string;
};

type ChatMessageRowModel = {
  item: ChatMessage;
  messageClientStateKey: string;
  planDraft: string;
  deletedAttachmentKeys: Record<string, boolean>;
  deletingAttachmentKeys: Record<string, boolean>;
};

const EMPTY_ATTACHMENT_STATE: Record<string, boolean> = {};

function formatBytes(value: number) {
  if (value >= 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${value} B`;
}

function formatDownloadProgress(progress: FileDownloadProgress) {
  if (typeof progress.totalBytes === "number" && progress.totalBytes > 0) {
    return `${formatBytes(progress.downloadedBytes)} / ${formatBytes(progress.totalBytes)}`;
  }
  return formatBytes(progress.downloadedBytes);
}

const ACTIVE_ASSISTANT_POLL_INTERVAL_MS = 1000;
const IDLE_ASSISTANT_POLL_INTERVAL_MS = 5000;
const CLUSTER_TASK_POLL_INTERVAL_MS = 1200;
const SSE_STALL_RECOVERY_DELAY_MS = 2500;
const CHAT_ATTACHMENT_LINE_RE = /^附件路径为[:：]\s*(.+?)\s*$/;
const MODEL_OPTION_NONE = "none";
const REVEAL_SCROLL_MAX_FRAMES = 6;
const REVEAL_SCROLL_BOTTOM_THRESHOLD_PX = 8;
const CHAT_RENDER_WINDOW_SIZE = 80;
const USER_SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " ", "Spacebar"]);

function fallbackAgents(): AgentSummary[] {
  return [{ id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true }];
}

function storageScopePrefix(accountId?: string) {
  const normalized = accountId?.trim();
  return normalized ? `${normalized}.` : "";
}

function activeAgentStorageKey(botAlias: string, accountId?: string) {
  return `tcb.activeAgent.${storageScopePrefix(accountId)}${botAlias}`;
}

function planModeStorageKey(botAlias: string, accountId?: string) {
  return `tcb.planMode.${storageScopePrefix(accountId)}${botAlias}`;
}

function executionModeStorageKey(botAlias: string, accountId?: string) {
  return `tcb.executionMode.${storageScopePrefix(accountId)}${botAlias}`;
}

function isPlanExecutionPrompt(text: string) {
  return text.trimStart().startsWith("请按方案执行。方案文件：");
}

function queuedMessageStorageKey(botAlias: string, agentId: string, accountId?: string) {
  return `tcb.queuedMessage.${storageScopePrefix(accountId)}${botAlias}.${agentId || "main"}`;
}

function readStoredAgentId(botAlias: string, accountId?: string) {
  if (typeof window === "undefined") {
    return "main";
  }
  return window.localStorage.getItem(activeAgentStorageKey(botAlias, accountId)) || "main";
}

function readStoredPlanMode(botAlias: string, accountId?: string) {
  if (typeof window === "undefined") {
    return false;
  }
  return window.localStorage.getItem(planModeStorageKey(botAlias, accountId)) === "1";
}

function writeStoredPlanMode(botAlias: string, enabled: boolean, accountId?: string) {
  if (typeof window === "undefined") {
    return;
  }
  if (enabled) {
    window.localStorage.setItem(planModeStorageKey(botAlias, accountId), "1");
    return;
  }
  window.localStorage.removeItem(planModeStorageKey(botAlias, accountId));
}

function readStoredExecutionMode(botAlias: string, accountId?: string): ChatExecutionMode | null {
  if (typeof window === "undefined") {
    return null;
  }
  const value = window.localStorage.getItem(executionModeStorageKey(botAlias, accountId));
  if (value === null) {
    return null;
  }
  return value === "native_agent" ? "native_agent" : "cli";
}

function writeStoredExecutionMode(botAlias: string, mode: ChatExecutionMode, accountId?: string) {
  if (typeof window === "undefined") {
    return;
  }
  if (mode === "native_agent") {
    window.localStorage.setItem(executionModeStorageKey(botAlias, accountId), mode);
    return;
  }
  window.localStorage.removeItem(executionModeStorageKey(botAlias, accountId));
}

function readStoredQueuedMessage(botAlias: string, agentId: string, accountId?: string): QueuedChatMessage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const rawValue = window.localStorage.getItem(queuedMessageStorageKey(botAlias, agentId, accountId));
    if (!rawValue) {
      return null;
    }
    const parsed = JSON.parse(rawValue) as Partial<QueuedChatMessage>;
    const text = typeof parsed.text === "string" ? parsed.text : "";
    const attachments = Array.isArray(parsed.attachments)
      ? parsed.attachments.filter((attachment): attachment is PendingChatAttachment => (
        attachment
        && typeof attachment.id === "string"
        && typeof attachment.filename === "string"
        && typeof attachment.savedPath === "string"
        && typeof attachment.size === "number"
      ))
      : [];
    const sendOptions = parsed.sendOptions && typeof parsed.sendOptions === "object" ? parsed.sendOptions : undefined;
    const nextMessage = {
      text,
      attachments,
      sendOptions,
    };
    return buildComposedMessageText(nextMessage.text, nextMessage.attachments) ? nextMessage : null;
  } catch {
    window.localStorage.removeItem(queuedMessageStorageKey(botAlias, agentId, accountId));
    return null;
  }
}

function writeStoredQueuedMessage(botAlias: string, agentId: string, message: QueuedChatMessage, accountId?: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(queuedMessageStorageKey(botAlias, agentId, accountId), JSON.stringify({
    text: message.text,
    attachments: message.attachments,
    sendOptions: message.sendOptions,
  }));
}

function clearStoredQueuedMessage(botAlias: string, agentId: string, accountId?: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(queuedMessageStorageKey(botAlias, agentId, accountId));
}

function agentOptions(agentId?: string, executionMode?: ChatExecutionMode): { agentId?: string; executionMode?: ChatExecutionMode } | undefined {
  const options = {
    ...(agentId && agentId !== "main" ? { agentId } : {}),
    ...(executionMode === "native_agent" ? { executionMode } : {}),
  };
  return Object.keys(options).length > 0 ? options : undefined;
}

function getSupportedExecutionModes(overview?: Pick<BotOverview, "supportedExecutionModes"> | null): ChatExecutionMode[] {
  return overview?.supportedExecutionModes?.length ? overview.supportedExecutionModes : ["cli"];
}

function getDefaultExecutionMode(overview?: Pick<BotOverview, "defaultExecutionMode" | "supportedExecutionModes"> | null): ChatExecutionMode {
  const supportedExecutionModes = getSupportedExecutionModes(overview);
  return overview?.defaultExecutionMode && supportedExecutionModes.includes(overview.defaultExecutionMode)
    ? overview.defaultExecutionMode
    : (supportedExecutionModes.includes("cli") ? "cli" : supportedExecutionModes[0] || "cli");
}

function getScopedOverview(client: WebBotClient, botAlias: string, agentId: string, executionMode?: ChatExecutionMode) {
  const options = agentOptions(agentId, executionMode);
  return options ? client.getBotOverview(botAlias, options) : client.getBotOverview(botAlias);
}

function listScopedMessages(client: WebBotClient, botAlias: string, agentId: string, executionMode?: ChatExecutionMode) {
  const options = agentOptions(agentId, executionMode);
  return options ? client.listMessages(botAlias, options) : client.listMessages(botAlias);
}

function listScopedMessageDelta(client: WebBotClient, botAlias: string, afterId: string, limit: number, agentId: string, executionMode?: ChatExecutionMode) {
  const options = agentOptions(agentId, executionMode);
  return options
    ? client.listMessageDelta(botAlias, afterId, limit, options)
    : client.listMessageDelta(botAlias, afterId, limit);
}

function getScopedMessageTrace(client: WebBotClient, botAlias: string, messageId: string, agentId: string, executionMode?: ChatExecutionMode) {
  const options = agentOptions(agentId, executionMode);
  return options
    ? client.getMessageTrace(botAlias, messageId, options)
    : client.getMessageTrace(botAlias, messageId);
}

function listScopedConversations(client: WebBotClient, botAlias: string, query: string, agentId: string, executionMode?: ChatExecutionMode) {
  const options = agentOptions(agentId, executionMode);
  return options
    ? client.listConversations(botAlias, query, options)
    : client.listConversations(botAlias, query);
}

function isMissingClusterRunError(err: unknown) {
  return (
    (err instanceof WebApiClientError && (err.status === 404 || err.code === "cluster_run_not_found"))
    || (err instanceof Error && err.message.includes("未找到集群任务"))
  );
}

function selectScopedConversation(client: WebBotClient, botAlias: string, conversationId: string, agentId: string, executionMode?: ChatExecutionMode) {
  const options = agentOptions(agentId, executionMode);
  return options
    ? client.selectConversation(botAlias, conversationId, options)
    : client.selectConversation(botAlias, conversationId);
}

function createScopedConversation(client: WebBotClient, botAlias: string, agentId: string, executionMode?: ChatExecutionMode) {
  const options = agentOptions(agentId, executionMode);
  return options ? client.createConversation(botAlias, "", options) : client.createConversation(botAlias);
}

function deleteScopedConversation(
  client: WebBotClient,
  botAlias: string,
  conversationId: string,
  agentId: string,
  deleteNativeSession: boolean,
  executionMode?: ChatExecutionMode,
) {
  const options = agentOptions(agentId, executionMode);
  return client.deleteConversation(botAlias, conversationId, {
    ...(options || {}),
    deleteNativeSession,
  });
}

function deleteAllScopedConversations(
  client: WebBotClient,
  botAlias: string,
  agentId: string,
  deleteNativeSession: boolean,
  executionMode?: ChatExecutionMode,
) {
  const options = agentOptions(agentId, executionMode);
  return client.deleteAllConversations(botAlias, {
    ...(options || {}),
    deleteNativeSession,
  });
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

function modelLimitTitle(contextWindow?: number, outputLimit?: number) {
  return [
    typeof contextWindow === "number" ? `context ${contextWindow.toLocaleString()}` : "",
    typeof outputLimit === "number" ? `output ${outputLimit.toLocaleString()}` : "",
  ].filter(Boolean).join(", ");
}

function resolveNativeReasoningEffort(model: NativeAgentModelOption | undefined, selected?: string) {
  const efforts = model?.reasoningEfforts || [];
  if (efforts.length === 0) {
    return "";
  }
  const normalized = String(selected || "").trim();
  if (normalized && efforts.includes(normalized)) {
    return normalized;
  }
  const defaultEffort = String(model?.defaultReasoningEffort || "").trim();
  if (defaultEffort && efforts.includes(defaultEffort)) {
    return defaultEffort;
  }
  return efforts[0] || "";
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

function isSilentDreamRuntimeRun(run: AssistantRuntimePendingRun | null | undefined) {
  return Boolean(run && run.taskMode === "dream" && !run.interactive);
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

function normalizeResolvedFinalMessage(message: ChatMessage): ChatMessage {
  if (message.state === "error") {
    return message;
  }
  const completionState = String(message.meta?.completionState || "").trim().toLowerCase();
  if (["cancelled", "canceled", "error", "failed"].includes(completionState)) {
    return {
      ...message,
      state: "error",
    };
  }
  return {
    ...message,
    state: "done",
  };
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

function chatMessageDisplayTime(item: ChatMessage) {
  if (item.role === "assistant" && item.state !== "streaming" && item.updatedAt) {
    return item.updatedAt;
  }
  return item.createdAt;
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

function maxDefinedNumber(...values: Array<number | undefined>) {
  const definedValues = values.filter((value): value is number => (
    typeof value === "number" && Number.isFinite(value)
  ));
  return definedValues.length > 0 ? Math.max(...definedValues) : undefined;
}

function mergeMessageMeta(base?: ChatMessageMetaInfo, incoming?: ChatMessageMetaInfo): ChatMessageMetaInfo | undefined {
  const isNativeSource = isNativeAgentMessage(incoming) || isNativeAgentMessage(base);
  const tracePresentation = incoming?.tracePresentation || base?.tracePresentation || (isNativeSource ? "native_agent_flat" : undefined);
  const trace = mergeChatTraceEvents(
    [base?.trace, incoming?.trace],
    { nativeFlat: tracePresentation === "native_agent_flat" },
  );
  const traceCount = trace?.length;
  const toolCallCount = trace?.filter((event) => event.kind === "tool_call").length;
  const processCount = trace?.filter((event) => event.kind !== "tool_call" && event.kind !== "tool_result").length;
  const meta: ChatMessageMetaInfo = {
    completionState: incoming?.completionState || base?.completionState,
    summaryKind: incoming?.summaryKind || base?.summaryKind,
    traceVersion: incoming?.traceVersion ?? base?.traceVersion ?? (trace ? 1 : undefined),
    traceCount: typeof traceCount === "number" ? traceCount : maxDefinedNumber(incoming?.traceCount, base?.traceCount),
    toolCallCount: maxDefinedNumber(
      typeof toolCallCount === "number" ? toolCallCount : undefined,
      incoming?.toolCallCount,
      base?.toolCallCount,
    ),
    processCount: maxDefinedNumber(
      typeof processCount === "number" ? processCount : undefined,
      incoming?.processCount,
      base?.processCount,
    ),
    nativeSource: incoming?.nativeSource || base?.nativeSource,
    contextUsage: incoming?.contextUsage || base?.contextUsage,
    agUiRunState: incoming?.agUiRunState || base?.agUiRunState,
    tracePresentation,
    trace,
  };

  return Object.values(meta).some((value) => typeof value !== "undefined") ? meta : undefined;
}

function getAgUiRunState(meta?: ChatMessageMetaInfo): AgUiRunState | null {
  const value = meta?.agUiRunState;
  return value && typeof value === "object" ? value as AgUiRunState : null;
}

function buildLiveAgUiMessageMeta(state: AgUiRunState, nativeAgent = false): ChatMessageMetaInfo {
  return {
    ...(buildAgUiMessageMeta(state, { nativeAgent }) || {}),
    agUiRunState: state,
  };
}

function hasPendingAgUiPermission(state: AgUiRunState | null) {
  return Boolean(state && !state.completed && state.permissionRequests.some((permission) => {
    const value = permission.state.trim().toLowerCase();
    return !value || (
      !value.includes("replied")
      && !value.includes("approved")
      && !value.includes("reject")
      && !value.includes("denied")
      && !value.includes("allow")
    );
  }));
}

function isNativePermissionTrace(event: ChatTraceEvent, permissionId: string) {
  const payload = event.payload && typeof event.payload === "object"
    ? event.payload as Record<string, unknown>
    : {};
  const currentId = String(payload.permissionId || payload.id || payload.permissionID || payload.permission_id || "").trim();
  return event.kind === "permission" && currentId === permissionId;
}

function markNativePermissionTraceReplied(meta: ChatMessageMetaInfo | undefined, permissionId: string, approved: boolean): ChatMessageMetaInfo | undefined {
  if (!meta?.trace?.length && !getAgUiRunState(meta)?.entries.length) {
    return meta;
  }
  const summary = approved ? "原生 agent 权限已允许" : "原生 agent 权限已拒绝";
  const response = approved ? "once" : "reject";
  const patchTrace = (event: ChatTraceEvent): ChatTraceEvent => {
    if (!isNativePermissionTrace(event, permissionId)) {
      return event;
    }
    const payload = event.payload && typeof event.payload === "object"
      ? event.payload as Record<string, unknown>
      : {};
    return {
      ...event,
      summary,
      payload: {
        ...payload,
        state: "permission.replied",
        response,
      },
    };
  };
  const agUiRunState = getAgUiRunState(meta);
  const nextAgUiRunState = agUiRunState
    ? {
        ...agUiRunState,
        permissionRequests: agUiRunState.permissionRequests.map((permission) => (
          permission.permissionId === permissionId
            ? {
                ...permission,
                summary,
                state: "permission.replied",
                content: {
                  ...permission.content,
                  state: "permission.replied",
                  response,
                },
              }
            : permission
        )),
        traceEvents: agUiRunState.traceEvents.map(patchTrace),
        entries: agUiRunState.entries.map((entry) => (
          entry.kind === "permission" && entry.permissionId === permissionId
            ? {
                ...entry,
                summary,
                pending: false,
                trace: entry.trace ? patchTrace(entry.trace) : entry.trace,
              }
            : entry
        )),
      }
    : undefined;
  return {
    ...meta,
    ...(meta.trace?.length ? { trace: meta.trace.map(patchTrace) } : {}),
    ...(nextAgUiRunState ? { agUiRunState: nextAgUiRunState } : {}),
  };
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

function mergeAgentMentions(left: AgentMention[] = [], right: AgentMention[] = []) {
  const seen = new Set<string>();
  const result: AgentMention[] = [];
  for (const mention of [...left, ...right]) {
    if (!mention.agentId || seen.has(mention.agentId)) {
      continue;
    }
    seen.add(mention.agentId);
    result.push(mention);
  }
  return result;
}

function mergeQueuedChatMessage(current: QueuedChatMessage | null, incoming: QueuedChatMessage): QueuedChatMessage {
  if (!current) {
    return incoming;
  }

  const currentText = current.text.trim();
  const incomingText = incoming.text.trim();
  const text = currentText && incomingText
    ? `${currentText}\n\n${incomingText}`
    : currentText || incomingText;
  const currentOptions = current.sendOptions;
  const incomingOptions = incoming.sendOptions;
  const sendOptions = (currentOptions || incomingOptions)
    ? {
      ...currentOptions,
      ...incomingOptions,
      mentions: mergeAgentMentions(currentOptions?.mentions, incomingOptions?.mentions),
    }
    : undefined;

  return {
    text,
    attachments: [...current.attachments, ...incoming.attachments],
    sendOptions,
  };
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

function shouldShowContextRing(meta?: ChatMessageMetaInfo) {
  const provider = String(meta?.contextUsage?.provider || "").trim().toLowerCase();
  return (
    isNativeAgentMessage(meta)
    || provider === "native_agent"
    || provider === "opencode"
    || provider === "原生 agent"
  );
}

function appendTraceToMessage(item: ChatMessage, traceEvent: ChatTraceEvent, tracePresentation?: ChatMessageMetaInfo["tracePresentation"]): ChatMessage {
  return {
    ...item,
    meta: mergeMessageMeta(item.meta, {
      trace: [traceEvent],
      traceVersion: 1,
      tracePresentation,
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
  if (task.status === "completed") return "bg-[var(--accent-soft)] text-[var(--accent)]";
  if (task.status === "failed") return "bg-[var(--surface-strong)] text-[var(--danger)]";
  return "bg-[var(--surface-strong)] text-[var(--text)]";
}

function ClusterTaskPanel({ status, agents }: { status: ClusterTaskStatus; agents: AgentSummary[] }) {
  if (status.tasks.length === 0) {
    return null;
  }
  const agentNameMap = new Map(agents.map((agent) => [agent.id, agent.name || agent.id]));
  return (
    <section className="rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-4 py-3 text-sm text-[var(--text)] shadow-[var(--shadow-soft)]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">智能体集群任务</span>
        {status.pendingCount > 0 ? (
          <span className="inline-flex items-center gap-1 rounded-md bg-[var(--surface-strong)] px-2 py-0.5 text-xs text-[var(--text)]">
            <LoaderCircle className="h-3 w-3 animate-spin" />
            {status.pendingCount} 项进行中
          </span>
        ) : (
          <span className="rounded-md bg-[var(--surface-strong)] px-2 py-0.5 text-xs text-[var(--text)]">已汇总</span>
        )}
      </div>
      <div className="mt-3 space-y-2">
        {status.tasks.map((task) => {
          const agentId = task.agentId || "agent";
          const agentName = agentNameMap.get(agentId) || "";
          return (
            <div key={task.taskId} className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--surface)] px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">@{agentId}</span>
                {agentName && agentName !== agentId ? (
                  <span className="text-xs text-[var(--muted)]">{agentName}</span>
                ) : null}
                <span className={`rounded-md px-2 py-0.5 text-xs ${clusterTaskStatusClass(task)}`}>
                  {clusterTaskStatusText(task)}
                </span>
                {task.modelTier ? <span className="text-xs text-[var(--muted)]">{task.modelTier}</span> : null}
              </div>
              {task.error ? (
                <p className="mt-2 whitespace-pre-wrap break-words text-xs text-[var(--danger)]">{task.error}</p>
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
  onCopyFinalAnswer: (text: string) => boolean | void | Promise<boolean | void>;
  onReplyNativePermission: (permissionId: string, approved: boolean) => Promise<void>;
  wideMessages: boolean;
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
  onCopyFinalAnswer,
  onReplyNativePermission,
  wideMessages,
}: ChatMessageRowProps) {
  const reduceMotion = useReducedMotion();

  if (item.role === "system") {
    return (
      <div className="flex justify-center">
        <div className="rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-4 py-2 text-sm text-[var(--muted)] whitespace-pre-wrap break-all">
          {item.text}
        </div>
      </div>
    );
  }

  const isUser = item.role === "user";
  const isCurrentUserMessage = !isUser || item.author?.isCurrentUser !== false;
  const messageName = isUser ? item.author?.username || "你" : assistantName;
  const messageAlign = isUser && isCurrentUserMessage ? "right" : "left";
  const parsedUserMessage = isUser ? parseUserMessageDisplay(item.text) : null;
  const visibleUserText = parsedUserMessage?.visibleText || "";
  const userAttachments = parsedUserMessage?.attachments || [];
  const isStreamingAssistant = item.role === "assistant" && item.state === "streaming";
  const hasStreamingText = isStreamingAssistant && item.text.trim().length > 0;
  const trace = item.meta?.trace;
  const agUiRunState = item.role === "assistant" ? getAgUiRunState(item.meta) : null;
  const isNativeAgentAssistant = item.role === "assistant" && isNativeAgentMessage(item.meta);
  const showContextRing = item.role === "assistant" && shouldShowContextRing(item.meta);
  const nativeTranscriptEntries = buildNativeAgentTranscriptEntries({
    trace,
    agUiState: agUiRunState,
  });
  const traceCount = typeof item.meta?.traceCount === "number" ? item.meta.traceCount : trace?.length ?? 0;
  const hasTracePanel = allowTrace && item.role === "assistant" && traceCount > 0 && !agUiRunState && !isNativeAgentAssistant;
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
      className={messageAlign === "right" ? "flex justify-end" : "flex justify-start"}
      {...resolveMotionProps(delightMotion.messagePop, reduceMotion)}
    >
      <div className={wideMessages ? "min-w-0 w-full" : "min-w-0 max-w-[96%] sm:max-w-[90%]"}>
        <ChatMessageMeta
          name={messageName}
          createdAt={chatMessageDisplayTime(item)}
          align={messageAlign}
          avatar={inlineAvatar}
          contextUsage={!isUser ? item.meta?.contextUsage : undefined}
          contextVariant={showContextRing ? "ring" : "text"}
        />
        <div
          data-streaming={isStreamingAssistant ? "true" : "false"}
          className={isNativeAgentAssistant
            ? "min-w-0 overflow-hidden text-[var(--text)]"
            : [
                "chat-message-bubble-delight",
                isUser && isCurrentUserMessage
                  ? "rounded-lg bg-[var(--accent)] px-4 py-2 text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
                  : isStreamingAssistant
                    ? "min-w-0 overflow-hidden rounded-lg border border-[var(--accent)]/45 bg-[var(--workbench-panel-elevated-bg)] px-4 py-3 text-[var(--text)] shadow-[var(--shadow-soft)]"
                  : item.state === "error"
                    ? "rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-red-700 shadow-[var(--shadow-soft)]"
                    : "min-w-0 overflow-hidden rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-4 py-3 text-[var(--text)] shadow-[var(--shadow-soft)]",
              ].join(" ")}
        >
          {isNativeAgentAssistant ? (
            <NativeAgentTranscript
              entries={nativeTranscriptEntries}
              resultText={item.text}
              state={item.state}
              onReplyPermission={onReplyNativePermission}
              onFileLinkClick={onFileLinkClick}
            />
          ) : item.role === "assistant" && item.state !== "streaming" && item.state !== "error" ? (
            <ChatMarkdownMessage content={item.text} onFileLinkClick={onFileLinkClick} />
          ) : isUser ? (
            <div className={userAttachments.length > 0 && visibleUserText ? "space-y-2" : undefined}>
              {visibleUserText ? (
                <ChatPlainTextMessage
                  content={visibleUserText}
                  className={isCurrentUserMessage ? "text-[var(--accent-foreground)]" : undefined}
                />
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
                        className={!isCurrentUserMessage
                          ? "inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--bg)] px-3 py-1 text-xs text-[var(--muted)]"
                          : isDeleted
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
          ) : isStreamingAssistant && !hasStreamingText ? (
            <div className="inline-flex items-center gap-2 text-sm text-[var(--muted)]">
              <LoaderCircle className="h-4 w-4 animate-spin text-[var(--accent)]" />
              <span>正在输出...</span>
            </div>
          ) : (
            <ChatPlainTextMessage
              content={item.text}
              className={isUser ? "text-[var(--accent-foreground)]" : item.state === "error" ? "text-red-700" : "text-[var(--text)]"}
            />
          )}
        </div>
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
            onCopyFinalAnswer={item.text ? () => onCopyFinalAnswer(item.text) : undefined}
            onReplyNativePermission={onReplyNativePermission}
          />
        ) : null}
      </div>
    </motion.div>
  );
});

const ChatMessageList = memo(function ChatMessageList({
  rows,
  assistantName,
  assistantAvatarName,
  userAvatarName,
  allowTrace,
  expandedTracePanels,
  traceLoadState,
  handleDeleteAttachment,
  handleFileLinkClick,
  loadMessageTrace,
  handleToggleTracePanel,
  handleCopyFinalAnswer,
  handleReplyNativePermission,
  executingPlanMessageId,
  planExecuteError,
  handleExecutePlan,
  wideMessages,
}: {
  rows: ChatMessageRowModel[];
  assistantName: string;
  assistantAvatarName?: string;
  userAvatarName?: string;
  allowTrace: boolean;
  expandedTracePanels: Record<string, boolean>;
  traceLoadState: Record<string, { loading: boolean; error?: string }>;
  handleDeleteAttachment: (messageId: string, savedPath: string) => void;
  handleFileLinkClick: (href: string) => void;
  loadMessageTrace: (messageId: string) => void;
  handleToggleTracePanel: (messageClientStateKey: string) => void;
  handleCopyFinalAnswer: (text: string) => boolean | void | Promise<boolean | void>;
  handleReplyNativePermission: (permissionId: string, approved: boolean) => Promise<void>;
  executingPlanMessageId: string;
  planExecuteError: string;
  handleExecutePlan: (messageId: string, content: string) => void;
  wideMessages: boolean;
}) {
  return rows.map((row) => (
    <div key={row.item.id} className="space-y-1">
      <ChatMessageRow
        item={row.item}
        messageClientStateKey={row.messageClientStateKey}
        assistantName={assistantName}
        assistantAvatarName={assistantAvatarName}
        userAvatarName={userAvatarName}
        allowTrace={allowTrace}
        deletedAttachmentKeys={row.deletedAttachmentKeys}
        deletingAttachmentKeys={row.deletingAttachmentKeys}
        tracePanelExpanded={Boolean(expandedTracePanels[row.messageClientStateKey])}
        traceLoadState={traceLoadState[row.messageClientStateKey]}
        onDeleteAttachment={handleDeleteAttachment}
        onFileLinkClick={handleFileLinkClick}
        onLoadTrace={loadMessageTrace}
        onToggleTracePanel={handleToggleTracePanel}
        onCopyFinalAnswer={handleCopyFinalAnswer}
        onReplyNativePermission={handleReplyNativePermission}
        wideMessages={wideMessages}
      />
      {row.planDraft ? (
        <div className="flex justify-start">
          <div className={wideMessages ? "min-w-0 w-full" : "min-w-0 max-w-[96%] sm:max-w-[90%]"}>
            <PlanDraftCard
              content={row.planDraft}
              executing={executingPlanMessageId === row.item.id}
              error={executingPlanMessageId === row.item.id ? "" : planExecuteError}
              onExecute={(content) => void handleExecutePlan(row.item.id, content)}
            />
          </div>
        </div>
      ) : null}
    </div>
  ));
});

export function ChatScreen({
  botAlias,
  accountId,
  client = new MockWebBotClient(),
  botAvatarName,
  userAvatarName,
  readOnly = false,
  readOnlyReason,
  disabledReason,
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
  const storageScope = accountId?.trim() || "";
  const [items, setItems] = useState<ChatMessage[]>([]);
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamMode, setStreamMode] = useState<"" | "sse" | "poll">("");
  const [streamStartedAtMs, setStreamStartedAtMs] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [workingDir, setWorkingDir] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [actionLoading, setActionLoading] = useState<"" | "kill">("");
  const [cliParams, setCliParams] = useState<CliParamsPayload | null>(null);
  const [nativeAgentModels, setNativeAgentModels] = useState<NativeAgentModelsPayload | null>(null);
  const [modelSaving, setModelSaving] = useState(false);
  const [pendingAttachments, setPendingAttachments] = useState<PendingChatAttachment[]>([]);
  const [queuedMessage, setQueuedMessage] = useState<QueuedChatMessage | null>(null);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);
  const [previewName, setPreviewName] = useState("");
  const [previewContent, setPreviewContent] = useState("");
  const [previewMode, setPreviewMode] = useState<"preview" | "full">("preview");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewResult, setPreviewResult] = useState<FileReadResult | null>(null);
  const [previewDownloadProgress, setPreviewDownloadProgress] = useState<FileDownloadProgress | null>(null);
  const previewRequestSeqRef = useRef(0);
  const [botOverview, setBotOverview] = useState<BotOverview | null>(null);
  const [pendingCronRuns, setPendingCronRuns] = useState<AssistantCronRunEnqueuedDetail[]>([]);
  const [deletedAttachmentKeys, setDeletedAttachmentKeys] = useState<Record<string, boolean>>({});
  const [deletingAttachmentKeys, setDeletingAttachmentKeys] = useState<Record<string, boolean>>({});
  const [expandedTracePanels, setExpandedTracePanels] = useState<Record<string, boolean>>({});
  const [traceLoadState, setTraceLoadState] = useState<Record<string, { loading: boolean; error?: string }>>({});
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false);
  const [conversationQuery, setConversationQuery] = useState("");
  const [conversationLoading, setConversationLoading] = useState(false);
  const [deletingConversationId, setDeletingConversationId] = useState("");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [agents, setAgents] = useState<AgentSummary[]>(fallbackAgents());
  const [activeAgentId, setActiveAgentId] = useState(() => readStoredAgentId(botAlias, storageScope));
  const [clusterRunId, setClusterRunId] = useState("");
  const [clusterTaskStatus, setClusterTaskStatus] = useState<ClusterTaskStatus | null>(null);
  const [clusterTaskError, setClusterTaskError] = useState("");
  const [clusterSaving, setClusterSaving] = useState(false);
  const [planMode, setPlanModeState] = useState(() => readStoredPlanMode(botAlias, storageScope));
  const [executionMode, setExecutionModeState] = useState<ChatExecutionMode>(() => readStoredExecutionMode(botAlias, storageScope) ?? "cli");
  const [nativePermissionPending, setNativePermissionPending] = useState(false);
  const [executingPlanMessageId, setExecutingPlanMessageId] = useState("");
  const [planExecuteError, setPlanExecuteError] = useState("");
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
  const queuedMessageRef = useRef<QueuedChatMessage | null>(null);
  const agentsRef = useRef<AgentSummary[]>(fallbackAgents());
  const activeAgentIdRef = useRef(activeAgentId);
  const executionModeRef = useRef(executionMode);
  const assistantPollTimerRef = useRef<number | null>(null);
  const sseRecoveryTimerRef = useRef<number | null>(null);
  const sseLastActivityAtRef = useRef<number | null>(null);
  const pollAssistantStateRef = useRef<(() => Promise<void>) | null>(null);
  const drainQueuedMessageIfIdleRef = useRef<((context?: { botAlias: string; agentId: string }) => Promise<void>) | null>(null);
  const clusterTaskPollTimerRef = useRef<number | null>(null);
  const revealScrollFrameRef = useRef<number | null>(null);
  const revealScrollAttemptsRef = useRef(0);
  const userScrollIntentRef = useRef(false);
  const clusterRunIdRef = useRef("");
  const assistantSendVersionRef = useRef(0);
  const previousBotAliasRef = useRef(botAlias);
  const previousStorageScopeRef = useRef(storageScope);
  const hasActivatedRef = useRef(false);
  const activationTargetRef = useRef<{ botAlias: string; client: WebBotClient; storageScope: string } | null>(null);
  const isSseStreaming = () => streamModeRef.current === "sse";

  const setPlanMode = useCallback((value: boolean | ((current: boolean) => boolean)) => {
    setPlanModeState((current) => {
      const next = typeof value === "function" ? value(current) : value;
      writeStoredPlanMode(previousBotAliasRef.current, next, previousStorageScopeRef.current);
      return next;
    });
  }, []);

  const setExecutionMode = useCallback((value: ChatExecutionMode | ((current: ChatExecutionMode) => ChatExecutionMode)) => {
    setExecutionModeState((current) => {
      const next = typeof value === "function" ? value(current) : value;
      writeStoredExecutionMode(previousBotAliasRef.current, next, previousStorageScopeRef.current);
      executionModeRef.current = next;
      return next;
    });
  }, []);

  const setQueuedMessageState = useCallback((
    next: QueuedChatMessage | null,
    context?: { botAlias: string; agentId: string; accountId?: string },
  ) => {
    const targetBotAlias = context?.botAlias || botAlias;
    const targetAgentId = context?.agentId || activeAgentIdRef.current || "main";
    const targetScope = context?.accountId ?? storageScope;
    queuedMessageRef.current = next;
    setQueuedMessage(next);
    if (next) {
      writeStoredQueuedMessage(targetBotAlias, targetAgentId, next, targetScope);
    } else {
      clearStoredQueuedMessage(targetBotAlias, targetAgentId, targetScope);
    }
  }, [botAlias, storageScope]);

  useLayoutEffect(() => {
    const previousBotAlias = previousBotAliasRef.current;
    const previousScope = previousStorageScopeRef.current;
    if (previousBotAlias === botAlias && previousScope === storageScope) {
      return;
    }
    clearStoredQueuedMessage(previousBotAlias, activeAgentIdRef.current || "main", previousScope);
    setQueuedMessage(null);
    queuedMessageRef.current = null;
    setHistoryExpanded(false);
    previousBotAliasRef.current = botAlias;
    previousStorageScopeRef.current = storageScope;
    assistantSendVersionRef.current += 1;
    setPlanModeState(readStoredPlanMode(botAlias, storageScope));
    const storedExecutionMode = readStoredExecutionMode(botAlias, storageScope) ?? "cli";
    executionModeRef.current = storedExecutionMode;
    setExecutionModeState(storedExecutionMode);
  }, [botAlias, storageScope]);

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
    setNativePermissionPending(false);
    clusterRunIdRef.current = "";
    setQueuedMessage(null);
    queuedMessageRef.current = null;
    const storedAgentId = readStoredAgentId(botAlias, storageScope);
    setActiveAgentId(storedAgentId);
    activeAgentIdRef.current = storedAgentId;
  }, [botAlias, storageScope]);

  useEffect(() => {
    loadingRef.current = loading;
  }, [loading]);

  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  useEffect(() => {
    streamModeRef.current = streamMode;
  }, [streamMode]);

  const cancelRevealScroll = useCallback(() => {
    if (revealScrollFrameRef.current !== null) {
      window.cancelAnimationFrame(revealScrollFrameRef.current);
      revealScrollFrameRef.current = null;
    }
  }, []);

  useEffect(() => () => {
    cancelRevealScroll();
    if (clusterTaskPollTimerRef.current !== null) {
      window.clearTimeout(clusterTaskPollTimerRef.current);
      clusterTaskPollTimerRef.current = null;
    }
  }, [cancelRevealScroll]);

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
    queuedMessageRef.current = queuedMessage;
  }, [queuedMessage]);

  useEffect(() => {
    agentsRef.current = agents;
  }, [agents]);

  useEffect(() => {
    activeAgentIdRef.current = activeAgentId;
  }, [activeAgentId]);

  useEffect(() => {
    executionModeRef.current = executionMode;
  }, [executionMode]);

  useEffect(() => {
    const supported = getSupportedExecutionModes(botOverview);
    if (!supported.includes(executionModeRef.current)) {
      setExecutionMode(getDefaultExecutionMode(botOverview));
    }
  }, [botOverview?.defaultExecutionMode, botOverview?.supportedExecutionModes, setExecutionMode]);

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

  useEffect(() => {
    const supported = getSupportedExecutionModes(botOverview);
    const shouldLoad = isVisible && supported.includes("native_agent");
    let active = true;
    if (!shouldLoad) {
      setNativeAgentModels(null);
      return () => {
        active = false;
      };
    }

    void client.getNativeAgentModels(botAlias)
      .then((payload) => {
        if (active) {
          setNativeAgentModels(payload);
        }
      })
      .catch(() => {
        if (active) {
          setNativeAgentModels(null);
        }
      });

    return () => {
      active = false;
    };
  }, [botAlias, botOverview?.defaultExecutionMode, botOverview?.supportedExecutionModes, client, isVisible]);

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
    isStreamingRef.current = shouldPoll;
    streamModeRef.current = shouldPoll ? "poll" : "";
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

  const clearClusterTaskState = useCallback(() => {
    stopClusterTaskPoll();
    clusterRunIdRef.current = "";
    setClusterRunId("");
    setClusterTaskStatus(null);
    setClusterTaskError("");
  }, [stopClusterTaskPoll]);

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
      if (isMissingClusterRunError(err)) {
        clearClusterTaskState();
        return;
      }
      setClusterTaskError(err instanceof Error ? err.message : "集群任务状态获取失败");
    }
  }, [botAlias, clearClusterTaskState, client, stopClusterTaskPoll]);

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
          const currentExecutionMode = executionModeRef.current;
          const overview = await getScopedOverview(client, botAlias, agentId, currentExecutionMode);
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

          const messages = await listScopedMessages(client, botAlias, agentId, currentExecutionMode);
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
          const { shouldPoll } = applyHistoryView(messages, overview, refreshedPendingRuns);
          if (!shouldPoll) {
            void drainQueuedMessageIfIdleRef.current?.({ botAlias, agentId });
          }
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
      const currentExecutionMode = executionModeRef.current;
      const overview = await getScopedOverview(client, botAlias, agentId, currentExecutionMode);
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
          messages = await listScopedMessages(client, botAlias, agentId, currentExecutionMode);
        } else if (afterId) {
          const delta = await listScopedMessageDelta(client, botAlias, afterId, 50, agentId, currentExecutionMode);
          messages = delta.reset ? delta.items : [...previousItems, ...delta.items];
        } else {
          messages = await listScopedMessages(client, botAlias, agentId, currentExecutionMode);
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
      if (!shouldPoll) {
        void drainQueuedMessageIfIdleRef.current?.({ botAlias, agentId });
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
    if (
      !activatedTarget
      || activatedTarget.botAlias !== botAlias
      || activatedTarget.client !== client
      || activatedTarget.storageScope !== storageScope
    ) {
      activationTargetRef.current = { botAlias, client, storageScope };
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
    loadingRef.current = true;
    setLoading(true);
    setError("");
    setItems([]);
    setWorkingDir("");
    isStreamingRef.current = false;
    streamModeRef.current = "";
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

    const storedExecutionMode = readStoredExecutionMode(botAlias, storageScope);
    const requestedExecutionMode = storedExecutionMode || undefined;
    const requestedAgentId = activeAgentIdRef.current || "main";
    const loadAgents = typeof client.listAgents === "function"
      ? client.listAgents(botAlias).catch(() => ({ items: fallbackAgents() }))
      : Promise.resolve({ items: fallbackAgents() });

    Promise.all([
      loadAgents,
      listScopedMessages(client, botAlias, requestedAgentId, requestedExecutionMode),
      getScopedOverview(client, botAlias, requestedAgentId, requestedExecutionMode),
    ])
      .then(async ([agentData, initialMessages, initialOverview]) => {
        if (cancelled) return;
        const nextAgents = agentData.items.length > 0 ? agentData.items : fallbackAgents();
        const nextExecutionMode = storedExecutionMode
          ? (getSupportedExecutionModes(initialOverview).includes(storedExecutionMode)
            ? storedExecutionMode
            : getDefaultExecutionMode(initialOverview))
          : getDefaultExecutionMode(initialOverview);
        const preferredAgentId = nextExecutionMode === "native_agent" ? "main" : requestedAgentId;
        const nextAgentId = nextAgents.some((agent) => agent.id === preferredAgentId) ? preferredAgentId : "main";
        let messages = initialMessages;
        let overview = initialOverview;
        if (storedExecutionMode && nextExecutionMode !== storedExecutionMode) {
          setExecutionMode(nextExecutionMode);
        } else if (!storedExecutionMode && nextExecutionMode !== requestedExecutionMode) {
          executionModeRef.current = nextExecutionMode;
          setExecutionModeState(nextExecutionMode);
        }
        if (nextAgentId !== requestedAgentId) {
          setActiveAgentId(nextAgentId);
          activeAgentIdRef.current = nextAgentId;
          window.localStorage.setItem(activeAgentStorageKey(botAlias, storageScope), nextAgentId);
        }
        const requestedComparisonMode = requestedExecutionMode ?? "cli";
        const executionModeNeedsReload = nextExecutionMode !== requestedComparisonMode;
        if (nextAgentId !== requestedAgentId || executionModeNeedsReload) {
          [messages, overview] = await Promise.all([
            listScopedMessages(client, botAlias, nextAgentId, nextExecutionMode),
            getScopedOverview(client, botAlias, nextAgentId, nextExecutionMode),
          ]);
          if (cancelled || activeAgentIdRef.current !== nextAgentId || executionModeRef.current !== nextExecutionMode) {
            return;
          }
        }
        setAgents(nextAgents);
        setBotOverview(overview);
        setWorkingDir(overview.workingDir || "");
        restoreClusterRunFromOverview(overview);
        const storedQueuedMessage = readStoredQueuedMessage(botAlias, nextAgentId, storageScope);
        setQueuedMessageState(storedQueuedMessage, { botAlias, agentId: nextAgentId });
        const { shouldPoll } = applyHistoryView(messages, overview, []);
        loadingRef.current = false;
        setLoading(false);
        if (isVisibleRef.current && (overview.isProcessing || overview.botMode === "assistant")) {
          scheduleAssistantPoll(
            overview.isProcessing ? ACTIVE_ASSISTANT_POLL_INTERVAL_MS : IDLE_ASSISTANT_POLL_INTERVAL_MS,
          );
        } else {
          stopAssistantPoll();
        }
        if (!shouldPoll) {
          void drainQueuedMessageIfIdleRef.current?.({ botAlias, agentId: nextAgentId });
        }
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || "加载历史失败");
        loadingRef.current = false;
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
    setQueuedMessageState,
    stopAssistantPoll,
    stopSseRecoveryWatch,
    storageScope,
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
  const hasHiddenAssistantRuntimeActive = isSilentDreamRuntimeRun(assistantRuntimeActive);
  const visibleAssistantRuntimeQueue = (assistantRuntime?.queue || []).filter((run) => !isSilentDreamRuntimeRun(run));
  const visibleAssistantRuntimeActive = isSilentDreamRuntimeRun(assistantRuntimeActive) ? null : assistantRuntimeActive;
  const assistantRuntimeQueuedCount = visibleAssistantRuntimeQueue.length;
  const assistantRuntimeQueueLabels = visibleAssistantRuntimeQueue.slice(0, 2).map(assistantRuntimeRunLabel);
  const showAssistantRuntimeBanner = Boolean(
    isAssistantBot
    && (visibleAssistantRuntimeActive || assistantRuntimeQueuedCount > 0 || hasHiddenAssistantRuntimeActive)
    && (
      assistantRuntimeQueuedCount > 0
      || (visibleAssistantRuntimeActive && !visibleAssistantRuntimeActive.interactive)
      || (hasHiddenAssistantRuntimeActive && assistantRuntimeQueuedCount > 0)
    ),
  );
  let assistantRuntimeHeadline = "";
  if ((visibleAssistantRuntimeActive || hasHiddenAssistantRuntimeActive) && assistantRuntimeQueuedCount > 0) {
    assistantRuntimeHeadline = "assistant 队列忙碌中，新消息会按顺序执行";
  } else if (visibleAssistantRuntimeActive && !visibleAssistantRuntimeActive.interactive) {
    assistantRuntimeHeadline = "assistant 后台任务执行中，新消息会等待当前任务完成";
  } else if (assistantRuntimeQueuedCount > 0) {
    assistantRuntimeHeadline = `assistant 队列中 ${assistantRuntimeQueuedCount} 项，新消息会按顺序执行`;
  }
  const assistantRuntimeActiveLabel = visibleAssistantRuntimeActive ? assistantRuntimeRunLabel(visibleAssistantRuntimeActive) : "";

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
    userScrollIntentRef.current = false;
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
    userScrollIntentRef.current = false;
  }, []);

  const isNearScrollBottom = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) {
      return true;
    }
    return container.scrollHeight - container.scrollTop - container.clientHeight <= REVEAL_SCROLL_BOTTOM_THRESHOLD_PX;
  }, []);

  const scheduleRevealScroll = useCallback(() => {
    if (!isVisibleRef.current) {
      return;
    }
    if (!forceAutoScrollRef.current && !shouldStickToBottomRef.current) {
      return;
    }
    if (revealScrollFrameRef.current !== null) {
      return;
    }

    revealScrollFrameRef.current = window.requestAnimationFrame(() => {
      revealScrollFrameRef.current = null;
      if (!isVisibleRef.current || loadingRef.current) {
        return;
      }
      if (!forceAutoScrollRef.current && !shouldStickToBottomRef.current) {
        return;
      }

      scrollToBottom();
      if (isNearScrollBottom() || revealScrollAttemptsRef.current >= REVEAL_SCROLL_MAX_FRAMES - 1) {
        forceAutoScrollRef.current = false;
        revealScrollAttemptsRef.current = 0;
        return;
      }

      revealScrollAttemptsRef.current += 1;
      scheduleRevealScroll();
    });
  }, [isNearScrollBottom, scrollToBottom]);

  useEffect(() => {
    if (!isVisible) {
      cancelRevealScroll();
      return;
    }
    shouldStickToBottomRef.current = true;
    forceAutoScrollRef.current = true;
    revealScrollAttemptsRef.current = 0;
    scheduleRevealScroll();
  }, [cancelRevealScroll, isVisible, scheduleRevealScroll]);

  useEffect(() => {
    if (!isVisible || loading) {
      return;
    }
    if (!forceAutoScrollRef.current && !shouldStickToBottomRef.current) {
      return;
    }
    scrollToBottom();
    scheduleRevealScroll();
  }, [isVisible, isStreaming, lastItem?.id, lastItem?.state, lastItem?.text, loading, items.length, scheduleRevealScroll, scrollToBottom]);

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
      scheduleRevealScroll();
    });
    observer.observe(content);
    return () => {
      observer.disconnect();
    };
  }, [isVisible, loading, scheduleRevealScroll, scrollToBottom]);

  function updateAutoScrollStickiness() {
    const container = scrollContainerRef.current;
    if (!container) {
      return;
    }
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldStickToBottomRef.current = distanceFromBottom <= 96;
    if (shouldStickToBottomRef.current) {
      userScrollIntentRef.current = false;
      return;
    }
    if (userScrollIntentRef.current) {
      forceAutoScrollRef.current = false;
      revealScrollAttemptsRef.current = 0;
      cancelRevealScroll();
      userScrollIntentRef.current = false;
    }
  }

  function markUserScrollIntent() {
    userScrollIntentRef.current = true;
  }

  function handleScrollKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (USER_SCROLL_KEYS.has(event.key)) {
      markUserScrollIntent();
    }
  }

  const loadPreview = useCallback(async (name: string, mode: "preview" | "full") => {
    const requestSeq = previewRequestSeqRef.current + 1;
    previewRequestSeqRef.current = requestSeq;
    setPreviewLoading(true);
    setError("");
    try {
      let result = mode === "full"
        ? await client.readFileFull(botAlias, name)
        : await client.readFile(botAlias, name);
      if (mode === "preview" && shouldAutoLoadFullHtmlPreview(name, result)) {
        result = await client.readFileFull(botAlias, name);
      }
      if (requestSeq !== previewRequestSeqRef.current) {
        return;
      }
      result = withDetectedPreviewKind(name, result);
      setPreviewName(name);
      setPreviewMode(result.mode === "cat" ? "full" : "preview");
      setPreviewResult(result);
      setPreviewContent(result.previewKind === "image" ? "" : result.content || "文件为空");
    } catch (err) {
      if (requestSeq === previewRequestSeqRef.current) {
        setError(err instanceof Error ? err.message : mode === "full" ? "读取全文失败" : "预览文件失败");
      }
    } finally {
      if (requestSeq === previewRequestSeqRef.current) {
        setPreviewLoading(false);
      }
    }
  }, [botAlias, client]);

  const downloadPreview = useCallback(async () => {
    if (!previewName) {
      return;
    }
    setPreviewDownloadProgress({ downloadedBytes: 0 });
    setError("");
    try {
      await client.downloadFile(botAlias, previewName, setPreviewDownloadProgress);
    } catch (err) {
      setError(err instanceof Error ? err.message : "下载文件失败");
    } finally {
      setPreviewDownloadProgress(null);
    }
  }, [botAlias, client, previewName]);

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

  const handleCopyFinalAnswer = useCallback(async (text: string) => {
    try {
      const ok = await copyText(text);
      if (!ok) {
        setError("复制最终回答失败，请检查浏览器剪贴板权限");
        return false;
      }
      return true;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "复制最终回答失败");
      return false;
    }
  }, []);

  const handleReplyNativePermission = useCallback(async (permissionId: string, approved: boolean) => {
    try {
      await client.replyNativeAgentPermission(botAlias, permissionId, {
        approved,
        agentId: activeAgentIdRef.current,
        executionMode: "native_agent",
      });
      setItems((prev) => prev.map((item) => {
        const nextMeta = markNativePermissionTraceReplied(item.meta, permissionId, approved);
        return nextMeta === item.meta ? item : { ...item, meta: nextMeta };
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "处理原生 agent 权限失败");
      throw err;
    }
  }, [botAlias, client]);

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
      const traceDetails = await getScopedMessageTrace(client, botAlias, messageId, activeAgentIdRef.current, executionModeRef.current);
      setItems((prev) => updateMessageByIdOrClientStateKey(prev, messageId, messageClientStateKey, (item) => ({
        ...item,
        meta: mergeMessageMeta(item.meta, {
          trace: traceDetails.trace,
          traceCount: traceDetails.traceCount,
          toolCallCount: traceDetails.toolCallCount,
          processCount: traceDetails.processCount,
          traceVersion: 1,
          ...(isNativeAgentMessage(item.meta) ? { tracePresentation: "native_agent_flat" as const } : {}),
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

  useEffect(() => {
    if (loading) {
      return;
    }
    for (const item of items) {
      if (item.role !== "assistant" || !isNativeAgentMessage(item.meta)) {
        continue;
      }
      const expectedTraceCount = item.meta?.traceCount || 0;
      const loadedTraceCount = (item.meta?.trace || []).length;
      if (expectedTraceCount <= 0 || loadedTraceCount >= expectedTraceCount) {
        continue;
      }
      const messageClientStateKey = getMessageClientStateKey(item);
      if (traceLoadState[messageClientStateKey]?.loading || traceLoadState[messageClientStateKey]?.error) {
        continue;
      }
      void loadMessageTrace(item.id);
      break;
    }
  }, [items, loadMessageTrace, loading, traceLoadState]);

  const loadConversations = useCallback(async (query = "") => {
    setConversationLoading(true);
    setError("");
    try {
      const data = await listScopedConversations(client, botAlias, query, activeAgentIdRef.current, executionModeRef.current);
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
      const data = await selectScopedConversation(client, botAlias, conversationId, activeAgentIdRef.current, executionModeRef.current);
      stopAssistantPoll();
      stopSseRecoveryWatch();
      stopClusterTaskPoll();
      setClusterRunId("");
      setClusterTaskStatus(null);
      setClusterTaskError("");
      clusterRunIdRef.current = "";
      setExpandedTracePanels({});
      setTraceLoadState({});
      setQueuedMessageState(null, { botAlias, agentId: activeAgentIdRef.current || "main" });
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
    if (executionModeRef.current === "native_agent" && activeAgentIdRef.current !== "main") {
      setError("子智能体只读，请回主 agent 发送；可用 @ 指派");
      return;
    }
    if (botOverview?.cluster?.enabled && activeAgentIdRef.current !== "main") {
      setError("子智能体只读，请回主 agent 发送；可用 @ 指派");
      return;
    }
    setConversationLoading(true);
    setError("");
    try {
      const data = await createScopedConversation(client, botAlias, activeAgentIdRef.current, executionModeRef.current);
      stopAssistantPoll();
      stopSseRecoveryWatch();
      stopClusterTaskPoll();
      setClusterRunId("");
      setClusterTaskStatus(null);
      setClusterTaskError("");
      clusterRunIdRef.current = "";
      setExpandedTracePanels({});
      setTraceLoadState({});
      setQueuedMessageState(null, { botAlias, agentId: activeAgentIdRef.current || "main" });
      setItems(data.messages);
      setConversations((prev) => [data.conversation, ...prev.map((item) => ({ ...item, active: false }))]);
      setHistoryPanelOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建会话失败");
    } finally {
      setConversationLoading(false);
    }
  }

  async function handleDeleteConversation(conversation: ConversationSummary, deleteNativeSession: boolean) {
    if (isStreamingRef.current) {
      setError("当前任务运行中，先终止或等待完成");
      return;
    }
    setDeletingConversationId(conversation.id);
    setConversationLoading(true);
    setError("");
    try {
      const data = await deleteScopedConversation(
        client,
        botAlias,
        conversation.id,
        activeAgentIdRef.current,
        deleteNativeSession,
        executionModeRef.current,
      );
      setConversations(data.items);
      if (conversation.active || data.messages) {
        const nextMessages = data.messages || [];
        stopAssistantPoll();
        stopSseRecoveryWatch();
        stopClusterTaskPoll();
        setClusterRunId("");
        setClusterTaskStatus(null);
        setClusterTaskError("");
        clusterRunIdRef.current = "";
        setExpandedTracePanels({});
        setTraceLoadState({});
        setPendingCronRuns([]);
        setQueuedMessageState(null, { botAlias, agentId: activeAgentIdRef.current || "main" });
        setItems(nextMessages);
        itemsRef.current = nextMessages;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除会话失败");
    } finally {
      setConversationLoading(false);
      setDeletingConversationId("");
    }
  }

  async function handleDeleteAllConversations(deleteNativeSession: boolean) {
    if (isStreamingRef.current) {
      setError("当前任务运行中，先终止或等待完成");
      return;
    }
    setDeletingConversationId("__all__");
    setConversationLoading(true);
    setError("");
    try {
      const data = await deleteAllScopedConversations(
        client,
        botAlias,
        activeAgentIdRef.current,
        deleteNativeSession,
        executionModeRef.current,
      );
      stopAssistantPoll();
      stopSseRecoveryWatch();
      stopClusterTaskPoll();
      setClusterRunId("");
      setClusterTaskStatus(null);
      setClusterTaskError("");
      clusterRunIdRef.current = "";
      setExpandedTracePanels({});
      setTraceLoadState({});
      setPendingCronRuns([]);
      setQueuedMessageState(null, { botAlias, agentId: activeAgentIdRef.current || "main" });
      setConversations(data.items);
      setItems(data.messages);
      itemsRef.current = data.messages;
      setHistoryPanelOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除全部会话失败");
    } finally {
      setConversationLoading(false);
      setDeletingConversationId("");
    }
  }

  const handleSelectAgent = useCallback((agentId: string) => {
    const normalized = agentId || "main";
    const previousAgentId = activeAgentIdRef.current || "main";
    setQueuedMessageState(null, { botAlias, agentId: previousAgentId });
    activeAgentIdRef.current = normalized;
    setActiveAgentId(normalized);
    window.localStorage.setItem(activeAgentStorageKey(botAlias, storageScope), normalized);
    assistantSendVersionRef.current += 1;
    stopAssistantPoll();
    stopSseRecoveryWatch();
    stopClusterTaskPoll();
    loadingRef.current = true;
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
    setQueuedMessage(null);
    queuedMessageRef.current = null;
    setHistoryPanelOpen(false);
    isStreamingRef.current = false;
    streamModeRef.current = "";
    setIsStreaming(false);
    setStreamMode("");
    setStreamStartedAtMs(null);

    Promise.all([
      listScopedMessages(client, botAlias, normalized, executionModeRef.current),
      getScopedOverview(client, botAlias, normalized, executionModeRef.current),
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
        const storedQueuedMessage = readStoredQueuedMessage(botAlias, normalized, storageScope);
        setQueuedMessageState(storedQueuedMessage, { botAlias, agentId: normalized });
        const { shouldPoll } = applyHistoryView(messages, overview, []);
        loadingRef.current = false;
        setLoading(false);
        if (!shouldPoll) {
          void drainQueuedMessageIfIdleRef.current?.({ botAlias, agentId: normalized });
        }
      })
      .catch((err: Error) => {
        if (activeAgentIdRef.current !== normalized) {
          return;
        }
        setError(err.message || "切换 agent 失败");
        loadingRef.current = false;
        setLoading(false);
      });
  }, [applyHistoryView, botAlias, client, restoreClusterRunFromOverview, setQueuedMessageState, stopAssistantPoll, stopClusterTaskPoll, stopSseRecoveryWatch, storageScope]);

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
    const sendBotAlias = botAlias;
    const sendAgentId = activeAgentIdRef.current || "main";
    const composedText = buildComposedMessageText(text, options.attachments || []);
    const hideProcessPreview = options.sendOptions?.taskMode === "dream";
    if (!composedText) {
      return;
    }

    const localStartedAtMs = Date.now();
    assistantSendVersionRef.current += 1;
    const sendVersion = assistantSendVersionRef.current;
    const displayUserText = options.sendOptions?.visibleText || composedText;
    const nativeStreaming = options.sendOptions?.executionMode === "native_agent" || executionModeRef.current === "native_agent";
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
      meta: nativeStreaming
        ? { tracePresentation: "native_agent_flat" }
        : undefined,
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
    isStreamingRef.current = true;
    streamModeRef.current = "sse";
    setIsStreaming(true);
    setStreamMode("sse");
    setStreamStartedAtMs(localStartedAtMs);
    sseLastActivityAtRef.current = localStartedAtMs;
    emitBotActivityForActiveAgent("busy");

    try {
      let usingPreviewReplace = false;
      let agUiState: AgUiRunState | null = null;
      let sawAgUiEvent = false;
      const onChunk = (chunk: string) => {
        if (sendVersion !== assistantSendVersionRef.current) {
          return;
        }
        markSseActivity();
        if (sawAgUiEvent) {
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
        if (sawAgUiEvent) {
          return;
        }
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
        if (status.contextUsage) {
          setItems((prev) => updateLatestAssistantMessage(prev, assistantId, localStartedAtMs, (item) => ({
            ...item,
            state: "streaming",
            meta: mergeMessageMeta(item.meta, { contextUsage: status.contextUsage }),
          })));
        }
        if (typeof status.replaceText === "string") {
          usingPreviewReplace = true;
          setItems((prev) => updateLatestAssistantMessage(prev, assistantId, localStartedAtMs, (item) => ({
            ...item,
            text: status.replaceText || "",
            state: "streaming",
          })));
        }
      };
      const onTrace = (traceEvent: ChatTraceEvent) => {
        if (sendVersion !== assistantSendVersionRef.current) {
          return;
        }
        markSseActivity();
        if (sawAgUiEvent) {
          return;
        }
        if (hideProcessPreview) {
          return;
        }
        setItems((prev) => updateLatestAssistantMessage(
          prev,
          assistantId,
          localStartedAtMs,
          (item) => {
            const isNativeTrace = executionModeRef.current === "native_agent"
              || String(traceEvent.source || "").trim().toLowerCase() === "native_agent";
            const nextItem = appendTraceToMessage(
              item,
              traceEvent,
              isNativeTrace ? "native_agent_flat" : undefined,
            );
            if (isNativeTrace) {
              return nextItem;
            }
            const canUseTracePreview = traceEvent.kind === "commentary"
              && Boolean(traceEvent.summary.trim())
              && !usingPreviewReplace
              && !item.text.trim();
            if (!canUseTracePreview) {
              return nextItem;
            }
            return {
              ...nextItem,
              text: traceEvent.summary,
              state: "streaming",
            };
          },
        ));
      };
      const onAgUiEvent = (event: AgUiEvent) => {
        if (sendVersion !== assistantSendVersionRef.current) {
          return;
        }
        markSseActivity();
        sawAgUiEvent = true;
        agUiState = reduceAgUiRunEvent(agUiState || createAgUiRunState(), event);
        const nextAgUiState = agUiState;
        if (typeof nextAgUiState.elapsedSeconds === "number") {
          setStreamStartedAtMs(resolveStreamStartMs(itemsRef.current, nextAgUiState.elapsedSeconds));
        }
        if (nextAgUiState.clusterRunId && nextAgUiState.clusterRunId !== clusterRunIdRef.current) {
          clusterRunIdRef.current = nextAgUiState.clusterRunId;
          setClusterRunId(nextAgUiState.clusterRunId);
          setClusterTaskStatus(null);
          setClusterTaskError("");
          void pollClusterTasks();
        }
        setItems((prev) => updateLatestAssistantMessage(
          prev,
          assistantId,
          localStartedAtMs,
          (item) => {
            const nextMeta = mergeMessageMeta(
              item.meta,
              buildLiveAgUiMessageMeta(nextAgUiState, executionModeRef.current === "native_agent"),
            );
            const completionState = nextMeta?.completionState || "";
            return {
              ...item,
              text: nextAgUiState.assistantText,
              state: nextAgUiState.error || (completionState && completionState !== "completed" && completionState !== "streaming")
                ? "error"
                : (nextAgUiState.completed ? "done" : "streaming"),
              meta: nextAgUiState.contextUsage
                ? mergeMessageMeta(nextMeta, { contextUsage: nextAgUiState.contextUsage })
                : nextMeta,
            };
          },
        ));
        setNativePermissionPending(hasPendingAgUiPermission(nextAgUiState));
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
          onAgUiEvent,
        )
        : (
          activeAgentIdRef.current === "main"
            ? await client.sendMessage(botAlias, composedText, onChunk, onStatus, onTrace, undefined, onAgUiEvent)
            : await client.sendMessage(botAlias, composedText, onChunk, onStatus, onTrace, {
              agentId: activeAgentIdRef.current,
            }, onAgUiEvent)
        );

      if (sendVersion !== assistantSendVersionRef.current) {
        return;
      }

      const elapsedSeconds = typeof finalMessage.elapsedSeconds === "number"
        ? finalMessage.elapsedSeconds
        : Math.max(0, Math.floor((Date.now() - localStartedAtMs) / 1000));
      const finalizedMessage: ChatMessage = normalizeResolvedFinalMessage({
        ...finalMessage,
        elapsedSeconds,
        ...(sawAgUiEvent && agUiState
          ? {
              meta: mergeMessageMeta(
                finalMessage.meta,
                buildLiveAgUiMessageMeta(agUiState, executionModeRef.current === "native_agent"),
              ),
            }
          : {}),
      });

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
      isStreamingRef.current = false;
      streamModeRef.current = "";
      setIsStreaming(false);
      setStreamMode("");
      setStreamStartedAtMs(null);
      setNativePermissionPending(false);
      emitBotActivityForActiveAgent("idle");
      void drainQueuedMessageIfIdleRef.current?.({ botAlias: sendBotAlias, agentId: sendAgentId });
    }
  }, [botAlias, client, markSseActivity, onUnreadResult, pollClusterTasks, stopAssistantPoll, stopClusterTaskPoll, stopSseRecoveryWatch]);

  drainQueuedMessageIfIdleRef.current = async (context) => {
    const targetBotAlias = context?.botAlias || botAlias;
    const targetAgentId = context?.agentId || activeAgentIdRef.current || "main";
    const nextQueuedMessage = queuedMessageRef.current;
    if (!nextQueuedMessage) {
      return;
    }
    if (targetBotAlias !== botAlias || targetAgentId !== (activeAgentIdRef.current || "main")) {
      return;
    }
    if (loadingRef.current || isStreamingRef.current) {
      return;
    }

    setQueuedMessageState(null, { botAlias: targetBotAlias, agentId: targetAgentId });
    await sendMessageInternal(nextQueuedMessage.text, {
      attachments: nextQueuedMessage.attachments,
      sendOptions: nextQueuedMessage.sendOptions,
    });
  };

  const handleExecutePlan = useCallback(async (messageId: string, content: string) => {
    const planContent = content.trim();
    if (!planContent) {
      return;
    }
    setExecutingPlanMessageId(messageId);
    setPlanExecuteError("");
    setConversationLoading(true);
    setError("");
    try {
      const currentExecutionMode = executionModeRef.current;
      const nativeSend = currentExecutionMode === "native_agent";
      const clusterSend = Boolean(botOverview?.cluster?.enabled);
      const mentions: AgentMention[] = [];
      const result = await client.executePlan(botAlias, {
        content: planContent,
        title: "执行方案",
        agentId: activeAgentIdRef.current !== "main" ? activeAgentIdRef.current : undefined,
        ...(nativeSend ? { executionMode: currentExecutionMode } : {}),
        ...(clusterSend ? { cluster: true, mentions } : {}),
      });
      stopAssistantPoll();
      stopSseRecoveryWatch();
      stopClusterTaskPoll();
      setClusterRunId("");
      setClusterTaskStatus(null);
      setClusterTaskError("");
      clusterRunIdRef.current = "";
      setExpandedTracePanels({});
      setTraceLoadState({});
      setQueuedMessageState(null, { botAlias, agentId: activeAgentIdRef.current || "main" });
      setItems(result.messages);
      setConversations((prev) => [result.conversation, ...prev.map((item) => ({ ...item, active: false }))]);
      setHistoryPanelOpen(false);
      setPlanMode(false);
      await sendMessageInternal(result.executionMessage, {
        sendOptions: nativeSend
          ? {
            taskMode: "standard",
            executionMode: currentExecutionMode,
            ...(clusterSend ? { cluster: true, mentions } : {}),
          }
          : clusterSend
            ? { taskMode: "standard", cluster: true, mentions }
            : { taskMode: "standard" },
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "执行方案失败";
      setPlanExecuteError(message);
      setError(message);
    } finally {
      setExecutingPlanMessageId("");
      setConversationLoading(false);
    }
  }, [botAlias, botOverview, client, sendMessageInternal, stopAssistantPoll, stopClusterTaskPoll, stopSseRecoveryWatch, setQueuedMessageState]);

  const handleSend = useCallback(async (text: string, mentions: AgentMention[] = []) => {
    const clusterMode = Boolean(botOverview?.cluster?.enabled);
    const currentExecutionMode = executionModeRef.current;
    const nativeSend = currentExecutionMode === "native_agent";
    if (nativeSend && activeAgentIdRef.current !== "main") {
      setError("子智能体只读，请回主 agent 发送；可用 @ 指派");
      return;
    }
    if (!nativeSend && clusterMode && activeAgentIdRef.current !== "main") {
      setError("子智能体只读，请回主 agent 发送；可用 @ 指派");
      return;
    }
    const clusterSend = clusterMode || mentions.length > 0;
    const isExecutingPlanPrompt = isPlanExecutionPrompt(text);
    if (planMode && isExecutingPlanPrompt) {
      setPlanMode(false);
    }
    const shouldSendPlanMode = planMode && !isExecutingPlanPrompt;
    const sendOptions = isExecutingPlanPrompt
      ? {
        taskMode: "standard" as const,
        ...(nativeSend ? { executionMode: currentExecutionMode } : {}),
        ...(clusterSend ? { cluster: true, mentions } : {}),
      }
      : shouldSendPlanMode
      ? {
        taskMode: "plan" as const,
        ...(nativeSend ? { executionMode: currentExecutionMode } : {}),
        ...(clusterSend ? { cluster: true, mentions } : {}),
      }
      : clusterSend
        ? {
          ...(nativeSend ? { executionMode: currentExecutionMode } : {}),
          cluster: true,
          mentions,
        }
        : nativeSend
          ? { executionMode: currentExecutionMode }
          : undefined;
    if (isStreamingRef.current) {
      const nextQueuedMessage: QueuedChatMessage = {
        text: text.trim(),
        attachments: pendingAttachments,
        sendOptions,
      };
      if (!buildComposedMessageText(nextQueuedMessage.text, nextQueuedMessage.attachments)) {
        return;
      }
      setError("");
      setQueuedMessageState(mergeQueuedChatMessage(queuedMessageRef.current, nextQueuedMessage));
      if (pendingAttachments.length > 0) {
        setPendingAttachments([]);
      }
      setComposerPulseKey((value) => value + 1);
      return;
    }
    setComposerPulseKey((value) => value + 1);
    await sendMessageInternal(text, {
      attachments: pendingAttachments,
      clearPendingAttachments: true,
      sendOptions,
    });
  }, [botOverview?.cluster?.enabled, pendingAttachments, planMode, sendMessageInternal, setPlanMode]);

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
      const currentExecutionMode = executionModeRef.current;
      const message = await client.killTask(botAlias, {
        ...(activeAgentIdRef.current !== "main" ? { agentId: activeAgentIdRef.current } : {}),
        ...(currentExecutionMode === "native_agent" ? { executionMode: currentExecutionMode } : {}),
      });
      appendSystemMessage(message || "已发送终止任务请求");
    } catch (err) {
      setError(err instanceof Error ? err.message : "终止任务失败");
    } finally {
      setActionLoading("");
    }
  }
  async function handleModelChange(nextModel: string) {
    if (!nextModel || nextModel === selectedModel) {
      return;
    }

    setModelSaving(true);
    setError("");
    try {
      if (nativeExecutionMode) {
        const nextModelItem = nativeModelOptions.find((model) => model.id === nextModel);
        const nextReasoningEffort = resolveNativeReasoningEffort(nextModelItem, nativeSelectedReasoningEffort);
        const next = await client.updateNativeAgentModel(botAlias, nextModel, { reasoningEffort: nextReasoningEffort });
        setNativeAgentModels({
          items: next.items,
          selectedModel: next.selectedModel,
          selectedReasoningEffort: next.selectedReasoningEffort,
        });
        if (next.bot) {
          const current = botOverviewRef.current;
          const overview = (current ? { ...current, ...next.bot } : { ...next.bot }) as BotOverview;
          botOverviewRef.current = overview;
          setBotOverview(overview);
        }
      } else if (cliParams) {
        const next = await client.updateCliParam(botAlias, "model", nextModel, cliParams.cliType);
        setCliParams(next);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "模型切换失败");
    } finally {
      setModelSaving(false);
    }
  }

  async function handleReasoningEffortChange(nextReasoningEffort: string) {
    if (!nativeExecutionMode || !nativeSelectedModel || nextReasoningEffort === nativeSelectedReasoningEffort) {
      return;
    }

    setModelSaving(true);
    setError("");
    try {
      const next = await client.updateNativeAgentModel(botAlias, nativeSelectedModel, { reasoningEffort: nextReasoningEffort });
      setNativeAgentModels({
        items: next.items,
        selectedModel: next.selectedModel,
        selectedReasoningEffort: next.selectedReasoningEffort,
      });
      if (next.bot) {
        const current = botOverviewRef.current;
        const overview = (current ? { ...current, ...next.bot } : { ...next.bot }) as BotOverview;
        botOverviewRef.current = overview;
        setBotOverview(overview);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "推理强度切换失败");
    } finally {
      setModelSaving(false);
    }
  }

  const handleExecutionModeChange = useCallback((mode: ChatExecutionMode) => {
    if (mode === executionModeRef.current || isStreamingRef.current) {
      return;
    }
    const previousAgentId = activeAgentIdRef.current || "main";
    const nextAgentId = mode === "native_agent" ? "main" : previousAgentId;
    setError("");
    setExecutionMode(mode);
    clearStoredQueuedMessage(botAlias, previousAgentId, storageScope);
    clearStoredQueuedMessage(botAlias, nextAgentId, storageScope);
    activeAgentIdRef.current = nextAgentId;
    setActiveAgentId(nextAgentId);
    window.localStorage.setItem(activeAgentStorageKey(botAlias, storageScope), nextAgentId);
    assistantSendVersionRef.current += 1;
    stopAssistantPoll();
    stopSseRecoveryWatch();
    stopClusterTaskPoll();
    loadingRef.current = true;
    setLoading(true);
    setError("");
    setItems([]);
    setConversations([]);
    setExpandedTracePanels({});
    setTraceLoadState({});
    setPendingCronRuns([]);
    setPendingAttachments([]);
    setQueuedMessage(null);
    queuedMessageRef.current = null;
    setClusterRunId("");
    setClusterTaskStatus(null);
    setClusterTaskError("");
    clusterRunIdRef.current = "";
    isStreamingRef.current = false;
    streamModeRef.current = "";
    setIsStreaming(false);
    setStreamMode("");
    setStreamStartedAtMs(null);

    Promise.all([
      listScopedMessages(client, botAlias, nextAgentId, mode),
      getScopedOverview(client, botAlias, nextAgentId, mode),
    ])
      .then(([messages, overview]) => {
        if (activeAgentIdRef.current !== nextAgentId || executionModeRef.current !== mode) {
          return;
        }
        setBotOverview(overview);
        setWorkingDir(overview.workingDir || "");
        restoreClusterRunFromOverview(overview);
        if (overview.agents && overview.agents.length > 0) {
          setAgents(overview.agents);
        }
        const { shouldPoll } = applyHistoryView(messages, overview, []);
        loadingRef.current = false;
        setLoading(false);
        if (historyPanelOpen) {
          void loadConversations(conversationQuery);
        }
        if (!shouldPoll) {
          void drainQueuedMessageIfIdleRef.current?.({ botAlias, agentId: nextAgentId });
        }
      })
      .catch((err: Error) => {
        if (activeAgentIdRef.current !== nextAgentId || executionModeRef.current !== mode) {
          return;
        }
        setError(err.message || "切换执行模式失败");
        loadingRef.current = false;
        setLoading(false);
      });
  }, [
    applyHistoryView,
    botAlias,
    client,
    conversationQuery,
    historyPanelOpen,
    loadConversations,
    restoreClusterRunFromOverview,
    setExecutionMode,
    setPlanMode,
    stopAssistantPoll,
    stopClusterTaskPoll,
    stopSseRecoveryWatch,
    storageScope,
  ]);

  const handleSaveGlobalPromptPresets = useCallback(async (presets: PromptPreset[]) => {
    const nextPresets = await client.updateGlobalPromptPresets(presets);
    setBotOverview((prev) => {
      if (!prev || prev.alias !== botAlias) {
        return prev;
      }
      const next = { ...prev, globalPromptPresets: nextPresets };
      botOverviewRef.current = next;
      return next;
    });
  }, [botAlias, client]);

  const handleSaveBotPromptPresets = useCallback(async (presets: PromptPreset[]) => {
    const updated = await client.updateBotPromptPresets(botAlias, presets);
    const nextPresets = updated.promptPresets || [];
    setBotOverview((prev) => {
      if (!prev || prev.alias !== botAlias) {
        return prev;
      }
      const next = { ...prev, promptPresets: nextPresets };
      botOverviewRef.current = next;
      return next;
    });
  }, [botAlias, client]);

  const terminateVisible = isStreaming || actionLoading === "kill";
  const assistantName = botAlias;
  const assistantAvatarName = botOverview?.avatarName || botAvatarName;
  const activeAgent = agents.find((agent) => agent.id === activeAgentId) || agents[0] || fallbackAgents()[0];
  const supportedExecutionModes = getSupportedExecutionModes(botOverview);
  const effectiveExecutionMode = supportedExecutionModes.includes(executionMode) ? executionMode : getDefaultExecutionMode(botOverview);
  const nativeExecutionMode = effectiveExecutionMode === "native_agent";
  const clusterMode = Boolean(botOverview?.cluster?.enabled);
  const activeClusterChildReadOnly = clusterMode && activeAgentId !== "main";
  const activeNativeReadOnly = nativeExecutionMode && activeAgentId !== "main";
  const chatMutationsDisabled = readOnly || activeClusterChildReadOnly || activeNativeReadOnly;
  const chatDisabledReason = nativePermissionPending
    ? "等待权限处理"
    : activeNativeReadOnly
    ? "子智能体只读，请回主 agent 发送；可用 @ 指派"
    : activeClusterChildReadOnly
    ? "子智能体只读，请回主 agent 发送；可用 @ 指派"
    : disabledReason || readOnlyReason || (readOnly ? "主机已关闭聊天，当前无法发送消息" : "");
  const killTaskDisabled = chatMutationsDisabled || !isStreaming || actionLoading === "kill";
  const overviewAgents = botOverview?.agents && botOverview.agents.length > 0 ? botOverview.agents : agents;
  const clusterAgents = overviewAgents.filter((agent) => !agent.isMain && agent.enabled);
  const showAgentSwitcher = agents.length > 1;
  const showClusterToggle = Boolean(botOverview?.cluster) && botOverview?.botMode !== "assistant";
  const showActionBar = !isImmersive;
  const showImmersiveButton = !embedded && isVisible && Boolean(onToggleImmersive);
  const canManagePromptPresets = !readOnly && (botOverview?.effectiveCapabilities
    ? botOverview.effectiveCapabilities.includes("admin_ops")
    : true);
  const cliModelOptions = cliParams?.schema.model?.enum ?? [];
  const nativeModelOptions = nativeAgentModels?.items ?? [];
  const nativeSelectedModel = nativeAgentModels?.selectedModel
    || botOverview?.nativeAgent?.model
    || nativeModelOptions[0]?.id
    || "";
  const nativeSelectedModelItem = nativeModelOptions.find((model) => model.id === nativeSelectedModel);
  const nativeReasoningEffortOptions = nativeSelectedModelItem?.reasoningEfforts || [];
  const nativeSelectedReasoningEffort = resolveNativeReasoningEffort(
    nativeSelectedModelItem,
    nativeAgentModels?.selectedReasoningEffort || botOverview?.nativeAgent?.reasoningEffort,
  );
  const selectedModel = nativeExecutionMode
    ? nativeSelectedModel
    : toModelOptionValue(cliParams?.params.model, cliModelOptions);
  const visibleModelOptions = useMemo<ChatModelOption[]>(() => {
    if (nativeExecutionMode) {
      const options = nativeModelOptions.map((model) => ({
        value: model.id,
        label: model.label || `${model.provider} / ${model.name || model.model}`,
        title: modelLimitTitle(model.contextWindow, model.outputLimit),
      }));
      if (nativeSelectedModel && !options.some((item) => item.value === nativeSelectedModel)) {
        return [{ value: nativeSelectedModel, label: nativeSelectedModel }, ...options];
      }
      return options;
    }
    const options = cliModelOptions.map((model) => ({ value: model, label: model }));
    if (selectedModel && !cliModelOptions.includes(selectedModel)) {
      return [{ value: selectedModel, label: selectedModel }, ...options];
    }
    return options;
  }, [cliModelOptions, nativeExecutionMode, nativeModelOptions, nativeSelectedModel, selectedModel]);
  const messageContentWidthClass = embedded ? "mx-auto w-full max-w-5xl space-y-4" : "w-full space-y-4";
  const composerPlaceholder = chatDisabledReason
    || (clusterMode ? "@ 可指定智能体集群" : (showAgentSwitcher && !nativeExecutionMode ? `发给 ${activeAgent.name}...` : "输入消息"));
  const deletedAttachmentKeysByMessage = useMemo(() => {
    const next: Record<string, Record<string, boolean>> = {};
    for (const [key, value] of Object.entries(deletedAttachmentKeys)) {
      const separatorIndex = key.indexOf("|");
      if (separatorIndex <= 0) {
        continue;
      }
      const messageId = key.slice(0, separatorIndex);
      next[messageId] = next[messageId] || {};
      next[messageId][key] = value;
    }
    return next;
  }, [deletedAttachmentKeys]);
  const deletingAttachmentKeysByMessage = useMemo(() => {
    const next: Record<string, Record<string, boolean>> = {};
    for (const [key, value] of Object.entries(deletingAttachmentKeys)) {
      const separatorIndex = key.indexOf("|");
      if (separatorIndex <= 0) {
        continue;
      }
      const messageId = key.slice(0, separatorIndex);
      next[messageId] = next[messageId] || {};
      next[messageId][key] = value;
    }
    return next;
  }, [deletingAttachmentKeys]);
  const hiddenHistoryCount = historyExpanded ? 0 : Math.max(0, items.length - CHAT_RENDER_WINDOW_SIZE);
  const visibleItems = useMemo(
    () => (hiddenHistoryCount > 0 ? items.slice(hiddenHistoryCount) : items),
    [hiddenHistoryCount, items],
  );
  const messageRowModels = useMemo<ChatMessageRowModel[]>(() => visibleItems.map((item) => {
    const messageClientStateKey = getMessageClientStateKey(item);
    const planDraft = item.role === "assistant" && item.state === "done"
      ? extractPlanDraft(item.text)
      : "";
    const displayItem = planDraft ? { ...item, text: stripPlanDraftTags(item.text) } : item;
    return {
      item: displayItem,
      messageClientStateKey,
      planDraft,
      deletedAttachmentKeys: deletedAttachmentKeysByMessage[item.id] || EMPTY_ATTACHMENT_STATE,
      deletingAttachmentKeys: deletingAttachmentKeysByMessage[item.id] || EMPTY_ATTACHMENT_STATE,
    };
  }), [deletedAttachmentKeysByMessage, deletingAttachmentKeysByMessage, visibleItems]);

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
    <main className="relative flex h-full flex-col bg-[var(--workbench-panel-bg)]">
      {showActionBar ? (
        <ChatActionBar
          visibleModelOptions={visibleModelOptions}
          selectedModel={selectedModel}
          modelDisabled={modelSaving || readOnly || visibleModelOptions.length === 0 || (!nativeExecutionMode && !cliParams)}
          onModelChange={(model) => void handleModelChange(model)}
          reasoningEffortOptions={nativeReasoningEffortOptions}
          selectedReasoningEffort={nativeSelectedReasoningEffort}
          reasoningEffortDisabled={modelSaving || readOnly || !nativeExecutionMode}
          onReasoningEffortChange={(effort) => void handleReasoningEffortChange(effort)}
          executionMode={effectiveExecutionMode}
          supportedExecutionModes={supportedExecutionModes}
          executionModeDisabled={loading || isStreaming || readOnly}
          onExecutionModeChange={handleExecutionModeChange}
          agents={showAgentSwitcher ? agents : []}
          activeAgentId={activeAgentId}
          agentDisabled={loading || nativeExecutionMode}
          onSelectAgent={handleSelectAgent}
          showClusterToggle={showClusterToggle}
          clusterMode={clusterMode}
          clusterSaving={clusterSaving}
          clusterDisabled={loading || isStreaming || clusterSaving || readOnly}
          onToggleClusterMode={() => void handleToggleClusterMode()}
          planMode={planMode}
          planDisabled={loading || isStreaming || chatMutationsDisabled}
          onTogglePlanMode={() => setPlanMode((value) => !value)}
          embedded={embedded}
          focused={focused}
          onToggleFocus={onToggleFocus}
          onOpenHistoryPanel={() => void handleOpenHistoryPanel()}
          onKillTask={terminateVisible ? () => void handleKillTask() : undefined}
          killTaskDisabled={killTaskDisabled}
          killTaskBusy={actionLoading === "kill"}
        />
      ) : null}
      {showAssistantRuntimeBanner ? (
        <section
          data-workbench-status="active"
          className="chat-runtime-banner border-b border-amber-200 bg-amber-50 px-4 py-3 text-amber-900 shadow-[var(--shadow-soft)]"
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
      {chatDisabledReason ? (
        <section className="border-b border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-900 shadow-[var(--shadow-soft)]">
          {chatDisabledReason}
        </section>
      ) : null}
      <section
        ref={scrollContainerRef}
        data-testid="chat-scroll-container"
        onScroll={updateAutoScrollStickiness}
        onWheel={markUserScrollIntent}
        onTouchMove={markUserScrollIntent}
        onKeyDown={handleScrollKeyDown}
        className={isImmersive ? "flex-1 overflow-y-auto bg-[var(--workbench-panel-bg)] px-4 pb-24 pt-4" : "flex-1 overflow-y-auto bg-[var(--workbench-panel-bg)] p-4"}
      >
        <div ref={scrollContentRef} data-testid="chat-scroll-content" className={messageContentWidthClass}>
          {loading ? (
            <div className="mt-10 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-4 py-8 text-center text-sm text-[var(--muted)] shadow-[var(--shadow-soft)]">加载中...</div>
          ) : null}
          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 shadow-[var(--shadow-soft)]">
              {error}
            </div>
          ) : null}
          {items.length === 0 && !isStreaming && !loading ? (
            <div className="mt-10 rounded-lg border border-dashed border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-4 py-10 text-center text-sm text-[var(--muted)]">
              暂无消息，开始聊天吧
            </div>
          ) : null}
          {hiddenHistoryCount > 0 ? (
            <div className="flex justify-center">
              <button
                type="button"
                onClick={() => setHistoryExpanded(true)}
                className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-3 py-1.5 text-xs text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)]"
              >
                展开较早消息（{hiddenHistoryCount}）
              </button>
            </div>
          ) : null}
          <ChatMessageList
            rows={messageRowModels}
            assistantName={assistantName}
            assistantAvatarName={assistantAvatarName}
            userAvatarName={userAvatarName}
            allowTrace={allowTrace}
            expandedTracePanels={expandedTracePanels}
            traceLoadState={traceLoadState}
            handleDeleteAttachment={handleDeleteAttachment}
            handleFileLinkClick={handleFileLinkClick}
            loadMessageTrace={loadMessageTrace}
            handleToggleTracePanel={handleToggleTracePanel}
            handleCopyFinalAnswer={handleCopyFinalAnswer}
            handleReplyNativePermission={handleReplyNativePermission}
            executingPlanMessageId={executingPlanMessageId}
            planExecuteError={planExecuteError}
            handleExecutePlan={handleExecutePlan}
            wideMessages={!embedded}
          />
          {clusterTaskStatus ? (
            <ClusterTaskPanel
              status={clusterTaskStatus}
              agents={botOverview?.agents && botOverview.agents.length > 0 ? botOverview.agents : agents}
            />
          ) : null}
          {clusterTaskError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 shadow-[var(--shadow-soft)]">
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
        deletingConversationId={deletingConversationId}
        onQueryChange={(nextQuery) => {
          setConversationQuery(nextQuery);
          void loadConversations(nextQuery);
        }}
        onClose={() => setHistoryPanelOpen(false)}
        onNewConversation={() => void handleNewConversation()}
        onSelectConversation={(conversationId) => void handleSelectConversation(conversationId)}
        onDeleteConversation={(conversation, deleteNativeSession) => void handleDeleteConversation(conversation, deleteNativeSession)}
        onDeleteAllConversations={(deleteNativeSession) => void handleDeleteAllConversations(deleteNativeSession)}
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
      <div className="border-t border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)]">
        {chatMutationsDisabled || nativePermissionPending ? (
          <p className="px-4 pt-3 text-xs font-medium text-amber-700">{chatDisabledReason || "只读模式"}</p>
        ) : null}
        {queuedMessage ? (
          <div className="mx-3 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 shadow-[var(--shadow-soft)]">
            <div className="font-medium">排队中</div>
            <div className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words">
              {buildComposedMessageText(queuedMessage.text, queuedMessage.attachments)}
            </div>
          </div>
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
          disabled={chatMutationsDisabled || nativePermissionPending || loading}
          compact={isImmersive || embedded}
          uploadingAttachments={uploadingAttachments}
          placeholder={composerPlaceholder}
          globalPromptPresets={botOverview?.globalPromptPresets || []}
          botPromptPresets={botOverview?.promptPresets || []}
          canManagePromptPresets={canManagePromptPresets}
          onSaveGlobalPromptPresets={handleSaveGlobalPromptPresets}
          onSaveBotPromptPresets={handleSaveBotPromptPresets}
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
            setPreviewDownloadProgress(null);
          }}
          onLoadFull={previewMode !== "full" && canLoadFull ? () => void loadPreview(previewName, "full") : undefined}
          onDownload={() => void downloadPreview()}
          downloadProgressText={previewDownloadProgress ? formatDownloadProgress(previewDownloadProgress) : ""}
          downloadPercent={previewDownloadProgress?.percent}
        />
      ) : null}
    </main>
  );
}
