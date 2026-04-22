import { clsx } from "clsx";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Copy, Globe, LogOut, RefreshCw, RotateCw, Save, Square } from "lucide-react";
import { AvatarPicker } from "../components/AvatarPicker";
import { BotIdentity } from "../components/BotIdentity";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { PluginCatalog } from "../components/PluginCatalog";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError } from "../services/types";
import type {
  AppUpdateDownloadProgress,
  AppUpdateStatus,
  AssistantCronJob,
  AssistantCronRun,
  AvatarAsset,
  BotOverview,
  CliParamField,
  CliParamsPayload,
  GitProxySettings,
  PluginSummary,
  TunnelSnapshot,
  UpdateBotWorkdirOptions,
  WorkdirChangeConflict,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { dispatchAssistantCronRunEnqueued } from "../utils/assistantCronEvents";
import { DEFAULT_AVATAR_ASSETS, readStoredUserAvatarName } from "../utils/avatar";
import { normalizePathInput } from "../utils/pathInput";
import {
  CHAT_BODY_FONT_FAMILY_OPTIONS,
  CHAT_BODY_FONT_SIZE_OPTIONS,
  CHAT_BODY_LINE_HEIGHT_OPTIONS,
  CHAT_BODY_PARAGRAPH_SPACING_OPTIONS,
  DEFAULT_CHAT_BODY_FONT_FAMILY,
  DEFAULT_CHAT_BODY_FONT_SIZE,
  DEFAULT_CHAT_BODY_LINE_HEIGHT,
  DEFAULT_CHAT_BODY_PARAGRAPH_SPACING,
  DEFAULT_UI_THEME,
  UI_THEME_OPTIONS,
  type ChatBodyFontFamilyName,
  type ChatBodyFontSizeName,
  type ChatBodyLineHeightName,
  type ChatBodyParagraphSpacingName,
  type UiThemeName,
} from "../theme";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  client?: WebBotClient;
  onLogout: () => void;
  embedded?: boolean;
  prefilledWorkdir?: string;
  onWorkdirUpdated?: (workingDir: string) => void;
  themeName?: UiThemeName;
  onThemeChange?: (themeName: UiThemeName) => void;
  chatBodyFontFamily?: ChatBodyFontFamilyName;
  onChatBodyFontFamilyChange?: (fontFamily: ChatBodyFontFamilyName) => void;
  chatBodyFontSize?: ChatBodyFontSizeName;
  onChatBodyFontSizeChange?: (fontSize: ChatBodyFontSizeName) => void;
  chatBodyLineHeight?: ChatBodyLineHeightName;
  onChatBodyLineHeightChange?: (lineHeight: ChatBodyLineHeightName) => void;
  chatBodyParagraphSpacing?: ChatBodyParagraphSpacingName;
  onChatBodyParagraphSpacingChange?: (paragraphSpacing: ChatBodyParagraphSpacingName) => void;
  userAvatarName?: string;
  onUserAvatarChange?: (avatarName: string) => void;
  sessionCapabilities?: string[];
};

type DraftValues = Record<string, string | boolean>;
type BuildLogStatus = "idle" | "running" | "success" | "error";

function fieldLabel(key: string, field: CliParamField) {
  return field.description || key;
}

function buildDraftValues(payload: CliParamsPayload): DraftValues {
  const drafts: DraftValues = {};
  for (const [key, field] of Object.entries(payload.schema)) {
    const value = payload.params[key];
    if (field.type === "boolean") {
      drafts[key] = Boolean(value);
      continue;
    }
    if (field.type === "string_list") {
      drafts[key] = Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
      continue;
    }
    drafts[key] = value == null ? "" : String(value);
  }
  return drafts;
}

function toRequestValue(field: CliParamField, value: string | boolean) {
  if (field.type === "boolean") {
    return Boolean(value);
  }
  if (field.type === "string_list") {
    return String(value)
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return value;
}

function hasDraftValueChanged(previousValue: string | boolean, nextValue: string | boolean) {
  return previousValue !== nextValue;
}

function tunnelStatusText(status: TunnelSnapshot["status"]) {
  if (status === "running") return "运行中";
  if (status === "starting") return "启动中";
  if (status === "error") return "异常";
  return "已停止";
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function asWebApiClientError(error: unknown): WebApiClientError | null {
  if (error instanceof WebApiClientError) {
    return error;
  }
  if (!error || typeof error !== "object") {
    return null;
  }
  const candidate = error as Partial<WebApiClientError> & { name?: unknown };
  if (candidate.name === "WebApiClientError" || typeof candidate.code === "string") {
    return candidate as WebApiClientError;
  }
  return null;
}

function cronScheduleText(job: AssistantCronJob) {
  if (job.schedule.type === "daily") {
    return `每天 ${job.schedule.time || "00:00"} (${job.schedule.timezone})`;
  }
  return `每 ${job.schedule.everySeconds || 0} 秒`;
}

function cronStatusText(job: AssistantCronJob) {
  if (job.pending) {
    return "排队中";
  }
  if (job.lastStatus === "success") {
    return "成功";
  }
  if (job.lastStatus === "error") {
    return "失败";
  }
  if (job.lastStatus === "queued") {
    return "已入队";
  }
  return job.lastStatus || "未运行";
}

function summarizePrompt(prompt: string, limit = 72) {
  const value = (prompt || "").trim();
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, limit).trimEnd()}...`;
}

export function SettingsScreen({
  botAlias,
  botAvatarName,
  client = new MockWebBotClient(),
  onLogout,
  embedded = false,
  prefilledWorkdir,
  onWorkdirUpdated,
  themeName = DEFAULT_UI_THEME,
  onThemeChange,
  chatBodyFontFamily = DEFAULT_CHAT_BODY_FONT_FAMILY,
  onChatBodyFontFamilyChange,
  chatBodyFontSize = DEFAULT_CHAT_BODY_FONT_SIZE,
  onChatBodyFontSizeChange,
  chatBodyLineHeight = DEFAULT_CHAT_BODY_LINE_HEIGHT,
  onChatBodyLineHeightChange,
  chatBodyParagraphSpacing = DEFAULT_CHAT_BODY_PARAGRAPH_SPACING,
  onChatBodyParagraphSpacingChange,
  userAvatarName = readStoredUserAvatarName(),
  onUserAvatarChange,
  sessionCapabilities = [],
}: Props) {
  const [overview, setOverview] = useState<BotOverview | null>(null);
  const [cliParams, setCliParams] = useState<CliParamsPayload | null>(null);
  const [tunnel, setTunnel] = useState<TunnelSnapshot | null>(null);
  const [gitProxySettings, setGitProxySettings] = useState<GitProxySettings | null>(null);
  const [updateStatus, setUpdateStatus] = useState<AppUpdateStatus | null>(null);
  const [avatarAssets, setAvatarAssets] = useState<AvatarAsset[]>(DEFAULT_AVATAR_ASSETS);
  const [plugins, setPlugins] = useState<PluginSummary[]>([]);
  const [draftValues, setDraftValues] = useState<DraftValues>({});
  const [cliTypeDraft, setCliTypeDraft] = useState("codex");
  const [cliPathDraft, setCliPathDraft] = useState("");
  const [gitProxyPortDraft, setGitProxyPortDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [workdirDraft, setWorkdirDraft] = useState("");
  const [pendingWorkdirConflict, setPendingWorkdirConflict] = useState<WorkdirChangeConflict | null>(null);
  const [showWorkdirPicker, setShowWorkdirPicker] = useState(false);
  const [assistantCronJobs, setAssistantCronJobs] = useState<AssistantCronJob[]>([]);
  const [assistantCronRuns, setAssistantCronRuns] = useState<Record<string, AssistantCronRun[]>>({});
  const [assistantCronLoading, setAssistantCronLoading] = useState(false);
  const [assistantCronCreating, setAssistantCronCreating] = useState(false);
  const [assistantCronEditingJobId, setAssistantCronEditingJobId] = useState("");
  const [assistantCronSavingEdit, setAssistantCronSavingEdit] = useState(false);
  const [assistantCronRunningJobId, setAssistantCronRunningJobId] = useState("");
  const [assistantCronDeletingJobId, setAssistantCronDeletingJobId] = useState("");
  const [assistantCronDraftId, setAssistantCronDraftId] = useState("");
  const [assistantCronDraftTitle, setAssistantCronDraftTitle] = useState("");
  const [assistantCronDraftScheduleType, setAssistantCronDraftScheduleType] = useState<"daily" | "interval">("daily");
  const [assistantCronDraftTime, setAssistantCronDraftTime] = useState("09:00");
  const [assistantCronDraftEverySeconds, setAssistantCronDraftEverySeconds] = useState("3600");
  const [assistantCronDraftMode, setAssistantCronDraftMode] = useState<"standard" | "dream">("standard");
  const [assistantCronDraftPrompt, setAssistantCronDraftPrompt] = useState("");
  const [assistantCronDraftLookbackHours, setAssistantCronDraftLookbackHours] = useState("24");
  const [assistantCronDraftHistoryLimit, setAssistantCronDraftHistoryLimit] = useState("40");
  const [assistantCronDraftCaptureLimit, setAssistantCronDraftCaptureLimit] = useState("20");
  const [assistantCronDraftDeliverMode, setAssistantCronDraftDeliverMode] = useState<"chat_handoff" | "silent">("chat_handoff");
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [showKillConfirm, setShowKillConfirm] = useState(false);
  const [actionLoading, setActionLoading] = useState<"" | "reset" | "kill">("");
  const [savingCliParams, setSavingCliParams] = useState(false);
  const [savingCliConfig, setSavingCliConfig] = useState(false);
  const [savingWorkdir, setSavingWorkdir] = useState(false);
  const [savingGitProxy, setSavingGitProxy] = useState(false);
  const [updateAction, setUpdateAction] = useState<"" | "toggle" | "download">("");
  const [resettingCliParams, setResettingCliParams] = useState(false);
  const [tunnelAction, setTunnelAction] = useState<"" | "start" | "stop" | "restart" | "copy">("");
  const [showUpdateLog, setShowUpdateLog] = useState(false);
  const [updateLogLines, setUpdateLogLines] = useState<string[]>([]);
  const [updateLogStatus, setUpdateLogStatus] = useState<BuildLogStatus>("idle");
  const [updateLogSummary, setUpdateLogSummary] = useState("");
  const updateLogViewportRef = useRef<HTMLDivElement | null>(null);
  const isMainBot = botAlias === "main";
  const workdirLocked = overview?.botMode === "assistant";
  const isAssistantBot = overview?.botMode === "assistant";
  const isUpdateDownloading = updateAction === "download";
  const isAssistantCronEditing = assistantCronEditingJobId !== "";
  const cliParamDrafts = cliParams ? buildDraftValues(cliParams) : null;
  const hasCliParamChanges = cliParams
    ? Object.keys(cliParams.schema).some((key) =>
      hasDraftValueChanged(cliParamDrafts?.[key] ?? "", draftValues[key] ?? ""),
    )
    : false;

  const resetAssistantAutomationDraft = () => {
    setAssistantCronEditingJobId("");
    setAssistantCronDraftId("");
    setAssistantCronDraftTitle("");
    setAssistantCronDraftScheduleType("daily");
    setAssistantCronDraftTime("09:00");
    setAssistantCronDraftEverySeconds("3600");
    setAssistantCronDraftMode("standard");
    setAssistantCronDraftPrompt("");
    setAssistantCronDraftLookbackHours("24");
    setAssistantCronDraftHistoryLimit("40");
    setAssistantCronDraftCaptureLimit("20");
    setAssistantCronDraftDeliverMode("chat_handoff");
  };

  const startEditingAssistantAutomation = (job: AssistantCronJob) => {
    setError("");
    setNotice("");
    setAssistantCronEditingJobId(job.id);
    setAssistantCronDraftId(job.id);
    setAssistantCronDraftTitle(job.title);
    setAssistantCronDraftScheduleType(job.schedule.type);
    setAssistantCronDraftTime(job.schedule.time || "09:00");
    setAssistantCronDraftEverySeconds(String(job.schedule.everySeconds || 3600));
    setAssistantCronDraftMode(job.task.mode || "standard");
    setAssistantCronDraftPrompt(job.task.prompt);
    setAssistantCronDraftLookbackHours(String(job.task.lookbackHours || 24));
    setAssistantCronDraftHistoryLimit(String(job.task.historyLimit || 40));
    setAssistantCronDraftCaptureLimit(String(job.task.captureLimit || 20));
    setAssistantCronDraftDeliverMode(
      job.task.deliverMode || ((job.task.mode || "standard") === "dream" ? "silent" : "chat_handoff"),
    );
  };

  const buildAssistantAutomationPayload = () => {
    const title = assistantCronDraftTitle.trim();
    const prompt = assistantCronDraftPrompt.trim();
    const mode = assistantCronDraftMode;
    if (!title) {
      throw new Error("任务标题不能为空");
    }
    if (!prompt) {
      throw new Error("任务提示词不能为空");
    }
    const task = {
      prompt,
      mode,
      lookbackHours: Number(assistantCronDraftLookbackHours),
      historyLimit: Number(assistantCronDraftHistoryLimit),
      captureLimit: Number(assistantCronDraftCaptureLimit),
      deliverMode: assistantCronDraftDeliverMode,
    } as const;
    if (mode === "dream") {
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
    if (assistantCronDraftScheduleType === "daily") {
      const time = assistantCronDraftTime.trim();
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

    const everySeconds = Number(assistantCronDraftEverySeconds);
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
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    Promise.allSettled([
      client.getBotOverview(botAlias),
      client.getCliParams(botAlias),
      client.getTunnelStatus(),
      isMainBot ? client.getGitProxySettings() : Promise.resolve(null),
      isMainBot ? client.getUpdateStatus() : Promise.resolve(null),
      client.listPlugins(),
      client.listAvatarAssets(),
    ])
      .then(([
        overviewResult,
        cliParamsResult,
        tunnelResult,
        gitProxyResult,
        updateResult,
        pluginsResult,
        avatarAssetsResult,
      ]) => {
        if (cancelled) return;

        if (overviewResult.status !== "fulfilled") {
          setError(getErrorMessage(overviewResult.reason, "加载设置失败"));
          setLoading(false);
          return;
        }

        if (cliParamsResult.status !== "fulfilled") {
          setError(getErrorMessage(cliParamsResult.reason, "加载设置失败"));
          setLoading(false);
          return;
        }

        const overviewData = overviewResult.value;
        const cliParamsData = cliParamsResult.value;
        const tunnelData = tunnelResult.status === "fulfilled" ? tunnelResult.value : null;
        const gitProxyData = gitProxyResult.status === "fulfilled" ? gitProxyResult.value : null;
        const updateData = updateResult.status === "fulfilled" ? updateResult.value : null;
        const pluginData = pluginsResult.status === "fulfilled" ? pluginsResult.value : [];
        const avatarData = avatarAssetsResult.status === "fulfilled" && avatarAssetsResult.value.length > 0
          ? avatarAssetsResult.value
          : DEFAULT_AVATAR_ASSETS;

        setOverview(overviewData);
        setCliParams(cliParamsData);
        setAvatarAssets(avatarData);
        setDraftValues(buildDraftValues(cliParamsData));
        setCliTypeDraft(overviewData.cliType);
        setCliPathDraft(overviewData.cliPath || "");
        setWorkdirDraft(normalizePathInput(prefilledWorkdir || overviewData.workingDir));
        setTunnel(tunnelData);
        setGitProxySettings(gitProxyData);
        setGitProxyPortDraft(gitProxyData?.port || "");
        setUpdateStatus(updateData);
        setPlugins(pluginData);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(getErrorMessage(err, "加载设置失败"));
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [botAlias, client, isMainBot, prefilledWorkdir]);

  useEffect(() => {
    if (!prefilledWorkdir) {
      return;
    }
    setWorkdirDraft(normalizePathInput(prefilledWorkdir));
    setPendingWorkdirConflict(null);
  }, [prefilledWorkdir]);

  useEffect(() => {
    if (!showUpdateLog || !updateLogViewportRef.current) {
      return;
    }
    updateLogViewportRef.current.scrollTop = updateLogViewportRef.current.scrollHeight;
  }, [showUpdateLog, updateLogLines, updateLogSummary]);

  useEffect(() => {
    if (!isAssistantBot) {
      setAssistantCronJobs([]);
      setAssistantCronRuns({});
      setAssistantCronLoading(false);
      resetAssistantAutomationDraft();
      return;
    }

    let cancelled = false;
    setAssistantCronLoading(true);

    client.listAssistantCronJobs(botAlias)
      .then(async (jobs) => {
        if (cancelled) {
          return;
        }
        setAssistantCronJobs(jobs);
        const runsEntries = await Promise.all(
          jobs.map(async (job) => {
            try {
              const runs = await client.listAssistantCronRuns(botAlias, job.id, 3);
              return [job.id, runs] as const;
            } catch {
              return [job.id, []] as const;
            }
          }),
        );
        if (cancelled) {
          return;
        }
        setAssistantCronRuns(Object.fromEntries(runsEntries));
        setAssistantCronLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setAssistantCronLoading(false);
        setError(getErrorMessage(err, "加载 Automation 失败"));
      });

    return () => {
      cancelled = true;
    };
  }, [botAlias, client, isAssistantBot]);

  useEffect(() => {
    if (!isUpdateDownloading) {
      return;
    }
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [isUpdateDownloading]);

  const syncCliParams = (payload: CliParamsPayload) => {
    setCliParams(payload);
    setDraftValues(buildDraftValues(payload));
  };

  const confirmReset = async () => {
    setActionLoading("reset");
    setError("");
    setNotice("");
    try {
      await client.resetSession(botAlias);
      setNotice("当前会话已重置");
      setShowResetConfirm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置会话失败");
    } finally {
      setActionLoading("");
    }
  };

  const confirmKill = async () => {
    setActionLoading("kill");
    setError("");
    setNotice("");
    try {
      const message = await client.killTask(botAlias);
      setNotice(message || "已发送终止任务请求");
      setShowKillConfirm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "终止任务失败");
    } finally {
      setActionLoading("");
    }
  };

  const saveCliParams = async () => {
    if (!cliParams) return;
    const dirtyKeys = Object.keys(cliParams.schema).filter((key) =>
      hasDraftValueChanged(cliParamDrafts?.[key] ?? "", draftValues[key] ?? ""),
    );

    if (!dirtyKeys.length) {
      setNotice("参数未改动");
      setError("");
      return;
    }

    setSavingCliParams(true);
    setError("");
    setNotice("");
    try {
      let next = cliParams;
      for (const key of dirtyKeys) {
        const field = next.schema[key];
        if (!field) {
          continue;
        }
        next = await client.updateCliParam(
          botAlias,
          key,
          toRequestValue(field, draftValues[key] ?? ""),
        );
      }
      syncCliParams(next);
      setNotice("参数已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存参数失败");
    } finally {
      setSavingCliParams(false);
    }
  };

  const resetCurrentCliParams = async () => {
    setResettingCliParams(true);
    setError("");
    setNotice("");
    try {
      const next = await client.resetCliParams(botAlias);
      syncCliParams(next);
      setNotice("CLI 参数已恢复默认值");
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置 CLI 参数失败");
    } finally {
      setResettingCliParams(false);
    }
  };

  const saveCliConfig = async () => {
    const nextCliPath = cliPathDraft.trim();
    if (!nextCliPath) {
      setError("CLI 路径不能为空");
      return;
    }

    setSavingCliConfig(true);
    setError("");
    setNotice("");
    try {
      const nextBot = await client.updateBotCli(botAlias, cliTypeDraft, nextCliPath);
      const nextCliParams = await client.getCliParams(botAlias);
      setOverview((prev) => (prev ? { ...prev, ...nextBot } : { ...nextBot }));
      setCliTypeDraft(nextBot.cliType);
      setCliPathDraft(nextBot.cliPath || nextCliPath);
      syncCliParams(nextCliParams);
      setNotice("CLI 配置已更新");
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新 CLI 配置失败");
    } finally {
      setSavingCliConfig(false);
    }
  };

  const applyWorkdirChange = async (options: UpdateBotWorkdirOptions = {}) => {
    const nextWorkdir = normalizePathInput(workdirDraft);
    setSavingWorkdir(true);
    try {
      const nextBot = await client.updateBotWorkdir(botAlias, nextWorkdir, options);
      setOverview((prev) => (prev ? { ...prev, ...nextBot } : { ...nextBot }));
      setWorkdirDraft(nextBot.workingDir);
      setPendingWorkdirConflict(null);
      setNotice("工作目录已更新");
      onWorkdirUpdated?.(nextBot.workingDir);
    } finally {
      setSavingWorkdir(false);
    }
  };

  const saveWorkdir = async () => {
    const nextWorkdir = normalizePathInput(workdirDraft);
    if (!nextWorkdir) {
      setError("工作目录不能为空");
      return;
    }

    setError("");
    setNotice("");
    try {
      await applyWorkdirChange();
    } catch (err) {
      const clientError = asWebApiClientError(err);
      if (clientError?.code === "workdir_change_requires_reset" && clientError.data) {
        setPendingWorkdirConflict(clientError.data as WorkdirChangeConflict);
        return;
      }
      if (clientError?.code === "workdir_change_blocked_processing") {
        setPendingWorkdirConflict(null);
        setError("当前仍有任务运行，请先停止任务再切换工作目录");
        return;
      }
      setError(getErrorMessage(err, "更新工作目录失败"));
    }
  };

  const confirmWorkdirChange = async () => {
    setError("");
    setNotice("");
    try {
      await applyWorkdirChange({ forceReset: true });
    } catch (err) {
      const clientError = asWebApiClientError(err);
      if (clientError?.code === "workdir_change_requires_reset" && clientError.data) {
        setPendingWorkdirConflict(clientError.data as WorkdirChangeConflict);
        return;
      }
      if (clientError?.code === "workdir_change_blocked_processing") {
        setPendingWorkdirConflict(null);
        setError("当前仍有任务运行，请先停止任务再切换工作目录");
        return;
      }
      setError(getErrorMessage(err, "更新工作目录失败"));
    }
  };

  const reloadAssistantAutomation = async () => {
    const jobs = await client.listAssistantCronJobs(botAlias);
    setAssistantCronJobs(jobs);
    const runsEntries = await Promise.all(
      jobs.map(async (job) => {
        try {
          const runs = await client.listAssistantCronRuns(botAlias, job.id, 3);
          return [job.id, runs] as const;
        } catch {
          return [job.id, []] as const;
        }
      }),
    );
    setAssistantCronRuns(Object.fromEntries(runsEntries));
  };

  const createAssistantAutomation = async () => {
    const jobId = assistantCronDraftId.trim();
    if (!jobId) {
      setError("任务 ID 不能为空");
      return;
    }

    setAssistantCronCreating(true);
    setError("");
    setNotice("");
    try {
      const payload = buildAssistantAutomationPayload();
      await client.createAssistantCronJob(botAlias, {
        id: jobId,
        enabled: true,
        ...payload,
      });
      await reloadAssistantAutomation();
      resetAssistantAutomationDraft();
      setNotice("Automation 任务已创建");
    } catch (err) {
      setError(getErrorMessage(err, "创建 Automation 任务失败"));
    } finally {
      setAssistantCronCreating(false);
    }
  };

  const saveAssistantAutomationEdit = async () => {
    if (!assistantCronEditingJobId) {
      return;
    }

    setAssistantCronSavingEdit(true);
    setError("");
    setNotice("");
    try {
      const payload = buildAssistantAutomationPayload();
      await client.updateAssistantCronJob(botAlias, assistantCronEditingJobId, payload);
      await reloadAssistantAutomation();
      resetAssistantAutomationDraft();
      setNotice("Automation 任务已更新");
    } catch (err) {
      setError(getErrorMessage(err, "更新 Automation 任务失败"));
    } finally {
      setAssistantCronSavingEdit(false);
    }
  };

  const runAssistantAutomation = async (job: AssistantCronJob) => {
    setAssistantCronRunningJobId(job.id);
    setError("");
    setNotice("");
    try {
      const result = await client.runAssistantCronJob(botAlias, job.id);
      setAssistantCronJobs((prev) => prev.map((item) => (
        item.id === job.id
          ? { ...item, pending: true, pendingRunId: result.runId, lastStatus: result.status }
          : item
      )));
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
        setNotice(`任务已投递到聊天会话: ${result.runId}`);
      } else {
        setNotice(`Dream 任务已入队，将在后台静默执行: ${result.runId}`);
      }
      try {
        const runs = await client.listAssistantCronRuns(botAlias, job.id, 3);
        setAssistantCronRuns((prev) => ({ ...prev, [job.id]: runs }));
      } catch {
        // ignore refresh failures for mock/local fallback
      }
    } catch (err) {
      setError(getErrorMessage(err, "手动触发 Automation 失败"));
    } finally {
      setAssistantCronRunningJobId("");
    }
  };

  const deleteAssistantAutomation = async (job: AssistantCronJob) => {
    setAssistantCronDeletingJobId(job.id);
    setError("");
    setNotice("");
    try {
      await client.deleteAssistantCronJob(botAlias, job.id);
      await reloadAssistantAutomation();
      if (assistantCronEditingJobId === job.id) {
        resetAssistantAutomationDraft();
      }
      setNotice("Automation 任务已删除");
    } catch (err) {
      setError(getErrorMessage(err, "删除 Automation 任务失败"));
    } finally {
      setAssistantCronDeletingJobId("");
    }
  };

  const saveGitProxy = async () => {
    const nextPort = gitProxyPortDraft.trim();
    if (nextPort && (!/^\d+$/.test(nextPort) || Number(nextPort) < 1 || Number(nextPort) > 65535)) {
      setError("代理端口必须是 1 到 65535 之间的整数");
      return;
    }

    setSavingGitProxy(true);
    setError("");
    setNotice("");
    try {
      const nextSettings = await client.updateGitProxySettings(nextPort);
      setGitProxySettings(nextSettings);
      setGitProxyPortDraft(nextSettings.port);
      setNotice("Git 代理设置已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 Git 代理失败");
    } finally {
      setSavingGitProxy(false);
    }
  };

  const saveUpdateToggle = async (enabled: boolean) => {
    setUpdateAction("toggle");
    setError("");
    setNotice("");
    try {
      const nextStatus = await client.setUpdateEnabled(enabled);
      setUpdateStatus(nextStatus);
      setNotice(enabled ? "已启用自动下载更新" : "已关闭自动下载更新");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存更新设置失败");
    } finally {
      setUpdateAction("");
    }
  };

  const downloadUpdate = async () => {
    setUpdateAction("download");
    setError("");
    setNotice("");
    setShowUpdateLog(true);
    setUpdateLogLines([]);
    setUpdateLogStatus("running");
    setUpdateLogSummary("");
    try {
      const nextStatus = await client.downloadUpdateStream((event) => {
        if (event.message) {
          setUpdateLogLines((prev) => [...prev, event.message as string]);
        }
      });
      setUpdateStatus(nextStatus);
      setUpdateLogStatus("success");
      setUpdateLogSummary(
        nextStatus.pendingUpdateVersion
          ? `更新 ${nextStatus.pendingUpdateVersion} 已下载成功。实际解压和应用在 start.ps1 中进行。请关闭当前程序后重新运行 start.bat，不要在页面里重启程序。`
          : "更新包已下载成功。实际解压和应用在 start.ps1 中进行。请关闭当前程序后重新运行 start.bat，不要在页面里重启程序。",
      );
      setNotice("更新包下载完成，请关闭当前程序后重新运行 start.bat");
    } catch (err) {
      const message = err instanceof Error ? err.message : "下载更新失败";
      setUpdateLogStatus("error");
      setUpdateLogSummary(message);
      setError(message);
    } finally {
      setUpdateAction("");
    }
  };

  const handleThemeChange = (nextTheme: UiThemeName) => {
    if (nextTheme === themeName) {
      return;
    }
    setNotice("界面主题已切换");
    onThemeChange?.(nextTheme);
  };

  const handleChatBodyFontFamilyChange = (nextFontFamily: ChatBodyFontFamilyName) => {
    if (nextFontFamily === chatBodyFontFamily) {
      return;
    }
    setNotice("聊天正文字体已更新");
    onChatBodyFontFamilyChange?.(nextFontFamily);
  };

  const handleChatBodyFontSizeChange = (nextFontSize: ChatBodyFontSizeName) => {
    if (nextFontSize === chatBodyFontSize) {
      return;
    }
    setNotice("聊天正文字号已更新");
    onChatBodyFontSizeChange?.(nextFontSize);
  };

  const handleChatBodyLineHeightChange = (nextLineHeight: ChatBodyLineHeightName) => {
    if (nextLineHeight === chatBodyLineHeight) {
      return;
    }
    setNotice("聊天行间距已更新");
    onChatBodyLineHeightChange?.(nextLineHeight);
  };

  const handleChatBodyParagraphSpacingChange = (nextParagraphSpacing: ChatBodyParagraphSpacingName) => {
    if (nextParagraphSpacing === chatBodyParagraphSpacing) {
      return;
    }
    setNotice("聊天段间距已更新");
    onChatBodyParagraphSpacingChange?.(nextParagraphSpacing);
  };

  const runTunnelAction = async (action: "start" | "stop" | "restart") => {
    setTunnelAction(action);
    setError("");
    setNotice("");
    try {
      const next = action === "start"
        ? await client.startTunnel()
        : action === "stop"
          ? await client.stopTunnel()
          : await client.restartTunnel();
      setTunnel(next);
      setNotice(action === "restart" ? "Tunnel 已重启" : action === "start" ? "Tunnel 已启动" : "Tunnel 已停止");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tunnel 操作失败");
    } finally {
      setTunnelAction("");
    }
  };

  const updateLogStatusText = updateLogStatus === "running"
    ? "下载中"
    : updateLogStatus === "success"
      ? "下载成功"
      : updateLogStatus === "error"
        ? "下载失败"
        : "等待开始";

  const copyTunnelUrl = async () => {
    if (!tunnel?.publicUrl) return;
    setTunnelAction("copy");
    setError("");
    setNotice("");
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(tunnel.publicUrl);
      }
      setNotice("公网地址已复制");
    } catch (err) {
      setError(err instanceof Error ? err.message : "复制公网地址失败");
    } finally {
      setTunnelAction("");
    }
  };

  return (
    <main className={clsx("flex h-full min-h-0 flex-col", embedded ? "bg-[var(--surface)]" : "bg-[var(--bg)]")}>
      {embedded ? null : (
        <header className="border-b border-[var(--border)] bg-[var(--surface-strong)] p-4">
          {botAvatarName || overview?.avatarName ? (
            <BotIdentity
              alias={overview?.alias || botAlias}
              avatarName={botAvatarName || overview?.avatarName}
              size={32}
              nameClassName="truncate text-xl font-bold text-[var(--text)]"
              subtitle={<p className="text-sm text-[var(--muted)]">设置</p>}
            />
          ) : (
            <h1 className="text-xl font-bold">设置</h1>
          )}
        </header>
      )}

      <section className={clsx("flex-1 overflow-y-auto space-y-6", embedded ? "p-3" : "p-4")}>
        {loading ? (
          <div className="text-center text-[var(--muted)]">加载中...</div>
        ) : null}
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

        {botAlias === "main" ? (
          <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
            <h2 className="text-base font-semibold text-[var(--text)]">界面与阅读</h2>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {UI_THEME_OPTIONS.map((themeOption) => {
                const isActive = themeName === themeOption.value;
                return (
                  <button
                    key={themeOption.value}
                    type="button"
                    aria-label={themeOption.label}
                    aria-pressed={isActive}
                    onClick={() => handleThemeChange(themeOption.value)}
                    className={
                      isActive
                        ? "rounded-2xl border border-[var(--accent)] bg-[var(--accent-soft)] p-4 text-left shadow-sm"
                        : "rounded-2xl border border-[var(--border)] bg-[var(--bg)] p-4 text-left hover:bg-[var(--surface-strong)]"
                    }
                    >
                      <div
                        className="mb-3 rounded-2xl border p-3"
                        style={{
                          backgroundColor: themeOption.preview.surface,
                        borderColor: themeOption.preview.border,
                      }}
                    >
                      <div className="flex gap-2">
                        <span
                          className="h-3 w-8 rounded-full"
                          style={{ backgroundColor: themeOption.preview.accent }}
                        />
                        <span
                          className="h-3 w-8 rounded-full border"
                          style={{
                            backgroundColor: themeOption.preview.surface,
                            borderColor: themeOption.preview.border,
                          }}
                        />
                        <span
                          className="h-3 w-8 rounded-full"
                          style={{ backgroundColor: themeOption.preview.accentStrong }}
                        />
                      </div>
                    </div>
                    <div className="font-medium text-[var(--text)]">{themeOption.label}</div>
                  </button>
                );
              })}
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <label className="space-y-2">
                <div className="text-sm font-medium text-[var(--text)]">聊天正文字体</div>
                <select
                  aria-label="聊天正文字体"
                  value={chatBodyFontFamily}
                  onChange={(event) => handleChatBodyFontFamilyChange(event.target.value as ChatBodyFontFamilyName)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                >
                  {CHAT_BODY_FONT_FAMILY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <div className="text-sm font-medium text-[var(--text)]">聊天行间距</div>
                <select
                  aria-label="聊天行间距"
                  value={chatBodyLineHeight}
                  onChange={(event) => handleChatBodyLineHeightChange(event.target.value as ChatBodyLineHeightName)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                >
                  {CHAT_BODY_LINE_HEIGHT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <div className="text-sm font-medium text-[var(--text)]">聊天正文字号</div>
                <select
                  aria-label="聊天正文字号"
                  value={chatBodyFontSize}
                  onChange={(event) => handleChatBodyFontSizeChange(event.target.value as ChatBodyFontSizeName)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                >
                  {CHAT_BODY_FONT_SIZE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <div className="text-sm font-medium text-[var(--text)]">聊天段间距</div>
                <select
                  aria-label="聊天段间距"
                  value={chatBodyParagraphSpacing}
                  onChange={(event) => handleChatBodyParagraphSpacingChange(event.target.value as ChatBodyParagraphSpacingName)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                >
                  {CHAT_BODY_PARAGRAPH_SPACING_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        ) : null}

        <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-base font-semibold text-[var(--text)]">我的头像</h2>
            <AvatarPicker
              assets={avatarAssets}
              selectedName={userAvatarName}
              previewAlt="我的头像预览"
              selectLabel="我的头像"
              kind="user"
              onSelect={(avatarName) => {
                onUserAvatarChange?.(avatarName);
                setNotice("我的头像已更新");
              }}
            />
          </div>
        </div>

        {overview ? (
          <section
            aria-labelledby={isMainBot ? "main-bot-ops-title" : "bot-runtime-title"}
            className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 text-sm text-[var(--muted)] space-y-4"
          >
            <div className="space-y-1">
              <h2
                id={isMainBot ? "main-bot-ops-title" : "bot-runtime-title"}
                className="text-base font-semibold text-[var(--text)]"
              >
                {isMainBot ? "主 Bot 运维" : "Bot CLI 配置"}
              </h2>
              {isMainBot ? (
                <p className="text-sm text-[var(--muted)]">主 Bot 的运行配置和更新入口。</p>
              ) : null}
            </div>

            <div className="space-y-2">
              <p><span className="font-medium text-[var(--text)]">CLI:</span> {overview.cliType}</p>
              {overview.cliPath ? (
                <p className="break-all"><span className="font-medium text-[var(--text)]">CLI 路径:</span> {overview.cliPath}</p>
              ) : null}
              <p><span className="font-medium text-[var(--text)]">状态:</span> {overview.status}</p>
              <p className="break-all"><span className="font-medium text-[var(--text)]">目录:</span> {overview.workingDir}</p>
            </div>

            <div className="space-y-3 border-t border-[var(--border)] pt-4">
              <h3 className="font-medium text-[var(--text)]">运行配置</h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="space-y-1">
                  <span className="text-sm text-[var(--text)]">CLI 类型</span>
                  <select
                    aria-label="CLI 类型"
                    value={cliTypeDraft}
                    onChange={(event) => setCliTypeDraft(event.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  >
                    <option value="codex">codex</option>
                    <option value="claude">claude</option>
                  </select>
                </label>
                <label className="space-y-1">
                  <span className="text-sm text-[var(--text)]">CLI 路径</span>
                  <input
                    aria-label="CLI 路径"
                    type="text"
                    value={cliPathDraft}
                    onChange={(event) => setCliPathDraft(event.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  />
                </label>
              </div>
              <button
                type="button"
                onClick={() => void saveCliConfig()}
                disabled={savingCliConfig}
                className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
              >
                <Save className="h-4 w-4" />
                {savingCliConfig ? "保存中..." : "保存 CLI 配置"}
              </button>
            </div>

            <div className="space-y-3 border-t border-[var(--border)] pt-4">
              <div>
                <label htmlFor="bot-workdir" className="font-medium text-[var(--text)]">工作目录</label>
                {workdirLocked ? <p className="mt-1 text-xs text-[var(--muted)]">assistant 型 Bot 的默认工作目录已锁定</p> : null}
              </div>
              <div>
                <input
                  id="bot-workdir"
                  aria-label="工作目录"
                  type="text"
                  value={workdirDraft}
                  onChange={(event) => {
                    setWorkdirDraft(event.target.value);
                    if (pendingWorkdirConflict) {
                      setPendingWorkdirConflict(null);
                    }
                  }}
                  readOnly={workdirLocked}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
              </div>
              {workdirLocked ? null : (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    aria-label="浏览工作目录"
                    onClick={() => setShowWorkdirPicker(true)}
                    disabled={savingWorkdir}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    浏览目录
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveWorkdir()}
                    disabled={savingWorkdir}
                    className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
                  >
                    <Save className="h-4 w-4" />
                    {savingWorkdir ? "保存中..." : "保存工作目录"}
                  </button>
                </div>
              )}
            </div>

            {isAssistantBot ? (
              <div className="space-y-4 border-t border-[var(--border)] pt-4">
                <div className="space-y-1">
                  <h3 className="font-medium text-[var(--text)]">Automation 定时任务</h3>
                  <p className="text-xs text-[var(--muted)]">定时任务会和人工对话共用 assistant 串行执行队列。</p>
                </div>

                <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-4 space-y-3">
                  <h4 className="font-medium text-[var(--text)]">{isAssistantCronEditing ? "编辑任务" : "新建任务"}</h4>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="space-y-1">
                      <span className="text-sm text-[var(--text)]">任务 ID</span>
                      <input
                        aria-label="任务 ID"
                        type="text"
                        value={assistantCronDraftId}
                        disabled={isAssistantCronEditing}
                        onChange={(event) => setAssistantCronDraftId(event.target.value)}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-60"
                        placeholder="daily_repo_review"
                      />
                    </label>
                    <label className="space-y-1">
                      <span className="text-sm text-[var(--text)]">任务标题</span>
                      <input
                        aria-label="任务标题"
                        type="text"
                        value={assistantCronDraftTitle}
                        onChange={(event) => setAssistantCronDraftTitle(event.target.value)}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
                        placeholder="Daily Repo Review"
                      />
                    </label>
                    <label className="space-y-1">
                      <span className="text-sm text-[var(--text)]">任务模式</span>
                      <select
                        aria-label="任务模式"
                        value={assistantCronDraftMode}
                        onChange={(event) => {
                          const nextMode = event.target.value as "standard" | "dream";
                          setAssistantCronDraftMode(nextMode);
                          setAssistantCronDraftDeliverMode(nextMode === "dream" ? "silent" : "chat_handoff");
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
                        value={assistantCronDraftScheduleType}
                        onChange={(event) => setAssistantCronDraftScheduleType(event.target.value as "daily" | "interval")}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
                      >
                        <option value="daily">daily</option>
                        <option value="interval">interval</option>
                      </select>
                    </label>
                    {assistantCronDraftScheduleType === "daily" ? (
                      <label className="space-y-1">
                        <span className="text-sm text-[var(--text)]">每日时间</span>
                        <input
                          aria-label="每日时间"
                          type="text"
                          value={assistantCronDraftTime}
                          onChange={(event) => setAssistantCronDraftTime(event.target.value)}
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
                          value={assistantCronDraftEverySeconds}
                          onChange={(event) => setAssistantCronDraftEverySeconds(event.target.value)}
                          className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
                        />
                      </label>
                    )}
                  </div>

                  <label className="space-y-1 block">
                    <span className="text-sm text-[var(--text)]">任务提示词</span>
                    <textarea
                      aria-label="任务提示词"
                      rows={3}
                      value={assistantCronDraftPrompt}
                      onChange={(event) => setAssistantCronDraftPrompt(event.target.value)}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
                      placeholder="请检查当前仓库状态并输出简短日报。"
                    />
                  </label>

                  {assistantCronDraftMode === "dream" ? (
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
                            value={assistantCronDraftLookbackHours}
                            onChange={(event) => setAssistantCronDraftLookbackHours(event.target.value)}
                            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                          />
                        </label>
                        <label className="space-y-1">
                          <span className="text-sm text-[var(--text)]">聊天历史条数</span>
                          <input
                            aria-label="聊天历史条数"
                            type="number"
                            min={1}
                            value={assistantCronDraftHistoryLimit}
                            onChange={(event) => setAssistantCronDraftHistoryLimit(event.target.value)}
                            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                          />
                        </label>
                        <label className="space-y-1">
                          <span className="text-sm text-[var(--text)]">Capture 条数</span>
                          <input
                            aria-label="Capture 条数"
                            type="number"
                            min={1}
                            value={assistantCronDraftCaptureLimit}
                            onChange={(event) => setAssistantCronDraftCaptureLimit(event.target.value)}
                            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                          />
                        </label>
                        <label className="space-y-1">
                          <span className="text-sm text-[var(--text)]">投递方式</span>
                          <select
                            aria-label="投递方式"
                            value={assistantCronDraftDeliverMode}
                            onChange={(event) => setAssistantCronDraftDeliverMode(event.target.value as "chat_handoff" | "silent")}
                            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                          >
                            <option value="silent">silent</option>
                            <option value="chat_handoff">chat_handoff</option>
                          </select>
                        </label>
                      </div>
                    </div>
                  ) : null}

                  {isAssistantCronEditing ? (
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void saveAssistantAutomationEdit()}
                        disabled={assistantCronSavingEdit}
                        className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
                      >
                        <Save className="h-4 w-4" />
                        {assistantCronSavingEdit ? "保存中..." : "保存修改"}
                      </button>
                      <button
                        type="button"
                        onClick={resetAssistantAutomationDraft}
                        disabled={assistantCronSavingEdit}
                        className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        取消编辑
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void createAssistantAutomation()}
                      disabled={assistantCronCreating}
                      className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
                    >
                      <Save className="h-4 w-4" />
                      {assistantCronCreating ? "创建中..." : "创建任务"}
                    </button>
                  )}
                </div>

                {assistantCronLoading ? (
                  <p className="text-sm text-[var(--muted)]">加载 Automation...</p>
                ) : assistantCronJobs.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--muted)]">
                    暂无 Automation 任务
                  </div>
                ) : (
                  <div className="space-y-3">
                    {assistantCronJobs.map((job) => (
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
                              onClick={() => startEditingAssistantAutomation(job)}
                              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
                            >
                              编辑
                            </button>
                            <button
                              type="button"
                              aria-label={`立即运行 ${job.title}`}
                              onClick={() => void runAssistantAutomation(job)}
                              disabled={assistantCronRunningJobId === job.id}
                              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                            >
                              {assistantCronRunningJobId === job.id ? "入队中..." : "立即运行"}
                            </button>
                            <button
                              type="button"
                              aria-label={`删除 ${job.title}`}
                              onClick={() => void deleteAssistantAutomation(job)}
                              disabled={assistantCronDeletingJobId === job.id}
                              className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                            >
                              {assistantCronDeletingJobId === job.id ? "删除中..." : "删除"}
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

                        {assistantCronRuns[job.id]?.length ? (
                          <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--muted)] space-y-2">
                            <p className="font-medium text-[var(--text)]">最近运行</p>
                            {assistantCronRuns[job.id].map((run) => (
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
            ) : null}

            {isMainBot ? (
              <div className="space-y-4 border-t border-[var(--border)] pt-4">
                <h3 className="font-medium text-[var(--text)]">版本更新</h3>
                <div className="grid grid-cols-1 gap-3 text-sm text-[var(--muted)] sm:grid-cols-2">
                  <p className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                    <span className="text-[var(--text)]">当前版本</span>
                    <span>{updateStatus?.currentVersion || "未知"}</span>
                  </p>
                  <p className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                    <span className="text-[var(--text)]">可用版本</span>
                    <span>{updateStatus?.latestVersion || "暂无"}</span>
                  </p>
                </div>

                <label className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-3 text-sm text-[var(--text)]">
                  <span>自动下载更新</span>
                  <input
                    type="checkbox"
                    checked={Boolean(updateStatus?.updateEnabled)}
                    disabled={updateAction === "toggle"}
                    onChange={(event) => void saveUpdateToggle(event.target.checked)}
                    className="h-4 w-4"
                  />
                </label>

                <div className="space-y-2 text-xs text-[var(--muted)]">
                  <p>最近检查: {updateStatus?.lastCheckedAt || "未检查"}</p>
                  {updateStatus?.pendingUpdateVersion ? (
                    <p>待应用更新: {updateStatus.pendingUpdateVersion}，重启后生效</p>
                  ) : null}
                  {updateStatus?.lastError ? (
                    <p className="text-red-700">最近错误: {updateStatus.lastError}</p>
                  ) : null}
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void downloadUpdate()}
                    disabled={updateAction !== "" || !updateStatus?.latestVersion}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    {updateAction === "download" ? "下载中..." : "下载更新"}
                  </button>
                  {updateStatus?.latestReleaseUrl ? (
                    <a
                      href={updateStatus.latestReleaseUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
                    >
                      查看发布说明
                    </a>
                  ) : null}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
          <div>
            <h2 className="text-base font-semibold text-[var(--text)]">插件</h2>
            <p className="text-sm text-[var(--muted)]">检测到的宿主插件和支持格式。</p>
          </div>
          <PluginCatalog plugins={plugins} />
        </div>

        {showWorkdirPicker && !workdirLocked ? (
          <DirectoryPickerDialog
            title="选择工作目录"
            botAlias={botAlias}
            client={client}
            initialPath={workdirDraft}
            onPick={(workingDir) => {
              setWorkdirDraft(workingDir);
              setPendingWorkdirConflict(null);
            }}
            onClose={() => setShowWorkdirPicker(false)}
          />
        ) : null}

        {isMainBot ? (
          <>
            <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
              <h2 className="text-base font-semibold text-[var(--text)]">Git 代理</h2>
              <div className="flex items-center gap-2">
                <input
                  aria-label="Git 代理端口"
                  type="text"
                  inputMode="numeric"
                  value={gitProxyPortDraft}
                  onChange={(event) => setGitProxyPortDraft(event.target.value)}
                  placeholder="例如 7897"
                  className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
                <button
                  type="button"
                  onClick={() => void saveGitProxy()}
                  disabled={savingGitProxy}
                  className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
                >
                  <Save className="h-4 w-4" />
                  {savingGitProxy ? "保存中..." : "保存 Git 代理"}
                </button>
              </div>
              <p className="text-xs text-[var(--muted)]">
                当前状态: {gitProxySettings?.port ? `127.0.0.1:${gitProxySettings.port}` : "直连"}
              </p>
            </div>
          </>
        ) : null}

        {cliParams ? (
          <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-[var(--text)]">CLI 参数</h2>
                <p className="text-sm text-[var(--muted)]">当前 CLI: {cliParams.cliType}</p>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => void saveCliParams()}
                  disabled={savingCliParams || !hasCliParamChanges}
                  className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
                >
                  <Save className="h-4 w-4" />
                  {savingCliParams ? "保存中..." : "保存参数"}
                </button>
                <button
                  type="button"
                  onClick={() => void resetCurrentCliParams()}
                  disabled={resettingCliParams}
                  className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  <RefreshCw className="h-4 w-4" />
                  {resettingCliParams ? "重置中..." : "恢复默认参数"}
                </button>
              </div>
            </div>

            <div className="space-y-3">
              {Object.entries(cliParams.schema).map(([key, field]) => {
                const label = fieldLabel(key, field);
                const value = draftValues[key] ?? "";
                const inputId = `cli-param-${key}`;

                if (field.type === "boolean") {
                  return (
                    <label
                      key={key}
                      htmlFor={inputId}
                      className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm font-medium text-[var(--text)]"
                    >
                      <span>{label}</span>
                      <input
                        id={inputId}
                        aria-label={label}
                        type="checkbox"
                        checked={Boolean(value)}
                        onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.checked }))}
                        className="h-4 w-4 shrink-0"
                      />
                    </label>
                  );
                }

                return (
                  <div key={key} className="space-y-2">
                    <label htmlFor={inputId} className="block text-sm font-medium text-[var(--text)]">{label}</label>

                    {field.enum ? (
                      <select
                        id={inputId}
                        aria-label={label}
                        value={String(value)}
                        onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                      >
                        {field.enum.map((item) => (
                          <option key={item} value={item}>{item}</option>
                        ))}
                      </select>
                    ) : field.type === "string_list" ? (
                      <textarea
                        id={inputId}
                        aria-label={label}
                        rows={3}
                        value={String(value)}
                        onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                        placeholder="每行一个参数"
                      />
                    ) : (
                      <input
                        id={inputId}
                        aria-label={label}
                        type={field.type === "number" ? "number" : "text"}
                        value={String(value)}
                        onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {tunnel ? (
          <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Globe className="h-5 w-5 text-[var(--accent)]" />
                  <h2 className="text-base font-semibold text-[var(--text)]">公网访问</h2>
                </div>
                <p className="text-sm text-[var(--muted)]">状态: {tunnelStatusText(tunnel.status)}</p>
              </div>
              <span className="rounded-full bg-[var(--surface-strong)] px-3 py-1 text-xs text-[var(--muted)]">
                {tunnel.source === "manual_config" ? "手工地址" : "Quick Tunnel"}
              </span>
            </div>

            <div className="space-y-2 text-sm text-[var(--muted)]">
              <p className="break-all"><span className="font-medium text-[var(--text)]">HTTPS 访问:</span> {tunnel.publicUrl || "未建立公网地址"}</p>
              <p className="break-all"><span className="font-medium text-[var(--text)]">本地转发目标:</span> {tunnel.localUrl}</p>
              {tunnel.lastError ? (
                <p className="break-all text-red-700"><span className="font-medium">错误:</span> {tunnel.lastError}</p>
              ) : null}
            </div>

            <div className="flex flex-wrap gap-2">
              {tunnel.source !== "manual_config" ? (
                <>
                  <button
                    type="button"
                    onClick={() => void runTunnelAction("start")}
                    disabled={tunnelAction !== "" || tunnel.status === "running" || tunnel.status === "starting"}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    启动 Tunnel
                  </button>
                  <button
                    type="button"
                    onClick={() => void runTunnelAction("stop")}
                    disabled={tunnelAction !== "" || tunnel.status === "stopped"}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    停止 Tunnel
                  </button>
                  <button
                    type="button"
                    onClick={() => void runTunnelAction("restart")}
                    disabled={tunnelAction !== ""}
                    className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    <RotateCw className="h-4 w-4" />
                    重启 Tunnel
                  </button>
                </>
              ) : (
                <div className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--muted)]">
                  当前使用 `WEB_PUBLIC_URL` 手工配置地址
                </div>
              )}

              <button
                type="button"
                onClick={() => void copyTunnelUrl()}
                disabled={tunnelAction !== "" || !tunnel.publicUrl}
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                <Copy className="h-4 w-4" />
                复制公网地址
              </button>
            </div>
          </div>
        ) : null}

        <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] overflow-hidden divide-y divide-[var(--border)]">
          <button
            onClick={() => setShowKillConfirm(true)}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)] text-[var(--danger)]"
          >
            <span className="flex items-center gap-3">
              <Square className="w-5 h-5" />
              终止当前任务
            </span>
          </button>
          <button
            onClick={() => setShowResetConfirm(true)}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)] text-[var(--danger)]"
          >
            <span className="flex items-center gap-3">
              <RefreshCw className="w-5 h-5" />
              重置当前会话
            </span>
          </button>
          {embedded ? null : (
            <button
              onClick={onLogout}
              className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)]"
            >
              <span className="flex items-center gap-3">
                <LogOut className="w-5 h-5" />
                退出登录
              </span>
            </button>
          )}
        </div>
      </section>

      {pendingWorkdirConflict ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="workdir-reset-title"
        >
          <div className="w-full max-w-md rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-2xl">
            <h2 id="workdir-reset-title" className="text-base font-semibold text-[var(--text)]">
              确认切换工作目录
            </h2>
            <p className="mt-3 text-sm text-[var(--muted)]">切换工作目录会丢失当前会话。</p>
            <p className="mt-2 break-all text-sm text-[var(--text)]">
              当前目录：{pendingWorkdirConflict.currentWorkingDir}
            </p>
            <p className="break-all text-sm text-[var(--text)]">
              目标目录：{pendingWorkdirConflict.requestedWorkingDir}
            </p>
            <p className="text-sm text-[var(--muted)]">
              将清空 {pendingWorkdirConflict.historyCount} 条聊天消息。
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setPendingWorkdirConflict(null)}
                disabled={savingWorkdir}
                className="rounded-full border border-[var(--border)] px-4 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void confirmWorkdirChange()}
                disabled={savingWorkdir}
                className="rounded-full bg-[var(--danger)] px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
              >
                {savingWorkdir ? "切换中..." : "确认并切换"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showResetConfirm ? (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-[var(--surface)] rounded-2xl p-6 max-w-sm w-full shadow-[var(--shadow-card)]">
            <div className="flex items-center gap-3 text-[var(--danger)] mb-4">
              <AlertTriangle className="w-6 h-6" />
              <h2 className="text-lg font-bold">危险操作</h2>
            </div>
            <p className="text-[var(--text)] mb-6">确定要重置当前会话吗？此操作不可恢复。</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowResetConfirm(false)}
                className="px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-[var(--surface-strong)]"
              >
                取消
              </button>
              <button
                onClick={() => void confirmReset()}
                disabled={actionLoading === "reset"}
                className="px-4 py-2 rounded-lg bg-[var(--danger)] text-white hover:opacity-90"
              >
                {actionLoading === "reset" ? "重置中..." : "确定重置"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showKillConfirm ? (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-[var(--surface)] rounded-2xl p-6 max-w-sm w-full shadow-[var(--shadow-card)]">
            <div className="flex items-center gap-3 text-[var(--danger)] mb-4">
              <AlertTriangle className="w-6 h-6" />
              <h2 className="text-lg font-bold">终止任务</h2>
            </div>
            <p className="text-[var(--text)] mb-6">确定要终止当前正在运行的任务吗？</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowKillConfirm(false)}
                className="px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-[var(--surface-strong)]"
              >
                取消
              </button>
              <button
                onClick={() => void confirmKill()}
                disabled={actionLoading === "kill"}
                className="px-4 py-2 rounded-lg bg-[var(--danger)] text-white hover:opacity-90"
              >
                {actionLoading === "kill" ? "终止中..." : "确定终止"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showUpdateLog ? (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" role="dialog" aria-modal="true" aria-labelledby="update-log-title">
          <div className="bg-[var(--surface)] rounded-2xl p-6 max-w-2xl w-full shadow-[var(--shadow-card)] space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <h2 id="update-log-title" className="text-lg font-bold text-[var(--text)]">更新日志</h2>
                <p className="text-sm text-[var(--muted)]">状态: {updateLogStatusText}</p>
              </div>
              <button
                type="button"
                onClick={() => setShowUpdateLog(false)}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
              >
                关闭
              </button>
            </div>

            <div
              ref={updateLogViewportRef}
              className="h-72 overflow-y-auto rounded-xl bg-slate-950 px-4 py-3 font-mono text-xs leading-6 text-slate-100 whitespace-pre-wrap break-all"
            >
              {updateLogLines.length > 0 ? updateLogLines.join("\n") : "等待更新输出..."}
            </div>

            {updateLogSummary ? (
              <div className={updateLogStatus === "success"
                ? "rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700"
                : "rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"}
              >
                {updateLogSummary}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </main>
  );
}
