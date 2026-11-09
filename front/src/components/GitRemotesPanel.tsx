import { clsx } from "clsx";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  CloudUpload,
  ExternalLink,
  Github,
  Globe,
  LoaderCircle,
  Lock,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Server,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { GitHubAccountPanel } from "./GitHubAccountPanel";
import {
  gitButtonClassName,
  gitDangerIconButtonClassName,
  gitEmptyStateClassName,
  gitFocusRing,
  gitIconButtonClassName,
  gitInputClassName,
  gitPrimaryButtonClassName,
  gitSegmentClass,
  gitSegmentGroupClassName,
  gitSelectCompactClassName,
} from "../screens/gitStyles";
import type {
  GitCapability,
  GitHubAccountStatus,
  GitHubOwner,
  GitHubRepository,
  GitRemoteEntry,
  GitRemoteList,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
  remoteWorkspace: boolean;
  repoName: string;
  remotesCapability: GitCapability;
  publishCapability: GitCapability;
  disabled: boolean;
  githubAccount: GitHubAccountStatus | null;
  githubAccountLoading: boolean;
  githubAccountError: string;
  onGitHubAccountChange: (account: GitHubAccountStatus) => void;
  onReloadGitHubAccount: () => void;
  onBusyChange: (busy: boolean) => void;
  onRepositoryChanged: () => Promise<void> | void;
};

type LinkMode = "create" | "existing";
type LinkProtocol = "https" | "ssh";

const REMOTE_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const REPO_NAME_RE = /^[A-Za-z0-9._-]{1,100}$/;

function remoteNameError(name: string) {
  if (!name) return "远端名称不能为空";
  if (name.length > 64 || !REMOTE_NAME_RE.test(name) || name.includes("..") || name.endsWith(".") || name.endsWith(".lock")) {
    return "远端名称只能包含字母、数字、点、下划线和连字符，并以字母或数字开头";
  }
  return "";
}

function repoNameError(name: string) {
  if (!REPO_NAME_RE.test(name) || name === "." || name === ".." || name.toLowerCase().endsWith(".git")) {
    return "仓库名只能包含字母、数字、点、下划线和连字符，最长 100 个字符，且不能以 .git 结尾";
  }
  return "";
}

function suggestGitHubRepoName(repoName: string) {
  const cleaned = repoName.replace(/\.git$/i, "").replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[-.]+|[-.]+$/g, "");
  return cleaned.slice(0, 100) || "my-project";
}

function defaultRemoteName(remotes: GitRemoteEntry[]) {
  const names = new Set(remotes.map((item) => item.name));
  if (!names.has("origin")) return "origin";
  return names.has("github") ? "" : "github";
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function GitRemotesPanel({
  botAlias,
  client,
  remoteWorkspace,
  repoName,
  remotesCapability,
  publishCapability,
  disabled,
  githubAccount,
  githubAccountLoading,
  githubAccountError,
  onGitHubAccountChange,
  onReloadGitHubAccount,
  onBusyChange,
  onRepositoryChanged,
}: Props) {
  const [list, setList] = useState<GitRemoteList | null>(null);
  const [loading, setLoading] = useState(false);
  const [busyKey, setBusyKey] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addUrl, setAddUrl] = useState("");
  const [editing, setEditing] = useState<{ name: string; url: string } | null>(null);
  const [publishTarget, setPublishTarget] = useState("");
  const [githubOpen, setGithubOpen] = useState(false);
  const [linkMode, setLinkMode] = useState<LinkMode>("create");
  const [owners, setOwners] = useState<GitHubOwner[]>([]);
  const [owner, setOwner] = useState("");
  const [newRepoName, setNewRepoName] = useState(() => suggestGitHubRepoName(repoName));
  const [newRepoDescription, setNewRepoDescription] = useState("");
  const [newRepoPrivate, setNewRepoPrivate] = useState(true);
  const [repos, setRepos] = useState<GitHubRepository[]>([]);
  const [reposPage, setReposPage] = useState(0);
  const [reposHasMore, setReposHasMore] = useState(false);
  const [reposLoading, setReposLoading] = useState(false);
  const [repoQuery, setRepoQuery] = useState("");
  const [selectedRepo, setSelectedRepo] = useState("");
  const [linkRemoteName, setLinkRemoteName] = useState("origin");
  const [linkProtocol, setLinkProtocol] = useState<LinkProtocol>(remoteWorkspace ? "ssh" : "https");
  const [publishAfterLink, setPublishAfterLink] = useState(true);
  const mountedRef = useRef(true);
  const onBusyChangeRef = useRef(onBusyChange);
  onBusyChangeRef.current = onBusyChange;

  const accountConnected = Boolean(githubAccount?.connected);
  const accountLogin = githubAccount?.login || "";
  const remotes = list?.remotes || [];
  const branch = list?.currentBranch || "";
  const upstreamRemote = list?.upstream ? remotes.find((item) => list.upstream.startsWith(`${item.name}/`))?.name || "" : "";
  const busy = busyKey !== "";
  const mutationDisabled = disabled || busy || !remotesCapability.available;
  const canPublish = Boolean(branch && list?.hasCommits && publishCapability.available && !disabled && !busy);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      onBusyChangeRef.current(false);
    };
  }, []);

  useEffect(() => {
    onBusyChangeRef.current(busy);
  }, [busy]);

  async function loadRemotes() {
    setLoading(true);
    try {
      const next = await client.listGitRemotes(botAlias);
      if (!mountedRef.current) return;
      setList(next);
      setError("");
    } catch (err) {
      if (mountedRef.current) setError(errorMessage(err, "读取远端失败"));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }

  useEffect(() => {
    if (remotesCapability.available) {
      void loadRemotes();
    }
  }, [botAlias, client, remotesCapability.available]);

  useEffect(() => {
    if (!list) return;
    setPublishTarget((current) => (remotes.some((item) => item.name === current) ? current : remotes[0]?.name || ""));
    setLinkRemoteName((current) => (current && !remotes.some((item) => item.name === current) ? current : defaultRemoteName(remotes)));
    setPublishAfterLink(Boolean(list.currentBranch && list.hasCommits && !list.upstream));
  }, [list]);

  useEffect(() => {
    // A different (or no) GitHub identity invalidates loaded owners and repositories.
    setOwners([]);
    setOwner(accountLogin);
    setRepos([]);
    setReposPage(0);
    setReposHasMore(false);
    setSelectedRepo("");
  }, [accountLogin]);

  async function loadOwners() {
    try {
      const next = await client.listGitHubOwners();
      if (!mountedRef.current) return;
      setOwners(next);
      setOwner((current) => (next.some((item) => item.login === current) ? current : next[0]?.login || accountLogin));
    } catch (err) {
      if (mountedRef.current) setError(errorMessage(err, "读取 GitHub 组织失败"));
    }
  }

  async function loadRepos(page: number) {
    setReposLoading(true);
    try {
      const next = await client.listGitHubRepositories(page);
      if (!mountedRef.current) return;
      setRepos((current) => (page === 1 ? next.items : [...current, ...next.items.filter((item) => !current.some((known) => known.id === item.id))]));
      setReposPage(next.page);
      setReposHasMore(next.hasMore);
    } catch (err) {
      if (mountedRef.current) setError(errorMessage(err, "读取 GitHub 仓库失败"));
    } finally {
      if (mountedRef.current) setReposLoading(false);
    }
  }

  useEffect(() => {
    if (!githubOpen || !accountConnected) return;
    if (linkMode === "create" && owners.length === 0) {
      void loadOwners();
    }
    if (linkMode === "existing" && reposPage === 0 && !reposLoading) {
      void loadRepos(1);
    }
  }, [accountConnected, githubOpen, linkMode, owners.length, reposPage]);

  async function run(key: string, action: () => Promise<void>) {
    if (busy) return;
    setBusyKey(key);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (err) {
      if (mountedRef.current) setError(errorMessage(err, "远端操作失败"));
    } finally {
      if (mountedRef.current) setBusyKey("");
    }
  }

  async function finishMutation(next: GitRemoteList, message: string) {
    if (!mountedRef.current) return;
    setList(next);
    setNotice(message);
    await onRepositoryChanged();
  }

  function addRemote() {
    const name = addName.trim();
    const url = addUrl.trim();
    const nameError = remoteNameError(name);
    if (nameError || !url) {
      setError(nameError || "远端地址不能为空");
      return;
    }
    void run("add", async () => {
      const next = await client.addGitRemote(botAlias, name, url);
      setAddOpen(false);
      setAddName("");
      setAddUrl("");
      await finishMutation(next, `已添加远端 ${name}`);
    });
  }

  function saveRemoteUrl() {
    if (!editing) return;
    const url = editing.url.trim();
    if (!url) {
      setError("远端地址不能为空");
      return;
    }
    const name = editing.name;
    void run(`edit:${name}`, async () => {
      const next = await client.updateGitRemote(botAlias, name, url);
      setEditing(null);
      await finishMutation(next, `已更新远端 ${name}`);
    });
  }

  function removeRemote(item: GitRemoteEntry) {
    const tracking = upstreamRemote === item.name ? `\n当前分支的 upstream ${list?.upstream} 也会失效。` : "";
    if (!window.confirm(`确定移除远端 ${item.name}（${item.fetchUrl}）吗？\n会同时删除它的远端跟踪分支。${tracking}`)) {
      return;
    }
    void run(`remove:${item.name}`, async () => {
      const next = await client.removeGitRemote(botAlias, item.name);
      await finishMutation(next, `已移除远端 ${item.name}`);
    });
  }

  function publishTo(remoteName: string) {
    if (!remoteName || !canPublish) return;
    if (!window.confirm(`确定将分支 ${branch} 推送到 ${remoteName} 并设为 upstream 吗？`)) {
      return;
    }
    void run(`publish:${remoteName}`, async () => {
      const result = await client.publishGitBranch(botAlias, remoteName);
      if (!mountedRef.current) return;
      setNotice(result.message || `已发布 ${branch} 到 ${remoteName}`);
      await loadRemotes();
      await onRepositoryChanged();
    });
  }

  function credentialHint(item: GitRemoteEntry) {
    const viaHost = !list?.githubAccountAuth;
    if (item.protocol === "ssh") {
      return viaHost ? "SSH 使用远程主机的 SSH 密钥" : "SSH 使用本机 SSH 密钥";
    }
    if (item.protocol === "https" && item.github) {
      if (viaHost) return "HTTPS 使用远程主机的 Git 凭据";
      return accountConnected ? `HTTPS 使用 GitHub 账号 @${accountLogin}` : "HTTPS 使用本机 Git 凭据；连接 GitHub 账号后改用账号令牌";
    }
    if (item.protocol === "https" || item.protocol === "http") {
      return viaHost ? "使用远程主机的 Git 凭据" : "使用本机 Git 凭据";
    }
    return "";
  }

  const filteredRepos = useMemo(() => {
    const query = repoQuery.trim().toLowerCase();
    return query ? repos.filter((item) => item.fullName.toLowerCase().includes(query)) : repos;
  }, [repoQuery, repos]);

  function linkGitHubRepository() {
    const remoteName = linkRemoteName.trim();
    const nameError = remoteNameError(remoteName);
    if (nameError) {
      setError(nameError);
      return;
    }
    const existingRepo = linkMode === "existing" ? repos.find((item) => item.fullName === selectedRepo) : undefined;
    if (linkMode === "existing" && !existingRepo) {
      setError("请选择要关联的 GitHub 仓库");
      return;
    }
    const targetName = newRepoName.trim();
    if (linkMode === "create") {
      const invalid = repoNameError(targetName);
      if (invalid) {
        setError(invalid);
        return;
      }
    }
    const fullName = linkMode === "create" ? `${owner || accountLogin}/${targetName}` : existingRepo!.fullName;
    const existingRemote = remotes.find((item) => item.name === remoteName);
    const publishBranch = publishAfterLink && Boolean(branch && list?.hasCommits);
    const steps = [
      linkMode === "create" ? `在 GitHub 创建${newRepoPrivate ? "私有" : "公开"}仓库 ${fullName}` : "",
      existingRemote
        ? `将远端 ${remoteName} 从 ${existingRemote.fetchUrl} 改为 ${fullName}（${linkProtocol.toUpperCase()}）`
        : `添加远端 ${remoteName} → ${fullName}（${linkProtocol.toUpperCase()}）`,
      publishBranch ? `推送分支 ${branch} 并设为 upstream` : "",
    ].filter(Boolean);
    if (!window.confirm(`确定执行以下操作吗？\n${steps.map((step, index) => `${index + 1}. ${step}`).join("\n")}`)) {
      return;
    }
    void run("github-link", async () => {
      let repository = existingRepo;
      if (linkMode === "create") {
        repository = await client.createGitHubRepository({
          owner: owner || accountLogin,
          name: targetName,
          description: newRepoDescription.trim(),
          private: newRepoPrivate,
        });
        if (mountedRef.current) {
          setRepos((current) => [repository!, ...current.filter((item) => item.id !== repository!.id)]);
        }
      }
      const url = linkProtocol === "ssh" ? repository!.sshUrl : repository!.cloneUrl;
      let next: GitRemoteList;
      try {
        next = existingRemote
          ? await client.updateGitRemote(botAlias, remoteName, url)
          : await client.addGitRemote(botAlias, remoteName, url);
      } catch (err) {
        throw new Error(linkMode === "create"
          ? `仓库 ${repository!.fullName} 已创建，但关联远端失败：${errorMessage(err, "未知错误")}`
          : errorMessage(err, "关联远端失败"));
      }
      if (!mountedRef.current) return;
      setList(next);
      let message = `${linkMode === "create" ? "已创建并关联" : "已关联"} ${repository!.fullName} 为远端 ${remoteName}`;
      if (publishBranch) {
        try {
          await client.publishGitBranch(botAlias, remoteName);
          message += `，并发布分支 ${branch}`;
          await loadRemotes();
        } catch (err) {
          if (mountedRef.current) setError(`远端已关联，但发布分支失败：${errorMessage(err, "未知错误")}`);
        }
      }
      if (!mountedRef.current) return;
      setNotice(message);
      setGithubOpen(false);
      await onRepositoryChanged();
    });
  }

  const statusText = loading && !list
    ? "读取远端…"
    : !list
      ? ""
      : !branch
        ? "当前为分离 HEAD，无法发布分支"
        : list.upstream
          ? `${branch} → ${list.upstream}`
          : `${branch} 尚未设置 upstream`;

  return (
    <div data-testid="git-remotes-panel" className="min-w-0 space-y-1.5">
      <div className="flex min-w-0 items-center gap-0.5 pl-3 pr-1.5">
        <p className="min-w-0 flex-1 truncate font-mono text-[11px] text-[var(--muted)]" title={statusText}>{statusText}</p>
        <button
          type="button"
          aria-label="关联 GitHub 仓库"
          aria-pressed={githubOpen}
          title={!remotesCapability.available ? remotesCapability.reason : "关联 GitHub 仓库"}
          onClick={() => setGithubOpen((value) => !value)}
          disabled={!remotesCapability.available}
          className={clsx(gitIconButtonClassName, githubOpen ? "text-[var(--accent)]" : "")}
        >
          <Github className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="添加远端"
          aria-pressed={addOpen}
          title={!remotesCapability.available ? remotesCapability.reason : "添加远端"}
          onClick={() => {
            setAddOpen((value) => !value);
            setAddName((current) => current || defaultRemoteName(remotes));
          }}
          disabled={mutationDisabled}
          className={gitIconButtonClassName}
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="刷新远端"
          title="刷新远端"
          onClick={() => void loadRemotes()}
          disabled={!remotesCapability.available || loading}
          className={gitIconButtonClassName}
        >
          <RefreshCw className={clsx("h-3.5 w-3.5", loading ? "animate-spin" : "")} />
        </button>
      </div>

      {!remotesCapability.available ? (
        <p className="px-3 text-xs text-[var(--muted)]">远端管理不可用：{remotesCapability.reason || "服务端未提供原因"}</p>
      ) : null}
      {error ? (
        <div role="alert" className="mx-2 break-words rounded-md border border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] px-2 py-1.5 text-xs text-[var(--status-danger)]">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div role="status" className="mx-2 break-words rounded-md border border-[var(--status-success-border)] bg-[var(--status-success-bg)] px-2 py-1.5 text-xs text-[var(--status-success)]">
          {notice}
        </div>
      ) : null}

      {list && branch && !list.upstream && remotes.length > 0 ? (
        <div data-testid="git-publish-branch" className="mx-2 flex min-w-0 flex-wrap items-center gap-1 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-1">
          <span className="min-w-0 flex-1 px-1 text-xs">
            发布 <span className="font-mono font-semibold">{branch}</span> 到
          </span>
          <label>
            <span className="sr-only">发布目标远端</span>
            <select
              aria-label="发布目标远端"
              value={publishTarget}
              onChange={(event) => setPublishTarget(event.target.value)}
              disabled={!canPublish}
              className={gitSelectCompactClassName}
            >
              {remotes.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
            </select>
          </label>
          <button
            type="button"
            onClick={() => publishTo(publishTarget)}
            disabled={!canPublish || !publishTarget}
            title={!list.hasCommits ? "先提交后才能发布" : !publishCapability.available ? publishCapability.reason : "推送当前分支并设为 upstream"}
            className={gitPrimaryButtonClassName}
          >
            {busyKey === `publish:${publishTarget}` ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <CloudUpload className="h-3.5 w-3.5" />}
            发布分支
          </button>
          {!list.hasCommits ? <p className="w-full px-1 text-[11px] text-[var(--muted)]">当前分支还没有提交，先提交后再发布。</p> : null}
        </div>
      ) : null}

      {list && remotes.length === 0 ? (
        <div className={gitEmptyStateClassName}>
          尚未配置远端。可
          <button type="button" onClick={() => setGithubOpen(true)} disabled={!remotesCapability.available} className="mx-0.5 text-[var(--accent)] underline disabled:opacity-50">
            关联 GitHub 仓库
          </button>
          或手动添加。
        </div>
      ) : null}

      {remotes.map((item) => {
        const isEditing = editing?.name === item.name;
        const hint = credentialHint(item);
        return (
          <div
            key={item.name}
            data-testid={`git-remote-row-${item.name}`}
            className="git-change-row flex min-w-0 items-start gap-1.5 py-1 pl-3 pr-1.5 text-xs transition-colors hover:bg-[var(--workbench-hover-bg)]"
          >
            <span className="mt-0.5 inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center text-[var(--muted)]">
              {item.github ? <Github className="h-3.5 w-3.5" /> : item.protocol === "ssh" ? <Server className="h-3 w-3" /> : <Globe className="h-3 w-3" />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-1.5">
                <span className="shrink-0 font-mono font-semibold text-[var(--text)]">{item.name}</span>
                {upstreamRemote === item.name ? (
                  <span className="shrink-0 rounded bg-[var(--workbench-active-bg)] px-1 text-[10px] text-[var(--accent)]">upstream</span>
                ) : null}
                {item.github ? (
                  <a
                    href={item.github.htmlUrl}
                    target="_blank"
                    rel="noreferrer"
                    title={`在 GitHub 打开 ${item.github.fullName}`}
                    className={clsx("inline-flex min-w-0 items-center gap-0.5 text-[10.5px] text-[var(--accent)] hover:underline", gitFocusRing)}
                  >
                    <span className="truncate">{item.github.fullName}</span>
                    <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                  </a>
                ) : null}
              </div>
              {isEditing ? (
                <div className="mt-0.5 flex min-w-0 items-center gap-1">
                  <label className="min-w-0 flex-1">
                    <span className="sr-only">远端 {item.name} 的新地址</span>
                    <input
                      aria-label={`远端 ${item.name} 的新地址`}
                      value={editing.url}
                      onChange={(event) => setEditing({ name: item.name, url: event.target.value })}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                          event.preventDefault();
                          saveRemoteUrl();
                        } else if (event.key === "Escape") {
                          setEditing(null);
                        }
                      }}
                      spellCheck={false}
                      className={gitInputClassName}
                    />
                  </label>
                  <button type="button" aria-label="保存远端地址" title="保存（fetch 与 push 同时更新）" onClick={saveRemoteUrl} disabled={mutationDisabled} className={gitIconButtonClassName}>
                    {busyKey === `edit:${item.name}` ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                  </button>
                  <button type="button" aria-label="取消编辑" title="取消" onClick={() => setEditing(null)} className={gitIconButtonClassName}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <div className="truncate font-mono text-[10.5px] leading-4 text-[var(--muted)]" title={item.fetchUrl}>{item.fetchUrl}</div>
              )}
              {!isEditing && item.pushUrl && item.pushUrl !== item.fetchUrl ? (
                <div className="truncate font-mono text-[10.5px] leading-4 text-[var(--muted)]" title={item.pushUrl}>push: {item.pushUrl}</div>
              ) : null}
              {hint ? <div className="truncate text-[10.5px] leading-4 text-[var(--muted)]" title={hint}>{hint}</div> : null}
              {item.hasEmbeddedCredentials ? (
                <div className="flex items-center gap-1 text-[10.5px] leading-4 text-[var(--status-warning)]">
                  <TriangleAlert className="h-3 w-3 shrink-0" />
                  地址中保存了凭据，建议改为不含凭据的地址
                </div>
              ) : null}
            </div>
            {!isEditing ? (
              <div className="git-change-row-actions flex shrink-0 items-center">
                {branch && upstreamRemote !== item.name ? (
                  <button
                    type="button"
                    aria-label={`发布到 ${item.name}`}
                    title={!list?.hasCommits ? "先提交后才能发布" : !publishCapability.available ? publishCapability.reason : `推送 ${branch} 到 ${item.name} 并设为 upstream`}
                    onClick={() => publishTo(item.name)}
                    disabled={!canPublish}
                    className={gitIconButtonClassName}
                  >
                    {busyKey === `publish:${item.name}` ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <CloudUpload className="h-3.5 w-3.5" />}
                  </button>
                ) : null}
                <button
                  type="button"
                  aria-label={`编辑远端 ${item.name}`}
                  title="修改地址"
                  onClick={() => setEditing({ name: item.name, url: item.fetchUrl })}
                  disabled={mutationDisabled}
                  className={gitIconButtonClassName}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  aria-label={`移除远端 ${item.name}`}
                  title="移除远端"
                  onClick={() => removeRemote(item)}
                  disabled={mutationDisabled}
                  className={gitDangerIconButtonClassName}
                >
                  {busyKey === `remove:${item.name}` ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                </button>
              </div>
            ) : null}
          </div>
        );
      })}

      {addOpen ? (
        <div data-testid="git-remote-add-form" className="mx-2 space-y-1 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-1.5">
          <div className="flex min-w-0 items-center gap-1">
            <label className="w-24 shrink-0">
              <span className="sr-only">远端名称</span>
              <input aria-label="远端名称" value={addName} onChange={(event) => setAddName(event.target.value)} placeholder="origin" spellCheck={false} className={gitInputClassName} />
            </label>
            <label className="min-w-0 flex-1">
              <span className="sr-only">远端地址</span>
              <input
                aria-label="远端地址"
                value={addUrl}
                onChange={(event) => setAddUrl(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    addRemote();
                  }
                }}
                placeholder="https://github.com/owner/repo.git"
                spellCheck={false}
                className={gitInputClassName}
              />
            </label>
          </div>
          <div className="flex items-center justify-end gap-1">
            <button type="button" onClick={() => setAddOpen(false)} className={gitButtonClassName}>取消</button>
            <button type="button" onClick={addRemote} disabled={mutationDisabled || !addName.trim() || !addUrl.trim()} className={gitPrimaryButtonClassName}>
              {busyKey === "add" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
              添加
            </button>
          </div>
        </div>
      ) : null}

      {githubOpen ? (
        <div data-testid="git-github-link-panel" className="mx-2 space-y-2 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <Github className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
            <h3 className="min-w-0 flex-1 truncate text-xs font-semibold">
              关联 GitHub 仓库{accountConnected ? <span className="font-normal text-[var(--muted)]"> · @{accountLogin}</span> : null}
            </h3>
            <button type="button" aria-label="关闭 GitHub 关联" title="关闭" onClick={() => setGithubOpen(false)} className={gitIconButtonClassName}>
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          {!accountConnected ? (
            <GitHubAccountPanel
              client={client}
              account={githubAccount}
              loading={githubAccountLoading}
              loadError={githubAccountError}
              disabled={disabled}
              onAccountChange={onGitHubAccountChange}
              onReload={onReloadGitHubAccount}
            />
          ) : (
            <>
              <div className={gitSegmentGroupClassName} role="group" aria-label="GitHub 关联方式">
                <button type="button" aria-pressed={linkMode === "create"} onClick={() => setLinkMode("create")} className={gitSegmentClass(linkMode === "create")}>新建仓库</button>
                <button type="button" aria-pressed={linkMode === "existing"} onClick={() => setLinkMode("existing")} className={gitSegmentClass(linkMode === "existing")}>已有仓库</button>
              </div>
              {linkMode === "create" ? (
                <div className="space-y-1.5">
                  <div className="flex min-w-0 items-center gap-1">
                    <label className="min-w-0 max-w-[45%] shrink-0">
                      <span className="sr-only">仓库所有者</span>
                      <select aria-label="仓库所有者" value={owner || accountLogin} onChange={(event) => setOwner(event.target.value)} className={clsx(gitSelectCompactClassName, "max-w-full")}>
                        {(owners.length > 0 ? owners : [{ login: accountLogin, type: "user" as const, avatarUrl: "" }]).map((item) => (
                          <option key={item.login} value={item.login}>{item.login}{item.type === "org" ? "（组织）" : ""}</option>
                        ))}
                      </select>
                    </label>
                    <span className="text-[var(--muted)]">/</span>
                    <label className="min-w-0 flex-1">
                      <span className="sr-only">新仓库名称</span>
                      <input aria-label="新仓库名称" value={newRepoName} onChange={(event) => setNewRepoName(event.target.value)} spellCheck={false} className={gitInputClassName} />
                    </label>
                  </div>
                  <label className="block">
                    <span className="sr-only">仓库描述</span>
                    <input aria-label="仓库描述" value={newRepoDescription} onChange={(event) => setNewRepoDescription(event.target.value)} placeholder="描述（可选）" maxLength={350} className={gitInputClassName} />
                  </label>
                  <div className="flex items-center gap-1.5 text-[11px] text-[var(--muted)]">
                    <div className={clsx(gitSegmentGroupClassName, "shrink-0")} role="group" aria-label="仓库可见性">
                      <button type="button" aria-pressed={newRepoPrivate} onClick={() => setNewRepoPrivate(true)} className={clsx(gitSegmentClass(newRepoPrivate), "whitespace-nowrap")}>
                        <Lock className="mr-0.5 h-3 w-3" />私有
                      </button>
                      <button type="button" aria-pressed={!newRepoPrivate} onClick={() => setNewRepoPrivate(false)} className={clsx(gitSegmentClass(!newRepoPrivate), "whitespace-nowrap")}>
                        <Globe className="mr-0.5 h-3 w-3" />公开
                      </button>
                    </div>
                    <span className="min-w-0 truncate">创建空仓库，保留本地历史</span>
                  </div>
                </div>
              ) : (
                <div className="space-y-1">
                  <label className="relative block">
                    <span className="sr-only">搜索 GitHub 仓库</span>
                    <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--muted)]" />
                    <input aria-label="搜索 GitHub 仓库" value={repoQuery} onChange={(event) => setRepoQuery(event.target.value)} placeholder="按名称筛选" className={clsx(gitInputClassName, "pl-6")} />
                  </label>
                  <div role="listbox" aria-label="GitHub 仓库" className="max-h-52 overflow-y-auto rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--bg)]">
                    {filteredRepos.map((item) => (
                      <button
                        key={item.id || item.fullName}
                        type="button"
                        role="option"
                        aria-selected={selectedRepo === item.fullName}
                        onClick={() => setSelectedRepo(item.fullName)}
                        className={clsx(
                          "flex w-full min-w-0 items-center gap-1.5 px-2 py-1 text-left text-xs transition-colors hover:bg-[var(--workbench-hover-bg)]",
                          gitFocusRing,
                          selectedRepo === item.fullName ? "bg-[var(--workbench-active-bg)]" : "",
                        )}
                      >
                        {item.private ? <Lock className="h-3 w-3 shrink-0 text-[var(--muted)]" /> : <Globe className="h-3 w-3 shrink-0 text-[var(--muted)]" />}
                        <span className="min-w-0 flex-1 truncate font-mono">{item.fullName}</span>
                        {item.archived ? <span className="shrink-0 text-[10px] text-[var(--muted)]">已归档</span> : null}
                        {!item.canPush ? <span className="shrink-0 text-[10px] text-[var(--status-warning)]">只读</span> : null}
                      </button>
                    ))}
                    {reposLoading ? <p className={gitEmptyStateClassName}>读取仓库…</p> : null}
                    {!reposLoading && filteredRepos.length === 0 ? <p className={gitEmptyStateClassName}>{repos.length === 0 ? "没有可访问的仓库" : "没有匹配的仓库"}</p> : null}
                  </div>
                  {reposHasMore ? (
                    <button type="button" onClick={() => void loadRepos(reposPage + 1)} disabled={reposLoading} className={clsx(gitButtonClassName, "w-full")}>
                      加载更多
                    </button>
                  ) : null}
                </div>
              )}
              <div className="flex min-w-0 flex-wrap items-center gap-1">
                <label className="w-24 shrink-0">
                  <span className="sr-only">关联的远端名称</span>
                  <input aria-label="关联的远端名称" value={linkRemoteName} onChange={(event) => setLinkRemoteName(event.target.value)} placeholder="origin" spellCheck={false} className={gitInputClassName} />
                </label>
                <div className={clsx(gitSegmentGroupClassName, "shrink-0")} role="group" aria-label="远端协议">
                  <button type="button" aria-pressed={linkProtocol === "https"} onClick={() => setLinkProtocol("https")} className={gitSegmentClass(linkProtocol === "https")}>HTTPS</button>
                  <button type="button" aria-pressed={linkProtocol === "ssh"} onClick={() => setLinkProtocol("ssh")} className={gitSegmentClass(linkProtocol === "ssh")}>SSH</button>
                </div>
              </div>
              <p className="text-[11px] leading-4 text-[var(--muted)]">
                {linkProtocol === "https"
                  ? (remoteWorkspace ? "HTTPS 同步使用远程主机的 Git 凭据，Orbit 不会把 GitHub 令牌发送到远程主机。" : `HTTPS 同步自动使用 GitHub 账号 @${accountLogin}。`)
                  : (remoteWorkspace ? "SSH 同步使用远程主机的 SSH 密钥。" : "SSH 同步使用本机 SSH 密钥。")}
                {remotes.some((item) => item.name === linkRemoteName.trim()) ? ` 远端 ${linkRemoteName.trim()} 已存在，将改为指向所选仓库。` : ""}
              </p>
              <label className="flex items-center gap-1.5 text-xs">
                <input
                  type="checkbox"
                  checked={publishAfterLink && Boolean(branch && list?.hasCommits)}
                  onChange={(event) => setPublishAfterLink(event.target.checked)}
                  disabled={!branch || !list?.hasCommits}
                />
                <span className="min-w-0">
                  关联后发布当前分支{branch ? <span className="font-mono"> {branch}</span> : null}
                  {!branch ? "（分离 HEAD 不可用）" : !list?.hasCommits ? "（先提交后可用）" : ""}
                </span>
              </label>
              <button
                type="button"
                onClick={linkGitHubRepository}
                disabled={mutationDisabled || (linkMode === "existing" && !selectedRepo) || (linkMode === "create" && !newRepoName.trim())}
                className={clsx(gitPrimaryButtonClassName, "w-full")}
              >
                {busyKey === "github-link" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Github className="h-3.5 w-3.5" />}
                {linkMode === "create" ? "创建并关联" : "关联所选仓库"}
              </button>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
