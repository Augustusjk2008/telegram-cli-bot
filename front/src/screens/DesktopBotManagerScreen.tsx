import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { clsx } from "clsx";
import {
  CheckSquare,
  FolderOpen,
  LogIn,
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
import { AgentSettingsPanel } from "../components/AgentSettingsPanel";
import { AvatarPicker } from "../components/AvatarPicker";
import { BotCliParamsPanel } from "../components/BotCliParamsPanel";
import { BotActivitySummary } from "../components/BotActivitySummary";
import { ChatAvatar } from "../components/ChatAvatar";
import { ClusterModelTiersPanel } from "../components/ClusterModelTiersPanel";
import { ClusterSetupPanel } from "../components/ClusterSetupPanel";
import { ClusterTemplatePanel } from "../components/ClusterTemplatePanel";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { NativeAgentConfigFields } from "../components/NativeAgentConfigFields";
import { StatusPill } from "../components/StatusPill";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  BotClusterConfig,
  BotSummary,
  ChatExecutionMode,
  CliType,
  CliParamsPayload,
  ClusterStatus,
  UpdateBotWorkdirOptions,
  WorkdirChangeConflict,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  buildExecutionConfig,
  buildBulkActionPlan,
  countBotManagerStats,
  DEFAULT_NATIVE_AGENT_DRAFT,
  detectBotIssues,
  draftFromBot,
  getRuntimeBackend,
  getBotManagerStatus,
  getVisibleManagedBots,
  isBotOffline,
  isMainBot,
  isNativeAgentGloballyEnabled,
  type BulkAction,
  type BulkActionResult,
  type EditDraft,
  type ManagerViewFilter,
} from "./botManagerModel";
import {
  buildCreateDraft,
  defaultCliPathForType,
  useBotManager,
  type CreateDraft,
} from "./useBotManager";

type Props = {
  client?: WebBotClient;
  currentAlias: string | null;
  onSelect: (alias: string) => void;
  onBotsChange?: (bots: BotSummary[]) => void;
  canManage?: boolean;
  canCreateWorkdirDirectory?: boolean;
};

type Mode = "inspect" | "create";
type InspectorTab = "overview" | "config" | "agents";

const LIST_MIN_WIDTH = 520;
const RESIZER_WIDTH = 8;
const INSPECTOR_MIN_WIDTH = 320;
const INSPECTOR_MAX_WIDTH = 720;
const INSPECTOR_DEFAULT_WIDTH = 400;
const DEFAULT_CLUSTER_CONFIG: BotClusterConfig = {
  enabled: false,
  writePolicy: "selected_agents",
  conflictPolicy: "snapshot_diff",
  maxParallelAgents: 2,
  defaultTimeoutSeconds: 600,
  modelTiers: { low: "", medium: "", high: "" },
};

const STATUS_FILTERS: Array<{ id: ManagerViewFilter; label: string }> = [
  { id: "all", label: "全部" },
  { id: "unread", label: "未读" },
  { id: "running", label: "运行中" },
  { id: "busy", label: "处理中" },
  { id: "offline", label: "离线" },
  { id: "attention", label: "需处理" },
];

function managerPillStatus(bot: BotSummary) {
  const status = getBotManagerStatus(bot);
  return status === "unread" ? "online" : status;
}

function normalizeCreateDraft(draft: CreateDraft): CreateDraft {
  const executionConfig = buildExecutionConfig(draft.runtimeBackend);
  const providerInput = draft.nativeAgent?.provider?.trim() || "";
  const providerLooksLikeUrl = /^https?:\/\//i.test(providerInput);
  const baseUrlInput = draft.nativeAgent?.baseUrl?.trim() || "";
  const nativeAgent = {
    ...DEFAULT_NATIVE_AGENT_DRAFT,
    ...(draft.nativeAgent || {}),
    provider: providerLooksLikeUrl ? "codeflow" : providerInput,
    model: draft.nativeAgent?.model?.trim() || "",
    piAgent: draft.nativeAgent?.piAgent?.trim() || "",
    baseUrl: providerLooksLikeUrl && !baseUrlInput ? providerInput.replace(/\/+$/, "") : baseUrlInput.replace(/\/+$/, ""),
    apiKey: draft.nativeAgent?.apiKey?.trim() || "",
    clearApiKey: Boolean(draft.nativeAgent?.clearApiKey),
  };
  return {
    alias: draft.alias.trim(),
    botMode: draft.botMode,
    cliType: draft.cliType,
    cliPath: draft.cliPath.trim(),
    workingDir: draft.workingDir.trim(),
    avatarName: draft.avatarName.trim(),
    runtimeBackend: draft.runtimeBackend,
    supportedExecutionModes: executionConfig.supportedExecutionModes,
    defaultExecutionMode: executionConfig.defaultExecutionMode,
    nativeAgent,
  };
}

function normalizeEditDraft(draft: EditDraft): EditDraft {
  const providerInput = draft.nativeAgent.provider.trim();
  const providerLooksLikeUrl = /^https?:\/\//i.test(providerInput);
  const baseUrlInput = draft.nativeAgent.baseUrl.trim();
  return {
    alias: draft.alias.trim(),
    botMode: draft.botMode,
    cliType: draft.cliType,
    cliPath: draft.cliPath.trim(),
    workingDir: draft.workingDir.trim(),
    avatarName: draft.avatarName.trim(),
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
  };
}

function createDraftEquals(left: CreateDraft, right: CreateDraft) {
  return JSON.stringify(normalizeCreateDraft(left)) === JSON.stringify(normalizeCreateDraft(right));
}

function cliPathPlaceholder(cliType: CliType) {
  return defaultCliPathForType(cliType);
}

function runtimeBackendLabel(runtimeBackend: ChatExecutionMode) {
  return runtimeBackend === "native_agent" ? "原生 agent" : "CLI";
}

function issueClassName(severity: "info" | "warning") {
  return severity === "warning"
    ? "border-amber-200 bg-amber-50 text-amber-700"
    : "border-[var(--border)] bg-[var(--surface-strong)] text-[var(--muted)]";
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
    <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
      <div>切换工作目录会清空 {conflict.historyCount} 条聊天消息。</div>
      <div className="mt-1 break-all text-xs text-amber-700">
        {conflict.currentWorkingDir} {"->"} {conflict.requestedWorkingDir}
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onConfirm}
          className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          确认切换
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-amber-300 px-3 py-1.5 text-sm hover:bg-amber-100"
        >
          取消
        </button>
      </div>
    </div>
  );
}

function CreatePanel({
  manager,
  canManage,
  canCreateWorkdirDirectory,
  nativeAgentFeatureEnabled,
  onCreated,
  onDirtyChange,
}: {
  manager: ReturnType<typeof useBotManager>;
  canManage: boolean;
  canCreateWorkdirDirectory: boolean;
  nativeAgentFeatureEnabled: boolean | null;
  onCreated: (alias: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const baseDraft = useMemo(() => buildCreateDraft("codex", manager.bots), [manager.bots]);
  const [draft, setDraft] = useState<CreateDraft>(() => buildCreateDraft());
  const [showWorkdirPicker, setShowWorkdirPicker] = useState(false);
  const dirty = !createDraftEquals(draft, baseDraft);
  const directoryBrowserAlias = manager.bots.find((bot) => isMainBot(bot))?.alias || manager.bots[0]?.alias || "main";

  useEffect(() => {
    if (manager.bots.length === 0) {
      return;
    }
    setDraft((prev) => {
      const userEditedPath = prev.cliPath.trim() && prev.cliPath.trim() !== defaultCliPathForType(prev.cliType);
      if (prev.alias.trim() || prev.workingDir.trim() || prev.avatarName.trim() || userEditedPath) {
        return prev;
      }
      return { ...prev, cliPath: buildCreateDraft(prev.cliType, manager.bots).cliPath };
    });
  }, [manager.bots]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (nativeAgentFeatureEnabled === false && draft.runtimeBackend === "native_agent") {
      setDraft((prev) => ({
        ...prev,
        runtimeBackend: "cli",
        supportedExecutionModes: ["cli"],
        defaultExecutionMode: "cli",
      }));
    }
  }, [draft.runtimeBackend, nativeAgentFeatureEnabled]);

  async function submit() {
    const created = await manager.createBot(draft);
    if (created) {
      setDraft(buildCreateDraft(draft.cliType, manager.bots));
      onCreated(created.alias);
    }
  }

  const nativeAgentOptionVisible = nativeAgentFeatureEnabled !== false || draft.runtimeBackend === "native_agent";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">新增智能体</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">创建后会出现在左侧列表。</p>
        </div>
        <AvatarPicker
          assets={manager.avatarAssets}
          selectedName={draft.avatarName}
          previewAlt="新智能体头像预览"
          selectLabel="新智能体头像"
          disabled={!canManage || manager.savingAction !== ""}
          onSelect={(avatarName) => setDraft((prev) => ({ ...prev, avatarName }))}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">别名</span>
          <input
            aria-label="新智能体别名"
            value={draft.alias}
            onChange={(event) => setDraft((prev) => ({ ...prev, alias: event.target.value }))}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
            placeholder="team3"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">模式</span>
          <select
            aria-label="新智能体模式"
            value={draft.botMode}
            onChange={(event) => {
              const botMode = event.target.value as CreateDraft["botMode"];
              setDraft((prev) => ({
                ...prev,
                botMode,
              }));
            }}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
          >
            <option value="cli">cli</option>
            <option value="assistant">assistant</option>
          </select>
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">运行后端</span>
          <select
            aria-label="运行后端"
            value={draft.runtimeBackend}
            onChange={(event) => {
              const runtimeBackend = event.target.value as CreateDraft["runtimeBackend"];
              setDraft((prev) => ({
                ...prev,
                runtimeBackend,
                supportedExecutionModes: [runtimeBackend],
                defaultExecutionMode: runtimeBackend,
              }));
            }}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
          >
            <option value="cli">CLI</option>
            {nativeAgentOptionVisible ? <option value="native_agent">原生 agent</option> : null}
          </select>
          {nativeAgentFeatureEnabled === false ? (
            <p className="text-xs text-[var(--muted)]">原生 agent 全局未启用</p>
          ) : null}
        </label>
        {draft.runtimeBackend === "cli" ? (
          <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">CLI 类型</span>
          <select
            aria-label="新智能体 CLI 类型"
            value={draft.cliType}
            onChange={(event) => {
              const cliType = event.target.value as CliType;
              setDraft((prev) => ({ ...prev, cliType, cliPath: buildCreateDraft(cliType, manager.bots).cliPath }));
            }}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
          >
            <option value="codex">codex</option>
            <option value="claude">claude</option>
            <option value="kimi">kimi</option>
          </select>
          </label>
        ) : null}
        {draft.runtimeBackend === "cli" ? (
          <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">CLI 路径</span>
          <input
            aria-label="新智能体 CLI 路径"
            value={draft.cliPath}
            onChange={(event) => setDraft((prev) => ({ ...prev, cliPath: event.target.value }))}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
            placeholder={cliPathPlaceholder(draft.cliType)}
          />
          </label>
        ) : null}
      </div>
      {draft.runtimeBackend === "native_agent" ? (
        <NativeAgentConfigFields
          provider={draft.nativeAgent?.provider || DEFAULT_NATIVE_AGENT_DRAFT.provider}
          model={draft.nativeAgent?.model || DEFAULT_NATIVE_AGENT_DRAFT.model}
          piAgent={draft.nativeAgent?.piAgent || DEFAULT_NATIVE_AGENT_DRAFT.piAgent}
          baseUrl={draft.nativeAgent?.baseUrl || DEFAULT_NATIVE_AGENT_DRAFT.baseUrl}
          apiKey={draft.nativeAgent?.apiKey || ""}
          disabled={!canManage || manager.savingAction !== ""}
          onNativeAgentChange={(patch) => setDraft((prev) => ({
            ...prev,
            nativeAgent: {
              ...DEFAULT_NATIVE_AGENT_DRAFT,
              ...(prev.nativeAgent || {}),
              ...patch,
            },
          }))}
        />
      ) : null}
      <label className="block space-y-1 text-sm">
        <span className="text-[var(--muted)]">工作目录</span>
        <div className="flex gap-2">
          <input
            aria-label="新智能体工作目录"
            value={draft.workingDir}
            onChange={(event) => setDraft((prev) => ({ ...prev, workingDir: event.target.value }))}
            className="h-9 min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
            placeholder="C:\\workspace\\team3"
          />
          <button
            type="button"
            aria-label="浏览新智能体工作目录"
            onClick={() => setShowWorkdirPicker(true)}
            disabled={!canManage || manager.savingAction !== ""}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[var(--border)] px-3 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <FolderOpen className="h-4 w-4" />
            浏览目录
          </button>
        </div>
      </label>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!canManage || manager.savingAction !== ""}
          className="inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium tcb-solid-accent disabled:opacity-60"
        >
          <Plus className="h-4 w-4" />
          {manager.savingAction === "create" ? "创建中..." : "创建智能体"}
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
    </div>
  );
}

function EditPanel({
  bot,
  manager,
  canManage,
  canCreateWorkdirDirectory,
  nativeAgentFeatureEnabled,
  onCancel,
  onSaved,
  onDirtyChange,
}: {
  bot: BotSummary;
  manager: ReturnType<typeof useBotManager>;
  canManage: boolean;
  canCreateWorkdirDirectory: boolean;
  nativeAgentFeatureEnabled: boolean | null;
  onCancel: () => void;
  onSaved: (alias: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [draft, setDraft] = useState<EditDraft>(draftFromBot(bot));
  const [showWorkdirPicker, setShowWorkdirPicker] = useState(false);
  const [pendingWorkdirConflict, setPendingWorkdirConflict] = useState<WorkdirChangeConflict | null>(null);
  const [clusterStatus, setClusterStatus] = useState<ClusterStatus | null>(null);
  const [clusterConfig, setClusterConfig] = useState<BotClusterConfig>(() => clusterConfigFromBot(bot));
  const [cliParams, setCliParams] = useState<CliParamsPayload | null>(null);
  const [clusterSaving, setClusterSaving] = useState(false);
  const [clusterError, setClusterError] = useState("");
  const dirty = !draftEquals(draft, draftFromBot(bot));
  const directoryBrowserAlias = manager.bots.find((item) => isMainBot(item))?.alias || manager.bots[0]?.alias || "main";
  const nativeAgentOptionVisible = nativeAgentFeatureEnabled !== false || draft.runtimeBackend === "native_agent";

  useEffect(() => {
    setDraft(draftFromBot(bot));
    setClusterConfig(clusterConfigFromBot(bot));
    setPendingWorkdirConflict(null);
  }, [bot]);

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
    if ((bot.botMode || "cli") !== "cli") {
      setClusterStatus(null);
      setCliParams(null);
      return;
    }
    let cancelled = false;
    setClusterError("");
    void Promise.all([
      manager.client.getClusterStatus(bot.alias),
      manager.client.getCliParams(bot.alias),
    ])
      .then(([nextCluster, nextCliParams]) => {
        if (!cancelled) {
          setClusterStatus(nextCluster);
          setCliParams(nextCliParams);
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
  }, [bot.alias, bot.botMode, manager.client]);

  async function submit(options: UpdateBotWorkdirOptions = {}) {
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

  async function saveCluster(patch: Partial<BotClusterConfig>) {
    const next: BotClusterConfig = {
      ...clusterConfig,
      ...patch,
      modelTiers: {
        ...clusterConfig.modelTiers,
        ...(patch.modelTiers || {}),
      },
    };
    setClusterSaving(true);
    setClusterError("");
    try {
      const result = await manager.client.updateClusterConfig(bot.alias, {
        enabled: next.enabled,
        writePolicy: next.writePolicy,
        conflictPolicy: next.conflictPolicy,
        maxParallelAgents: next.maxParallelAgents,
        defaultTimeoutSeconds: next.defaultTimeoutSeconds,
        modelTiers: next.modelTiers,
      });
      setClusterConfig(result.cluster);
      setClusterStatus(result.status);
    } catch (err) {
      setClusterError(err instanceof Error ? err.message : "保存集群配置失败");
    } finally {
      setClusterSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">编辑 {bot.alias}</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">横屏版支持在右侧直接编辑和保存。</p>
        </div>
        <AvatarPicker
          assets={manager.avatarAssets}
          selectedName={draft.avatarName}
          previewAlt={`${bot.alias} 头像`}
          selectLabel={`${bot.alias} 头像`}
          disabled={!canManage || manager.savingAction !== ""}
          onSelect={(avatarName) => setDraft((prev) => ({ ...prev, avatarName }))}
        />
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
          <span className="text-[var(--muted)]">模式</span>
          <select
            aria-label="智能体模式"
            value={draft.botMode}
            disabled
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm opacity-60"
          >
            <option value="cli">cli</option>
            <option value="assistant">assistant</option>
          </select>
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
            {nativeAgentOptionVisible ? <option value="native_agent">原生 agent</option> : null}
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
            onChange={(event) => setDraft((prev) => ({ ...prev, cliType: event.target.value as CliType }))}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
          >
            <option value="codex">codex</option>
            <option value="claude">claude</option>
            <option value="kimi">kimi</option>
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
      <label className="block space-y-1 text-sm">
        <span className="text-[var(--muted)]">工作目录</span>
        <div className="flex gap-2">
          <input
            aria-label="智能体工作目录"
            value={draft.workingDir}
            disabled={!canManage}
            onChange={(event) => setDraft((prev) => ({ ...prev, workingDir: event.target.value }))}
            className="h-9 min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
          />
          <button
            type="button"
            aria-label="浏览智能体工作目录"
            onClick={() => setShowWorkdirPicker(true)}
            disabled={!canManage || manager.savingAction !== ""}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[var(--border)] px-3 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <FolderOpen className="h-4 w-4" />
            浏览目录
          </button>
        </div>
      </label>
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
          disabled={!canManage || manager.savingAction !== ""}
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

      {(bot.botMode || "cli") === "cli" && draft.runtimeBackend === "cli" ? (
        <div className="space-y-4 border-t border-[var(--border)] pt-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="inline-flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={Boolean(clusterConfig.enabled)}
                disabled={!canManage || clusterSaving || !clusterStatus}
                onChange={(event) => {
                  if (!clusterStatus) return;
                  void saveCluster({ enabled: event.target.checked });
                }}
              />
              启用集群模式
            </label>
            {clusterSaving ? <span className="text-xs text-[var(--muted)]">保存中...</span> : null}
          </div>
          {clusterError ? <div className="text-sm text-red-700">{clusterError}</div> : null}
          {clusterStatus ? (
            <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-base font-semibold text-[var(--text)]">集群运行参数</h2>
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="grid gap-1 text-sm">
                  <span className="font-medium text-[var(--text)]">并发子 agent 数</span>
                  <select
                    aria-label="并发子 agent 数"
                    value={clusterConfig.maxParallelAgents}
                    disabled={!canManage || clusterSaving}
                    onChange={(event) => void saveCluster({ maxParallelAgents: Number(event.target.value) })}
                    className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                  >
                    {[1, 2, 3, 4, 5, 6, 7, 8].map((count) => (
                      <option key={count} value={count}>{count}</option>
                    ))}
                  </select>
                </label>
              </div>
            </section>
          ) : null}
          {clusterStatus ? (
            <ClusterModelTiersPanel
              value={clusterConfig.modelTiers}
              modelOptions={cliParams?.schema.model?.enum ?? []}
              disabled={!canManage || clusterSaving}
              onChange={(modelTiers) => void saveCluster({ modelTiers })}
            />
          ) : null}
          <ClusterTemplatePanel
            botAlias={bot.alias}
            client={manager.client}
            canManage={canManage && !clusterSaving}
            onApplied={() => {
              void manager.loadBots();
              void manager.client.getClusterStatus(bot.alias).then(setClusterStatus).catch(() => undefined);
            }}
          />
          <ClusterSetupPanel botAlias={bot.alias} client={manager.client} canManage={canManage} />
        </div>
      ) : null}

      {draft.runtimeBackend === "cli" ? (
        <BotCliParamsPanel
          botAlias={bot.alias}
          client={manager.client}
          canManage={canManage}
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
  busy,
  onDeleteHistoryChange,
  onCancel,
  onConfirm,
}: {
  title: string;
  description?: string;
  deleteHistory: boolean;
  busy: boolean;
  onDeleteHistoryChange: (value: boolean) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-[var(--surface)] p-5 shadow-[var(--shadow-card)]">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">{description || "可只删智能体，或连历史记录一起删。"}</p>
        <label className="mt-4 flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={deleteHistory}
            onChange={(event) => onDeleteHistoryChange(event.target.checked)}
            disabled={busy}
            className="mt-0.5 h-4 w-4 rounded border-[var(--border)]"
          />
          <span>同时删除历史记录（包含所有子 agents）</span>
        </label>
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
            disabled={busy}
            className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
          >
            {busy ? "删除中..." : "删除"}
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
  onBotsChange,
  canManage = true,
  canCreateWorkdirDirectory = true,
}: Props) {
  const manager = useBotManager({ client, onBotsChange });
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
  }

  function openBulkDeleteDialog(count: number) {
    setPendingDeleteAlias("");
    setPendingBulkDeleteCount(count);
    setDeleteHistory(false);
  }

  async function confirmDelete() {
    if (!pendingDeleteAlias) {
      return;
    }
    const bot = manager.bots.find((item) => item.alias === pendingDeleteAlias);
    if (!bot) {
      setPendingDeleteAlias("");
      setDeleteHistory(false);
      return;
    }
    const removed = await manager.deleteBot(bot, { deleteHistory });
    if (removed) {
      setPendingDeleteAlias("");
      setPendingBulkDeleteCount(0);
      setDeleteHistory(false);
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
      { id: "agents", label: "Agent" },
    ];

    return (
      <div className="mb-3 inline-flex rounded-md border border-[var(--border)] bg-[var(--surface-strong)] p-0.5">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            aria-pressed={inspectorTab === tab.id}
            onClick={() => {
              if (tab.id !== inspectorTab && !confirmDiscardDirty()) {
                return;
              }
              setDirty(false);
              setMode("inspect");
              setInspectorTab(tab.id);
            }}
            className={clsx(
              "h-8 rounded px-2 text-xs",
              inspectorTab === tab.id
                ? "tcb-selected-accent"
                : "text-[var(--muted)] hover:bg-[var(--surface)] hover:text-[var(--text)]",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
    );
  }

  return (
    <main
      data-testid="desktop-bot-manager-screen"
      className="flex h-[100dvh] min-h-0 flex-col bg-[var(--bg)] text-[var(--text)]"
    >
      <header className="border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">智能体管理</h1>
          <div className="flex items-center gap-3 text-xs text-[var(--muted)]">
            <span>总数 {stats.total}</span>
            <span>在线 {stats.online}</span>
            <span>处理中 {stats.busy}</span>
            <span>离线 {stats.offline}</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div className="relative w-[320px]">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted)]" />
              <input
                aria-label="搜索智能体"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索智能体、目录、agent"
                className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--bg)] pl-8 pr-3 text-sm outline-none focus:border-[var(--accent)]"
              />
            </div>
            {selectedAliases.size > 0 ? (
              <div className="flex items-center gap-1 border-r border-[var(--border)] pr-2">
                <span className="px-1 text-xs text-[var(--muted)]">已选 {selectedAliases.size}</span>
                <button
                  type="button"
                  onClick={() => void runBulkAction("start")}
                  className="inline-flex h-8 items-center gap-1 rounded-md border border-[var(--border)] px-2 text-xs hover:bg-[var(--surface-strong)]"
                >
                  <Play className="h-3.5 w-3.5" />
                  批量启动
                </button>
                <button
                  type="button"
                  onClick={() => void runBulkAction("stop")}
                  className="inline-flex h-8 items-center gap-1 rounded-md border border-[var(--border)] px-2 text-xs hover:bg-[var(--surface-strong)]"
                >
                  <Square className="h-3.5 w-3.5" />
                  批量停止
                </button>
                <button
                  type="button"
                  onClick={() => void runBulkAction("delete")}
                  className="inline-flex h-8 items-center gap-1 rounded-md border border-red-200 px-2 text-xs text-red-700 hover:bg-red-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  批量删除
                </button>
              </div>
            ) : null}
            <button
              type="button"
              aria-label="刷新智能体"
              onClick={() => {
                if (!confirmDiscardDirty()) {
                  return;
                }
                setDirty(false);
                void manager.loadBots();
              }}
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-strong)]"
            >
              <RefreshCw className="h-4 w-4" />
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
                className="inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium tcb-solid-accent"
              >
                <Plus className="h-4 w-4" />
                新增智能体
              </button>
            ) : null}
          </div>
        </div>
        <div className="mt-3 inline-flex rounded-md border border-[var(--border)] bg-[var(--surface-strong)] p-0.5">
          {STATUS_FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              aria-pressed={statusFilter === filter.id}
              onClick={() => setStatusFilter(filter.id)}
              className={clsx(
                "h-8 rounded px-2 text-xs",
                statusFilter === filter.id
                  ? "tcb-selected-accent"
                  : "text-[var(--muted)] hover:bg-[var(--surface)] hover:text-[var(--text)]",
              )}
            >
              {filter.label}
            </button>
          ))}
        </div>
      </header>

      {manager.error ? (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{manager.error}</div>
      ) : null}
      {manager.notice ? (
        <div className="border-b border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">{manager.notice}</div>
      ) : null}

      <div
        ref={layoutRef}
        className="grid min-h-0 flex-1"
        style={{
          gridTemplateColumns: `minmax(${LIST_MIN_WIDTH}px, 1fr) ${RESIZER_WIDTH}px ${inspectorWidth}px`,
        }}
      >
        <section
          data-testid="desktop-bot-manager-list"
          tabIndex={0}
          onKeyDown={handleTableKeyDown}
          className="min-h-0 overflow-auto bg-[var(--surface)] focus:outline-none"
        >
          {manager.loading ? (
            <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">加载中...</div>
          ) : visibleBots.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">没有匹配的智能体</div>
          ) : (
            <table aria-label="智能体舰队" className="w-full min-w-[680px] table-fixed border-separate border-spacing-0 text-sm">
              <thead className="sticky top-0 z-10 bg-[var(--surface)] text-left text-xs text-[var(--muted)]">
                <tr className="border-b border-[var(--border)]">
                  <th className="w-10 px-3 py-2">
                    <button
                      type="button"
                      aria-label="选择当前可见智能体"
                      onClick={selectVisibleBots}
                      className="inline-flex h-6 w-6 items-center justify-center rounded hover:bg-[var(--surface-strong)]"
                    >
                      <CheckSquare className="h-4 w-4" />
                    </button>
                  </th>
                  <th className="w-[220px] px-2 py-2">智能体</th>
                  <th className="w-[110px] px-2 py-2">状态</th>
                  <th className="w-[120px] px-2 py-2">类型</th>
                  <th className="px-2 py-2">工作目录</th>
                  <th className="w-[96px] px-2 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {visibleBots.map((bot) => {
                  const focused = mode !== "create" && focusedBot?.alias === bot.alias;
                  const current = bot.alias === currentAlias;
                  const checked = selectedAliases.has(bot.alias);
                  const issues = detectBotIssues(bot, manager.bots);
                  const runtimeBackend = getRuntimeBackend(bot);

                  return (
                    <tr
                      key={bot.alias}
                      aria-selected={focused}
                      className={clsx(
                        "border-b border-[var(--border)]",
                        focused ? "tcb-soft-selected" : "hover:bg-[var(--surface-strong)]",
                      )}
                    >
                      <td className="px-3 py-2 align-middle">
                        <input
                          type="checkbox"
                          aria-label={`选择 ${bot.alias}`}
                          checked={checked}
                          onChange={() => toggleBotSelection(bot.alias)}
                          className="h-4 w-4 rounded border-[var(--border)]"
                        />
                      </td>
                      <td className="px-2 py-2 align-middle">
                        <button
                          type="button"
                          aria-label={`聚焦 ${bot.alias}`}
                          onClick={() => focusBot(bot.alias)}
                          onDoubleClick={() => {
                            if (!isBotOffline(bot)) {
                              onSelect(bot.alias);
                            }
                          }}
                          className="flex w-full min-w-0 items-center gap-2 text-left"
                        >
                          <ChatAvatar alt={`${bot.alias} 头像`} avatarName={bot.avatarName} kind="bot" size={28} />
                          <span className="min-w-0">
                            <span className="flex min-w-0 items-center gap-1.5">
                              <span className="truncate font-semibold">{bot.alias}</span>
                              {isMainBot(bot) ? <span className="rounded border border-[var(--border)] px-1 text-[10px] text-[var(--muted)]">主</span> : null}
                              {current ? <span className="rounded border border-transparent px-1 text-[10px] tcb-selected-accent">当前</span> : null}
                            </span>
                            {issues.length > 0 ? (
                              <span className="mt-1 flex flex-wrap gap-1">
                                {issues.slice(0, 2).map((issue) => (
                                  <span key={issue.code} className={clsx("rounded border px-1 py-0.5 text-[10px]", issueClassName(issue.severity))}>
                                    {issue.label}
                                  </span>
                                ))}
                              </span>
                            ) : null}
                          </span>
                        </button>
                      </td>
                      <td className="px-2 py-2 align-middle">
                        <div className="flex flex-col items-start gap-1">
                          {bot.status === "unread" ? <StatusPill status="unread" /> : null}
                          <StatusPill status={managerPillStatus(bot)} />
                        </div>
                      </td>
                      <td className={clsx(
                        "px-2 py-2 align-middle text-xs",
                        focused ? "text-[var(--text)]" : "text-[var(--muted)]",
                      )}>
                        {bot.botMode || "cli"} · {runtimeBackend === "cli" ? `CLI / ${bot.cliType}` : "原生 agent"}
                      </td>
                      <td
                        className={clsx(
                          "truncate px-2 py-2 align-middle font-mono text-xs",
                          focused ? "text-[var(--text)]" : "text-[var(--muted)]",
                        )}
                        title={bot.workingDir}
                      >
                        {bot.workingDir || "未设置"}
                      </td>
                      <td className="px-2 py-2 align-middle">
                        <div className="flex justify-end gap-1">
                          <button
                            type="button"
                            aria-label="从表格进入"
                            disabled={isBotOffline(bot)}
                            onClick={() => onSelect(bot.alias)}
                            className="inline-flex h-7 w-7 items-center justify-center rounded border border-[var(--border)] hover:bg-[var(--surface-strong)] disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <LogIn className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            aria-label="打开配置"
                            onClick={() => {
                              focusBot(bot.alias);
                              setInspectorTab("config");
                            }}
                            className="inline-flex h-7 w-7 items-center justify-center rounded border border-[var(--border)] hover:bg-[var(--surface-strong)]"
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

        <div
          role="separator"
          aria-label="调整智能体列表和详情宽度"
          aria-orientation="vertical"
          aria-valuemin={INSPECTOR_MIN_WIDTH}
          aria-valuemax={INSPECTOR_MAX_WIDTH}
          aria-valuenow={inspectorWidth}
          title="拖动调整左右宽度"
          onPointerDown={startPaneResize}
          className="group flex cursor-col-resize items-stretch justify-center border-x border-[var(--border)] bg-[var(--bg)] hover:bg-[var(--surface-strong)]"
        >
          <span className="my-2 w-px bg-[var(--border)] group-hover:bg-[var(--accent)]" />
        </div>

        <aside className="min-h-0 overflow-y-auto bg-[var(--bg)] p-4">
          {mode === "create" ? (
            <CreatePanel
              manager={manager}
              canManage={canManage}
              canCreateWorkdirDirectory={canCreateWorkdirDirectory}
              nativeAgentFeatureEnabled={nativeAgentFeatureEnabled}
              onCreated={(alias) => {
                setDirty(false);
                setFocusedAlias(alias);
                setMode("inspect");
                setInspectorTab("overview");
              }}
              onDirtyChange={setDirty}
            />
          ) : selectedBots.length > 0 ? (
            <BulkSummaryPanel selectedBots={selectedBots} />
          ) : focusedBot ? (
            <div>
              {renderInspectorTabs()}
              {inspectorTab === "config" ? (
                <EditPanel
                  bot={focusedBot}
                  manager={manager}
                  canManage={canManage}
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
                  onDirtyChange={setDirty}
                />
              ) : inspectorTab === "agents" ? (
                <AgentSettingsPanel
                  botAlias={focusedBot.alias}
                  botMode={focusedBot.botMode || "cli"}
                  client={client}
                  canManage={canManage}
                />
              ) : (
                <div className="space-y-4">
                  <div className="flex items-start gap-3">
                    <ChatAvatar alt={`${focusedBot.alias} 头像`} avatarName={focusedBot.avatarName} kind="bot" size={44} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h2 className="truncate text-base font-semibold">{focusedBot.alias}</h2>
                        {isMainBot(focusedBot) ? <span className="rounded border border-[var(--border)] px-1.5 py-0.5 text-xs text-[var(--muted)]">主</span> : null}
                        <StatusPill status={managerPillStatus(focusedBot)} />
                      </div>
                      <div className="mt-1 text-sm text-[var(--muted)]">
                        {focusedBot.botMode || "cli"} · {runtimeBackendLabel(getRuntimeBackend(focusedBot))}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
                    <div className="text-xs font-medium text-[var(--muted)]">运行后端</div>
                    <div className="mt-1 text-sm">{runtimeBackendLabel(getRuntimeBackend(focusedBot))}</div>
                  </div>

                  {getRuntimeBackend(focusedBot) === "cli" ? (
                    <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
                      <div className="text-xs font-medium text-[var(--muted)]">CLI 路径</div>
                      <div className="mt-1 break-all font-mono text-xs">{focusedBot.cliPath || focusedBot.cliType}</div>
                    </div>
                  ) : (
                    <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
                      <div className="text-xs font-medium text-[var(--muted)]">原生 agent</div>
                      <div className="mt-1 space-y-1 text-xs text-[var(--muted)]">
                        <div>Provider/Model: 全局配置</div>
                        <div>Pi agent: {focusedBot.nativeAgent?.piAgent || "未设置"}</div>
                      </div>
                    </div>
                  )}

                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
                    <div className="text-xs font-medium text-[var(--muted)]">工作目录</div>
                    <div className="mt-1 break-all font-mono text-xs">{focusedBot.workingDir}</div>
                  </div>

                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
                    <div className="text-xs font-medium text-[var(--muted)]">状态</div>
                    <BotActivitySummary bot={focusedBot} className="mt-1" />
                    {detectBotIssues(focusedBot, manager.bots).length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {detectBotIssues(focusedBot, manager.bots).map((issue) => (
                          <span key={issue.code} className={clsx("rounded border px-1.5 py-0.5 text-xs", issueClassName(issue.severity))}>
                            {issue.label}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      aria-label={isBotOffline(focusedBot) ? `${focusedBot.alias} 当前离线，不可进入` : `进入 ${focusedBot.alias}`}
                      disabled={isBotOffline(focusedBot)}
                      onClick={() => onSelect(focusedBot.alias)}
                      className="inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium tcb-solid-accent disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <LogIn className="h-4 w-4" />
                      进入
                    </button>
                    {canManage ? (
                      <button
                        type="button"
                        aria-label={`编辑 ${focusedBot.alias}`}
                        onClick={() => setInspectorTab("config")}
                        className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[var(--border)] px-3 text-sm hover:bg-[var(--surface-strong)]"
                      >
                        <Pencil className="h-4 w-4" />
                        编辑
                      </button>
                    ) : null}
                    {canManage && !isMainBot(focusedBot) ? (
                      <button
                        type="button"
                        aria-label={isBotOffline(focusedBot) ? `启动 ${focusedBot.alias}` : `停止 ${focusedBot.alias}`}
                        onClick={() => void manager.toggleBot(focusedBot)}
                        disabled={manager.savingAction !== ""}
                        className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[var(--border)] px-3 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        {isBotOffline(focusedBot) ? <Play className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                        {isBotOffline(focusedBot) ? "启动" : "停止"}
                      </button>
                    ) : null}
                    {canManage && !isMainBot(focusedBot) ? (
                      <button
                        type="button"
                        aria-label={`删除 ${focusedBot.alias}`}
                        onClick={() => openDeleteDialog(focusedBot.alias)}
                        disabled={manager.savingAction !== ""}
                        className="inline-flex h-9 items-center gap-1.5 rounded-md border border-red-200 px-3 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                      >
                        <Trash2 className="h-4 w-4" />
                        删除
                      </button>
                    ) : null}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">暂无可展示智能体</div>
          )}
        </aside>
      </div>

      {bulkResult ? (
        <footer className="border-t border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-xs text-[var(--muted)]">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-medium text-[var(--text)]">{bulkResultSummary(bulkResult)}</span>
            {bulkResult.skipped.map((item) => (
              <span key={`skipped:${item.alias}`} className="rounded border border-[var(--border)] px-1.5 py-0.5">
                {item.alias}: {item.reason}
              </span>
            ))}
            {bulkResult.failed.map((item) => (
              <span key={`failed:${item.alias}`} className="rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-red-700">
                {item.alias}: {item.message}
              </span>
            ))}
          </div>
        </footer>
      ) : null}
      {pendingDeleteAlias || pendingBulkDeleteCount > 0 ? (
        <DeleteBotDialog
          title={pendingDeleteAlias ? `删除智能体 ${pendingDeleteAlias}` : `批量删除 ${pendingBulkDeleteCount} 个智能体`}
          description={pendingDeleteAlias ? undefined : "可只删智能体，或连历史记录一起删。主 bot 等不可删除项会自动跳过。"}
          deleteHistory={deleteHistory}
          busy={pendingDeleteAlias ? manager.savingAction === `${pendingDeleteAlias}:delete` : false}
          onDeleteHistoryChange={setDeleteHistory}
          onCancel={() => {
            if (pendingDeleteAlias && manager.savingAction === `${pendingDeleteAlias}:delete`) {
              return;
            }
            setPendingDeleteAlias("");
            setPendingBulkDeleteCount(0);
            setDeleteHistory(false);
          }}
          onConfirm={() => void (pendingDeleteAlias ? confirmDelete() : confirmBulkDelete())}
        />
      ) : null}
    </main>
  );
}
