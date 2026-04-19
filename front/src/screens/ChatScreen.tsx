import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { LoaderCircle, Maximize2, Minimize2, RotateCcw, Square, Terminal } from "lucide-react";
import { BotIdentity } from "../components/BotIdentity";
import { ChatAvatar } from "../components/ChatAvatar";
import { ChatComposer } from "../components/ChatComposer";
import { ChatMessageActions } from "../components/ChatMessageActions";
import { ChatMessageMeta } from "../components/ChatMessageMeta";
import { ChatMarkdownMessage } from "../components/ChatMarkdownMessage";
import { ChatPlainTextMessage } from "../components/ChatPlainTextMessage";
import { ChatTracePanel } from "../components/ChatTracePanel";
import { FilePreviewDialog } from "../components/FilePreviewDialog";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  BotOverview,
  ChatMessage,
  ChatMessageMetaInfo,
  ChatTraceEvent,
  FileReadResult,
  SystemScript,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  ASSISTANT_CRON_RUN_ENQUEUED_EVENT,
  isAssistantCronRunEnqueuedEvent,
  type AssistantCronRunEnqueuedDetail,
} from "../utils/assistantCronEvents";
import { resolvePreviewFilePath } from "../utils/fileLinks";
import {
  getFilePreviewStatusText,
  isFilePreviewFullyLoaded,
  isFilePreviewTooLarge,
} from "../utils/filePreview";
import type { ChatWorkbenchStatus } from "../workbench/workbenchTypes";

type Props = {
  botAlias: string;
  client?: WebBotClient;
  botAvatarName?: string;
  userAvatarName?: string;
  isVisible?: boolean;
  isImmersive?: boolean;
  embedded?: boolean;
  focused?: boolean;
  onToggleFocus?: () => void;
  onToggleImmersive?: () => void;
  onUnreadResult?: (botAlias: string) => void;
  onWorkbenchStatusChange?: (status: ChatWorkbenchStatus) => void;
};

const ACTIVE_ASSISTANT_POLL_INTERVAL_MS = 1000;
const IDLE_ASSISTANT_POLL_INTERVAL_MS = 5000;

function getCompactScriptTitle(script: SystemScript) {
  const source = (script.displayName || script.description || script.scriptName).trim();
  if (!source) {
    return script.scriptName;
  }
  const firstSentence = source.split(/[。.!?！？;\n]/)[0]?.trim();
  return firstSentence || script.scriptName;
}

function pendingCronUserId(runId: string) {
  return `assistant-cron-user-${runId}`;
}

function pendingCronAssistantId(runId: string) {
  return `assistant-cron-assistant-${runId}`;
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

function countPersistedHistoryItems(items: ChatMessage[]) {
  return items.filter((item) => !item.id.startsWith("assistant-cron-")).length;
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

function mergeMessageMeta(base?: ChatMessageMetaInfo, incoming?: ChatMessageMetaInfo): ChatMessageMetaInfo | undefined {
  const trace = mergeTraceEvents(base?.trace, incoming?.trace);
  const meta: ChatMessageMetaInfo = {
    completionState: incoming?.completionState || base?.completionState,
    summaryKind: incoming?.summaryKind || base?.summaryKind,
    traceVersion: incoming?.traceVersion ?? base?.traceVersion ?? (trace ? 1 : undefined),
    traceCount: incoming?.traceCount ?? base?.traceCount ?? trace?.length,
    toolCallCount: incoming?.toolCallCount ?? base?.toolCallCount ?? trace?.filter((event) => event.kind === "tool_call").length,
    processCount: incoming?.processCount ?? base?.processCount ?? trace?.filter((event) => event.kind !== "tool_call" && event.kind !== "tool_result").length,
    nativeSource: incoming?.nativeSource || base?.nativeSource,
    trace,
  };

  return Object.values(meta).some((value) => typeof value !== "undefined") ? meta : undefined;
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

type ChatMessageRowProps = {
  item: ChatMessage;
  previousRole: string;
  assistantName: string;
  assistantAvatarName?: string;
  userAvatarName?: string;
  isCopied: boolean;
  tracePanelExpanded: boolean;
  traceLoadState?: { loading: boolean; error?: string };
  onFileLinkClick: (href: string) => void;
  onLoadTrace: (messageId: string) => void;
  onToggleTracePanel: () => void;
  onCopyMessage: (item: ChatMessage) => void;
};

const ChatMessageRow = memo(function ChatMessageRow({
  item,
  previousRole,
  assistantName,
  assistantAvatarName,
  userAvatarName,
  isCopied,
  tracePanelExpanded,
  traceLoadState,
  onFileLinkClick,
  onLoadTrace,
  onToggleTracePanel,
  onCopyMessage,
}: ChatMessageRowProps) {
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
  const trace = item.meta?.trace;
  const traceCount = typeof item.meta?.traceCount === "number" ? item.meta.traceCount : trace?.length ?? 0;
  const hasTracePanel = item.role === "assistant" && traceCount > 0;
  const canCopyAssistantMessage = item.role === "assistant" && item.state !== "streaming" && item.state !== "error";
  const showInlineMobileAvatar = previousRole !== item.role;
  const inlineAvatar = showInlineMobileAvatar ? (
    <span className="sm:hidden">
      <ChatAvatar
        alt={`${messageName} 头像`}
        avatarName={isUser ? userAvatarName : assistantAvatarName}
        kind={isUser ? "user" : "bot"}
        size={20}
      />
    </span>
  ) : null;

  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div className={`flex max-w-[94%] items-start gap-3 sm:max-w-[88%] ${isUser ? "flex-row-reverse" : "flex-row"}`}>
        <div className="hidden shrink-0 sm:flex items-start">
          <ChatAvatar
            alt={`${messageName} 头像`}
            avatarName={isUser ? userAvatarName : assistantAvatarName}
            kind={isUser ? "user" : "bot"}
            size={32}
          />
        </div>
        <div className="min-w-0">
          <ChatMessageMeta
            name={messageName}
            createdAt={item.createdAt}
            align={isUser ? "right" : "left"}
            avatar={inlineAvatar}
          />
          <div
            className={
              isUser
                ? "rounded-2xl bg-[var(--accent)] px-4 py-2 text-white"
                : item.state === "error"
                  ? "rounded-2xl border border-red-200 bg-red-50 px-4 py-2 text-red-700"
                  : "min-w-0 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-[var(--text)]"
            }
          >
            {item.role === "assistant" && item.state !== "streaming" && item.state !== "error" ? (
              <ChatMarkdownMessage content={item.text} onFileLinkClick={onFileLinkClick} />
            ) : (
              <ChatPlainTextMessage
                content={item.text || (item.state === "streaming" ? "正在输出..." : "")}
                className={isUser ? "text-white" : item.state === "error" ? "text-red-700" : "text-[var(--text)]"}
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
              elapsedSeconds={item.elapsedSeconds}
              expanded={tracePanelExpanded}
              onToggleExpanded={onToggleTracePanel}
              isLoading={Boolean(traceLoadState?.loading)}
              loadError={traceLoadState?.error}
              onLoadTrace={() => void onLoadTrace(item.id)}
            />
          ) : null}
          {canCopyAssistantMessage && !hasTracePanel ? (
            <ChatMessageActions
              elapsedSeconds={item.elapsedSeconds}
              copyLabel={isCopied ? "已复制" : "复制"}
              onCopy={() => void onCopyMessage(item)}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
});

export function ChatScreen({
  botAlias,
  client = new MockWebBotClient(),
  botAvatarName,
  userAvatarName,
  isVisible = true,
  isImmersive = false,
  embedded = false,
  focused = false,
  onToggleFocus,
  onToggleImmersive,
  onUnreadResult,
  onWorkbenchStatusChange,
}: Props) {
  const [items, setItems] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamMode, setStreamMode] = useState<"" | "sse" | "poll">("");
  const [streamStartedAtMs, setStreamStartedAtMs] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [workingDir, setWorkingDir] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [actionLoading, setActionLoading] = useState<"" | "reset" | "kill" | "scripts">("");
  const [showScripts, setShowScripts] = useState(false);
  const [scripts, setScripts] = useState<SystemScript[]>([]);
  const [scriptError, setScriptError] = useState("");
  const [runningScriptName, setRunningScriptName] = useState("");
  const [previewName, setPreviewName] = useState("");
  const [previewContent, setPreviewContent] = useState("");
  const [previewMode, setPreviewMode] = useState<"preview" | "full">("preview");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewResult, setPreviewResult] = useState<FileReadResult | null>(null);
  const [botOverview, setBotOverview] = useState<BotOverview | null>(null);
  const [pendingCronRuns, setPendingCronRuns] = useState<AssistantCronRunEnqueuedDetail[]>([]);
  const [copiedMessageId, setCopiedMessageId] = useState("");
  const [expandedTracePanels, setExpandedTracePanels] = useState<Record<string, boolean>>({});
  const [traceLoadState, setTraceLoadState] = useState<Record<string, { loading: boolean; error?: string }>>({});
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null);
  const scrollContainerRef = useRef<HTMLElement | null>(null);
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
  const assistantPollTimerRef = useRef<number | null>(null);
  const pollAssistantStateRef = useRef<(() => Promise<void>) | null>(null);

  useEffect(() => {
    isVisibleRef.current = isVisible;
  }, [isVisible]);

  useEffect(() => {
    loadingRef.current = loading;
  }, [loading]);

  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  useEffect(() => {
    streamModeRef.current = streamMode;
  }, [streamMode]);

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

  const applyHistoryView = useCallback((
    messages: ChatMessage[],
    overview: BotOverview,
    pendingRuns: AssistantCronRunEnqueuedDetail[],
  ) => {
    const nextItems = mergePendingCronRuns(messages, pendingRuns);
    const hasStreamingRow = nextItems.some((item) => item.role === "assistant" && item.state === "streaming");
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

  const scheduleAssistantPoll = useCallback((delayMs = ACTIVE_ASSISTANT_POLL_INTERVAL_MS) => {
    stopAssistantPoll();
    assistantPollTimerRef.current = window.setTimeout(() => {
      assistantPollTimerRef.current = null;
      void pollAssistantStateRef.current?.();
    }, delayMs);
  }, [stopAssistantPoll]);

  pollAssistantStateRef.current = async () => {
    try {
      const overview = await client.getBotOverview(botAlias);

      setBotOverview(overview);
      setWorkingDir(overview.workingDir || "");
      const previousCount = countPersistedHistoryItems(itemsRef.current);

      const nextPendingRuns = resolvePendingCronRuns(
        pendingCronRunsRef.current,
        itemsRef.current,
      );
      if (nextPendingRuns.length !== pendingCronRunsRef.current.length) {
        setPendingCronRuns(nextPendingRuns);
      }

      const shouldRefreshMessages = Boolean(
        overview.isProcessing
        || overview.runningReply
        || nextPendingRuns.length > 0
        || (typeof overview.historyCount === "number" && overview.historyCount !== previousCount),
      );

      const messages = shouldRefreshMessages
        ? await client.listMessages(botAlias)
        : itemsRef.current.filter((item) => !item.id.startsWith("assistant-cron-"));

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
    setCopiedMessageId("");
    setExpandedTracePanels({});
    setTraceLoadState({});
    shouldStickToBottomRef.current = true;
    forceAutoScrollRef.current = true;

    Promise.all([client.listMessages(botAlias), client.getBotOverview(botAlias)])
      .then(([messages, overview]) => {
        if (cancelled) return;
        setBotOverview(overview);
        setWorkingDir(overview.workingDir || "");
        applyHistoryView(messages, overview, []);
        setLoading(false);
        if (isVisible && (overview.isProcessing || overview.botMode === "assistant")) {
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
    };
  }, [applyHistoryView, botAlias, client, isVisible, scheduleAssistantPoll, stopAssistantPoll]);

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

  useEffect(() => {
    onWorkbenchStatusChange?.({
      state: error ? "error" : isStreaming ? "running" : loading ? "waiting" : "idle",
      processing: isStreaming,
      elapsedSeconds: isStreaming ? elapsedSeconds : undefined,
      lastError: error || undefined,
    });
  }, [elapsedSeconds, error, isStreaming, loading, onWorkbenchStatusChange]);

  useLayoutEffect(() => {
    const shouldPoll = streamMode === "poll" || (Boolean(isAssistantBot) && isVisible && !loading && !isStreaming);
    if (!shouldPoll) {
      stopAssistantPoll();
      return;
    }
    scheduleAssistantPoll(streamMode === "poll" ? ACTIVE_ASSISTANT_POLL_INTERVAL_MS : IDLE_ASSISTANT_POLL_INTERVAL_MS);
  }, [isAssistantBot, isStreaming, isVisible, loading, scheduleAssistantPoll, stopAssistantPoll, streamMode]);

  const lastItem = items[items.length - 1];

  useEffect(() => {
    if (!isVisible || loading) {
      return;
    }
    if (!forceAutoScrollRef.current && !shouldStickToBottomRef.current) {
      return;
    }
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
    forceAutoScrollRef.current = false;
  }, [isVisible, isStreaming, lastItem?.id, lastItem?.state, lastItem?.text, loading, items.length]);

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
      setPreviewContent(result.content || "文件为空");
    } catch (err) {
      setError(err instanceof Error ? err.message : mode === "full" ? "读取全文失败" : "预览文件失败");
    } finally {
      setPreviewLoading(false);
    }
  }, [botAlias, client]);

  const previewStatusText = getFilePreviewStatusText(previewResult);
  const canLoadFull = !isFilePreviewFullyLoaded(previewResult) && !isFilePreviewTooLarge(previewResult?.fileSizeBytes);

  const handleFileLinkClick = useCallback((href: string) => {
    const nextPath = resolvePreviewFilePath(href, workingDirRef.current);
    if (!nextPath) {
      setError("暂不支持预览该文件链接");
      return;
    }
    void loadPreview(nextPath, "preview");
  }, [loadPreview]);

  const loadMessageTrace = useCallback(async (messageId: string) => {
    const currentMessage = itemsRef.current.find((item) => item.id === messageId);
    if (!currentMessage || currentMessage.role !== "assistant") {
      return;
    }
    const messageClientStateKey = getMessageClientStateKey(currentMessage);
    if ((currentMessage.meta?.trace || []).length > 0) {
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
      const traceDetails = await client.getMessageTrace(botAlias, messageId);
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

  const handleSend = useCallback(async (text: string) => {
    const localStartedAtMs = Date.now();
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      text,
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
    forceAutoScrollRef.current = true;
    shouldStickToBottomRef.current = true;
    setItems((prev) => [...prev, userMessage, assistantMessage]);
    setIsStreaming(true);
    setStreamMode("sse");
    setStreamStartedAtMs(localStartedAtMs);

    try {
      let usingPreviewReplace = false;
      const finalMessage = await client.sendMessage(
        botAlias,
        text,
        (chunk) => {
          if (usingPreviewReplace) {
            return;
          }
          setItems((prev) => updateMessageById(prev, assistantId, (item) => ({
            ...item,
            text: item.text + chunk,
            state: "streaming",
          })));
        },
        (status) => {
          if (typeof status.elapsedSeconds === "number") {
            setStreamStartedAtMs(resolveStreamStartMs(itemsRef.current, status.elapsedSeconds));
          }
          if (status.previewText) {
            usingPreviewReplace = true;
            setItems((prev) => updateMessageById(prev, assistantId, (item) => ({
              ...item,
              text: status.previewText || item.text,
              state: "streaming",
            })));
          }
        },
        (traceEvent) => {
          setItems((prev) => updateMessageById(prev, assistantId, (item) => appendTraceToMessage(item, traceEvent)));
        },
      );

      const elapsedSeconds = typeof finalMessage.elapsedSeconds === "number"
        ? finalMessage.elapsedSeconds
        : Math.max(0, Math.floor((Date.now() - localStartedAtMs) / 1000));
      const finalizedMessage: ChatMessage = {
        ...finalMessage,
        elapsedSeconds,
      };

      setItems((prev) => updateMessageById(prev, assistantId, (item) => ({
        ...finalizedMessage,
        meta: mergeMessageMeta(item.meta, finalizedMessage.meta),
      })));
      if (!isVisibleRef.current) {
        onUnreadResult?.(botAlias);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "发送失败";
      setError(message);
      setItems((prev) => updateMessageById(prev, assistantId, (item) => ({
        ...item,
        text: message,
        state: "error",
      })));
    } finally {
      setIsStreaming(false);
      setStreamMode("");
      setStreamStartedAtMs(null);
    }
  }, [botAlias, client, onUnreadResult]);

  async function handleResetSession() {
    setActionLoading("reset");
    setError("");
    try {
      await client.resetSession(botAlias);
      setExpandedTracePanels({});
      setTraceLoadState({});
      setItems([]);
      appendSystemMessage("当前会话已重置");
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置会话失败");
    } finally {
      setActionLoading("");
    }
  }

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

  async function handleOpenScripts() {
    setActionLoading("scripts");
    setScriptError("");
    try {
      const nextScripts = await client.listSystemScripts(botAlias);
      setScripts(nextScripts);
      setShowScripts(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载系统功能失败");
    } finally {
      setActionLoading("");
    }
  }

  async function handleRunScript(script: SystemScript) {
    setRunningScriptName(script.scriptName);
    setScriptError("");
    try {
      const result = await client.runSystemScript(botAlias, script.scriptName);
      appendSystemMessage(
        [
          `系统功能：${script.displayName}`,
          result.success ? "执行结果：成功" : "执行结果：失败",
          result.output || "无输出",
        ].join("\n"),
      );
      setShowScripts(false);
    } catch (err) {
      setScriptError(err instanceof Error ? err.message : "执行系统功能失败");
    } finally {
      setRunningScriptName("");
    }
  }

  const handleCopyMessage = useCallback(async (item: ChatMessage) => {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("当前环境不支持复制");
      }
      await navigator.clipboard.writeText(item.text);
      setCopiedMessageId(item.id);
      window.setTimeout(() => {
        setCopiedMessageId((prev) => (prev === item.id ? "" : prev));
      }, 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : "复制失败");
    }
  }, []);

  const killTaskActive = isStreaming || actionLoading === "kill";
  const killTaskDisabled = !isStreaming || actionLoading === "kill";
  const assistantName = botAlias;
  const assistantAvatarName = botOverview?.avatarName || botAvatarName;
  const showTopChrome = !embedded && !isImmersive;
  const showActionBar = !isImmersive;
  const showImmersiveButton = !embedded && isVisible && Boolean(onToggleImmersive);

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
            {embedded && onToggleFocus ? (
              <button
                type="button"
                aria-label={focused ? "退出聚焦聊天" : "聚焦聊天"}
                onClick={onToggleFocus}
                className="inline-flex shrink-0 items-center gap-2 rounded-full border border-[var(--border)] px-3 py-2 text-sm font-medium hover:bg-[var(--surface-strong)]"
              >
                {focused ? "恢复布局" : "聚焦聊天"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => void handleOpenScripts()}
              disabled={actionLoading === "scripts"}
              className="inline-flex shrink-0 items-center gap-2 rounded-full border border-[var(--border)] px-3 py-2 text-sm font-medium hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              <Terminal className="h-4 w-4" />
              {actionLoading === "scripts" ? "加载系统功能..." : "系统功能"}
            </button>
            <button
              type="button"
              onClick={() => void handleResetSession()}
              disabled={actionLoading === "reset"}
              className="inline-flex shrink-0 items-center gap-2 rounded-full border border-[var(--border)] px-3 py-2 text-sm font-medium hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              <RotateCcw className="h-4 w-4" />
              {actionLoading === "reset" ? "重置中..." : "重置会话"}
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
      <section
        ref={scrollContainerRef}
        data-testid="chat-scroll-container"
        onScroll={updateAutoScrollStickiness}
        className={isImmersive ? "flex-1 overflow-y-auto px-4 pb-24 pt-4 space-y-4" : "flex-1 overflow-y-auto p-4 space-y-4"}
      >
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
        {items.map((item, index) => (
          <ChatMessageRow
            key={item.id}
            item={item}
            previousRole={index > 0 ? items[index - 1]?.role : ""}
            assistantName={assistantName}
            assistantAvatarName={assistantAvatarName}
            userAvatarName={userAvatarName}
            isCopied={copiedMessageId === item.id}
            tracePanelExpanded={Boolean(expandedTracePanels[getMessageClientStateKey(item)])}
            traceLoadState={traceLoadState[getMessageClientStateKey(item)]}
            onFileLinkClick={handleFileLinkClick}
            onLoadTrace={loadMessageTrace}
            onToggleTracePanel={() => {
              const messageClientStateKey = getMessageClientStateKey(item);
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
            }}
            onCopyMessage={handleCopyMessage}
          />
        ))}
        <div ref={bottomAnchorRef} aria-hidden="true" />
      </section>
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
      <ChatComposer onSend={handleSend} disabled={isStreaming || loading} compact={isImmersive || embedded} />

      {previewName ? (
        <FilePreviewDialog
          title={previewName}
          content={previewContent}
          mode={previewMode}
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

      {showScripts ? (
        <div className="fixed inset-0 z-50 flex items-end bg-black/45">
          <div className="w-full rounded-t-3xl bg-[var(--surface)] p-4 shadow-[var(--shadow-card)]">
            <div className="mb-4 flex items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">系统功能</h2>
                <p className="text-sm text-[var(--muted)]">选择一个系统功能立即执行</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setShowScripts(false);
                  setScriptError("");
                }}
                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"
              >
                关闭
              </button>
            </div>
            {scriptError ? (
              <div className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {scriptError}
              </div>
            ) : null}
            {scripts.length === 0 ? (
              <div className="rounded-xl border border-[var(--border)] px-4 py-6 text-center text-sm text-[var(--muted)]">
                当前没有可执行脚本
              </div>
            ) : (
              <div className="max-h-[60vh] overflow-y-auto pr-1">
                <div className="grid grid-cols-2 gap-2">
                {scripts.map((script) => (
                  <button
                    key={script.scriptName}
                    type="button"
                    onClick={() => void handleRunScript(script)}
                    disabled={runningScriptName === script.scriptName}
                    className="min-h-[68px] rounded-2xl border border-[var(--border)] px-3 py-2 text-left hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    <div className="text-sm font-medium leading-5 text-[var(--text)]">
                      {runningScriptName === script.scriptName ? "执行中..." : getCompactScriptTitle(script)}
                    </div>
                  </button>
                ))}
                </div>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </main>
  );
}
