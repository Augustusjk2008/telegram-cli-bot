import { cliTypeLabel } from "../utils/cliType";
import { RemoteWorkspacePicker } from "../components/RemoteWorkspacePicker";
import { RemoteReconnectButton } from "../components/RemoteConnectionForm";
import { workspaceLabel } from "../services/remoteWorkspace";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { clsx } from "clsx";
import {
  CheckSquare,
  Archive,
  ArchiveRestore,
  FolderOpen,
  LogIn,
  LogOut,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  Square,
  Trash2,
  Undo2,
} from "lucide-react";
import { BotCliParamsPanel } from "../components/BotCliParamsPanel";
import { BotActivitySummary } from "../components/BotActivitySummary";
import { ClusterModelTiersPanel } from "../components/ClusterModelTiersPanel";
import { ClusterSetupPanel } from "../components/ClusterSetupPanel";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { NativeAgentConfigFields } from "../components/NativeAgentConfigFields";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { clusterDraftEquals } from "../utils/clusterDraft";
import { WebApiClientError } from "../services/types";
import { getBotIdentityTextStyle } from "../utils/botVisual";
import { AgentCreateForm } from "./AgentCreateForm";
import { FleetAvatar, FleetStats, FleetStatusChip } from "./AgentManagerParts";
import "../styles/agent-manager.css";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";
import type {
  BotClusterConfig,
  BotSummary,
  ChatExecutionMode,
  CliType,
  CliParamsPayload,
  ClusterResizeBlockedData,
  ClusterResizeBlocker,
  ClusterStatus,
  NativeAgentModelsPayload,
  UpdateBotWorkdirOptions,
  WorkdirChangeConflict,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  buildBulkActionPlan,
  countBotManagerStats,
  DEFAULT_NATIVE_AGENT_DRAFT,
  detectBotIssues,
  draftFromBot,
  getRuntimeBackend,
  getBotManagerStatus,
  getVisibleManagedBots,
  isBotOffline,
  isBotArchived,
  isMainBot,
  isNativeAgentGloballyEnabled,
  type BulkAction,
  type BulkActionResult,
  type EditDraft,
  type ManagerViewFilter,
} from "./botManagerModel";
import { defaultCliPathForType, useBotManager } from "./useBotManager";

type Props = {
  client?: WebBotClient;
  currentAlias: string | null;
  onSelect: (alias: string) => void;
  onLogout?: () => void;
  onBotsChange?: (bots: BotSummary[]) => void;
  canManage?: boolean;
  canCreateWorkdirDirectory?: boolean;
  canRunUnsafeCli?: boolean;
};

type Mode = "inspect" | "create";
type InspectorTab = "overview" | "config";

const LIST_MIN_WIDTH = 520;
const RESIZER_WIDTH = 8;
const INSPECTOR_MIN_WIDTH = 320;
const INSPECTOR_MAX_WIDTH = 720;
const INSPECTOR_DEFAULT_WIDTH = 400;
const DELETE_WORKSPACE_CONFIRM_TEXT = "永久删除";
const DEFAULT_CLUSTER_CONFIG: BotClusterConfig = {
  enabled: false,
  writePolicy: "all_agents",
  maxParallelAgents: 3,
  defaultTimeoutSeconds: 1800,
  modelTiers: { low: "", medium: "", high: "", professional: "" },
  reasoningEfforts: { low: "", medium: "", high: "", professional: "" },
};

const STATUS_FILTERS: Array<{ id: ManagerViewFilter; label: string }> = [
  { id: "all", label: "全部" },
  { id: "unread", label: "未读" },
  { id: "running", label: "运行中" },
  { id: "busy", label: "处理中" },
  { id: "offline", label: "离线" },
  { id: "archived", label: "已归档" },
  { id: "attention", label: "需处理" },
];

function managerPillStatus(bot: BotSummary) {
  const status = getBotManagerStatus(bot);
  return status === "unread" ? "online" : status;
}

function normalizeEditDraft(draft: EditDraft): EditDraft {
  const providerInput = draft.nativeAgent.provider.trim();
  const providerLooksLikeUrl = /^https?:\/\//i.test(providerInput);
  const baseUrlInput = draft.nativeAgent.baseUrl.trim();
  return {
    alias: draft.alias.trim(),
    cliType: draft.cliType,
    cliPath: draft.cliPath.trim(),
    workingDir: draft.workingDir.trim(),
    remoteWorkspace: draft.remoteWorkspace,
    runtimeBackend: draft.runtimeBackend,
    nativeAgent: {
      ...DEFAULT_NATIVE_AGENT_DRAFT,
      ...draft.nativeAgent,
      provider: providerLooksLikeUrl ? "codeflow" : providerInput,
      model: draft.nativeAgent.model.trim(),
      piAgent: draft.nativeAgent.piAgent.trim(),
      baseUrl: providerLooksLikeUrl && !baseUrlInput ? providerInput.replace(/\/+$/, "") : baseUrlInput.replace(/\/+$/, ""),
      apiKey: draft.nativeAgent.apiKey.trim(),
      clearApiKey: Boolean(draft.nativeAgent.clearApiKey),
    },
  };
}

function draftEquals(left: EditDraft, right: EditDraft) {
  return JSON.stringify(normalizeEditDraft(left)) === JSON.stringify(normalizeEditDraft(right));
}

function clusterConfigFromBot(bot: BotSummary): BotClusterConfig {
  return {
    ...DEFAULT_CLUSTER_CONFIG,
    ...(bot.cluster || {}),
    modelTiers: {
      ...DEFAULT_CLUSTER_CONFIG.modelTiers,
      ...(bot.cluster?.modelTiers || {}),
    },
    reasoningEfforts: {
      ...DEFAULT_CLUSTER_CONFIG.reasoningEfforts,
      ...(bot.cluster?.reasoningEfforts || {}),
    },
  };
}

function cliPathPlaceholder(cliType: CliType) {
  return defaultCliPathForType(cliType);
}

function runtimeBackendLabel(runtimeBackend: ChatExecutionMode) {
  return runtimeBackend === "native_agent" ? "原生 agent" : "CLI";
}

function clampInspectorWidth(width: number, availableWidth?: number) {
  const maxBySpace = availableWidth
    ? Math.max(INSPECTOR_MIN_WIDTH, availableWidth - LIST_MIN_WIDTH - RESIZER_WIDTH)
    : INSPECTOR_MAX_WIDTH;
  return Math.min(Math.min(INSPECTOR_MAX_WIDTH, maxBySpace), Math.max(INSPECTOR_MIN_WIDTH, Math.round(width)));
}

function bulkActionVerb(action: BulkAction) {
  if (action === "start") {
    return "启动";
  }
  if (action === "stop") {
    return "停止";
  }
  return "删除";
}

function bulkResultSummary(result: BulkActionResult) {
  const verb = bulkActionVerb(result.action);
  const parts = [`已${verb} ${result.succeeded.length} 个`];
  if (result.failed.length > 0) {
    parts.push(`失败 ${result.failed.length} 个`);
  }
  if (result.skipped.length > 0) {
    parts.push(`跳过 ${result.skipped.length} 个`);
  }
  return parts.join("，");
}

function WorkdirConflictNotice({
  conflict,
  onConfirm,
  onCancel,
}: {
  conflict: WorkdirChangeConflict;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="rounded-md border border-[var(--feedback-warning-border-light)] bg-[var(--feedback-warning-background-subtle)] p-3 text-sm text-[var(--feedback-warning-text-stronger)]">
      <div>切换工作区会清空 {conflict.historyCount} 条聊天消息。</div>
      <div className="mt-1 break-all text-xs text-[var(--feedback-warning-text-deep)]">
        {conflict.currentWorkingDir} {"->"} {conflict.requestedWorkingDir}
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onConfirm}
          className="rounded-md bg-[var(--button-warning-background-strong)] px-3 py-1.5 text-sm font-medium text-[var(--button-filled-foreground)] hover:opacity-90"
        >
          确认切换
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-[var(--feedback-warning-border-visible)] px-3 py-1.5 text-sm hover:bg-[var(--feedback-warning-background-soft)]"
        >
          取消
        </button>
      </div>
    </div>
  );
}

function EditPanel({
  bot,
  manager,
  canManage,
  canConfigureBot,
  canCreateWorkdirDirectory,
  nativeAgentFeatureEnabled,
  onCancel,
  onSaved,
  onOpenConversation,
  onDirtyChange,
}: {
  bot: BotSummary;
  manager: ReturnType<typeof useBotManager>;
  canManage: boolean;
  canConfigureBot: boolean;
  canCreateWorkdirDirectory: boolean;
  nativeAgentFeatureEnabled: boolean | null;
  onCancel: () => void;
  onSaved: (alias: string) => void;
  onOpenConversation: (alias: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [draft, setDraft] = useState<EditDraft>(draftFromBot(bot));
  const [showWorkdirPicker, setShowWorkdirPicker] = useState(false);
  const [showRemotePicker, setShowRemotePicker] = useState(false);
  const [pendingWorkdirConflict, setPendingWorkdirConflict] = useState<WorkdirChangeConflict | null>(null);
  const [clusterStatus, setClusterStatus] = useState<ClusterStatus | null>(null);
  // `clusterConfig` mirrors the persisted config; edits stay in `clusterDraft` until saved together.
  const [clusterConfig, setClusterConfig] = useState<BotClusterConfig>(() => clusterConfigFromBot(bot));
  const [clusterDraft, setClusterDraft] = useState<BotClusterConfig>(() => clusterConfigFromBot(bot));
  const [clusterTimeoutDraft, setClusterTimeoutDraft] = useState(() => String(clusterConfigFromBot(bot).defaultTimeoutSeconds));
  const clusterScopeRef = useRef({ alias: bot.alias, saved: clusterConfigFromBot(bot) });
  const [cliParams, setCliParams] = useState<CliParamsPayload | null>(null);
  const [nativeAgentModels, setNativeAgentModels] = useState<NativeAgentModelsPayload | null>(null);
  const [clusterSaving, setClusterSaving] = useState(false);
  const [clusterError, setClusterError] = useState("");
  const [clusterResizeBlocked, setClusterResizeBlocked] = useState<ClusterResizeBlockedData | null>(null);
  const [clusterBlockerAction, setClusterBlockerAction] = useState("");
  const clusterDirty = !clusterDraftEquals(clusterDraft, clusterConfig)
    || clusterTimeoutDraft.trim() !== String(clusterConfig.defaultTimeoutSeconds);
  const dirty = !draftEquals(draft, draftFromBot(bot)) || clusterDirty;
  const directoryBrowserAlias = manager.bots.find((item) => isMainBot(item))?.alias || manager.bots[0]?.alias || "main";
  const nativeAgentOptionVisible = nativeAgentFeatureEnabled !== false || draft.runtimeBackend === "native_agent";
  const nativeRuntime = getRuntimeBackend(bot) === "native_agent";

  useEffect(() => {
    setDraft(draftFromBot(bot));
    setShowRemotePicker(false);
    setPendingWorkdirConflict(null);
    setClusterResizeBlocked(null);
  }, [bot.alias]);

  useEffect(() => {
    // Bot list refreshes (including the enable toggle) must not discard unsaved cluster edits.
    const nextClusterConfig = clusterConfigFromBot(bot);
    const previous = clusterScopeRef.current;
    clusterScopeRef.current = { alias: bot.alias, saved: nextClusterConfig };
    const sameBot = previous.alias === bot.alias;
    setClusterConfig(nextClusterConfig);
    setClusterDraft((current) => (
      sameBot && !clusterDraftEquals(current, previous.saved) ? current : nextClusterConfig
    ));
    setClusterTimeoutDraft((current) => (
      sameBot && current.trim() !== String(previous.saved.defaultTimeoutSeconds)
        ? current
        : String(nextClusterConfig.defaultTimeoutSeconds)
    ));
  }, [bot.alias, bot.cluster]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (nativeAgentFeatureEnabled === false && draft.runtimeBackend !== "native_agent") {
      return;
    }
    if (nativeAgentFeatureEnabled === false && draft.runtimeBackend === "native_agent" && getRuntimeBackend(bot) !== "native_agent") {
      setDraft((prev) => ({ ...prev, runtimeBackend: "cli" }));
    }
  }, [bot, draft.runtimeBackend, nativeAgentFeatureEnabled]);

  useEffect(() => {
    let cancelled = false;
    setClusterError("");
    setClusterStatus(null);
    setCliParams(null);
    setNativeAgentModels(null);
    void Promise.all([
      manager.client.getClusterStatus(bot.alias),
      nativeRuntime ? Promise.resolve(null) : manager.client.getCliParams(bot.alias),
      nativeRuntime ? manager.client.getNativeAgentModels(bot.alias) : Promise.resolve(null),
    ])
      .then(([nextCluster, nextCliParams, nextNativeAgentModels]) => {
        if (!cancelled) {
          setClusterStatus(nextCluster);
          setCliParams(nextCliParams);
          setNativeAgentModels(nextNativeAgentModels);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setClusterError(err.message || "加载集群配置失败");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [bot.alias, bot.cliType, bot.nativeAgent?.model, nativeRuntime, manager.client]);

  function clusterReasoningOptions(model: string): string[] {
    if (nativeRuntime) {
      const effectiveModel = model || nativeAgentModels?.selectedModel || bot.nativeAgent?.model;
      return nativeAgentModels?.items.find((item) => item.id === effectiveModel)?.reasoningEfforts ?? [];
    }
    return cliParams?.schema.reasoning_effort?.enum ?? cliParams?.schema.effort?.enum ?? [];
  }

  async function submit(options: UpdateBotWorkdirOptions = {}) {
    // Save pending cluster edits first, while the current alias is still valid.
    if (clusterDirty && !(await saveClusterDraft())) {
      return;
    }
    const result = await manager.saveBotEdits(bot, draft, options);
    if (result.ok) {
      setPendingWorkdirConflict(null);
      onSaved(result.bot.alias);
      return;
    }
    if ("conflict" in result && result.conflict) {
      setPendingWorkdirConflict(result.conflict);
    }
  }

  async function persistCluster(next: BotClusterConfig, options: { replaceDraft: boolean }) {
    if (!canConfigureBot) {
      return false;
    }
    setClusterSaving(true);
    setClusterError("");
    try {
      const result = await manager.client.updateClusterConfig(bot.alias, {
        enabled: next.enabled,
        writePolicy: next.writePolicy,
        maxParallelAgents: next.maxParallelAgents,
        defaultTimeoutSeconds: next.defaultTimeoutSeconds,
        modelTiers: next.modelTiers,
        reasoningEfforts: next.reasoningEfforts,
      });
      setClusterConfig(result.cluster);
      if (options.replaceDraft) {
        setClusterDraft(result.cluster);
        setClusterTimeoutDraft(String(result.cluster.defaultTimeoutSeconds));
      } else {
        setClusterDraft((current) => ({ ...current, enabled: result.cluster.enabled }));
      }
      setClusterStatus(result.status);
      setClusterResizeBlocked(null);
      manager.updateBotCluster(bot.alias, result.cluster);
      return true;
    } catch (err) {
      if (
        err instanceof WebApiClientError
        && (err.code === "cluster_resize_blocked" || (err.data as { code?: string } | undefined)?.code === "cluster_resize_blocked")
      ) {
        setClusterResizeBlocked(err.data as ClusterResizeBlockedData);
      }
      setClusterError(err instanceof Error ? err.message : "保存集群配置失败");
      return false;
    } finally {
      setClusterSaving(false);
    }
  }

  // The switch applies immediately and leaves unsaved field edits in the draft.
  async function toggleClusterEnabled(enabled: boolean) {
    await persistCluster({ ...clusterConfig, enabled }, { replaceDraft: false });
  }

  async function saveClusterDraft() {
    const timeoutSeconds = Number(clusterTimeoutDraft.trim());
    if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 60 || timeoutSeconds > 3600) {
      setClusterError("任务超时必须是 60 到 3600 之间的整数");
      return false;
    }
    const next: BotClusterConfig = {
      ...clusterDraft,
      enabled: clusterConfig.enabled,
      defaultTimeoutSeconds: timeoutSeconds,
      modelTiers: { ...clusterDraft.modelTiers },
      reasoningEfforts: { ...clusterDraft.reasoningEfforts },
    };
    if (nativeRuntime && nativeAgentModels) {
      for (const tier of ["low", "medium", "high", "professional"] as const) {
        if (!clusterReasoningOptions(next.modelTiers[tier]).includes(next.reasoningEfforts[tier])) {
          next.reasoningEfforts[tier] = "";
        }
      }
    }
    return persistCluster(next, { replaceDraft: true });
  }

  function resetClusterDraft() {
    setClusterDraft(clusterConfig);
    setClusterTimeoutDraft(String(clusterConfig.defaultTimeoutSeconds));
    setClusterError("");
    setClusterResizeBlocked(null);
  }

  async function openBlockingConversation(blocker: ClusterResizeBlocker) {
    setClusterBlockerAction(`open:${blocker.conversationId}`);
    setClusterError("");
    try {
      await manager.client.selectConversation(bot.alias, blocker.conversationId, {
        agentId: "main",
        executionMode: blocker.executionMode,
      });
      onOpenConversation(bot.alias);
    } catch (err) {
      setClusterError(err instanceof Error ? err.message : "打开阻塞会话失败");
    } finally {
      setClusterBlockerAction("");
    }
  }

  async function archiveBlockingConversation(blocker: ClusterResizeBlocker) {
    setClusterBlockerAction(`archive:${blocker.conversationId}`);
    setClusterError("");
    try {
      await manager.client.archiveConversation(bot.alias, blocker.conversationId, {
        agentId: "main",
        executionMode: blocker.executionMode,
      });
      setClusterResizeBlocked((current) => {
        if (!current) return current;
        const blockers = current.blockers.filter((item) => item.conversationId !== blocker.conversationId);
        return blockers.length > 0 ? { ...current, blockers } : null;
      });
    } catch (err) {
      setClusterError(err instanceof Error ? err.message : "归档阻塞会话失败");
    } finally {
      setClusterBlockerAction("");
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold">编辑 {bot.alias}</h2>
      </div>
      {pendingWorkdirConflict ? (
        <WorkdirConflictNotice
          conflict={pendingWorkdirConflict}
          onConfirm={() => void submit({ forceReset: true })}
          onCancel={() => setPendingWorkdirConflict(null)}
        />
      ) : null}
      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">别名</span>
          <input
            aria-label="智能体别名"
            value={draft.alias}
            disabled={!canManage || isMainBot(bot)}
            onChange={(event) => setDraft((prev) => ({ ...prev, alias: event.target.value }))}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">运行后端</span>
          <select
            aria-label="运行后端"
            value={draft.runtimeBackend}
            disabled={!canManage}
            onChange={(event) => setDraft((prev) => ({ ...prev, runtimeBackend: event.target.value as EditDraft["runtimeBackend"] }))}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
          >
            <option value="cli">CLI</option>
            {nativeAgentOptionVisible && draft.cliType !== "deepseek" ? <option value="native_agent">原生 agent</option> : null}
          </select>
          {nativeAgentFeatureEnabled === false ? (
            <p className="text-xs text-[var(--muted)]">原生 agent 全局未启用</p>
          ) : null}
        </label>
        {draft.runtimeBackend === "cli" ? (
          <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">CLI 类型</span>
          <select
            aria-label="智能体 CLI 类型"
            value={draft.cliType}
            disabled={!canManage}
            onChange={(event) => {
              const cliType = event.target.value as CliType;
              setDraft((prev) => ({ ...prev, cliType, cliPath: cliType === "deepseek" || prev.cliType === "deepseek" ? defaultCliPathForType(cliType) : prev.cliPath }));
            }}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
          >
            <option value="codex">codex</option>
            <option value="codex_server">codex server</option>
            <option value="claude">claude</option>
            <option value="antigravity">Antigravity CLI</option>
            <option value="deepseek" disabled={Boolean(bot.remoteWorkspace)}>DeepSeek Harness</option>
          </select>
          </label>
        ) : null}
        {draft.runtimeBackend === "cli" ? (
          <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">CLI 路径</span>
          <input
            aria-label="智能体 CLI 路径"
            value={draft.cliPath}
            disabled={!canManage}
            onChange={(event) => setDraft((prev) => ({ ...prev, cliPath: event.target.value }))}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
            placeholder={cliPathPlaceholder(draft.cliType)}
          />
          </label>
        ) : null}
      </div>
      {draft.runtimeBackend === "native_agent" ? (
        <NativeAgentConfigFields
          provider={draft.nativeAgent.provider}
          model={draft.nativeAgent.model}
          piAgent={draft.nativeAgent.piAgent}
          baseUrl={draft.nativeAgent.baseUrl}
          apiKey={draft.nativeAgent.apiKey}
          hasApiKey={draft.nativeAgent.hasApiKey}
          apiKeyMasked={draft.nativeAgent.apiKeyMasked}
          clearApiKey={draft.nativeAgent.clearApiKey}
          editing
          disabled={!canManage || manager.savingAction !== ""}
          onNativeAgentChange={(patch) => setDraft((prev) => ({
            ...prev,
            nativeAgent: {
              ...prev.nativeAgent,
              ...patch,
            },
          }))}
        />
      ) : null}
      {bot.remoteWorkspace ? (
        <div className="space-y-2 text-sm">
          <span className="text-[var(--muted)]">远程地址和工作目录</span>
          <div className="flex flex-wrap items-center gap-2">
            <span className="min-w-0 flex-1 break-all">{workspaceLabel({ workingDir: draft.workingDir, remoteWorkspace: draft.remoteWorkspace })}</span>
            <button type="button" onClick={() => setShowRemotePicker((open) => !open)} disabled={!canManage || manager.savingAction !== ""} className="rounded-md border border-[var(--border)] px-3 py-2 hover:bg-[var(--surface-strong)] disabled:opacity-60">
              {showRemotePicker ? "取消更换" : "更换远程地址或工作目录"}
            </button>
          </div>
          {showRemotePicker && <RemoteWorkspacePicker client={manager.client} initial={draft.remoteWorkspace} onPick={(remote) => { setDraft((prev) => ({ ...prev, remoteWorkspace: remote })); setShowRemotePicker(false); }} />}
        </div>
      ) : (
        <label className="block space-y-1 text-sm">
          <span className="text-[var(--muted)]">工作目录</span>
          <div className="flex gap-2">
            <input aria-label="智能体工作目录" value={draft.workingDir} disabled={!canManage} onChange={(event) => setDraft((prev) => ({ ...prev, workingDir: event.target.value }))} className="h-9 min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60" />
            <button type="button" aria-label="浏览智能体工作目录" onClick={() => setShowWorkdirPicker(true)} disabled={!canManage || manager.savingAction !== ""} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[var(--border)] px-3 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"><FolderOpen className="h-4 w-4" />浏览目录</button>
          </div>
        </label>
      )}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[var(--border)] px-3 text-sm hover:bg-[var(--surface-strong)]"
        >
          <Undo2 className="h-4 w-4" />
          撤销
        </button>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!canManage || manager.savingAction !== "" || showRemotePicker || clusterSaving}
          className="inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium tcb-solid-accent disabled:opacity-60"
        >
          <Save className="h-4 w-4" />
          保存智能体
        </button>
      </div>
      {showWorkdirPicker ? (
        <DirectoryPickerDialog
          title="选择工作目录"
          botAlias={directoryBrowserAlias}
          client={manager.client}
          initialPath={draft.workingDir}
          mutateBrowseState={false}
          mode="workdir"
          canCreateDirectory={canCreateWorkdirDirectory}
          onPick={(workingDir) => setDraft((prev) => ({ ...prev, workingDir }))}
          onClose={() => setShowWorkdirPicker(false)}
        />
      ) : null}

      <div className="space-y-4 border-t border-[var(--border)] pt-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="inline-flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={Boolean(clusterConfig.enabled)}
                disabled={!canConfigureBot || clusterSaving || !clusterStatus}
                onChange={(event) => {
                  if (!clusterStatus) return;
                  void toggleClusterEnabled(event.target.checked);
                }}
              />
              启用集群模式
            </label>
            {clusterSaving ? <span className="text-xs text-[var(--muted)]">保存中...</span> : null}
          </div>
          {clusterError ? <div className="text-sm text-[var(--feedback-error-text-deep)]">{clusterError}</div> : null}
          {clusterResizeBlocked ? (
            <section role="alert" aria-label="缩容受阻" className="rounded-lg border border-[var(--status-warning-border)] bg-[var(--status-warning-bg)] p-3 text-sm text-[var(--text)]">
              <div className="font-medium">集群规模暂时无法缩小到 {clusterResizeBlocked.targetSize}</div>
              <p className="mt-1 text-xs text-[var(--muted)]">至少需要 {clusterResizeBlocked.minimumSize} 个槽位。请打开会话要求主 Agent 重新编组，或归档不再需要的会话。</p>
              <div className="mt-3 space-y-2">
                {clusterResizeBlocked.blockers.map((blocker) => (
                  <div key={blocker.conversationId} className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--surface)] p-2">
                    <div className="font-medium">{blocker.title || "新会话"}</div>
                    <div className="mt-1 text-xs text-[var(--muted)]">
                      当前角色 {blocker.roleCount}；超出槽位：{blocker.outsideAgentIds.join("、") || "运行中任务"}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void openBlockingConversation(blocker)}
                        disabled={Boolean(clusterBlockerAction)}
                        className="h-8 rounded-md border border-[var(--border)] px-2 text-xs hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        {clusterBlockerAction === `open:${blocker.conversationId}` ? "打开中..." : "打开会话"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void archiveBlockingConversation(blocker)}
                        disabled={Boolean(clusterBlockerAction)}
                        className="h-8 rounded-md border border-[var(--border)] px-2 text-xs hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        {clusterBlockerAction === `archive:${blocker.conversationId}` ? "归档中..." : "归档会话"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
          {clusterStatus ? (
            <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-base font-semibold text-[var(--text)]">集群运行参数</h2>
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="grid gap-1 text-sm">
                  <span className="font-medium text-[var(--text)]">集群规模</span>
                  <select
                    aria-label="集群规模"
                    value={clusterDraft.maxParallelAgents}
                    disabled={!canConfigureBot || clusterSaving}
                    onChange={(event) => setClusterDraft((current) => ({ ...current, maxParallelAgents: Number(event.target.value) }))}
                    className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                  >
                    {Array.from({ length: 20 }, (_, index) => index + 1).map((count) => (
                      <option key={count} value={count}>{count}</option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-1 text-sm">
                  <span className="font-medium text-[var(--text)]">子 Agent 写入策略</span>
                  <select
                    aria-label="子 Agent 写入策略"
                    value={clusterDraft.writePolicy}
                    disabled={!canConfigureBot || clusterSaving}
                    onChange={(event) => setClusterDraft((current) => ({ ...current, writePolicy: event.target.value as BotClusterConfig["writePolicy"] }))}
                    className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                  >
                    <option value="main_only">仅主 Agent 可写</option>
                    <option value="all_agents">允许子 Agent 写入</option>
                  </select>
                </label>
                <label className="grid gap-1 text-sm">
                  <span className="font-medium text-[var(--text)]">任务超时（秒）</span>
                  <input
                    aria-label="任务超时（秒）"
                    type="number"
                    min={60}
                    max={3600}
                    value={clusterTimeoutDraft}
                    disabled={!canConfigureBot || clusterSaving}
                    onChange={(event) => setClusterTimeoutDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                        event.preventDefault();
                        void saveClusterDraft();
                      }
                    }}
                    className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                  />
                </label>
              </div>
            </section>
          ) : null}
          {clusterStatus ? (
            <ClusterModelTiersPanel
              value={clusterDraft.modelTiers}
              reasoningEfforts={clusterDraft.reasoningEfforts}
              modelOptions={nativeRuntime ? nativeAgentModels?.items.map((item) => item.id) ?? [] : cliParams?.schema.model?.enum ?? []}
              reasoningOptions={clusterReasoningOptions}
              disabled={!canConfigureBot || clusterSaving}
              onChange={(modelTiers) => setClusterDraft((current) => ({ ...current, modelTiers }))}
              onReasoningChange={(reasoningEfforts) => setClusterDraft((current) => ({ ...current, reasoningEfforts }))}
            />
          ) : null}
          {clusterStatus ? (
            <div className="flex items-center justify-end gap-2">
              {clusterDirty ? (
                <button
                  type="button"
                  onClick={resetClusterDraft}
                  disabled={clusterSaving}
                  className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[var(--border)] px-3 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  <Undo2 className="h-4 w-4" />
                  还原集群配置
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => void saveClusterDraft()}
                disabled={!canConfigureBot || clusterSaving || !clusterDirty}
                className="inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium tcb-solid-accent disabled:opacity-60"
              >
                <Save className="h-4 w-4" />
                {clusterSaving ? "保存中..." : "保存集群配置"}
              </button>
            </div>
          ) : null}
          <ClusterSetupPanel key={`${bot.alias}:${bot.cliType}:${nativeRuntime}`} botAlias={bot.alias} client={manager.client} canManage={canConfigureBot} />
      </div>

      {draft.runtimeBackend === "cli" ? (
        <BotCliParamsPanel
          botAlias={bot.alias}
          client={manager.client}
          canManage={canConfigureBot}
          reloadKey={`${bot.alias}:${bot.cliType}:${bot.cliPath || ""}`}
        />
      ) : null}
    </div>
  );
}

function BulkSummaryPanel({
  selectedBots,
}: {
  selectedBots: BotSummary[];
}) {
  const startPlan = buildBulkActionPlan("start", selectedBots);
  const stopPlan = buildBulkActionPlan("stop", selectedBots);
  const deletePlan = buildBulkActionPlan("delete", selectedBots);
  const skipped = [...startPlan.skipped, ...stopPlan.skipped, ...deletePlan.skipped];

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">批量操作</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">已选 {selectedBots.length} 个智能体。</p>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
          <div className="text-xs text-[var(--muted)]">可启动</div>
          <div className="mt-1 text-lg font-semibold">{startPlan.targets.length}</div>
        </div>
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
          <div className="text-xs text-[var(--muted)]">可停止</div>
          <div className="mt-1 text-lg font-semibold">{stopPlan.targets.length}</div>
        </div>
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
          <div className="text-xs text-[var(--muted)]">可删除</div>
          <div className="mt-1 text-lg font-semibold">{deletePlan.targets.length}</div>
        </div>
      </div>
      <div className="space-y-1 text-xs text-[var(--muted)]">
        {skipped.slice(0, 6).map((item, index) => (
          <div key={`${item.alias}:${item.reason}:${index}`}>{item.alias}: {item.reason}</div>
        ))}
      </div>
    </div>
  );
}

function DeleteBotDialog({
  title,
  description,
  deleteHistory,
  deleteWorkspace,
  workspacePath,
  workspaceConfirmText,
  allowWorkspaceDelete = true,
  busy,
  onDeleteHistoryChange,
  onDeleteWorkspaceChange,
  onWorkspaceConfirmTextChange,
  onCancel,
  onConfirm,
}: {
  title: string;
  description?: string;
  deleteHistory: boolean;
  deleteWorkspace: boolean;
  workspacePath?: string;
  workspaceConfirmText: string;
  allowWorkspaceDelete?: boolean;
  busy: boolean;
  onDeleteHistoryChange: (value: boolean) => void;
  onDeleteWorkspaceChange: (value: boolean) => void;
  onWorkspaceConfirmTextChange: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const workspaceConfirmMatched = workspaceConfirmText.trim() === DELETE_WORKSPACE_CONFIRM_TEXT;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay-backdrop-50)] p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-bot-dialog-title"
        className="w-full max-w-md rounded-2xl bg-[var(--surface)] p-5 shadow-[var(--shadow-card)]"
      >
        <h2 id="delete-bot-dialog-title" className="text-base font-semibold">{title}</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">{description || "可只删智能体，或连历史记录一起删。"}</p>
        <label className="mt-4 flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={deleteWorkspace || deleteHistory}
            onChange={(event) => onDeleteHistoryChange(event.target.checked)}
            disabled={busy || deleteWorkspace}
            className="mt-0.5 h-4 w-4 rounded border-[var(--border)]"
          />
          <span>同时删除历史记录（包含所有子 agents）</span>
        </label>
        {allowWorkspaceDelete ? (
          <>
            <label className="mt-3 flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={deleteWorkspace}
                onChange={(event) => onDeleteWorkspaceChange(event.target.checked)}
                disabled={busy}
                className="mt-0.5 h-4 w-4 rounded border-[var(--border)]"
              />
              <span>同时删除工作区和所有记录</span>
            </label>
            {deleteWorkspace ? (
              <div className="mt-3 space-y-3 rounded-md border border-[var(--feedback-error-border-light)] bg-[var(--feedback-error-background-subtle)] px-3 py-2 text-sm text-[var(--feedback-error-text-stronger)]">
                <p>将删除该 Bot 的磁盘工作区目录，且会一并删除历史记录和 session 记录。</p>
                <div className="break-all font-mono text-xs">{workspacePath || "未设置工作区"}</div>
                <label className="block text-sm">
                  <span>输入“{DELETE_WORKSPACE_CONFIRM_TEXT}”确认</span>
                  <input
                    aria-label="输入永久删除确认词"
                    value={workspaceConfirmText}
                    onChange={(event) => onWorkspaceConfirmTextChange(event.target.value)}
                    className="mt-2 h-9 w-full rounded-md border border-[var(--feedback-error-border-light)] bg-[var(--access-badge-background)] px-3 text-sm text-[var(--feedback-error-text-emphasis)] outline-none focus:border-[var(--feedback-error-border)]"
                    autoFocus
                  />
                </label>
              </div>
            ) : null}
          </>
        ) : (
          <p className="mt-3 text-xs text-[var(--muted)]">彻底删除工作区请逐个操作。</p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy || (deleteWorkspace && !workspaceConfirmMatched)}
            className="rounded-lg border border-[var(--feedback-error-border-light)] px-3 py-2 text-sm text-[var(--feedback-error-text-deep)] hover:bg-[var(--feedback-error-background-subtle)] disabled:opacity-60"
          >
            {busy ? "删除中..." : deleteWorkspace ? "彻底删除" : "删除"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function DesktopBotManagerScreen({
  client = new MockWebBotClient(),
  currentAlias,
  onSelect,
  onLogout,
  onBotsChange,
  canManage = true,
  canCreateWorkdirDirectory = true,
  canRunUnsafeCli = false,
}: Props) {
  const manager = useBotManager({ client, onBotsChange, includeArchived: canManage });
  const [nativeAgentFeatureEnabled, setNativeAgentFeatureEnabled] = useState<boolean | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<ManagerViewFilter>("all");
  const [mode, setMode] = useState<Mode>("inspect");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("overview");
  const [focusedAlias, setFocusedAlias] = useState(currentAlias || "");
  const [selectedAliases, setSelectedAliases] = useState<Set<string>>(() => new Set());
  const [dirty, setDirty] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkActionResult | null>(null);
  const [inspectorWidth, setInspectorWidth] = useState(INSPECTOR_DEFAULT_WIDTH);
  const [pendingDeleteAlias, setPendingDeleteAlias] = useState("");
  const [pendingBulkDeleteCount, setPendingBulkDeleteCount] = useState(0);
  const [deleteHistory, setDeleteHistory] = useState(false);
  const [deleteWorkspace, setDeleteWorkspace] = useState(false);
  const [deleteWorkspaceConfirmText, setDeleteWorkspaceConfirmText] = useState("");
  const layoutRef = useRef<HTMLDivElement>(null);

  const visibleBots = useMemo(() => getVisibleManagedBots({
    bots: manager.bots,
    query,
    filter: statusFilter,
  }), [manager.bots, query, statusFilter]);

  const focusedBot = manager.bots.find((bot) => bot.alias === focusedAlias)
    || manager.bots.find((bot) => bot.alias === currentAlias)
    || visibleBots[0]
    || null;

  const selectedBots = useMemo(
    () => manager.bots.filter((bot) => selectedAliases.has(bot.alias)),
    [manager.bots, selectedAliases],
  );

  const stats = countBotManagerStats(manager.bots);
  const focusedBotIssues = focusedBot ? detectBotIssues(focusedBot, manager.bots) : [];

  useEffect(() => {
    let cancelled = false;
    void client.getEnvConfig()
      .then((snapshot) => {
        if (cancelled) return;
        setNativeAgentFeatureEnabled(isNativeAgentGloballyEnabled(snapshot));
      })
      .catch(() => {
        if (cancelled) return;
        setNativeAgentFeatureEnabled(null);
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  useEffect(() => {
    if (!focusedBot && visibleBots[0]) {
      setFocusedAlias(visibleBots[0].alias);
      return;
    }
    if (focusedBot && !manager.bots.some((bot) => bot.alias === focusedBot.alias)) {
      setFocusedAlias(visibleBots[0]?.alias || currentAlias || "");
    }
  }, [currentAlias, focusedBot, manager.bots, visibleBots]);

  function confirmDiscardDirty() {
    if (!dirty) {
      return true;
    }
    return window.confirm("当前智能体配置有未保存修改，继续会丢失这些修改。确定继续吗？");
  }

  function focusBot(alias: string) {
    if (!confirmDiscardDirty()) {
      return;
    }
    setDirty(false);
    setMode("inspect");
    setInspectorTab("overview");
    setFocusedAlias(alias);
  }

  function toggleBotSelection(alias: string) {
    setSelectedAliases((prev) => {
      const next = new Set(prev);
      if (next.has(alias)) {
        next.delete(alias);
      } else {
        next.add(alias);
      }
      return next;
    });
  }

  function clearSelection() {
    setSelectedAliases(new Set());
  }

  function selectVisibleBots() {
    setSelectedAliases(new Set(visibleBots.map((bot) => bot.alias)));
  }

  function openDeleteDialog(alias: string) {
    setPendingDeleteAlias(alias);
    setPendingBulkDeleteCount(0);
    setDeleteHistory(false);
    setDeleteWorkspace(false);
    setDeleteWorkspaceConfirmText("");
  }

  function openBulkDeleteDialog(count: number) {
    setPendingDeleteAlias("");
    setPendingBulkDeleteCount(count);
    setDeleteHistory(false);
    setDeleteWorkspace(false);
    setDeleteWorkspaceConfirmText("");
  }

  async function confirmDelete() {
    if (!pendingDeleteAlias) {
      return;
    }
    const bot = manager.bots.find((item) => item.alias === pendingDeleteAlias);
    if (!bot) {
      setPendingDeleteAlias("");
      setDeleteHistory(false);
      setDeleteWorkspace(false);
      setDeleteWorkspaceConfirmText("");
      return;
    }
    const removed = await manager.deleteBot(bot, { deleteHistory: deleteHistory || deleteWorkspace, deleteWorkspace });
    if (removed) {
      setPendingDeleteAlias("");
      setPendingBulkDeleteCount(0);
      setDeleteHistory(false);
      setDeleteWorkspace(false);
      setDeleteWorkspaceConfirmText("");
    }
  }

  async function confirmBulkDelete() {
    const plan = buildBulkActionPlan("delete", selectedBots);
    if (plan.targets.length === 0 && plan.skipped.length === 0) {
      setPendingBulkDeleteCount(0);
      setDeleteHistory(false);
      return;
    }

    const result: BulkActionResult = {
      action: "delete",
      succeeded: [],
      failed: [],
      skipped: plan.skipped,
    };

    for (const bot of plan.targets) {
      try {
        await manager.client.removeBot(bot.alias, { deleteHistory });
        result.succeeded.push(bot.alias);
      } catch (error) {
        result.failed.push({
          alias: bot.alias,
          message: error instanceof Error ? error.message : "删除失败",
        });
      }
    }

    setBulkResult(result);
    clearSelection();
    setPendingBulkDeleteCount(0);
    setDeleteHistory(false);
    setDeleteWorkspace(false);
    setDeleteWorkspaceConfirmText("");
    await manager.loadBots();
  }

  function handleTableKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (visibleBots.length === 0) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      if (selectedAliases.size > 0) {
        clearSelection();
        return;
      }
      if (dirty && confirmDiscardDirty()) {
        setDirty(false);
        setMode("inspect");
        setInspectorTab("overview");
      }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      selectVisibleBots();
      return;
    }
    if (event.key === " ") {
      event.preventDefault();
      if (focusedBot) {
        toggleBotSelection(focusedBot.alias);
      }
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
      return;
    }
    event.preventDefault();
    const currentIndex = Math.max(0, visibleBots.findIndex((bot) => bot.alias === focusedBot?.alias));
    const delta = event.key === "ArrowDown" ? 1 : -1;
    const nextBot = visibleBots[(currentIndex + delta + visibleBots.length) % visibleBots.length];
    focusBot(nextBot.alias);
  }

  function startPaneResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const layout = layoutRef.current;
    const rect = layout?.getBoundingClientRect();
    const pointerId = event.pointerId;
    event.currentTarget.setPointerCapture?.(pointerId);

    function handlePointerMove(moveEvent: PointerEvent) {
      if (!layout) {
        return;
      }
      const nextRect = layout.getBoundingClientRect();
      setInspectorWidth(clampInspectorWidth(nextRect.right - moveEvent.clientX, nextRect.width));
    }

    function handlePointerUp() {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    }

    if (rect) {
      setInspectorWidth(clampInspectorWidth(rect.right - event.clientX, rect.width));
    }
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp, { once: true });
  }

  async function runBulkAction(action: BulkAction) {
    const plan = buildBulkActionPlan(action, selectedBots);
    if (plan.targets.length === 0 && plan.skipped.length === 0) {
      return;
    }

    if (plan.destructive) {
      openBulkDeleteDialog(plan.targets.length);
      return;
    }

    const result: BulkActionResult = {
      action,
      succeeded: [],
      failed: [],
      skipped: plan.skipped,
    };

    for (const bot of plan.targets) {
      try {
        if (action === "start") {
          await manager.client.startBot(bot.alias);
        } else if (action === "stop") {
          await manager.client.stopBot(bot.alias);
        } else {
          await manager.client.removeBot(bot.alias);
        }
        result.succeeded.push(bot.alias);
      } catch (error) {
        result.failed.push({
          alias: bot.alias,
          message: error instanceof Error ? error.message : `${bulkActionVerb(action)}失败`,
        });
      }
    }

    setBulkResult(result);
    clearSelection();
    await manager.loadBots();
  }

  function renderInspectorTabs() {
    const tabs: Array<{ id: InspectorTab; label: string }> = [
      { id: "overview", label: "概览" },
      { id: "config", label: "配置" },
    ];

    return (
      <div className="orbit-segmented orbit-segmented--accent am-inspector-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            aria-pressed={inspectorTab === tab.id}
            disabled={tab.id === "config" && Boolean(focusedBot?.archived)}
            onClick={() => {
              if (tab.id !== inspectorTab && !confirmDiscardDirty()) {
                return;
              }
              setDirty(false);
              setMode("inspect");
              setInspectorTab(tab.id);
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
    );
  }

  function renderBotTags(bot: BotSummary, options: { remote?: boolean } = {}) {
    return (
      <>
        {isMainBot(bot) ? <span className="am-tag">主</span> : null}
        {options.remote && bot.remoteWorkspace ? <span className="am-tag">远程</span> : null}
        {isBotArchived(bot) ? <span className="am-tag" data-tone="warning">已归档</span> : null}
        {bot.alias === currentAlias ? <span className="am-tag" data-tone="accent">当前</span> : null}
        {bot.canOperate === false ? <span className="am-tag" data-tone="restricted">无权限 · 只读</span> : null}
      </>
    );
  }

  return (
    <main
      data-testid="desktop-bot-manager-screen"
      data-ui-density="compact"
      className="desktop-bot-manager-screen am-screen orbit-shell flex h-[100dvh] min-h-0 flex-col overflow-hidden"
    >
      <header className="am-cover orbit-cover">
        <div className="orbit-cover-art">
          <ThemeIllustrationLayer surface="agentManager" />
        </div>
        <div className="am-cover-bar">
          <div className="am-search">
            <Search aria-hidden="true" />
            <input
              aria-label="搜索智能体"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索智能体、目录、agent"
              className="orbit-field"
            />
          </div>
          <button
            type="button"
            aria-label="刷新智能体"
            title="刷新智能体"
            onClick={() => {
              if (!confirmDiscardDirty()) {
                return;
              }
              setDirty(false);
              void manager.loadBots();
            }}
            className="orbit-btn orbit-btn--icon am-glass-btn"
          >
            <RefreshCw className={clsx("h-4 w-4", manager.loading && "animate-spin")} />
          </button>
          {canManage ? (
            <button
              type="button"
              onClick={() => {
                if (!confirmDiscardDirty()) {
                  return;
                }
                setDirty(false);
                clearSelection();
                setMode("create");
              }}
              className="orbit-btn orbit-btn--primary"
            >
              <Plus className="h-4 w-4" />
              新增智能体
            </button>
          ) : null}
          {onLogout ? (
            <button
              type="button"
              aria-label="退出登录"
              title="退出登录"
              onClick={onLogout}
              className="orbit-btn orbit-btn--icon am-glass-btn"
            >
              <LogOut className="h-4 w-4" />
            </button>
          ) : null}
        </div>
        <div className="am-cover-main">
          <div>
            <p className="am-cover-eyebrow">ORBIT 舰队</p>
            <h1 className="am-cover-title">智能体管理</h1>
            <p className="am-cover-description">调度本机与远程工作区里的每一个智能体。</p>
          </div>
          <FleetStats stats={stats} />
        </div>
      </header>

      <div className="am-body">
        {manager.error ? (
          <div role="alert" className="am-banner" data-tone="danger">{manager.error}</div>
        ) : null}
        {manager.notice ? (
          <div className="am-banner" data-tone="success">{manager.notice}</div>
        ) : null}

        <div
          ref={layoutRef}
          className="am-layout"
          style={{
            gridTemplateColumns: `minmax(${LIST_MIN_WIDTH}px, 1fr) ${RESIZER_WIDTH}px ${inspectorWidth}px`,
          }}
        >
          <div className="am-list-island orbit-island">
            <div className="am-list-head">
              <div className="orbit-segmented orbit-segmented--accent">
                {STATUS_FILTERS.map((filter) => (
                  <button
                    key={filter.id}
                    type="button"
                    aria-pressed={statusFilter === filter.id}
                    onClick={() => setStatusFilter(filter.id)}
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
              {selectedAliases.size > 0 ? (
                <div className="am-bulk">
                  <span className="am-bulk-count">已选 {selectedAliases.size}</span>
                  <button
                    type="button"
                    onClick={() => void runBulkAction("start")}
                    className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                  >
                    <Play className="h-3.5 w-3.5" />
                    批量启动
                  </button>
                  <button
                    type="button"
                    onClick={() => void runBulkAction("stop")}
                    className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                  >
                    <Square className="h-3.5 w-3.5" />
                    批量停止
                  </button>
                  <button
                    type="button"
                    onClick={() => void runBulkAction("delete")}
                    className="orbit-btn orbit-btn--ghost orbit-btn--sm am-tone-danger"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    批量删除
                  </button>
                </div>
              ) : (
                <span className="am-list-count ml-auto">{visibleBots.length} / {stats.total} 个智能体</span>
              )}
            </div>
            <section
              data-testid="desktop-bot-manager-list"
              tabIndex={0}
              onKeyDown={handleTableKeyDown}
              className="am-list-scroll"
            >
              {manager.loading ? (
                <div className="am-empty">加载中...</div>
              ) : visibleBots.length === 0 ? (
                <div className="am-empty">没有匹配的智能体</div>
              ) : (
                <table aria-label="智能体舰队" className="am-table">
                  <thead>
                    <tr>
                      <th className="w-11">
                        <button
                          type="button"
                          aria-label="选择当前可见智能体"
                          title="选择当前可见智能体"
                          onClick={selectVisibleBots}
                          className="orbit-btn orbit-btn--ghost orbit-btn--icon orbit-btn--sm"
                        >
                          <CheckSquare className="h-3.5 w-3.5" />
                        </button>
                      </th>
                      <th className="w-[28%]">智能体</th>
                      <th className="w-[124px]">状态</th>
                      <th className="w-[128px]">类型</th>
                      <th>工作目录</th>
                      <th className="w-[76px] text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleBots.map((bot) => {
                      const focused = mode !== "create" && focusedBot?.alias === bot.alias;
                      const checked = selectedAliases.has(bot.alias);
                      const issues = detectBotIssues(bot, manager.bots);
                      const runtimeBackend = getRuntimeBackend(bot);

                      return (
                        <tr
                          key={bot.alias}
                          aria-selected={focused}
                          data-checked={checked ? "true" : undefined}
                          className="am-row"
                        >
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`选择 ${bot.alias}`}
                              checked={checked}
                              onChange={() => toggleBotSelection(bot.alias)}
                              className="am-check ml-1.5"
                            />
                          </td>
                          <td>
                            <button
                              type="button"
                              aria-label={`聚焦 ${bot.alias}`}
                              onClick={() => focusBot(bot.alias)}
                              onDoubleClick={() => {
                                if (!isBotOffline(bot)) {
                                  onSelect(bot.alias);
                                }
                              }}
                              className="am-identity-btn"
                            >
                              <FleetAvatar alias={bot.alias} />
                              <span className="min-w-0 flex-1">
                                <span className="am-name-line">
                                  <span className="am-name">{bot.alias}</span>
                                  {renderBotTags(bot, { remote: true })}
                                </span>
                                {issues.length > 0 ? (
                                  <span className="am-issues">
                                    {issues.slice(0, 2).map((issue) => (
                                      <span key={issue.code} className="am-tag" data-tone={issue.severity === "warning" ? "warning" : undefined}>
                                        {issue.label}
                                      </span>
                                    ))}
                                  </span>
                                ) : null}
                              </span>
                            </button>
                          </td>
                          <td>
                            <div className="am-status">
                              {bot.status === "unread" ? <FleetStatusChip status="unread" /> : null}
                              <FleetStatusChip status={managerPillStatus(bot)} />
                            </div>
                          </td>
                          <td>
                            <div className="am-type">
                              <span aria-hidden="true" className="am-type-mark" style={getBotIdentityTextStyle(bot.cliType)} />
                              {runtimeBackend === "cli" ? `CLI / ${cliTypeLabel(bot.cliType)}` : "原生 agent"}
                            </div>
                          </td>
                          <td>
                            <div className="am-path" title={workspaceLabel(bot)}>
                              {workspaceLabel(bot) || "未设置"}
                            </div>
                          </td>
                          <td>
                            <div className="am-row-actions">
                              <button
                                type="button"
                                aria-label="从表格进入"
                                title="进入"
                                disabled={isBotOffline(bot)}
                                onClick={() => onSelect(bot.alias)}
                                className="orbit-btn orbit-btn--ghost orbit-btn--icon orbit-btn--sm disabled:cursor-not-allowed"
                              >
                                <LogIn className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                aria-label="打开配置"
                                title="配置"
                                disabled={Boolean(bot.archived)}
                                onClick={() => {
                                  focusBot(bot.alias);
                                  setInspectorTab("config");
                                }}
                                className="orbit-btn orbit-btn--ghost orbit-btn--icon orbit-btn--sm"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </section>
          </div>

          <div
            role="separator"
            aria-label="调整智能体列表和详情宽度"
            aria-orientation="vertical"
            aria-valuemin={INSPECTOR_MIN_WIDTH}
            aria-valuemax={INSPECTOR_MAX_WIDTH}
            aria-valuenow={inspectorWidth}
            title="拖动调整左右宽度"
            onPointerDown={startPaneResize}
            className="am-resizer"
          >
            <span />
          </div>

          <aside className="am-inspector orbit-island orbit-island--reading">
            {mode === "create" ? (
              <AgentCreateForm
                layout="panel"
                description="创建后会出现在左侧列表。"
                client={manager.client}
                bots={manager.bots}
                savingAction={manager.savingAction}
                onCreate={manager.createBot}
                canManage={canManage}
                canCreateWorkdirDirectory={canCreateWorkdirDirectory}
                canRunUnsafeCli={canRunUnsafeCli}
                nativeAgentFeatureEnabled={nativeAgentFeatureEnabled}
                onCreated={(alias) => {
                  setDirty(false);
                  setFocusedAlias(alias);
                  setMode("inspect");
                  setInspectorTab("overview");
                }}
                onCancel={() => {
                  if (!confirmDiscardDirty()) {
                    return;
                  }
                  setDirty(false);
                  setMode("inspect");
                }}
                onDirtyChange={setDirty}
              />
            ) : selectedBots.length > 0 ? (
              <BulkSummaryPanel selectedBots={selectedBots} />
            ) : focusedBot ? (
              <div>
                {renderInspectorTabs()}
                {inspectorTab === "config" && !focusedBot.archived ? (
                  <EditPanel
                    bot={focusedBot}
                    manager={manager}
                    canManage={canManage}
                    canConfigureBot={canManage || focusedBot.canOperate !== false}
                    canCreateWorkdirDirectory={canCreateWorkdirDirectory}
                    nativeAgentFeatureEnabled={nativeAgentFeatureEnabled}
                    onCancel={() => {
                      setDirty(false);
                      setInspectorTab("overview");
                    }}
                    onSaved={(alias) => {
                      setDirty(false);
                      setFocusedAlias(alias);
                      setInspectorTab("overview");
                    }}
                    onOpenConversation={onSelect}
                    onDirtyChange={setDirty}
                  />
                ) : (
                  <div>
                    <div className="am-detail-head">
                      <FleetAvatar alias={focusedBot.alias} large />
                      <div className="min-w-0 flex-1">
                        <h2 className="am-detail-title">{focusedBot.alias}</h2>
                        <div className="am-name-line mt-1.5">
                          <FleetStatusChip status={managerPillStatus(focusedBot)} />
                          {renderBotTags(focusedBot)}
                          {focusedBotIssues.slice(0, 2).map((issue) => (
                            <span key={issue.code} className="am-tag" data-tone={issue.severity === "warning" ? "warning" : undefined}>
                              {issue.label}
                            </span>
                          ))}
                        </div>
                        <div className="am-detail-sub">
                          {getRuntimeBackend(focusedBot) === "cli" ? `CLI / ${cliTypeLabel(focusedBot.cliType)}` : "原生 agent"}
                        </div>
                      </div>
                    </div>

                    <dl className="am-defs">
                      <div className="am-def">
                        <dt>运行后端</dt>
                        <dd>{runtimeBackendLabel(getRuntimeBackend(focusedBot))}</dd>
                      </div>
                      {getRuntimeBackend(focusedBot) === "cli" ? (
                        <div className="am-def">
                          <dt>CLI 路径</dt>
                          <dd className="am-mono">{focusedBot.cliPath || defaultCliPathForType(focusedBot.cliType)}</dd>
                        </div>
                      ) : (
                        <div className="am-def">
                          <dt>原生 agent</dt>
                          <dd className="text-[var(--muted)]">
                            <div>Provider/Model: 全局配置</div>
                            <div>Pi agent: {focusedBot.nativeAgent?.piAgent || "未设置"}</div>
                          </dd>
                        </div>
                      )}
                      <div className="am-def">
                        <dt>工作目录</dt>
                        <dd>
                          <div className="am-mono">{workspaceLabel(focusedBot)}</div>
                          {focusedBot.remoteWorkspace && <RemoteReconnectButton client={manager.client} botAlias={focusedBot.alias} remote={focusedBot.remoteWorkspace} disabled={focusedBot.canOperate === false} />}
                        </dd>
                      </div>
                      <div className="am-def">
                        <dt>状态</dt>
                        <dd>
                          <BotActivitySummary bot={focusedBot} />
                          {focusedBotIssues.length > 0 ? (
                            <div className="am-issues mt-2">
                              {focusedBotIssues.map((issue) => (
                                <span key={issue.code} className="am-tag" data-tone={issue.severity === "warning" ? "warning" : undefined}>
                                  {issue.label}
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </dd>
                      </div>
                    </dl>

                    <div className="am-detail-actions">
                      <button
                        type="button"
                        aria-label={isBotOffline(focusedBot) ? `${focusedBot.alias} 当前离线，不可进入` : `进入 ${focusedBot.alias}`}
                        disabled={isBotOffline(focusedBot)}
                        onClick={() => onSelect(focusedBot.alias)}
                        className="orbit-btn orbit-btn--primary disabled:cursor-not-allowed"
                      >
                        <LogIn className="h-4 w-4" />
                        进入
                      </button>
                      {canManage ? (
                        <button
                          type="button"
                          aria-label={`编辑 ${focusedBot.alias}`}
                          disabled={Boolean(focusedBot.archived)}
                          onClick={() => setInspectorTab("config")}
                          className="orbit-btn orbit-btn--secondary"
                        >
                          <Pencil className="h-4 w-4" />
                          编辑
                        </button>
                      ) : null}
                      {canManage && !isMainBot(focusedBot) ? (
                        <>
                          <span aria-hidden="true" className="am-detail-actions-sep" />
                          <button
                            type="button"
                            aria-label={isBotArchived(focusedBot)
                              ? `取消归档 ${focusedBot.alias}`
                              : isBotOffline(focusedBot) ? `启动 ${focusedBot.alias}` : `停止 ${focusedBot.alias}`}
                            onClick={() => void (isBotArchived(focusedBot) ? manager.unarchiveBot(focusedBot) : manager.toggleBot(focusedBot))}
                            disabled={manager.savingAction !== ""}
                            className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                          >
                            {isBotArchived(focusedBot)
                              ? <ArchiveRestore className="h-3.5 w-3.5" />
                              : isBotOffline(focusedBot) ? <Play className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
                            {isBotArchived(focusedBot) ? "取消归档" : isBotOffline(focusedBot) ? "启动" : "停止"}
                          </button>
                        </>
                      ) : null}
                      {canManage && !isMainBot(focusedBot) && !isBotArchived(focusedBot) ? (
                        <button
                          type="button"
                          aria-label={`归档 ${focusedBot.alias}`}
                          onClick={() => void manager.archiveBot(focusedBot)}
                          disabled={manager.savingAction !== ""}
                          className="orbit-btn orbit-btn--ghost orbit-btn--sm am-tone-warning"
                        >
                          <Archive className="h-3.5 w-3.5" />
                          归档
                        </button>
                      ) : null}
                      {canManage && !isMainBot(focusedBot) ? (
                        <button
                          type="button"
                          aria-label={`删除 ${focusedBot.alias}`}
                          onClick={() => openDeleteDialog(focusedBot.alias)}
                          disabled={manager.savingAction !== ""}
                          className="orbit-btn orbit-btn--ghost orbit-btn--sm am-tone-danger"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          删除
                        </button>
                      ) : null}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="am-empty">暂无可展示智能体</div>
            )}
          </aside>
        </div>

        {bulkResult ? (
          <footer className="am-footer orbit-island">
            <strong>{bulkResultSummary(bulkResult)}</strong>
            {bulkResult.skipped.map((item) => (
              <span key={`skipped:${item.alias}`} className="am-tag">
                {item.alias}: {item.reason}
              </span>
            ))}
            {bulkResult.failed.map((item) => (
              <span key={`failed:${item.alias}`} className="am-tag" data-tone="danger">
                {item.alias}: {item.message}
              </span>
            ))}
          </footer>
        ) : null}
      </div>
      {pendingDeleteAlias || pendingBulkDeleteCount > 0 ? (
        <DeleteBotDialog
          title={pendingDeleteAlias ? `删除智能体 ${pendingDeleteAlias}` : `批量删除 ${pendingBulkDeleteCount} 个智能体`}
          description={pendingDeleteAlias ? undefined : "可只删智能体，或连历史记录一起删。主 bot 等不可删除项会自动跳过。"}
          deleteHistory={deleteHistory}
          deleteWorkspace={pendingDeleteAlias ? deleteWorkspace : false}
          workspacePath={manager.bots.find((item) => item.alias === pendingDeleteAlias)?.workingDir || ""}
          workspaceConfirmText={deleteWorkspaceConfirmText}
          allowWorkspaceDelete={Boolean(pendingDeleteAlias) && !manager.bots.find((item) => item.alias === pendingDeleteAlias)?.remoteWorkspace}
          busy={pendingDeleteAlias ? manager.savingAction === `${pendingDeleteAlias}:delete` : false}
          onDeleteHistoryChange={setDeleteHistory}
          onDeleteWorkspaceChange={(value) => {
            setDeleteWorkspace(value);
            if (value) {
              setDeleteHistory(true);
            }
            setDeleteWorkspaceConfirmText("");
          }}
          onWorkspaceConfirmTextChange={setDeleteWorkspaceConfirmText}
          onCancel={() => {
            if (pendingDeleteAlias && manager.savingAction === `${pendingDeleteAlias}:delete`) {
              return;
            }
            setPendingDeleteAlias("");
            setPendingBulkDeleteCount(0);
            setDeleteHistory(false);
            setDeleteWorkspace(false);
            setDeleteWorkspaceConfirmText("");
          }}
          onConfirm={() => void (pendingDeleteAlias ? confirmDelete() : confirmBulkDelete())}
        />
      ) : null}
    </main>
  );
}
