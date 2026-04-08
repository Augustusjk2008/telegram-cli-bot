import { useEffect, useState } from "react";
import { AlertTriangle, LogOut, RefreshCw, Square } from "lucide-react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client?: WebBotClient;
  onLogout: () => void;
};

export function SettingsScreen({ botAlias, client = new MockWebBotClient(), onLogout }: Props) {
  const [overview, setOverview] = useState<BotOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [showKillConfirm, setShowKillConfirm] = useState(false);
  const [actionLoading, setActionLoading] = useState<"" | "reset" | "kill">("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    client.getBotOverview(botAlias)
      .then((data) => {
        if (cancelled) return;
        setOverview(data);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || "加载设置失败");
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [botAlias, client]);

  const confirmReset = async () => {
    setActionLoading("reset");
    setError("");
    setNotice("");
    try {
      await client.resetSession(botAlias);
      setNotice("当前会话已重置");
      setShowResetConfirm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置会话失败");
    } finally {
      setActionLoading("");
    }
  };

  const confirmKill = async () => {
    setActionLoading("kill");
    setError("");
    setNotice("");
    try {
      const message = await client.killTask(botAlias);
      setNotice(message || "已发送终止任务请求");
      setShowKillConfirm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "终止任务失败");
    } finally {
      setActionLoading("");
    }
  };

  return (
    <main className="flex flex-col h-full bg-[var(--bg)]">
      <header className="p-4 border-b border-[var(--border)] bg-[var(--surface-strong)]">
        <h1 className="text-xl font-bold">设置</h1>
      </header>

      <section className="flex-1 overflow-y-auto p-4 space-y-6">
        {loading ? (
          <div className="text-center text-[var(--muted)]">加载中...</div>
        ) : null}
        {error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {notice}
          </div>
        ) : null}
        {overview ? (
          <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 text-sm text-[var(--muted)] space-y-2">
            <p><span className="font-medium text-[var(--text)]">Bot:</span> {overview.alias}</p>
            <p><span className="font-medium text-[var(--text)]">CLI:</span> {overview.cliType}</p>
            <p><span className="font-medium text-[var(--text)]">状态:</span> {overview.status}</p>
            <p className="break-all"><span className="font-medium text-[var(--text)]">目录:</span> {overview.workingDir}</p>
          </div>
        ) : null}
        <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] overflow-hidden divide-y divide-[var(--border)]">
          <button
            onClick={() => setShowKillConfirm(true)}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)] text-[var(--danger)]"
          >
            <span className="flex items-center gap-3">
              <Square className="w-5 h-5" />
              终止当前任务
            </span>
          </button>
          <button
            onClick={() => setShowResetConfirm(true)}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)] text-[var(--danger)]"
          >
            <span className="flex items-center gap-3">
              <RefreshCw className="w-5 h-5" />
              重置当前会话
            </span>
          </button>
          <button
            onClick={onLogout}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)]"
          >
            <span className="flex items-center gap-3">
              <LogOut className="w-5 h-5" />
              退出登录
            </span>
          </button>
        </div>
      </section>

      {showResetConfirm ? (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-[var(--surface)] rounded-2xl p-6 max-w-sm w-full shadow-[var(--shadow-card)]">
            <div className="flex items-center gap-3 text-[var(--danger)] mb-4">
              <AlertTriangle className="w-6 h-6" />
              <h2 className="text-lg font-bold">危险操作</h2>
            </div>
            <p className="text-[var(--text)] mb-6">确定要重置当前会话吗？此操作不可恢复。</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowResetConfirm(false)}
                className="px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-[var(--surface-strong)]"
              >
                取消
              </button>
              <button
                onClick={() => void confirmReset()}
                disabled={actionLoading === "reset"}
                className="px-4 py-2 rounded-lg bg-[var(--danger)] text-white hover:opacity-90"
              >
                {actionLoading === "reset" ? "重置中..." : "确定重置"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showKillConfirm ? (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-[var(--surface)] rounded-2xl p-6 max-w-sm w-full shadow-[var(--shadow-card)]">
            <div className="flex items-center gap-3 text-[var(--danger)] mb-4">
              <AlertTriangle className="w-6 h-6" />
              <h2 className="text-lg font-bold">终止任务</h2>
            </div>
            <p className="text-[var(--text)] mb-6">确定要终止当前正在运行的任务吗？</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowKillConfirm(false)}
                className="px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-[var(--surface-strong)]"
              >
                取消
              </button>
              <button
                onClick={() => void confirmKill()}
                disabled={actionLoading === "kill"}
                className="px-4 py-2 rounded-lg bg-[var(--danger)] text-white hover:opacity-90"
              >
                {actionLoading === "kill" ? "终止中..." : "确定终止"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
