import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Maximize2, Minimize2, RotateCcw, Square, Terminal } from "lucide-react";
import { ChatComposer } from "../components/ChatComposer";
import { ChatMarkdownMessage } from "../components/ChatMarkdownMessage";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { ChatMessage, RunningReply, SystemScript } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client?: WebBotClient;
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

export function ChatScreen({
  botAlias,
  client = new MockWebBotClient(),
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
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [actionLoading, setActionLoading] = useState<"" | "reset" | "kill" | "scripts">("");
  const [showScripts, setShowScripts] = useState(false);
  const [scripts, setScripts] = useState<SystemScript[]>([]);
  const [scriptError, setScriptError] = useState("");
  const [runningScriptName, setRunningScriptName] = useState("");
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null);
  const isVisibleRef = useRef(isVisible);

  useEffect(() => {
    isVisibleRef.current = isVisible;
  }, [isVisible]);

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
    setIsStreaming(false);
    setStreamMode("");
    setStreamStartedAtMs(null);

    Promise.all([client.listMessages(botAlias), client.getBotOverview(botAlias)])
      .then(([messages, overview]) => {
        if (cancelled) return;
        if (overview.isProcessing) {
          setItems(mergeRunningReply(messages, botAlias, overview.runningReply));
          setIsStreaming(true);
          setStreamMode("poll");
          setStreamStartedAtMs(resolveStreamStartMs(overview.runningReply));
        } else if (overview.runningReply) {
          setItems(mergeRestoredReply(messages, botAlias, overview.runningReply));
        } else {
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

        if (overview.isProcessing) {
          setIsStreaming(true);
          setStreamStartedAtMs((prev) => prev ?? resolveStreamStartMs(overview.runningReply));
          setItems((prev) => mergeRunningReply(prev, botAlias, overview.runningReply));
          return;
        }

        const messages = await client.listMessages(botAlias);
        if (cancelled) return;
        setItems(messages);
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

  useEffect(() => {
    if (!isVisible || loading) {
      return;
    }
    if (bottomAnchorRef.current && typeof bottomAnchorRef.current.scrollIntoView === "function") {
      bottomAnchorRef.current.scrollIntoView({ block: "end" });
    }
  }, [isVisible, loading, items, isStreaming]);

  async function handleSend(text: string) {
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
          setItems((prev) =>
            prev.map((item) =>
              item.id === assistantId
                ? { ...item, text: item.text + chunk, state: "streaming" }
                : item,
            ),
          );
        },
        (status) => {
          if (typeof status.elapsedSeconds === "number") {
            setStreamStartedAtMs(resolveStreamStartMs(undefined, status.elapsedSeconds));
          }
          if (status.previewText) {
            usingPreviewReplace = true;
            setItems((prev) =>
              prev.map((item) =>
                item.id === assistantId
                  ? { ...item, text: status.previewText || item.text, state: "streaming" }
                  : item,
              ),
            );
          }
        },
      );

      const elapsedSeconds = typeof finalMessage.elapsedSeconds === "number"
        ? finalMessage.elapsedSeconds
        : Math.max(0, Math.floor((Date.now() - localStartedAtMs) / 1000));
      const finalizedMessage: ChatMessage = {
        ...finalMessage,
        elapsedSeconds,
      };

      setItems((prev) => prev.map((item) => (item.id === assistantId ? finalizedMessage : item)));
      if (!isVisibleRef.current) {
        onUnreadResult?.(botAlias);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "发送失败";
      setError(message);
      setItems((prev) =>
        prev.map((item) =>
          item.id === assistantId
            ? { ...item, text: message, state: "error" }
            : item,
        ),
      );
    } finally {
      setIsStreaming(false);
      setStreamMode("");
      setStreamStartedAtMs(null);
    }
  }

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

  const killTaskActive = isStreaming || actionLoading === "kill";
  const killTaskDisabled = !isStreaming || actionLoading === "kill";

  return (
    <main className="relative flex flex-col h-full">
      {!isImmersive ? (
        <header className="p-4 border-b border-[var(--border)] bg-[var(--surface-strong)]">
          <h1 className="text-lg font-semibold">{botAlias}</h1>
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
      <section className={isImmersive ? "flex-1 overflow-y-auto px-4 pb-24 pt-4 space-y-4" : "flex-1 overflow-y-auto p-4 space-y-4"}>
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
        {items.map((item) => (
          <div
            key={item.id}
            className={
              item.role === "user"
                ? "flex justify-end"
                : item.role === "system"
                  ? "flex justify-center"
                  : "flex justify-start"
            }
          >
            <div
              className={
                item.role === "user"
                  ? "flex max-w-[80%] min-w-0 flex-col items-end gap-1"
                  : item.role === "system"
                    ? "flex max-w-[90%] min-w-0 flex-col items-center gap-1"
                    : "flex max-w-[80%] min-w-0 flex-col items-start gap-1"
              }
            >
              <div
                className={
                  item.role === "user"
                    ? "rounded-2xl bg-[var(--accent)] px-4 py-2 text-white whitespace-pre-wrap break-all"
                    : item.role === "system"
                      ? "rounded-2xl border border-slate-200 bg-slate-100 px-4 py-2 text-slate-700 whitespace-pre-wrap break-all"
                      : item.state === "error"
                        ? "rounded-2xl border border-red-200 bg-red-50 px-4 py-2 text-red-700 whitespace-pre-wrap break-all"
                        : "min-w-0 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-[var(--text)]"
                }
              >
                {item.role === "assistant" && item.state !== "streaming" && item.state !== "error"
                  ? <ChatMarkdownMessage content={item.text} />
                  : item.text || (item.state === "streaming" ? "正在输出..." : "")}
              </div>
              {item.role === "assistant" && item.state !== "streaming" && typeof item.elapsedSeconds === "number" ? (
                <div className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600">
                  用时 {item.elapsedSeconds} 秒
                </div>
              ) : null}
            </div>
          </div>
        ))}
        <div ref={bottomAnchorRef} aria-hidden="true" />
      </section>
      <button
        type="button"
        onClick={onToggleImmersive}
        aria-label={isImmersive ? "退出沉浸模式" : "进入沉浸模式"}
        className="absolute bottom-20 right-4 z-20 inline-flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] shadow-[var(--shadow-card)] backdrop-blur hover:bg-[var(--surface-strong)]"
      >
        {isImmersive ? <Minimize2 className="h-5 w-5" /> : <Maximize2 className="h-5 w-5" />}
      </button>
      <ChatComposer onSend={handleSend} disabled={isStreaming || loading} compact={isImmersive} />

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
