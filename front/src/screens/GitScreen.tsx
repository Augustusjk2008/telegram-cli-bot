import { clsx } from "clsx";
import { useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  DownloadCloud,
  Eye,
  FileDiff,
  GitBranch,
  GitFork,
  GitPullRequest,
  LoaderCircle,
  Minus,
  Plus,
  RefreshCw,
  Save,
  SendHorizontal,
  Sparkles,
  Trash2,
  UploadCloud,
  UserRound,
} from "lucide-react";
import { BotIdentity } from "../components/BotIdentity";
import { GitCommitCliConfigPanel } from "../components/GitCommitCliConfigPanel";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  GitBlamePayload,
  GitBranchList,
  GitIdentityConfig,
  GitIdentityScope,
  GitOverview,
  GitStashList,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  client?: WebBotClient;
  embedded?: boolean;
  onOpenDiff?: (path: string, staged: boolean) => void | Promise<void>;
  onOverviewChange?: (overview: GitOverview | null) => void;
  sessionCapabilities?: string[];
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
      ? "bg-[var(--accent)] text-[var(--accent-foreground)] hover:opacity-90"
      : "border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] hover:bg-[var(--surface-strong)]",
  );
}

function sectionClass(extra = "") {
  return clsx("min-w-0 bg-[var(--workbench-panel-bg)]", extra);
}

function sectionStackClass(extra = "") {
  return clsx("min-w-0 space-y-2 bg-[var(--workbench-titlebar-bg)]", extra);
}

function sectionHeaderClass(extra = "") {
  return clsx(
    "flex items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--surface-strong)] px-3 py-1.5",
    extra,
  );
}

function sectionBodyClass(extra = "") {
  return clsx("px-3", extra);
}

function listClass(extra = "") {
  return clsx("divide-y divide-[var(--border)]/70", extra);
}

function listRowClass(extra = "") {
  return clsx(
    "flex min-w-0 items-center justify-between gap-2 px-1.5 py-1.5 hover:bg-[var(--surface-strong)]",
    extra,
  );
}

function emptyStateClass(extra = "") {
  return clsx("border border-dashed border-[var(--border)] px-3 py-2 text-xs text-[var(--muted)]", extra);
}

function identityForScope(config: GitIdentityConfig | null, scope: GitIdentityScope) {
  return scope === "local" ? config?.local : config?.global;
}

export function GitScreen({
  botAlias,
  botAvatarName,
  client = new MockWebBotClient(),
  embedded = false,
  onOpenDiff,
  onOverviewChange,
  sessionCapabilities = [],
}: Props) {
  const [overview, setOverview] = useState<GitOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [commitMessage, setCommitMessage] = useState("");
  const [actionLoading, setActionLoading] = useState("");
  const [branches, setBranches] = useState<GitBranchList>({ currentBranch: "", branches: [] });
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [branchDraft, setBranchDraft] = useState("");
  const [selectedBranch, setSelectedBranch] = useState("");
  const [stashes, setStashes] = useState<GitStashList>({ items: [] });
  const [stashesLoading, setStashesLoading] = useState(false);
  const [blame, setBlame] = useState<GitBlamePayload | null>(null);
  const [blameLoadingPath, setBlameLoadingPath] = useState("");
  const [changesCollapsed, setChangesCollapsed] = useState(false);
  const [commitsCollapsed, setCommitsCollapsed] = useState(false);
  const [identityConfig, setIdentityConfig] = useState<GitIdentityConfig | null>(null);
  const [identityScope, setIdentityScope] = useState<GitIdentityScope>("global");
  const [identityName, setIdentityName] = useState("");
  const [identityEmail, setIdentityEmail] = useState("");
  const [identityLoading, setIdentityLoading] = useState(false);
  const canManageBotRuntime = sessionCapabilities.length === 0 || sessionCapabilities.includes("admin_ops");
  const canManageCliParams = canManageBotRuntime || sessionCapabilities.includes("manage_cli_params");
  const isGeneratingCommitMessage = actionLoading === "generate-commit-message";
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
    void loadIdentityConfig("global");
  }, [botAlias, client]);

  useEffect(() => {
    if (overview?.repoFound) {
      void loadBranches();
      void loadStashes();
    } else {
      setBranches({ currentBranch: "", branches: [] });
      setSelectedBranch("");
      setStashes({ items: [] });
      setBlame(null);
    }
  }, [botAlias, client, overview?.repoFound]);

  function applyIdentityDraft(config: GitIdentityConfig, scope: GitIdentityScope) {
    const nextScope = scope === "local" && !config.repoFound ? "global" : scope;
    const identity = identityForScope(config, nextScope);
    setIdentityScope(nextScope);
    setIdentityName(identity?.name || "");
    setIdentityEmail(identity?.email || "");
  }

  async function loadIdentityConfig(preferredScope = identityScope) {
    setIdentityLoading(true);
    try {
      const next = await client.getGitIdentityConfig(botAlias);
      setIdentityConfig(next);
      applyIdentityDraft(next, preferredScope);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 Git 用户失败");
    } finally {
      setIdentityLoading(false);
    }
  }

  function selectIdentityScope(scope: GitIdentityScope) {
    setIdentityScope(scope);
    const identity = identityForScope(identityConfig, scope);
    setIdentityName(identity?.name || "");
    setIdentityEmail(identity?.email || "");
  }

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

  async function loadBranches() {
    setBranchesLoading(true);
    try {
      const next = await client.listGitBranches(botAlias);
      setBranches(next);
      setSelectedBranch(next.currentBranch || next.branches[0]?.name || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载分支失败");
    } finally {
      setBranchesLoading(false);
    }
  }

  async function loadStashes() {
    setStashesLoading(true);
    try {
      setStashes(await client.listGitStashes(botAlias));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 stash 失败");
    } finally {
      setStashesLoading(false);
    }
  }

  async function createBranch() {
    const name = branchDraft.trim();
    if (!name) {
      setError("分支名不能为空");
      return;
    }
    setActionLoading("branch-create");
    setError("");
    setNotice("");
    try {
      const next = await client.createGitBranch(botAlias, name, "");
      setBranches(next);
      setSelectedBranch(name);
      setBranchDraft("");
      setNotice("分支已创建");
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建分支失败");
    } finally {
      setActionLoading("");
    }
  }

  async function switchBranch() {
    if (!selectedBranch) {
      setError("请选择要切换的分支");
      return;
    }
    setActionLoading("branch-switch");
    setError("");
    setNotice("");
    try {
      const next = await client.switchGitBranch(botAlias, selectedBranch);
      setBranches(next);
      await loadOverview();
      setNotice(`已切换到 ${selectedBranch}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换分支失败");
    } finally {
      setActionLoading("");
    }
  }

  async function stashChanges() {
    await runAction("stash", () => client.stashGitChanges(botAlias));
    await loadStashes();
  }

  async function applyStash(ref: string) {
    await runAction(`stash-apply:${ref}`, () => client.applyGitStash(botAlias, ref));
    await loadStashes();
  }

  async function dropStash(ref: string) {
    await runAction(`stash-drop:${ref}`, () => client.dropGitStash(botAlias, ref));
    await loadStashes();
  }

  async function loadBlame(path: string) {
    setBlameLoadingPath(path);
    setError("");
    try {
      setBlame(await client.getGitBlame(botAlias, path));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 blame 失败");
    } finally {
      setBlameLoadingPath("");
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

  async function saveGitIdentity() {
    const name = identityName.trim();
    const email = identityEmail.trim();
    if (!name || !email) {
      setError("Git 用户名和邮箱不能为空");
      return;
    }
    if (identityScope === "local" && !identityConfig?.repoFound) {
      setError("当前目录不在 Git 仓库中，无法保存局部配置");
      return;
    }
    setActionLoading("git-identity");
    setError("");
    setNotice("");
    try {
      const next = await client.updateGitIdentityConfig(botAlias, { scope: identityScope, name, email });
      setIdentityConfig(next);
      applyIdentityDraft(next, identityScope);
      setNotice(identityScope === "local" ? "当前仓库 Git 用户已保存" : "全局 Git 用户已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 Git 用户失败");
    } finally {
      setActionLoading("");
    }
  }

  async function generateCommitMessage() {
    setActionLoading("generate-commit-message");
    setError("");
    setNotice("");
    try {
      const result = await client.generateGitCommitMessage(botAlias);
      setCommitMessage(result.message);
      setNotice("已生成提交说明");
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成提交说明失败");
    } finally {
      setActionLoading("");
    }
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

      <section
        data-testid="git-scroll-region"
        className={clsx(
          "min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto",
          embedded ? "bg-[var(--workbench-titlebar-bg)] py-0.5" : "py-3",
        )}
      >
        <div className={sectionStackClass()}>
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
            <section className={sectionClass()}>
              <div className={sectionBodyClass("space-y-2")}>
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
                className={clsx("ml-3 mt-4", buttonClass("primary"))}
              >
                {actionLoading === "init" ? "初始化中..." : "初始化 Git 仓库"}
              </button>
            </section>
          ) : null}

          {!loading && overview && overview.repoFound ? (
            <div
              data-testid="git-desktop-shell"
              className={sectionStackClass()}
            >
              <section
                data-testid="git-changes-panel"
                className={sectionClass()}
              >
                <div className={sectionHeaderClass()}>
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
                  <div data-testid="git-changes-content" className={sectionBodyClass("mt-2 space-y-3")}>
                    {changeGroups.map(([key, title, items]) => (
                      <div key={key} className="space-y-2">
                        <div className="flex items-center justify-between text-xs font-medium text-[var(--muted)]">
                          <span>{countLabel(title, items.length)}</span>
                          <span className={clsx("rounded-full border px-2 py-0.5", changeGroupTone(key))}>
                            {key === "staged" ? "Index" : key === "unstaged" ? "Worktree" : "New"}
                          </span>
                        </div>
                        {items.length === 0 ? (
                          <div className={emptyStateClass()}>
                            当前分组暂无文件
                          </div>
                        ) : (
                          <div className={listClass()}>
                            {items.map((item) => (
                              <div
                                key={`${key}-${item.path}`}
                                data-testid={`git-change-row-${item.path}`}
                                className={listRowClass()}
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
                                      aria-label={`查看 blame ${item.path}`}
                                      title={`查看 blame ${item.path}`}
                                      onClick={() => void loadBlame(item.path)}
                                      disabled={blameLoadingPath !== ""}
                                      className={iconButtonClass()}
                                    >
                                      <Eye className="h-3 w-3" />
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
              </section>

              {blame ? (
                <section className={sectionClass()}>
                  <div className={sectionHeaderClass()}>
                    <h2 className="min-w-0 truncate text-sm font-semibold">{blame.path} blame</h2>
                    <button type="button" onClick={() => setBlame(null)} className={buttonClass()}>
                      关闭
                    </button>
                  </div>
                  <div className={sectionBodyClass("mt-3")}>
                    <div className="max-h-80 overflow-auto rounded-md border border-[var(--border)] bg-[var(--bg)]">
                      {blame.lines.map((line) => (
                        <div
                          key={`${line.line}-${line.commit}`}
                          className="grid min-w-[520px] grid-cols-[48px_88px_minmax(100px,160px)_minmax(160px,1fr)] gap-2 border-b border-[var(--border)] px-2 py-1.5 text-xs last:border-b-0"
                        >
                          <span className="text-right font-mono text-[var(--muted)]">{line.line}</span>
                          <span className="font-mono text-[var(--text)]">{line.shortCommit}</span>
                          <span className="truncate text-[var(--muted)]" title={`${line.authorName} · ${line.summary}`}>
                            {line.authorName}
                          </span>
                          <span className="min-w-0 truncate font-mono text-[var(--text)]" title={line.content}>
                            {line.content}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </section>
              ) : null}

              <div
                data-testid="git-commit-panel"
                className={sectionStackClass()}
              >
                <section className={sectionClass("space-y-2")}>
                  <div className={sectionHeaderClass()}>
                    <div className="flex min-w-0 items-start gap-2">
                      <GitBranch className="mt-0.5 h-4 w-4 shrink-0 text-[var(--accent)]" />
                      <div className="min-w-0">
                        <h2 className="truncate text-sm font-semibold">{overview.repoName}</h2>
                        <p className="mt-1 break-all text-xs text-[var(--muted)]">{overview.repoPath}</p>
                      </div>
                    </div>
                    <span className={clsx(
                      "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
                      overview.isClean ? "bg-emerald-50 text-emerald-700" : "bg-yellow-50 text-yellow-700",
                    )}>
                      {overview.isClean ? "工作区干净" : "存在改动"}
                    </span>
                  </div>
                  <div className={sectionBodyClass("grid grid-cols-2 gap-2 text-xs")}>
                    <div className="border-l border-[var(--border)] px-2 py-1.5">
                      <div className="text-[var(--muted)]">当前分支</div>
                      <div className="mt-1 truncate font-medium">{overview.currentBranch || "-"}</div>
                    </div>
                    <div className="border-l border-[var(--border)] px-2 py-1.5">
                      <div className="text-[var(--muted)]">Ahead / Behind</div>
                      <div className="mt-1 font-medium">{overview.aheadCount} / {overview.behindCount}</div>
                    </div>
                  </div>
                </section>

                <section className={sectionClass("space-y-2")}>
                  <div className={sectionHeaderClass()}>
                    <h2 className="text-sm font-semibold">分支</h2>
                    <button type="button" onClick={() => void loadBranches()} className={buttonClass()}>
                      <RefreshCw className="h-3.5 w-3.5" />
                      刷新
                    </button>
                  </div>
                  {branchesLoading ? <p className={sectionBodyClass("text-xs text-[var(--muted)]")}>加载分支...</p> : null}
                  <div className={sectionBodyClass("flex flex-wrap gap-2")}>
                    <label className="min-w-[180px] flex-1">
                      <span className="sr-only">切换分支</span>
                      <select
                        aria-label="切换分支"
                        value={selectedBranch}
                        onChange={(event) => setSelectedBranch(event.target.value)}
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-2 text-xs"
                      >
                        {branches.branches.map((branch) => (
                          <option key={branch.name} value={branch.name}>
                            {branch.current ? "当前：" : ""}{branch.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      onClick={() => void switchBranch()}
                      disabled={actionLoading !== "" || !selectedBranch}
                      className={buttonClass()}
                    >
                      <GitPullRequest className="h-3.5 w-3.5" />
                      切换
                    </button>
                  </div>
                  <div className={sectionBodyClass("flex flex-wrap gap-2")}>
                    <label className="min-w-[180px] flex-1">
                      <span className="sr-only">新建分支名</span>
                      <input
                        aria-label="新建分支名"
                        value={branchDraft}
                        onChange={(event) => setBranchDraft(event.target.value)}
                        placeholder="feature/name"
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-2 text-xs"
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => void createBranch()}
                      disabled={actionLoading !== "" || !branchDraft.trim()}
                      className={buttonClass()}
                    >
                      <GitFork className="h-3.5 w-3.5" />
                      新建分支
                    </button>
                  </div>
                  <div className={sectionBodyClass(listClass())}>
                    {branches.branches.map((branch) => (
                      <div
                        key={branch.name}
                        className={listRowClass(clsx("block text-xs", branch.current ? "bg-[var(--surface-strong)]" : ""))}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate font-medium">{branch.name}</span>
                          <span className="shrink-0 text-[var(--muted)]">{branch.shortHash || "-"}</span>
                        </div>
                        <div className="mt-1 truncate text-[var(--muted)]">
                          {branch.upstream || "无 upstream"} · {branch.subject || "-"}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                <section className={sectionClass("space-y-2")}>
                  <div className={sectionHeaderClass()}>
                    <h2 className="text-sm font-semibold">远端</h2>
                  </div>
                  <div className={sectionBodyClass("flex flex-wrap gap-2")}>
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
                      onClick={() => void stashChanges()}
                      disabled={actionLoading !== ""}
                      className={buttonClass()}
                    >
                      <Archive className="h-3.5 w-3.5" />
                      Stash Push
                    </button>
                  </div>
                </section>

                <section className={sectionClass("space-y-2")}>
                  <div className={sectionHeaderClass()}>
                    <h2 className="text-sm font-semibold">Stash</h2>
                    <button type="button" onClick={() => void loadStashes()} className={buttonClass()}>
                      <RefreshCw className="h-3.5 w-3.5" />
                      刷新
                    </button>
                  </div>
                  {stashesLoading ? <p className={sectionBodyClass("text-xs text-[var(--muted)]")}>加载 stash...</p> : null}
                  {stashes.items.length === 0 ? (
                    <div className={sectionBodyClass()}>
                      <div className={emptyStateClass()}>
                        暂无 stash
                      </div>
                    </div>
                  ) : (
                    <div className={sectionBodyClass(listClass())}>
                      {stashes.items.map((stash) => (
                        <div key={stash.ref} className={listRowClass("items-start py-2")}>
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="font-mono text-xs font-medium text-[var(--text)]">{stash.ref}</div>
                              <div className="mt-1 break-all text-xs text-[var(--muted)]">{stash.message}</div>
                              <div className="mt-1 text-[11px] text-[var(--muted)]">
                                {stash.hash || "-"} · {stash.createdAt || "-"}
                              </div>
                            </div>
                            <div className="flex shrink-0 gap-1">
                              <button
                                type="button"
                                aria-label={`应用 ${stash.ref}`}
                                title={`应用 ${stash.ref}`}
                                onClick={() => void applyStash(stash.ref)}
                                disabled={actionLoading !== ""}
                                className={iconButtonClass()}
                              >
                                <ArchiveRestore className="h-3 w-3" />
                              </button>
                              <button
                                type="button"
                                aria-label={`删除 ${stash.ref}`}
                                title={`删除 ${stash.ref}`}
                                onClick={() => void dropStash(stash.ref)}
                                disabled={actionLoading !== ""}
                                className={iconButtonClass()}
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                <section className={sectionClass("space-y-2")}>
                  <div className={sectionHeaderClass()}>
                    <h2 className="text-sm font-semibold">提交更改</h2>
                    <button
                      type="button"
                      aria-label="生成 commit message"
                      title="生成 commit message"
                      onClick={() => void generateCommitMessage()}
                      disabled={actionLoading !== "" || overview.isClean}
                      className={buttonClass()}
                    >
                      {isGeneratingCommitMessage ? (
                        <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="h-3.5 w-3.5" />
                      )}
                      生成
                    </button>
                  </div>
                  <div className={sectionBodyClass()}>
                    <textarea
                      value={commitMessage}
                      onChange={(event) => setCommitMessage(event.target.value)}
                      rows={5}
                      placeholder="输入 commit message"
                      aria-label="commit message"
                      className="w-full resize-none rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                    />
                  </div>
                  <div className={sectionBodyClass("flex flex-wrap gap-2")}>
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
                </section>

                <section data-testid="git-recent-commits-panel" className={sectionClass("space-y-2")}>
                  <div className={sectionHeaderClass()}>
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
                      <div className={sectionBodyClass()}>
                        <div className={emptyStateClass()}>
                          当前仓库还没有提交记录
                        </div>
                      </div>
                    ) : (
                      <div data-testid="git-recent-commits-content" className={sectionBodyClass(listClass())}>
                        {overview.recentCommits.map((item) => (
                          <div key={item.hash} className={listRowClass("block px-1.5 py-2")}>
                            <div className="text-sm font-medium text-[var(--text)]">{item.subject}</div>
                            <div className="mt-1 text-[11px] text-[var(--muted)]">
                              {item.shortHash} · {item.authorName} · {item.authoredAt}
                            </div>
                          </div>
                        ))}
                      </div>
                    )
                  ) : null}
                </section>
              </div>
            </div>
          ) : null}

          {!loading ? (
            <div className={sectionStackClass()}>
              <section
                data-testid="git-identity-panel"
                className={sectionClass("space-y-3")}
              >
                <div className={sectionHeaderClass("gap-3")}>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <UserRound className="h-4 w-4 text-[var(--accent)]" />
                      <h2 className="text-sm font-semibold">Git 用户</h2>
                    </div>
                    <p className="mt-1 truncate text-xs text-[var(--muted)]">
                      {identityScope === "local" ? identityConfig?.repoPath || "当前仓库" : "全局配置"}
                    </p>
                  </div>
                  <button type="button" onClick={() => void loadIdentityConfig(identityScope)} className={buttonClass()}>
                    <RefreshCw className="h-3.5 w-3.5" />
                    刷新
                  </button>
                </div>

                {identityLoading ? <p className={sectionBodyClass("text-xs text-[var(--muted)]")}>加载 Git 用户...</p> : null}

                <div className={sectionBodyClass("flex flex-wrap gap-2")}>
                  <button
                    type="button"
                    onClick={() => selectIdentityScope("global")}
                    className={clsx(buttonClass(identityScope === "global" ? "primary" : "plain"), "min-w-20")}
                  >
                    全局
                  </button>
                  <button
                    type="button"
                    onClick={() => selectIdentityScope("local")}
                    disabled={!identityConfig?.repoFound}
                    className={clsx(buttonClass(identityScope === "local" ? "primary" : "plain"), "min-w-24")}
                  >
                    当前仓库
                  </button>
                </div>

                <div className={sectionBodyClass("grid gap-2 md:grid-cols-2")}>
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-[var(--muted)]">用户名</span>
                    <input
                      aria-label="Git 用户名"
                      value={identityName}
                      onChange={(event) => setIdentityName(event.target.value)}
                      placeholder="Your Name"
                      className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                    />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-[var(--muted)]">邮箱</span>
                    <input
                      aria-label="Git 邮箱"
                      value={identityEmail}
                      onChange={(event) => setIdentityEmail(event.target.value)}
                      placeholder="you@example.com"
                      className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                    />
                  </label>
                </div>

                <div className={sectionBodyClass("flex flex-wrap items-center justify-between gap-2")}>
                  <p className="text-xs text-[var(--muted)]">
                    {identityConfig?.repoFound ? "局部配置仅作用于当前仓库" : "当前目录无仓库，仅可保存全局配置"}
                  </p>
                  <button
                    type="button"
                    onClick={() => void saveGitIdentity()}
                    disabled={actionLoading !== "" || identityLoading || !identityName.trim() || !identityEmail.trim()}
                    className={buttonClass("primary")}
                  >
                    <Save className="h-3.5 w-3.5" />
                    {actionLoading === "git-identity" ? "保存中..." : "保存 Git 用户"}
                  </button>
                </div>
              </section>

              <section className={sectionClass("space-y-3")}>
                <div className={sectionHeaderClass("gap-3")}>
                  <div className="min-w-0">
                    <h2 className="text-sm font-semibold">Commit Message CLI</h2>
                    <p className="mt-1 truncate text-xs text-[var(--muted)]">
                      {canManageCliParams ? "可单独配置生成提交说明的 CLI" : "当前模式只读"}
                    </p>
                  </div>
                </div>
                <div className={sectionBodyClass("pb-3")}>
                  <GitCommitCliConfigPanel
                    botAlias={botAlias}
                    client={client}
                    canManage={canManageCliParams}
                  />
                </div>
              </section>
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
