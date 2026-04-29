import { useEffect, useMemo, useState } from "react";
import { Play, RefreshCw, Save } from "lucide-react";
import type {
  AssistantCronJob,
  AssistantCronRun,
  AssistantRuntimeSnapshot,
} from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { dispatchAssistantCronRunEnqueued } from "../../utils/assistantCronEvents";

export type AutomationSubTab = "queue" | "cron" | "runs";

type Props = {
  botAlias: string;
  client: WebBotClient;
  activeTab: AutomationSubTab;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function summarizePrompt(prompt: string) {
  const text = String(prompt || "").trim();
  return text.length > 120 ? `${text.slice(0, 120).trim()}...` : text;
}

function cronScheduleText(job: AssistantCronJob) {
  if (job.schedule.type === "interval") {
    return `每 ${job.schedule.everySeconds || 0} 秒`;
  }
  return `${job.schedule.time || "00:00"} ${job.schedule.timezone || "Asia/Shanghai"}`;
}

function cronStatusText(job: AssistantCronJob) {
  if (job.pending) {
    return `pending ${job.pendingRunId || ""}`.trim();
  }
  if (job.lastStatus) {
    return job.lastError ? `${job.lastStatus}: ${job.lastError}` : job.lastStatus;
  }
  return job.enabled ? "enabled" : "disabled";
}

export function AutomationTabs({ botAlias, client, activeTab, onNotice, onError }: Props) {
  const [jobs, setJobs] = useState<AssistantCronJob[]>([]);
  const [runsByJobId, setRunsByJobId] = useState<Record<string, AssistantCronRun[]>>({});
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<AssistantRuntimeSnapshot | null>(null);
  const [cronLoading, setCronLoading] = useState(false);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editingJobId, setEditingJobId] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [runningJobId, setRunningJobId] = useState("");
  const [deletingJobId, setDeletingJobId] = useState("");
  const [draftId, setDraftId] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftScheduleType, setDraftScheduleType] = useState<"daily" | "interval">("daily");
  const [draftTime, setDraftTime] = useState("09:00");
  const [draftEverySeconds, setDraftEverySeconds] = useState("3600");
  const [draftMode, setDraftMode] = useState<"standard" | "dream">("standard");
  const [draftPrompt, setDraftPrompt] = useState("");
  const [draftLookbackHours, setDraftLookbackHours] = useState("24");
  const [draftHistoryLimit, setDraftHistoryLimit] = useState("40");
  const [draftCaptureLimit, setDraftCaptureLimit] = useState("20");
  const [draftDeliverMode, setDraftDeliverMode] = useState<"chat_handoff" | "silent">("chat_handoff");
  const isEditing = editingJobId !== "";

  function resetDraft() {
    setEditingJobId("");
    setDraftId("");
    setDraftTitle("");
    setDraftScheduleType("daily");
    setDraftTime("09:00");
    setDraftEverySeconds("3600");
    setDraftMode("standard");
    setDraftPrompt("");
    setDraftLookbackHours("24");
    setDraftHistoryLimit("40");
    setDraftCaptureLimit("20");
    setDraftDeliverMode("chat_handoff");
  }

  function startEditing(job: AssistantCronJob) {
    onError("");
    onNotice("");
    setEditingJobId(job.id);
    setDraftId(job.id);
    setDraftTitle(job.title);
    setDraftScheduleType(job.schedule.type);
    setDraftTime(job.schedule.time || "09:00");
    setDraftEverySeconds(String(job.schedule.everySeconds || 3600));
    setDraftMode(job.task.mode || "standard");
    setDraftPrompt(job.task.prompt);
    setDraftLookbackHours(String(job.task.lookbackHours || 24));
    setDraftHistoryLimit(String(job.task.historyLimit || 40));
    setDraftCaptureLimit(String(job.task.captureLimit || 20));
    setDraftDeliverMode(
      job.task.deliverMode || ((job.task.mode || "standard") === "dream" ? "silent" : "chat_handoff"),
    );
  }

  function buildPayload() {
    const title = draftTitle.trim();
    const prompt = draftPrompt.trim();
    if (!title) {
      throw new Error("任务标题不能为空");
    }
    if (!prompt) {
      throw new Error("任务提示词不能为空");
    }
    const taskMode = draftMode;
    const task = {
      prompt,
      mode: taskMode,
      lookbackHours: Number(draftLookbackHours),
      historyLimit: Number(draftHistoryLimit),
      captureLimit: Number(draftCaptureLimit),
      deliverMode: draftDeliverMode,
    } as const;
    if (taskMode === "dream") {
      if (!Number.isInteger(task.lookbackHours) || task.lookbackHours <= 0) {
        throw new Error("回看小时数必须是正整数");
      }
      if (!Number.isInteger(task.historyLimit) || task.historyLimit <= 0) {
        throw new Error("聊天历史条数必须是正整数");
      }
      if (!Number.isInteger(task.captureLimit) || task.captureLimit <= 0) {
        throw new Error("capture 条数必须是正整数");
      }
    }
    if (draftScheduleType === "daily") {
      const time = draftTime.trim();
      if (!time) {
        throw new Error("每日时间不能为空");
      }
      return {
        title,
        schedule: {
          type: "daily" as const,
          time,
          timezone: "Asia/Shanghai",
          misfirePolicy: "once" as const,
        },
        task,
        execution: {
          timeoutSeconds: 1800,
        },
      };
    }
    const everySeconds = Number(draftEverySeconds);
    if (!Number.isInteger(everySeconds) || everySeconds <= 0) {
      throw new Error("间隔秒数必须是正整数");
    }
    return {
      title,
      schedule: {
        type: "interval" as const,
        everySeconds,
        timezone: "Asia/Shanghai",
        misfirePolicy: "skip" as const,
      },
      task,
      execution: {
        timeoutSeconds: 1800,
      },
    };
  }

  async function loadRuntimeSnapshot() {
    setRuntimeLoading(true);
    try {
      const overview = await client.getBotOverview(botAlias);
      setRuntimeSnapshot(overview.assistantRuntime || null);
    } catch (error) {
      onError(getErrorMessage(error, "加载队列失败"));
      setRuntimeSnapshot(null);
    } finally {
      setRuntimeLoading(false);
    }
  }

  async function loadCronState() {
    setCronLoading(true);
    try {
      const nextJobs = await client.listAssistantCronJobs(botAlias);
      setJobs(nextJobs);
      const runsEntries = await Promise.all(
        nextJobs.map(async (job) => {
          try {
            const runs = await client.listAssistantCronRuns(botAlias, job.id, 3);
            return [job.id, runs] as const;
          } catch {
            return [job.id, []] as const;
          }
        }),
      );
      setRunsByJobId(Object.fromEntries(runsEntries));
    } catch (error) {
      onError(getErrorMessage(error, "加载 Automation 失败"));
      setJobs([]);
      setRunsByJobId({});
    } finally {
      setCronLoading(false);
    }
  }

  async function reloadAll() {
    await Promise.all([loadCronState(), loadRuntimeSnapshot()]);
  }

  useEffect(() => {
    void reloadAll();
  }, [botAlias]);

  useEffect(() => {
    if (activeTab === "queue") {
      void loadRuntimeSnapshot();
      return;
    }
    void loadCronState();
  }, [activeTab, botAlias]);

  const runRows = useMemo(() => jobs.flatMap((job) => (
    (runsByJobId[job.id] || []).map((run) => ({ job, run }))
  )), [jobs, runsByJobId]);

  async function createJob() {
    const jobId = draftId.trim();
    if (!jobId) {
      onError("任务 ID 不能为空");
      return;
    }
    setCreating(true);
    onError("");
    onNotice("");
    try {
      await client.createAssistantCronJob(botAlias, {
        id: jobId,
        enabled: true,
        ...buildPayload(),
      });
      await loadCronState();
      resetDraft();
      onNotice("Automation 任务已创建");
    } catch (error) {
      onError(getErrorMessage(error, "创建 Automation 任务失败"));
    } finally {
      setCreating(false);
    }
  }

  async function saveEdit() {
    if (!editingJobId) {
      return;
    }
    setSavingEdit(true);
    onError("");
    onNotice("");
    try {
      await client.updateAssistantCronJob(botAlias, editingJobId, buildPayload());
      await loadCronState();
      resetDraft();
      onNotice("Automation 任务已更新");
    } catch (error) {
      onError(getErrorMessage(error, "更新 Automation 任务失败"));
    } finally {
      setSavingEdit(false);
    }
  }

  async function runJob(job: AssistantCronJob) {
    setRunningJobId(job.id);
    onError("");
    onNotice("");
    try {
      const result = await client.runAssistantCronJob(botAlias, job.id);
      const taskMode = result.taskMode || job.task.mode || "standard";
      const deliverMode = result.deliverMode
        || job.task.deliverMode
        || (taskMode === "dream" ? "silent" : "chat_handoff");
      const shouldChatHandoff = taskMode !== "dream" && deliverMode === "chat_handoff";
      if (shouldChatHandoff) {
        dispatchAssistantCronRunEnqueued({
          botAlias,
          runId: result.runId,
          prompt: job.task.prompt,
          queuedAt: new Date().toISOString(),
        });
        onNotice(`任务已投递到聊天会话: ${result.runId}`);
      } else {
        onNotice(`Dream 任务已入队，将在后台静默执行: ${result.runId}`);
      }
      await reloadAll();
    } catch (error) {
      onError(getErrorMessage(error, "手动触发 Automation 失败"));
    } finally {
      setRunningJobId("");
    }
  }

  async function deleteJob(job: AssistantCronJob) {
    setDeletingJobId(job.id);
    onError("");
    onNotice("");
    try {
      await client.deleteAssistantCronJob(botAlias, job.id);
      await reloadAll();
      if (editingJobId === job.id) {
        resetDraft();
      }
      onNotice("Automation 任务已删除");
    } catch (error) {
      onError(getErrorMessage(error, "删除 Automation 任务失败"));
    } finally {
      setDeletingJobId("");
    }
  }

  if (activeTab === "queue") {
    return (
      <div className="space-y-3" role="tabpanel" aria-label="Queue">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-sm font-medium text-[var(--text)]">当前队列</h4>
          <button
            type="button"
            onClick={() => void loadRuntimeSnapshot()}
            disabled={runtimeLoading}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <RefreshCw className="h-4 w-4" />
            {runtimeLoading ? "加载中..." : "刷新"}
          </button>
        </div>
        {runtimeSnapshot?.active ? (
          <article className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
            <div className="text-sm font-medium text-[var(--text)]">{runtimeSnapshot.active.runId}</div>
            <div className="text-xs text-[var(--muted)]">
              running · {runtimeSnapshot.active.source} · {runtimeSnapshot.active.taskMode}
            </div>
          </article>
        ) : null}
        {(runtimeSnapshot?.queue || []).map((run) => (
          <article key={run.runId} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
            <div className="text-sm font-medium text-[var(--text)]">{run.runId}</div>
            <div className="text-xs text-[var(--muted)]">
              queued · {run.source} · {run.jobTitle || run.visibleText || "-"}
            </div>
          </article>
        ))}
        {!runtimeSnapshot?.active && !(runtimeSnapshot?.queue || []).length ? (
          <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
            暂无排队任务
          </div>
        ) : null}
      </div>
    );
  }

  if (activeTab === "runs") {
    return (
      <div className="space-y-3" role="tabpanel" aria-label="Runs">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-sm font-medium text-[var(--text)]">最近运行</h4>
          <button
            type="button"
            onClick={() => void loadCronState()}
            disabled={cronLoading}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <RefreshCw className="h-4 w-4" />
            {cronLoading ? "加载中..." : "刷新"}
          </button>
        </div>
        {runRows.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
            暂无运行记录
          </div>
        ) : (
          runRows.map(({ job, run }) => (
            <article key={`${job.id}-${run.runId}`} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="text-sm font-medium text-[var(--text)]">{job.title}</div>
                  <div className="text-xs text-[var(--muted)]">{job.id}</div>
                </div>
                <div className="text-xs text-[var(--muted)]">
                  {run.status} · {run.runId}
                </div>
              </div>
              <div className="grid grid-cols-1 gap-2 text-xs text-[var(--muted)] sm:grid-cols-2">
                <p><span className="text-[var(--text)]">触发:</span> {run.triggerSource || "-"}</p>
                <p><span className="text-[var(--text)]">入队:</span> {run.enqueuedAt || "-"}</p>
                <p><span className="text-[var(--text)]">计划:</span> {run.scheduledAt || "-"}</p>
                <p><span className="text-[var(--text)]">耗时:</span> {run.elapsedSeconds || 0}s</p>
              </div>
            </article>
          ))
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4" role="tabpanel" aria-label="Cron">
      <div className="space-y-1">
        <h3 className="font-medium text-[var(--text)]">Automation 定时任务</h3>
        <p className="text-xs text-[var(--muted)]">定时任务会和人工对话共用 assistant 串行执行队列。</p>
      </div>

      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-4 space-y-3">
        <h4 className="font-medium text-[var(--text)]">{isEditing ? "编辑任务" : "新建任务"}</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-sm text-[var(--text)]">任务 ID</span>
            <input
              aria-label="任务 ID"
              type="text"
              value={draftId}
              disabled={isEditing}
              onChange={(event) => setDraftId(event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-60"
              placeholder="daily_repo_review"
            />
          </label>
          <label className="space-y-1">
            <span className="text-sm text-[var(--text)]">任务标题</span>
            <input
              aria-label="任务标题"
              type="text"
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
              placeholder="Daily Repo Review"
            />
          </label>
          <label className="space-y-1">
            <span className="text-sm text-[var(--text)]">任务模式</span>
            <select
              aria-label="任务模式"
              value={draftMode}
              onChange={(event) => {
                const nextMode = event.target.value as "standard" | "dream";
                setDraftMode(nextMode);
                setDraftDeliverMode(nextMode === "dream" ? "silent" : "chat_handoff");
              }}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
            >
              <option value="standard">standard</option>
              <option value="dream">dream</option>
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-sm text-[var(--text)]">调度类型</span>
            <select
              aria-label="调度类型"
              value={draftScheduleType}
              onChange={(event) => setDraftScheduleType(event.target.value as "daily" | "interval")}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
            >
              <option value="daily">daily</option>
              <option value="interval">interval</option>
            </select>
          </label>
          {draftScheduleType === "daily" ? (
            <label className="space-y-1">
              <span className="text-sm text-[var(--text)]">每日时间</span>
              <input
                aria-label="每日时间"
                type="text"
                value={draftTime}
                onChange={(event) => setDraftTime(event.target.value)}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
                placeholder="09:00"
              />
            </label>
          ) : (
            <label className="space-y-1">
              <span className="text-sm text-[var(--text)]">间隔秒数</span>
              <input
                aria-label="间隔秒数"
                type="number"
                min={1}
                value={draftEverySeconds}
                onChange={(event) => setDraftEverySeconds(event.target.value)}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
              />
            </label>
          )}
        </div>

        <label className="block space-y-1">
          <span className="text-sm text-[var(--text)]">任务提示词</span>
          <textarea
            aria-label="任务提示词"
            rows={3}
            value={draftPrompt}
            onChange={(event) => setDraftPrompt(event.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
            placeholder="请检查当前仓库状态并输出简短日报。"
          />
        </label>

        {draftMode === "dream" ? (
          <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
            <p className="text-xs text-[var(--muted)]">
              Dream 会在后台单轮完成，只会自动写 `.assistant` 受控目录；涉及代码或长期规则变化时只会生成 proposal。
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-sm text-[var(--text)]">回看小时数</span>
                <input
                  aria-label="回看小时数"
                  type="number"
                  min={1}
                  value={draftLookbackHours}
                  onChange={(event) => setDraftLookbackHours(event.target.value)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm text-[var(--text)]">聊天历史条数</span>
                <input
                  aria-label="聊天历史条数"
                  type="number"
                  min={1}
                  value={draftHistoryLimit}
                  onChange={(event) => setDraftHistoryLimit(event.target.value)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm text-[var(--text)]">Capture 条数</span>
                <input
                  aria-label="Capture 条数"
                  type="number"
                  min={1}
                  value={draftCaptureLimit}
                  onChange={(event) => setDraftCaptureLimit(event.target.value)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm text-[var(--text)]">投递方式</span>
                <select
                  aria-label="投递方式"
                  value={draftDeliverMode}
                  onChange={(event) => setDraftDeliverMode(event.target.value as "chat_handoff" | "silent")}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                >
                  <option value="silent">silent</option>
                  <option value="chat_handoff">chat_handoff</option>
                </select>
              </label>
            </div>
          </div>
        ) : null}

        {isEditing ? (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void saveEdit()}
              disabled={savingEdit}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
            >
              <Save className="h-4 w-4" />
              {savingEdit ? "保存中..." : "保存修改"}
            </button>
            <button
              type="button"
              onClick={resetDraft}
              disabled={savingEdit}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              取消编辑
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => void createJob()}
            disabled={creating}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
          >
            <Save className="h-4 w-4" />
            {creating ? "创建中..." : "创建任务"}
          </button>
        )}
      </div>

      {cronLoading ? (
        <p className="text-sm text-[var(--muted)]">加载 Automation...</p>
      ) : jobs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
          暂无 Automation 任务
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => (
            <article key={job.id} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-4 space-y-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-1">
                  <h4 className="font-medium text-[var(--text)]">{job.title}</h4>
                  <p className="text-xs text-[var(--muted)]">{job.id}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    aria-label={`编辑 ${job.title}`}
                    onClick={() => startEditing(job)}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    aria-label={`立即运行 ${job.title}`}
                    onClick={() => void runJob(job)}
                    disabled={runningJobId === job.id}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    {runningJobId === job.id ? "入队中..." : "立即运行"}
                  </button>
                  <button
                    type="button"
                    aria-label={`删除 ${job.title}`}
                    onClick={() => void deleteJob(job)}
                    disabled={deletingJobId === job.id}
                    className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                  >
                    {deletingJobId === job.id ? "删除中..." : "删除"}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-2 text-xs text-[var(--muted)] sm:grid-cols-2">
                <p><span className="text-[var(--text)]">模式:</span> {job.task.mode || "standard"}</p>
                <p><span className="text-[var(--text)]">调度:</span> {cronScheduleText(job)}</p>
                <p><span className="text-[var(--text)]">下次运行:</span> {job.nextRunAt || "待计算"}</p>
                <p><span className="text-[var(--text)]">状态:</span> {cronStatusText(job)}</p>
                <p><span className="text-[var(--text)]">合并次数:</span> {job.coalescedCount}</p>
                <p><span className="text-[var(--text)]">投递:</span> {job.task.deliverMode || "chat_handoff"}</p>
              </div>

              <p className="text-xs text-[var(--muted)]">
                <span className="text-[var(--text)]">提示词:</span> {summarizePrompt(job.task.prompt)}
              </p>

              {runsByJobId[job.id]?.length ? (
                <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--muted)] space-y-2">
                  <p className="font-medium text-[var(--text)]">最近运行</p>
                  {runsByJobId[job.id].map((run) => (
                    <p key={run.runId || `${job.id}-${run.status}`}>
                      {run.status || "unknown"} · {run.runId || "pending"} · {run.triggerSource || "manual"}
                    </p>
                  ))}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
