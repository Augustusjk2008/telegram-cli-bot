import { clsx } from "clsx";
import { useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  DownloadCloud,
  FileDiff,
  GitBranch,
  Minus,
  Plus,
  RefreshCw,
  SendHorizontal,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { BotIdentity } from "../components/BotIdentity";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { GitOverview } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  client?: WebBotClient;
  embedded?: boolean;
  onOpenDiff?: (path: string, staged: boolean) => void | Promise<void>;
  onOverviewChange?: (overview: GitOverview | null) => void;
};

type GitFileGroupKey = "staged" | "unstaged" | "untracked";

function groupedFiles(overview: GitOverview | null) {
  const changedFiles = overview?.changedFiles || [];
  return {
    staged: changedFiles.filter((item) => item.staged),
    unstaged: changedFiles.filter((item) => item.unstaged && !item.untracked),
    untracked: changedFiles.filter((item) => item.untracked),
  };
}

function countLabel(title: string, count: number) {
  return `${title} (${count})`;
}

function changeGroupTone(key: GitFileGroupKey) {
  if (key === "staged") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (key === "unstaged") {
    return "border-yellow-200 bg-yellow-50 text-yellow-700";
  }
  return "border-sky-200 bg-sky-50 text-sky-700";
}

function iconButtonClass() {
  return "inline-flex h-6 w-6 items-center justify-center rounded border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)] disabled:opacity-50";
}

function buttonClass(kind: "plain" | "primary" = "plain") {
  return clsx(
    "inline-flex h-8 items-center justify-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors disabled:opacity-50",
    kind === "primary"
      ? "bg-[var(--accent)] text-white hover:opacity-90"
      : "border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] hover:bg-[var(--surface-strong)]",
  );
}

export function GitScreen({
  botAlias,
  botAvatarName,
  client = new MockWebBotClient(),
  embedded = false,
  onOpenDiff,
  onOverviewChange,
}: Props) {
  const [overview, setOverview] = useState<GitOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [commitMessage, setCommitMessage] = useState("");
  const [actionLoading, setActionLoading] = useState("");
  const [changesCollapsed, setChangesCollapsed] = useState(false);
  const [commitsCollapsed, setCommitsCollapsed] = useState(false);
  const groups = useMemo(() => groupedFiles(overview), [overview]);
  const changeGroups = useMemo(
    () => ([
      ["staged", "已暂存", groups.staged],
      ["unstaged", "未暂存", groups.unstaged],
      ["untracked", "未跟踪", groups.untracked],
    ] as const),
    [groups.staged, groups.unstaged, groups.untracked],
  );
  const stageAllPaths = useMemo(
    () => [...groups.unstaged, ...groups.untracked].map((item) => item.path),
    [groups.unstaged, groups.untracked],
  );
  const totalChanges = groups.staged.length + groups.unstaged.length + groups.untracked.length;

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

  async function openChangedDiff(path: string, staged: boolean) {
    if (!onOpenDiff) {
      setNotice("当前视图未连接文件编辑器");
      return;
    }
    setNotice("");
    await onOpenDiff(path, staged);
  }

  return (
    <main className={clsx("flex h-full min-h-0 flex-col", embedded ? "bg-[var(--surface)]" : "bg-[var(--bg)]")}>
      {embedded ? null : (
        <header className="border-b border-[var(--border)] bg-[var(--surface-strong)] px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <GitBranch className="h-4 w-4 text-[var(--accent)]" />
                <h1 className="text-lg font-semibold">Git</h1>
              </div>
              {botAvatarName ? (
                <BotIdentity
                  alias={botAlias}
                  avatarName={botAvatarName}
                  size={24}
                  className="mt-1 flex min-w-0 items-center gap-2"
                  nameClassName="truncate text-xs font-medium text-[var(--muted)]"
                />
              ) : (
                <p className="truncate text-xs text-[var(--muted)]">{botAlias}</p>
              )}
            </div>
            <button
              type="button"
              onClick={() => void loadOverview()}
              className={buttonClass()}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              刷新
            </button>
          </div>
        </header>
      )}

      <section className={clsx("flex-1 overflow-y-auto", embedded ? "p-3" : "p-4")}>
        <div className="space-y-3">
          {loading ? <div className="text-center text-[var(--muted)]">加载中...</div> : null}
          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : null}
          {notice ? (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              {notice}
            </div>
          ) : null}

          {!loading && overview && !overview.repoFound ? (
            <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5">
              <div className="space-y-2">
                <h2 className="text-lg font-semibold">当前目录不在 Git 仓库中</h2>
                <p className="break-all text-sm text-[var(--muted)]">{overview.workingDir}</p>
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
                className={clsx("mt-4", buttonClass("primary"))}
              >
                {actionLoading === "init" ? "初始化中..." : "初始化 Git 仓库"}
              </button>
            </div>
          ) : null}

          {!loading && overview && overview.repoFound ? (
            <div
              data-testid="git-desktop-shell"
              className="space-y-3"
            >
              <aside
                data-testid="git-changes-panel"
                className="rounded-lg border border-[var(--border)] bg-[var(--surface)]"
              >
                <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2">
                  <div>
                    <h2 className="text-sm font-semibold">变更</h2>
                    <p className="text-xs text-[var(--muted)]">{countLabel("文件", totalChanges)}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      aria-label="刷新 Git 状态"
                      onClick={() => void loadOverview()}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--border)] hover:bg-[var(--surface-strong)]"
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      aria-label={changesCollapsed ? "展开变更" : "收起变更"}
                      onClick={() => setChangesCollapsed((value) => !value)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--border)] hover:bg-[var(--surface-strong)]"
                    >
                      {changesCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>
                {!changesCollapsed ? (
                  <div data-testid="git-changes-content" className="space-y-3 p-3">
                    {changeGroups.map(([key, title, items]) => (
                      <div key={key} className="space-y-2">
                        <div className="flex items-center justify-between text-xs font-medium text-[var(--muted)]">
                          <span>{countLabel(title, items.length)}</span>
                          <span className={clsx("rounded-full border px-2 py-0.5", changeGroupTone(key))}>
                            {key === "staged" ? "Index" : key === "unstaged" ? "Worktree" : "New"}
                          </span>
                        </div>
                        {items.length === 0 ? (
                          <div className="rounded-md border border-dashed border-[var(--border)] px-3 py-2 text-xs text-[var(--muted)]">
                            当前分组暂无文件
                          </div>
                        ) : (
                          <div className="space-y-1.5">
                            {items.map((item) => (
                              <div
                                key={`${key}-${item.path}`}
                                data-testid={`git-change-row-${item.path}`}
                                className="rounded-md border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1.5"
                              >
                                <div className="flex min-w-0 items-center justify-between gap-2">
                                  <div className="flex min-w-0 items-center gap-2">
                                    <div className="min-w-0 break-all text-sm font-medium text-[var(--text)]">{item.path}</div>
                                    <span className="shrink-0 rounded border border-[var(--border)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--muted)]">
                                      {item.status.trim() || item.status}
                                    </span>
                                  </div>
                                  <div className="flex shrink-0 items-center gap-1">
                                    {(item.untracked || item.unstaged || !item.staged) ? (
                                      <button
                                        type="button"
                                        aria-label={`暂存 ${item.path}`}
                                        title={`暂存 ${item.path}`}
                                        onClick={() => void runAction(`stage:${item.path}`, () => client.stageGitPaths(botAlias, [item.path]))}
                                        disabled={actionLoading !== ""}
                                        className={iconButtonClass()}
                                      >
                                        <Plus className="h-3 w-3" />
                                      </button>
                                    ) : null}
                                    {item.staged ? (
                                      <button
                                        type="button"
                                        aria-label={`取消暂存 ${item.path}`}
                                        title={`取消暂存 ${item.path}`}
                                        onClick={() => void runAction(`unstage:${item.path}`, () => client.unstageGitPaths(botAlias, [item.path]))}
                                        disabled={actionLoading !== ""}
                                        className={iconButtonClass()}
                                      >
                                        <Minus className="h-3 w-3" />
                                      </button>
                                    ) : null}
                                    <button
                                      type="button"
                                      aria-label={`丢弃 ${item.path}`}
                                      title={`丢弃 ${item.path}`}
                                      onClick={() => void runAction(`discard:${item.path}`, () => client.discardGitPaths(botAlias, [item.path]))}
                                      disabled={actionLoading !== ""}
                                      className={iconButtonClass()}
                                    >
                                      <Trash2 className="h-3 w-3" />
                                    </button>
                                    <button
                                      type="button"
                                      aria-label={`在编辑器打开 ${item.path}`}
                                      title={`在编辑器打开 ${item.path}`}
                                      onClick={() => void openChangedDiff(item.path, item.staged && !item.unstaged)}
                                      className={iconButtonClass()}
                                    >
                                      <FileDiff className="h-3 w-3" />
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
                ) : null}
              </aside>

              <aside
                data-testid="git-commit-panel"
                className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3"
              >
                <div className="space-y-2 rounded-md border border-[var(--border)] bg-[var(--bg)] p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <GitBranch className="h-4 w-4 text-[var(--accent)]" />
                        <h2 className="truncate text-sm font-semibold">{overview.repoName}</h2>
                      </div>
                      <p className="mt-1 break-all text-xs text-[var(--muted)]">{overview.repoPath}</p>
                    </div>
                    <span className={clsx(
                      "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
                      overview.isClean ? "bg-emerald-50 text-emerald-700" : "bg-yellow-50 text-yellow-700",
                    )}>
                      {overview.isClean ? "工作区干净" : "存在改动"}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-md border border-[var(--border)] px-2 py-2">
                      <div className="text-[var(--muted)]">当前分支</div>
                      <div className="mt-1 truncate font-medium">{overview.currentBranch || "-"}</div>
                    </div>
                    <div className="rounded-md border border-[var(--border)] px-2 py-2">
                      <div className="text-[var(--muted)]">Ahead / Behind</div>
                      <div className="mt-1 font-medium">{overview.aheadCount} / {overview.behindCount}</div>
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void runAction("fetch", () => client.fetchGitRemote(botAlias))}
                    disabled={actionLoading !== ""}
                    className={buttonClass()}
                  >
                    <DownloadCloud className="h-3.5 w-3.5" />
                    Fetch
                  </button>
                  <button
                    type="button"
                    onClick={() => void runAction("pull", () => client.pullGitRemote(botAlias))}
                    disabled={actionLoading !== ""}
                    className={buttonClass()}
                  >
                    <DownloadCloud className="h-3.5 w-3.5" />
                    Pull
                  </button>
                  <button
                    type="button"
                    onClick={() => void runAction("push", () => client.pushGitRemote(botAlias))}
                    disabled={actionLoading !== ""}
                    className={buttonClass()}
                  >
                    <UploadCloud className="h-3.5 w-3.5" />
                    Push
                  </button>
                  <button
                    type="button"
                    onClick={() => void runAction("stash", () => client.stashGitChanges(botAlias))}
                    disabled={actionLoading !== ""}
                    className={buttonClass()}
                  >
                    <Archive className="h-3.5 w-3.5" />
                    Stash Push
                  </button>
                  <button
                    type="button"
                    onClick={() => void runAction("stash-pop", () => client.popGitStash(botAlias))}
                    disabled={actionLoading !== ""}
                    className={buttonClass()}
                  >
                    <ArchiveRestore className="h-3.5 w-3.5" />
                    Stash Pop
                  </button>
                </div>

                <div className="space-y-2">
                  <h2 className="text-sm font-semibold">提交更改</h2>
                  <textarea
                    value={commitMessage}
                    onChange={(event) => setCommitMessage(event.target.value)}
                    rows={5}
                    placeholder="输入 commit message"
                    className="w-full resize-none rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
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
                      className={buttonClass()}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      暂存全部
                    </button>
                    <button
                      type="button"
                      onClick={() => void runAction("discard-all", () => client.discardAllGitChanges(botAlias))}
                      disabled={actionLoading !== "" || overview.isClean}
                      className={buttonClass()}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      丢弃全部
                    </button>
                    <button
                      type="button"
                      onClick={() => void runAction("commit", () => client.commitGitChanges(botAlias, commitMessage))}
                      disabled={actionLoading !== "" || overview.isClean}
                      className={buttonClass("primary")}
                    >
                      <SendHorizontal className="h-3.5 w-3.5" />
                      {actionLoading === "commit" ? "提交中..." : "提交更改"}
                    </button>
                  </div>
                </div>

                <div data-testid="git-recent-commits-panel" className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <h2 className="text-sm font-semibold">最近提交</h2>
                    <button
                      type="button"
                      aria-label={commitsCollapsed ? "展开最近提交" : "收起最近提交"}
                      onClick={() => setCommitsCollapsed((value) => !value)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--border)] hover:bg-[var(--surface-strong)]"
                    >
                      {commitsCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                  {!commitsCollapsed ? (
                    overview.recentCommits.length === 0 ? (
                      <div className="rounded-md border border-dashed border-[var(--border)] px-3 py-2 text-xs text-[var(--muted)]">
                        当前仓库还没有提交记录
                      </div>
                    ) : (
                      <div data-testid="git-recent-commits-content" className="space-y-2">
                        {overview.recentCommits.map((item) => (
                          <div key={item.hash} className="rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                            <div className="text-sm font-medium text-[var(--text)]">{item.subject}</div>
                            <div className="mt-1 text-[11px] text-[var(--muted)]">
                              {item.shortHash} · {item.authorName} · {item.authoredAt}
                            </div>
                          </div>
                        ))}
                      </div>
                    )
                  ) : null}
                </div>
              </aside>
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
