import { memo, useCallback, useEffect, useRef, useState } from "react";
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
import { RestoredReplyNotice } from "../components/RestoredReplyNotice";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  BotOverview,
  ChatMessage,
  ChatMessageMetaInfo,
  ChatTraceEvent,
  RunningReply,
  SystemScript,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { buildResumePrompt } from "../utils/chatResume";
import { resolvePreviewFilePath } from "../utils/fileLinks";

type Props = {
  botAlias: string;
  client?: WebBotClient;
  botAvatarName?: string;
  userAvatarName?: string;
  isVisible?: boolean;
  isImmersive?: boolean;
  onToggleImmersive?: () => void;
  onUnreadResult?: (botAlias: string) => void;
};

function getCompactScriptTitle(script: SystemScript) {
  const source = (script.displayName || script.description || script.scriptName).trim();
  if (!source) {
    return script.scriptName;
  }
  const firstSentence = source.split(/[。.!?！？;\n]/)[0]?.trim();
  return firstSentence || script.scriptName;
}

function runningUserId(botAlias: string) {
  return `running-user-${botAlias}`;
}

function runningAssistantId(botAlias: string) {
  return `running-assistant-${botAlias}`;
}

function restoredSystemId(botAlias: string) {
  return `restored-system-${botAlias}`;
}

function restoredAssistantId(botAlias: string) {
  return `restored-assistant-${botAlias}`;
}

function mergeRunningReply(items: ChatMessage[], botAlias: string, runningReply?: RunningReply | null) {
  const nextItems = items.filter(
    (item) => item.id !== runningUserId(botAlias) && item.id !== runningAssistantId(botAlias),
  );

  if (runningReply?.userText) {
    const hasUserMessage = nextItems.some((item) => item.role === "user" && item.text === runningReply.userText);
    if (!hasUserMessage) {
      nextItems.push({
        id: runningUserId(botAlias),
        role: "user",
        text: runningReply.userText,
        createdAt: runningReply.startedAt,
        state: "done",
      });
    }
  }

  nextItems.push({
    id: runningAssistantId(botAlias),
    role: "assistant",
    text: runningReply?.previewText || "",
    createdAt: runningReply?.startedAt || new Date().toISOString(),
    state: "streaming",
  });

  return nextItems;
}

function mergeRestoredReply(items: ChatMessage[], botAlias: string, runningReply?: RunningReply | null) {
  if (!runningReply) {
    return items;
  }

  const nextItems = items.filter(
    (item) =>
      item.id !== runningUserId(botAlias)
      && item.id !== runningAssistantId(botAlias)
      && item.id !== restoredSystemId(botAlias)
      && item.id !== restoredAssistantId(botAlias),
  );

  if (runningReply.userText) {
    const hasUserMessage = nextItems.some((item) => item.role === "user" && item.text === runningReply.userText);
    if (!hasUserMessage) {
      nextItems.push({
        id: runningUserId(botAlias),
        role: "user",
        text: runningReply.userText,
        createdAt: runningReply.startedAt,
        state: "done",
      });
    }
  }

  nextItems.push({
    id: restoredSystemId(botAlias),
    role: "system",
    text: "检测到上次未完成任务，已恢复最近预览。",
    createdAt: runningReply.updatedAt || runningReply.startedAt,
    state: "done",
  });
  nextItems.push({
    id: restoredAssistantId(botAlias),
    role: "assistant",
    text: runningReply.previewText || "上次任务在完成前中断，未留下预览文本。",
    createdAt: runningReply.updatedAt || runningReply.startedAt,
    state: "error",
  });

  return nextItems;
}

function resolveStreamStartMs(runningReply?: RunningReply | null, elapsedSeconds?: number) {
  if (runningReply?.startedAt) {
    const parsed = Date.parse(runningReply.startedAt);
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

type ChatMessageRowProps = {
  item: ChatMessage;
  previousRole: string;
  assistantName: string;
  assistantAvatarName?: string;
  userAvatarName?: string;
  botAlias: string;
  restoredReplyActive: boolean;
  isStreaming: boolean;
  isCopied: boolean;
  traceLoadState?: { loading: boolean; error?: string };
  onFileLinkClick: (href: string) => void;
  onLoadTrace: (messageId: string) => void;
  onCopyMessage: (item: ChatMessage) => void;
  onResumeContinue: () => void;
};

const ChatMessageRow = memo(function ChatMessageRow({
  item,
  previousRole,
  assistantName,
  assistantAvatarName,
  userAvatarName,
  botAlias,
  restoredReplyActive,
  isStreaming,
  isCopied,
  traceLoadState,
  onFileLinkClick,
  onLoadTrace,
  onCopyMessage,
  onResumeContinue,
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
              elapsedSeconds={canCopyAssistantMessage ? item.elapsedSeconds : undefined}
              copyLabel={canCopyAssistantMessage ? (isCopied ? "已复制" : "复制") : undefined}
              onCopy={canCopyAssistantMessage ? (() => void onCopyMessage(item)) : undefined}
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
          {item.id === restoredAssistantId(botAlias) && restoredReplyActive ? (
            <RestoredReplyNotice disabled={isStreaming} onContinue={() => void onResumeContinue()} />
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
  onToggleImmersive,
  onUnreadResult,
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
  const [botOverview, setBotOverview] = useState<BotOverview | null>(null);
  const [restoredReply, setRestoredReply] = useState<RunningReply | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState("");
  const [traceLoadState, setTraceLoadState] = useState<Record<string, { loading: boolean; error?: string }>>({});
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null);
  const scrollContainerRef = useRef<HTMLElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const forceAutoScrollRef = useRef(true);
  const isVisibleRef = useRef(isVisible);
  const itemsRef = useRef<ChatMessage[]>([]);
  const traceLoadStateRef = useRef<Record<string, { loading: boolean; error?: string }>>({});
  const workingDirRef = useRef("");
  const botOverviewRef = useRef<BotOverview | null>(null);
  const restoredReplyRef = useRef<RunningReply | null>(null);

  useEffect(() => {
    isVisibleRef.current = isVisible;
  }, [isVisible]);

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
    restoredReplyRef.current = restoredReply;
  }, [restoredReply]);

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
    setBotOverview(null);
    setRestoredReply(null);
    setCopiedMessageId("");
    setTraceLoadState({});
    shouldStickToBottomRef.current = true;
    forceAutoScrollRef.current = true;

    Promise.all([client.listMessages(botAlias), client.getBotOverview(botAlias)])
      .then(([messages, overview]) => {
        if (cancelled) return;
        setBotOverview(overview);
        setWorkingDir(overview.workingDir || "");
        if (overview.isProcessing) {
          setRestoredReply(null);
          setItems(mergeRunningReply(messages, botAlias, overview.runningReply));
          setIsStreaming(true);
          setStreamMode("poll");
          setStreamStartedAtMs(resolveStreamStartMs(overview.runningReply));
        } else if (overview.runningReply) {
          setRestoredReply(overview.runningReply);
          setItems(mergeRestoredReply(messages, botAlias, overview.runningReply));
        } else {
          setRestoredReply(null);
          setItems(messages);
        }
        setLoading(false);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || "加载历史失败");
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [botAlias, client]);

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

  useEffect(() => {
    if (streamMode !== "poll") {
      return;
    }

    let cancelled = false;
    const refresh = async () => {
      try {
        const overview = await client.getBotOverview(botAlias);
        if (cancelled) return;
        setBotOverview(overview);
        setWorkingDir(overview.workingDir || "");

        if (overview.isProcessing) {
          setIsStreaming(true);
          setRestoredReply(null);
          setStreamStartedAtMs((prev) => prev ?? resolveStreamStartMs(overview.runningReply));
          setItems((prev) => mergeRunningReply(prev, botAlias, overview.runningReply));
          return;
        }

        const messages = await client.listMessages(botAlias);
        if (cancelled) return;
        setItems(messages);
        setRestoredReply(null);
        setIsStreaming(false);
        setStreamMode("");
        setStreamStartedAtMs(null);
        if (!isVisibleRef.current) {
          onUnreadResult?.(botAlias);
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "恢复任务状态失败");
        setIsStreaming(false);
        setStreamMode("");
        setStreamStartedAtMs(null);
      }
    };

    const timer = window.setInterval(() => {
      void refresh();
    }, 1000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [botAlias, client, streamMode]);

  const lastItem = items[items.length - 1];

  useEffect(() => {
    if (!isVisible || loading) {
      return;
    }
    if (!forceAutoScrollRef.current && !shouldStickToBottomRef.current) {
      return;
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
      const content = mode === "full"
        ? await client.readFileFull(botAlias, name)
        : await client.readFile(botAlias, name);
      setPreviewName(name);
      setPreviewMode(mode);
      setPreviewContent(content || "文件为空");
    } catch (err) {
      setError(err instanceof Error ? err.message : mode === "full" ? "读取全文失败" : "预览文件失败");
    } finally {
      setPreviewLoading(false);
    }
  }, [botAlias, client]);

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
    if ((currentMessage.meta?.trace || []).length > 0) {
      return;
    }
    if ((traceLoadStateRef.current[messageId]?.loading)) {
      return;
    }
    if (!(currentMessage.meta?.traceCount || 0)) {
      return;
    }

    setTraceLoadState((prev) => ({
      ...prev,
      [messageId]: {
        loading: true,
      },
    }));

    try {
      const traceDetails = await client.getMessageTrace(botAlias, messageId);
      setItems((prev) => updateMessageById(prev, messageId, (item) => ({
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
        [messageId]: {
          loading: false,
        },
      }));
    } catch (err) {
      setTraceLoadState((prev) => ({
        ...prev,
        [messageId]: {
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
    setRestoredReply(null);
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
            setStreamStartedAtMs(resolveStreamStartMs(undefined, status.elapsedSeconds));
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
      const nextScripts = await client.listSystemScripts();
      setScripts(nextScripts);
      setShowScripts(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载系统脚本失败");
    } finally {
      setActionLoading("");
    }
  }

  async function handleRunScript(script: SystemScript) {
    setRunningScriptName(script.scriptName);
    setScriptError("");
    try {
      const result = await client.runSystemScript(script.scriptName);
      appendSystemMessage(
        [
          `脚本：${script.displayName}`,
          result.success ? "执行结果：成功" : "执行结果：失败",
          result.output || "无输出",
        ].join("\n"),
      );
      setShowScripts(false);
    } catch (err) {
      setScriptError(err instanceof Error ? err.message : "执行脚本失败");
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

  const handleResumeContinue = useCallback(async () => {
    const activeRestoredReply = restoredReplyRef.current;
    if (!activeRestoredReply || isStreaming) {
      return;
    }
    await handleSend(buildResumePrompt(botOverviewRef.current?.botMode, activeRestoredReply.previewText));
  }, [handleSend, isStreaming]);

  const killTaskActive = isStreaming || actionLoading === "kill";
  const killTaskDisabled = !isStreaming || actionLoading === "kill";
  const assistantName = botAlias;
  const assistantAvatarName = botOverview?.avatarName || botAvatarName;

  return (
    <main className="relative flex flex-col h-full">
      {!isImmersive ? (
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
      {!isImmersive ? (
        <section className="border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {botAlias === "main" ? (
              <button
                type="button"
                onClick={() => void handleOpenScripts()}
                disabled={actionLoading === "scripts"}
                className="inline-flex shrink-0 items-center gap-2 rounded-full border border-[var(--border)] px-3 py-2 text-sm font-medium hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                <Terminal className="h-4 w-4" />
                {actionLoading === "scripts" ? "加载脚本..." : "系统脚本"}
              </button>
            ) : null}
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
            botAlias={botAlias}
            restoredReplyActive={Boolean(restoredReply)}
            isStreaming={isStreaming}
            isCopied={copiedMessageId === item.id}
            traceLoadState={traceLoadState[item.id]}
            onFileLinkClick={handleFileLinkClick}
            onLoadTrace={loadMessageTrace}
            onCopyMessage={handleCopyMessage}
            onResumeContinue={handleResumeContinue}
          />
        ))}
        <div ref={bottomAnchorRef} aria-hidden="true" />
      </section>
      {isVisible && onToggleImmersive ? (
        <button
          type="button"
          onClick={onToggleImmersive}
          aria-label={isImmersive ? "退出沉浸模式" : "进入沉浸模式"}
          className="absolute bottom-20 right-4 z-20 inline-flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] shadow-[var(--shadow-card)] backdrop-blur hover:bg-[var(--surface-strong)]"
        >
          {isImmersive ? <Minimize2 className="h-5 w-5" /> : <Maximize2 className="h-5 w-5" />}
        </button>
      ) : null}
      <ChatComposer onSend={handleSend} disabled={isStreaming || loading} compact={isImmersive} />

      {previewName ? (
        <FilePreviewDialog
          title={previewName}
          content={previewContent}
          mode={previewMode}
          loading={previewLoading}
          onClose={() => {
            setPreviewName("");
            setPreviewContent("");
          }}
          onLoadFull={previewMode !== "full" ? () => void loadPreview(previewName, "full") : undefined}
          onDownload={() => void client.downloadFile(botAlias, previewName)}
        />
      ) : null}

      {showScripts ? (
        <div className="fixed inset-0 z-50 flex items-end bg-black/45">
          <div className="w-full rounded-t-3xl bg-[var(--surface)] p-4 shadow-[var(--shadow-card)]">
            <div className="mb-4 flex items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">系统脚本</h2>
                <p className="text-sm text-[var(--muted)]">选择一个预设脚本立即执行</p>
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
