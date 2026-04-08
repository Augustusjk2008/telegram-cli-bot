import { useEffect, useState } from "react";
import { LoaderCircle, RotateCcw, Square, Terminal } from "lucide-react";
import { ChatComposer } from "../components/ChatComposer";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { ChatMessage, SystemScript } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client?: WebBotClient;
};

export function ChatScreen({ botAlias, client = new MockWebBotClient() }: Props) {
  const [items, setItems] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [actionLoading, setActionLoading] = useState<"" | "reset" | "kill" | "scripts">("");
  const [showScripts, setShowScripts] = useState(false);
  const [scripts, setScripts] = useState<SystemScript[]>([]);
  const [scriptError, setScriptError] = useState("");
  const [runningScriptName, setRunningScriptName] = useState("");

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

    client.listMessages(botAlias)
      .then((messages) => {
        if (cancelled) return;
        setItems((prev) => (prev.length > 0 ? [...messages, ...prev] : messages));
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
    if (!isStreaming) {
      setElapsedSeconds(0);
      return;
    }

    setElapsedSeconds(0);
    const timer = window.setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [isStreaming]);

  async function handleSend(text: string) {
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

    try {
      const finalMessage = await client.sendMessage(botAlias, text, (chunk) => {
        setItems((prev) =>
          prev.map((item) =>
            item.id === assistantId
              ? { ...item, text: item.text + chunk, state: "streaming" }
              : item,
          ),
        );
      });

      setItems((prev) => prev.map((item) => (item.id === assistantId ? finalMessage : item)));
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

  return (
    <main className="flex flex-col h-full">
      <header className="p-4 border-b border-[var(--border)] bg-[var(--surface-strong)]">
        <h1 className="text-lg font-semibold">{botAlias}</h1>
        {isStreaming ? (
          <div className="mt-2 inline-flex items-center gap-2 rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700">
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            <span>已等待 {elapsedSeconds} 秒</span>
          </div>
        ) : null}
      </header>
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
            disabled={actionLoading === "kill"}
            className="inline-flex shrink-0 items-center gap-2 rounded-full border border-red-200 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
          >
            <Square className="h-4 w-4" />
            {actionLoading === "kill" ? "终止中..." : "终止任务"}
          </button>
        </div>
      </section>
      <section className="flex-1 overflow-y-auto p-4 space-y-4">
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
                  ? "bg-[var(--accent)] text-white px-4 py-2 rounded-2xl max-w-[80%]"
                  : item.role === "system"
                    ? "bg-slate-100 text-slate-700 px-4 py-2 rounded-2xl max-w-[90%] border border-slate-200 whitespace-pre-wrap"
                  : item.state === "error"
                    ? "bg-red-50 text-red-700 px-4 py-2 rounded-2xl max-w-[80%] border border-red-200"
                    : "bg-[var(--surface)] text-[var(--text)] px-4 py-2 rounded-2xl max-w-[80%] border border-[var(--border)] whitespace-pre-wrap"
              }
            >
              {item.text || (item.state === "streaming" ? "正在生成..." : "")}
            </div>
          </div>
        ))}
      </section>
      <ChatComposer onSend={handleSend} disabled={isStreaming || loading} />

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
              <div className="space-y-2">
                {scripts.map((script) => (
                  <button
                    key={script.scriptName}
                    type="button"
                    onClick={() => void handleRunScript(script)}
                    disabled={runningScriptName === script.scriptName}
                    className="w-full rounded-2xl border border-[var(--border)] px-4 py-3 text-left hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    <div className="font-medium">{script.displayName}</div>
                    <div className="mt-1 text-sm text-[var(--muted)]">{script.description}</div>
                    <div className="mt-1 text-xs text-[var(--muted)] break-all">{script.path}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </main>
  );
}
