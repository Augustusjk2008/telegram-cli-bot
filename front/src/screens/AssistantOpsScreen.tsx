import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Check, Database, Play, RefreshCw, Search, X } from "lucide-react";
import type {
  AssistantMemoryEvalCase,
  AssistantMemoryEvalReport,
  AssistantMemorySearchItem,
  AssistantPerfRecord,
  AssistantProposal,
  AssistantProposalDetail,
  AssistantUpgradeApplyLog,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
};

type AssistantOpsTab = "proposals" | "memory" | "diagnostics";

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

  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryItems, setMemoryItems] = useState<AssistantMemorySearchItem[]>([]);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryActioningId, setMemoryActioningId] = useState("");
  const [memoryReindexing, setMemoryReindexing] = useState(false);
  const [memoryEvalCases, setMemoryEvalCases] = useState(DEFAULT_MEMORY_EVAL_CASES);
  const [memoryEvaluating, setMemoryEvaluating] = useState(false);
  const [memoryEvalReports, setMemoryEvalReports] = useState<AssistantMemoryEvalReport[]>([]);
  const [memoryReportsLoading, setMemoryReportsLoading] = useState(false);

  const [diagnostics, setDiagnostics] = useState<AssistantPerfRecord[]>([]);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);

  const selectedProposal = useMemo(
    () => proposals.find((item) => item.id === selectedProposalId) || null,
    [proposals, selectedProposalId],
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
      if (!keepLog) {
        setProposalApplyLog(null);
      }
    } catch (loadError) {
      setError(getErrorMessage(loadError, "加载 proposal 详情失败"));
      setProposalDetail(null);
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
      const result = await client.searchAssistantMemories(botAlias, memoryQuery, { userId: 1001, limit: 12 });
      setMemoryItems(result.items);
    } catch (loadError) {
      setError(getErrorMessage(loadError, "搜索 memory 失败"));
      setMemoryItems([]);
    } finally {
      setMemoryLoading(false);
    }
  }, [botAlias, client, memoryQuery]);

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
      const result = await client.getAssistantDiagnostics(botAlias, 20);
      setDiagnostics(result.items);
    } catch (loadError) {
      setError(getErrorMessage(loadError, "加载诊断失败"));
      setDiagnostics([]);
    } finally {
      setDiagnosticsLoading(false);
    }
  }, [botAlias, client]);

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
  }, [loadDiagnostics, loadMemoryReports, tab]);

  async function mutateProposal(action: "approve" | "reject" | "apply") {
    if (!selectedProposalId) {
      return;
    }
    setProposalActioning(action);
    setError("");
    try {
      if (action === "approve") {
        await client.approveAssistantProposal(botAlias, selectedProposalId);
        setNotice("proposal 已批准");
      } else if (action === "reject") {
        await client.rejectAssistantProposal(botAlias, selectedProposalId);
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
    } catch (actionError) {
      setError(getErrorMessage(actionError, "proposal 操作失败"));
      if (action === "apply") {
        await loadProposalApplyLog(selectedProposalId);
        await loadProposalDetail(selectedProposalId, true);
      }
    } finally {
      setProposalActioning("");
    }
  }

  async function invalidateMemory(memoryId: string) {
    setMemoryActioningId(memoryId);
    setError("");
    try {
      await client.invalidateAssistantMemory(botAlias, memoryId, "web_admin");
      setNotice("memory 已失效");
      await searchMemories();
    } catch (actionError) {
      setError(getErrorMessage(actionError, "memory 失效失败"));
    } finally {
      setMemoryActioningId("");
    }
  }

  async function reindexMemory() {
    setMemoryReindexing(true);
    setError("");
    try {
      const result = await client.reindexAssistantMemory(botAlias, { userId: 1001, force: true });
      setNotice(`已重建索引：working ${result.working.indexedCount}，knowledge ${result.knowledge.indexedCount}`);
      await searchMemories();
      await loadDiagnostics();
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
      if (cases.length === 0) {
        throw new Error("至少提供 1 个 case");
      }
      const result = await client.runAssistantMemoryEval(botAlias, { userId: 1001, cases });
      setNotice(`eval 完成：hit@5=${result.metrics.hitAt5.toFixed(2)}`);
      await loadMemoryReports();
      await loadDiagnostics();
    } catch (actionError) {
      setError(getErrorMessage(actionError, "运行 eval 失败"));
    } finally {
      setMemoryEvaluating(false);
    }
  }

  return (
    <section className="space-y-4 border-t border-[var(--border)] pt-4" aria-labelledby="assistant-ops-title">
      <div className="space-y-1">
        <h3 id="assistant-ops-title" className="font-medium text-[var(--text)]">Assistant 运维台</h3>
        <p className="text-xs text-[var(--muted)]">proposal 审批、memory/knowledge 管理和性能诊断。</p>
      </div>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Assistant 运维页签">
        {[
          { id: "proposals", label: "Proposal" },
          { id: "memory", label: "Memory / Knowledge" },
          { id: "diagnostics", label: "Diagnostics" },
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

              <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
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
                          onClick={() => void mutateProposal("apply")}
                          disabled={proposalActioning !== "" || proposalDetail.proposal.status !== "approved"}
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
                      <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text)]">
                        {proposalDetail.diff.text || "暂无 diff"}
                      </pre>
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
              onClick={() => void reindexMemory()}
              disabled={memoryReindexing}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
            >
              <Database className="h-4 w-4" />
              {memoryReindexing ? "重建中..." : "Re-index"}
            </button>
          </div>

          {memoryItems.length ? (
            <div className="space-y-2">
              {memoryItems.map((item) => (
                <article key={item.id} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="text-sm font-medium text-[var(--text)]">{item.title}</div>
                      <div className="text-xs text-[var(--muted)]">
                        {item.kind}/{item.scope} · score {item.score.toFixed(2)} · {item.sourceType || "-"}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void invalidateMemory(item.id)}
                      disabled={memoryActioningId === item.id}
                      className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                    >
                      {memoryActioningId === item.id ? "处理中..." : "Invalidate"}
                    </button>
                  </div>
                  <p className="text-sm text-[var(--text)]">{item.summary}</p>
                  <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text)]">
                    {item.body}
                  </pre>
                </article>
              ))}
            </div>
          ) : memoryLoading ? null : (
            <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
              暂无搜索结果
            </div>
          )}

          <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-sm font-medium text-[var(--text)]">Eval</h4>
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
        <div className="space-y-3" role="tabpanel" aria-label="Diagnostics">
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-sm font-medium text-[var(--text)]">最近性能记录</h4>
            <button
              type="button"
              onClick={() => void loadDiagnostics()}
              disabled={diagnosticsLoading}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              <Activity className="h-4 w-4" />
              {diagnosticsLoading ? "加载中..." : "刷新"}
            </button>
          </div>
          {diagnostics.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
              暂无诊断记录
            </div>
          ) : (
            diagnostics.map((item) => (
              <article key={item.runId} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-1">
                    <div className="text-sm font-medium text-[var(--text)]">{item.runId}</div>
                    <div className="text-xs text-[var(--muted)]">
                      {item.source} · {item.taskMode} · {item.status} · {item.createdAt}
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
      ) : null}
    </section>
  );
}
