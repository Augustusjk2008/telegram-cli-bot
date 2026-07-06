import { clsx } from "clsx";
import { useEffect, useState } from "react";
import { AlertTriangle, Bell, LogOut, Save, SlidersHorizontal, Square } from "lucide-react";
import { AgentSettingsPanel } from "../components/AgentSettingsPanel";
import { AiInlineCompletionSettingsPanel } from "../components/AiInlineCompletionSettingsPanel";
import { BotCliParamsPanel } from "../components/BotCliParamsPanel";
import { ClusterSetupPanel } from "../components/ClusterSetupPanel";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { NativeAgentConfigFields } from "../components/NativeAgentConfigFields";
import { ThemeDropdown } from "../components/ThemeDropdown";
import { toolbarButtonClass } from "../components/ToolbarButton";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError } from "../services/types";
import type {
  BotOverview,
  BrowserNotificationPermission,
  ChatExecutionMode,
  CliType,
  NativeAgentDraft,
  NativeAgentModelsPayload,
  UpdateBotWorkdirOptions,
  WorkdirChangeConflict,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getErrorMessage } from "../utils/errorMessage";
import { normalizePathInput } from "../utils/pathInput";
import { defaultCliPathForType } from "./useBotManager";
import {
  buildExecutionConfig,
  DEFAULT_NATIVE_AGENT_DRAFT,
  getRuntimeBackend,
} from "./botManagerModel";
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
  type ChatBodyFontFamilyName,
  type ChatBodyFontSizeName,
  type ChatBodyLineHeightName,
  type ChatBodyParagraphSpacingName,
  type UiThemeName,
} from "../theme";
import {
  getBrowserNotificationPermission,
  readChatCompletionWebNotificationEnabled,
  requestBrowserNotificationPermission,
  writeChatCompletionWebNotificationEnabled,
} from "../utils/chatNotificationEvents";

type Props = {
  botAlias: string;
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
  sessionCapabilities?: string[];
  showBotRuntimeSettings?: boolean;
  onOpenBotManager?: () => void;
};

function settingsPanelClass(extra = "") {
  return clsx(
    "rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-4 shadow-[var(--shadow-soft)]",
    extra,
  );
}

function settingsActionPanelClass(extra = "") {
  return clsx(
    "overflow-hidden rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] shadow-[var(--shadow-soft)]",
    extra,
  );
}

function settingsButtonClass(kind: "plain" | "primary" | "danger" = "plain", extra = "") {
  if (kind === "danger") {
    return toolbarButtonClass("danger", "md", extra);
  }
  return toolbarButtonClass(kind, "md", extra);
}

function nativeAgentDraftFromOverview(overview?: Pick<BotOverview, "nativeAgent"> | null): NativeAgentDraft {
  return {
    ...DEFAULT_NATIVE_AGENT_DRAFT,
    ...(overview?.nativeAgent || {}),
    apiKey: "",
    clearApiKey: false,
  };
}

function normalizeNativeAgentDraft(draft: NativeAgentDraft) {
  return {
    ...DEFAULT_NATIVE_AGENT_DRAFT,
    ...draft,
    provider: "",
    model: draft.model.trim(),
    piAgent: draft.piAgent.trim(),
    baseUrl: "",
    apiKey: "",
    clearApiKey: false,
    reasoningEffort: draft.reasoningEffort?.trim(),
  };
}

function notificationPermissionText(permission: BrowserNotificationPermission) {
  if (permission === "granted") return "已允许";
  if (permission === "denied") return "已拒绝";
  if (permission === "unsupported") return "浏览器不支持";
  return "未询问";
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

export function SettingsScreen({
  botAlias,
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
  sessionCapabilities = [],
  showBotRuntimeSettings = true,
  onOpenBotManager,
}: Props) {
  const [overview, setOverview] = useState<BotOverview | null>(null);
  const [nativeAgentModels, setNativeAgentModels] = useState<NativeAgentModelsPayload | null>(null);
  const [notificationEnabled, setNotificationEnabled] = useState(() => readChatCompletionWebNotificationEnabled());
  const [notificationPermission, setNotificationPermission] = useState<BrowserNotificationPermission>(() => getBrowserNotificationPermission());
  const [runtimeBackendDraft, setRuntimeBackendDraft] = useState<ChatExecutionMode>("cli");
  const [cliTypeDraft, setCliTypeDraft] = useState<CliType>("codex");
  const [cliPathDraft, setCliPathDraft] = useState("");
  const [nativeAgentDraft, setNativeAgentDraft] = useState<NativeAgentDraft>(() => ({ ...DEFAULT_NATIVE_AGENT_DRAFT }));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [workdirDraft, setWorkdirDraft] = useState("");
  const [pendingWorkdirConflict, setPendingWorkdirConflict] = useState<WorkdirChangeConflict | null>(null);
  const [showWorkdirPicker, setShowWorkdirPicker] = useState(false);
  const [showKillConfirm, setShowKillConfirm] = useState(false);
  const [actionLoading, setActionLoading] = useState<"" | "kill">("");
  const [savingCliConfig, setSavingCliConfig] = useState(false);
  const [savingWorkdir, setSavingWorkdir] = useState(false);
  const [requestingNotificationPermission, setRequestingNotificationPermission] = useState(false);
  const isMainBot = botAlias === "main";
  const canManageBotRuntime = sessionCapabilities.length === 0 || sessionCapabilities.includes("manage_bots") || sessionCapabilities.includes("admin_ops");
  const canCreateWorkdirDirectory =
    sessionCapabilities.length === 0
    || sessionCapabilities.includes("create_workdir_directory")
    || sessionCapabilities.includes("manage_bots")
    || sessionCapabilities.includes("admin_ops");
  const canConfigureBot = overview ? overview.canOperate !== false : canManageBotRuntime;
  const canManageInlineCompletion = sessionCapabilities.length === 0 || sessionCapabilities.includes("admin_ops");
  const runtimeBackend = getRuntimeBackend(overview);
  const nativeRuntime = runtimeBackend === "native_agent";
  const draftNativeRuntime = runtimeBackendDraft === "native_agent";
  const nativeAgentOptionVisible = true;
  const nativeSelectedModel = nativeAgentDraft.model || nativeAgentModels?.selectedModel || "";
  const nativeSelectedModelItem = nativeAgentModels?.items.find((item) => item.id === nativeSelectedModel);
  const nativeReasoningEffortOptions = nativeSelectedModelItem?.reasoningEfforts || [];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    Promise.allSettled([
      client.getBotOverview(botAlias),
    ])
      .then(([overviewResult]) => {
        if (cancelled) return;

        if (overviewResult.status !== "fulfilled") {
          setError(getErrorMessage(overviewResult.reason, "加载设置失败"));
          setLoading(false);
          return;
        }

        const overviewData = overviewResult.value;

        setOverview(overviewData);
        setCliTypeDraft(overviewData.cliType);
        setCliPathDraft(overviewData.cliPath || "");
        setRuntimeBackendDraft(getRuntimeBackend(overviewData));
        setNativeAgentDraft(nativeAgentDraftFromOverview(overviewData));
        setWorkdirDraft(normalizePathInput(prefilledWorkdir || overviewData.workingDir));
        setNotificationPermission(getBrowserNotificationPermission());
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
  }, [botAlias, client, prefilledWorkdir]);

  useEffect(() => {
    if (!nativeRuntime && !draftNativeRuntime) {
      setNativeAgentModels(null);
      return;
    }
    let cancelled = false;
    void client.getNativeAgentModels(botAlias)
      .then((models) => {
        if (!cancelled) {
          setNativeAgentModels(models);
          setNativeAgentDraft((prev) => ({
            ...prev,
            model: prev.model || models.selectedModel || models.items[0]?.id || "",
            reasoningEffort: prev.reasoningEffort || models.selectedReasoningEffort || models.items[0]?.defaultReasoningEffort || "",
          }));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setNativeAgentModels(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [botAlias, client, nativeRuntime, draftNativeRuntime]);

  useEffect(() => {
    if (!prefilledWorkdir) {
      return;
    }
    setWorkdirDraft(normalizePathInput(prefilledWorkdir));
    setPendingWorkdirConflict(null);
  }, [prefilledWorkdir]);

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

  const saveRuntimeConfig = async () => {
    const nextCliPath = cliPathDraft.trim();
    if (runtimeBackendDraft === "cli" && !nextCliPath) {
      setError("CLI 路径不能为空");
      return;
    }

    setSavingCliConfig(true);
    setError("");
    setNotice("");
    try {
      let nextBot = overview;
      if (runtimeBackendDraft === "cli") {
        nextBot = await client.updateBotCli(botAlias, cliTypeDraft, nextCliPath);
      }
      const normalizedNativeAgent = normalizeNativeAgentDraft(nativeAgentDraft);
      const executionChanged =
        runtimeBackend !== runtimeBackendDraft
        || (overview?.nativeAgent?.piAgent || "").trim() !== normalizedNativeAgent.piAgent;
      const nativeModelChanged =
        (overview?.nativeAgent?.model || "").trim() !== normalizedNativeAgent.model
        || (overview?.nativeAgent?.reasoningEffort || "").trim() !== (normalizedNativeAgent.reasoningEffort || "");
      if (executionChanged || (runtimeBackendDraft === "native_agent" && nativeModelChanged)) {
        const executionConfig = buildExecutionConfig(runtimeBackendDraft);
        nextBot = await client.updateBotExecutionConfig(botAlias, {
          supportedExecutionModes: executionConfig.supportedExecutionModes,
          defaultExecutionMode: executionConfig.defaultExecutionMode,
          nativeAgent: normalizedNativeAgent,
        });
      }
      if (!nextBot) {
        throw new Error("更新运行配置失败");
      }
      setOverview((prev) => (prev ? { ...prev, ...nextBot } : { ...nextBot }));
      setCliTypeDraft(nextBot.cliType);
      setCliPathDraft(nextBot.cliPath || nextCliPath);
      setRuntimeBackendDraft(getRuntimeBackend(nextBot));
      setNativeAgentDraft(nativeAgentDraftFromOverview(nextBot));
      setNotice(runtimeBackendDraft === "native_agent" ? "原生 agent 配置已更新" : "CLI 配置已更新");
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新运行配置失败");
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

  const handleThemeChange = (nextTheme: UiThemeName) => {
    if (nextTheme === themeName) {
      return;
    }
    setNotice("界面主题已切换");
    onThemeChange?.(nextTheme);
  };

  const handleNotificationToggle = (enabled: boolean) => {
    setNotificationEnabled(enabled);
    writeChatCompletionWebNotificationEnabled(enabled);
    setNotice(enabled ? "聊天完成通知已开启" : "聊天完成通知已关闭");
  };

  const requestNotificationPermission = async () => {
    setRequestingNotificationPermission(true);
    setError("");
    setNotice("");
    try {
      const nextPermission = await requestBrowserNotificationPermission();
      setNotificationPermission(nextPermission);
      if (nextPermission === "granted") {
        handleNotificationToggle(true);
      } else if (nextPermission === "denied") {
        setNotice("浏览器已拒绝通知权限");
      } else if (nextPermission === "unsupported") {
        setNotice("当前浏览器不支持通知");
      }
    } finally {
      setRequestingNotificationPermission(false);
    }
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

  return (
    <main className={clsx("flex h-full min-h-0 flex-col", embedded ? "bg-[var(--workbench-titlebar-bg)]" : "bg-[var(--bg)]")}>
      {embedded ? null : (
        <header className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] p-4">
          <h1 className="text-xl font-bold">设置</h1>
          <p className="text-sm text-[var(--muted)]">{overview?.alias || botAlias}</p>
        </header>
      )}

      <section className={clsx("flex-1 overflow-y-auto space-y-4", embedded ? "bg-[var(--workbench-titlebar-bg)] p-3" : "p-4")}>
        {loading ? (
          <div className="text-center text-[var(--muted)]">加载中...</div>
        ) : null}
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

        <div className={settingsPanelClass("space-y-4")}>
          <h2 className="text-base font-semibold text-[var(--text)]">界面与阅读</h2>

          <div className="space-y-2">
            <div className="text-sm font-medium text-[var(--text)]">界面主题</div>
            <ThemeDropdown value={themeName} onChange={handleThemeChange} />
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

        <div className={settingsPanelClass("space-y-4")}>
          <div className="flex items-center gap-2">
            <Bell className="h-5 w-5 text-[var(--accent)]" />
            <h2 className="text-base font-semibold text-[var(--text)]">通知</h2>
          </div>

          <label className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
            <span className="text-sm text-[var(--text)]">聊天完成网页通知</span>
            <input
              aria-label="聊天完成网页通知"
              type="checkbox"
              checked={notificationEnabled}
              onChange={(event) => handleNotificationToggle(event.target.checked)}
              className="h-4 w-4"
            />
          </label>

          <div className="grid grid-cols-1 gap-3 text-sm text-[var(--muted)] sm:grid-cols-2">
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
              浏览器权限: <span className="font-medium text-[var(--text)]">{notificationPermissionText(notificationPermission)}</span>
            </div>
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
              本地开关: <span className="font-medium text-[var(--text)]">{notificationEnabled ? "已开启" : "已关闭"}</span>
            </div>
          </div>

          <div className="flex flex-col items-start gap-2">
            <button
              type="button"
              onClick={() => void requestNotificationPermission()}
              disabled={requestingNotificationPermission || notificationPermission === "unsupported"}
              className={settingsButtonClass("plain")}
            >
              <Bell className="h-4 w-4" />
              {requestingNotificationPermission ? "请求中..." : "请求浏览器通知权限"}
            </button>
          </div>
        </div>

        {canManageInlineCompletion ? (
          <AiInlineCompletionSettingsPanel
            client={client}
            onSaved={() => {
              setError("");
              setNotice("AI inline 补全配置已保存");
            }}
            onError={(message) => {
              setNotice("");
              setError(message);
            }}
          />
        ) : null}

        {overview ? (
          showBotRuntimeSettings ? (
            <section
              aria-labelledby={isMainBot ? "main-bot-ops-title" : "bot-runtime-title"}
              className={settingsPanelClass("space-y-4 text-sm text-[var(--muted)]")}
            >
              <div className="space-y-1">
                <h2
                  id={isMainBot ? "main-bot-ops-title" : "bot-runtime-title"}
                  className="text-base font-semibold text-[var(--text)]"
                >
                  {isMainBot ? "主 Bot 运维" : "Bot 运行配置"}
                </h2>
                {isMainBot ? (
                  <p className="text-sm text-[var(--muted)]">主 Bot 的运行配置入口。</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <p><span className="font-medium text-[var(--text)]">运行后端:</span> {nativeRuntime ? "原生 agent" : "CLI"}</p>
                {!nativeRuntime ? <p><span className="font-medium text-[var(--text)]">CLI:</span> {overview.cliType}</p> : null}
                {!nativeRuntime && overview.cliPath ? (
                  <p className="break-all"><span className="font-medium text-[var(--text)]">CLI 路径:</span> {overview.cliPath}</p>
                ) : null}
                {nativeRuntime ? (
                  <p>
                    <span className="font-medium text-[var(--text)]">Model:</span>{" "}
                    {overview.nativeAgent?.model || nativeAgentModels?.selectedModel || "使用全局默认"}
                  </p>
                ) : null}
                {nativeRuntime && (overview.nativeAgent?.reasoningEffort || nativeAgentModels?.selectedReasoningEffort) ? (
                  <p>
                    <span className="font-medium text-[var(--text)]">Reasoning:</span>{" "}
                    {overview.nativeAgent?.reasoningEffort || nativeAgentModels?.selectedReasoningEffort}
                  </p>
                ) : null}
                {nativeRuntime ? <p><span className="font-medium text-[var(--text)]">Pi agent:</span> {overview.nativeAgent?.piAgent || "未设置"}</p> : null}
                <p><span className="font-medium text-[var(--text)]">状态:</span> {overview.status}</p>
                <p className="break-all"><span className="font-medium text-[var(--text)]">目录:</span> {overview.workingDir}</p>
              </div>

              {nativeRuntime && onOpenBotManager ? (
                <button
                  type="button"
                  onClick={onOpenBotManager}
                  className={settingsButtonClass("plain")}
                >
                  <SlidersHorizontal className="h-4 w-4" />
                  查看管理中心
                </button>
              ) : null}

              <div className="space-y-3 border-t border-[var(--border)] pt-4">
                <h3 className="font-medium text-[var(--text)]">运行配置</h3>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label className="space-y-1">
                    <span className="text-sm text-[var(--text)]">运行后端</span>
                    <select
                      aria-label="运行后端"
                      value={runtimeBackendDraft}
                      disabled={!canManageBotRuntime}
                      onChange={(event) => setRuntimeBackendDraft(event.target.value as ChatExecutionMode)}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
                    >
                      <option value="cli">CLI</option>
                      {nativeAgentOptionVisible ? <option value="native_agent">原生 agent</option> : null}
                    </select>
                  </label>
                </div>

                {runtimeBackendDraft === "cli" ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="space-y-1">
                    <span className="text-sm text-[var(--text)]">CLI 类型</span>
                    <select
                      aria-label="CLI 类型"
                      value={cliTypeDraft}
                      disabled={!canManageBotRuntime}
                      onChange={(event) => setCliTypeDraft(event.target.value as CliType)}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
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
                      disabled={!canManageBotRuntime}
                      onChange={(event) => setCliPathDraft(event.target.value)}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
                      placeholder={defaultCliPathForType(cliTypeDraft)}
                    />
                  </label>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <label className="space-y-1">
                        <span className="text-sm text-[var(--text)]">Native model</span>
                        <select
                          aria-label="Native model"
                          value={nativeSelectedModel}
                          disabled={!canManageBotRuntime || savingCliConfig || !nativeAgentModels?.items.length}
                          onChange={(event) => {
                            const selected = nativeAgentModels?.items.find((item) => item.id === event.target.value);
                            setNativeAgentDraft((prev) => ({
                              ...prev,
                              model: event.target.value,
                              reasoningEffort: selected?.defaultReasoningEffort || selected?.reasoningEfforts?.[0] || "",
                            }));
                          }}
                          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
                        >
                          {nativeSelectedModel && !nativeAgentModels?.items.some((model) => model.id === nativeSelectedModel) ? (
                            <option value={nativeSelectedModel}>{nativeSelectedModel}</option>
                          ) : null}
                          {nativeAgentModels?.items.length ? nativeAgentModels.items.map((model) => (
                            <option key={model.id} value={model.id}>{model.label || model.id}</option>
                          )) : (
                            <option value="">使用全局默认</option>
                          )}
                        </select>
                      </label>
                      <label className="space-y-1">
                        <span className="text-sm text-[var(--text)]">Reasoning effort</span>
                        <select
                          aria-label="Reasoning effort"
                          value={nativeAgentDraft.reasoningEffort || nativeAgentModels?.selectedReasoningEffort || ""}
                          disabled={!canManageBotRuntime || savingCliConfig || nativeReasoningEffortOptions.length === 0}
                          onChange={(event) => setNativeAgentDraft((prev) => ({ ...prev, reasoningEffort: event.target.value }))}
                          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
                        >
                          {nativeReasoningEffortOptions.length ? nativeReasoningEffortOptions.map((effort) => (
                            <option key={effort} value={effort}>{effort}</option>
                          )) : (
                            <option value="">使用模型默认</option>
                          )}
                        </select>
                      </label>
                    </div>
                    <NativeAgentConfigFields
                      provider={nativeAgentDraft.provider}
                      model={nativeAgentDraft.model}
                      piAgent={nativeAgentDraft.piAgent}
                      baseUrl={nativeAgentDraft.baseUrl}
                      apiKey={nativeAgentDraft.apiKey}
                      hasApiKey={nativeAgentDraft.hasApiKey}
                      apiKeyMasked={nativeAgentDraft.apiKeyMasked}
                      clearApiKey={nativeAgentDraft.clearApiKey}
                      editing
                      disabled={!canManageBotRuntime || savingCliConfig}
                      onNativeAgentChange={(patch) => setNativeAgentDraft((prev) => ({
                        ...prev,
                        ...patch,
                      }))}
                    />
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => void saveRuntimeConfig()}
                  disabled={!canManageBotRuntime || savingCliConfig}
                  className={settingsButtonClass("primary")}
                >
                  <Save className="h-4 w-4" />
                  {savingCliConfig
                    ? "保存中..."
                    : runtimeBackendDraft === "native_agent" ? "保存原生 agent 配置" : "保存 CLI 配置"}
                </button>
              </div>

              <div className="space-y-3 border-t border-[var(--border)] pt-4">
                <div>
                  <label htmlFor="bot-workdir" className="font-medium text-[var(--text)]">工作目录</label>
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
                    readOnly={!canManageBotRuntime}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    aria-label="浏览工作目录"
                    onClick={() => setShowWorkdirPicker(true)}
                    disabled={!canManageBotRuntime || savingWorkdir}
                    className={settingsButtonClass("plain")}
                  >
                    浏览目录
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveWorkdir()}
                    disabled={!canManageBotRuntime || savingWorkdir}
                    className={settingsButtonClass("primary")}
                  >
                    <Save className="h-4 w-4" />
                    {savingWorkdir ? "保存中..." : "保存工作目录"}
                  </button>
                </div>
              </div>
            </section>
          ) : null
        ) : null}

        {showWorkdirPicker ? (
          <DirectoryPickerDialog
            title="选择工作目录"
            botAlias={botAlias}
            client={client}
            initialPath={workdirDraft}
            mutateBrowseState={false}
            mode="workdir"
            canCreateDirectory={canCreateWorkdirDirectory}
            onPick={(workingDir) => {
              setWorkdirDraft(workingDir);
              setPendingWorkdirConflict(null);
            }}
            onClose={() => setShowWorkdirPicker(false)}
          />
        ) : null}

        {overview && showBotRuntimeSettings && nativeRuntime ? (
          <ClusterSetupPanel
            botAlias={botAlias}
            client={client}
            canManage={canConfigureBot}
          />
        ) : null}

        {overview && showBotRuntimeSettings ? (
          <AgentSettingsPanel
            botAlias={botAlias}
            client={client}
            canManage={canManageBotRuntime}
          />
        ) : null}

        {overview && showBotRuntimeSettings && !nativeRuntime ? (
          <BotCliParamsPanel
            botAlias={botAlias}
            client={client}
            canManage={canConfigureBot}
            reloadKey={`${botAlias}:${overview.cliType}:${overview.cliPath || ""}`}
          />
        ) : null}

        <div className={settingsActionPanelClass("divide-y divide-[var(--workbench-hairline)]")}>
          <button
            onClick={() => setShowKillConfirm(true)}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--workbench-hover-bg)] active:bg-[var(--workbench-active-bg)] text-[var(--danger)]"
          >
            <span className="flex items-center gap-3">
              <Square className="w-5 h-5" />
              终止当前任务
            </span>
          </button>
          {embedded ? null : (
            <button
              onClick={onLogout}
              className="w-full flex items-center justify-between p-4 hover:bg-[var(--workbench-hover-bg)] active:bg-[var(--workbench-active-bg)]"
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
                className="tcb-solid-danger rounded-full px-4 py-2 text-sm hover:opacity-90 disabled:opacity-60"
              >
                {savingWorkdir ? "切换中..." : "确认并切换"}
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
                className="tcb-solid-danger px-4 py-2 rounded-lg hover:opacity-90"
              >
                {actionLoading === "kill" ? "终止中..." : "确定终止"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

    </main>
  );
}
