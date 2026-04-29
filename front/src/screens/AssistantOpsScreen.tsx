import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Check, Database, Play, RefreshCw, Search, Shield, X } from "lucide-react";
import { AutomationTabs, type AutomationSubTab } from "./assistantOps/AutomationTabs";
import type {
  AssistantAdminAuditItem,
  AssistantDiagnosticsFilters,
  AssistantMemoryEvalCase,
  AssistantMemoryEvalReport,
  AssistantMemorySearchItem,
  AssistantPerfDiagnostics,
  AssistantPerfRecord,
  AssistantProposal,
  AssistantProposalDetail,
  AssistantUpgradeApplyLog,
  AssistantUpgradeDryRunResult,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
};

type AssistantOpsTab = "proposals" | "memory" | "diagnostics" | "audit" | AutomationSubTab;

const DEFAULT_MEMORY_EVAL_CASES = JSON.stringify(
  [
    {
      query: "默认简短中文",
      expectedMemoryKind: "semantic",
      expectedHitTerms: ["简短中文"],
      mustNotHitTerms: ["默认英文"],
    },
  ],
  null,
  2,
);

const MEMORY_KIND_OPTIONS = ["semantic", "episodic", "procedural"] as const;
const MEMORY_SCOPE_OPTIONS = ["user", "project", "global"] as const;
const EMPTY_DIAGNOSTICS: AssistantPerfDiagnostics = {
  items: [],
  summary: {
    total: 0,
    success: 0,
    failed: 0,
    avgElapsedMs: 0,
    p95ElapsedMs: 0,
    bySource: {},
    byStatus: {},
    slowStages: [],
    errorGroups: [],
  },
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function parseEvalCases(text: string): AssistantMemoryEvalCase[] {
  const payload = JSON.parse(text);
  const rows = Array.isArray(payload) ? payload : payload?.cases;
  if (!Array.isArray(rows)) {
    throw new Error("eval cases 需为数组或 { cases: [] }");
  }
  return rows.map((item) => ({
    query: String(item.query || "").trim(),
    expectedMemoryKind: String(item.expectedMemoryKind || item.expected_memory_kind || "").trim(),
    expectedHitTerms: Array.isArray(item.expectedHitTerms || item.expected_hit_terms)
      ? (item.expectedHitTerms || item.expected_hit_terms).map((value: unknown) => String(value))
      : [],
    mustNotHitTerms: Array.isArray(item.mustNotHitTerms || item.must_not_hit_terms)
      ? (item.mustNotHitTerms || item.must_not_hit_terms).map((value: unknown) => String(value))
      : [],
  })).filter((item) => item.query && item.expectedMemoryKind);
}

function stageText(record: AssistantPerfRecord) {
  const stages = record.stageDurations;
  return [
    `sync ${stages.syncMs}ms`,
    `index ${stages.indexMs}ms`,
    `recall ${stages.recallMs}ms`,
    `cli ${stages.cliMs}ms`,
    `db ${stages.dbMs}ms`,
    `trace ${stages.traceMs}ms`,
    `plugin ${stages.pluginMs}ms`,
  ].join(" · ");
}

function toggleValue(values: string[], value: string) {
  return values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];
}

function toNumberOrUndefined(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function AssistantOpsScreen({ botAlias, client }: Props) {
  const [tab, setTab] = useState<AssistantOpsTab>("proposals");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const [proposalStatus, setProposalStatus] = useState("all");
  const [proposals, setProposals] = useState<AssistantProposal[]>([]);
  const [proposalLoading, setProposalLoading] = useState(false);
  const [proposalActioning, setProposalActioning] = useState("");
  const [selectedProposalId, setSelectedProposalId] = useState("");
  const [proposalDetail, setProposalDetail] = useState<AssistantProposalDetail | null>(null);
  const [proposalDetailLoading, setProposalDetailLoading] = useState(false);
  const [proposalApplyLog, setProposalApplyLog] = useState<AssistantUpgradeApplyLog | null>(null);
  const [proposalApplyLogLoading, setProposalApplyLogLoading] = useState(false);
  const [proposalDryRunResult, setProposalDryRunResult] = useState<AssistantUpgradeDryRunResult | null>(null);
  const [proposalDryRunning, setProposalDryRunning] = useState(false);
  const [selectedProposalFilePath, setSelectedProposalFilePath] = useState("");

  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryUserId, setMemoryUserId] = useState("");
  const [memoryKinds, setMemoryKinds] = useState<string[]>([]);
  const [memoryScopes, setMemoryScopes] = useState<string[]>([]);
  const [memoryIncludeInvalidated, setMemoryIncludeInvalidated] = useState(false);
  const [memoryItems, setMemoryItems] = useState<AssistantMemorySearchItem[]>([]);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryActioningId, setMemoryActioningId] = useState("");
  const [memorySelectedIds, setMemorySelectedIds] = useState<string[]>([]);
  const [selectedMemoryId, setSelectedMemoryId] = useState("");
  const [memoryBulkInvalidating, setMemoryBulkInvalidating] = useState(false);
  const [memoryReindexing, setMemoryReindexing] = useState(false);
  const [memoryEvalCases, setMemoryEvalCases] = useState(DEFAULT_MEMORY_EVAL_CASES);
  const [memoryEvaluating, setMemoryEvaluating] = useState(false);
  const [memoryEvalReports, setMemoryEvalReports] = useState<AssistantMemoryEvalReport[]>([]);
  const [memoryReportsLoading, setMemoryReportsLoading] = useState(false);

  const [diagnostics, setDiagnostics] = useState<AssistantPerfDiagnostics>(EMPTY_DIAGNOSTICS);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [diagnosticsSource, setDiagnosticsSource] = useState("");
  const [diagnosticsStatus, setDiagnosticsStatus] = useState("");
  const [diagnosticsUserId, setDiagnosticsUserId] = useState("");
  const [diagnosticsLimit, setDiagnosticsLimit] = useState("20");

  const [auditItems, setAuditItems] = useState<AssistantAdminAuditItem[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditAction, setAuditAction] = useState("");
  const [auditResource, setAuditResource] = useState("");
  const [auditStatus, setAuditStatus] = useState<"ok" | "failed" | "">("");
  const [auditLimit, setAuditLimit] = useState("20");
  const [selectedAuditId, setSelectedAuditId] = useState("");

  const selectedMemory = useMemo(
    () => memoryItems.find((item) => item.id === selectedMemoryId) || null,
    [memoryItems, selectedMemoryId],
  );
  const selectedProposalFile = useMemo(
    () => proposalDetail?.diff.files.find((item) => item.path === selectedProposalFilePath)
      || proposalDetail?.diff.files[0]
      || null,
    [proposalDetail, selectedProposalFilePath],
  );
  const selectedAudit = useMemo(
    () => auditItems.find((item) => item.id === selectedAuditId) || null,
    [auditItems, selectedAuditId],
  );
  const diagnosticsMaxElapsed = useMemo(
    () => Math.max(...diagnostics.items.map((item) => item.elapsedMs), 1),
    [diagnostics.items],
  );

  const loadProposals = useCallback(async (status: string, preferredProposalId?: string) => {
    setProposalLoading(true);
    setError("");
    try {
      const items = await client.listAssistantProposals(botAlias, status === "all" ? undefined : status);
      setProposals(items);
      const nextId = preferredProposalId && items.some((item) => item.id === preferredProposalId)
        ? preferredProposalId
        : items[0]?.id || "";
      setSelectedProposalId(nextId);
    } catch (loadError) {
      setError(getErrorMessage(loadError, "加载 proposal 失败"));
      setProposals([]);
      setSelectedProposalId("");
    } finally {
      setProposalLoading(false);
    }
  }, [botAlias, client]);

  const loadProposalDetail = useCallback(async (proposalId: string, keepLog = false) => {
    if (!proposalId) {
      setProposalDetail(null);
      setProposalDryRunResult(null);
      setSelectedProposalFilePath("");
      if (!keepLog) {
        setProposalApplyLog(null);
      }
      return;
    }
    setProposalDetailLoading(true);
    setError("");
    try {
      const detail = await client.getAssistantProposal(botAlias, proposalId);
      setProposalDetail(detail);
      setProposalDryRunResult(null);
      setSelectedProposalFilePath(detail.diff.files[0]?.path || "");
      if (!keepLog) {
        setProposalApplyLog(null);
      }
    } catch (loadError) {
      setError(getErrorMessage(loadError, "加载 proposal 详情失败"));
      setProposalDetail(null);
      setProposalDryRunResult(null);
      setSelectedProposalFilePath("");
      if (!keepLog) {
        setProposalApplyLog(null);
      }
    } finally {
      setProposalDetailLoading(false);
    }
  }, [botAlias, client]);

  const loadProposalApplyLog = useCallback(async (proposalId: string) => {
    setProposalApplyLogLoading(true);
    setError("");
    try {
      const log = await client.getAssistantProposalApplyLog(botAlias, proposalId);
      setProposalApplyLog(log);
    } catch (loadError) {
      setError(getErrorMessage(loadError, "加载 apply 日志失败"));
      setProposalApplyLog(null);
    } finally {
      setProposalApplyLogLoading(false);
    }
  }, [botAlias, client]);

  const searchMemories = useCallback(async () => {
    setMemoryLoading(true);
    setError("");
    try {
      const userId = toNumberOrUndefined(memoryUserId);
      const result = await client.searchAssistantMemories(botAlias, memoryQuery, {
        limit: 12,
        ...(typeof userId === "number" ? { userId } : {}),
        ...(memoryKinds.length ? { kinds: memoryKinds } : {}),
        ...(memoryScopes.length ? { scopes: memoryScopes } : {}),
        ...(memoryIncludeInvalidated ? { includeInvalidated: true } : {}),
      });
      setMemoryItems(result.items);
      setSelectedMemoryId((current) => result.items.some((item) => item.id === current) ? current : (result.items[0]?.id || ""));
      setMemorySelectedIds((current) => current.filter((id) => result.items.some((item) => item.id === id)));
    } catch (loadError) {
      setError(getErrorMessage(loadError, "搜索 memory 失败"));
      setMemoryItems([]);
      setSelectedMemoryId("");
      setMemorySelectedIds([]);
    } finally {
      setMemoryLoading(false);
    }
  }, [botAlias, client, memoryIncludeInvalidated, memoryKinds, memoryQuery, memoryScopes, memoryUserId]);

  const loadMemoryReports = useCallback(async () => {
    setMemoryReportsLoading(true);
    setError("");
    try {
      const items = await client.listAssistantMemoryEvalReports(botAlias, 8);
      setMemoryEvalReports(items);
    } catch (loadError) {
      setError(getErrorMessage(loadError, "加载 eval 报告失败"));
      setMemoryEvalReports([]);
    } finally {
      setMemoryReportsLoading(false);
    }
  }, [botAlias, client]);

  const loadDiagnostics = useCallback(async () => {
    setDiagnosticsLoading(true);
    setError("");
    try {
      const filters: AssistantDiagnosticsFilters = {
        source: diagnosticsSource || undefined,
        status: diagnosticsStatus || undefined,
        userId: toNumberOrUndefined(diagnosticsUserId),
        limit: toNumberOrUndefined(diagnosticsLimit) || 20,
      };
      const result = await client.getAssistantDiagnostics(botAlias, filters);
      setDiagnostics(result);
    } catch (loadError) {
      setError(getErrorMessage(loadError, "加载诊断失败"));
      setDiagnostics(EMPTY_DIAGNOSTICS);
    } finally {
      setDiagnosticsLoading(false);
    }
  }, [botAlias, client, diagnosticsLimit, diagnosticsSource, diagnosticsStatus, diagnosticsUserId]);

  const loadAudit = useCallback(async () => {
    setAuditLoading(true);
    setError("");
    try {
      const result = await client.listAssistantAdminAudit(botAlias, {
        action: auditAction || undefined,
        resource: auditResource || undefined,
        status: auditStatus || undefined,
        limit: toNumberOrUndefined(auditLimit) || 20,
      });
      setAuditItems(result.items);
      setSelectedAuditId((current) => result.items.some((item) => item.id === current) ? current : (result.items[0]?.id || ""));
    } catch (loadError) {
      setError(getErrorMessage(loadError, "加载审计失败"));
      setAuditItems([]);
      setSelectedAuditId("");
    } finally {
      setAuditLoading(false);
    }
  }, [auditAction, auditLimit, auditResource, auditStatus, botAlias, client]);

  useEffect(() => {
    void loadProposals(proposalStatus);
  }, [loadProposals, proposalStatus]);

  useEffect(() => {
    void loadProposalDetail(selectedProposalId);
  }, [loadProposalDetail, selectedProposalId]);

  useEffect(() => {
    if (tab === "memory") {
      void loadMemoryReports();
    }
    if (tab === "diagnostics") {
      void loadDiagnostics();
    }
    if (tab === "audit") {
      void loadAudit();
    }
  }, [loadAudit, loadDiagnostics, loadMemoryReports, tab]);

  async function mutateProposal(action: "approve" | "reject" | "apply") {
    if (!selectedProposalId) {
      return;
    }
    setProposalActioning(action);
    setError("");
    try {
      if (action === "approve") {
        await client.approveAssistantProposal(botAlias, selectedProposalId);
        setProposalDryRunResult(null);
        setNotice("proposal 已批准");
      } else if (action === "reject") {
        await client.rejectAssistantProposal(botAlias, selectedProposalId);
        setProposalDryRunResult(null);
        setNotice("proposal 已拒绝");
      } else {
        await client.applyAssistantUpgrade(botAlias, selectedProposalId);
        setNotice("upgrade 已 apply");
      }
      await loadProposals(proposalStatus, selectedProposalId);
      await loadProposalDetail(selectedProposalId, true);
      if (action === "apply") {
        await loadProposalApplyLog(selectedProposalId);
      }
      if (tab === "audit") {
        await loadAudit();
      }
    } catch (actionError) {
      setError(getErrorMessage(actionError, "proposal 操作失败"));
      if (action === "apply") {
        await loadProposalApplyLog(selectedProposalId);
      }
    } finally {
      setProposalActioning("");
    }
  }

  async function dryRunProposal() {
    if (!selectedProposalId) {
      return;
    }
    setProposalDryRunning(true);
    setError("");
    try {
      const result = await client.dryRunAssistantUpgrade(botAlias, selectedProposalId);
      setProposalDryRunResult(result);
      setNotice(result.ok ? "dry-run 通过" : "dry-run 失败");
      if (tab === "audit") {
        await loadAudit();
      }
    } catch (actionError) {
      setError(getErrorMessage(actionError, "dry-run 失败"));
      setProposalDryRunResult(null);
    } finally {
      setProposalDryRunning(false);
    }
  }

  async function invalidateMemory(memoryId: string) {
    setMemoryActioningId(memoryId);
    setError("");
    try {
      await client.invalidateAssistantMemory(botAlias, memoryId, "web_admin");
      setNotice("memory 已失效");
      await searchMemories();
      if (tab === "audit") {
        await loadAudit();
      }
    } catch (actionError) {
      setError(getErrorMessage(actionError, "memory 失效失败"));
    } finally {
      setMemoryActioningId("");
    }
  }

  async function bulkInvalidateMemory() {
    if (memorySelectedIds.length === 0) {
      return;
    }
    setMemoryBulkInvalidating(true);
    setError("");
    try {
      const result = await client.bulkInvalidateAssistantMemories(botAlias, memorySelectedIds, "web_admin_bulk");
      setNotice(`已失效 ${result.invalidated} 条`);
      setMemorySelectedIds([]);
      await searchMemories();
      if (tab === "audit") {
        await loadAudit();
      }
    } catch (actionError) {
      setError(getErrorMessage(actionError, "批量失效失败"));
    } finally {
      setMemoryBulkInvalidating(false);
    }
  }

  async function reindexMemory() {
    setMemoryReindexing(true);
    setError("");
    try {
      const userId = toNumberOrUndefined(memoryUserId);
      const result = await client.reindexAssistantMemory(botAlias, {
        force: true,
        ...(typeof userId === "number" ? { userId } : {}),
      });
      setNotice(`已重建索引：working ${result.working.indexedCount}，knowledge ${result.knowledge.indexedCount}`);
      await searchMemories();
      await loadDiagnostics();
      if (tab === "audit") {
        await loadAudit();
      }
    } catch (actionError) {
      setError(getErrorMessage(actionError, "重建索引失败"));
    } finally {
      setMemoryReindexing(false);
    }
  }

  async function runMemoryEval() {
    setMemoryEvaluating(true);
    setError("");
    try {
      const cases = parseEvalCases(memoryEvalCases);
      const userId = toNumberOrUndefined(memoryUserId);
      if (cases.length === 0) {
        throw new Error("至少提供 1 个 case");
      }
      const result = await client.runAssistantMemoryEval(botAlias, {
        cases,
        ...(typeof userId === "number" ? { userId } : {}),
      });
      setNotice(`eval 完成：hit@5=${result.metrics.hitAt5.toFixed(2)}`);
      await loadMemoryReports();
      await loadDiagnostics();
      if (tab === "audit") {
        await loadAudit();
      }
    } catch (actionError) {
      setError(getErrorMessage(actionError, "运行 eval 失败"));
    } finally {
      setMemoryEvaluating(false);
    }
  }

  const canApplyProposal = Boolean(
    proposalDetail
    && proposalDetail.proposal.status === "approved"
    && proposalDetail.apply.available
    && proposalDryRunResult?.ok,
  );

  return (
    <section
      data-testid="assistant-ops-screen"
      className="h-full min-h-0 space-y-4 overflow-y-auto bg-[var(--surface)] p-4"
      aria-labelledby="assistant-ops-title"
    >
      <div className="space-y-1">
        <h3 id="assistant-ops-title" className="font-medium text-[var(--text)]">Assistant 运维台</h3>
        <p className="text-xs text-[var(--muted)]">proposal、memory、诊断和审计。</p>
      </div>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Assistant 运维页签">
        {[
          { id: "proposals", label: "Proposal" },
          { id: "memory", label: "Memory / Knowledge" },
          { id: "diagnostics", label: "Diagnostics" },
          { id: "queue", label: "Queue" },
          { id: "cron", label: "Cron" },
          { id: "runs", label: "Runs" },
          { id: "audit", label: "Audit" },
        ].map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id as AssistantOpsTab)}
            className={`rounded-lg px-3 py-2 text-sm ${
              tab === item.id
                ? "bg-[var(--accent)] text-white"
                : "border border-[var(--border)] text-[var(--text)] hover:bg-[var(--surface-strong)]"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {notice ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          {notice}
        </div>
      ) : null}
      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {tab === "proposals" ? (
        <div className="space-y-4" role="tabpanel" aria-label="Proposal">
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="proposal 状态"
              value={proposalStatus}
              onChange={(event) => setProposalStatus(event.target.value)}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            >
              <option value="all">全部</option>
              <option value="proposed">proposed</option>
              <option value="approved">approved</option>
              <option value="rejected">rejected</option>
              <option value="applied">applied</option>
            </select>
            <button
              type="button"
              onClick={() => void loadProposals(proposalStatus, selectedProposalId)}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)]"
            >
              <RefreshCw className="h-4 w-4" />
              刷新
            </button>
          </div>

          {proposalLoading ? (
            <p className="text-sm text-[var(--muted)]">加载 proposal...</p>
          ) : proposals.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
              暂无 proposal
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
              <div className="space-y-2">
                {proposals.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedProposalId(item.id)}
                    className={`block w-full rounded-lg border px-3 py-3 text-left ${
                      item.id === selectedProposalId
                        ? "border-[var(--accent)] bg-[var(--surface-strong)]"
                        : "border-[var(--border)] bg-[var(--bg)] hover:bg-[var(--surface-strong)]"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="text-sm font-medium text-[var(--text)]">{item.title}</div>
                        <div className="text-xs text-[var(--muted)]">{item.id}</div>
                      </div>
                      <span className="text-xs text-[var(--muted)]">{item.status}</span>
                    </div>
                  </button>
                ))}
              </div>

              <div className="space-y-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
                {proposalDetailLoading ? (
                  <p className="text-sm text-[var(--muted)]">加载详情...</p>
                ) : proposalDetail ? (
                  <>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="space-y-1">
                        <h4 className="text-sm font-medium text-[var(--text)]">{proposalDetail.proposal.title}</h4>
                        <p className="text-xs text-[var(--muted)]">
                          {proposalDetail.proposal.kind} · {proposalDetail.proposal.status} · {proposalDetail.proposal.createdAt || "-"}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => void mutateProposal("approve")}
                          disabled={proposalActioning !== "" || proposalDetail.proposal.status === "approved" || proposalDetail.proposal.status === "applied"}
                          className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 px-3 py-2 text-sm text-emerald-700 hover:bg-emerald-50 disabled:opacity-60"
                        >
                          <Check className="h-4 w-4" />
                          批准
                        </button>
                        <button
                          type="button"
                          onClick={() => void mutateProposal("reject")}
                          disabled={proposalActioning !== "" || proposalDetail.proposal.status === "rejected" || proposalDetail.proposal.status === "applied"}
                          className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                        >
                          <X className="h-4 w-4" />
                          拒绝
                        </button>
                        <button
                          type="button"
                          onClick={() => void dryRunProposal()}
                          disabled={proposalDryRunning || proposalActioning !== "" || proposalDetail.proposal.status !== "approved"}
                          className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
                        >
                          {proposalDryRunning ? "Dry-run 中..." : "Dry-run"}
                        </button>
                        <button
                          type="button"
                          onClick={() => void mutateProposal("apply")}
                          disabled={proposalActioning !== "" || !canApplyProposal}
                          className="inline-flex items-center gap-1 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
                        >
                          <Play className="h-4 w-4" />
                          Apply
                        </button>
                      </div>
                    </div>

                    <div className="space-y-2 text-sm text-[var(--text)]">
                      <div className="font-medium">正文</div>
                      <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text)]">
                        {proposalDetail.proposal.body || "-"}
                      </pre>
                    </div>

                    <div className="space-y-2 text-sm text-[var(--text)]">
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-medium">Diff</div>
                        <div className="text-xs text-[var(--muted)]">
                          {proposalDetail.diff.available ? proposalDetail.diff.source : "无 patch"}
                        </div>
                      </div>
                      {proposalDetail.diff.files.length > 0 ? (
                        <div className="grid gap-3 lg:grid-cols-[240px_minmax(0,1fr)]">
                          <div className="space-y-2">
                            {proposalDetail.diff.files.map((file) => (
                              <button
                                key={file.path}
                                type="button"
                                onClick={() => setSelectedProposalFilePath(file.path)}
                                className={`block w-full rounded-lg border px-3 py-2 text-left ${
                                  selectedProposalFile?.path === file.path
                                    ? "border-[var(--accent)] bg-[var(--surface-strong)]"
                                    : "border-[var(--border)] hover:bg-[var(--surface-strong)]"
                                }`}
                              >
                                <div className="text-sm text-[var(--text)]">{file.path}</div>
                                <div className="text-xs text-[var(--muted)]">
                                  {file.status} · +{file.additions} / -{file.deletions}
                                </div>
                              </button>
                            ))}
                          </div>
                          <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text)]">
                            {selectedProposalFile?.text || proposalDetail.diff.text || "暂无 diff"}
                          </pre>
                        </div>
                      ) : (
                        <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text)]">
                          {proposalDetail.diff.text || "暂无 diff"}
                        </pre>
                      )}
                    </div>

                    <div className="space-y-2 text-sm text-[var(--text)]">
                      <div className="font-medium">Dry-run</div>
                      <div className="grid gap-2 text-xs text-[var(--muted)] sm:grid-cols-2">
                        <p><span className="text-[var(--text)]">状态:</span> {proposalDryRunResult ? (proposalDryRunResult.ok ? "ok" : "failed") : "未执行"}</p>
                        <p><span className="text-[var(--text)]">时间:</span> {proposalDryRunResult?.checkedAt || "-"}</p>
                        <p><span className="text-[var(--text)]">repo:</span> {proposalDryRunResult?.repoRoot || "-"}</p>
                        <p><span className="text-[var(--text)]">patch:</span> {proposalDryRunResult?.patchPath || "-"}</p>
                      </div>
                      {proposalDryRunResult?.stdout ? (
                        <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text)]">
                          {proposalDryRunResult.stdout}
                        </pre>
                      ) : null}
                      {proposalDryRunResult?.stderr ? (
                        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                          {proposalDryRunResult.stderr}
                        </div>
                      ) : null}
                    </div>

                    <div className="space-y-2 text-sm text-[var(--text)]">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="font-medium">Apply 状态</div>
                        <button
                          type="button"
                          onClick={() => void loadProposalApplyLog(proposalDetail.proposal.id)}
                          disabled={proposalApplyLogLoading}
                          className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                        >
                          {proposalApplyLogLoading ? "加载中..." : "查看日志"}
                        </button>
                      </div>
                      <div className="grid gap-2 text-xs text-[var(--muted)] sm:grid-cols-2">
                        <p><span className="text-[var(--text)]">可 apply:</span> {proposalDetail.apply.available ? "是" : "否"}</p>
                        <p><span className="text-[var(--text)]">已 apply:</span> {proposalDetail.apply.applied ? "是" : "否"}</p>
                        <p><span className="text-[var(--text)]">最近错误:</span> {proposalDetail.apply.lastErrorAt || "-"}</p>
                        <p><span className="text-[var(--text)]">错误日志:</span> {proposalDetail.apply.lastErrorLogPath || "-"}</p>
                      </div>
                      {proposalApplyLog ? (
                        <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text)]">
                          {JSON.stringify(proposalApplyLog, null, 2)}
                        </pre>
                      ) : proposalDetail.apply.lastError ? (
                        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                          {proposalDetail.apply.lastError}
                        </div>
                      ) : null}
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-[var(--muted)]">选择个 proposal 查看详情</p>
                )}
              </div>
            </div>
          )}
        </div>
      ) : null}

      {tab === "memory" ? (
        <div className="space-y-4" role="tabpanel" aria-label="Memory / Knowledge">
          <div className="flex flex-wrap gap-2">
            <label className="flex-1 min-w-[220px]">
              <span className="sr-only">memory 查询</span>
              <input
                aria-label="memory 查询"
                type="text"
                value={memoryQuery}
                onChange={(event) => setMemoryQuery(event.target.value)}
                placeholder="搜索 memory / knowledge"
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
              />
            </label>
            <input
              aria-label="memory user id"
              type="text"
              value={memoryUserId}
              onChange={(event) => setMemoryUserId(event.target.value)}
              placeholder="user id"
              className="w-32 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            />
            <button
              type="button"
              onClick={() => void searchMemories()}
              disabled={memoryLoading}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              <Search className="h-4 w-4" />
              {memoryLoading ? "搜索中..." : "搜索"}
            </button>
            <button
              type="button"
              onClick={() => void bulkInvalidateMemory()}
              disabled={memoryBulkInvalidating || memorySelectedIds.length === 0}
              className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
            >
              {memoryBulkInvalidating ? "处理中..." : "批量 Invalidate"}
            </button>
            <button
              type="button"
              onClick={() => void reindexMemory()}
              disabled={memoryReindexing}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
            >
              <Database className="h-4 w-4" />
              {memoryReindexing ? "重建中..." : "Re-index"}
            </button>
          </div>

          <div className="flex flex-wrap gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 text-sm text-[var(--text)]">
            <div className="flex flex-wrap gap-2">
              {MEMORY_KIND_OPTIONS.map((kind) => (
                <label key={kind} className="inline-flex items-center gap-2">
                  <input
                    aria-label={`memory kind ${kind}`}
                    type="checkbox"
                    checked={memoryKinds.includes(kind)}
                    onChange={() => setMemoryKinds((current) => toggleValue(current, kind))}
                  />
                  {kind}
                </label>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {MEMORY_SCOPE_OPTIONS.map((scope) => (
                <label key={scope} className="inline-flex items-center gap-2">
                  <input
                    aria-label={`memory scope ${scope}`}
                    type="checkbox"
                    checked={memoryScopes.includes(scope)}
                    onChange={() => setMemoryScopes((current) => toggleValue(current, scope))}
                  />
                  {scope}
                </label>
              ))}
            </div>
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={memoryIncludeInvalidated}
                onChange={(event) => setMemoryIncludeInvalidated(event.target.checked)}
              />
              包含失效 memory
            </label>
          </div>

          {memoryItems.length ? (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="space-y-2">
                {memoryItems.map((item) => (
                  <article
                    key={item.id}
                    className={`rounded-lg border p-3 space-y-2 ${
                      item.id === selectedMemoryId
                        ? "border-[var(--accent)] bg-[var(--surface-strong)]"
                        : "border-[var(--border)] bg-[var(--bg)]"
                    }`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex min-w-0 items-start gap-3">
                        <input
                          aria-label={`选择 memory ${item.title}`}
                          type="checkbox"
                          checked={memorySelectedIds.includes(item.id)}
                          onChange={() => setMemorySelectedIds((current) => toggleValue(current, item.id))}
                          className="mt-1"
                        />
                        <button
                          type="button"
                          onClick={() => setSelectedMemoryId(item.id)}
                          className="min-w-0 text-left"
                        >
                          <div className="text-sm font-medium text-[var(--text)]">{item.title}</div>
                          <div className="text-xs text-[var(--muted)]">
                            {item.kind}/{item.scope} · score {item.score.toFixed(2)} · {item.sourceType || "-"}
                          </div>
                        </button>
                      </div>
                      <div className="flex items-center gap-2">
                        {item.invalidatedAt ? (
                          <span className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700">
                            已失效
                          </span>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => void invalidateMemory(item.id)}
                          disabled={memoryActioningId === item.id || Boolean(item.invalidatedAt)}
                          className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                        >
                          {memoryActioningId === item.id ? "处理中..." : "Invalidate"}
                        </button>
                      </div>
                    </div>
                    <p className="text-sm text-[var(--text)]">{item.summary}</p>
                  </article>
                ))}
              </div>

              <aside className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
                <h4 className="text-sm font-medium text-[var(--text)]">Memory 详情</h4>
                {selectedMemory ? (
                  <>
                    <div className="space-y-1">
                      <div className="text-sm text-[var(--text)]">{selectedMemory.title}</div>
                      <div className="text-xs text-[var(--muted)]">
                        {selectedMemory.kind}/{selectedMemory.scope} · {selectedMemory.updatedAt || "-"}
                      </div>
                    </div>
                    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--muted)]">
                      召回解释：score {selectedMemory.score.toFixed(2)} · {selectedMemory.sourceType || "-"} / {selectedMemory.sourceRef || "-"}
                    </div>
                    <div className="text-sm text-[var(--text)]">{selectedMemory.summary}</div>
                    <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text)]">
                      {selectedMemory.body}
                    </pre>
                    <div className="text-xs text-[var(--muted)]">
                      失效时间：{selectedMemory.invalidatedAt || "-"}
                    </div>
                  </>
                ) : (
                  <div className="text-sm text-[var(--muted)]">选择个 memory</div>
                )}
              </aside>
            </div>
          ) : memoryLoading ? null : (
            <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
              暂无搜索结果
            </div>
          )}

          <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="space-y-1">
                <h4 className="text-sm font-medium text-[var(--text)]">Eval</h4>
                <p className="text-xs text-[var(--muted)]">看召回是否命中预期。</p>
              </div>
              <button
                type="button"
                onClick={() => void runMemoryEval()}
                disabled={memoryEvaluating}
                className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
              >
                <Play className="h-4 w-4" />
                {memoryEvaluating ? "运行中..." : "运行 Eval"}
              </button>
            </div>
            <textarea
              aria-label="eval cases"
              rows={8}
              value={memoryEvalCases}
              onChange={(event) => setMemoryEvalCases(event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--text)]"
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-sm font-medium text-[var(--text)]">Eval 报告</h4>
              <button
                type="button"
                onClick={() => void loadMemoryReports()}
                disabled={memoryReportsLoading}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                {memoryReportsLoading ? "加载中..." : "刷新"}
              </button>
            </div>
            {memoryEvalReports.length === 0 ? (
              <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
                暂无 eval 报告
              </div>
            ) : (
              memoryEvalReports.map((report) => (
                <article key={report.reportPath} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="text-sm font-medium text-[var(--text)]">{report.reportPath}</div>
                    <div className="text-xs text-[var(--muted)]">
                      hit@5 {report.metrics.hitAt5.toFixed(2)} · stale {report.metrics.staleRecallRate.toFixed(2)}
                    </div>
                  </div>
                  <div className="text-xs text-[var(--muted)]">{report.createdAt || "-"}</div>
                  {report.rows.map((row) => (
                    <div key={`${report.reportPath}-${row.query}`} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text)] space-y-1">
                      <div>{row.query}</div>
                      <div className="text-[var(--muted)]">
                        {row.hit ? "hit" : "miss"} · {row.stale ? "stale" : "fresh"}
                      </div>
                      <pre className="whitespace-pre-wrap">{row.promptBlock}</pre>
                    </div>
                  ))}
                </article>
              ))
            )}
          </div>
        </div>
      ) : null}

      {tab === "diagnostics" ? (
        <div className="space-y-4" role="tabpanel" aria-label="Diagnostics">
          <div className="flex flex-wrap gap-2">
            <select
              aria-label="diagnostics source"
              value={diagnosticsSource}
              onChange={(event) => setDiagnosticsSource(event.target.value)}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            >
              <option value="">全部 source</option>
              <option value="web">web</option>
              <option value="cron">cron</option>
            </select>
            <select
              aria-label="diagnostics status"
              value={diagnosticsStatus}
              onChange={(event) => setDiagnosticsStatus(event.target.value)}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            >
              <option value="">全部 status</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
            </select>
            <input
              aria-label="diagnostics user id"
              type="text"
              value={diagnosticsUserId}
              onChange={(event) => setDiagnosticsUserId(event.target.value)}
              placeholder="user id"
              className="w-32 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            />
            <input
              aria-label="diagnostics limit"
              type="text"
              value={diagnosticsLimit}
              onChange={(event) => setDiagnosticsLimit(event.target.value)}
              className="w-24 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            />
            <button
              type="button"
              onClick={() => void loadDiagnostics()}
              disabled={diagnosticsLoading}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              <Activity className="h-4 w-4" />
              {diagnosticsLoading ? "加载中..." : "刷新诊断"}
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { label: "总数", value: diagnostics.summary.total },
              { label: "失败", value: diagnostics.summary.failed },
              { label: "平均", value: `${diagnostics.summary.avgElapsedMs}ms` },
              { label: "P95", value: `${diagnostics.summary.p95ElapsedMs}ms` },
            ].map((item) => (
              <div key={item.label} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
                <div className="text-xs text-[var(--muted)]">{item.label}</div>
                <div className="mt-1 text-lg font-medium text-[var(--text)]">{item.value}</div>
              </div>
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
            <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
              <h4 className="text-sm font-medium text-[var(--text)]">趋势</h4>
              {diagnostics.items.length === 0 ? (
                <div className="text-sm text-[var(--muted)]">暂无诊断记录</div>
              ) : (
                diagnostics.items.map((item) => (
                  <div key={item.runId} className="space-y-1">
                    <div className="flex items-center justify-between gap-2 text-xs text-[var(--muted)]">
                      <span>{item.runId}</span>
                      <span>{item.elapsedMs}ms</span>
                    </div>
                    <div className="h-2 rounded-full bg-[var(--surface)]">
                      <div
                        className={`h-2 rounded-full ${item.status === "failed" ? "bg-red-500" : "bg-emerald-500"}`}
                        style={{ width: `${Math.max(8, Math.round(item.elapsedMs / diagnosticsMaxElapsed * 100))}%` }}
                      />
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="space-y-4">
              <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
                <h4 className="text-sm font-medium text-[var(--text)]">慢阶段排行</h4>
                <div className="mt-3 space-y-2">
                  {diagnostics.summary.slowStages.length === 0 ? (
                    <div className="text-sm text-[var(--muted)]">暂无</div>
                  ) : (
                    diagnostics.summary.slowStages.map((item) => (
                      <div key={item.stage} className="flex items-center justify-between gap-2 text-sm">
                        <span className="text-[var(--text)]">{item.stage}</span>
                        <span className="text-[var(--muted)]">{item.totalMs}ms / avg {item.avgMs}ms</span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
                <h4 className="text-sm font-medium text-[var(--text)]">错误聚合</h4>
                <div className="mt-3 space-y-2">
                  {diagnostics.summary.errorGroups.length === 0 ? (
                    <div className="text-sm text-[var(--muted)]">暂无</div>
                  ) : (
                    diagnostics.summary.errorGroups.map((item) => (
                      <div key={`${item.message}-${item.latestAt}`} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2">
                        <div className="text-sm text-[var(--text)]">{item.message}</div>
                        <div className="text-xs text-[var(--muted)]">{item.count} 次 · {item.latestAt}</div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <h4 className="text-sm font-medium text-[var(--text)]">最近性能记录</h4>
            {diagnostics.items.length === 0 ? (
              <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
                暂无诊断记录
              </div>
            ) : (
              diagnostics.items.map((item) => (
                <article key={item.runId} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="text-sm font-medium text-[var(--text)]">{item.runId}</div>
                      <div className="text-xs text-[var(--muted)]">
                        {item.source} · {item.taskMode} · {item.status} · user {item.userId}
                      </div>
                    </div>
                    <div className="text-xs text-[var(--muted)]">
                      elapsed {item.elapsedMs}ms · trace {item.traceCount} · tool {item.toolCallCount}
                    </div>
                  </div>
                  <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--text)]">
                    {stageText(item)}
                  </div>
                  {item.error ? (
                    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                      {item.error}
                    </div>
                  ) : null}
                </article>
              ))
            )}
          </div>
        </div>
      ) : null}

      {tab === "queue" || tab === "cron" || tab === "runs" ? (
        <AutomationTabs
          botAlias={botAlias}
          client={client}
          activeTab={tab as AutomationSubTab}
          onNotice={setNotice}
          onError={setError}
        />
      ) : null}

      {tab === "audit" ? (
        <div className="space-y-4" role="tabpanel" aria-label="Audit">
          <div className="flex flex-wrap gap-2">
            <input
              aria-label="audit action"
              type="text"
              value={auditAction}
              onChange={(event) => setAuditAction(event.target.value)}
              placeholder="action"
              className="min-w-[180px] rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            />
            <input
              aria-label="audit resource"
              type="text"
              value={auditResource}
              onChange={(event) => setAuditResource(event.target.value)}
              placeholder="resource"
              className="min-w-[140px] rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            />
            <select
              aria-label="audit status"
              value={auditStatus}
              onChange={(event) => setAuditStatus(event.target.value as "ok" | "failed" | "")}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            >
              <option value="">全部 status</option>
              <option value="ok">ok</option>
              <option value="failed">failed</option>
            </select>
            <input
              aria-label="audit limit"
              type="text"
              value={auditLimit}
              onChange={(event) => setAuditLimit(event.target.value)}
              className="w-24 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            />
            <button
              type="button"
              onClick={() => void loadAudit()}
              disabled={auditLoading}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              <Shield className="h-4 w-4" />
              {auditLoading ? "加载中..." : "刷新审计"}
            </button>
          </div>

          {auditItems.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
              暂无审计记录
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
              <div className="space-y-2">
                {auditItems.map((item) => (
                  <article key={item.id} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="space-y-1">
                        <div className="text-sm text-[var(--text)]">{item.action}</div>
                        <div className="text-xs text-[var(--muted)]">
                          {item.target.resource || "-"} · {item.target.resourceId || "-"} · {item.createdAt}
                        </div>
                      </div>
                      <span className={`rounded border px-2 py-1 text-xs ${item.ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}`}>
                        {item.ok ? "ok" : "failed"}
                      </span>
                    </div>
                    <div className="text-xs text-[var(--muted)]">
                      {item.username} · {item.method} · {item.statusCode}
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedAuditId(item.id)}
                      className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
                    >
                      查看审计详情
                    </button>
                  </article>
                ))}
              </div>

              <aside className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
                <h4 className="text-sm font-medium text-[var(--text)]">审计详情</h4>
                {selectedAudit ? (
                  <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text)]">
                    {JSON.stringify(selectedAudit, null, 2)}
                  </pre>
                ) : (
                  <div className="text-sm text-[var(--muted)]">选择条记录</div>
                )}
              </aside>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
