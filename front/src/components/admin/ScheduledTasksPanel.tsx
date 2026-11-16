import { CalendarClock, History, Pencil, Play, Plus, Save, Square, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChatConfirmDialog } from "../ChatConfirmDialog";
import { StateBadge } from "../StateBadge";
import { WebApiClientError } from "../../services/types";
import type {
  ScheduledTask,
  ScheduledTaskBusyPolicy,
  ScheduledTaskInput,
  ScheduledTaskListResult,
  ScheduledTaskPatchInput,
  ScheduledTaskRun,
  ScheduledTaskRunStatus,
  ScheduledTaskTrigger,
  ScheduledTaskTriggerType,
  ScheduledTaskWeekday,
} from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { cliTypeLabel } from "../../utils/cliType";
import { getErrorMessage } from "../../utils/errorMessage";

type Props = {
  client: WebBotClient;
  /** Bumped by the Admin Center refresh button; reloads without discarding an open editor. */
  refreshKey?: number;
  onNotice?: (message: string) => void;
};

type Tone = "neutral" | "success" | "warning" | "danger" | "accent";

const POLL_INTERVAL_MS = 10_000;
const RUN_HISTORY_LIMIT = 20;
const ACTIVE_RUN_STATUSES: readonly ScheduledTaskRunStatus[] = ["pending", "waiting", "running"];
const ALL_WEEKDAYS: ScheduledTaskWeekday[] = [1, 2, 3, 4, 5, 6, 7];
const WEEKDAY_LABELS: Record<ScheduledTaskWeekday, string> = {
  1: "一",
  2: "二",
  3: "三",
  4: "四",
  5: "五",
  6: "六",
  7: "日",
};

export const SCHEDULED_RUN_STATUS_META: Record<ScheduledTaskRunStatus, { label: string; tone: Tone }> = {
  pending: { label: "等待中", tone: "neutral" },
  waiting: { label: "等待空闲", tone: "warning" },
  running: { label: "运行中", tone: "accent" },
  completed: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "neutral" },
  skipped: { label: "已跳过", tone: "neutral" },
  missed: { label: "已错过", tone: "warning" },
  interrupted: { label: "已中断", tone: "danger" },
};

const TRIGGER_TYPE_OPTIONS: Array<{ id: ScheduledTaskTriggerType; label: string }> = [
  { id: "daily", label: "每天/每周" },
  { id: "interval", label: "间隔" },
  { id: "once", label: "一次" },
];

const DISABLED_REASON_LABELS: Record<string, string> = {
  bot_removed: "目标 Bot 已删除",
  once_finished: "一次性任务已执行",
  invalid_trigger: "触发规则无效，请重新编辑",
};

const FIELD_CLASS = "w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-70";

function isActiveRun(run: ScheduledTaskRun | null | undefined) {
  return Boolean(run && ACTIVE_RUN_STATUSES.includes(run.status));
}

function pad2(value: number) {
  return String(value).padStart(2, "0");
}

/** Joins runs of three or more consecutive days into "一至周五", the rest with "、". */
function weekdaySummary(weekdays: readonly number[]) {
  const days = Array.from(new Set(weekdays)).filter((day) => day >= 1 && day <= 7).sort((a, b) => a - b);
  const parts: string[] = [];
  let index = 0;
  while (index < days.length) {
    let end = index;
    while (end + 1 < days.length && days[end + 1] === days[end] + 1) end += 1;
    const first = WEEKDAY_LABELS[days[index] as ScheduledTaskWeekday];
    const last = WEEKDAY_LABELS[days[end] as ScheduledTaskWeekday];
    if (end - index >= 2) {
      parts.push(`${first}至周${last}`);
    } else {
      for (let cursor = index; cursor <= end; cursor += 1) parts.push(WEEKDAY_LABELS[days[cursor] as ScheduledTaskWeekday]);
    }
    index = end + 1;
  }
  return parts.join("、");
}

function hasExplicitOffset(value: string) {
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value.trim());
}

/** Wall-clock "YYYY-MM-DDTHH:mm" of an instant in `timeZone`; naive inputs are already wall time. */
function wallTimeIn(value: string, timeZone: string) {
  if (!value) return "";
  if (!hasExplicitOffset(value)) return value.slice(0, 16);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: timeZone || undefined,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(date);
  } catch {
    return localWallTime(date);
  }
  const get = (type: string) => parts.find((part) => part.type === type)?.value || "";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

function localWallTime(date: Date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}T${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

export function scheduleTriggerSummary(trigger: ScheduledTaskTrigger, timeZone: string) {
  if (trigger.type === "interval") return `每 ${trigger.minutes} 分钟`;
  if (trigger.type === "once") {
    const wall = wallTimeIn(trigger.at, timeZone);
    return wall ? `一次 · ${wall.slice(5, 10)} ${wall.slice(11, 16)}` : "一次";
  }
  const days = new Set(trigger.weekdays);
  if (ALL_WEEKDAYS.every((day) => days.has(day))) return `每天 ${trigger.time}`;
  return `每周${weekdaySummary(trigger.weekdays)} ${trigger.time}`;
}

/** Browser-local "MM-DD HH:mm", with the year when it differs from now. */
function formatLocalTime(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const prefix = date.getFullYear() === new Date().getFullYear() ? "" : `${date.getFullYear()}-`;
  return `${prefix}${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

type Draft = {
  name: string;
  botAlias: string;
  prompt: string;
  triggerType: ScheduledTaskTriggerType;
  time: string;
  weekdays: ScheduledTaskWeekday[];
  intervalMinutes: string;
  onceAt: string;
  timezone: string;
  busyPolicy: ScheduledTaskBusyPolicy;
  maxWaitMinutes: string;
  misfireGraceMinutes: string;
  allowUnsafeCli: boolean;
  enabled: boolean;
};

type EditorState = { mode: "create" } | { mode: "edit"; task: ScheduledTask };

function tomorrowNineLocal() {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(9, 0, 0, 0);
  return localWallTime(date);
}

function createDraft(data: ScheduledTaskListResult): Draft {
  return {
    name: "",
    botAlias: data.targets[0]?.alias || "",
    prompt: "",
    triggerType: "daily",
    time: "09:00",
    weekdays: [...ALL_WEEKDAYS],
    intervalMinutes: "60",
    onceAt: tomorrowNineLocal(),
    timezone: data.defaultTimezone,
    busyPolicy: "wait",
    maxWaitMinutes: String(Math.min(15, data.limits.maxWaitMinutes)),
    misfireGraceMinutes: String(Math.min(30, data.limits.maxMisfireGraceMinutes)),
    allowUnsafeCli: false,
    enabled: true,
  };
}

function draftFromTask(task: ScheduledTask, data: ScheduledTaskListResult): Draft {
  const base = createDraft(data);
  const trigger = task.trigger;
  return {
    ...base,
    name: task.name,
    botAlias: task.botAlias,
    prompt: task.prompt,
    triggerType: trigger.type,
    time: trigger.type === "daily" ? trigger.time : base.time,
    weekdays: trigger.type === "daily" ? [...trigger.weekdays] : base.weekdays,
    intervalMinutes: trigger.type === "interval" ? String(trigger.minutes) : base.intervalMinutes,
    onceAt: trigger.type === "once" ? wallTimeIn(trigger.at, task.timezone) : base.onceAt,
    timezone: task.timezone,
    busyPolicy: task.busyPolicy,
    maxWaitMinutes: String(task.maxWaitMinutes),
    misfireGraceMinutes: String(task.misfireGraceMinutes),
    allowUnsafeCli: task.allowUnsafeCli,
    enabled: task.enabled,
  };
}

function parseWholeNumber(value: string) {
  return /^\d+$/.test(value.trim()) ? Number(value.trim()) : Number.NaN;
}

function validateDraft(draft: Draft, data: ScheduledTaskListResult) {
  const { limits } = data;
  if (!draft.name.trim()) return "请填写任务名称";
  if (!draft.botAlias) return "请选择目标 Bot";
  if (!draft.prompt.trim()) return "请填写要发送的指令";
  if (draft.prompt.length > limits.maxPromptChars) return `指令不能超过 ${limits.maxPromptChars} 个字符`;
  if (draft.triggerType === "daily") {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(draft.time)) return "请填写有效的时间（HH:MM）";
    if (!draft.weekdays.length) return "请至少选择一天";
  } else if (draft.triggerType === "interval") {
    const minutes = parseWholeNumber(draft.intervalMinutes);
    if (!Number.isFinite(minutes) || minutes < limits.minIntervalMinutes) {
      return `间隔需为不少于 ${limits.minIntervalMinutes} 的整数分钟`;
    }
  } else if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(draft.onceAt)) {
    return "请选择执行时间";
  }
  if (!draft.timezone.trim()) return "请填写时区";
  if (draft.busyPolicy === "wait") {
    const wait = parseWholeNumber(draft.maxWaitMinutes);
    if (!Number.isFinite(wait) || wait < 1 || wait > limits.maxWaitMinutes) {
      return `最长等待需为 1 到 ${limits.maxWaitMinutes} 分钟`;
    }
  }
  const grace = parseWholeNumber(draft.misfireGraceMinutes);
  if (!Number.isFinite(grace) || grace > limits.maxMisfireGraceMinutes) {
    return `错过补跑窗口需为 0 到 ${limits.maxMisfireGraceMinutes} 分钟`;
  }
  return "";
}

function draftTrigger(draft: Draft, original?: ScheduledTask): ScheduledTaskTrigger {
  if (draft.triggerType === "interval") {
    const anchor = original?.trigger.type === "interval" ? original.trigger.anchor : undefined;
    return { type: "interval", minutes: parseWholeNumber(draft.intervalMinutes), ...(anchor ? { anchor } : {}) };
  }
  if (draft.triggerType === "once") {
    // An untouched time keeps the stored instant; an edited one is wall time in `timezone`.
    const unchanged = original?.trigger.type === "once"
      && draft.timezone.trim() === original.timezone
      && draft.onceAt === wallTimeIn(original.trigger.at, original.timezone);
    return { type: "once", at: unchanged && original?.trigger.type === "once" ? original.trigger.at : draft.onceAt.slice(0, 16) };
  }
  return { type: "daily", time: draft.time, weekdays: [...draft.weekdays].sort((a, b) => a - b) };
}

function draftToInput(draft: Draft, original?: ScheduledTask): ScheduledTaskInput {
  const fallbackWait = original?.maxWaitMinutes ?? 15;
  const wait = parseWholeNumber(draft.maxWaitMinutes);
  return {
    name: draft.name.trim(),
    botAlias: draft.botAlias,
    prompt: draft.prompt,
    trigger: draftTrigger(draft, original),
    timezone: draft.timezone.trim(),
    busyPolicy: draft.busyPolicy,
    maxWaitMinutes: Number.isFinite(wait) && wait >= 1 ? wait : fallbackWait,
    misfireGraceMinutes: parseWholeNumber(draft.misfireGraceMinutes),
    allowUnsafeCli: draft.allowUnsafeCli,
    enabled: draft.enabled,
  };
}

function errorCode(error: unknown) {
  return error instanceof WebApiClientError ? error.code || "" : "";
}

const CONFLICT_MESSAGE = "该定时任务已在别处被修改，已重新加载最新内容。";

export function ScheduledTasksPanel({ client, refreshKey = 0, onNotice }: Props) {
  const [data, setData] = useState<ScheduledTaskListResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editorError, setEditorError] = useState("");
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ScheduledTask | null>(null);
  const [historyId, setHistoryId] = useState("");
  const [runs, setRuns] = useState<ScheduledTaskRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState("");
  const [cancellingRunId, setCancellingRunId] = useState("");
  const historyIdRef = useRef("");
  historyIdRef.current = historyId;

  const loadList = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const next = await client.listScheduledTasks();
      setData(next);
      if (!silent) setError("");
      return next;
    } catch (nextError) {
      if (!silent) setError(getErrorMessage(nextError, "加载定时任务失败"));
      return null;
    } finally {
      if (!silent) setLoading(false);
    }
  }, [client]);

  const loadRuns = useCallback(async (scheduleId: string, silent = false) => {
    if (!silent) {
      setRunsLoading(true);
      setRunsError("");
    }
    try {
      const items = await client.listScheduledTaskRuns(scheduleId, RUN_HISTORY_LIMIT);
      if (historyIdRef.current === scheduleId) setRuns(items);
    } catch (nextError) {
      if (!silent && historyIdRef.current === scheduleId) setRunsError(getErrorMessage(nextError, "加载运行记录失败"));
    } finally {
      if (!silent) setRunsLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void loadList();
    if (historyIdRef.current) void loadRuns(historyIdRef.current);
  }, [loadList, loadRuns, refreshKey]);

  const hasActiveRun = useMemo(
    () => Boolean(data?.items.some((item) => item.activeRunId || isActiveRun(item.lastRun))),
    [data],
  );

  useEffect(() => {
    if (!hasActiveRun) return undefined;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void loadList(true);
      if (historyIdRef.current) void loadRuns(historyIdRef.current, true);
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [hasActiveRun, loadList, loadRuns]);

  function openCreate() {
    if (!data) return;
    setEditor({ mode: "create" });
    setDraft(createDraft(data));
    setEditorError("");
  }

  function openEdit(task: ScheduledTask) {
    if (!data) return;
    setEditor({ mode: "edit", task });
    setDraft(draftFromTask(task, data));
    setEditorError("");
  }

  function closeEditor() {
    setEditor(null);
    setDraft(null);
    setEditorError("");
  }

  function patchDraft(patch: Partial<Draft>) {
    setDraft((previous) => (previous ? { ...previous, ...patch } : previous));
  }

  async function handleConflict(scheduleId: string) {
    const next = await loadList(true);
    const latest = next?.items.find((item) => item.id === scheduleId);
    return latest || null;
  }

  async function saveEditor() {
    if (!data || !draft || !editor) return;
    const validation = validateDraft(draft, data);
    if (validation) {
      setEditorError(validation);
      return;
    }
    setSaving(true);
    setEditorError("");
    const original = editor.mode === "edit" ? editor.task : undefined;
    const input = draftToInput(draft, original);
    try {
      if (!original) {
        await client.createScheduledTask({ ...input, allowUnsafeCli: data.canAllowUnsafeCli && input.allowUnsafeCli });
        onNotice?.(`定时任务「${input.name}」已创建`);
      } else {
        const { allowUnsafeCli, ...rest } = input;
        const patch: ScheduledTaskPatchInput = {
          ...rest,
          // Without run_unsafe_cli the stored flag is left untouched instead of being rejected.
          ...(data.canAllowUnsafeCli ? { allowUnsafeCli } : {}),
          revision: original.revision,
        };
        await client.updateScheduledTask(original.id, patch);
        onNotice?.(`定时任务「${input.name}」已保存`);
      }
      closeEditor();
      await loadList(true);
    } catch (nextError) {
      const code = errorCode(nextError);
      if (code === "schedule_conflict" && original) {
        const latest = await handleConflict(original.id);
        if (latest) {
          // Keep the typed draft; saving again applies it on top of the latest revision.
          setEditor({ mode: "edit", task: latest });
          setEditorError(`${CONFLICT_MESSAGE}请核对后再次保存，保存会覆盖对方的修改。`);
        } else {
          closeEditor();
          setError("该定时任务已被删除");
        }
      } else if (code === "schedule_not_found") {
        closeEditor();
        setError("该定时任务已被删除");
        await loadList(true);
      } else {
        setEditorError(getErrorMessage(nextError, "保存定时任务失败"));
      }
    } finally {
      setSaving(false);
    }
  }

  async function toggleEnabled(task: ScheduledTask, enabled: boolean) {
    setBusyId(task.id);
    setError("");
    try {
      await client.updateScheduledTask(task.id, { enabled, revision: task.revision });
      onNotice?.(enabled ? `已启用「${task.name}」` : `已停用「${task.name}」`);
      await loadList(true);
    } catch (nextError) {
      if (errorCode(nextError) === "schedule_conflict") {
        await handleConflict(task.id);
        setError(`${CONFLICT_MESSAGE}请重新操作。`);
      } else {
        setError(getErrorMessage(nextError, "更新定时任务失败"));
        await loadList(true);
      }
    } finally {
      setBusyId("");
    }
  }

  async function runNow(task: ScheduledTask) {
    setBusyId(task.id);
    setError("");
    try {
      await client.runScheduledTaskNow(task.id);
      onNotice?.(`已触发「${task.name}」，将新建会话并发送指令`);
      await loadList(true);
      if (historyIdRef.current === task.id) await loadRuns(task.id, true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "立即运行失败"));
    } finally {
      setBusyId("");
    }
  }

  async function confirmDelete() {
    const task = deleteTarget;
    setDeleteTarget(null);
    if (!task) return;
    setBusyId(task.id);
    setError("");
    try {
      await client.deleteScheduledTask(task.id);
      onNotice?.(`定时任务「${task.name}」已删除`);
      if (historyIdRef.current === task.id) setHistoryId("");
      if (editor?.mode === "edit" && editor.task.id === task.id) closeEditor();
      await loadList(true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "删除定时任务失败"));
    } finally {
      setBusyId("");
    }
  }

  function toggleHistory(task: ScheduledTask) {
    if (historyId === task.id) {
      setHistoryId("");
      return;
    }
    historyIdRef.current = task.id;
    setHistoryId(task.id);
    setRuns([]);
    void loadRuns(task.id);
  }

  async function cancelRun(task: ScheduledTask, run: ScheduledTaskRun) {
    setCancellingRunId(run.id);
    setRunsError("");
    try {
      await client.cancelScheduledTaskRun(task.id, run.id);
      onNotice?.("已请求取消本次运行");
      await Promise.all([loadRuns(task.id, true), loadList(true)]);
    } catch (nextError) {
      setRunsError(getErrorMessage(nextError, "取消运行失败"));
    } finally {
      setCancellingRunId("");
    }
  }

  const targetOptions = useMemo(() => {
    const targets = (data?.targets || []).map((target) => ({ ...target, missing: false }));
    const current = editor?.mode === "edit" ? editor.task.botAlias : "";
    if (current && !targets.some((target) => target.alias === current)) {
      return [...targets, { alias: current, cliType: "", missing: true }];
    }
    return targets;
  }, [data, editor]);

  const editingUnsafeLocked = editor?.mode === "edit" && editor.task.allowUnsafeCli && !data?.canAllowUnsafeCli;

  return (
    <section className="admin-island orbit-island orbit-island--reading space-y-4" aria-label="定时任务">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <CalendarClock className="mt-0.5 h-5 w-5 text-[var(--accent)]" />
          <div>
            <h2 className="text-base font-semibold text-[var(--text)]">定时任务</h2>
            <p className="mt-1 text-sm text-[var(--muted)]">
              到点后在目标 Bot 上新建会话并发送固定指令，同时把该 Bot 的当前会话切换过去；原有会话记录仍会保留。
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={openCreate}
          disabled={!data || Boolean(editor)}
          className="orbit-btn orbit-btn--primary text-sm"
        >
          <Plus className="h-4 w-4" />
          新建定时任务
        </button>
      </div>

      {error ? <div role="alert" className="admin-callout" data-tone="danger">{error}</div> : null}
      {loading && !data ? <p className="text-sm text-[var(--muted)]">加载中...</p> : null}

      {editor && draft && data ? (
        <div className="admin-well space-y-4 p-4" role="group" aria-label={editor.mode === "create" ? "新建定时任务" : "编辑定时任务"}>
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-[var(--text)]">
              {editor.mode === "create" ? "新建定时任务" : `编辑「${editor.task.name}」`}
            </h3>
            <button type="button" onClick={closeEditor} disabled={saving} className="orbit-btn orbit-btn--ghost orbit-btn--sm text-xs">
              <X className="h-3.5 w-3.5" />
              取消
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="text-sm text-[var(--text)]">任务名称</span>
              <input
                aria-label="任务名称"
                value={draft.name}
                onChange={(event) => patchDraft({ name: event.target.value })}
                placeholder="例如：每日晨报"
                className={FIELD_CLASS}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm text-[var(--text)]">目标 Bot</span>
              <select
                aria-label="目标 Bot"
                value={draft.botAlias}
                onChange={(event) => patchDraft({ botAlias: event.target.value })}
                className={FIELD_CLASS}
              >
                {!targetOptions.length ? <option value="">暂无可用 Bot</option> : null}
                {targetOptions.map((target) => (
                  <option key={target.alias} value={target.alias}>
                    {target.missing
                      ? `${target.alias}（已不可用）`
                      : `${target.alias}${target.cliType ? ` · ${cliTypeLabel(target.cliType)}` : ""}`}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="block space-y-1">
            <span className="flex items-center justify-between text-sm text-[var(--text)]">
              <span>指令内容</span>
              <span
                className={`text-xs ${draft.prompt.length > data.limits.maxPromptChars ? "text-[var(--status-danger)]" : "text-[var(--muted)]"}`}
              >
                {draft.prompt.length} / {data.limits.maxPromptChars}
              </span>
            </span>
            <textarea
              aria-label="指令内容"
              value={draft.prompt}
              rows={5}
              onChange={(event) => patchDraft({ prompt: event.target.value })}
              placeholder="每次触发时发送给智能体 main 的固定指令"
              className={`${FIELD_CLASS} resize-y`}
            />
          </label>

          <div className="space-y-2">
            <span className="block text-sm text-[var(--text)]" id="schedule-trigger-type-label">触发方式</span>
            <div role="group" aria-labelledby="schedule-trigger-type-label" className="orbit-segmented orbit-segmented--accent w-fit">
              {TRIGGER_TYPE_OPTIONS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  aria-pressed={draft.triggerType === option.id}
                  onClick={() => patchDraft({ triggerType: option.id })}
                  className="text-sm"
                >
                  {option.label}
                </button>
              ))}
            </div>

            {draft.triggerType === "daily" ? (
              <div className="flex flex-wrap items-end gap-3">
                <label className="space-y-1">
                  <span className="block text-xs text-[var(--muted)]">时间</span>
                  <input
                    aria-label="触发时间"
                    type="time"
                    value={draft.time}
                    onChange={(event) => patchDraft({ time: event.target.value })}
                    className={FIELD_CLASS}
                  />
                </label>
                <div className="space-y-1">
                  <span className="block text-xs text-[var(--muted)]" id="schedule-weekdays-label">星期</span>
                  <div role="group" aria-labelledby="schedule-weekdays-label" className="orbit-segmented orbit-segmented--accent">
                    {ALL_WEEKDAYS.map((day) => (
                      <button
                        key={day}
                        type="button"
                        aria-label={`周${WEEKDAY_LABELS[day]}`}
                        aria-pressed={draft.weekdays.includes(day)}
                        onClick={() => patchDraft({
                          weekdays: draft.weekdays.includes(day)
                            ? draft.weekdays.filter((item) => item !== day)
                            : [...draft.weekdays, day].sort((a, b) => a - b),
                        })}
                        className="text-sm"
                      >
                        {WEEKDAY_LABELS[day]}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex gap-1">
                  <button type="button" onClick={() => patchDraft({ weekdays: [...ALL_WEEKDAYS] })} className="orbit-btn orbit-btn--ghost orbit-btn--sm text-xs">每天</button>
                  <button type="button" onClick={() => patchDraft({ weekdays: [1, 2, 3, 4, 5] })} className="orbit-btn orbit-btn--ghost orbit-btn--sm text-xs">工作日</button>
                </div>
              </div>
            ) : null}

            {draft.triggerType === "interval" ? (
              <label className="inline-block space-y-1">
                <span className="block text-xs text-[var(--muted)]">间隔（分钟，至少 {data.limits.minIntervalMinutes}）</span>
                <input
                  aria-label="间隔分钟"
                  type="number"
                  min={data.limits.minIntervalMinutes}
                  step={1}
                  value={draft.intervalMinutes}
                  onChange={(event) => patchDraft({ intervalMinutes: event.target.value })}
                  className={FIELD_CLASS}
                />
              </label>
            ) : null}

            {draft.triggerType === "once" ? (
              <label className="inline-block space-y-1">
                <span className="block text-xs text-[var(--muted)]">执行时间（按下方时区）</span>
                <input
                  aria-label="执行时间"
                  type="datetime-local"
                  value={draft.onceAt}
                  onChange={(event) => patchDraft({ onceAt: event.target.value })}
                  className={FIELD_CLASS}
                />
              </label>
            ) : null}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="text-sm text-[var(--text)]">时区</span>
              <input
                aria-label="时区"
                value={draft.timezone}
                onChange={(event) => patchDraft({ timezone: event.target.value })}
                placeholder={data.defaultTimezone}
                className={FIELD_CLASS}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm text-[var(--text)]">错过补跑窗口（分钟）</span>
              <input
                aria-label="错过补跑窗口"
                type="number"
                min={0}
                max={data.limits.maxMisfireGraceMinutes}
                step={1}
                value={draft.misfireGraceMinutes}
                onChange={(event) => patchDraft({ misfireGraceMinutes: event.target.value })}
                className={FIELD_CLASS}
              />
              <span className="block text-xs text-[var(--muted)]">服务暂停期间错过的触发，超过该时长后不再补跑。</span>
            </label>
          </div>

          <div className="space-y-2">
            <span className="block text-sm text-[var(--text)]">Bot 忙碌时</span>
            <div className="flex flex-wrap items-center gap-3">
              <label className="admin-choice">
                <input
                  type="radio"
                  name="schedule-busy-policy"
                  checked={draft.busyPolicy === "wait"}
                  onChange={() => patchDraft({ busyPolicy: "wait" })}
                />
                <span>等待空闲</span>
              </label>
              <label className="admin-choice">
                <input
                  type="radio"
                  name="schedule-busy-policy"
                  checked={draft.busyPolicy === "skip"}
                  onChange={() => patchDraft({ busyPolicy: "skip" })}
                />
                <span>忙碌时跳过</span>
              </label>
              {draft.busyPolicy === "wait" ? (
                <label className="inline-flex items-center gap-2 whitespace-nowrap text-sm text-[var(--text)]">
                  最长等待
                  <input
                    aria-label="最长等待分钟"
                    type="number"
                    min={1}
                    max={data.limits.maxWaitMinutes}
                    step={1}
                    value={draft.maxWaitMinutes}
                    onChange={(event) => patchDraft({ maxWaitMinutes: event.target.value })}
                    className={FIELD_CLASS.replace("w-full", "w-24")}
                  />
                  分钟，超时则跳过
                </label>
              ) : null}
            </div>
          </div>

          <div className="space-y-2">
            {data.canAllowUnsafeCli ? (
              <div className="space-y-1">
                <label className="admin-toggle">
                  <input
                    type="checkbox"
                    checked={draft.allowUnsafeCli}
                    onChange={(event) => patchDraft({ allowUnsafeCli: event.target.checked })}
                  />
                  <span className="admin-toggle-label">允许高风险 CLI 参数</span>
                </label>
                {draft.allowUnsafeCli ? (
                  <p className="admin-callout text-xs" data-tone="warning">
                    无人值守的运行将可使用跳过权限确认等高风险 CLI 参数，请确认指令内容安全。
                  </p>
                ) : null}
              </div>
            ) : editingUnsafeLocked ? (
              <p className="text-xs text-[var(--muted)]">该任务已允许高风险 CLI 参数；当前账号没有高风险 CLI 权限，保存时不会修改此项。</p>
            ) : null}
            <label className="admin-toggle">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) => patchDraft({ enabled: event.target.checked })}
              />
              <span className="admin-toggle-label">启用</span>
            </label>
          </div>

          <p className="text-xs text-[var(--muted)]">
            每次运行都会在目标 Bot 上新建会话，并把该 Bot 的当前会话切换到新会话；旧会话的历史记录会保留。
          </p>

          {editorError ? <div role="alert" className="admin-callout" data-tone="danger">{editorError}</div> : null}

          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void saveEditor()} disabled={saving} className="orbit-btn orbit-btn--primary text-sm">
              <Save className="h-4 w-4" />
              {saving ? "保存中..." : editor.mode === "create" ? "创建定时任务" : "保存修改"}
            </button>
          </div>
        </div>
      ) : null}

      {data && !data.items.length && !editor ? (
        <p className="admin-well px-3 py-4 text-sm text-[var(--muted)]">还没有定时任务。</p>
      ) : null}

      {data?.items.length ? (
        <ul className="space-y-3" aria-label="定时任务列表">
          {data.items.map((task) => {
            const lastStatus = task.lastRun ? SCHEDULED_RUN_STATUS_META[task.lastRun.status] : null;
            const rowBusy = busyId === task.id;
            const historyOpen = historyId === task.id;
            return (
              <li key={task.id} className="admin-well space-y-3 p-3" aria-label={task.name}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-sm font-semibold text-[var(--text)]">{task.name}</h3>
                      {!task.enabled ? <StateBadge>已停用</StateBadge> : null}
                      {task.disabledReason ? (
                        <StateBadge tone="warning">{DISABLED_REASON_LABELS[task.disabledReason] || task.disabledReason}</StateBadge>
                      ) : null}
                      {task.allowUnsafeCli ? <StateBadge tone="danger">高风险 CLI</StateBadge> : null}
                    </div>
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs text-[var(--muted)] sm:grid-cols-[auto_1fr_auto_1fr]">
                      <dt>目标</dt>
                      <dd className="text-[var(--text)]">{task.botAlias}</dd>
                      <dt>触发</dt>
                      <dd className="text-[var(--text)]">{scheduleTriggerSummary(task.trigger, task.timezone)}</dd>
                      <dt>时区</dt>
                      <dd className="text-[var(--text)]">{task.timezone}</dd>
                      <dt>下次</dt>
                      <dd className="text-[var(--text)]" title={task.nextRunAt || undefined}>{formatLocalTime(task.nextRunAt)}</dd>
                    </dl>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                      <span>上次运行</span>
                      {task.lastRun && lastStatus ? (
                        <>
                          <StateBadge tone={lastStatus.tone}>{lastStatus.label}</StateBadge>
                          <span>{formatLocalTime(task.lastRun.startedAt || task.lastRun.plannedAt)}</span>
                        </>
                      ) : (
                        <span>暂无</span>
                      )}
                    </div>
                  </div>
                  <label className="admin-toggle">
                    <input
                      type="checkbox"
                      aria-label={`启用 ${task.name}`}
                      checked={task.enabled}
                      disabled={rowBusy}
                      onChange={(event) => void toggleEnabled(task, event.target.checked)}
                    />
                    <span className="admin-toggle-label">{task.enabled ? "已启用" : "已停用"}</span>
                  </label>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void runNow(task)}
                    disabled={rowBusy || Boolean(task.activeRunId)}
                    aria-label={`立即运行 ${task.name}`}
                    className="orbit-btn orbit-btn--secondary orbit-btn--sm text-xs"
                  >
                    <Play className="h-3.5 w-3.5" />
                    {task.activeRunId ? "运行中" : "立即运行"}
                  </button>
                  <button
                    type="button"
                    onClick={() => openEdit(task)}
                    disabled={rowBusy || Boolean(editor)}
                    aria-label={`编辑 ${task.name}`}
                    className="orbit-btn orbit-btn--ghost orbit-btn--sm text-xs"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                    编辑
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleHistory(task)}
                    aria-expanded={historyOpen}
                    aria-label={`运行记录 ${task.name}`}
                    className="orbit-btn orbit-btn--ghost orbit-btn--sm text-xs"
                  >
                    <History className="h-3.5 w-3.5" />
                    运行记录
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeleteTarget(task)}
                    disabled={rowBusy}
                    aria-label={`删除 ${task.name}`}
                    className="orbit-btn orbit-btn--sm admin-btn--danger-quiet text-xs"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    删除
                  </button>
                </div>

                {historyOpen ? (
                  <div className="space-y-2 border-t border-[var(--border)] pt-3" aria-label={`${task.name} 的运行记录`}>
                    {runsError ? <div role="alert" className="admin-callout" data-tone="danger">{runsError}</div> : null}
                    {runsLoading && !runs.length ? <p className="text-xs text-[var(--muted)]">加载中...</p> : null}
                    {!runsLoading && !runs.length && !runsError ? <p className="text-xs text-[var(--muted)]">暂无运行记录</p> : null}
                    {runs.map((run) => {
                      const meta = SCHEDULED_RUN_STATUS_META[run.status];
                      return (
                        <article key={run.id} className="space-y-1 rounded-lg border border-[var(--border)] px-3 py-2 text-xs">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[var(--text)]">{formatLocalTime(run.plannedAt)}</span>
                            <StateBadge>{run.trigger === "manual" ? "手动" : "定时"}</StateBadge>
                            <StateBadge tone={meta.tone}>{meta.label}</StateBadge>
                            {run.unsafeDowngraded ? <StateBadge tone="warning">已降级为安全参数</StateBadge> : null}
                            {isActiveRun(run) ? (
                              <button
                                type="button"
                                onClick={() => void cancelRun(task, run)}
                                disabled={cancellingRunId === run.id}
                                className="orbit-btn orbit-btn--sm admin-btn--danger-quiet ml-auto text-xs"
                              >
                                <Square className="h-3 w-3" />
                                {cancellingRunId === run.id ? "取消中..." : "取消运行"}
                              </button>
                            ) : null}
                          </div>
                          {run.reasonMessage ? <p className="text-[var(--muted)]">{run.reasonMessage}</p> : null}
                          {run.preview ? <p className="line-clamp-3 whitespace-pre-wrap text-[var(--text)]">{run.preview}</p> : null}
                          {run.conversationId ? (
                            <p className="text-[var(--muted)]">会话 <code className="font-mono">{run.conversationId}</code></p>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      {deleteTarget ? (
        <ChatConfirmDialog
          label="确认删除定时任务"
          title={`删除「${deleteTarget.name}」？`}
          description="删除后不再触发；已经创建的会话和其中的记录不受影响。"
          confirmLabel="确认删除"
          tone="danger"
          onConfirm={() => void confirmDelete()}
          onCancel={() => setDeleteTarget(null)}
        />
      ) : null}
    </section>
  );
}
