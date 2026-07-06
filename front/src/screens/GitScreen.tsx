import { clsx } from "clsx";
import { useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  DownloadCloud,
  GitBranch,
  GitFork,
  GitPullRequest,
  LoaderCircle,
  Minus,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  SendHorizontal,
  Sparkles,
  Trash2,
  UploadCloud,
  UserRound,
  X,
} from "lucide-react";
import { GitCommitCliConfigPanel } from "../components/GitCommitCliConfigPanel";
import { GitDiffViewer } from "../components/GitDiffViewer";
import { StateBadge } from "../components/StateBadge";
import { toolbarButtonClass } from "../components/ToolbarButton";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  GitBranchList,
  GitChangedFile,
  GitCommitGraphEdge,
  GitCommitGraphNode,
  GitCommitGraphPayload,
  GitCommitGraphRef,
  GitGraphScope,
  GitIdentityConfig,
  GitIdentityScope,
  GitOverview,
  GitDiffPayload,
  GitResetMode,
  GitSmartCommitJob,
  GitStashList,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client?: WebBotClient;
  embedded?: boolean;
  onOpenDiff?: (path: string, staged: boolean) => void | Promise<void>;
  onOverviewChange?: (overview: GitOverview | null) => void;
  sessionCapabilities?: string[];
};

type GitFileGroupKey = "staged" | "unstaged" | "untracked";
type CommitLike = Pick<GitCommitGraphNode, "hash" | "shortHash" | "subject">;
type SelectedGitDiff = GitDiffPayload & { label: string };

const GIT_GRAPH_LIMIT = 50;
const GIT_GRAPH_ROW_HEIGHT = 44;
const GIT_GRAPH_LANE_GAP = 14;
const GIT_GRAPH_LANE_PADDING = 8;
const GIT_GRAPH_NODE_RADIUS = 4;

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

function displayGitPath(path: string) {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/g, "");
  const parts = normalized.split("/").filter(Boolean);
  return parts[parts.length - 1] || path;
}

function changeStatsForGroup(item: GitChangedFile, key: GitFileGroupKey) {
  if (key === "staged") {
    return {
      additions: Number(item.stagedAdditions || 0),
      deletions: Number(item.stagedDeletions || 0),
    };
  }
  if (key === "untracked") {
    return {
      additions: Number(item.unstagedAdditions || item.additions || 0),
      deletions: Number(item.unstagedDeletions || 0),
    };
  }
  return {
    additions: Number(item.unstagedAdditions || 0),
    deletions: Number(item.unstagedDeletions || 0),
  };
}

function changeGroupTone(key: GitFileGroupKey) {
  if (key === "staged") {
    return "success";
  }
  if (key === "unstaged") {
    return "warning";
  }
  return "accent";
}

function iconButtonClass() {
  return toolbarButtonClass("ghost", "icon", "h-7 w-7 border-[var(--workbench-hairline)]");
}

function buttonClass(kind: "plain" | "primary" = "plain") {
  return toolbarButtonClass(kind, "sm");
}

function sectionClass(extra = "") {
  return clsx(
    "min-w-0 overflow-hidden rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] shadow-[var(--shadow-soft)]",
    extra,
  );
}

function sectionStackClass(extra = "") {
  return clsx("min-w-0 space-y-3 bg-[var(--workbench-titlebar-bg)]", extra);
}

function sectionHeaderClass(extra = "") {
  return clsx(
    "flex items-center justify-between gap-2 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-3 py-2",
    extra,
  );
}

function sectionBodyClass(extra = "") {
  return clsx("px-3 py-3", extra);
}

function listClass(extra = "") {
  return clsx("divide-y divide-[var(--workbench-hairline)]", extra);
}

function listRowClass(extra = "") {
  return clsx(
    "flex min-w-0 items-center justify-between gap-2 rounded-md px-2 py-2 transition-colors hover:bg-[var(--workbench-hover-bg)]",
    extra,
  );
}

function emptyStateClass(extra = "") {
  return clsx("rounded-md border border-dashed border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-3 py-2 text-xs text-[var(--muted)]", extra);
}

function identityForScope(config: GitIdentityConfig | null, scope: GitIdentityScope) {
  return scope === "local" ? config?.local : config?.global;
}

function isGitSmartCommitRunning(job: GitSmartCommitJob | null) {
  return job?.status === "queued" || job?.status === "running";
}

function gitSmartCommitPhaseText(job: GitSmartCommitJob | null) {
  if (!job) {
    return "";
  }
  if (job.phase === "staging") {
    return "暂存中...";
  }
  if (job.phase === "committing") {
    return "提交中...";
  }
  if (job.phase === "done" && job.status === "succeeded") {
    return "智能提交完成";
  }
  if (job.phase === "done" && job.status === "failed") {
    return "智能提交失败";
  }
  return "生成说明...";
}

function gitSmartCommitSuccessHash(job: GitSmartCommitJob | null, fallbackOverview: GitOverview | null = null) {
  if (!job || job.status !== "succeeded") {
    return "";
  }
  return job.overview?.recentCommits[0]?.shortHash || fallbackOverview?.recentCommits[0]?.shortHash || "";
}

function gitSmartCommitStatusText(job: GitSmartCommitJob | null, fallbackOverview: GitOverview | null = null) {
  const text = gitSmartCommitPhaseText(job);
  const hash = gitSmartCommitSuccessHash(job, fallbackOverview);
  return hash ? `${text} · ${hash}` : text;
}

function graphRefTone(ref: GitCommitGraphRef) {
  if (ref.kind === "head") {
    return "success";
  }
  if (ref.kind === "tag") {
    return "warning";
  }
  return ref.kind === "remote_branch" ? "neutral" : "accent";
}

function clampGraphColumn(value: number, laneCount: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(Math.max(Math.round(value), 0), Math.max(laneCount - 1, 0));
}

function graphLaneCount(nodes: GitCommitGraphNode[]) {
  return Math.max(
    1,
    ...nodes.map((node) => Math.max(
      node.graph.width || 1,
      node.graph.column + 1,
      ...(node.graph.edges || []).flatMap((edge) => [edge.from + 1, edge.to + 1]),
    )),
  );
}

function laneX(column: number) {
  return GIT_GRAPH_LANE_PADDING + column * GIT_GRAPH_LANE_GAP;
}

function graphEdgeKey(node: GitCommitGraphNode, edge: GitCommitGraphEdge, index: number) {
  return `${node.hash}-${edge.from}-${edge.to}-${edge.commit || index}`;
}

type GraphIncomingEdge = GitCommitGraphEdge & {
  sourceHash: string;
  sourceIndex: number;
};

function graphIncomingEdgesByRow(nodes: GitCommitGraphNode[], laneCount: number) {
  const activeEdges = new Map<number, GraphIncomingEdge>();
  return nodes.map((node) => {
    const nodeColumn = clampGraphColumn(node.graph.column, laneCount);
    const incomingEdges = Array.from(activeEdges.values());
    for (const [column, edge] of Array.from(activeEdges.entries())) {
      if (column === nodeColumn && (!edge.commit || edge.commit === node.hash)) {
        activeEdges.delete(column);
      }
    }
    (node.graph.edges || []).forEach((edge, index) => {
      const to = clampGraphColumn(edge.to, laneCount);
      activeEdges.set(to, { ...edge, to, sourceHash: node.hash, sourceIndex: index });
    });
    return incomingEdges;
  });
}

function compactGraphRefClass(ref: GitCommitGraphRef) {
  const tone = graphRefTone(ref);
  return clsx(
    "inline-flex h-4 min-w-0 max-w-24 shrink items-center rounded border px-1 text-[10px] font-medium leading-none",
    tone === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "",
    tone === "warning" ? "border-yellow-200 bg-yellow-50 text-yellow-700" : "",
    tone === "neutral" ? "border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] text-[var(--muted)]" : "",
    tone === "accent" ? "border-[var(--workbench-hover-border)] bg-[var(--workbench-active-bg)] text-[var(--accent)]" : "",
  );
}

function formatCommitGraphDate(value: string | number | Date) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type GitCommitGraphLiteProps = {
  nodes: GitCommitGraphNode[];
  selectedHash: string;
  disabled: boolean;
  onSelect: (hash: string) => void;
};

function GitCommitGraphLite({ nodes, selectedHash, disabled, onSelect }: GitCommitGraphLiteProps) {
  const laneCount = graphLaneCount(nodes);
  const laneWidth = GIT_GRAPH_LANE_PADDING * 2 + (laneCount - 1) * GIT_GRAPH_LANE_GAP;
  const midY = GIT_GRAPH_ROW_HEIGHT / 2;
  const curveOffset = Math.max(8, Math.floor(GIT_GRAPH_ROW_HEIGHT * 0.28));
  const incomingEdgesByRow = graphIncomingEdgesByRow(nodes, laneCount);

  return (
    <div className="min-w-0 divide-y divide-[var(--workbench-hairline)]">
      {nodes.map((node, rowIndex) => {
        const selected = selectedHash === node.hash;
        const nodeColumn = clampGraphColumn(node.graph.column, laneCount);
        const shortHash = node.shortHash || node.hash.slice(0, 7);
        const commitTitle = (node.message || node.subject || "-").trim() || "-";
        const incomingEdges = incomingEdgesByRow[rowIndex] || [];
        return (
          <button
            key={node.hash}
            type="button"
            data-testid={`git-graph-row-${shortHash}`}
            data-selected={selected ? "true" : "false"}
            aria-label={`选择提交 ${shortHash}`}
            onClick={() => onSelect(node.hash)}
            disabled={disabled}
            className={clsx(
              "grid w-full min-w-0 items-stretch gap-2 px-2 py-0 text-left transition-colors",
              "hover:bg-[var(--workbench-hover-bg)] disabled:cursor-not-allowed disabled:opacity-70",
              selected ? "bg-[var(--workbench-active-bg)]" : "",
            )}
            style={{ gridTemplateColumns: `${laneWidth}px minmax(0, 1fr)` }}
          >
            <svg
              data-testid={`git-graph-lanes-${shortHash}`}
              aria-hidden="true"
              width={laneWidth}
              height={GIT_GRAPH_ROW_HEIGHT}
              viewBox={`0 0 ${laneWidth} ${GIT_GRAPH_ROW_HEIGHT}`}
              className="block overflow-visible"
            >
              {Array.from({ length: laneCount }, (_, column) => (
                <line
                  key={`lane-${column}`}
                  x1={laneX(column)}
                  x2={laneX(column)}
                  y1="0"
                  y2={GIT_GRAPH_ROW_HEIGHT}
                  stroke="var(--workbench-hairline)"
                  strokeWidth="1"
                />
              ))}
              {incomingEdges.map((edge, index) => {
                const to = clampGraphColumn(edge.to, laneCount);
                const toX = laneX(to);
                const landsOnNode = to === nodeColumn && (!edge.commit || edge.commit === node.hash);
                return (
                  <path
                    key={`incoming-${graphEdgeKey(nodes[rowIndex - 1], edge, index)}`}
                    data-testid={`git-graph-incoming-${shortHash}-${index}`}
                    d={`M ${toX} 0 L ${toX} ${landsOnNode ? midY : GIT_GRAPH_ROW_HEIGHT}`}
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth="2"
                    strokeLinecap="round"
                    opacity={landsOnNode ? 0.95 : 0.58}
                  />
                );
              })}
              {(node.graph.edges || []).map((edge, index) => {
                const from = clampGraphColumn(edge.from, laneCount);
                const to = clampGraphColumn(edge.to, laneCount);
                const fromX = laneX(from);
                const toX = laneX(to);
                const path = from === to
                  ? `M ${fromX} ${midY} L ${toX} ${GIT_GRAPH_ROW_HEIGHT}`
                  : `M ${fromX} ${midY} C ${fromX} ${midY + curveOffset}, ${toX} ${GIT_GRAPH_ROW_HEIGHT - curveOffset}, ${toX} ${GIT_GRAPH_ROW_HEIGHT}`;
                return (
                  <path
                    key={graphEdgeKey(node, edge, index)}
                    data-testid={`git-graph-edge-${shortHash}-${index}`}
                    d={path}
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth="2"
                    strokeLinecap="round"
                    opacity={from === nodeColumn ? 0.95 : 0.58}
                  />
                );
              })}
              <circle
                cx={laneX(nodeColumn)}
                cy={midY}
                r={GIT_GRAPH_NODE_RADIUS + 2}
                fill="var(--workbench-panel-elevated-bg)"
                stroke={selected ? "var(--accent)" : "var(--workbench-hairline)"}
                strokeWidth="1"
              />
              <circle
                data-testid={`git-graph-node-${shortHash}`}
                cx={laneX(nodeColumn)}
                cy={midY}
                r={GIT_GRAPH_NODE_RADIUS}
                fill="var(--accent)"
              />
            </svg>
            <div className="flex min-w-0 flex-col justify-center gap-0.5 py-1.5">
              <div className="flex min-w-0 items-center gap-1.5 text-[11px] text-[var(--muted)]">
                <span className="shrink-0 font-mono font-semibold text-[var(--accent)]" title={node.authorName || "-"}>
                  {shortHash} - {node.authorName || "-"}
                </span>
                <span className="min-w-0 truncate">{formatCommitGraphDate(node.authoredAt)}</span>
                {node.refs.length > 0 ? (
                  <span className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
                    {node.refs.map((ref) => (
                      <span key={`${node.hash}-${ref.kind}-${ref.name}`} className={compactGraphRefClass(ref)}>
                        <span data-testid={`git-graph-ref-${shortHash}-${ref.name}`} className="block min-w-0 truncate" title={ref.name}>
                          {ref.name}
                        </span>
                      </span>
                    ))}
                  </span>
                ) : null}
              </div>
              <div className="min-w-0 truncate text-sm font-medium text-[var(--text)]" title={commitTitle}>
                {node.subject || "-"}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export function GitScreen({
  botAlias,
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
  const [selectedDiff, setSelectedDiff] = useState<SelectedGitDiff | null>(null);
  const [diffLoadingPath, setDiffLoadingPath] = useState("");
  const [diffError, setDiffError] = useState("");
  const [changesCollapsed, setChangesCollapsed] = useState(false);
  const [graphCollapsed, setGraphCollapsed] = useState(false);
  const [graphScope, setGraphScope] = useState<GitGraphScope>("all");
  const [graphPayload, setGraphPayload] = useState<GitCommitGraphPayload | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [selectedGraphHash, setSelectedGraphHash] = useState("");
  const [graphBranchDraft, setGraphBranchDraft] = useState("");
  const [graphResetMode, setGraphResetMode] = useState<GitResetMode>("mixed");
  const [identityConfig, setIdentityConfig] = useState<GitIdentityConfig | null>(null);
  const [identityScope, setIdentityScope] = useState<GitIdentityScope>("global");
  const [identityName, setIdentityName] = useState("");
  const [identityEmail, setIdentityEmail] = useState("");
  const [identityLoading, setIdentityLoading] = useState(false);
  const [smartCommitJob, setSmartCommitJob] = useState<GitSmartCommitJob | null>(null);
  const canManageBotRuntime = sessionCapabilities.length === 0 || sessionCapabilities.includes("admin_ops");
  const canManageCliParams = canManageBotRuntime || sessionCapabilities.includes("manage_cli_params");
  const isGeneratingCommitMessage = actionLoading === "generate-commit-message";
  const isSmartCommitRunning = isGitSmartCommitRunning(smartCommitJob);
  const mutationBusy = actionLoading !== "" || isSmartCommitRunning;
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
  const selectedGraphNode = useMemo(
    () => graphPayload?.nodes.find((node) => node.hash === selectedGraphHash) || null,
    [graphPayload, selectedGraphHash],
  );

  function confirmDiscardPath(path: string) {
    return window.confirm(`确定丢弃 ${path} 的改动吗？`);
  }

  function confirmDiscardAll(count: number) {
    return window.confirm(`确定丢弃全部 ${count} 个文件的改动吗？`);
  }

  function syncOverview(next: GitOverview | null) {
    setOverview(next);
    onOverviewChange?.(next);
  }

  async function loadOverview() {
    setLoading(true);
    setError("");
    try {
      const next = await client.getGitOverview(botAlias);
      syncOverview(next);
    } catch (err) {
      syncOverview(null);
      setError(err instanceof Error ? err.message : "加载 Git 状态失败");
    } finally {
      setLoading(false);
    }
  }

  async function refreshOverviewQuietly() {
    try {
      syncOverview(await client.getGitOverview(botAlias));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 Git 状态失败");
    }
  }

  async function loadGitGraph(options: { scope?: GitGraphScope; cursor?: string; append?: boolean } = {}) {
    const scope = options.scope || graphScope;
    setGraphLoading(true);
    try {
      const next = await client.getGitCommitGraph(botAlias, {
        scope,
        limit: GIT_GRAPH_LIMIT,
        cursor: options.cursor,
      });
      setGraphPayload((current) => options.append && current
        ? { ...next, nodes: [...current.nodes, ...next.nodes] }
        : next);
      setSelectedGraphHash((current) => options.append
        ? current || next.nodes[0]?.hash || ""
        : next.nodes.some((node) => node.hash === current) ? current : next.nodes[0]?.hash || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载提交图失败");
    } finally {
      setGraphLoading(false);
    }
  }

  async function refreshGitWorkspace(options: { graph?: boolean } = {}) {
    await refreshOverviewQuietly();
    await loadBranches();
    if (options.graph !== false) {
      await loadGitGraph({ scope: graphScope });
    }
  }

  useEffect(() => {
    void loadOverview();
    void loadIdentityConfig("global");
  }, [botAlias, client]);

  useEffect(() => {
    if (overview?.repoFound) {
      void loadGitGraph({ scope: graphScope });
    } else {
      setGraphPayload(null);
      setSelectedGraphHash("");
    }
  }, [botAlias, client, overview?.repoFound, graphScope]);

  async function applySmartCommitJob(job: GitSmartCommitJob, options?: { refreshOverview?: boolean }) {
    setSmartCommitJob(job);
    if (job.message && job.status !== "succeeded") {
      setCommitMessage(job.message);
    }
    if (job.overview) {
      syncOverview(job.overview);
    }
    if (job.status === "succeeded") {
      if (options?.refreshOverview !== false) {
        await refreshOverviewQuietly();
      }
      setCommitMessage("");
      setError("");
      const hash = gitSmartCommitSuccessHash(job);
      setNotice(hash ? `智能提交完成 · ${hash}` : "智能提交完成");
      return;
    }
    if (job.status === "failed") {
      if (options?.refreshOverview !== false) {
        await refreshOverviewQuietly();
      }
      setNotice("");
      setError(job.error || "智能提交失败");
      return;
    }
    if (job.status === "canceled") {
      if (options?.refreshOverview !== false) {
        await refreshOverviewQuietly();
      }
      setNotice("");
      setError(job.error || "智能提交已取消");
      return;
    }
  }

  useEffect(() => {
    let cancelled = false;
    setSmartCommitJob(null);
    async function restoreSmartCommit() {
      try {
        const job = await client.getActiveGitSmartCommit(botAlias);
        if (cancelled || !job) {
          return;
        }
        await applySmartCommitJob(job);
      } catch (err) {
        if (cancelled) {
          return;
        }
        setError(err instanceof Error ? err.message : "加载智能提交状态失败");
      }
    }
    void restoreSmartCommit();
    return () => {
      cancelled = true;
    };
  }, [botAlias, client]);

  useEffect(() => {
    if (overview?.repoFound) {
      void loadBranches();
      void loadStashes();
    } else {
      setBranches({ currentBranch: "", branches: [] });
      setSelectedBranch("");
      setStashes({ items: [] });
      setSelectedDiff(null);
      setDiffError("");
    }
  }, [botAlias, client, overview?.repoFound]);

  useEffect(() => {
    if (!smartCommitJob?.jobId || !isSmartCommitRunning) {
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const next = await client.getGitSmartCommitJob(botAlias, smartCommitJob.jobId);
        if (cancelled) {
          return;
        }
        await applySmartCommitJob(next);
      } catch (err) {
        if (cancelled) {
          return;
        }
        setNotice("");
        setError(err instanceof Error ? err.message : "查询智能提交状态失败");
      }
    }, 1000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [botAlias, client, isSmartCommitRunning, smartCommitJob]);

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
    options: { refreshWorkspace?: boolean } = {},
  ) {
    setActionLoading(key);
    setError("");
    setNotice("");
    try {
      const result = await fn();
      syncOverview(result.overview);
      if (options.refreshWorkspace) {
        await loadBranches();
        await loadGitGraph({ scope: graphScope });
      }
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
      setBranchDraft("");
      await refreshGitWorkspace();
      setSelectedBranch(name);
      setNotice("分支已创建");
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建分支失败");
    } finally {
      setActionLoading("");
    }
  }

  async function createBranchFromTarget(commit: CommitLike, name: string, onSuccess?: () => void) {
    if (!name) {
      setError("分支名不能为空");
      return;
    }
    setActionLoading(`branch-create:${commit.hash}`);
    setError("");
    setNotice("");
    try {
      const next = await client.createGitBranch(botAlias, name, commit.hash);
      setBranches(next);
      onSuccess?.();
      await refreshGitWorkspace();
      setSelectedBranch(name);
      setNotice(`分支已从 ${commit.shortHash} 创建`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建分支失败");
    } finally {
      setActionLoading("");
    }
  }

  async function createBranchFromGraphNode() {
    if (!selectedGraphNode) {
      return;
    }
    const name = graphBranchDraft.trim();
    await createBranchFromTarget(selectedGraphNode, name, () => setGraphBranchDraft(""));
  }

  async function resetBranchToTarget(commit: CommitLike, mode: GitResetMode) {
    const currentBranch = overview?.currentBranch || branches.currentBranch || "当前分支";
    const confirmed = window.confirm(
      `确定将 ${currentBranch} 重置到 ${commit.shortHash}（${commit.subject}）吗？\n模式：${mode}`,
    );
    if (!confirmed) {
      return;
    }
    setActionLoading(`branch-reset:${commit.hash}`);
    setError("");
    setNotice("");
    try {
      const result = await client.resetGitBranch(botAlias, commit.hash, mode);
      syncOverview(result.overview);
      setBranches({ currentBranch: result.currentBranch, branches: result.branches });
      setSelectedBranch(result.currentBranch);
      await refreshGitWorkspace();
      setNotice(result.message || `已重置到 ${commit.shortHash}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置分支失败");
    } finally {
      setActionLoading("");
    }
  }

  async function resetBranchToGraphNode() {
    if (!selectedGraphNode || selectedGraphNode.canReset === false) {
      return;
    }
    await resetBranchToTarget(selectedGraphNode, graphResetMode);
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
      await refreshGitWorkspace();
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

  async function openChangedDiff(path: string, staged: boolean) {
    setNotice("");
    setDiffError("");
    if (onOpenDiff) {
      try {
        await onOpenDiff(path, staged);
      } catch (err) {
        setError(err instanceof Error ? err.message : "打开 diff 失败");
      }
      return;
    }

    const loadingKey = `${staged ? "staged" : "worktree"}:${path}`;
    setDiffLoadingPath(loadingKey);
    try {
      const diff = await client.getGitDiff(botAlias, path, staged);
      setSelectedDiff({ ...diff, label: displayGitPath(diff.path || path) });
    } catch (err) {
      setSelectedDiff(null);
      setDiffError(err instanceof Error ? err.message : "加载 diff 失败");
    } finally {
      setDiffLoadingPath("");
    }
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

  async function startSmartCommit() {
    setActionLoading("smart-commit");
    setError("");
    setNotice("");
    try {
      const job = await client.startGitSmartCommit(botAlias);
      await applySmartCommitJob(job, { refreshOverview: false });
    } catch (err) {
      setError(err instanceof Error ? err.message : "发起智能提交失败");
    } finally {
      setActionLoading("");
    }
  }

  return (
    <main className={clsx("flex h-full min-h-0 flex-col", embedded ? "bg-[var(--workbench-titlebar-bg)]" : "bg-[var(--workbench-panel-bg)]")}>
      {embedded ? null : (
        <header className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <GitBranch className="h-4 w-4 text-[var(--accent)]" />
                <h1 className="text-lg font-semibold">Git</h1>
              </div>
              <p className="truncate text-xs text-[var(--muted)]">{botAlias}</p>
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
          embedded ? "bg-[var(--workbench-titlebar-bg)] py-0.5" : "bg-[var(--workbench-panel-bg)] p-3",
        )}
      >
        <div className={sectionStackClass("mx-auto w-full max-w-6xl")}>
          {loading ? (
            <div className="rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-4 py-8 text-center text-sm text-[var(--muted)] shadow-[var(--shadow-soft)]">
              加载中...
            </div>
          ) : null}
          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 shadow-[var(--shadow-soft)]">
              {error}
            </div>
          ) : null}
          {notice ? (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 shadow-[var(--shadow-soft)]">
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
                      className={iconButtonClass()}
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      aria-label={changesCollapsed ? "展开变更" : "收起变更"}
                      onClick={() => setChangesCollapsed((value) => !value)}
                      className={iconButtonClass()}
                    >
                      {changesCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>
                {!changesCollapsed ? (
                  <div data-testid="git-changes-content" className={sectionBodyClass("space-y-2")}>
                    {changeGroups.map(([key, title, items]) => (
                      <div key={key} className="space-y-1.5">
                        <div className="flex items-center justify-between text-xs font-medium text-[var(--muted)]">
                          <span>{countLabel(title, items.length)}</span>
                          <StateBadge tone={changeGroupTone(key)}>
                            {key === "staged" ? "Index" : key === "unstaged" ? "Worktree" : "New"}
                          </StateBadge>
                        </div>
                        {items.length === 0 ? (
                          <div className={emptyStateClass()}>
                            当前分组暂无文件
                          </div>
                        ) : (
                          <div className="divide-y divide-[var(--workbench-hairline)] rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)]">
                            {items.map((item) => {
                              const stats = changeStatsForGroup(item, key);
                              const stagedDiff = key === "staged";
                              const diffLoadingKey = `${stagedDiff ? "staged" : "worktree"}:${item.path}`;
                              const diffLoading = diffLoadingPath === diffLoadingKey;
                              return (
                                <div
                                  key={`${key}-${item.path}`}
                                  data-testid={`git-change-row-${item.path}`}
                                  data-full-path={item.path}
                                  className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 px-2 py-1.5 text-xs transition-colors hover:bg-[var(--workbench-hover-bg)]"
                                >
                                  <button
                                    type="button"
                                    aria-label={`打开 diff ${item.path}`}
                                    title={item.path}
                                    data-full-path={item.path}
                                    onClick={() => void openChangedDiff(item.path, stagedDiff)}
                                    disabled={diffLoading}
                                    className="min-w-0 truncate text-left font-medium text-[var(--text)] hover:text-[var(--accent)] disabled:opacity-60"
                                  >
                                    {diffLoading ? (
                                      <span className="inline-flex min-w-0 items-center gap-1">
                                        <LoaderCircle className="h-3 w-3 shrink-0 animate-spin" />
                                        <span className="min-w-0 truncate">{displayGitPath(item.path)}</span>
                                      </span>
                                    ) : (
                                      displayGitPath(item.path)
                                    )}
                                  </button>
                                  <div className="flex shrink-0 items-center gap-1.5">
                                    <span className="rounded border border-[var(--border)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--muted)]">
                                      {item.status.trim() || item.status}
                                    </span>
                                    <span className="font-mono text-[10px] text-emerald-600">+{stats.additions}</span>
                                    <span className="font-mono text-[10px] text-red-600">-{stats.deletions}</span>
                                  </div>
                                  <div className="flex shrink-0 items-center gap-1">
                                    {(item.untracked || item.unstaged || !item.staged) ? (
                                      <button
                                        type="button"
                                        aria-label={`暂存 ${item.path}`}
                                        title={`暂存 ${item.path}`}
                                        onClick={() => void runAction(`stage:${item.path}`, () => client.stageGitPaths(botAlias, [item.path]))}
                                        disabled={mutationBusy}
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
                                        disabled={mutationBusy}
                                        className={iconButtonClass()}
                                      >
                                        <Minus className="h-3 w-3" />
                                      </button>
                                    ) : null}
                                    <button
                                      type="button"
                                      aria-label={`丢弃 ${item.path}`}
                                      title={`丢弃 ${item.path}`}
                                      onClick={() => {
                                        if (!confirmDiscardPath(item.path)) {
                                          return;
                                        }
                                        void runAction(`discard:${item.path}`, () => client.discardGitPaths(botAlias, [item.path]));
                                      }}
                                      disabled={mutationBusy}
                                      className={iconButtonClass()}
                                    >
                                      <Trash2 className="h-3 w-3" />
                                    </button>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    ))}
                    {diffError ? (
                      <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                        {diffError}
                      </div>
                    ) : null}
                    {selectedDiff ? (
                      <div data-testid="git-diff-panel" className="min-w-0 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)]">
                        <div className="flex min-w-0 items-center justify-between gap-2 border-b border-[var(--workbench-hairline)] px-2 py-1.5">
                          <div className="flex min-w-0 items-center gap-2">
                            <h3 className="min-w-0 truncate text-xs font-semibold text-[var(--text)]" title={selectedDiff.path}>
                              {selectedDiff.label}
                            </h3>
                            <StateBadge tone={selectedDiff.staged ? "success" : "warning"}>
                              {selectedDiff.staged ? "Index" : "Worktree"}
                            </StateBadge>
                          </div>
                          <button
                            type="button"
                            aria-label="关闭 diff"
                            title="关闭 diff"
                            onClick={() => {
                              setSelectedDiff(null);
                              setDiffError("");
                            }}
                            className={iconButtonClass()}
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </div>
                        {selectedDiff.truncated ? (
                          <div className="border-b border-[var(--workbench-hairline)] px-2 py-1 text-[10px] text-[var(--muted)]">
                            Diff 已截断
                          </div>
                        ) : null}
                        <GitDiffViewer
                          content={selectedDiff.diff || ""}
                          testId="git-diff-content"
                          className="max-h-80 px-2 py-2 text-[11px] leading-5"
                          ariaLabel={`Git Diff 内容：${selectedDiff.label}`}
                        />
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </section>

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
                    <StateBadge tone={overview.isClean ? "success" : "warning"} className="shrink-0">
                      {overview.isClean ? "工作区干净" : "存在改动"}
                    </StateBadge>
                  </div>
                  <div className={sectionBodyClass("grid grid-cols-2 gap-2 text-xs")}>
                    <div className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-3 py-2">
                      <div className="text-[var(--muted)]">当前分支</div>
                      <div className="mt-1 truncate font-medium">{overview.currentBranch || "-"}</div>
                    </div>
                    <div className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-3 py-2">
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
                      disabled={mutationBusy || !selectedBranch}
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
                      disabled={mutationBusy || !branchDraft.trim()}
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
                      onClick={() => void runAction("fetch", () => client.fetchGitRemote(botAlias), { refreshWorkspace: true })}
                      disabled={mutationBusy}
                      className={buttonClass()}
                    >
                      <DownloadCloud className="h-3.5 w-3.5" />
                      Fetch
                    </button>
                    <button
                      type="button"
                      onClick={() => void runAction("pull", () => client.pullGitRemote(botAlias), { refreshWorkspace: true })}
                      disabled={mutationBusy}
                      className={buttonClass()}
                    >
                      <DownloadCloud className="h-3.5 w-3.5" />
                      Pull
                    </button>
                    <button
                      type="button"
                      onClick={() => void runAction("push", () => client.pushGitRemote(botAlias))}
                      disabled={mutationBusy}
                      className={buttonClass()}
                    >
                      <UploadCloud className="h-3.5 w-3.5" />
                      Push
                    </button>
                    <button
                      type="button"
                      onClick={() => void stashChanges()}
                      disabled={mutationBusy}
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
                                disabled={mutationBusy}
                                className={iconButtonClass()}
                              >
                                <ArchiveRestore className="h-3 w-3" />
                              </button>
                              <button
                                type="button"
                                aria-label={`删除 ${stash.ref}`}
                                title={`删除 ${stash.ref}`}
                                onClick={() => void dropStash(stash.ref)}
                                disabled={mutationBusy}
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
                      disabled={mutationBusy || overview.isClean}
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
                      disabled={isSmartCommitRunning}
                      placeholder="输入 commit message"
                      aria-label="commit message"
                      className="w-full resize-none rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                    />
                  </div>
                  {smartCommitJob ? (
                    <div className={sectionBodyClass("mx-3 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] text-xs")} data-testid="git-smart-commit-status">
                      <div className="font-medium text-[var(--text)]">{gitSmartCommitStatusText(smartCommitJob, overview)}</div>
                      {smartCommitJob.message && smartCommitJob.status !== "succeeded" ? (
                        <div className="whitespace-pre-wrap text-[var(--muted)]">{smartCommitJob.message}</div>
                      ) : null}
                      {smartCommitJob.error ? (
                        <div className="text-red-600">{smartCommitJob.error}</div>
                      ) : null}
                    </div>
                  ) : null}
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
                      disabled={mutationBusy || stageAllPaths.length === 0}
                      className={buttonClass()}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      暂存全部
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (!confirmDiscardAll(totalChanges)) {
                          return;
                        }
                        void runAction("discard-all", () => client.discardAllGitChanges(botAlias));
                      }}
                      disabled={mutationBusy || overview.isClean}
                      className={buttonClass()}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      丢弃全部
                    </button>
                    <button
                      type="button"
                      onClick={() => void runAction("commit", () => client.commitGitChanges(botAlias, commitMessage))}
                      disabled={mutationBusy || overview.isClean}
                      className={buttonClass("primary")}
                    >
                      <SendHorizontal className="h-3.5 w-3.5" />
                      {actionLoading === "commit" ? "提交中..." : "提交更改"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void startSmartCommit()}
                      disabled={mutationBusy || overview.isClean}
                      className={buttonClass()}
                    >
                      {isSmartCommitRunning ? (
                        <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="h-3.5 w-3.5" />
                      )}
                      智能提交
                    </button>
                  </div>
                </section>

                <section data-testid="git-version-tree-panel" className={sectionClass("space-y-2")}>
                  <div className={sectionHeaderClass("flex-wrap")}>
                    <div>
                      <h2 className="text-sm font-semibold">提交图</h2>
                      <p className="text-xs text-[var(--muted)]">
                        {graphPayload ? `${graphPayload.nodes.length} 个提交` : "未加载"}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <div className="inline-flex rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-0.5">
                        {([
                          ["all", "全部"],
                          ["current", "当前分支"],
                        ] as const).map(([scope, label]) => (
                          <button
                            key={scope}
                            type="button"
                            onClick={() => setGraphScope(scope)}
                            disabled={mutationBusy || graphLoading}
                            className={clsx(
                              "rounded px-2 py-1 text-xs transition-colors",
                              graphScope === scope
                                ? "bg-[var(--workbench-active-bg)] text-[var(--accent)]"
                                : "text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)]",
                            )}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={() => void loadGitGraph({ scope: graphScope })}
                        disabled={mutationBusy || graphLoading}
                        className={buttonClass()}
                      >
                        {graphLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                        刷新
                      </button>
                      <button
                        type="button"
                        aria-label={graphCollapsed ? "展开提交图" : "收起提交图"}
                        onClick={() => setGraphCollapsed((value) => !value)}
                        className={iconButtonClass()}
                      >
                        {graphCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  </div>
                  {!graphCollapsed ? (
                    <div data-testid="git-version-tree-content" className={sectionBodyClass("space-y-3")}>
                      {graphLoading && !graphPayload ? (
                        <div className={emptyStateClass()}>加载提交图...</div>
                      ) : null}
                      {graphPayload && graphPayload.nodes.length === 0 ? (
                        <div className={emptyStateClass()}>暂无提交</div>
                      ) : null}
                      {graphPayload && graphPayload.nodes.length > 0 ? (
                        <div className="space-y-2">
                          <div className="overflow-x-auto rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)]">
                            <div
                              data-testid="git-commit-graph"
                              aria-disabled={mutationBusy}
                              className={clsx("git-commit-graph min-w-0", mutationBusy ? "pointer-events-none opacity-70" : "")}
                            >
                              <GitCommitGraphLite
                                nodes={graphPayload.nodes}
                                selectedHash={selectedGraphHash}
                                disabled={mutationBusy}
                                onSelect={setSelectedGraphHash}
                              />
                            </div>
                          </div>
                        </div>
                      ) : null}
                      {selectedGraphNode ? (
                        <div data-testid="git-version-tree-actions" className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-2">
                          <div className="min-w-0 flex-1 text-xs">
                            <div className="font-mono font-semibold text-[var(--accent)]">{selectedGraphNode.shortHash}</div>
                            <div className="truncate text-[var(--muted)]">{selectedGraphNode.subject}</div>
                          </div>
                          <label className="min-w-[150px] flex-1 sm:flex-none">
                            <span className="sr-only">从提交图新建分支名</span>
                            <input
                              aria-label="从提交图新建分支名"
                              value={graphBranchDraft}
                              onChange={(event) => setGraphBranchDraft(event.target.value)}
                              placeholder="feature/name"
                              disabled={mutationBusy}
                              className="h-8 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 text-xs"
                            />
                          </label>
                          <button
                            type="button"
                            onClick={() => void createBranchFromGraphNode()}
                            disabled={mutationBusy || !graphBranchDraft.trim()}
                            className={buttonClass()}
                          >
                            {actionLoading === `branch-create:${selectedGraphNode.hash}` ? (
                              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <GitFork className="h-3.5 w-3.5" />
                            )}
                            新建分支
                          </button>
                          <label>
                            <span className="sr-only">提交图重置模式</span>
                            <select
                              aria-label="提交图重置模式"
                              value={graphResetMode}
                              onChange={(event) => setGraphResetMode(event.target.value as GitResetMode)}
                              disabled={mutationBusy}
                              className="h-8 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 text-xs"
                            >
                              <option value="soft">soft</option>
                              <option value="mixed">mixed</option>
                              <option value="hard">hard</option>
                            </select>
                          </label>
                          <button
                            type="button"
                            onClick={() => void resetBranchToGraphNode()}
                            disabled={mutationBusy || selectedGraphNode.canReset === false}
                            className={buttonClass()}
                          >
                            {actionLoading === `branch-reset:${selectedGraphNode.hash}` ? (
                              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <RotateCcw className="h-3.5 w-3.5" />
                            )}
                            重置到此提交
                          </button>
                        </div>
                      ) : null}
                      {graphPayload?.hasMore ? (
                        <button
                          type="button"
                          onClick={() => void loadGitGraph({ scope: graphScope, cursor: graphPayload.nextCursor, append: true })}
                          disabled={mutationBusy || graphLoading}
                          className={buttonClass()}
                        >
                          {graphLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <ChevronDown className="h-3.5 w-3.5" />}
                          加载更多
                        </button>
                      ) : null}
                    </div>
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
                    disabled={mutationBusy || identityLoading || !identityName.trim() || !identityEmail.trim()}
                    className={buttonClass("primary")}
                  >
                    <Save className="h-3.5 w-3.5" />
                    {actionLoading === "git-identity" ? "保存中..." : "保存 Git 用户"}
                  </button>
                </div>
              </section>

              <section className={sectionClass("space-y-3")}>
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
