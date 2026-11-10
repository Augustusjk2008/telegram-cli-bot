import { cliTypeLabel, suggestCliPath } from "../utils/cliType";
import { startConversationAfterCliSwitch } from "../utils/conversationEvents";
import { workspaceLabel } from "../services/remoteWorkspace";
import { RemoteReconnectButton } from "../components/RemoteConnectionForm";
import { clsx } from "clsx";
import { useEffect, useRef, useState } from "react";
import { Bot, Check, Copy, Cpu, FolderOpen, LoaderCircle, MessageSquareText, Network, Plug, Save, SlidersHorizontal, X } from "lucide-react";
import { BotCliParamsPanel } from "../components/BotCliParamsPanel";
import { BotClusterSettingsPanel } from "../components/BotClusterSettingsPanel";
import { BotPromptPresetsPanel } from "../components/BotPromptPresetsPanel";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import {
  SettingsDirtyBadge,
  SettingsField,
  SettingsNotice,
  SettingsSection,
  settingsButtonClassName,
  settingsControlClassName,
  settingsPrimaryButtonClassName,
  settingsTextareaClassName,
} from "../components/SettingsSection";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError } from "../services/types";
import { copyText } from "../utils/clipboard";
import type {
  BotOverview,
  BotSummary,
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
  onRemoteConnected?: () => void;
  /** Called after a saved CLI type switch has started a new conversation, so the host can show the chat. */
  onCliSwitched?: (botAlias: string) => void;
  sessionCapabilities?: string[];
};

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
  onRemoteConnected,
  onCliSwitched,
  sessionCapabilities = [],
}: Props) {
  const [overview, setOverview] = useState<BotOverview | null>(null);
  const [peerBots, setPeerBots] = useState<BotSummary[]>([]);
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
  const [clusterDirty, setClusterDirty] = useState(false);
  const [activeSection, setActiveSection] = useState("settings-section-runtime");
  const scrollRegionRef = useRef<HTMLElement | null>(null);
  const navLockUntilRef = useRef(0);
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
    // Only feeds CLI path suggestions, so a failed list leaves the default commands in place.
    let cancelled = false;
    void Promise.resolve()
      .then(() => client.listBots())
      .then((bots) => {
        if (!cancelled) setPeerBots(bots);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [client]);

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
      if (runtimeBackendDraft === "cli" && overview && nextBot.cliType !== overview.cliType) {
        try {
          await startConversationAfterCliSwitch(client, botAlias);
          setNotice(`已切换到 ${cliTypeLabel(nextBot.cliType)}，并开启新会话`);
          onCliSwitched?.(botAlias);
        } catch (err) {
          setError(`CLI 配置已更新，但新建会话失败：${getErrorMessage(err, "未知错误")}`);
        }
      }
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

  const runtimeDirty = Boolean(overview) && (
    runtimeBackendDraft !== runtimeBackend
    || (runtimeBackendDraft === "cli"
      ? cliTypeDraft !== overview?.cliType || cliPathDraft.trim() !== (overview?.cliPath || "").trim()
      : nativeAgentDraft.piAgent.trim() !== (overview?.nativeAgent?.piAgent || "").trim()
        || (Boolean(overview?.nativeAgent?.model) && nativeAgentDraft.model.trim() !== (overview?.nativeAgent?.model || "").trim()))
  );
  const workdirDirty = Boolean(overview)
    && !overview?.remoteWorkspace
    && normalizePathInput(workdirDraft) !== normalizePathInput(overview?.workingDir || "");
  const runtimeSummary = overview
    ? nativeRuntime
      ? `原生 agent · ${overview.nativeAgent?.model || nativeAgentModels?.selectedModel || "全局默认模型"}`
      : `${cliTypeLabel(overview.cliType)} CLI`
    : "";
  const statusRunning = overview?.status === "running";
  const statusLabel = overview ? ({ running: "运行中", busy: "处理中", unread: "未读", offline: "离线" } as Record<string, string>)[overview.status] || overview.status : "";
  const navSections = [
    { id: "settings-section-runtime", label: "运行", icon: Cpu },
    { id: "settings-section-workdir", label: "目录", icon: FolderOpen },
    { id: "settings-section-cluster", label: "集群", icon: Network },
    ...(!nativeRuntime ? [{ id: "settings-section-params", label: "参数", icon: SlidersHorizontal }] : []),
    { id: "settings-section-presets", label: "预设", icon: MessageSquareText },
  ];

  const scrollToSection = (sectionId: string) => {
    const container = scrollRegionRef.current;
    const target = container?.querySelector<HTMLElement>(`[data-settings-section="${sectionId}"]`);
    if (!container || !target) return;
    setActiveSection(sectionId);
    navLockUntilRef.current = Date.now() + 800;
    container.scrollTo({ top: target.offsetTop, behavior: "smooth" });
  };

  const syncActiveSection = () => {
    const container = scrollRegionRef.current;
    if (!container || Date.now() < navLockUntilRef.current) return;
    const sections = Array.from(container.querySelectorAll<HTMLElement>("[data-settings-section]"));
    if (sections.length === 0) return;
    const atBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 4;
    let current = sections[0];
    for (const section of sections) {
      if (section.offsetTop <= container.scrollTop + 24) {
        current = section;
      }
    }
    const next = atBottom ? sections[sections.length - 1] : current;
    setActiveSection(next.dataset.settingsSection || "");
  };

  return (
    <main
      data-ui-density="compact"
      className={clsx("@container flex h-full min-h-0 flex-col text-[var(--text)]", embedded ? "bg-[var(--workbench-titlebar-bg)]" : "bg-[var(--bg)]")}
    >
      <header className="shrink-0 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)]">
        <div className={clsx("flex min-w-0 items-center gap-2.5 px-3 pb-2 pt-2.5", embedded ? "" : "mx-auto w-full max-w-3xl")}>
          <span className="relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--workbench-active-bg)] text-[var(--accent)]">
            <Bot className="h-[18px] w-[18px]" />
            {overview ? (
              <span
                aria-hidden="true"
                className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-[var(--workbench-titlebar-bg)]"
                style={{ backgroundColor: statusRunning ? "var(--status-success)" : "var(--muted)" }}
              />
            ) : null}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">当前智能体设置</p>
            <h1 className="truncate text-sm font-semibold leading-5">{overview?.alias || botAlias}</h1>
            {overview ? (
              <p className="flex min-w-0 items-center gap-1.5 text-[11px] leading-4 text-[var(--muted)]">
                <span className="shrink-0">{statusLabel}</span>
                <span aria-hidden="true">·</span>
                <span className="min-w-0 truncate">{runtimeSummary}</span>
              </p>
            ) : null}
          </div>
        </div>
        {overview ? (
          <nav aria-label="设置分区" className={clsx("flex min-w-0 gap-0.5 overflow-x-auto px-2 pb-1.5 [scrollbar-width:none]", embedded ? "" : "mx-auto w-full max-w-3xl")}>
            {navSections.map(({ id, label, icon: Icon }) => {
              const active = activeSection === id;
              return (
                <button
                  key={id}
                  type="button"
                  aria-current={active ? "true" : undefined}
                  onClick={() => scrollToSection(id)}
                  className={clsx(
                    "inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)]",
                    active
                      ? "bg-[var(--workbench-active-bg)] text-[var(--accent)]"
                      : "text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]",
                  )}
                >
                  <Icon aria-hidden="true" className="hidden h-3 w-3 @xs:block" />
                  {label}
                  {(id === "settings-section-runtime" && runtimeDirty) || (id === "settings-section-workdir" && workdirDirty) || (id === "settings-section-cluster" && clusterDirty) ? (
                    <span aria-label="有未保存更改" className="h-1.5 w-1.5 rounded-full bg-[var(--status-warning)]" />
                  ) : null}
                </button>
              );
            })}
          </nav>
        ) : null}
      </header>

      <section
        ref={scrollRegionRef}
        onScroll={syncActiveSection}
        className={clsx("relative min-h-0 flex-1 overflow-y-auto", embedded ? "bg-[var(--workbench-titlebar-bg)]" : "bg-[var(--bg)]")}
      >
        <div className={clsx("min-w-0", embedded ? "" : "mx-auto w-full max-w-3xl")}>
          {loading ? (
            <div className="flex items-center justify-center gap-2 px-3 py-10 text-xs text-[var(--muted)]">
              <LoaderCircle className="h-4 w-4 animate-spin" />
              加载中...
            </div>
          ) : null}
          {error || notice ? (
            <div className="space-y-1.5 px-3 pt-2.5">
              {error ? <SettingsNotice tone="danger">{error}</SettingsNotice> : null}
              {notice ? (
                <SettingsNotice tone="success" className="flex items-start gap-1.5">
                  <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 flex-1">{notice}</span>
                  <button type="button" aria-label="关闭提示" onClick={() => setNotice("")} className="-my-0.5 -mr-1 rounded p-0.5 opacity-70 hover:opacity-100">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </SettingsNotice>
              ) : null}
            </div>
          ) : null}

          {overview ? (
            <SettingsSection
              id="settings-section-runtime"
              titleId={isMainBot ? "main-bot-ops-title" : "bot-runtime-title"}
              icon={<Cpu className="h-3.5 w-3.5" />}
              title="运行配置"
              description={isMainBot ? "主 Bot 的运行后端与执行入口。" : "选择执行后端以及 CLI 或原生 agent 参数。"}
              badge={runtimeDirty ? <SettingsDirtyBadge /> : null}
            >
              <div className="grid gap-2 @md:grid-cols-2">
                <SettingsField label="运行后端">
                  <select
                    aria-label="运行后端"
                    value={runtimeBackendDraft}
                    disabled={!canManageBotRuntime}
                    onChange={(event) => setRuntimeBackendDraft(event.target.value as ChatExecutionMode)}
                    className={settingsControlClassName}
                  >
                    <option value="cli">CLI</option>
                    {nativeAgentOptionVisible ? <option value="native_agent">原生 agent</option> : null}
                  </select>
                </SettingsField>
                {runtimeBackendDraft === "cli" ? (
                  <>
                    <SettingsField label="CLI 类型">
                      <select
                        aria-label="CLI 类型"
                        value={cliTypeDraft}
                        disabled={!canManageBotRuntime}
                        onChange={(event) => {
                          const cliType = event.target.value as CliType;
                          setCliPathDraft(suggestCliPath(cliType, peerBots, overview ? {
                            alias: overview.alias || botAlias,
                            cliType: overview.cliType,
                            cliPath: overview.cliPath,
                          } : undefined));
                          setCliTypeDraft(cliType);
                        }}
                        className={settingsControlClassName}
                      >
                        <option value="codex">codex</option>
                        <option value="codex_server">codex server</option>
                        <option value="claude">claude</option>
                        <option value="antigravity">Antigravity CLI</option>
                        <option value="deepseek" disabled={Boolean(overview?.remoteWorkspace)}>DeepSeek Harness</option>
                      </select>
                    </SettingsField>
                    <SettingsField label="CLI 路径" className="@md:col-span-2">
                      <input
                        aria-label="CLI 路径"
                        type="text"
                        value={cliPathDraft}
                        disabled={!canManageBotRuntime}
                        onChange={(event) => setCliPathDraft(event.target.value)}
                        className={clsx(settingsControlClassName, "font-mono")}
                        placeholder={defaultCliPathForType(cliTypeDraft)}
                        spellCheck={false}
                      />
                    </SettingsField>
                  </>
                ) : (
                  <>
                    <SettingsField label="Pi agent">
                      <input
                        aria-label="Pi agent"
                        value={nativeAgentDraft.piAgent}
                        disabled={!canManageBotRuntime || savingCliConfig}
                        onChange={(event) => setNativeAgentDraft((prev) => ({ ...prev, piAgent: event.target.value }))}
                        className={settingsControlClassName}
                        placeholder="main"
                        spellCheck={false}
                      />
                    </SettingsField>
                    <SettingsField label="Native model">
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
                        className={settingsControlClassName}
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
                    </SettingsField>
                    <SettingsField label="Reasoning effort">
                      <select
                        aria-label="Reasoning effort"
                        value={nativeAgentDraft.reasoningEffort || nativeAgentModels?.selectedReasoningEffort || ""}
                        disabled={!canManageBotRuntime || savingCliConfig || nativeReasoningEffortOptions.length === 0}
                        onChange={(event) => setNativeAgentDraft((prev) => ({ ...prev, reasoningEffort: event.target.value }))}
                        className={settingsControlClassName}
                      >
                        {nativeReasoningEffortOptions.length ? nativeReasoningEffortOptions.map((effort) => (
                          <option key={effort} value={effort}>{effort}</option>
                        )) : (
                          <option value="">使用模型默认</option>
                        )}
                      </select>
                    </SettingsField>
                    <p className="text-[11px] leading-4 text-[var(--muted)] @md:col-span-2">
                      Provider、Base URL、API Key 在全局环境配置中设置。
                    </p>
                  </>
                )}
              </div>
              <div className="mt-2.5 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => void saveRuntimeConfig()}
                  disabled={!canManageBotRuntime || savingCliConfig}
                  className={settingsPrimaryButtonClassName}
                >
                  {savingCliConfig ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                  {savingCliConfig
                    ? "保存中..."
                    : runtimeBackendDraft === "native_agent" ? "保存原生 agent 配置" : "保存 CLI 配置"}
                </button>
              </div>
            </SettingsSection>
          ) : null}

          {overview ? (
            <SettingsSection
              id="settings-section-workdir"
              titleId="bot-workdir-title"
              icon={<FolderOpen className="h-3.5 w-3.5" />}
              title="工作目录"
              description={overview.remoteWorkspace ? "远程工作区目录由 SSH 连接决定。" : "智能体执行命令与读写文件的根目录。"}
              badge={workdirDirty ? <SettingsDirtyBadge /> : null}
              actions={overview.remoteWorkspace ? (
                <RemoteReconnectButton client={client} botAlias={botAlias} remote={overview.remoteWorkspace} disabled={!canConfigureBot} onConnected={() => onRemoteConnected?.()} />
              ) : null}
            >
              <div className="flex min-w-0 items-center gap-1">
                <div className="relative min-w-0 flex-1">
                  <FolderOpen aria-hidden="true" className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted)]" />
                  <input
                    id="bot-workdir"
                    aria-label="工作目录"
                    type="text"
                    value={workdirDraft}
                    title={workdirDraft}
                    onChange={(event) => {
                      setWorkdirDraft(event.target.value);
                      if (pendingWorkdirConflict) {
                        setPendingWorkdirConflict(null);
                      }
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.nativeEvent.isComposing && workdirDirty && canManageBotRuntime && !savingWorkdir) {
                        event.preventDefault();
                        void saveWorkdir();
                      }
                    }}
                    readOnly={!canManageBotRuntime || Boolean(overview.remoteWorkspace)}
                    spellCheck={false}
                    className={clsx(settingsControlClassName, "pl-7 font-mono")}
                  />
                </div>
                <button
                  type="button"
                  aria-label="浏览工作目录"
                  title="浏览目录"
                  onClick={() => setShowWorkdirPicker(true)}
                  disabled={!canManageBotRuntime || savingWorkdir || Boolean(overview.remoteWorkspace)}
                  className={clsx(settingsButtonClassName, "h-8")}
                >
                  浏览
                </button>
              </div>
              {!overview.remoteWorkspace ? (
                <div className="mt-2.5 flex items-center justify-end gap-2">
                  {workdirDirty ? (
                    <button
                      type="button"
                      onClick={() => {
                        setWorkdirDraft(normalizePathInput(overview.workingDir));
                        setPendingWorkdirConflict(null);
                      }}
                      disabled={savingWorkdir}
                      className={settingsButtonClassName}
                    >
                      还原
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void saveWorkdir()}
                    disabled={!canManageBotRuntime || savingWorkdir}
                    className={settingsPrimaryButtonClassName}
                  >
                    {savingWorkdir ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                    {savingWorkdir ? "保存中..." : "保存工作目录"}
                  </button>
                </div>
              ) : null}

              {overview.cliType === "antigravity" && overview.remoteWorkspace && overview.remoteWorkspaceMcp ? (
                <div data-testid="remote-workspace-mcp-panel" className="mt-3 space-y-2 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-2.5">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <Plug className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
                    <h3 className="min-w-0 flex-1 truncate text-xs font-semibold text-[var(--text)]">Antigravity 远程 MCP</h3>
                    <span
                      className={clsx(
                        "shrink-0 rounded-full border px-1.5 text-[10px] leading-4",
                        overview.remoteWorkspaceMcp.state === "installed"
                          ? "border-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success)]"
                          : "border-[var(--status-warning-border)] bg-[var(--status-warning-bg)] text-[var(--status-warning)]",
                      )}
                    >
                      {remoteWorkspaceMcpStateLabel(overview.remoteWorkspaceMcp.state)}
                    </span>
                  </div>
                  <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-[11px] leading-4">
                    <dt className="text-[var(--muted)]">服务</dt>
                    <dd className="min-w-0 truncate font-mono">{overview.remoteWorkspaceMcp.serverName}</dd>
                    {overview.remoteWorkspaceMcp.scope ? (
                      <>
                        <dt className="text-[var(--muted)]">范围</dt>
                        <dd className="min-w-0 truncate">{overview.remoteWorkspaceMcp.scope}</dd>
                      </>
                    ) : null}
                    {overview.remoteWorkspaceMcp.configPath ? (
                      <>
                        <dt className="text-[var(--muted)]">配置</dt>
                        <dd className="min-w-0 break-all font-mono">{overview.remoteWorkspaceMcp.configPath}</dd>
                      </>
                    ) : null}
                    {overview.remoteWorkspaceMcp.allowedTools.length ? (
                      <>
                        <dt className="text-[var(--muted)]">工具</dt>
                        <dd className="min-w-0 break-words">{overview.remoteWorkspaceMcp.allowedTools.join(", ")}</dd>
                      </>
                    ) : null}
                    {overview.remoteWorkspaceMcp.askPolicy ? (
                      <>
                        <dt className="text-[var(--muted)]">权限</dt>
                        <dd className="min-w-0 break-words">权限策略：{overview.remoteWorkspaceMcp.askPolicy}</dd>
                      </>
                    ) : null}
                  </dl>
                  {overview.remoteWorkspaceMcp.message ? <p className="text-[11px] leading-4 text-[var(--muted)]">{overview.remoteWorkspaceMcp.message}</p> : null}
                  {overview.remoteWorkspaceMcp.diagnostics?.length ? (
                    <SettingsNotice tone="danger" className="space-y-1">
                      {overview.remoteWorkspaceMcp.diagnostics.map((diagnostic, index) => (
                        <p key={`${diagnostic.code || "diagnostic"}-${index}`}>
                          {diagnostic.message}{diagnostic.action ? `：${diagnostic.action}` : ""}
                        </p>
                      ))}
                    </SettingsNotice>
                  ) : null}
                  {overview.remoteWorkspaceMcp.setupInstructions ? (
                    <p className="text-[11px] leading-4 text-[var(--muted)]">{overview.remoteWorkspaceMcp.setupInstructions}</p>
                  ) : null}
                  {([
                    ["mcp", "MCP 设置说明", "Antigravity MCP 设置说明", overview.remoteWorkspaceMcp.mcpSetupSnippet, 5],
                    ["statusLine", "statusLine 设置说明", "Antigravity statusLine 设置说明", overview.remoteWorkspaceMcp.statusLineSnippet, 2],
                  ] as const).map(([item, label, ariaLabel, snippet, rows]) => snippet ? (
                    <div key={item} className="space-y-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] font-medium text-[var(--muted)]">{label}</span>
                        <button
                          type="button"
                          onClick={() => void copyRemoteMcpText(snippet, item)}
                          className={clsx(settingsButtonClassName, "h-6 px-1.5 text-[11px]")}
                        >
                          {copiedRemoteMcpItem === item ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                          {copiedRemoteMcpItem === item ? "已复制" : "复制"}
                        </button>
                      </div>
                      <textarea
                        aria-label={ariaLabel}
                        readOnly
                        value={snippet}
                        rows={rows}
                        className={clsx(settingsTextareaClassName, "resize-none font-mono text-[11px] leading-4")}
                      />
                    </div>
                  ) : null)}
                </div>
              ) : null}
            </SettingsSection>
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

          {overview ? <BotClusterSettingsPanel botAlias={botAlias} client={client} overview={overview} canManage={canConfigureBot} onDirtyChange={setClusterDirty} /> : null}

          {overview && !nativeRuntime ? (
            <BotCliParamsPanel
              botAlias={botAlias}
              client={client}
              canManage={canConfigureBot}
              reloadKey={`${botAlias}:${overview.cliType}:${overview.cliPath || ""}`}
              variant="section"
            />
          ) : null}

          {overview ? <BotPromptPresetsPanel botAlias={botAlias} client={client} canManage={canConfigureBot} /> : null}
        </div>
      </section>

      {pendingWorkdirConflict ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay-backdrop-50)] p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="workdir-reset-title"
        >
          <div className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-2xl">
            <h2 id="workdir-reset-title" className="text-sm font-semibold text-[var(--text)]">
              确认切换工作目录
            </h2>
            <p className="mt-2 text-xs text-[var(--muted)]">切换工作目录会丢失当前会话。</p>
            <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
              <dt className="text-[var(--muted)]">当前目录</dt>
              <dd className="break-all font-mono text-[var(--text)]">{pendingWorkdirConflict.currentWorkingDir}</dd>
              <dt className="text-[var(--muted)]">目标目录</dt>
              <dd className="break-all font-mono text-[var(--text)]">{pendingWorkdirConflict.requestedWorkingDir}</dd>
            </dl>
            <p className="mt-2 text-xs text-[var(--status-warning)]">
              将清空 {pendingWorkdirConflict.historyCount} 条聊天消息。
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingWorkdirConflict(null)}
                disabled={savingWorkdir}
                className={settingsButtonClassName}
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void confirmWorkdirChange()}
                disabled={savingWorkdir}
                className="tcb-solid-danger inline-flex h-7 items-center rounded-[var(--radius-control)] px-2.5 text-xs font-medium hover:opacity-90 disabled:opacity-60"
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
