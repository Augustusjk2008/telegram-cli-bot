import { useEffect, useState } from "react";
import { ArrowLeft, RefreshCw, Save } from "lucide-react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { RegisterCodeCreateResult, RegisterCodeItem } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  client?: WebBotClient;
  onClose: () => void;
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function InviteCodeManagementScreen({
  client = new MockWebBotClient(),
  onClose,
}: Props) {
  const [registerCodes, setRegisterCodes] = useState<RegisterCodeItem[]>([]);
  const [registerCodeDraftUses, setRegisterCodeDraftUses] = useState("1");
  const [registerCodeCreating, setRegisterCodeCreating] = useState(false);
  const [registerCodeActionId, setRegisterCodeActionId] = useState("");
  const [createdRegisterCode, setCreatedRegisterCode] = useState<RegisterCodeCreateResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    client.listRegisterCodes()
      .then((items) => {
        if (cancelled) {
          return;
        }
        setRegisterCodes(items);
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setError(getErrorMessage(err, "加载邀请码失败"));
      })
      .finally(() => {
        if (cancelled) {
          return;
        }
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [client]);

  const reloadRegisterCodes = async () => {
    setRefreshing(true);
    try {
      setRegisterCodes(await client.listRegisterCodes());
    } catch (err) {
      setError(getErrorMessage(err, "加载邀请码失败"));
    } finally {
      setRefreshing(false);
    }
  };

  const createRegisterCode = async () => {
    const maxUses = Number(registerCodeDraftUses);
    if (!Number.isInteger(maxUses) || maxUses <= 0) {
      setError("邀请码可用次数至少为 1");
      return;
    }
    setRegisterCodeCreating(true);
    setError("");
    setNotice("");
    try {
      const created = await client.createRegisterCode(maxUses);
      setCreatedRegisterCode(created);
      setRegisterCodeDraftUses("1");
      await reloadRegisterCodes();
      setNotice("邀请码已生成");
    } catch (err) {
      setError(getErrorMessage(err, "生成邀请码失败"));
    } finally {
      setRegisterCodeCreating(false);
    }
  };

  const mutateRegisterCode = async (
    codeId: string,
    input: { maxUsesDelta?: number; disabled?: boolean },
    successNotice: string,
  ) => {
    setRegisterCodeActionId(codeId);
    setError("");
    setNotice("");
    try {
      await client.updateRegisterCode(codeId, input);
      await reloadRegisterCodes();
      setNotice(successNotice);
    } catch (err) {
      setError(getErrorMessage(err, "更新邀请码失败"));
    } finally {
      setRegisterCodeActionId("");
    }
  };

  const removeRegisterCode = async (codeId: string) => {
    setRegisterCodeActionId(codeId);
    setError("");
    setNotice("");
    try {
      await client.deleteRegisterCode(codeId);
      await reloadRegisterCodes();
      setNotice("邀请码已删除");
    } catch (err) {
      setError(getErrorMessage(err, "删除邀请码失败"));
    } finally {
      setRegisterCodeActionId("");
    }
  };

  return (
    <main className="min-h-[100dvh] bg-[var(--bg)]">
      <div className="mx-auto flex min-h-[100dvh] max-w-5xl flex-col p-4">
        <header className="mb-6 flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-4">
          <div className="space-y-1">
            <h1 className="text-2xl font-bold text-[var(--text)]">邀请码管理</h1>
            <p className="text-sm text-[var(--muted)]">仅 127.0.0.1 超管可见。新邀请码明文只显示 1 次。</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
          >
            <ArrowLeft className="h-4 w-4" />
            返回
          </button>
        </header>

        {error ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {notice}
          </div>
        ) : null}

        <section className="mb-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="space-y-1">
              <span className="text-sm text-[var(--text)]">可用次数</span>
              <input
                aria-label="邀请码可用次数"
                type="number"
                min={1}
                value={registerCodeDraftUses}
                onChange={(event) => setRegisterCodeDraftUses(event.target.value)}
                className="w-32 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
              />
            </label>
            <button
              type="button"
              onClick={() => void createRegisterCode()}
              disabled={registerCodeCreating}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
            >
              <Save className="h-4 w-4" />
              {registerCodeCreating ? "生成中..." : "生成邀请码"}
            </button>
            <button
              type="button"
              onClick={() => void reloadRegisterCodes()}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              <RefreshCw className="h-4 w-4" />
              {refreshing ? "刷新中..." : "刷新"}
            </button>
          </div>

          {createdRegisterCode ? (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-700">
              最新邀请码: <span className="font-semibold">{createdRegisterCode.code}</span>
            </div>
          ) : null}
        </section>

        <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-[var(--text)]">邀请码列表</h2>
            <span className="text-xs text-[var(--muted)]">共 {registerCodes.length} 个</span>
          </div>

          {loading ? (
            <p className="text-sm text-[var(--muted)]">加载中...</p>
          ) : registerCodes.length ? (
            registerCodes.map((item) => (
              <article key={item.codeId} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-1 text-sm text-[var(--muted)]">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium text-[var(--text)]">{item.codePreview}</p>
                      {item.disabled ? (
                        <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
                          已停用
                        </span>
                      ) : null}
                    </div>
                    <p>已用 {item.usedCount} / {item.maxUses}，剩余 {item.remainingUses}</p>
                    <p>创建: {item.createdAt || "未知"} · 创建人: {item.createdBy || "未知"}</p>
                    <p>最近使用: {item.lastUsedAt || "未使用"}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void mutateRegisterCode(item.codeId, { maxUsesDelta: 1 }, "邀请码次数已增加")}
                      disabled={registerCodeActionId === item.codeId}
                      className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                    >
                      +1
                    </button>
                    <button
                      type="button"
                      onClick={() => void mutateRegisterCode(item.codeId, { maxUsesDelta: -1 }, "邀请码次数已减少")}
                      disabled={registerCodeActionId === item.codeId || item.remainingUses <= 0}
                      className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                    >
                      -1
                    </button>
                    <button
                      type="button"
                      onClick={() => void mutateRegisterCode(item.codeId, { disabled: !item.disabled }, item.disabled ? "邀请码已启用" : "邀请码已停用")}
                      disabled={registerCodeActionId === item.codeId}
                      className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                    >
                      {item.disabled ? "启用" : "停用"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void removeRegisterCode(item.codeId)}
                      disabled={registerCodeActionId === item.codeId}
                      className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                    >
                      删除
                    </button>
                  </div>
                </div>

                {item.usage.length ? (
                  <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--muted)] space-y-1">
                    {item.usage.map((usage, index) => (
                      <p key={`${item.codeId}-${index}`}>{usage.usedAt || "未知时间"} · {usage.usedBy || "未知用户"}</p>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-[var(--muted)]">暂无使用记录</p>
                )}
              </article>
            ))
          ) : (
            <p className="text-sm text-[var(--muted)]">暂无邀请码</p>
          )}
        </section>
      </div>
    </main>
  );
}
