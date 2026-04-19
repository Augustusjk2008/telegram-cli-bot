import { clsx } from "clsx";
import { useEffect, useMemo, useState } from "react";
import { GitBranch, RefreshCw } from "lucide-react";
import { BotIdentity } from "../components/BotIdentity";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { GitChangedFile, GitDiffPayload, GitOverview } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  client?: WebBotClient;
  embedded?: boolean;
  onOverviewChange?: (overview: GitOverview | null) => void;
};

type DiffLineKind = "meta" | "hunk" | "add" | "delete" | "context";

type ParsedDiffLine = {
  text: string;
  kind: DiffLineKind;
};

function groupedFiles(overview: GitOverview | null) {
  const changedFiles = overview?.changedFiles || [];
  return {
    staged: changedFiles.filter((item) => item.staged),
    unstaged: changedFiles.filter((item) => item.unstaged && !item.untracked),
    untracked: changedFiles.filter((item) => item.untracked),
  };
}

function sectionTitle(title: string, count: number) {
  return `${title} (${count})`;
}

function parseDiffLineKind(line: string): DiffLineKind {
  if (
    line.startsWith("diff --git")
    || line.startsWith("index ")
    || line.startsWith("--- ")
    || line.startsWith("+++ ")
    || line.startsWith("rename ")
    || line.startsWith("new file ")
    || line.startsWith("deleted file ")
  ) {
    return "meta";
  }
  if (line.startsWith("@@")) {
    return "hunk";
  }
  if (line.startsWith("+") && !line.startsWith("+++")) {
    return "add";
  }
  if (line.startsWith("-") && !line.startsWith("---")) {
    return "delete";
  }
  return "context";
}

function parseDiffLines(diff: string): ParsedDiffLine[] {
  return (diff || "").split(/\r?\n/).map((line) => ({
    text: line,
    kind: parseDiffLineKind(line),
  }));
}

function diffLineClasses(kind: DiffLineKind) {
  if (kind === "add") {
    return "bg-emerald-50 text-emerald-700";
  }
  if (kind === "delete") {
    return "bg-red-50 text-red-700";
  }
  if (kind === "hunk") {
    return "bg-sky-50 text-sky-700";
  }
  if (kind === "meta") {
    return "bg-slate-100 text-slate-600";
  }
  return "text-[var(--text)]";
}

export function GitScreen({
  botAlias,
  botAvatarName,
  client = new MockWebBotClient(),
  embedded = false,
  onOverviewChange,
}: Props) {
  const [overview, setOverview] = useState<GitOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [commitMessage, setCommitMessage] = useState("");
  const [actionLoading, setActionLoading] = useState("");
  const [diffPayload, setDiffPayload] = useState<GitDiffPayload | null>(null);
  const [diffLoadingPath, setDiffLoadingPath] = useState("");
  const groups = useMemo(() => groupedFiles(overview), [overview]);
  const parsedDiffLines = useMemo(() => parseDiffLines(diffPayload?.diff || ""), [diffPayload]);
  const stageAllPaths = useMemo(
    () => [...groups.unstaged, ...groups.untracked].map((item) => item.path),
    [groups.unstaged, groups.untracked],
  );

  async function loadOverview() {
    setLoading(true);
    setError("");
    try {
      const next = await client.getGitOverview(botAlias);
      setOverview(next);
      onOverviewChange?.(next);
    } catch (err) {
      setOverview(null);
      setError(err instanceof Error ? err.message : "加载 Git 状态失败");
      onOverviewChange?.(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadOverview();
  }, [botAlias, client]);

  async function runAction(
    key: string,
    fn: () => Promise<{ message: string; overview: GitOverview }>,
  ) {
    setActionLoading(key);
    setError("");
    setNotice("");
    try {
      const result = await fn();
      setOverview(result.overview);
      onOverviewChange?.(result.overview);
      setNotice(result.message || "Git 操作完成");
      if (key === "commit") {
        setCommitMessage("");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Git 操作失败");
    } finally {
      setActionLoading("");
    }
  }

  async function loadDiff(item: GitChangedFile, staged: boolean) {
    setDiffLoadingPath(`${item.path}:${staged ? "staged" : "worktree"}`);
    setError("");
    try {
      const diff = await client.getGitDiff(botAlias, item.path, staged);
      setDiffPayload(diff);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 Diff 失败");
    } finally {
      setDiffLoadingPath("");
    }
  }

  return (
    <main className={clsx("flex h-full min-h-0 flex-col", embedded ? "bg-[var(--surface)]" : "bg-[var(--bg)]")}>
      {embedded ? null : (
        <header className="border-b border-[var(--border)] bg-[var(--surface-strong)] p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h1 className="text-xl font-bold">Git</h1>
              {botAvatarName ? (
                <BotIdentity
                  alias={botAlias}
                  avatarName={botAvatarName}
                  size={28}
                  className="mt-1 flex min-w-0 items-center gap-2"
                  nameClassName="truncate text-sm font-medium text-[var(--muted)]"
                />
              ) : (
                <p className="text-sm text-[var(--muted)]">{botAlias}</p>
              )}
            </div>
            <button
              type="button"
              onClick={() => void loadOverview()}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface)]"
            >
              <RefreshCw className="h-4 w-4" />
              刷新
            </button>
          </div>
        </header>
      )}

      <section className={clsx("flex-1 space-y-4 overflow-y-auto", embedded ? "p-3" : "p-4")}>
        {loading ? <div className="text-center text-[var(--muted)]">加载中...</div> : null}
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

        {!loading && overview && !overview.repoFound ? (
          <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <div className="space-y-2">
              <h2 className="text-lg font-semibold">当前目录不在 Git 仓库中</h2>
              <p className="text-sm text-[var(--muted)] break-all">{overview.workingDir}</p>
            </div>
            <button
              type="button"
              onClick={async () => {
                setActionLoading("init");
                setError("");
                try {
                  const next = await client.initGitRepository(botAlias);
                  setOverview(next);
                  setNotice("Git 仓库已初始化");
                } catch (err) {
                  setError(err instanceof Error ? err.message : "初始化 Git 仓库失败");
                } finally {
                  setActionLoading("");
                }
              }}
              disabled={actionLoading === "init" || !overview.canInit}
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
            >
              {actionLoading === "init" ? "初始化中..." : "初始化 Git 仓库"}
            </button>
          </div>
        ) : null}

        {!loading && overview && overview.repoFound ? (
          <>
            <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <GitBranch className="h-5 w-5 text-[var(--accent)]" />
                    <h2 className="text-lg font-semibold">{overview.repoName}</h2>
                  </div>
                  <p className="break-all text-sm text-[var(--muted)]">{overview.repoPath}</p>
                </div>
                <span className="rounded-full bg-[var(--surface-strong)] px-3 py-1 text-xs text-[var(--muted)]">
                  {overview.isClean ? "工作区干净" : "存在改动"}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-3">
                  <div className="text-[var(--muted)]">当前分支</div>
                  <div className="mt-1 font-medium">{overview.currentBranch || "-"}</div>
                </div>
                <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-3">
                  <div className="text-[var(--muted)]">Ahead / Behind</div>
                  <div className="mt-1 font-medium">{overview.aheadCount} / {overview.behindCount}</div>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void runAction("fetch", () => client.fetchGitRemote(botAlias))}
                  disabled={actionLoading !== ""}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  {actionLoading === "fetch" ? "抓取中..." : "Fetch"}
                </button>
                <button
                  type="button"
                  onClick={() => void runAction("pull", () => client.pullGitRemote(botAlias))}
                  disabled={actionLoading !== ""}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  {actionLoading === "pull" ? "拉取中..." : "Pull"}
                </button>
                <button
                  type="button"
                  onClick={() => void runAction("push", () => client.pushGitRemote(botAlias))}
                  disabled={actionLoading !== ""}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  {actionLoading === "push" ? "推送中..." : "Push"}
                </button>
                <button
                  type="button"
                  onClick={() => void runAction("stash", () => client.stashGitChanges(botAlias))}
                  disabled={actionLoading !== ""}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  {actionLoading === "stash" ? "暂存中..." : "Stash Push"}
                </button>
                <button
                  type="button"
                  onClick={() => void runAction("stash-pop", () => client.popGitStash(botAlias))}
                  disabled={actionLoading !== ""}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  {actionLoading === "stash-pop" ? "恢复中..." : "Stash Pop"}
                </button>
              </div>
            </div>

            <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <div>
                <h2 className="text-base font-semibold">提交更改</h2>
                <p className="text-sm text-[var(--muted)]">只允许常用安全操作，不做危险 Git 命令。</p>
              </div>
              <textarea
                value={commitMessage}
                onChange={(event) => setCommitMessage(event.target.value)}
                rows={3}
                placeholder="输入 commit message"
                className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-3 text-sm text-[var(--text)]"
              />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void runAction("stage-all", async () => {
                    const result = await client.stageGitPaths(botAlias, stageAllPaths);
                    return {
                      message: "已暂存全部改动",
                      overview: result.overview,
                    };
                  })}
                  disabled={actionLoading !== "" || stageAllPaths.length === 0}
                  className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  {actionLoading === "stage-all" ? "暂存中..." : "暂存全部"}
                </button>
                <button
                  type="button"
                  onClick={() => void runAction("commit", () => client.commitGitChanges(botAlias, commitMessage))}
                  disabled={actionLoading !== "" || overview.isClean}
                  className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
                >
                  {actionLoading === "commit" ? "提交中..." : "提交更改"}
                </button>
              </div>
            </div>

            <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <h2 className="text-base font-semibold">变更文件</h2>
              {([["staged", groups.staged], ["unstaged", groups.unstaged], ["untracked", groups.untracked]] as const).map(([key, items]) => (
                <div key={key} className="space-y-2">
                  <h3 className="text-sm font-medium text-[var(--muted)]">
                    {sectionTitle(key === "staged" ? "已暂存" : key === "unstaged" ? "未暂存" : "未跟踪", items.length)}
                  </h3>
                  {items.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
                      当前分组暂无文件
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {items.map((item) => (
                        <div key={`${key}-${item.path}`} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="break-all font-medium text-[var(--text)]">{item.path}</div>
                              <div className="mt-1 text-xs text-[var(--muted)]">状态: {item.status}</div>
                            </div>
                            <div className="flex shrink-0 flex-wrap gap-2">
                              {(item.untracked || item.unstaged || !item.staged) ? (
                                <button
                                  type="button"
                                  onClick={() => void runAction(`stage:${item.path}`, () => client.stageGitPaths(botAlias, [item.path]))}
                                  disabled={actionLoading !== ""}
                                  className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--surface-strong)] disabled:opacity-60"
                                >
                                  暂存
                                </button>
                              ) : null}
                              {item.staged ? (
                                <button
                                  type="button"
                                  onClick={() => void runAction(`unstage:${item.path}`, () => client.unstageGitPaths(botAlias, [item.path]))}
                                  disabled={actionLoading !== ""}
                                  className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--surface-strong)] disabled:opacity-60"
                                >
                                  取消暂存
                                </button>
                              ) : null}
                              <button
                                type="button"
                                onClick={() => void loadDiff(item, item.staged && !item.unstaged)}
                                disabled={diffLoadingPath !== ""}
                                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--surface-strong)] disabled:opacity-60"
                              >
                                {diffLoadingPath === `${item.path}:${item.staged && !item.unstaged ? "staged" : "worktree"}` ? "读取中..." : "查看 Diff"}
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <h2 className="text-base font-semibold">最近提交</h2>
              {overview.recentCommits.length === 0 ? (
                <div className="rounded-xl border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
                  当前仓库还没有提交记录
                </div>
              ) : (
                <div className="space-y-2">
                  {overview.recentCommits.map((item) => (
                    <div key={item.hash} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-4 py-3">
                      <div className="font-medium text-[var(--text)]">{item.subject}</div>
                      <div className="mt-1 text-xs text-[var(--muted)]">
                        {item.shortHash} · {item.authorName} · {item.authoredAt}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        ) : null}
      </section>

      {diffPayload ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4">
          <div className="w-full max-w-3xl rounded-2xl bg-[var(--surface)] p-5 shadow-[var(--shadow-card)]">
            <div className="mb-4 flex items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">Diff</h2>
                <p className="text-sm text-[var(--muted)] break-all">{diffPayload.path}</p>
              </div>
              <button
                type="button"
                onClick={() => setDiffPayload(null)}
                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"
              >
                关闭
              </button>
            </div>
            {parsedDiffLines.length > 0 ? (
              <div className="max-h-[60vh] overflow-auto rounded-xl border border-[var(--border)] bg-[var(--bg)] p-2 font-mono text-xs leading-6">
                {parsedDiffLines.map((line, index) => (
                  <div
                    key={`${index}-${line.text}`}
                    data-diff-kind={line.kind}
                    className={`flex gap-3 rounded-md px-3 py-0.5 ${diffLineClasses(line.kind)}`}
                  >
                    <span className="w-8 shrink-0 select-none text-right text-slate-400">
                      {index + 1}
                    </span>
                    <span className="min-w-0 flex-1 whitespace-pre">
                      {line.text || " "}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-xl bg-[var(--bg)] p-4 text-sm text-[var(--muted)]">
                当前没有可显示的差异
              </div>
            )}
          </div>
        </div>
      ) : null}
    </main>
  );
}
