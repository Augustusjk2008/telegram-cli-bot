import { cliPathPlaceholderForType, cliTypeLabel } from "../utils/cliType";
import { workspaceLabel } from "../services/remoteWorkspace";
import { RemoteReconnectButton } from "../components/RemoteConnectionForm";
import { clsx } from "clsx";
import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { BotCliParamsPanel } from "../components/BotCliParamsPanel";
import { BotClusterSettingsPanel } from "../components/BotClusterSettingsPanel";
import { BotPromptPresetsPanel } from "../components/BotPromptPresetsPanel";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { NativeAgentConfigFields } from "../components/NativeAgentConfigFields";
import { toolbarButtonClass } from "../components/ToolbarButton";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError } from "../services/types";
import { copyText } from "../utils/clipboard";
import type {
  BotOverview,
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
type Props = {
  botAlias: string;
  client?: WebBotClient;
  /** Kept for callers compiled against the previous screen contract; the Bot settings UI does not render account actions. */
  onLogout?: () => void;
  onOpenBotManager?: () => void;
  chatEnterToSend?: boolean;
  onChatEnterToSendChange?: (enabled: boolean) => void;
  embedded?: boolean;
  prefilledWorkdir?: string;
  onWorkdirUpdated?: (workingDir: string) => void;
  sessionCapabilities?: string[];
};

function settingsPanelClass(extra = "") {
  return clsx(
    "space-y-3",
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

function remoteWorkspaceMcpStateLabel(state: string) {
  if (state === "installed") return "已配置";
  if (state === "conflict") return "配置冲突";
  if (state === "broken") return "配置损坏";
  if (state === "stale") return "需要更新";
  return "未配置";
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
  embedded = false,
  prefilledWorkdir,
  onWorkdirUpdated,
  sessionCapabilities = [],
}: Props) {
  const [overview, setOverview] = useState<BotOverview | null>(null);
  const [nativeAgentModels, setNativeAgentModels] = useState<NativeAgentModelsPayload | null>(null);
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
  const [savingCliConfig, setSavingCliConfig] = useState(false);
  const [savingWorkdir, setSavingWorkdir] = useState(false);
  const [copiedRemoteMcpItem, setCopiedRemoteMcpItem] = useState("");
  const isMainBot = botAlias === "main";
  const canManageBotRuntime = sessionCapabilities.length === 0 || sessionCapabilities.includes("manage_bots") || sessionCapabilities.includes("admin_ops");
  const canCreateWorkdirDirectory =
    sessionCapabilities.length === 0
    || sessionCapabilities.includes("create_workdir_directory")
    || sessionCapabilities.includes("manage_bots")
    || sessionCapabilities.includes("admin_ops");
  const canConfigureBot = overview ? overview.canOperate !== false : canManageBotRuntime;
  const runtimeBackend = getRuntimeBackend(overview);
  const nativeRuntime = runtimeBackend === "native_agent";
  const draftNativeRuntime = runtimeBackendDraft === "native_agent";
  const nativeAgentOptionVisible = cliTypeDraft !== "deepseek";
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
        setWorkdirDraft(overviewData.remoteWorkspace ? workspaceLabel(overviewData) : normalizePathInput(prefilledWorkdir || overviewData.workingDir));
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

  const saveRuntimeConfig = async () => {
    if (cliTypeDraft === "deepseek" && (overview?.remoteWorkspace || runtimeBackendDraft !== "cli")) {
      setError("DeepSeek Harness 目前仅支持本地 CLI");
      return;
    }
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
      if (runtimeBackendDraft === "cli" && cliTypeDraft !== "deepseek") {
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
      if (runtimeBackendDraft === "cli" && cliTypeDraft === "deepseek") {
        nextBot = await client.updateBotCli(botAlias, cliTypeDraft, nextCliPath);
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

  const copyRemoteMcpText = async (value: string, item: string) => {
    const copied = await copyText(value);
    if (copied) {
      setCopiedRemoteMcpItem(item);
      setNotice("Antigravity 设置说明已复制");
      window.setTimeout(() => setCopiedRemoteMcpItem((current) => current === item ? "" : current), 1800);
    } else {
      setError("复制失败，请检查剪贴板权限");
    }
  };

  return (
    <main data-ui-density="compact" className={clsx("flex h-full min-h-0 flex-col", embedded ? "bg-[var(--workbench-titlebar-bg)]" : "bg-[var(--bg)]")}>
      {embedded ? null : (
        <header className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] p-3">
          <h1 className="text-xl font-bold">当前智能体设置</h1>
          <p className="text-sm text-[var(--muted)]">{overview?.alias || botAlias}</p>
        </header>
      )}

      <section className={clsx("flex-1 space-y-3 overflow-y-auto", embedded ? "bg-[var(--workbench-titlebar-bg)] p-3" : "p-4")}>
        {loading ? (
          <div className="text-center text-[var(--muted)]">加载中...</div>
        ) : null}
        {error ? (
          <div className="rounded-lg border border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] px-3 py-2 text-sm text-[var(--status-danger)]">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className="rounded-lg border border-[var(--status-success-border)] bg-[var(--status-success-bg)] px-3 py-2 text-sm text-[var(--status-success)]">
            {notice}
          </div>
        ) : null}

        {overview ? (
          <section
              aria-labelledby={isMainBot ? "main-bot-ops-title" : "bot-runtime-title"}
              className={settingsPanelClass("text-sm text-[var(--muted)]")}
            >
              <div className="space-y-1">
                <h2
                  id={isMainBot ? "main-bot-ops-title" : "bot-runtime-title"}
                  className="text-base font-semibold text-[var(--text)]"
                >
                  当前智能体设置
                </h2>
                {isMainBot ? (
                  <p className="text-sm text-[var(--muted)]">主 Bot 的运行配置入口。</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <p><span className="font-medium text-[var(--text)]">运行后端:</span> {nativeRuntime ? "原生 agent" : "CLI"}</p>
                {!nativeRuntime ? <p><span className="font-medium text-[var(--text)]">CLI:</span> {cliTypeLabel(overview.cliType)}</p> : null}
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
                <p className="break-all"><span className="font-medium text-[var(--text)]">目录:</span> {workspaceLabel(overview)}</p>
              </div>

              <div className="space-y-3 border-t border-[var(--border)] pt-3">
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
                      onChange={(event) => {
                        const cliType = event.target.value as CliType;
                        if (cliType === "deepseek" || cliTypeDraft === "deepseek") setCliPathDraft(defaultCliPathForType(cliType));
                        setCliTypeDraft(cliType);
                      }}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
                    >
                      <option value="codex">codex</option>
                      <option value="codex_server">codex server</option>
                      <option value="claude">claude</option>
                      <option value="antigravity">Antigravity CLI</option>
                      <option value="deepseek" disabled={Boolean(overview?.remoteWorkspace)}>DeepSeek Harness</option>
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
                      placeholder={cliPathPlaceholderForType(cliTypeDraft)}
                    />
                    {cliTypeDraft === "deepseek" ? (
                      <span className="text-xs text-[var(--muted)]">
                        必须使用桌面版 dsh.cmd（桌面版安装目录\resources\runtime\cli\bin\dsh.cmd）；不要填写 DeepSeek Harness.exe 或 npm 目录下的 dsh.cmd。
                      </span>
                    ) : null}
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

              <div className="space-y-3 border-t border-[var(--border)] pt-3">
                <div>
                  {overview?.remoteWorkspace && <RemoteReconnectButton client={client} botAlias={botAlias} remote={overview.remoteWorkspace} disabled={!canConfigureBot} />}
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
                    readOnly={!canManageBotRuntime || Boolean(overview?.remoteWorkspace)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    aria-label="浏览工作目录"
                    onClick={() => setShowWorkdirPicker(true)}
                    disabled={!canManageBotRuntime || savingWorkdir || Boolean(overview?.remoteWorkspace)}
                    className={settingsButtonClass("plain")}
                  >
                    浏览目录
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveWorkdir()}
                    disabled={!canManageBotRuntime || savingWorkdir || Boolean(overview?.remoteWorkspace)}
                    className={settingsButtonClass("primary")}
                  >
                    <Save className="h-4 w-4" />
                    {savingWorkdir ? "保存中..." : "保存工作目录"}
                  </button>
                </div>
              </div>

              {overview?.cliType === "antigravity" && overview.remoteWorkspace && overview.remoteWorkspaceMcp ? (
                <div data-testid="remote-workspace-mcp-panel" className="space-y-3 border-t border-[var(--border)] pt-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-medium text-[var(--text)]">Antigravity 远程 MCP</h3>
                    <span className="rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted)]">
                      {remoteWorkspaceMcpStateLabel(overview.remoteWorkspaceMcp.state)}
                    </span>
                  </div>
                  <div className="space-y-1 text-sm text-[var(--muted)]">
                    <p><span className="font-medium text-[var(--text)]">服务：</span>{overview.remoteWorkspaceMcp.serverName}</p>
                    {overview.remoteWorkspaceMcp.scope ? <p><span className="font-medium text-[var(--text)]">范围：</span>{overview.remoteWorkspaceMcp.scope}</p> : null}
                    {overview.remoteWorkspaceMcp.configPath ? <p className="break-all"><span className="font-medium text-[var(--text)]">配置路径：</span>{overview.remoteWorkspaceMcp.configPath}</p> : null}
                    {overview.remoteWorkspaceMcp.message ? <p>{overview.remoteWorkspaceMcp.message}</p> : null}
                    {overview.remoteWorkspaceMcp.allowedTools.length ? (
                      <p><span className="font-medium text-[var(--text)]">工具：</span>{overview.remoteWorkspaceMcp.allowedTools.join(", ")}</p>
                    ) : null}
                  </div>
                  {overview.remoteWorkspaceMcp.diagnostics?.length ? (
                    <div className="space-y-2 rounded border border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] p-2 text-sm text-[var(--status-danger)]">
                      {overview.remoteWorkspaceMcp.diagnostics.map((diagnostic, index) => (
                        <p key={`${diagnostic.code || "diagnostic"}-${index}`}>
                          {diagnostic.message}{diagnostic.action ? `：${diagnostic.action}` : ""}
                        </p>
                      ))}
                    </div>
                  ) : null}
                  {overview.remoteWorkspaceMcp.setupInstructions ? (
                    <p className="text-sm text-[var(--muted)]">{overview.remoteWorkspaceMcp.setupInstructions}</p>
                  ) : null}
                  {overview.remoteWorkspaceMcp.askPolicy ? (
                    <p className="text-sm text-[var(--muted)]">权限策略：{overview.remoteWorkspaceMcp.askPolicy}</p>
                  ) : null}
                  {overview.remoteWorkspaceMcp.mcpSetupSnippet ? (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-[var(--text)]">MCP 设置说明</span>
                        <button
                          type="button"
                          onClick={() => void copyRemoteMcpText(overview.remoteWorkspaceMcp?.mcpSetupSnippet || "", "mcp")}
                          className={settingsButtonClass("plain")}
                        >
                          {copiedRemoteMcpItem === "mcp" ? "已复制" : "复制"}
                        </button>
                      </div>
                      <textarea
                        aria-label="Antigravity MCP 设置说明"
                        readOnly
                        value={overview.remoteWorkspaceMcp.mcpSetupSnippet}
                        rows={5}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-xs text-[var(--text)]"
                      />
                    </div>
                  ) : null}
                  {overview.remoteWorkspaceMcp.statusLineSnippet ? (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-[var(--text)]">statusLine 设置说明</span>
                        <button
                          type="button"
                          onClick={() => void copyRemoteMcpText(overview.remoteWorkspaceMcp?.statusLineSnippet || "", "statusLine")}
                          className={settingsButtonClass("plain")}
                        >
                          {copiedRemoteMcpItem === "statusLine" ? "已复制" : "复制"}
                        </button>
                      </div>
                      <textarea
                        aria-label="Antigravity statusLine 设置说明"
                        readOnly
                        value={overview.remoteWorkspaceMcp.statusLineSnippet}
                        rows={2}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-xs text-[var(--text)]"
                      />
                    </div>
                  ) : null}
                </div>
              ) : null}
          </section>
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

        {overview ? <BotClusterSettingsPanel botAlias={botAlias} client={client} overview={overview} canManage={canConfigureBot} /> : null}

        {overview && !nativeRuntime ? (
          <BotCliParamsPanel
            botAlias={botAlias}
            client={client}
            canManage={canConfigureBot}
            reloadKey={`${botAlias}:${overview.cliType}:${overview.cliPath || ""}`}
          />
        ) : null}

        {overview ? <BotPromptPresetsPanel botAlias={botAlias} client={client} canManage={canConfigureBot} /> : null}
      </section>

      {pendingWorkdirConflict ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay-backdrop-50)] p-4"
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

    </main>
  );
}
