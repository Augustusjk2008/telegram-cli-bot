import { WebApiClientError } from "./types";
import type {
  AdminUser,
  AdminUserUpdateInput,
  CreateAnnouncementInput,
  AnnouncementItem,
  AnnouncementListResult,
  AssistantAdminAuditItem,
  AssistantAdminAuditResult,
  Capability,
  AppUpdateDownloadProgress,
  AppUpdatePackageKind,
  AppUpdateStatus,
  AssistantCronJob,
  AssistantCronRun,
  AssistantCronRunRequestResult,
  AssistantDiagnosticsFilters,
  AssistantMemoryEvalCase,
  AssistantMemoryEvalReport,
  AssistantMemoryEvalRun,
  AssistantMemoryBulkInvalidateResult,
  AssistantMemoryInvalidateResult,
  AssistantMemoryReindexResult,
  AssistantMemorySearchItem,
  AssistantMemorySearchOptions,
  AssistantMemorySearchResult,
  AssistantPatchGenerationHandlers,
  AssistantPatchMetadata,
  AssistantPerfDiagnostics,
  AssistantPerfRecord,
  AssistantPerfSummary,
  AssistantProposal,
  AssistantProposalDiffFile,
  AssistantProposalDetail,
  AssistantRuntimeSnapshot,
  AssistantUpgradeApplyLog,
  AssistantUpgradeApplyResult,
  AssistantUpgradeDryRunResult,
  AssistantUpgradeTarget,
  AgentInput,
  AgentListResult,
  AgentMutationResult,
  AgentScopedOptions,
  AgentSummary,
  ChatSendOptions,
  ConversationBulkDeleteResult,
  ConversationDeleteResult,
  ConversationListResult,
  PlanExecuteInput,
  PlanExecuteResult,
  ConversationSelectResult,
  ConversationSummary,
  CreateAssistantCronJobInput,
  BotOverview,
  BotExecutionConfigInput,
  BotWorkdirOpenResult,
  BotSummary,
  ChatAttachmentDeleteResult,
  ChatAttachmentUploadResult,
  ChatMessage,
  ChatStatusUpdate,
  ChatTraceDetails,
  ChatTraceEvent,
  NativeAgentPermissionReplyOptions,
  NativeAgentConfigPayload,
  NativeAgentModelOption,
  NativeAgentModelsPayload,
  NativeAgentModelUpdateResult,
  CliErrorStatsFilters,
  CliErrorStatsResult,
  CliType,
  CliParamsPayload,
  ClusterConfigUpdateInput,
  ClusterConfigUpdateResult,
  ClusterBundleApplyResult,
  ClusterBundlePreviewResult,
  ClusterBundleSchemaResult,
  ClusterConfigBundle,
  ClusterSetupPrepareResult,
  ClusterStatus,
  ClusterTaskStatus,
  ClusterTemplateListResult,
  ClusterTemplateSummary,
  CreateBotInput,
  DebugProfile,
  DebugState,
  DirectoryListing,
  EnvConfigItem,
  EnvConfigPatchInput,
  EnvConfigPatchResult,
  EnvConfigPatchValue,
  EnvConfigSnapshot,
  AvatarAsset,
  FileOpenTarget,
  FileTreeRevealResult,
  FileCopyResult,
  FileCreateResult,
  FileDownloadProgress,
  FileEntry,
  FileReadResult,
  GitActionResult,
  GitBlamePayload,
  GitBranchResetResult,
  GitBranchList,
  GitCommitGraphOptions,
  GitCommitGraphPayload,
  GitCommitMessageCliConfig,
  GitCommitMessageCliConfigUpdateInput,
  GitCommitMessageGenerateResult,
  GitDiffPayload,
  GitIdentityConfig,
  GitIdentityScope,
  GitProxySettings,
  GitResetMode,
  GitOverview,
  GitSmartCommitJob,
  GitStashList,
  GitTreeStatus,
  FileMoveResult,
  FileRenameResult,
  LanChatConfig,
  LanChatConfigInput,
  LanChatConversation,
  LanChatEvent,
  LanChatMessage,
  LanChatParticipant,
  LanChatStatus,
  HostEffect,
  InstallablePluginSummary,
  OfflineUpdatePackageList,
  PluginAction,
  PluginActionInvokeInput,
  PluginActionResult,
  PromptPreset,
  PluginViewWindowRequest,
  PluginViewWindowPayload,
  PluginRenderResult,
  PluginSummary,
  PluginUpdateInput,
  PersistentTerminalSnapshot,
  FileWriteResult,
  HistoryDeltaResult,
  PublicHostInfo,
  RegisterCodeCreateResult,
  RegisterCodeItem,
  SessionState,
  TerminalAction,
  TerminalActionRunInput,
  TerminalActionRunResult,
  TerminalActionsConfig,
  TerminalActionsEditableConfig,
  TerminalRuntimePlatform,
  TreeViewPayload,
  TunnelSnapshot,
  UpdateAssistantCronJobInput,
  UpdateBotWorkdirOptions,
  UserBotPermissions,
  WorkspaceDefinitionResult,
  WorkspaceOutlineResult,
  WorkspaceQuickOpenResult,
  WorkspaceSearchResult,
  DocumentViewPayload,
  HexViewPayload,
  TableColumn,
  TableRow,
  TableViewSummary,
  TableWindowPayload,
  TreeNode,
  TreeViewSummary,
  TreeWindowPayload,
  WaveformTrack,
  WaveformViewSummary,
  WaveformWindowPayload,
} from "./types";
import { WebBotClient } from "./webBotClient";
import { EventType, type AgUiEvent } from "./agUiProtocol";
import { mockBots } from "../mocks/bots";
import { mockChatMessages } from "../mocks/chat";
import { mockFiles } from "../mocks/files";
import { createMockAssistantOpsState } from "../mocks/assistantOpsData";
import {
  findMockClusterTemplate,
  listMockClusterTemplateSummaries,
} from "../mocks/clusterTemplates";
import {
  DEMO_MAIN_WORKDIR,
  DEMO_TEAM_WORKDIR,
} from "../mocks/demoEnvironment";
import {
  buildMockPlanExecutionMessage,
  MOCK_PLAN_PATH,
} from "../mocks/planModeData";
import { APP_VERSION } from "../theme";

const MOCK_RELEASE_URL = `https://github.com/example/cli-bridge/releases/tag/v${APP_VERSION}`;
const MOCK_PERSISTENT_TERMINAL_STORAGE_KEY = "mock-web-persistent-terminal-session";
const MEMBER_BOT_LIMIT = 3;

function getMockUpdatePath(packageKind: AppUpdatePackageKind) {
  if (packageKind === "portable") return ".updates/orbit-safe-claw-windows-x64.zip";
  if (packageKind === "linux") return ".updates/orbit-safe-claw-linux-x64.tar.gz";
  if (packageKind === "macos") return ".updates/orbit-safe-claw-macos-universal.tar.gz";
  return ".updates/orbit-safe-claw-windows-x64-installer.zip";
}

function getMockUpdatePlatform(packageKind: AppUpdatePackageKind) {
  if (packageKind === "portable") return "windows-x64-portable";
  if (packageKind === "linux") return "linux-x64";
  if (packageKind === "macos") return "macos-universal";
  return "windows-x64-installer";
}

function resolveMockTerminalActionCommand(action: TerminalAction, runtimePlatform: TerminalRuntimePlatform) {
  if (runtimePlatform === "windows") return (action.windowsCommand || "").trim();
  if (runtimePlatform === "macos") return ((action.macosCommand || "").trim() || (action.linuxCommand || "").trim());
  return (action.linuxCommand || "").trim();
}

const MEMBER_CAPABILITIES: Capability[] = [
  "view_bots",
  "view_bot_status",
  "view_file_tree",
  "mutate_browse_state",
  "view_chat_history",
  "view_chat_trace",
  "read_file_content",
  "write_files",
  "chat_send",
  "terminal_exec",
  "debug_exec",
  "git_ops",
  "manage_cli_params",
  "manage_bots",
  "create_workdir_directory",
  "view_plugins",
  "run_plugins",
  "admin_ops",
];
const SUPER_ADMIN_CAPABILITIES: Capability[] = [...MEMBER_CAPABILITIES, "manage_register_codes"];
const GUEST_CAPABILITIES: Capability[] = [
  "view_bots",
  "view_bot_status",
  "view_file_tree",
  "view_chat_history",
];
const MOCK_GIT_IGNORED_ITEMS: Record<string, string[]> = {
  main: ["dist"],
};
const MOCK_CLI_MODEL_OPTIONS = [
  "gpt-5.5",
  "gpt-5.4",
  "gpt-5.4-mini",
  "gpt-5.3-codex",
  "claude-opus-4-7",
  "claude-sonnet-4-6",
  "none",
];
const DEFAULT_CLUSTER = {
  enabled: false,
  writePolicy: "selected_agents" as const,
  conflictPolicy: "snapshot_diff" as const,
  maxParallelAgents: 2,
  defaultTimeoutSeconds: 600,
  modelTiers: { low: "", medium: "", high: "" },
};
const DEFAULT_AGENT_CLUSTER = {
  allowCluster: true,
  allowWrite: false,
  sessionPolicy: "persistent" as const,
  timeoutSeconds: 600,
};

function defaultCliPathForType(cliType: string) {
  return cliType === "kimi" ? "kimi" : cliType === "claude" ? "claude" : "codex";
}

function buildMockCliParams(cliType: string): CliParamsPayload {
  if (cliType === "kimi") {
    return {
      cliType: "kimi",
      params: {
        thinking: "default",
        stream_json: true,
        yolo: true,
        extra_args: [],
      },
      defaults: {
        thinking: "default",
        stream_json: true,
        yolo: true,
        extra_args: [],
      },
      schema: {
        thinking: {
          type: "string",
          enum: ["enabled", "disabled", "default"],
          description: "Thinking 模式",
        },
        stream_json: {
          type: "boolean",
          description: "启用 stream-json 输出",
        },
        yolo: {
          type: "boolean",
          description: "自动批准操作",
        },
        extra_args: {
          type: "string_list",
          description: "额外参数",
        },
      },
    };
  }
  return {
    cliType: cliType === "claude" ? "claude" : "codex",
    params: {
      reasoning_effort: "xhigh",
      model: "gpt-5.4",
      skip_git_check: true,
      json_output: true,
      yolo: true,
      extra_args: [],
    },
    defaults: {
      reasoning_effort: "xhigh",
      model: "gpt-5.4",
      skip_git_check: true,
      json_output: true,
      yolo: true,
      extra_args: [],
    },
    schema: {
      reasoning_effort: {
        type: "string",
        enum: ["xhigh", "high", "medium", "low"],
        description: "推理努力程度",
      },
      model: {
        type: "string",
        description: "模型选择",
        nullable: true,
        enum: MOCK_CLI_MODEL_OPTIONS,
      },
      skip_git_check: {
        type: "boolean",
        description: "跳过 Git 仓库检查",
      },
      json_output: {
        type: "boolean",
        description: "JSON 格式输出",
      },
      yolo: {
        type: "boolean",
        description: "绕过审批和沙箱",
      },
      extra_args: {
        type: "string_list",
        description: "额外参数",
      },
    },
  };
}

function buildMockGitCommitMessageConfig(cliType: CliType, cliPath?: string): GitCommitMessageCliConfig {
  const payload = buildMockCliParams(cliType);
  return {
    cliType: payload.cliType,
    cliPath: cliPath?.trim() || defaultCliPathForType(payload.cliType),
    params: { ...payload.params },
    defaults: { ...payload.defaults },
    schema: { ...payload.schema },
  };
}

function createMockEnvItems(): EnvConfigItem[] {
  return [
    {
      key: "CLI_TYPE",
      label: "CLI 类型",
      description: "主 Bot 下次启动使用的 CLI。",
      type: "select",
      category: "basic",
      value: "codex",
      defaultValue: "codex",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
      options: [
        { value: "codex", label: "codex" },
        { value: "claude", label: "claude" },
        { value: "kimi", label: "kimi" },
      ],
    },
    {
      key: "CLI_PATH",
      label: "CLI 路径",
      description: "CLI 可执行文件名或绝对路径。",
      type: "path",
      category: "basic",
      value: "codex",
      defaultValue: "codex",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "WORKING_DIR",
      label: "默认工作目录",
      description: "只影响主 Bot 下次启动默认值。",
      type: "path",
      category: "basic",
      value: DEMO_MAIN_WORKDIR,
      defaultValue: DEMO_MAIN_WORKDIR,
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "WEB_HOST",
      label: "Web 监听地址",
      description: "Web 服务监听 host。",
      type: "string",
      category: "web",
      value: "127.0.0.1",
      defaultValue: "127.0.0.1",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "WEB_PORT",
      label: "Web 端口",
      description: "Web 服务监听端口。",
      type: "number",
      category: "web",
      value: 8765,
      defaultValue: 8765,
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "WEB_API_TOKEN",
      label: "Web API 口令",
      description: "空值会禁用口令登录。",
      type: "password",
      category: "web",
      value: "",
      defaultValue: "",
      source: "env",
      sensitive: true,
      masked: true,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "NATIVE_AGENT_ENABLED",
      label: "启用原生 agent",
      description: "启用后可创建原生 agent Bot。",
      type: "boolean",
      category: "native_agent",
      value: true,
      defaultValue: false,
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "NATIVE_AGENT_COMMAND",
      label: "原生 agent 命令",
      description: "全局 OpenCode 命令。",
      type: "path",
      category: "native_agent",
      value: "opencode",
      defaultValue: "opencode",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "NATIVE_AGENT_HOST",
      label: "原生 agent Host",
      description: "全局 OpenCode Host。",
      type: "string",
      category: "native_agent",
      value: "127.0.0.1",
      defaultValue: "127.0.0.1",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "NATIVE_AGENT_PORT",
      label: "原生 agent 端口",
      description: "全局 OpenCode 端口。",
      type: "number",
      category: "native_agent",
      value: 0,
      defaultValue: 0,
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "NATIVE_AGENT_SERVER_PASSWORD",
      label: "原生 agent 服务密码",
      description: "全局 OpenCode 服务密码。",
      type: "password",
      category: "native_agent",
      value: "",
      defaultValue: "",
      source: "env",
      sensitive: true,
      masked: true,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "WEB_ALLOWED_ORIGINS",
      label: "允许来源",
      description: "CORS 来源，逗号分隔。",
      type: "csv",
      category: "web",
      value: ["http://127.0.0.1:3000"],
      defaultValue: [],
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "TCB_NODE_ID",
      label: "节点 ID",
      description: "Hub 固定公网转发节点 ID。",
      type: "string",
      category: "web",
      value: "demo-node",
      defaultValue: "",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "WEB_BASE_PATH",
      label: "Web 子路径",
      description: "空或 /node/<节点 ID>。",
      type: "string",
      category: "web",
      value: "",
      defaultValue: "",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: true,
    },
    {
      key: "VITE_BASE_PATH",
      label: "前端资源子路径",
      description: "留空则跟随 WEB_BASE_PATH。",
      type: "string",
      category: "frontend",
      value: "",
      defaultValue: "",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: true,
    },
    {
      key: "VITE_API_BASE_URL",
      label: "前端 API 子路径",
      description: "留空则跟随 WEB_BASE_PATH。",
      type: "string",
      category: "frontend",
      value: "",
      defaultValue: "",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: true,
    },
    {
      key: "WEB_FIXED_PUBLIC_FORWARD_ENABLED",
      label: "固定公网转发",
      description: "启用 Hub 固定公网转发。",
      type: "boolean",
      category: "tunnel",
      value: false,
      defaultValue: false,
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "WEB_FIXED_PUBLIC_FORWARD_URL",
      label: "固定公网入口",
      description: "Hub 公网入口 URL。",
      type: "string",
      category: "tunnel",
      value: "",
      defaultValue: "",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "TCB_HUB_FRPS_PORT",
      label: "Hub frps 端口",
      description: "Hub 分配给 frpc 连接 frps 的端口，不是公网 HTTP 访问端口。",
      type: "number",
      category: "tunnel",
      value: "",
      defaultValue: "",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "TCB_HUB_NODE_TOKEN",
      label: "Hub 节点授权码",
      description: "Hub 分配给本节点的授权码。",
      type: "password",
      category: "tunnel",
      value: "",
      defaultValue: "",
      source: "env",
      sensitive: true,
      masked: true,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "WEB_TUNNEL_MODE",
      label: "Tunnel 模式",
      description: "保存后需重启或手动重启 tunnel。",
      type: "select",
      category: "tunnel",
      value: "cloudflare_quick",
      defaultValue: "disabled",
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
      options: [
        { value: "disabled", label: "disabled" },
        { value: "cloudflare_quick", label: "cloudflare_quick" },
      ],
    },
    {
      key: "APP_UPDATE_REPOSITORY",
      label: "更新仓库",
      description: "GitHub Release 仓库。",
      type: "string",
      category: "updates",
      value: "owner/repo",
      defaultValue: "",
      source: "example",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "PUSHPLUS_TOKEN",
      label: "PushPlus Token",
      description: "推送通知 token。",
      type: "password",
      category: "notifications",
      value: "",
      defaultValue: "",
      source: "env",
      sensitive: true,
      masked: true,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "TCB_DIAG_ENABLED",
      label: "诊断日志",
      description: "开启后重启生效。",
      type: "boolean",
      category: "diagnostics",
      value: false,
      defaultValue: false,
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    },
    {
      key: "VITE_CHAT_TRACE_PREVIEW_MAX_LINES",
      label: "Trace 预览行数",
      description: "前端构建项，保存后需重新 build。",
      type: "number",
      category: "frontend",
      value: 5,
      defaultValue: 5,
      source: "example",
      sensitive: false,
      masked: false,
      restartRequired: false,
      rebuildRequired: true,
    },
  ];
}

function cloneEnvItem(item: EnvConfigItem): EnvConfigItem {
  return {
    ...item,
    value: Array.isArray(item.value) ? [...item.value] : item.value,
    defaultValue: Array.isArray(item.defaultValue) ? [...item.defaultValue] : item.defaultValue,
    options: item.options?.map((option) => ({ ...option })),
    validation: item.validation ? { ...item.validation } : undefined,
  };
}

function readMockPersistentTerminalSnapshot(): PersistentTerminalSnapshot {
  if (typeof localStorage === "undefined") {
    return {
      started: false,
      closed: false,
      cwd: "",
      ptyMode: null,
      connectionText: "未启动",
      lastSeq: 0,
    };
  }
  try {
    const raw = localStorage.getItem(MOCK_PERSISTENT_TERMINAL_STORAGE_KEY);
    if (!raw) {
      return {
        started: false,
        closed: false,
        cwd: "",
        ptyMode: null,
        connectionText: "未启动",
        lastSeq: 0,
      };
    }
    const parsed = JSON.parse(raw) as Partial<PersistentTerminalSnapshot>;
    return {
      started: Boolean(parsed.started),
      closed: Boolean(parsed.closed),
      cwd: typeof parsed.cwd === "string" ? parsed.cwd : "",
      ptyMode: typeof parsed.ptyMode === "boolean" ? parsed.ptyMode : null,
      connectionText: typeof parsed.connectionText === "string" ? parsed.connectionText : "未启动",
      lastSeq: typeof parsed.lastSeq === "number" ? parsed.lastSeq : 0,
    };
  } catch {
    return {
      started: false,
      closed: false,
      cwd: "",
      ptyMode: null,
      connectionText: "未启动",
      lastSeq: 0,
    };
  }
}

function writeMockPersistentTerminalSnapshot(snapshot: PersistentTerminalSnapshot) {
  if (typeof localStorage === "undefined") {
    return;
  }
  localStorage.setItem(MOCK_PERSISTENT_TERMINAL_STORAGE_KEY, JSON.stringify(snapshot));
}

function resolveMemberCapabilities(username: string) {
  return username.trim() === "127.0.0.1"
    ? [...SUPER_ADMIN_CAPABILITIES]
    : [...MEMBER_CAPABILITIES];
}

function parseMockAssistantDiffFiles(diffText: string): AssistantProposalDiffFile[] {
  const text = diffText.trim();
  if (!text) {
    return [];
  }
  const matches = Array.from(text.matchAll(/^diff --git a\/(.+?) b\/(.+)$/gm));
  if (matches.length === 0) {
    return [{
      path: "patch.diff",
      status: "unknown",
      additions: (text.match(/^\+(?!\+\+)/gm) || []).length,
      deletions: (text.match(/^-(?!--)/gm) || []).length,
      text,
    }];
  }
  return matches.map((match, index) => {
    const start = match.index || 0;
    const end = index + 1 < matches.length ? (matches[index + 1].index || text.length) : text.length;
    const chunk = text.slice(start, end).trim();
    const path = (chunk.match(/^rename to (.+)$/m)?.[1] || match[2] || match[1]).trim();
    const oldPath = chunk.match(/^rename from (.+)$/m)?.[1]?.trim() || match[1];
    const status = chunk.includes("new file mode")
      ? "added"
      : chunk.includes("deleted file mode")
        ? "deleted"
        : chunk.includes("rename from") || oldPath !== path
          ? "renamed"
          : "modified";
    return {
      path,
      oldPath: status === "renamed" ? oldPath : undefined,
      status,
      additions: (chunk.match(/^\+(?!\+\+)/gm) || []).length,
      deletions: (chunk.match(/^-(?!--)/gm) || []).length,
      text: chunk,
    } satisfies AssistantProposalDiffFile;
  });
}

function summarizeMockAssistantDiagnostics(records: AssistantPerfRecord[]): AssistantPerfSummary {
  const total = records.length;
  const success = records.filter((item) => item.status === "completed").length;
  const failed = total - success;
  const avgElapsedMs = total ? Math.round(records.reduce((sum, item) => sum + item.elapsedMs, 0) / total) : 0;
  const sortedElapsed = records.map((item) => item.elapsedMs).sort((left, right) => left - right);
  const p95Index = sortedElapsed.length ? Math.max(0, Math.ceil(sortedElapsed.length * 0.95) - 1) : 0;
  const p95ElapsedMs = sortedElapsed[p95Index] || 0;
  const bySource: Record<string, number> = {};
  const byStatus: Record<string, number> = {};
  const stageTotals = {
    syncMs: 0,
    indexMs: 0,
    recallMs: 0,
    cliMs: 0,
    dbMs: 0,
    traceMs: 0,
    pluginMs: 0,
  };
  const errorGroups = new Map<string, { count: number; latestAt: string }>();
  for (const record of records) {
    bySource[record.source] = (bySource[record.source] || 0) + 1;
    byStatus[record.status] = (byStatus[record.status] || 0) + 1;
    stageTotals.syncMs += record.stageDurations.syncMs;
    stageTotals.indexMs += record.stageDurations.indexMs;
    stageTotals.recallMs += record.stageDurations.recallMs;
    stageTotals.cliMs += record.stageDurations.cliMs;
    stageTotals.dbMs += record.stageDurations.dbMs;
    stageTotals.traceMs += record.stageDurations.traceMs;
    stageTotals.pluginMs += record.stageDurations.pluginMs;
    if (record.error) {
      const current = errorGroups.get(record.error);
      errorGroups.set(record.error, {
        count: (current?.count || 0) + 1,
        latestAt: !current || record.createdAt > current.latestAt ? record.createdAt : current.latestAt,
      });
    }
  }
  const slowStages = Object.entries(stageTotals)
    .map(([stage, totalMs]) => ({
      stage: stage.replace(/Ms$/, ""),
      totalMs,
      avgMs: total ? Math.round(totalMs / total) : 0,
    }))
    .sort((left, right) => right.totalMs - left.totalMs)
    .slice(0, 5);
  return {
    total,
    success,
    failed,
    avgElapsedMs,
    p95ElapsedMs,
    bySource,
    byStatus,
    slowStages,
    errorGroups: Array.from(errorGroups.entries())
      .map(([message, info]) => ({ message, count: info.count, latestAt: info.latestAt }))
      .sort((left, right) => right.count - left.count || right.latestAt.localeCompare(left.latestAt)),
  };
}

function buildMockWaveformTracks(): WaveformTrack[] {
  return [
    {
      signalId: "tb.clk",
      label: "tb.clk",
      width: 1,
      segments: [
        { start: 0, end: 5, value: "0" },
        { start: 5, end: 10, value: "1" },
        { start: 10, end: 15, value: "0" },
        { start: 15, end: 20, value: "1" },
        { start: 20, end: 25, value: "0" },
        { start: 25, end: 30, value: "1" },
        { start: 30, end: 35, value: "0" },
        { start: 35, end: 40, value: "1" },
        { start: 40, end: 45, value: "0" },
        { start: 45, end: 50, value: "1" },
        { start: 50, end: 55, value: "0" },
        { start: 55, end: 60, value: "1" },
        { start: 60, end: 65, value: "0" },
        { start: 65, end: 70, value: "1" },
        { start: 70, end: 75, value: "0" },
        { start: 75, end: 80, value: "1" },
        { start: 80, end: 85, value: "0" },
        { start: 85, end: 90, value: "1" },
        { start: 90, end: 95, value: "0" },
        { start: 95, end: 100, value: "1" },
        { start: 100, end: 105, value: "0" },
        { start: 105, end: 110, value: "1" },
        { start: 110, end: 115, value: "0" },
        { start: 115, end: 120, value: "1" },
      ],
    },
    {
      signalId: "tb.rst_n",
      label: "tb.rst_n",
      width: 1,
      segments: [
        { start: 0, end: 10, value: "0" },
        { start: 10, end: 120, value: "1" },
      ],
    },
    {
      signalId: "tb.counter",
      label: "tb.counter",
      width: 4,
      segments: [
        { start: 0, end: 15, value: "0000" },
        { start: 15, end: 25, value: "0001" },
        { start: 25, end: 35, value: "0010" },
        { start: 35, end: 45, value: "0011" },
        { start: 45, end: 55, value: "0100" },
        { start: 55, end: 65, value: "0101" },
        { start: 65, end: 75, value: "0110" },
        { start: 75, end: 85, value: "0111" },
        { start: 85, end: 95, value: "1000" },
        { start: 95, end: 105, value: "1001" },
        { start: 105, end: 115, value: "1010" },
        { start: 115, end: 120, value: "1011" },
      ],
    },
  ];
}

function buildMockWaveformSummary(sourcePath: string): WaveformViewSummary {
  const tracks = buildMockWaveformTracks();
  return {
    path: sourcePath,
    timescale: "1ns",
    startTime: 0,
    endTime: 120,
    display: {
      defaultZoom: 1,
      zoomLevels: [0.5, 0.75, 1, 1.5, 2, 3, 4],
      showTimeAxis: true,
      busStyle: "cross",
      labelWidth: 220,
      minWaveWidth: 840,
      pixelsPerTime: 18,
      axisHeight: 42,
      trackHeight: 64,
    },
    signals: tracks.map((track) => ({
      signalId: track.signalId,
      label: track.label,
      width: track.width,
      kind: track.width > 1 ? "bus" : "scalar",
    })),
    defaultSignalIds: tracks.map((track) => track.signalId),
  };
}

const TIMING_COLUMNS: TableColumn[] = [
  { id: "endpoint", title: "Endpoint" },
  { id: "slack", title: "Slack", kind: "number", align: "right", sortable: true },
];

const TIMING_ROWS: TableRow[] = [
  {
    id: "path-1",
    cells: { endpoint: "rx_data", slack: -0.132 },
    actions: [{ id: "export-row", label: "导出行", target: "plugin", location: "row" }],
  },
  {
    id: "path-2",
    cells: { endpoint: "tx_data", slack: -0.081 },
    actions: [{ id: "export-row", label: "导出行", target: "plugin", location: "row" }],
  },
  {
    id: "path-3",
    cells: { endpoint: "ctrl_state", slack: 0.014 },
    actions: [{ id: "export-row", label: "导出行", target: "plugin", location: "row" }],
  },
];

function clonePluginActions(actions: PluginAction[] | undefined) {
  return (actions || []).map((action) => ({
    ...action,
    payload: action.payload ? { ...action.payload } : undefined,
    confirm: action.confirm ? { ...action.confirm } : undefined,
    hostAction: action.hostAction ? { ...action.hostAction } as HostEffect : undefined,
  }));
}

function clonePromptPresets(presets: PromptPreset[] = []) {
  return presets.map((preset) => ({ ...preset }));
}

function buildMockTimingRows(offset: number, limit: number, query = "", sort?: { columnId?: string; direction?: string }) {
  let rows = TIMING_ROWS.filter((row) =>
    !query.trim() || String(row.cells.endpoint || "").toLowerCase().includes(query.trim().toLowerCase()),
  );
  if (sort?.columnId === "slack") {
    rows = [...rows].sort((left, right) => {
      const diff = Number(left.cells.slack || 0) - Number(right.cells.slack || 0);
      return sort.direction === "desc" ? -diff : diff;
    });
  }
  return rows.slice(offset, offset + limit).map((row) => ({
    ...row,
    cells: { ...row.cells },
    actions: clonePluginActions(row.actions),
  }));
}

function buildMockTimingSummary(defaultPageSize = 2): TableViewSummary {
  return {
    columns: TIMING_COLUMNS.map((column) => ({ ...column })),
    totalRows: TIMING_ROWS.length,
    defaultPageSize,
    actions: [{ id: "export-all", label: "导出 CSV", target: "plugin", location: "toolbar", variant: "primary" }],
  };
}

function cloneTreeNodes(nodes: TreeNode[]): TreeNode[] {
  return nodes.map((node) => ({
    ...node,
    actions: clonePluginActions(node.actions),
    children: node.children ? cloneTreeNodes(node.children) : undefined,
  }));
}

function buildMockTreeRoots(): TreeNode[] {
  return [
    {
      id: "top",
      label: "top",
      kind: "folder",
      badges: [{ text: "root" }],
      hasChildren: true,
      expandable: true,
      actions: [{ id: "open-source", label: "打开源码", target: "plugin", location: "node" }],
    },
    {
      id: "tb_uart",
      label: "tb_uart",
      kind: "symbol",
      secondaryText: "uart block",
      expandable: false,
      actions: [{ id: "copy-name", label: "复制名", target: "host", location: "node", hostAction: { type: "copy_text", text: "tb_uart" } }],
    },
  ];
}

function buildMockTreeChildren(nodeId: string): TreeNode[] {
  if (nodeId === "top") {
    return [
      {
        id: "top.u_core",
        label: "u_core",
        kind: "symbol",
        expandable: false,
        actions: [{ id: "open-source", label: "打开源码", target: "plugin", location: "node" }],
      },
      {
        id: "top.u_mem",
        label: "u_mem",
        kind: "symbol",
        expandable: false,
        actions: [{ id: "copy-name", label: "复制名", target: "host", location: "node", hostAction: { type: "copy_text", text: "u_mem" } }],
      },
    ];
  }
  return [];
}

function buildMockTreeSummary(): TreeViewSummary {
  return {
    roots: cloneTreeNodes(buildMockTreeRoots()),
    searchable: true,
    searchPlaceholder: "搜索层级",
    actions: [
      {
        id: "open-timing",
        label: "打开 Timing",
        target: "host",
        location: "toolbar",
        hostAction: {
          type: "open_plugin_view",
          pluginId: "timing-report",
          viewId: "timing-table",
          title: "timing.rpt",
          input: { path: "reports/timing.rpt" },
        },
      },
    ],
  };
}

function buildMockDocumentPayload(sourcePath: string): DocumentViewPayload {
  return {
    path: sourcePath,
    title: "项目路线图",
    statsText: "5 段 · 1 表格 · 1 图片",
    blocks: [
      { type: "heading", level: 1, runs: [{ text: "项目路线图" }] },
      { type: "paragraph", runs: [{ text: "目标：" }, { text: "先打通 document renderer", bold: true }] },
      { type: "list_item", ordered: false, depth: 0, marker: "•", runs: [{ text: "支持标题和段落" }] },
      { type: "list_item", ordered: false, depth: 0, marker: "•", runs: [{ text: "支持列表和表格" }] },
      {
        type: "image",
        artifactId: "artifact-docx-image-1",
        filename: "image1.png",
        contentType: "image/png",
        alt: "系统架构图",
        title: "系统架构",
        widthPx: 320,
        heightPx: 160,
      },
      {
        type: "table",
        rows: [
          { cells: [{ runs: [{ text: "交付物" }] }, { runs: [{ text: "状态" }] }] },
          { cells: [{ runs: [{ text: "MVP" }] }, { runs: [{ text: "开发中" }] }] },
        ],
      },
    ],
  };
}

function buildMockPdfDocumentPayload(sourcePath: string): DocumentViewPayload {
  return {
    path: sourcePath,
    title: "Project Roadmap",
    statsText: "1 页 · 2 段",
    blocks: [
      { type: "heading", level: 1, runs: [{ text: "Project Roadmap" }] },
      { type: "paragraph", runs: [{ text: "Current status: in progress." }] },
      { type: "paragraph", runs: [{ text: "Deliver text PDF preview first." }] },
    ],
  };
}

function buildMockXlsxDocumentPayload(sourcePath: string): DocumentViewPayload {
  return {
    path: sourcePath,
    title: "roadmap.xlsx",
    statsText: "2 工作表 · 5 行预览",
    blocks: [
      { type: "heading", level: 2, runs: [{ text: "Summary" }] },
      {
        type: "table",
        rows: [
          { cells: [{ runs: [{ text: "Milestone" }] }, { runs: [{ text: "Status" }] }] },
          { cells: [{ runs: [{ text: "Renderer" }] }, { runs: [{ text: "Done" }] }] },
          { cells: [{ runs: [{ text: "Plugin" }] }, { runs: [{ text: "In Progress" }] }] },
        ],
      },
      { type: "heading", level: 2, runs: [{ text: "Owners" }] },
      {
        type: "table",
        rows: [
          { cells: [{ runs: [{ text: "Area" }] }, { runs: [{ text: "Owner" }] }] },
          { cells: [{ runs: [{ text: "Frontend" }] }, { runs: [{ text: "Kai" }] }] },
        ],
      },
    ],
  };
}

function buildMockHexPayload(sourcePath: string): HexViewPayload {
  return {
    path: sourcePath,
    fileSizeBytes: 20,
    previewBytes: 16,
    bytesPerRow: 8,
    truncated: true,
    statsText: "20 B · preview 16 B",
    entropyBuckets: [
      { index: 0, startOffset: 0, endOffset: 8, entropy: 0.1 },
      { index: 1, startOffset: 8, endOffset: 16, entropy: 0.9 },
    ],
    rows: [
      { offset: 0, hex: ["00", "41", "42", "7F", "80", "FF", "20", "2E"], ascii: ".AB... ." },
      { offset: 8, hex: ["48", "65", "78", "21"], ascii: "Hex!" },
    ],
  };
}

function buildRepoOutlineFileNode(path: string, symbolCount?: number): TreeNode {
  const parts = path.split("/");
  const label = parts[parts.length - 1] || path;
  const parent = parts.slice(0, -1).join("/");
  return {
    id: `file:${path}`,
    label,
    kind: "file",
    secondaryText: parent,
    badges: typeof symbolCount === "number" ? [{ text: `${symbolCount} symbols` }] : undefined,
    hasChildren: path === "bot/web/api_service.py",
    expandable: path === "bot/web/api_service.py",
    payload: { path, nodeType: "file" },
    actions: [
      {
        id: "open-file",
        label: "打开文件",
        target: "host",
        location: "node",
        hostAction: { type: "open_file", path },
      },
    ],
  };
}

function buildRepoOutlineDirNode(path: string): TreeNode {
  const parts = path.split("/");
  const label = parts[parts.length - 1] || path;
  const parent = parts.slice(0, -1).join("/");
  return {
    id: `dir:${path}`,
    label,
    kind: "folder",
    secondaryText: parent,
    hasChildren: true,
    expandable: true,
    payload: { path, nodeType: "directory" },
  };
}

function buildRepoOutlineSymbolNode(): TreeNode {
  return {
    id: "symbol:bot/web/api_service.py:run_cli_chat:184",
    label: "run_cli_chat",
    kind: "function",
    secondaryText: "function · line 184",
    payload: {
      path: "bot/web/api_service.py",
      line: 184,
      symbol: "run_cli_chat",
      nodeType: "symbol",
    },
    actions: [
      {
        id: "jump-definition",
        label: "跳到定义",
        target: "host",
        location: "node",
        hostAction: { type: "open_file", path: "bot/web/api_service.py", line: 184 },
      },
    ],
  };
}

function normalizeRepoOutlineRoot(rootPath = ""): string {
  const normalized = rootPath.trim().replace(/\\/g, "/").replace(/\/+$/g, "");
  if (!normalized || normalized === ".") {
    return "";
  }
  if (normalized === "bot" || normalized.startsWith("bot/")) {
    return normalized;
  }
  const botIndex = normalized.lastIndexOf("/bot");
  if (botIndex >= 0) {
    return normalized.slice(botIndex + 1);
  }
  return "";
}

function buildRepoOutlineRoots(rootPath = ""): TreeNode[] {
  const root = normalizeRepoOutlineRoot(rootPath);
  if (root === "bot") {
    return [buildRepoOutlineDirNode("bot/web")];
  }
  if (root === "bot/web") {
    return [buildRepoOutlineFileNode("bot/web/api_service.py", 1)];
  }
  return [
    buildRepoOutlineDirNode("bot"),
    buildRepoOutlineFileNode("README.md"),
  ];
}

function buildRepoOutlineChildren(nodeId: string): TreeNode[] {
  if (nodeId === "dir:bot") {
    return [buildRepoOutlineDirNode("bot/web")];
  }
  if (nodeId === "dir:bot/web") {
    return [buildRepoOutlineFileNode("bot/web/api_service.py", 1)];
  }
  if (nodeId === "file:bot/web/api_service.py") {
    return [buildRepoOutlineSymbolNode()];
  }
  return [];
}

function buildRepoOutlineSearch(query: string, rootPath = ""): TreeWindowPayload {
  const keyword = query.trim().toLowerCase();
  const root = normalizeRepoOutlineRoot(rootPath);
  if (!keyword) {
    const roots = buildRepoOutlineRoots(root);
    return {
      op: "search",
      nodes: cloneTreeNodes(roots),
      statsText: repoOutlineStatsText(root),
    };
  }
  const canMatchApiFile = !root || "bot/web/api_service.py".startsWith(root);
  const matchesApiFile = canMatchApiFile && [
    "bot/web/api_service.py",
    "api_service.py",
    "web",
    "bot",
    "run_cli_chat",
  ].some((value) => value.toLowerCase().includes(keyword));
  const matchesReadme = !root && ["readme.md", "readme"].some((value) => value.includes(keyword));

  const nodes: TreeNode[] = [];
  if (matchesApiFile) {
    const fileNode = buildRepoOutlineFileNode("bot/web/api_service.py", 1);
    fileNode.children = keyword.includes("run") || keyword.includes("chat") || keyword.includes("api") || keyword.includes("web")
      ? [buildRepoOutlineSymbolNode()]
      : [];
    nodes.push(fileNode);
  }
  if (matchesReadme) {
    nodes.push(buildRepoOutlineFileNode("README.md"));
  }
  return {
    op: "search",
    nodes: cloneTreeNodes(nodes),
    statsText: `${nodes.length} 文件 · ${nodes.some((node) => node.id.startsWith("file:bot/web/api_service.py")) ? 1 : 0} 符号`,
  };
}

function repoOutlineStatsText(rootPath = ""): string {
  const root = normalizeRepoOutlineRoot(rootPath);
  if (root === "bot") {
    return "0 文件 · 0 符号";
  }
  if (root === "bot/web") {
    return "1 文件 · 1 符号";
  }
  return "2 文件 · 1 符号";
}

function buildRepoOutlineSummary(rootPath = ""): TreeViewSummary {
  const roots = buildRepoOutlineRoots(rootPath);
  return {
    roots: cloneTreeNodes(roots),
    searchable: true,
    searchPlaceholder: "搜当前文件夹目录、文件、符号",
    statsText: repoOutlineStatsText(rootPath),
    emptySearchText: "未找到匹配目录、文件、符号",
    actions: [
      { id: "refresh-tree", label: "刷新", target: "plugin", location: "toolbar" },
      { id: "collapse-all", label: "折叠全部", target: "plugin", location: "toolbar" },
    ],
  };
}

function buildMockZipTreePayload(sourcePath: string): TreeViewPayload {
  return {
    roots: [
      {
        id: "dir:docs",
        label: "docs",
        kind: "folder",
        hasChildren: true,
        expandable: true,
        children: [
          {
            id: "file:docs/readme.txt",
            label: "readme.txt",
            kind: "file",
            secondaryText: "docs",
            badges: [{ text: "5 B", tone: "info" }],
            payload: { path: "docs/readme.txt" },
          },
        ],
      },
      {
        id: "dir:src",
        label: "src",
        kind: "folder",
        hasChildren: true,
        expandable: true,
        children: [
          {
            id: "file:src/main.py",
            label: "main.py",
            kind: "file",
            secondaryText: "src",
            badges: [{ text: "12 B", tone: "info" }],
            payload: { path: "src/main.py" },
          },
        ],
      },
    ],
    searchable: false,
    statsText: `2 文件 · 2 文件夹 · ${sourcePath.split(/[\\/]/).pop() || "sample.zip"}`,
  };
}

export class MockWebBotClient implements WebBotClient {
  private bots = new Map<string, BotSummary>(
    mockBots.map((item) => [
      item.alias,
      {
        ...item,
        cliPath: defaultCliPathForType(item.cliType),
        botMode: "cli",
        enabled: true,
        isMain: item.alias === "main",
        serviceStatus: item.status === "offline" ? "offline" : "online",
        activityStatus: item.status === "busy" ? "busy" : "idle",
        busyAgentIds: [],
        busyAgentNames: [],
        busyAgentCount: item.status === "busy" ? 1 : 0,
        promptPresets: clonePromptPresets(item.promptPresets),
        supportedExecutionModes: ["cli"],
        defaultExecutionMode: "cli",
        nativeAgent: { provider: "", model: "", opencodeAgent: "", baseUrl: "", hasApiKey: false, apiKeyMasked: "" },
        cluster: {
          ...DEFAULT_CLUSTER,
          modelTiers: { ...DEFAULT_CLUSTER.modelTiers },
        },
      },
    ]),
  );
  private globalPromptPresets: PromptPreset[] = [];
  private nativeAgentConfig: Record<string, unknown> = {
    "$schema": "https://opencode.ai/config.json",
    provider: {
      jojocode_max: {
        models: {
          "gpt-5.4": {
            name: "gpt-5.4",
            limit: {
              context: 1000000,
              output: 128000,
            },
          },
        },
      },
    },
  };
  private nativeAgentModels: NativeAgentModelOption[] = [
    {
      id: "jojocode_max/gpt-5.4",
      provider: "jojocode_max",
      model: "gpt-5.4",
      name: "gpt-5.4",
      label: "jojocode_max / gpt-5.4",
      contextWindow: 1000000,
      outputLimit: 128000,
    },
  ];
  private currentPaths = new Map<string, string>();
  private pluginSessions = new Map<
    string,
    | { pluginId: string; renderer: "waveform"; summary: WaveformViewSummary; window: WaveformWindowPayload }
    | { pluginId: string; renderer: "table"; summary: TableViewSummary; window: TableWindowPayload }
    | { pluginId: string; renderer: "tree"; summary: TreeViewSummary; window: TreeWindowPayload; rootPath?: string }
  >();
  private pluginSessionCounter = 0;
  private pluginArtifacts = new Map<string, { filename: string; content: string; contentType?: string }>([
    ["artifact-docx-image-1", { filename: "image1.png", content: "mock image", contentType: "image/png" }],
  ]);
  private pluginArtifactCounter = 0;
  private workdirOverrides = new Map<string, string>();
  private conversationsByBot = new Map<string, ConversationSummary[]>();
  private activeConversationByBot = new Map<string, string>();
  private agentsByBot = new Map<string, AgentSummary[]>();
  private terminalActionsConfig: TerminalActionsConfig = {
    schemaVersion: 1,
    configPath: `${DEMO_MAIN_WORKDIR}/scripts/terminal-actions.json`,
    exists: true,
    mtimeNs: "1",
    editable: true,
    errors: [],
    runtimePlatform: "windows",
    actions: [
      {
        id: "build",
        label: "构建",
        icon: "Hammer",
        windowsCommand: "npm run build",
        linuxCommand: "npm run build",
        macosCommand: "npm run build",
        cwd: ".",
        confirm: false,
        enabled: true,
      },
      {
        id: "test",
        label: "测试",
        icon: "TestTube2",
        windowsCommand: "python -m pytest tests -q",
        linuxCommand: "python3 -m pytest tests -q",
        macosCommand: "python3 -m pytest tests -q",
        cwd: ".",
        confirm: false,
        enabled: true,
      },
    ],
  };
  private gitOverviews = new Map<string, GitOverview>([
    [
      "main",
      {
        repoFound: true,
        canInit: false,
        workingDir: DEMO_MAIN_WORKDIR,
        repoPath: DEMO_MAIN_WORKDIR,
        repoName: "demo",
        currentBranch: "main",
        isClean: false,
        aheadCount: 1,
        behindCount: 0,
        changedFiles: [
          {
            path: "bot/web/server.py",
            status: "M ",
            staged: true,
            unstaged: false,
            untracked: false,
          },
          {
            path: "front/src/screens/GitScreen.tsx",
            status: "??",
            staged: false,
            unstaged: false,
            untracked: true,
          },
        ],
        recentCommits: [
          {
            hash: "847b894",
            shortHash: "847b894",
            authorName: "Web Bot",
            authoredAt: "2026-04-08 03:00:00 +0800",
            subject: "feat: 实现完整的Web前端与后端集成",
          },
        ],
      },
    ],
    [
      "team2",
      {
        repoFound: true,
        canInit: false,
        workingDir: DEMO_TEAM_WORKDIR,
        repoPath: DEMO_TEAM_WORKDIR,
        repoName: "plans",
        currentBranch: "feature/git-panel",
        isClean: true,
        aheadCount: 0,
        behindCount: 0,
        changedFiles: [],
        recentCommits: [
          {
            hash: "cfb8d40",
            shortHash: "cfb8d40",
            authorName: "Web Bot",
            authoredAt: "2026-04-09 13:00:00 +0800",
            subject: "docs: add web tunnel and cli settings design",
          },
        ],
      },
    ],
  ]);
  private gitBranches = new Map<string, GitBranchList>();
  private gitStashes = new Map<string, GitStashList>([
    [
      "main",
      {
        items: [
          {
            ref: "stash@{0}",
            hash: "abc1234",
            createdAt: "2026-04-28 10:30:00 +0800",
            message: "On main: Web Bot stash 2026-04-28 10:30:00",
          },
        ],
      },
    ],
  ]);
  private gitIdentityConfigs = new Map<string, GitIdentityConfig>();
  private gitCommitMessageConfig: GitCommitMessageCliConfig | null = null;
  private gitSmartCommitJobs = new Map<string, GitSmartCommitJob>();
  private gitSmartCommitActiveJobs = new Map<string, string>();
  private gitSmartCommitJobSeq = 1;
  private gitProxySettings: GitProxySettings = { address: "", port: "" };
  private cliErrorStats: CliErrorStatsResult = {
    summary: {
      total: 3,
      byCliType: { codex: 2, kimi: 1 },
      byBot: { main: 2, reviewer: 1 },
      byCategory: { rate_limit: 2, resume_session: 1 },
      latestAt: "2026-05-31T10:20:00+08:00",
    },
    topErrors: [
      {
        message: "HTTP 429 rate limit reached",
        count: 2,
        category: "rate_limit",
        latestAt: "2026-05-31T10:20:00+08:00",
      },
      {
        message: "failed to resume: conversation not found",
        count: 1,
        category: "resume_session",
        latestAt: "2026-05-31T09:40:00+08:00",
      },
    ],
    items: [
      {
        botAlias: "main",
        cliType: "codex",
        workingDir: DEMO_MAIN_WORKDIR,
        conversationId: "conv_demo_1",
        turnId: "turn_demo_1",
        startedAt: "2026-05-31T10:20:00+08:00",
        completedAt: "2026-05-31T10:20:12+08:00",
        errorCode: "failed",
        errorMessage: "HTTP 429 rate limit reached",
        category: "rate_limit",
        durationMs: 12000,
      },
      {
        botAlias: "main",
        cliType: "codex",
        workingDir: DEMO_MAIN_WORKDIR,
        conversationId: "conv_demo_2",
        turnId: "turn_demo_2",
        startedAt: "2026-05-31T09:48:00+08:00",
        completedAt: "2026-05-31T09:48:04+08:00",
        errorCode: "failed",
        errorMessage: "HTTP 429 rate limit reached",
        category: "rate_limit",
        durationMs: 4000,
      },
      {
        botAlias: "reviewer",
        cliType: "kimi",
        workingDir: DEMO_TEAM_WORKDIR,
        conversationId: "conv_demo_3",
        turnId: "turn_demo_3",
        startedAt: "2026-05-31T09:40:00+08:00",
        completedAt: "2026-05-31T09:40:08+08:00",
        errorCode: "error",
        errorMessage: "failed to resume: conversation not found",
        category: "resume_session",
        durationMs: 8000,
      },
    ],
  };
  private updateStatus: AppUpdateStatus = {
    currentVersion: APP_VERSION,
    currentPackageKind: "installer",
    updateEnabled: true,
    updateChannel: "release",
    lastCheckedAt: "",
    latestVersion: APP_VERSION,
    latestReleaseUrl: MOCK_RELEASE_URL,
    latestNotes: "Bugfixes",
    pendingUpdateVersion: "",
    pendingUpdatePath: "",
    pendingUpdateNotes: "",
    pendingUpdatePlatform: "",
    pendingUpdatePackageKind: "",
    lastError: "",
  };
  private readonly avatarAssets: AvatarAsset[] = [
    { name: "avatar_01.png", url: "/assets/avatars/avatar_01.png" },
    { name: "avatar_02.png", url: "/assets/avatars/avatar_02.png" },
    { name: "avatar_03.png", url: "/assets/avatars/avatar_03.png" },
    { name: "avatar_04.png", url: "/assets/avatars/avatar_04.png" },
  ];
  private plugins: PluginSummary[] = [
    {
      id: "vivado-waveform",
      schemaVersion: 2,
      name: "Vivado Waveform",
      version: "0.1.0",
      description: "Vivado/HDL 波形预览，V1 支持 VCD。",
      enabled: true,
      config: { lodEnabled: true },
      configSchema: {
        title: "Waveform Settings",
        sections: [
          {
            id: "display",
            fields: [
              {
                key: "lodEnabled",
                label: "启用 LOD",
                type: "boolean",
                default: true,
                description: "缩放较大时自动降采样。",
              },
            ],
          },
        ],
      },
      views: [{ id: "waveform", title: "波形预览", renderer: "waveform", viewMode: "session", dataProfile: "heavy" }],
      fileHandlers: [{ id: "wave-vcd", label: "VCD 波形预览", extensions: [".vcd"], viewId: "waveform" }],
      runtime: {
        type: "python",
        entry: "backend/main.py",
        protocol: "jsonrpc-stdio",
        permissions: {},
      },
    },
    {
      id: "timing-report",
      schemaVersion: 2,
      name: "Timing Report",
      version: "0.2.0",
      description: "结构化 timing 表格视图。",
      enabled: true,
      config: { defaultPageSize: 2 },
      configSchema: {
        title: "Timing Settings",
        sections: [
          {
            id: "display",
            fields: [
              {
                key: "defaultPageSize",
                label: "默认页大小",
                type: "integer",
                default: 2,
                minimum: 1,
              },
            ],
          },
        ],
      },
      views: [{ id: "timing-table", title: "Timing Paths", renderer: "table", viewMode: "session", dataProfile: "heavy" }],
      fileHandlers: [{ id: "timing-rpt", label: "Timing 报告", extensions: [".rpt"], viewId: "timing-table" }],
      catalogActions: [{ id: "export-all", label: "导出 CSV", target: "plugin", location: "catalog", variant: "primary" }],
      runtime: {
        type: "python",
        entry: "backend/main.py",
        protocol: "jsonrpc-stdio",
        permissions: { workspaceRead: true, tempArtifacts: true },
      },
    },
    {
      id: "repo-outline",
      schemaVersion: 2,
      name: "Repo Outline",
      version: "0.1.0",
      description: "浏览仓库目录、文件和符号。",
      enabled: true,
      config: {
        includeHidden: false,
        maxFiles: 2000,
        maxSymbolsPerFile: 200,
        codeExtensions: ".py,.ts,.tsx,.js,.jsx,.go,.rs,.java,.kt,.md",
      },
      configSchema: {
        title: "仓库大纲设置",
        sections: [
          {
            id: "scan",
            fields: [
              { key: "includeHidden", label: "包含隐藏目录", type: "boolean", default: false },
              { key: "maxFiles", label: "最大扫描文件数", type: "integer", default: 2000, minimum: 200, maximum: 20000 },
              { key: "maxSymbolsPerFile", label: "单文件最大符号数", type: "integer", default: 200, minimum: 20, maximum: 1000 },
              { key: "codeExtensions", label: "代码扩展名", type: "string", default: ".py,.ts,.tsx,.js,.jsx,.go,.rs,.java,.kt,.md" },
            ],
          },
        ],
      },
      views: [{ id: "repo-tree", title: "文件夹大纲", renderer: "tree", viewMode: "session", dataProfile: "light" }],
      fileHandlers: [],
      catalogActions: [
        {
          id: "open-outline",
          label: "选择文件夹大纲",
          target: "host",
          location: "catalog",
          variant: "primary",
          payload: {
            folderPicker: true,
            folderInputKey: "path",
            folderTitle: "选择要生成大纲的文件夹",
          },
          hostAction: {
            type: "open_plugin_view",
            pluginId: "repo-outline",
            viewId: "repo-tree",
            title: "文件夹大纲",
            input: {},
          },
        },
      ],
      runtime: {
        type: "python",
        entry: "backend/main.py",
        protocol: "jsonrpc-stdio",
        permissions: { workspaceRead: true, workspaceList: true },
      },
    },
    {
      id: "rtl-hierarchy",
      schemaVersion: 2,
      name: "RTL Hierarchy",
      version: "0.2.0",
      description: "模块层级树视图。",
      enabled: true,
      config: {},
      views: [{ id: "module-tree", title: "Hierarchy", renderer: "tree", viewMode: "session", dataProfile: "light" }],
      fileHandlers: [{ id: "rtl-hier", label: "层级视图", extensions: [".hier"], viewId: "module-tree" }],
      catalogActions: [
        {
          id: "open-timing",
          label: "打开 Timing",
          target: "host",
          location: "catalog",
          hostAction: {
            type: "open_plugin_view",
            pluginId: "timing-report",
            viewId: "timing-table",
            title: "timing.rpt",
            input: { path: "reports/timing.rpt" },
          },
        },
      ],
      runtime: {
        type: "python",
        entry: "backend/main.py",
        protocol: "jsonrpc-stdio",
        permissions: { workspaceRead: true },
      },
    },
  ];
  private installablePlugins: InstallablePluginSummary[] = [
    {
      id: "document-renderer",
      pluginId: "document-renderer",
      name: "Document Renderer",
      version: "0.1.0",
      description: "快速预览 docx 等文档内容。",
      installed: false,
    },
  ];
  private assistantCronJobs = new Map<string, AssistantCronJob[]>();
  private assistantCronRuns = new Map<string, AssistantCronRun[]>();
  private assistantProposals = new Map<string, AssistantProposal[]>();
  private assistantProposalDiffs = new Map<string, string>();
  private assistantProposalPatchDiffs = new Map<string, string>();
  private assistantProposalPatchMetadata = new Map<string, AssistantPatchMetadata>();
  private assistantProposalApplyLogs = new Map<string, AssistantUpgradeApplyLog>();
  private assistantMemories = new Map<string, AssistantMemorySearchItem[]>();
  private assistantMemoryEvalReports = new Map<string, AssistantMemoryEvalReport[]>();
  private assistantPerfRecords = new Map<string, AssistantPerfRecord[]>();
  private assistantAdminAudit = new Map<string, AssistantAdminAuditItem[]>();
  private fileContents = new Map<string, string>();
  private fileVersions = new Map<string, number>();
  private registerCodes: RegisterCodeItem[] = [
    {
      codeId: "invite-demo-1",
      codePreview: "INV***001",
      disabled: false,
      maxUses: 3,
      usedCount: 1,
      remainingUses: 2,
      createdAt: "2026-04-22T01:00:00Z",
      createdBy: "127.0.0.1",
      lastUsedAt: "2026-04-22T02:00:00Z",
      usage: [{ usedAt: "2026-04-22T02:00:00Z", usedBy: "alice" }],
    },
  ];
  private announcements: AnnouncementItem[] = [
    {
      id: "ann-2026-05-13-demo",
      publishedAt: "2026-05-13T09:00:00+08:00",
      publisher: "CLI Bridge",
      title: "公告中心",
      category: "feature",
      severity: "info",
      summary: "公告会在新内容发布后自动提醒。",
      sections: [
        { label: "新增", items: ["登录后自动弹出", "右上角可再次打开"] },
        { label: "操作", items: ["看完后点关闭即可"] },
      ],
    },
  ];
  private announcementReads = new Map<string, string>();
  private adminUsers = new Map<string, Omit<AdminUser, "ownedBots" | "ownedBotCount">>([
    ["demo", {
      accountId: "demo",
      username: "demo",
      role: "member",
      disabled: false,
      capabilities: [...MEMBER_CAPABILITIES],
      createdAt: "2026-05-01T09:00:00+08:00",
      allowedBots: ["main", "team2"],
      botCreateLimit: MEMBER_BOT_LIMIT,
    }],
    ["alice", {
      accountId: "alice",
      username: "alice",
      role: "member",
      disabled: false,
      capabilities: [...MEMBER_CAPABILITIES],
      createdAt: "2026-05-02T09:00:00+08:00",
      allowedBots: ["main"],
      botCreateLimit: MEMBER_BOT_LIMIT,
    }],
  ]);
  private envItems: EnvConfigItem[] = createMockEnvItems();
  private botOwners = new Map<string, string>([
    ["team2", "demo"],
  ]);
  private offlineUpdatePackages: OfflineUpdatePackageList = {
    artifactsDir: ".release-local/artifacts",
    items: [
      {
        name: "orbit-safe-claw-windows-x64-installer-1.2.3.zip",
        path: ".release-local/artifacts/orbit-safe-claw-windows-x64-installer-1.2.3.zip",
        version: "1.2.3",
        packageKind: "installer",
        sizeBytes: 2_048,
        valid: true,
        error: "",
      },
      {
        name: "orbit-safe-claw-macos-universal-1.2.3.tar.gz",
        path: ".release-local/artifacts/orbit-safe-claw-macos-universal-1.2.3.tar.gz",
        version: "1.2.3",
        packageKind: "macos",
        sizeBytes: 2_560,
        valid: true,
        error: "",
      },
      {
        name: "broken-package.zip",
        path: ".release-local/artifacts/broken-package.zip",
        version: "",
        packageKind: "unknown",
        sizeBytes: 512,
        valid: false,
        error: "包校验失败",
      },
    ],
  };
  private session: SessionState = {
    currentBotAlias: "main",
    currentPath: "/",
    isLoggedIn: true,
    token: "mock-session-member",
    userId: 1001,
    accountId: "demo",
    username: "demo",
    role: "member",
    capabilities: [...MEMBER_CAPABILITIES],
    isLocalAdmin: false,
  };
  private lanChatConfig: LanChatConfig = {
    mode: "host",
    roomName: "工作室",
    instanceId: "inst_mock",
    instanceName: "演示机",
    hostUrl: "",
    roomKey: "tcbr_mock_demo",
    roomKeyPreview: "tcbr...demo",
    lanOnly: true,
    autoConnect: true,
  };
  private lanChatUsers: LanChatParticipant[] = [
    {
      roomUserId: "inst_b:member_bob",
      accountId: "member_bob",
      username: "bob",
      displayName: "Bob",
      instanceId: "inst_b",
      instanceName: "设计机",
      online: true,
      lastSeenAt: "2026-05-18T12:00:00+08:00",
    },
  ];
  private lanChatConversations = new Map<string, LanChatConversation>([
    ["group:default", {
      id: "group:default",
      kind: "group",
      title: "工作室",
      participantIds: [],
      lastMessage: null,
      unreadCount: 0,
      updatedAt: "2026-05-18T12:00:00+08:00",
    }],
  ]);
  private lanChatMessages: LanChatMessage[] = [];
  private lanChatReadSeq = new Map<string, number>();
  private lanChatSocketListeners = new Set<(event: LanChatEvent) => void>();

  private normalizeEnvValue(item: EnvConfigItem, patchValue: EnvConfigPatchValue): EnvConfigItem["value"] {
    if (patchValue && typeof patchValue === "object" && !Array.isArray(patchValue)) {
      if (patchValue.masked) {
        return item.value;
      }
      if (patchValue.action === "clear") {
        return item.type === "csv" ? [] : item.type === "boolean" ? false : item.type === "number" ? 0 : "";
      }
      if (patchValue.action === "regenerate") {
        return `mock_${Math.random().toString(36).slice(2, 14)}`;
      }
      return this.normalizeEnvValue(item, patchValue.value ?? "");
    }
    if (item.type === "boolean") {
      return patchValue === true || patchValue === "true" || patchValue === "1";
    }
    if (item.type === "number") {
      return Number(patchValue || 0);
    }
    if (item.type === "csv") {
      return Array.isArray(patchValue)
        ? patchValue.map(String)
        : String(patchValue || "").split(",").map((value) => value.trim()).filter(Boolean);
    }
    return String(patchValue ?? "");
  }

  private buildEnvPatchResult(input: EnvConfigPatchInput, apply: boolean): EnvConfigPatchResult {
    const changedKeys: string[] = [];
    const restartRequiredKeys: string[] = [];
    const rebuildRequiredKeys: string[] = [];
    const nextItems = this.envItems.map((item) => {
      if (!Object.prototype.hasOwnProperty.call(input.values, item.key)) {
        return item;
      }
      const nextValue = this.normalizeEnvValue(item, input.values[item.key]);
      const currentText = Array.isArray(item.value) ? item.value.join(",") : String(item.value);
      const nextText = Array.isArray(nextValue) ? nextValue.join(",") : String(nextValue);
      if (currentText === nextText) {
        return item;
      }
      changedKeys.push(item.key);
      if (item.restartRequired) {
        restartRequiredKeys.push(item.key);
      }
      if (item.rebuildRequired) {
        rebuildRequiredKeys.push(item.key);
      }
      return {
        ...item,
        value: nextValue,
        source: "env",
        masked: item.sensitive && nextText.length > 0,
      };
    });
    if (apply) {
      this.envItems = nextItems;
    }
    return {
      changedKeys,
      restartRequiredKeys,
      rebuildRequiredKeys,
      backupPath: apply && changedKeys.length ? ".env.bak.20260524102000" : "",
    };
  }

  private moveKey<T>(map: Map<string, T>, oldKey: string, newKey: string) {
    if (!map.has(oldKey)) {
      return;
    }
    const value = map.get(oldKey) as T;
    map.delete(oldKey);
    map.set(newKey, value);
  }

  private moveAgentScopedKeys<T>(map: Map<string, T>, oldAlias: string, newAlias: string) {
    for (const [key, value] of Array.from(map.entries())) {
      if (key !== oldAlias && !key.startsWith(`${oldAlias}:`)) {
        continue;
      }
      map.delete(key);
      map.set(`${newAlias}${key.slice(oldAlias.length)}`, value);
    }
  }

  private currentAccountId() {
    return String(this.session.accountId || this.session.username || "").trim();
  }

  private lanChatSelf(): LanChatParticipant {
    const accountId = this.currentAccountId() || "member_demo";
    const username = this.session.username || "demo";
    return {
      roomUserId: `${this.lanChatConfig.instanceId}:${accountId}`,
      accountId,
      username,
      displayName: username,
      instanceId: this.lanChatConfig.instanceId,
      instanceName: this.lanChatConfig.instanceName,
      online: true,
      lastSeenAt: new Date().toISOString(),
    };
  }

  private lanChatNow() {
    return new Date().toISOString();
  }

  private cloneLanChatMessage(message: LanChatMessage): LanChatMessage {
    return {
      ...message,
      sender: { ...message.sender },
    };
  }

  private cloneLanChatConversation(conversation: LanChatConversation): LanChatConversation {
    return {
      ...conversation,
      participantIds: [...conversation.participantIds],
      lastMessage: conversation.lastMessage ? this.cloneLanChatMessage(conversation.lastMessage) : null,
    };
  }

  private lanChatConversationWithUnread(conversation: LanChatConversation): LanChatConversation {
    const lastReadSeq = this.lanChatReadSeq.get(conversation.id) || 0;
    const unreadCount = this.lanChatMessages
      .filter((message) => message.conversationId === conversation.id && message.seq > lastReadSeq)
      .length;
    return {
      ...this.cloneLanChatConversation(conversation),
      unreadCount,
    };
  }

  private buildLanChatStatus(): LanChatStatus {
    const self = this.lanChatSelf();
    return {
      mode: this.lanChatConfig.mode,
      connected: this.lanChatConfig.mode !== "off",
      roomName: this.lanChatConfig.roomName,
      self,
      onlineUsers: [self, ...this.lanChatUsers.map((user) => ({ ...user }))],
      onlineNodes: [
        { instanceId: this.lanChatConfig.instanceId, connected: this.lanChatConfig.mode !== "off" },
        ...this.lanChatUsers.map((user) => ({ instanceId: user.instanceId, connected: user.online })),
      ],
      lastError: "",
    };
  }

  private emitLanChatEvent(event: LanChatEvent) {
    for (const listener of this.lanChatSocketListeners) {
      listener(event);
    }
  }

  private isLocalAdminSession() {
    return this.session.username.trim() === "127.0.0.1" || this.session.capabilities.includes("manage_register_codes");
  }

  private hasAdminOps() {
    return this.session.username.trim() === "127.0.0.1" || this.session.capabilities.includes("admin_ops");
  }

  private ensureAdminUser(accountId: string, username = accountId) {
    const normalizedId = accountId.trim();
    if (!normalizedId || this.adminUsers.has(normalizedId) || this.isLocalAdminSession()) {
      return;
    }
    this.adminUsers.set(normalizedId, {
      accountId: normalizedId,
      username: username.trim() || normalizedId,
      role: "member",
      disabled: false,
      capabilities: resolveMemberCapabilities(username),
      createdAt: new Date().toISOString(),
      allowedBots: Array.from(this.bots.keys()),
      botCreateLimit: MEMBER_BOT_LIMIT,
    });
  }

  private normalizeAllowedBots(allowedBots: string[]) {
    return Array.from(new Set(
      allowedBots
        .map((item) => item.trim())
        .filter(Boolean),
    )).sort((left, right) => left.localeCompare(right, "zh-CN", { numeric: true, sensitivity: "base" }));
  }

  private getAllowedBotsForAccount(accountId: string) {
    const user = this.adminUsers.get(accountId);
    return user ? [...user.allowedBots] : [];
  }

  private setAllowedBotsForAccount(accountId: string, allowedBots: string[]) {
    const user = this.adminUsers.get(accountId);
    if (!user) {
      return [];
    }
    const nextAllowedBots = this.normalizeAllowedBots(allowedBots);
    this.adminUsers.set(accountId, {
      ...user,
      allowedBots: nextAllowedBots,
    });
    return nextAllowedBots;
  }

  private getOwnedBotsForAccount(accountId: string) {
    return Array.from(this.botOwners.entries())
      .filter(([, ownerAccountId]) => ownerAccountId === accountId)
      .map(([alias]) => alias)
      .sort((left, right) => left.localeCompare(right, "zh-CN", { numeric: true, sensitivity: "base" }));
  }

  private canOperateBot(alias: string) {
    if (this.isLocalAdminSession()) {
      return true;
    }
    if (this.session.role !== "member") {
      return false;
    }
    return this.getAllowedBotsForAccount(this.currentAccountId()).includes(alias);
  }

  private effectiveCapabilitiesForBot(alias: string) {
    if (this.canOperateBot(alias)) {
      return [...this.session.capabilities];
    }
    return [...GUEST_CAPABILITIES];
  }

  private buildAdminUser(accountId: string): AdminUser | null {
    const current = this.adminUsers.get(accountId);
    if (!current) {
      return null;
    }
    const ownedBots = this.getOwnedBotsForAccount(accountId);
    return {
      ...current,
      allowedBots: [...current.allowedBots],
      ownedBots,
      ownedBotCount: ownedBots.length,
    };
  }

  private sortedAnnouncements() {
    return [...this.announcements].sort((left, right) => (
      `${right.publishedAt}|${right.id}`.localeCompare(`${left.publishedAt}|${left.id}`)
    ));
  }

  private cloneAnnouncement(item: AnnouncementItem): AnnouncementItem {
    return {
      ...item,
      sections: item.sections.map((section) => ({
        label: section.label,
        items: [...section.items],
      })),
    };
  }

  private formatAnnouncementTimestamp(date: Date) {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(date);
    const value = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value || "";
    const datePart = `${value("year")}-${value("month")}-${value("day")}`;
    const timePart = `${value("hour")}:${value("minute")}`;
    return {
      idBase: `ann-${datePart}-${value("hour")}-${value("minute")}`,
      publishedAt: `${datePart}T${timePart}:00+08:00`,
    };
  }

  private nextAnnouncementId(baseId: string) {
    const existingIds = new Set(this.announcements.map((item) => item.id));
    if (!existingIds.has(baseId)) {
      return baseId;
    }
    let index = 2;
    while (true) {
      const candidate = `${baseId}-${String(index).padStart(2, "0")}`;
      if (!existingIds.has(candidate)) {
        return candidate;
      }
      index += 1;
    }
  }

  private normalizeAnnouncementInput(input: CreateAnnouncementInput): AnnouncementItem {
    const { idBase, publishedAt } = this.formatAnnouncementTimestamp(new Date());
    return this.cloneAnnouncement({
      ...input,
      id: this.nextAnnouncementId(idBase),
      publishedAt,
    });
  }

  private buildAnnouncementList(): AnnouncementListResult {
    const items = this.sortedAnnouncements();
    const latestId = items[0]?.id || "";
    const lastSeenId = this.announcementReads.get(this.currentAccountId()) || "";
    return {
      items: items.map((item) => this.cloneAnnouncement(item)),
      latestId,
      lastSeenId,
      hasUnseen: Boolean(latestId && latestId !== lastSeenId),
    };
  }

  private normalizeNativeAgentConfig(input: BotExecutionConfigInput["nativeAgent"] | CreateBotInput["nativeAgent"] | undefined, current?: BotSummary["nativeAgent"]): BotSummary["nativeAgent"] {
    const opencodeAgent = String(input?.opencodeAgent || "").trim();
    const model = String(input?.model || current?.model || "").trim();
    return {
      provider: "",
      model,
      opencodeAgent,
      baseUrl: "",
      hasApiKey: false,
      apiKeyMasked: "",
    };
  }

  private extractNativeAgentModels(config: Record<string, unknown>): NativeAgentModelOption[] {
    const providerMap = config.provider && typeof config.provider === "object"
      ? config.provider as Record<string, unknown>
      : {};
    const items: NativeAgentModelOption[] = [];
    for (const [provider, providerValue] of Object.entries(providerMap)) {
      if (!providerValue || typeof providerValue !== "object") continue;
      const models = (providerValue as Record<string, unknown>).models;
      if (!models || typeof models !== "object") continue;
      for (const [model, modelValue] of Object.entries(models as Record<string, unknown>)) {
        const modelRecord = modelValue && typeof modelValue === "object" ? modelValue as Record<string, unknown> : {};
        const limit = modelRecord.limit && typeof modelRecord.limit === "object" ? modelRecord.limit as Record<string, unknown> : {};
        const name = String(modelRecord.name || model);
        items.push({
          id: `${provider}/${model}`,
          provider,
          model,
          name,
          label: `${provider} / ${name}`,
          ...(typeof limit.context === "number" ? { contextWindow: limit.context } : {}),
          ...(typeof limit.output === "number" ? { outputLimit: limit.output } : {}),
        });
      }
    }
    return items;
  }

  private getBotSummary(botAlias: string): BotSummary {
    const fallback = this.bots.get("main") || Array.from(this.bots.values())[0];
    const base = this.bots.get(botAlias) || fallback;
    if (!base) {
      return {
        alias: botAlias,
        cliType: "codex",
        status: "running",
        workingDir: DEMO_MAIN_WORKDIR,
        lastActiveText: "运行中",
        avatarName: "avatar_01.png",
        cliPath: "codex",
        botMode: "cli",
        enabled: true,
        isMain: false,
        promptPresets: [],
        cluster: { ...DEFAULT_CLUSTER, modelTiers: { ...DEFAULT_CLUSTER.modelTiers } },
      };
    }
    const workingDir = this.workdirOverrides.get(base.alias) || base.workingDir;
    const serviceStatus = base.serviceStatus || (base.status === "offline" ? "offline" : "online");
    const activityStatus = base.activityStatus || (base.status === "busy" ? "busy" : "idle");
    const busyAgentIds = base.busyAgentIds || [];
    const busyAgentNames = base.busyAgentNames || [];
    const busyAgentCount = base.busyAgentCount ?? busyAgentIds.length;
    const ownerAccountId = this.botOwners.get(base.alias) || base.ownerAccountId || "";
    return {
      ...base,
      serviceStatus,
      activityStatus,
      busyAgentIds,
      busyAgentNames,
      busyAgentCount,
      workingDir,
      canOperate: typeof base.canOperate === "boolean" ? base.canOperate : this.canOperateBot(base.alias),
      effectiveCapabilities: base.effectiveCapabilities || this.effectiveCapabilitiesForBot(base.alias),
      ownerAccountId,
      ownerUsername: base.ownerUsername || this.adminUsers.get(ownerAccountId)?.username || "",
      isOwnedByCurrentUser: ownerAccountId !== "" && ownerAccountId === this.currentAccountId(),
      promptPresets: clonePromptPresets(base.promptPresets),
      globalPromptPresets: clonePromptPresets(this.globalPromptPresets),
      nativeAgent: this.normalizeNativeAgentConfig(base.nativeAgent, base.nativeAgent),
      cluster: base.cluster
        ? { ...base.cluster, modelTiers: { ...base.cluster.modelTiers } }
        : { ...DEFAULT_CLUSTER, modelTiers: { ...DEFAULT_CLUSTER.modelTiers } },
    };
  }

  private clonePluginSummary(plugin: PluginSummary): PluginSummary {
    return {
      ...plugin,
      config: { ...(plugin.config || {}) },
      configSchema: plugin.configSchema
        ? {
            title: plugin.configSchema.title,
            sections: plugin.configSchema.sections.map((section) => ({
              ...section,
              fields: section.fields.map((field) => ({
                ...field,
                options: "options" in field && field.options
                  ? field.options.map((option) => ({ ...option }))
                  : undefined,
              })),
            })),
          }
        : undefined,
      catalogActions: clonePluginActions(plugin.catalogActions),
      views: plugin.views.map((view) => ({ ...view })),
      fileHandlers: plugin.fileHandlers.map((handler) => ({ ...handler, extensions: [...handler.extensions] })),
      runtime: plugin.runtime
        ? {
            ...plugin.runtime,
            permissions: plugin.runtime.permissions ? { ...plugin.runtime.permissions } : undefined,
          }
        : undefined,
    };
  }

  private cloneInstallablePlugin(plugin: InstallablePluginSummary): InstallablePluginSummary {
    return { ...plugin };
  }

  private getPathTail(path: string): string {
    const parts = path.trim().split(/[\\/]+/).filter(Boolean);
    return parts[parts.length - 1] || "custom-plugin";
  }

  private buildInstalledPluginFromInstallable(plugin: InstallablePluginSummary): PluginSummary {
    return {
      id: plugin.pluginId || plugin.id,
      schemaVersion: 2,
      name: plugin.name,
      version: plugin.version || "0.1.0",
      description: plugin.description,
      enabled: true,
      config: {},
      views: [{ id: "document-view", title: "文档预览", renderer: "document", viewMode: "snapshot", dataProfile: "light" }],
      fileHandlers: [{ id: "docx-preview", label: "文档预览", extensions: [".docx"], viewId: "document-view" }],
      runtime: {
        type: "python",
        entry: "backend/main.py",
        protocol: "jsonrpc-stdio",
        permissions: { workspaceRead: true },
      },
    };
  }

  private buildInstalledPluginFromSourcePath(sourcePath: string): PluginSummary {
    const folderName = this.getPathTail(sourcePath);
    const pluginId = folderName.toLowerCase();
    const title = folderName
      .split(/[-_]+/)
      .filter(Boolean)
      .map((part) => part[0]?.toUpperCase() + part.slice(1))
      .join(" ") || "Custom Plugin";
    return {
      id: pluginId,
      schemaVersion: 2,
      name: title,
      version: "0.1.0",
      description: `${sourcePath} 安装的插件`,
      enabled: true,
      config: {},
      views: [],
      fileHandlers: [],
      runtime: {
        type: "python",
        entry: "backend/main.py",
        protocol: "jsonrpc-stdio",
        permissions: {},
      },
    };
  }

  private getBrowserPath(botAlias: string): string {
    return this.currentPaths.get(botAlias) || this.getBotSummary(botAlias).workingDir;
  }

  private resolveTargetDir(botAlias: string, parentPath?: string): string {
    const candidate = parentPath?.trim();
    return candidate && candidate.length > 0 ? candidate : this.getBrowserPath(botAlias);
  }

  private normalizeMockPath(path: string): string {
    return path.trim().replace(/\\/g, "/").replace(/\/+$/g, "") || "/";
  }

  private resolveFileTreePath(botAlias: string, path: string): string {
    const candidate = this.normalizeMockPath(path);
    if (candidate.startsWith("/")) {
      return candidate;
    }
    const root = this.normalizeMockPath(this.getBrowserPath(botAlias));
    return root === "/" ? `/${candidate}` : `${root}/${candidate}`;
  }

  private splitMockFilePath(fullPath: string) {
    const normalized = this.normalizeMockPath(fullPath);
    const lastSlash = normalized.lastIndexOf("/");
    if (lastSlash <= 0) {
      return { dir: "/", name: normalized.replace(/^\/+/, "") };
    }
    return {
      dir: normalized.slice(0, lastSlash),
      name: normalized.slice(lastSlash + 1),
    };
  }

  private relativeMockPath(botAlias: string, fullPath: string): string {
    const root = this.normalizeMockPath(this.getBrowserPath(botAlias));
    const normalized = this.normalizeMockPath(fullPath);
    if (normalized === root) {
      return "";
    }
    if (normalized.startsWith(`${root}/`)) {
      return normalized.slice(root.length + 1);
    }
    return normalized.replace(/^\/+/, "");
  }

  private buildCopyName(botFiles: Record<string, FileEntry[]>, dir: string, sourceName: string) {
    const dotIndex = sourceName.lastIndexOf(".");
    const hasExtension = dotIndex > 0 && dotIndex < sourceName.length - 1;
    const stem = hasExtension ? sourceName.slice(0, dotIndex) : sourceName;
    const suffix = hasExtension ? sourceName.slice(dotIndex) : "";
    const existing = new Set((botFiles[dir] || []).map((entry) => entry.name));
    let candidate = `${stem} 副本${suffix}`;
    let counter = 2;
    while (existing.has(candidate)) {
      candidate = `${stem} 副本 ${counter}${suffix}`;
      counter += 1;
    }
    return candidate;
  }

  private sortFileEntries(entries: Array<{ name: string; isDir: boolean }>) {
    entries.sort((left, right) => {
      if (left.isDir !== right.isDir) {
        return left.isDir ? -1 : 1;
      }
      return left.name.localeCompare(right.name, "zh-CN");
    });
  }

  private cronRunKey(botAlias: string, jobId: string): string {
    return `${botAlias}:${jobId}`;
  }

  private assistantProposalKey(botAlias: string, proposalId: string): string {
    return `${botAlias}:${proposalId}`;
  }

  private buildMockUpgradeTarget(botAlias: string): AssistantUpgradeTarget {
    const bot = this.getBotSummary(botAlias);
    const dirty = bot.alias === "assistant1";
    return {
      alias: bot.alias,
      workingDir: bot.workingDir,
      repoRoot: bot.workingDir,
      head: bot.alias === "main" ? "a1b2c3d4" : "b2c3d4e5",
      dirty,
      dirtyPaths: dirty ? [" M bot/assistant_memory_recall.py"] : [],
      botMode: bot.botMode || "cli",
      cliType: bot.cliType || "",
      cliPath: bot.cliPath || "",
      available: Boolean(bot.workingDir) && !dirty,
      reason: !bot.workingDir ? "working_dir_not_found" : (dirty ? "upgrade_target_dirty" : ""),
    };
  }

  private getAssistantPatchMetadata(botAlias: string, proposalId: string): AssistantPatchMetadata | null {
    return this.assistantProposalPatchMetadata.get(this.assistantProposalKey(botAlias, proposalId)) || null;
  }

  private appendChatMessage(botAlias: string, message: ChatMessage) {
    this.appendAgentChatMessage(botAlias, "main", message);
  }

  private agentKey(botAlias: string, agentId = "main") {
    return `${botAlias}:${agentId || "main"}`;
  }

  private getAgentMessages(botAlias: string, agentId = "main") {
    if (agentId === "main") {
      return mockChatMessages[botAlias] || [];
    }
    const key = this.agentKey(botAlias, agentId);
    if (!mockChatMessages[key]) {
      mockChatMessages[key] = [];
    }
    return mockChatMessages[key];
  }

  private appendAgentChatMessage(botAlias: string, agentId: string, message: ChatMessage) {
    const key = agentId === "main" ? botAlias : this.agentKey(botAlias, agentId);
    if (!mockChatMessages[key]) {
      mockChatMessages[key] = [];
    }
    mockChatMessages[key].push(message);
  }

  private getConversationKey(botAlias: string, agentId = "main") {
    return agentId === "main" ? botAlias : this.agentKey(botAlias, agentId);
  }

  private mainAgent(): AgentSummary {
    return {
      id: "main",
      name: "主 agent",
      systemPrompt: "",
      enabled: true,
      isMain: true,
      cluster: { ...DEFAULT_AGENT_CLUSTER },
    };
  }

  private ensureAgents(botAlias: string) {
    const existing = this.agentsByBot.get(botAlias);
    if (existing) {
      return existing;
    }
    const items = [this.mainAgent()];
    this.agentsByBot.set(botAlias, items);
    return items;
  }

  private cloneAgent(agent: AgentSummary): AgentSummary {
    return { ...agent, cluster: agent.cluster ? { ...agent.cluster } : { ...DEFAULT_AGENT_CLUSTER } };
  }

  private buildAssistantUpgradeState(botAlias: string, proposal: AssistantProposal) {
    const metadata = this.getAssistantPatchMetadata(botAlias, proposal.id);
    const key = this.assistantProposalKey(botAlias, proposal.id);
    const hasPatch = this.assistantProposalPatchDiffs.has(key);
    const lifecycle = metadata?.lifecycle || metadata?.state || "";
    const state = proposal.status === "applied"
      ? "applied"
      : (lifecycle === "failed" ? "failed" : (metadata?.state || "none"));
    return {
      state,
      targetAlias: metadata?.targetAlias || "",
      targetRepoRoot: metadata?.targetRepoRoot || "",
      baseCommit: metadata?.baseCommit || "",
      patchSource: hasPatch && metadata ? `upgrades/${metadata.state}/${proposal.id}.patch` : "",
      generationStatus: metadata?.generator.status || "",
      chatConclusion: String((metadata as Record<string, unknown> | null)?.chatConclusion || ""),
      sensitiveHits: metadata?.sensitiveHits || [],
      dryRun: metadata?.dryRun || {
        ok: false,
        checkedAt: "",
        stdout: "",
        stderr: "",
        patchPath: "",
        repoRoot: "",
      },
      canGenerate: proposal.status === "approved",
      canApprovePatch: metadata?.state === "pending" && lifecycle !== "failed" && (metadata.sensitiveHits?.length || 0) === 0,
      canDryRun: metadata?.state === "approved",
      canApply: metadata?.state === "approved" && proposal.status !== "applied",
    };
  }

  private pushAssistantAdminAudit(
    botAlias: string,
    input: {
      action: string;
      resource: string;
      resourceId?: string;
      requestSummary?: Record<string, unknown>;
      ok?: boolean;
      statusCode?: number;
      errorCode?: string;
      errorMessage?: string;
      method?: string;
      path?: string;
      elapsedMs?: number;
    },
  ) {
    const current = this.assistantAdminAudit.get(botAlias) || [];
    const ok = input.ok !== false;
    const createdAt = new Date().toISOString();
    this.assistantAdminAudit.set(botAlias, [{
      id: `audit_${Date.now()}_${current.length + 1}`,
      createdAt,
      accountId: this.session.accountId || this.session.username || "demo",
      userId: this.session.userId || 1001,
      username: this.session.username || "demo",
      method: input.method || "POST",
      path: input.path || `/api/admin/bots/${botAlias}/assistant/${input.resource}`,
      action: input.action,
      target: {
        botAlias,
        resource: input.resource,
        resourceId: input.resourceId || "",
      },
      requestSummary: input.requestSummary || {},
      statusCode: input.statusCode || (ok ? 200 : 400),
      ok,
      errorCode: input.errorCode,
      errorMessage: input.errorMessage,
      elapsedMs: input.elapsedMs || 12,
    }, ...current]);
  }

  private fileKey(botAlias: string, browserPath: string, filename: string): string {
    return `${botAlias}:${browserPath}:${filename}`;
  }

  private getFileContent(botAlias: string, browserPath: string, filename: string): string {
    const key = this.fileKey(botAlias, browserPath, filename);
    if (this.fileContents.has(key)) {
      return this.fileContents.get(key) || "";
    }
    return `Mock full content for ${filename}\n\nThis is the full file content.`;
  }

  private getFileVersion(botAlias: string, browserPath: string, filename: string): number {
    const key = this.fileKey(botAlias, browserPath, filename);
    if (!this.fileVersions.has(key)) {
      this.fileVersions.set(key, Date.now() * 1_000_000);
    }
    return this.fileVersions.get(key) || Date.now() * 1_000_000;
  }

  private setFileState(botAlias: string, browserPath: string, filename: string, content: string): number {
    const key = this.fileKey(botAlias, browserPath, filename);
    const version = Date.now() * 1_000_000 + Math.floor(Math.random() * 1_000);
    this.fileContents.set(key, content);
    this.fileVersions.set(key, version);
    return version;
  }

  private ensureAssistantOpsState(botAlias: string) {
    const state = createMockAssistantOpsState(botAlias);
    if (!this.assistantProposals.has(botAlias)) {
      this.assistantProposals.set(botAlias, structuredClone(state.proposals));
    }
    for (const [proposalId, diffText] of Object.entries(state.proposalDiffs)) {
      const key = this.assistantProposalKey(botAlias, proposalId);
      if (!this.assistantProposalDiffs.has(key)) {
        this.assistantProposalDiffs.set(key, diffText);
      }
    }
    for (const [proposalId, diffText] of Object.entries(state.proposalPatchDiffs)) {
      const key = this.assistantProposalKey(botAlias, proposalId);
      if (!this.assistantProposalPatchDiffs.has(key)) {
        this.assistantProposalPatchDiffs.set(key, diffText);
      }
    }
    for (const [proposalId, metadata] of Object.entries(state.proposalPatchMetadata)) {
      const key = this.assistantProposalKey(botAlias, proposalId);
      if (!this.assistantProposalPatchMetadata.has(key)) {
        this.assistantProposalPatchMetadata.set(key, structuredClone(metadata));
      }
    }
    if (!this.assistantMemories.has(botAlias)) {
      this.assistantMemories.set(botAlias, structuredClone(state.memories));
    }
    if (!this.assistantMemoryEvalReports.has(botAlias)) {
      this.assistantMemoryEvalReports.set(botAlias, structuredClone(state.evalReports));
    }
    if (!this.assistantPerfRecords.has(botAlias)) {
      this.assistantPerfRecords.set(botAlias, structuredClone(state.perfRecords));
    }
    if (!this.assistantAdminAudit.has(botAlias)) {
      this.assistantAdminAudit.set(botAlias, []);
    }
  }

  private getAssistantCronJobs(botAlias: string): AssistantCronJob[] {
    return [...(this.assistantCronJobs.get(botAlias) || [])];
  }

  private getAssistantProposals(botAlias: string): AssistantProposal[] {
    this.ensureAssistantOpsState(botAlias);
    return [...(this.assistantProposals.get(botAlias) || [])];
  }

  private getAssistantMemories(botAlias: string): AssistantMemorySearchItem[] {
    this.ensureAssistantOpsState(botAlias);
    return [...(this.assistantMemories.get(botAlias) || [])];
  }

  private getAssistantMemoryEvalReports(botAlias: string): AssistantMemoryEvalReport[] {
    this.ensureAssistantOpsState(botAlias);
    return [...(this.assistantMemoryEvalReports.get(botAlias) || [])];
  }

  private getAssistantPerfRecords(botAlias: string): AssistantPerfRecord[] {
    this.ensureAssistantOpsState(botAlias);
    return [...(this.assistantPerfRecords.get(botAlias) || [])];
  }

  private getAssistantAdminAudit(botAlias: string): AssistantAdminAuditItem[] {
    this.ensureAssistantOpsState(botAlias);
    return [...(this.assistantAdminAudit.get(botAlias) || [])];
  }

  private buildAssistantRuntime(botAlias: string): AssistantRuntimeSnapshot | null {
    const bot = this.bots.get(botAlias);
    if (!bot || bot.botMode !== "assistant") {
      return null;
    }
    const queue = this.getAssistantCronJobs(botAlias)
      .filter((job) => job.pending && job.pendingRunId)
      .map((job) => {
        const run = (this.assistantCronRuns.get(this.cronRunKey(botAlias, job.id)) || [])
          .find((item) => item.runId === job.pendingRunId);
        return {
          runId: job.pendingRunId,
          source: "manual" as const,
          status: "queued" as const,
          taskMode: job.task.mode || "standard",
          interactive: false,
          jobId: job.id,
          jobTitle: job.title,
          visibleText: job.task.prompt,
          enqueuedAt: run?.enqueuedAt || "",
        };
      });
    return {
      pendingCount: queue.length,
      queuedCount: queue.length,
      active: null,
      queue,
    };
  }

  async getPublicHostInfo(): Promise<PublicHostInfo> {
    return {
      username: "demo",
      operatingSystem: "Windows 11",
      hardwarePlatform: "AMD64",
      hardwareSpec: "16 逻辑核心 · 32 GB 内存",
    };
  }

  async login(_input: { username: string; password: string } | string): Promise<SessionState> {
    const legacyToken = typeof _input === "string"
      ? _input
      : !_input.password
        ? _input.username.trim()
        : "";
    const username = typeof _input === "string"
      ? _input.trim() || "alice"
      : _input.username.trim() || "alice";
    this.session = {
      currentBotAlias: "main",
      currentPath: "/",
      isLoggedIn: true,
      token: legacyToken || "mock-session-member",
      userId: 1001,
      accountId: username,
      username,
      role: "member",
      capabilities: resolveMemberCapabilities(username),
      isLocalAdmin: username === "127.0.0.1",
    };
    this.ensureAdminUser(this.currentAccountId(), username);
    return { ...this.session };
  }

  async register(input: { username: string; password: string; registerCode: string }): Promise<SessionState> {
    this.session = {
      currentBotAlias: "main",
      currentPath: "/",
      isLoggedIn: true,
      token: "mock-session-member",
      userId: 1001,
      accountId: input.username,
      username: input.username,
      role: "member",
      capabilities: resolveMemberCapabilities(input.username),
      isLocalAdmin: input.username === "127.0.0.1",
    };
    this.ensureAdminUser(this.currentAccountId(), input.username);
    return { ...this.session };
  }

  async loginGuest(): Promise<SessionState> {
    this.session = {
      currentBotAlias: "main",
      currentPath: "/",
      isLoggedIn: true,
      token: "mock-session-guest",
      userId: 0,
      accountId: "guest",
      username: "guest",
      role: "guest",
      capabilities: [...GUEST_CAPABILITIES],
      isLocalAdmin: false,
    };
    return { ...this.session };
  }

  async restoreSession(): Promise<SessionState> {
    this.ensureAdminUser(this.currentAccountId(), this.session.username);
    return { ...this.session };
  }

  async logout(): Promise<void> {
    this.session = {
      currentBotAlias: "",
      currentPath: "",
      isLoggedIn: false,
      token: "",
      userId: undefined,
      accountId: "",
      username: "",
      role: "guest",
      capabilities: [],
      isLocalAdmin: false,
    };
  }

  async listAnnouncements(): Promise<AnnouncementListResult> {
    return this.buildAnnouncementList();
  }

  async markAnnouncementsSeen(latestId: string): Promise<AnnouncementListResult> {
    if (latestId && !this.announcements.some((item) => item.id === latestId)) {
      throw new WebApiClientError("公告不存在", { status: 400, code: "invalid_announcement" });
    }
    this.announcementReads.set(this.currentAccountId(), latestId);
    return this.buildAnnouncementList();
  }

  async upsertAnnouncement(input: CreateAnnouncementInput): Promise<AnnouncementItem> {
    if (!this.isLocalAdminSession()) {
      throw new WebApiClientError("无权发布公告", { status: 403, code: "forbidden" });
    }
    const normalized = this.normalizeAnnouncementInput(input);
    this.announcements = [
      normalized,
      ...this.announcements.filter((item) => item.id !== normalized.id),
    ];
    return this.cloneAnnouncement(normalized);
  }

  async deleteAnnouncement(id: string): Promise<{ deleted: boolean }> {
    if (!this.isLocalAdminSession()) {
      throw new WebApiClientError("无权删除公告", { status: 403, code: "forbidden" });
    }
    const before = this.announcements.length;
    this.announcements = this.announcements.filter((item) => item.id !== id);
    return { deleted: this.announcements.length !== before };
  }

  async listRegisterCodes(): Promise<RegisterCodeItem[]> {
    return this.registerCodes.map((item) => ({ ...item, usage: [...item.usage] }));
  }

  async createRegisterCode(maxUses = 1): Promise<RegisterCodeCreateResult> {
    const created: RegisterCodeCreateResult = {
      codeId: `invite-${Date.now()}`,
      code: `INV-${String(this.registerCodes.length + 1).padStart(3, "0")}`,
      codePreview: `INV***${String(this.registerCodes.length + 1).padStart(3, "0")}`,
      disabled: false,
      maxUses,
      usedCount: 0,
      remainingUses: maxUses,
      createdAt: new Date().toISOString(),
      createdBy: "127.0.0.1",
      lastUsedAt: "",
      usage: [],
    };
    this.registerCodes = [created, ...this.registerCodes];
    return { ...created, usage: [] };
  }

  async updateRegisterCode(codeId: string, input: { maxUsesDelta?: number; disabled?: boolean }): Promise<RegisterCodeItem> {
    const index = this.registerCodes.findIndex((item) => item.codeId === codeId);
    if (index < 0) {
      throw new WebApiClientError("邀请码不存在", { status: 404, code: "register_code_not_found" });
    }
    const current = this.registerCodes[index];
    const nextMaxUses = typeof input.maxUsesDelta === "number" ? current.maxUses + input.maxUsesDelta : current.maxUses;
    if (nextMaxUses < current.usedCount || nextMaxUses <= 0) {
      throw new WebApiClientError("使用次数无效", { status: 400, code: "invalid_register_code_max_uses" });
    }
    const updated: RegisterCodeItem = {
      ...current,
      maxUses: nextMaxUses,
      remainingUses: nextMaxUses - current.usedCount,
      disabled: typeof input.disabled === "boolean" ? input.disabled : current.disabled,
    };
    this.registerCodes[index] = updated;
    return { ...updated, usage: [...updated.usage] };
  }

  async deleteRegisterCode(codeId: string): Promise<void> {
    this.registerCodes = this.registerCodes.filter((item) => item.codeId !== codeId);
  }

  async listAdminUsers(): Promise<AdminUser[]> {
    if (!this.isLocalAdminSession()) {
      throw new WebApiClientError("无权查看用户权限", { status: 403, code: "forbidden" });
    }
    return Array.from(this.adminUsers.keys())
      .sort((left, right) => left.localeCompare(right))
      .map((accountId) => this.buildAdminUser(accountId));
  }

  async updateUser(accountId: string, input: AdminUserUpdateInput): Promise<AdminUser> {
    if (!this.isLocalAdminSession()) {
      throw new WebApiClientError("无权修改用户", { status: 403, code: "forbidden" });
    }
    const current = this.adminUsers.get(accountId);
    if (!current) {
      throw new WebApiClientError("用户不存在", { status: 404, code: "user_not_found" });
    }
    this.adminUsers.set(accountId, {
      ...current,
      disabled: typeof input.disabled === "boolean" ? input.disabled : current.disabled,
      capabilities: Array.isArray(input.capabilities) ? [...input.capabilities] : current.capabilities,
    });
    return this.buildAdminUser(accountId);
  }

  async updateUserBotPermissions(accountId: string, allowedBots: string[]): Promise<UserBotPermissions> {
    if (!this.isLocalAdminSession()) {
      throw new WebApiClientError("无权修改权限", { status: 403, code: "forbidden" });
    }
    if (!this.adminUsers.has(accountId)) {
      throw new WebApiClientError("用户不存在", { status: 404, code: "user_not_found" });
    }
    const normalized = this.normalizeAllowedBots(allowedBots);
    this.setAllowedBotsForAccount(accountId, normalized);
    return {
      accountId,
      allowedBots: [...normalized],
    };
  }

  async getEnvConfig(): Promise<EnvConfigSnapshot> {
    if (!this.hasAdminOps()) {
      throw new WebApiClientError("无权查看环境配置", { status: 403, code: "forbidden" });
    }
    return {
      envPath: ".env",
      examplePath: ".env.example",
      items: this.envItems.map(cloneEnvItem),
    };
  }

  async getNativeAgentConfig(): Promise<NativeAgentConfigPayload> {
    if (!this.hasAdminOps()) {
      throw new WebApiClientError("无权查看原生 Agent 配置", { status: 403, code: "forbidden" });
    }
    return {
      config: JSON.parse(JSON.stringify(this.nativeAgentConfig)) as Record<string, unknown>,
      opencodeConfigPath: "~/.config/opencode/opencode.json",
      backupPath: "~/.tcb/native_agent/opencode.config.backup.json",
      models: this.nativeAgentModels.map((item) => ({ ...item })),
      needsRestart: false,
    };
  }

  async updateNativeAgentConfig(config: Record<string, unknown>): Promise<NativeAgentConfigPayload> {
    if (!this.hasAdminOps()) {
      throw new WebApiClientError("无权保存原生 Agent 配置", { status: 403, code: "forbidden" });
    }
    this.nativeAgentConfig = JSON.parse(JSON.stringify(config)) as Record<string, unknown>;
    this.nativeAgentModels = this.extractNativeAgentModels(this.nativeAgentConfig);
    return {
      config: JSON.parse(JSON.stringify(this.nativeAgentConfig)) as Record<string, unknown>,
      opencodeConfigPath: "~/.config/opencode/opencode.json",
      backupPath: "~/.tcb/native_agent/opencode.config.backup.json",
      models: this.nativeAgentModels.map((item) => ({ ...item })),
      needsRestart: true,
    };
  }

  async previewEnvConfig(input: EnvConfigPatchInput): Promise<EnvConfigPatchResult> {
    if (!this.hasAdminOps()) {
      throw new WebApiClientError("无权预览环境配置", { status: 403, code: "forbidden" });
    }
    return this.buildEnvPatchResult(input, false);
  }

  async updateEnvConfig(input: EnvConfigPatchInput): Promise<EnvConfigPatchResult> {
    if (!this.hasAdminOps()) {
      throw new WebApiClientError("无权保存环境配置", { status: 403, code: "forbidden" });
    }
    return this.buildEnvPatchResult(input, true);
  }

  async listBots(): Promise<BotSummary[]> {
    return Array.from(this.bots.values()).map((item) => this.getBotSummary(item.alias));
  }

  async listPlugins(_refresh = false): Promise<PluginSummary[]> {
    return this.plugins.map((plugin) => this.clonePluginSummary(plugin));
  }

  async listInstallablePlugins(): Promise<InstallablePluginSummary[]> {
    return this.installablePlugins.map((plugin) => this.cloneInstallablePlugin(plugin));
  }

  async installPlugin(input: string | {
    pluginId?: string;
    sourcePath?: string;
    force?: boolean;
    allowDevSourcePath?: boolean;
  }): Promise<PluginSummary> {
    const pluginId = typeof input === "string" ? input : (input.pluginId || "").trim();
    const sourcePath = typeof input === "string" ? "" : (input.sourcePath || "").trim();
    const force = typeof input === "string" ? false : Boolean(input.force);
    const sourceTail = sourcePath ? this.getPathTail(sourcePath) : "";
    const index = this.installablePlugins.findIndex((plugin) =>
      plugin.id === pluginId
      || plugin.pluginId === pluginId
      || (sourceTail && (plugin.id === sourceTail || plugin.pluginId === sourceTail)),
    );

    let installed: PluginSummary;
    if (index >= 0) {
      const current = this.installablePlugins[index];
      if (current.installed && !force) {
        throw new WebApiClientError("插件已安装", { status: 409, code: "plugin_already_installed" });
      }
      installed = this.buildInstalledPluginFromInstallable({ ...current, installed: true });
      this.installablePlugins[index] = { ...current, installed: true };
    } else if (pluginId && force) {
      const existing = this.plugins.find((plugin) => plugin.id === pluginId);
      if (!existing) {
        throw new WebApiClientError("插件不存在", { status: 404, code: "plugin_not_found" });
      }
      installed = this.clonePluginSummary(existing);
    } else if (sourcePath) {
      installed = this.buildInstalledPluginFromSourcePath(sourcePath);
    } else {
      throw new WebApiClientError("插件不存在", { status: 404, code: "plugin_not_found" });
    }

    const existingIndex = this.plugins.findIndex((plugin) => plugin.id === installed.id);
    if (existingIndex >= 0 && !force) {
      throw new WebApiClientError("插件已安装", { status: 409, code: "plugin_already_installed" });
    }
    if (existingIndex >= 0) {
      this.plugins = this.plugins.map((plugin, itemIndex) => (itemIndex === existingIndex ? installed : plugin));
    } else {
      this.plugins = [...this.plugins, installed];
    }
    return this.clonePluginSummary(installed);
  }

  async uninstallPlugin(pluginId: string): Promise<void> {
    const existing = this.plugins.find((plugin) => plugin.id === pluginId);
    if (!existing) {
      throw new WebApiClientError("插件不存在", { status: 404, code: "plugin_not_found" });
    }
    this.plugins = this.plugins.filter((plugin) => plugin.id !== pluginId);
    this.installablePlugins = this.installablePlugins.map((plugin) => (
      plugin.id === pluginId || plugin.pluginId === pluginId
        ? { ...plugin, installed: false }
        : plugin
    ));
  }

  async updatePlugin(pluginId: string, input: PluginUpdateInput): Promise<PluginSummary> {
    const index = this.plugins.findIndex((plugin) => plugin.id === pluginId);
    if (index < 0) {
      throw new WebApiClientError("插件不存在", { status: 404, code: "plugin_not_found" });
    }
    const current = this.plugins[index];
    const updated: PluginSummary = {
      ...current,
      enabled: typeof input.enabled === "boolean" ? input.enabled : current.enabled,
      config: input.config ? { ...(current.config || {}), ...input.config } : { ...(current.config || {}) },
      views: current.views.map((view) => ({ ...view })),
      fileHandlers: current.fileHandlers.map((handler) => ({ ...handler, extensions: [...handler.extensions] })),
      configSchema: current.configSchema,
      catalogActions: clonePluginActions(current.catalogActions),
      runtime: current.runtime
        ? {
            ...current.runtime,
            permissions: current.runtime.permissions ? { ...current.runtime.permissions } : undefined,
          }
        : undefined,
    };
    this.plugins[index] = updated;
    return this.clonePluginSummary(updated);
  }

  async listAgents(botAlias: string): Promise<AgentListResult> {
    this.getBotSummary(botAlias);
    return { items: this.ensureAgents(botAlias).map((agent) => this.cloneAgent(agent)) };
  }

  async createAgent(botAlias: string, input: AgentInput): Promise<AgentMutationResult> {
    const bot = this.getBotSummary(botAlias);
    if ((bot.botMode || "cli") !== "cli") {
      throw new WebApiClientError("仅 CLI Bot 支持子 agent", { status: 400, code: "agent_not_supported" });
    }
    const id = (input.id || "").trim().toLowerCase();
    const name = (input.name || "").trim();
    if (!id || id === "main" || !/^[a-z][a-z0-9_-]{1,31}$/.test(id)) {
      throw new WebApiClientError("agent id 无效", { status: 400, code: "invalid_agent" });
    }
    if (!name) {
      throw new WebApiClientError("agent 名称不能为空", { status: 400, code: "invalid_agent" });
    }
    const agents = this.ensureAgents(botAlias);
    if (agents.some((agent) => agent.id === id)) {
      throw new WebApiClientError("agent id 已存在", { status: 400, code: "invalid_agent" });
    }
    const now = new Date().toISOString();
    const agent: AgentSummary = {
      id,
      name,
      systemPrompt: input.systemPrompt || "",
      enabled: input.enabled !== false,
      isMain: false,
      createdAt: now,
      updatedAt: now,
      cluster: {
        ...DEFAULT_AGENT_CLUSTER,
        ...(input.cluster || {}),
      },
    };
    this.agentsByBot.set(botAlias, [...agents, agent]);
    return { agent: this.cloneAgent(agent) };
  }

  async updateAgent(botAlias: string, agentId: string, input: AgentInput): Promise<AgentMutationResult> {
    const agents = this.ensureAgents(botAlias);
    const id = agentId.trim().toLowerCase();
    if (id === "main") {
      throw new WebApiClientError("主 agent 不支持编辑", { status: 400, code: "invalid_agent" });
    }
    const index = agents.findIndex((agent) => agent.id === id);
    if (index < 0) {
      throw new WebApiClientError("未找到 agent", { status: 404, code: "agent_not_found" });
    }
    const current = agents[index];
    const updated: AgentSummary = {
      ...current,
      name: typeof input.name === "string" ? input.name.trim() : current.name,
      systemPrompt: typeof input.systemPrompt === "string" ? input.systemPrompt : current.systemPrompt,
      enabled: typeof input.enabled === "boolean" ? input.enabled : current.enabled,
      cluster: input.cluster ? { ...(current.cluster || DEFAULT_AGENT_CLUSTER), ...input.cluster } : current.cluster,
      updatedAt: new Date().toISOString(),
    };
    const next = [...agents];
    next[index] = updated;
    this.agentsByBot.set(botAlias, next);
    return { agent: this.cloneAgent(updated) };
  }

  async deleteAgent(botAlias: string, agentId: string): Promise<void> {
    const id = agentId.trim().toLowerCase();
    if (id === "main") {
      throw new WebApiClientError("主 agent 不能删除", { status: 400, code: "invalid_agent" });
    }
    const agents = this.ensureAgents(botAlias);
    if (!agents.some((agent) => agent.id === id)) {
      throw new WebApiClientError("未找到 agent", { status: 404, code: "agent_not_found" });
    }
    this.agentsByBot.set(botAlias, agents.filter((agent) => agent.id !== id));
  }

  setClusterStatus(botAlias: string, input: Partial<ClusterStatus>): void {
    const current = this.getBotSummary(botAlias);
    this.bots.set(botAlias, {
      ...current,
      cluster: {
        ...(current.cluster || DEFAULT_CLUSTER),
        enabled: typeof input.enabled === "boolean" ? input.enabled : current.cluster?.enabled ?? false,
        modelTiers: input.modelTiers
          ? { ...input.modelTiers }
          : { ...(current.cluster?.modelTiers || DEFAULT_CLUSTER.modelTiers) },
      },
    });
  }

  async getClusterStatus(botAlias: string): Promise<ClusterStatus> {
    const bot = this.getBotSummary(botAlias);
    const cluster = bot.cluster || DEFAULT_CLUSTER;
    return {
      enabled: Boolean(cluster.enabled),
      modelTiers: { ...cluster.modelTiers },
      mcp: {
        serverName: "tcb-cluster",
        activeCliType: bot.cliType,
        runtime: { state: "runtime_ready", message: "运行态可用" },
        codex: bot.cliType === "codex" ? { state: "runtime_ready", message: "运行态可用" } : { state: "not_checked", message: "未使用" },
        claude: bot.cliType === "claude" ? { state: "runtime_ready", message: "运行态可用" } : { state: "not_checked", message: "未使用" },
        kimi: bot.cliType === "kimi" ? { state: "runtime_ready", message: "运行态可用" } : { state: "not_checked", message: "未使用" },
      },
      agents: this.ensureAgents(botAlias)
        .filter((agent) => !agent.isMain)
        .map((agent) => ({
          id: agent.id,
          name: agent.name,
          enabled: agent.enabled,
          allowCluster: agent.cluster?.allowCluster !== false,
          allowWrite: Boolean(agent.cluster?.allowWrite),
          sessionPolicy: agent.cluster?.sessionPolicy || "persistent",
          timeoutSeconds: agent.cluster?.timeoutSeconds || 600,
        })),
    };
  }

  async getClusterTaskStatus(_botAlias: string, _runId: string): Promise<ClusterTaskStatus> {
    return {
      tasks: [],
      queuedCount: 0,
      runningCount: 0,
      completedCount: 0,
      failedCount: 0,
      pendingCount: 0,
    };
  }

  async prepareClusterSetup(botAlias: string): Promise<ClusterSetupPrepareResult> {
    const cliPath = this.getBotSummary(botAlias).cliPath || defaultCliPathForType(this.getBotSummary(botAlias).cliType);
    const cliType = this.getBotSummary(botAlias).cliType;
    return {
      serverName: "tcb-cluster",
      launcherPath: "C:\\Users\\demo\\.tcb\\bin\\tcb-cluster-mcp.cmd",
      configPath: "C:\\Users\\demo\\.tcb\\cluster-mcp\\config.json",
      tokenPath: "C:\\Users\\demo\\.tcb\\cluster-mcp\\token",
      installCommand: cliType === "kimi"
        ? [cliPath, "mcp", "add", "--transport", "stdio", "tcb-cluster", "--", "C:\\Users\\demo\\.tcb\\bin\\tcb-cluster-mcp.cmd"]
        : [cliPath, "mcp", "add", "tcb-cluster", "--", "C:\\Users\\demo\\.tcb\\bin\\tcb-cluster-mcp.cmd"],
      verifyCommand: cliType === "kimi"
        ? [cliPath, "mcp", "test", "tcb-cluster"]
        : [cliPath, "mcp", "get", "tcb-cluster"],
      removeCommand: [cliPath, "mcp", "remove", "tcb-cluster"],
    };
  }

  async updateClusterConfig(botAlias: string, input: ClusterConfigUpdateInput): Promise<ClusterConfigUpdateResult> {
    const current = this.getBotSummary(botAlias);
    const cluster = {
      ...(current.cluster || DEFAULT_CLUSTER),
      ...(typeof input.enabled === "boolean" ? { enabled: input.enabled } : {}),
      ...(input.writePolicy ? { writePolicy: input.writePolicy } : {}),
      ...(input.conflictPolicy ? { conflictPolicy: input.conflictPolicy } : {}),
      ...(typeof input.maxParallelAgents === "number" ? { maxParallelAgents: input.maxParallelAgents } : {}),
      ...(typeof input.defaultTimeoutSeconds === "number" ? { defaultTimeoutSeconds: input.defaultTimeoutSeconds } : {}),
      modelTiers: input.modelTiers
        ? { ...input.modelTiers }
        : { ...(current.cluster?.modelTiers || DEFAULT_CLUSTER.modelTiers) },
    };
    this.bots.set(botAlias, { ...current, cluster });
    return { cluster, status: await this.getClusterStatus(botAlias) };
  }

  async getClusterTemplates(_botAlias: string): Promise<ClusterTemplateListResult> {
    return { templates: listMockClusterTemplateSummaries() };
  }

  async getClusterBundleSchema(_botAlias: string): Promise<ClusterBundleSchemaResult> {
    return {
      version: 1,
      schema: {
        type: "object",
        required: ["cluster", "agents"],
        properties: {
          id: { type: "string", pattern: "^[a-z][a-z0-9_-]{1,31}$" },
          agents: { type: "array", maxItems: 8 },
        },
      },
      instructions: "只输出 JSON bundle。默认所有 agent 只读。只有用户明确要求并行写代码时，才设置某个 agent 的 cluster.allow_write=true。",
    };
  }

  async previewClusterTemplate(_botAlias: string, templateId: string): Promise<ClusterBundlePreviewResult> {
    const bundle = this.findTemplate(templateId);
    return { bundle, diff: this.buildBundleDiff(bundle) };
  }

  async applyClusterTemplate(botAlias: string, templateId: string, confirmOverwriteAgents: boolean): Promise<ClusterBundleApplyResult> {
    if (!confirmOverwriteAgents) {
      throw new WebApiClientError("应用模板会覆盖当前子 agent 配置，请确认后重试", { status: 409, code: "cluster_bundle_overwrite_not_confirmed" });
    }
    const bundle = this.findTemplate(templateId);
    return this.applyBundle(botAlias, bundle);
  }

  async previewClusterConfigBundle(botAlias: string, bundle: unknown): Promise<ClusterBundlePreviewResult> {
    const normalized = this.coerceBundle(bundle);
    const diff = this.buildBundleDiff(normalized, botAlias);
    return { bundle: normalized, diff };
  }

  async applyClusterConfigBundle(botAlias: string, bundle: unknown, confirmOverwriteAgents: boolean): Promise<ClusterBundleApplyResult> {
    if (!confirmOverwriteAgents) {
      throw new WebApiClientError("应用配置会覆盖当前子 agent 配置，请确认后重试", { status: 409, code: "cluster_bundle_overwrite_not_confirmed" });
    }
    return this.applyBundle(botAlias, this.coerceBundle(bundle));
  }

  async getBotOverview(botAlias: string, options: AgentScopedOptions = {}): Promise<BotOverview> {
    const bot = this.getBotSummary(botAlias);
    const agentId = options.agentId || "main";
    const messages = this.getAgentMessages(bot.alias, agentId);
    return {
      ...bot,
      botMode: bot.botMode || "cli",
      cliPath: bot.cliPath,
      enabled: bot.enabled,
      isMain: bot.isMain,
      messageCount: messages.length,
      historyCount: messages.length,
      isProcessing: false,
      assistantRuntime: this.buildAssistantRuntime(botAlias),
      agents: this.ensureAgents(botAlias).map((agent) => this.cloneAgent(agent)),
      activeAgentId: agentId,
      busyAgentIds: [],
      executionMode: options.executionMode || bot.executionMode || bot.defaultExecutionMode || "cli",
      globalPromptPresets: clonePromptPresets(this.globalPromptPresets),
    };
  }

  private findTemplate(templateId: string): ClusterConfigBundle {
    const found = findMockClusterTemplate(templateId);
    if (!found) {
      throw new WebApiClientError("集群模板不存在", { status: 404, code: "cluster_template_not_found" });
    }
    return found;
  }

  private coerceBundle(raw: unknown): ClusterConfigBundle {
    const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
    return {
      id: String(value.id || "custom_review"),
      name: String(value.name || "自定义集群"),
      description: String(value.description || ""),
      cluster: {
        ...(DEFAULT_CLUSTER),
        ...(value.cluster && typeof value.cluster === "object" ? value.cluster as typeof DEFAULT_CLUSTER : {}),
      },
      agents: Array.isArray(value.agents)
        ? value.agents.map((agent) => {
            const item = agent && typeof agent === "object" ? agent as Record<string, unknown> : {};
            return {
              id: String(item.id || ""),
              name: String(item.name || ""),
              systemPrompt: String(item.system_prompt ?? item.systemPrompt ?? ""),
              enabled: item.enabled !== false,
              cluster: {
                ...DEFAULT_AGENT_CLUSTER,
                ...(item.cluster && typeof item.cluster === "object" ? item.cluster as typeof DEFAULT_AGENT_CLUSTER : {}),
              },
            };
          })
        : [],
    };
  }

  private buildBundleDiff(bundle: ClusterConfigBundle, botAlias = "main") {
    const current = this.ensureAgents(botAlias).filter((agent) => !agent.isMain);
    const currentMap = new Map(current.map((agent) => [agent.id, agent]));
    const nextMap = new Map(bundle.agents.map((agent) => [agent.id, agent]));
    const deleteAgents = current.filter((agent) => !nextMap.has(agent.id)).map((agent) => agent.id).sort();
    const createAgents = bundle.agents.filter((agent) => !currentMap.has(agent.id)).map((agent) => agent.id).sort();
    const updateAgents = bundle.agents
      .filter((agent) => {
        const prev = currentMap.get(agent.id);
        return prev && JSON.stringify({
          id: prev.id,
          name: prev.name,
          systemPrompt: prev.systemPrompt,
          enabled: prev.enabled,
          cluster: prev.cluster,
        }) !== JSON.stringify(agent);
      })
      .map((agent) => agent.id)
      .sort();
    return {
      deleteAgents,
      createAgents,
      updateAgents,
      clusterChanges: {},
      overwritesAgents: deleteAgents.length > 0 || createAgents.length > 0 || updateAgents.length > 0,
    };
  }

  private async applyBundle(botAlias: string, bundle: ClusterConfigBundle): Promise<ClusterBundleApplyResult> {
    const current = this.getBotSummary(botAlias);
    const nextAgents: AgentSummary[] = bundle.agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      systemPrompt: agent.systemPrompt,
      enabled: agent.enabled,
      isMain: false,
      cluster: { ...agent.cluster },
      createdAt: "",
      updatedAt: "",
    }));
    this.agentsByBot.set(botAlias, [
      { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true, cluster: { ...DEFAULT_AGENT_CLUSTER } },
      ...nextAgents,
    ]);
    this.bots.set(botAlias, {
      ...current,
      cluster: { ...bundle.cluster },
      agents: this.ensureAgents(botAlias).map((item) => this.cloneAgent(item)),
    });
    return {
      cluster: { ...bundle.cluster },
      agents: nextAgents.map((item) => this.cloneAgent(item)),
      bundle: structuredClone(bundle),
      diff: this.buildBundleDiff(bundle, botAlias),
      status: await this.getClusterStatus(botAlias),
    };
  }

  private ensureConversations(botAlias: string, agentId = "main"): ConversationSummary[] {
    const key = this.getConversationKey(botAlias, agentId);
    const existing = this.conversationsByBot.get(key);
    if (existing) {
      return existing;
    }
    const messages = this.getAgentMessages(botAlias, agentId);
    const now = new Date().toISOString();
    const conversation: ConversationSummary = {
      id: `mock-conv-${key}`,
      title: messages.find((item) => item.role === "user")?.text.slice(0, 32) || "当前会话",
      lastMessagePreview: [...messages].reverse().find((item) => item.text.trim())?.text || "",
      messageCount: messages.length,
      pinned: false,
      active: true,
      status: "active",
      botAlias,
      agentId,
      botMode: this.getBotSummary(botAlias).botMode || "cli",
      cliType: this.getBotSummary(botAlias).cliType,
      workingDir: this.getBotSummary(botAlias).workingDir,
      createdAt: messages[0]?.createdAt || now,
      updatedAt: messages[messages.length - 1]?.createdAt || now,
    };
    const items = [conversation];
    this.conversationsByBot.set(key, items);
    this.activeConversationByBot.set(key, conversation.id);
    return items;
  }

  async listConversations(botAlias: string, _query = "", options: AgentScopedOptions = {}): Promise<ConversationListResult> {
    const agentId = options.agentId || "main";
    const key = this.getConversationKey(botAlias, agentId);
    const items = this.ensureConversations(botAlias, agentId);
    const activeConversationId = this.activeConversationByBot.get(key) || items.find((item) => item.active)?.id || "";
    return { items, activeConversationId };
  }

  async createConversation(botAlias: string, title = "", options: AgentScopedOptions = {}): Promise<ConversationSelectResult> {
    const agentId = options.agentId || "main";
    const key = this.getConversationKey(botAlias, agentId);
    const now = new Date().toISOString();
    const bot = this.getBotSummary(botAlias);
    const conversation: ConversationSummary = {
      id: `mock-conv-${Date.now()}`,
      title: title.trim() || "新会话",
      lastMessagePreview: "",
      messageCount: 0,
      pinned: false,
      active: true,
      status: "active",
      botAlias,
      agentId,
      botMode: bot.botMode || "cli",
      cliType: bot.cliType,
      workingDir: bot.workingDir,
      createdAt: now,
      updatedAt: now,
    };
    const previous = this.ensureConversations(botAlias, agentId).map((item) => ({ ...item, active: false }));
    this.conversationsByBot.set(key, [conversation, ...previous]);
    this.activeConversationByBot.set(key, conversation.id);
    if (agentId === "main") {
      mockChatMessages[botAlias] = [];
    } else {
      mockChatMessages[this.agentKey(botAlias, agentId)] = [];
    }
    return { conversation, messages: [] };
  }

  async executePlan(botAlias: string, input: PlanExecuteInput): Promise<PlanExecuteResult> {
    const conversationResult = await this.createConversation(botAlias, input.title || "执行方案", {
      agentId: input.agentId,
    });
    const planPath = MOCK_PLAN_PATH;
    return {
      planPath,
      conversation: conversationResult.conversation,
      messages: conversationResult.messages,
      executionMessage: buildMockPlanExecutionMessage(planPath),
    };
  }

  async selectConversation(botAlias: string, conversationId: string, options: AgentScopedOptions = {}): Promise<ConversationSelectResult> {
    const agentId = options.agentId || "main";
    const key = this.getConversationKey(botAlias, agentId);
    const items = this.ensureConversations(botAlias, agentId).map((item) => ({
      ...item,
      active: item.id === conversationId,
    }));
    const conversation = items.find((item) => item.id === conversationId);
    if (!conversation) {
      throw new WebApiClientError("未找到会话", { status: 404, code: "conversation_not_found" });
    }
    this.conversationsByBot.set(key, items);
    this.activeConversationByBot.set(key, conversationId);
    return { conversation, messages: this.getAgentMessages(botAlias, agentId) };
  }

  async deleteConversation(
    botAlias: string,
    conversationId: string,
    options: AgentScopedOptions & { deleteNativeSession?: boolean } = {},
  ): Promise<ConversationDeleteResult> {
    const agentId = options.agentId || "main";
    const key = this.getConversationKey(botAlias, agentId);
    const items = this.ensureConversations(botAlias, agentId);
    const activeConversationId = this.activeConversationByBot.get(key) || "";
    const conversation = items.find((item) => item.id === conversationId);
    if (!conversation) {
      throw new WebApiClientError("未找到会话", { status: 404, code: "conversation_not_found" });
    }
    const wasActive = activeConversationId === conversationId || conversation.active;
    const nextItems = items.filter((item) => item.id !== conversationId);
    this.conversationsByBot.set(key, nextItems);
    if (wasActive) {
      this.activeConversationByBot.set(key, "");
      if (agentId === "main") {
        mockChatMessages[botAlias] = [];
      } else {
        mockChatMessages[this.agentKey(botAlias, agentId)] = [];
      }
    }
    return {
      deletedConversationId: conversationId,
      activeConversationId: this.activeConversationByBot.get(key) || "",
      nativeSessionCleared: Boolean(options.deleteNativeSession),
      items: nextItems,
      ...(wasActive ? { messages: [] } : {}),
    };
  }

  async deleteAllConversations(
    botAlias: string,
    options: AgentScopedOptions & { deleteNativeSession?: boolean } = {},
  ): Promise<ConversationBulkDeleteResult> {
    const agentId = options.agentId || "main";
    const key = this.getConversationKey(botAlias, agentId);
    const items = this.ensureConversations(botAlias, agentId);
    const deletedCount = items.length;
    this.conversationsByBot.set(key, []);
    this.activeConversationByBot.set(key, "");
    if (agentId === "main") {
      mockChatMessages[botAlias] = [];
    } else {
      mockChatMessages[this.agentKey(botAlias, agentId)] = [];
    }
    return {
      deletedCount,
      activeConversationId: "",
      nativeSessionCleared: Boolean(options.deleteNativeSession),
      items: [],
      messages: [],
    };
  }

  async listMessages(botAlias: string, options: AgentScopedOptions = {}): Promise<ChatMessage[]> {
    return this.getAgentMessages(botAlias, options.agentId || "main");
  }

  async listMessageDelta(botAlias: string, afterId: string, limit = 50, options: AgentScopedOptions = {}): Promise<HistoryDeltaResult> {
    const messages = this.getAgentMessages(botAlias, options.agentId || "main");
    if (!afterId) {
      return { items: messages.slice(-limit), reset: false };
    }
    const index = messages.findIndex((message) => message.id === afterId);
    if (index < 0) {
      return { items: messages.slice(-limit), reset: true };
    }
    return { items: messages.slice(index + 1, index + 1 + limit), reset: false };
  }

  async getMessageTrace(_botAlias: string, _messageId: string): Promise<ChatTraceDetails> {
    return {
      traceCount: 0,
      toolCallCount: 0,
      processCount: 0,
      trace: [],
    };
  }

  async getDebugProfile(_botAlias: string): Promise<DebugProfile | null> {
    return {
      specVersion: 3,
      providerId: "cpp-gdb",
      providerLabel: "C++ GDB",
      language: "cpp",
      configName: "(gdb) Remote Debug",
      target: {
        program: "H:\\Resources\\RTLinux\\Demos\\MB_DDF\\build\\aarch64\\Debug\\MB_DDF",
        cwd: "H:\\Resources\\RTLinux\\Demos\\MB_DDF",
      },
      capabilities: {
        continue: true,
        pause: true,
        next: true,
        stepIn: true,
        stepOut: true,
        variables: true,
        evaluate: true,
      },
      launchSchema: {
        fields: [
          { key: "prepareCommand", label: "准备命令", type: "string" },
          { key: "remoteHost", label: "host", type: "string" },
          { key: "remoteUser", label: "user", type: "string" },
          { key: "remoteDir", label: "remoteDir", type: "string" },
          { key: "remotePort", label: "port", type: "number" },
          { key: "password", label: "password", type: "string", secret: true },
          { key: "stopAtEntry", label: "入口暂停", type: "boolean" },
        ],
      },
      launchDefaults: {
        prepareCommand: ".\\debug.bat",
        remoteHost: "192.168.1.29",
        remoteUser: "root",
        remoteDir: "/home/sast8/tmp",
        remotePort: 1234,
        stopAtEntry: true,
      },
      program: "H:\\Resources\\RTLinux\\Demos\\MB_DDF\\build\\aarch64\\Debug\\MB_DDF",
      cwd: "H:\\Resources\\RTLinux\\Demos\\MB_DDF",
      miDebuggerPath: "D:\\Toolchain\\aarch64-none-linux-gnu-gdb.exe",
      compileCommands: "H:\\Resources\\RTLinux\\Demos\\MB_DDF\\.vscode\\compile_commands.json",
      prepareCommand: ".\\debug.bat",
      stopAtEntry: true,
      setupCommands: [
        "-enable-pretty-printing",
        "set print thread-events off",
        "set pagination off",
        "set sysroot H:/Resources/RTLinux/Demos/MB_DDF/build/aarch64/sysroot",
      ],
      remoteHost: "192.168.1.29",
      remoteUser: "root",
      remoteDir: "/home/sast8/tmp",
      remotePort: 1234,
      providerConfig: {
        gdb: {
          path: "D:\\Toolchain\\aarch64-none-linux-gnu-gdb.exe",
        },
      },
    };
  }

  async getDebugState(_botAlias: string): Promise<DebugState> {
    return {
      phase: "idle",
      detailPhase: "",
      message: "",
      breakpoints: [],
      frames: [],
      currentFrameId: "",
      scopes: [],
      variables: {},
    };
  }

  async getTerminalSession(_ownerId: string): Promise<PersistentTerminalSnapshot> {
    return readMockPersistentTerminalSnapshot();
  }

  async rebuildTerminalSession(_ownerId: string, cwd: string, _shell = "auto"): Promise<PersistentTerminalSnapshot> {
    const snapshot: PersistentTerminalSnapshot = {
      started: true,
      closed: false,
      cwd,
      ptyMode: true,
      connectionText: "运行中",
      lastSeq: 0,
    };
    writeMockPersistentTerminalSnapshot(snapshot);
    return snapshot;
  }

  async closeTerminalSession(_ownerId: string): Promise<PersistentTerminalSnapshot> {
    const current = readMockPersistentTerminalSnapshot();
    const snapshot: PersistentTerminalSnapshot = {
      ...current,
      started: false,
      closed: true,
      connectionText: "终端已关闭",
    };
    writeMockPersistentTerminalSnapshot(snapshot);
    return snapshot;
  }

  async getTerminalActionsConfig(_botAlias: string): Promise<TerminalActionsConfig> {
    return {
      ...this.terminalActionsConfig,
      actions: this.terminalActionsConfig.actions.map((action) => ({ ...action })),
      errors: [...this.terminalActionsConfig.errors],
    };
  }

  async saveTerminalActionsConfig(
    _botAlias: string,
    config: TerminalActionsEditableConfig,
    _expectedMtimeNs: string,
  ): Promise<TerminalActionsConfig> {
    this.terminalActionsConfig = {
      ...this.terminalActionsConfig,
      ...config,
      exists: true,
      mtimeNs: String(Number(this.terminalActionsConfig.mtimeNs || "0") + 1),
      actions: config.actions.map((action) => ({ ...action })),
      errors: [],
    };
    return this.getTerminalActionsConfig(_botAlias);
  }

  async runTerminalAction(
    _botAlias: string,
    actionId: string,
    _input: TerminalActionRunInput,
  ): Promise<TerminalActionRunResult> {
    const action = this.terminalActionsConfig.actions.find((item) => item.id === actionId);
    if (!action) {
      throw new Error("快捷命令不存在");
    }
    const current = readMockPersistentTerminalSnapshot();
    const snapshot: PersistentTerminalSnapshot = {
      ...current,
      started: true,
      closed: false,
      cwd: current.cwd || DEMO_MAIN_WORKDIR,
      ptyMode: current.ptyMode ?? true,
      connectionText: "运行中",
    };
    writeMockPersistentTerminalSnapshot(snapshot);
    const command = resolveMockTerminalActionCommand(action, this.terminalActionsConfig.runtimePlatform);
    return {
      actionId,
      command,
      cwd: snapshot.cwd,
      startedTerminal: !current.started,
      snapshot,
    };
  }

  async sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
    onTrace?: (trace: ChatTraceEvent) => void,
    options?: ChatSendOptions,
    onAgUiEvent?: (event: AgUiEvent) => void,
  ): Promise<ChatMessage> {
    const agentId = options?.agentId || "main";
    const createdAt = new Date().toISOString();
    const userText = options?.visibleText || text;
    this.appendAgentChatMessage(botAlias, agentId, {
      id: `user-${Date.now()}`,
      role: "user",
      text: userText,
      createdAt,
      state: "done",
    });

    if (options?.taskMode === "proposal_patch") {
      onStatus?.({ elapsedSeconds: 1, previewText: "开始生成 patch" });
      onTrace?.({
        kind: "tool_call",
        summary: "git worktree add",
        toolName: "git",
        callId: "call_git_worktree_add",
      });
      onAgUiEvent?.({
        type: EventType.RUN_STARTED,
        threadId: "mock-thread",
        runId: "mock-run",
      });
      onAgUiEvent?.({
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "mock-message",
        activityType: "TCB_STATUS",
        replace: true,
        content: {
          elapsedSeconds: 1,
          previewText: "开始生成 patch",
        },
      });
      onAgUiEvent?.({
        type: EventType.TOOL_CALL_START,
        toolCallId: "call_git_worktree_add",
        toolCallName: "git",
      });
      const proposalId = String(options.taskPayload?.proposalId || options.taskPayload?.proposal_id || "").trim();
      const targetAlias = String(options.taskPayload?.targetAlias || options.taskPayload?.target_alias || "").trim();
      const metadata = await this.generateAssistantProposalPatch(botAlias, proposalId, {
        targetAlias,
        regenerate: Boolean(options.taskPayload?.regenerate),
      });
      const summary = [
        "patch 已生成",
        `目标工程: ${metadata.targetAlias}`,
        `变更文件: ${metadata.changedFiles.length}`,
      ].join("\n");
      this.assistantProposalPatchMetadata.set(this.assistantProposalKey(botAlias, proposalId), {
        ...metadata,
        chatConclusion: summary,
      } as AssistantPatchMetadata);
      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        text: summary,
        createdAt: new Date().toISOString(),
        elapsedSeconds: 1,
        state: "done",
        meta: {
          traceCount: 1,
          toolCallCount: 1,
          processCount: 0,
          trace: [{
            kind: "tool_call",
            summary: "git worktree add",
            toolName: "git",
            callId: "call_git_worktree_add",
          }],
        },
      };
      onAgUiEvent?.({
        type: EventType.TOOL_CALL_RESULT,
        messageId: assistantMessage.id,
        toolCallId: "call_git_worktree_add",
        content: summary,
      });
      onAgUiEvent?.({
        type: EventType.RUN_FINISHED,
        threadId: "mock-thread",
        runId: "mock-run",
        outcome: { type: "success" },
      });
      this.appendAgentChatMessage(botAlias, agentId, assistantMessage);
      return assistantMessage;
    }

    if (options?.taskMode === "plan") {
      const summary = [
        "<PLAN_DRAFT>",
        "# 执行方案",
        "",
        "## 目标",
        `- 处理：${text.trim() || "当前任务"}`,
        "",
        "## 步骤",
        "- 梳理相关代码和状态",
        "- 实施最小改动",
        "- 跑必要验证",
        "</PLAN_DRAFT>",
      ].join("\n");
      onChunk(summary);
      onStatus?.({ elapsedSeconds: 1 });
      onAgUiEvent?.({
        type: EventType.RUN_STARTED,
        threadId: "mock-thread",
        runId: "mock-run",
      });
      onAgUiEvent?.({
        type: EventType.TEXT_MESSAGE_START,
        messageId: "mock-message",
        role: "assistant",
      });
      onAgUiEvent?.({
        type: EventType.TEXT_MESSAGE_CONTENT,
        messageId: "mock-message",
        delta: summary,
      });
      onAgUiEvent?.({
        type: EventType.TEXT_MESSAGE_END,
        messageId: "mock-message",
      });
      onAgUiEvent?.({
        type: EventType.RUN_FINISHED,
        threadId: "mock-thread",
        runId: "mock-run",
        outcome: { type: "success" },
      });
      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        text: summary,
        createdAt: new Date().toISOString(),
        elapsedSeconds: 1,
        state: "done",
      };
      this.appendAgentChatMessage(botAlias, agentId, assistantMessage);
      return assistantMessage;
    }

    let streamed = "";
    onAgUiEvent?.({
      type: EventType.RUN_STARTED,
      threadId: "mock-thread",
      runId: "mock-run",
    });
    onAgUiEvent?.({
      type: EventType.TEXT_MESSAGE_START,
      messageId: "mock-message",
      role: "assistant",
    });
    await streamAssistantReply((chunk) => {
      streamed += chunk;
      onChunk(chunk);
      onStatus?.({
        elapsedSeconds: streamed.length > 0 ? 1 : 0,
      });
      onAgUiEvent?.({
        type: EventType.TEXT_MESSAGE_CONTENT,
        messageId: "mock-message",
        delta: chunk,
      });
    });
    onAgUiEvent?.({
      type: EventType.TEXT_MESSAGE_END,
      messageId: "mock-message",
    });
    onAgUiEvent?.({
      type: EventType.RUN_FINISHED,
      threadId: "mock-thread",
      runId: "mock-run",
      outcome: { type: "success" },
    });
    const assistantMessage = {
      id: Date.now().toString(),
      role: "assistant",
      text: streamed || "Mock response",
      createdAt: new Date().toISOString(),
      elapsedSeconds: 1,
      state: "done"
    } satisfies ChatMessage;
    this.appendAgentChatMessage(botAlias, agentId, assistantMessage);
    return assistantMessage;
  }

  async getCurrentPath(botAlias: string): Promise<string> {
    return this.getBotSummary(botAlias).workingDir;
  }

  async resolveFileOpenTarget(_botAlias: string, path: string): Promise<FileOpenTarget> {
    const lower = path.toLowerCase();
    if (lower.endsWith(".vcd")) {
      return {
        kind: "plugin_view",
        pluginId: "vivado-waveform",
        viewId: "waveform",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    if (lower.endsWith(".rpt")) {
      return {
        kind: "plugin_view",
        pluginId: "timing-report",
        viewId: "timing-table",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    if (lower.endsWith(".hier")) {
      return {
        kind: "plugin_view",
        pluginId: "rtl-hierarchy",
        viewId: "module-tree",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    if (lower.endsWith(".docx")) {
      return {
        kind: "plugin_view",
        pluginId: "docx-preview",
        viewId: "document",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    if (lower.endsWith(".pdf")) {
      return {
        kind: "plugin_view",
        pluginId: "pdf-preview",
        viewId: "document",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    if (lower.endsWith(".zip")) {
      return {
        kind: "plugin_view",
        pluginId: "zip-preview",
        viewId: "archive-tree",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    if (lower.endsWith(".bin")) {
      return {
        kind: "plugin_view",
        pluginId: "hex-preview",
        viewId: "hex",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    if (lower.endsWith(".xlsx")) {
      return {
        kind: "plugin_view",
        pluginId: "xlsx-preview",
        viewId: "document",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    return { kind: "file" };
  }

  async listFiles(botAlias: string, path?: string): Promise<DirectoryListing> {
    const currentPath = path?.trim() || this.getBrowserPath(botAlias);
    const botFiles = mockFiles[botAlias] || {};
    return {
      workingDir: currentPath,
      entries: botFiles[currentPath] || [],
    };
  }

  async openBotWorkdir(botAlias: string): Promise<BotWorkdirOpenResult> {
    return {
      opened: true,
      path: this.getBotSummary(botAlias).workingDir,
      platform: "windows",
    };
  }

  async revealFileTreePath(botAlias: string, path: string): Promise<FileTreeRevealResult> {
    const botFiles = mockFiles[botAlias] || {};
    const root = this.normalizeMockPath(this.getBrowserPath(botAlias));
    const target = this.resolveFileTreePath(botAlias, path);
    const split = this.splitMockFilePath(target);
    const targetIsDir = Object.prototype.hasOwnProperty.call(botFiles, target);
    const targetIsFile = (botFiles[split.dir] || []).some((entry) => !entry.isDir && entry.name === split.name);
    if (!targetIsDir && !targetIsFile) {
      throw new Error("文件或文件夹不存在");
    }

    const branchTarget = targetIsDir ? target : split.dir;
    const branchPaths = [""];
    const relativeBranchTarget = this.relativeMockPath(botAlias, branchTarget);
    if (relativeBranchTarget) {
      const parts = relativeBranchTarget.split("/");
      for (let index = 1; index <= parts.length; index += 1) {
        branchPaths.push(parts.slice(0, index).join("/"));
      }
    }

    const branches = Object.fromEntries(branchPaths.map((branchPath) => {
      const absolutePath = branchPath ? `${root}/${branchPath}` : root;
      return [branchPath, botFiles[this.normalizeMockPath(absolutePath)] || []];
    }));

    return {
      rootPath: root,
      highlightPath: this.relativeMockPath(botAlias, target),
      expandedPaths: branchPaths.filter(Boolean),
      branches,
    };
  }

  async changeDirectory(botAlias: string, path: string): Promise<string> {
    const currentPath = this.getBrowserPath(botAlias);
    let nextPath = currentPath;
    if (path === "..") {
      if (currentPath !== "/") {
        const parts = currentPath.split("/").filter(Boolean);
        parts.pop();
        nextPath = parts.length ? `/${parts.join("/")}` : "/";
      }
    } else if (path.startsWith("/")) {
      nextPath = path;
    } else {
      nextPath = currentPath === "/" ? `/${path}` : `${currentPath}/${path}`;
    }
    this.currentPaths.set(botAlias, nextPath);
    return nextPath;
  }

  async createDirectory(botAlias: string, name: string, parentPath?: string): Promise<void> {
    const folderName = name.trim();
    if (!folderName) {
      throw new Error("文件夹名称不能为空");
    }

    const currentPath = this.resolveTargetDir(botAlias, parentPath);
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[currentPath] || [])];
    if (currentEntries.some((entry) => entry.name === folderName)) {
      throw new Error("目标已存在");
    }

    currentEntries.push({ name: folderName, isDir: true });
    currentEntries.sort((left, right) => {
      if (left.isDir !== right.isDir) {
        return left.isDir ? -1 : 1;
      }
      return left.name.localeCompare(right.name, "zh-CN");
    });
    botFiles[currentPath] = currentEntries;

    const separator = currentPath.endsWith("/") ? "" : "/";
    const childPath = currentPath === "/" ? `/${folderName}` : `${currentPath}${separator}${folderName}`;
    botFiles[childPath] = botFiles[childPath] || [];
  }

  async createWorkdirDirectory(botAlias: string, parentPath: string, name: string): Promise<void> {
    await this.createDirectory(botAlias, name, parentPath);
  }

  async deletePath(botAlias: string, path: string): Promise<void> {
    const targetName = path.trim();
    if (!targetName) {
      throw new Error("路径不能为空");
    }

    const currentPath = this.getBrowserPath(botAlias);
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[currentPath] || [])];
    const target = currentEntries.find((entry) => entry.name === targetName);
    if (!target) {
      throw new Error("文件或文件夹不存在");
    }

    botFiles[currentPath] = currentEntries.filter((entry) => entry.name !== targetName);
    if (!target.isDir) {
      return;
    }

    const separator = currentPath.endsWith("/") ? "" : "/";
    const targetPath = currentPath === "/" ? `/${targetName}` : `${currentPath}${separator}${targetName}`;
    for (const candidate of Object.keys(botFiles)) {
      if (candidate === targetPath || candidate.startsWith(`${targetPath}/`)) {
        delete botFiles[candidate];
      }
    }
  }

  async readFile(botAlias: string, filename: string): Promise<FileReadResult> {
    const browserPath = this.getBrowserPath(botAlias);
    const content = this.getFileContent(botAlias, browserPath, filename);
    return {
      content,
      mode: "head" as const,
      fileSizeBytes: new TextEncoder().encode(content).length,
      isFullContent: true,
      lastModifiedNs: String(this.getFileVersion(botAlias, browserPath, filename)),
    };
  }

  async readFileFull(botAlias: string, filename: string): Promise<FileReadResult> {
    const browserPath = this.getBrowserPath(botAlias);
    const content = this.getFileContent(botAlias, browserPath, filename);
    return {
      content,
      mode: "cat" as const,
      fileSizeBytes: new TextEncoder().encode(content).length,
      isFullContent: true,
      lastModifiedNs: String(this.getFileVersion(botAlias, browserPath, filename)),
    };
  }

  async openPluginView(
    _botAlias: string,
    pluginId: string,
    viewId: string,
    input: Record<string, unknown>,
  ): Promise<PluginRenderResult> {
    if (pluginId === "docx-preview") {
      const sourcePath = typeof input.path === "string" ? input.path : "docs/roadmap.docx";
      return {
        pluginId,
        viewId,
        title: sourcePath.split(/[\\/]/).pop() || "roadmap.docx",
        renderer: "document",
        mode: "snapshot",
        payload: buildMockDocumentPayload(sourcePath),
      };
    }
    if (pluginId === "pdf-preview") {
      const sourcePath = typeof input.path === "string" ? input.path : "docs/roadmap.pdf";
      return {
        pluginId,
        viewId,
        title: sourcePath.split(/[\\/]/).pop() || "roadmap.pdf",
        renderer: "document",
        mode: "snapshot",
        payload: buildMockPdfDocumentPayload(sourcePath),
      };
    }
    if (pluginId === "zip-preview") {
      const sourcePath = typeof input.path === "string" ? input.path : "docs/sample.zip";
      return {
        pluginId,
        viewId,
        title: sourcePath.split(/[\\/]/).pop() || "sample.zip",
        renderer: "tree",
        mode: "snapshot",
        payload: buildMockZipTreePayload(sourcePath),
      };
    }
    if (pluginId === "hex-preview") {
      const sourcePath = typeof input.path === "string" ? input.path : "reports/firmware.bin";
      return {
        pluginId,
        viewId,
        title: sourcePath.split(/[\\/]/).pop() || "firmware.bin",
        renderer: "hex",
        mode: "snapshot",
        payload: buildMockHexPayload(sourcePath),
      };
    }
    if (pluginId === "xlsx-preview") {
      const sourcePath = typeof input.path === "string" ? input.path : "docs/roadmap.xlsx";
      return {
        pluginId,
        viewId,
        title: sourcePath.split(/[\\/]/).pop() || "roadmap.xlsx",
        renderer: "document",
        mode: "snapshot",
        payload: buildMockXlsxDocumentPayload(sourcePath),
      };
    }
    if (pluginId === "timing-report") {
      const sourcePath = typeof input.path === "string" ? input.path : "reports/timing.rpt";
      const title = sourcePath.split(/[\\/]/).pop() || "timing.rpt";
      const pageSize = Number(this.plugins.find((plugin) => plugin.id === "timing-report")?.config?.defaultPageSize || 2);
      const summary = buildMockTimingSummary(pageSize);
      const initialWindow: TableWindowPayload = {
        offset: 0,
        limit: pageSize,
        totalRows: TIMING_ROWS.length,
        rows: buildMockTimingRows(0, pageSize),
      };
      this.pluginSessionCounter += 1;
      const sessionId = `timing-session-${this.pluginSessionCounter}`;
      this.pluginSessions.set(sessionId, { pluginId, renderer: "table", summary, window: initialWindow });
      return {
        pluginId,
        viewId,
        title,
        renderer: "table",
        mode: "session",
        sessionId,
        summary,
        initialWindow,
      };
    }
    if (pluginId === "rtl-hierarchy") {
      const sourcePath = typeof input.path === "string" ? input.path : "reports/design.hier";
      const title = sourcePath.split(/[\\/]/).pop() || "design.hier";
      const summary = buildMockTreeSummary();
      const initialWindow: TreeWindowPayload = {
        op: "children",
        nodeId: null,
        nodes: cloneTreeNodes(summary.roots || []),
      };
      this.pluginSessionCounter += 1;
      const sessionId = `tree-session-${this.pluginSessionCounter}`;
      this.pluginSessions.set(sessionId, { pluginId, renderer: "tree", summary, window: initialWindow });
      return {
        pluginId,
        viewId,
        title,
        renderer: "tree",
        mode: "session",
        sessionId,
        summary,
        initialWindow,
      };
    }
    if (pluginId === "repo-outline") {
      const rootPath = typeof input.path === "string" ? input.path : "";
      const summary = buildRepoOutlineSummary(rootPath);
      const initialWindow: TreeWindowPayload = {
        op: "children",
        nodeId: null,
        nodes: cloneTreeNodes(summary.roots || []),
        statsText: summary.statsText,
      };
      this.pluginSessionCounter += 1;
      const sessionId = `repo-tree-session-${this.pluginSessionCounter}`;
      this.pluginSessions.set(sessionId, { pluginId, renderer: "tree", summary, window: initialWindow, rootPath });
      return {
        pluginId,
        viewId,
        title: "文件夹大纲",
        renderer: "tree",
        mode: "session",
        sessionId,
        summary,
        initialWindow,
      };
    }

    const sourcePath = typeof input.path === "string" ? input.path : "waves/simple_counter.vcd";
    const title = sourcePath.split(/[\\/]/).pop() || "simple_counter.vcd";
    const summary = buildMockWaveformSummary(sourcePath);
    const window: WaveformWindowPayload = {
      startTime: summary.startTime,
      endTime: summary.endTime,
      tracks: buildMockWaveformTracks(),
    };
    this.pluginSessionCounter += 1;
    const sessionId = `session-${this.pluginSessionCounter}`;
    this.pluginSessions.set(sessionId, { pluginId, renderer: "waveform", summary, window });
    return {
      pluginId,
      viewId,
      title,
      renderer: "waveform",
      mode: "session",
      sessionId,
      summary,
      initialWindow: window,
    };
  }

  private ensurePluginSession(sessionId: string, pluginId: string) {
    const existing = this.pluginSessions.get(sessionId);
    if (existing) {
      return existing.pluginId === pluginId ? existing : null;
    }
    if (!/^session-\d+$/.test(sessionId)) {
      if (/^timing-session-\d+$/.test(sessionId)) {
        const summary = buildMockTimingSummary(2);
        const session = {
          pluginId,
          renderer: "table" as const,
          summary,
          window: {
            offset: 0,
            limit: 2,
            totalRows: TIMING_ROWS.length,
            rows: buildMockTimingRows(0, 2),
          },
        };
        this.pluginSessions.set(sessionId, session);
        return session;
      }
      if (/^tree-session-\d+$/.test(sessionId)) {
        const summary = buildMockTreeSummary();
        const session = {
          pluginId,
          renderer: "tree" as const,
          summary,
          window: { op: "children" as const, nodeId: null, nodes: cloneTreeNodes(summary.roots || []) },
        };
        this.pluginSessions.set(sessionId, session);
        return session;
      }
      if (/^repo-tree-session-\d+$/.test(sessionId)) {
        const summary = buildRepoOutlineSummary();
        const session = {
          pluginId,
          renderer: "tree" as const,
          summary,
          window: {
            op: "children" as const,
            nodeId: null,
            nodes: cloneTreeNodes(summary.roots || []),
            statsText: summary.statsText,
          },
        };
        this.pluginSessions.set(sessionId, session);
        return session;
      }
      return null;
    }
    const summary = buildMockWaveformSummary("waves/simple_counter.vcd");
    const session = {
      pluginId,
      renderer: "waveform" as const,
      summary,
      window: {
        startTime: summary.startTime,
        endTime: summary.endTime,
        tracks: buildMockWaveformTracks(),
      },
    };
    this.pluginSessions.set(sessionId, session);
    return session;
  }

  async queryPluginViewWindow(
    _botAlias: string,
    pluginId: string,
    sessionId: string,
    request: PluginViewWindowRequest,
    signal?: AbortSignal,
  ): Promise<PluginViewWindowPayload> {
    signal?.throwIfAborted?.();
    const session = this.ensurePluginSession(sessionId, pluginId);
    if (!session) {
      throw new Error("插件会话不存在");
    }
    if (session.renderer === "table") {
      const offset = Number(request.offset || 0);
      const limit = Number(request.limit || session.summary.defaultPageSize || 2);
      const query = typeof request.query === "string" ? request.query : "";
      const sort = request.sort as { columnId?: string; direction?: string } | undefined;
      return {
        offset,
        limit,
        totalRows: query.trim()
          ? TIMING_ROWS.filter((row) => String(row.cells.endpoint || "").toLowerCase().includes(query.trim().toLowerCase())).length
          : TIMING_ROWS.length,
        rows: buildMockTimingRows(offset, limit, query, sort),
        appliedSort: sort,
      };
    }
    if (session.renderer === "tree") {
      const op = String((request as { op?: string; kind?: string }).op || (request as { op?: string; kind?: string }).kind || "children");
      if (session.pluginId === "repo-outline") {
        const repoRootPath = "rootPath" in session && typeof session.rootPath === "string" ? session.rootPath : "";
        if (op === "search") {
          return buildRepoOutlineSearch(String(request.query || ""), repoRootPath);
        }
        if (!request.nodeId) {
          return {
            op: "children",
            nodeId: null,
            nodes: cloneTreeNodes(buildRepoOutlineRoots(repoRootPath)),
            statsText: repoOutlineStatsText(repoRootPath),
          };
        }
        return {
          op: "children",
          nodeId: String(request.nodeId || ""),
          nodes: cloneTreeNodes(buildRepoOutlineChildren(String(request.nodeId || ""))),
          statsText: repoOutlineStatsText(repoRootPath),
        };
      }
      if (op === "search") {
        const query = String(request.query || "").trim().toLowerCase();
        const roots = buildMockTreeRoots().filter((node) =>
          !query
            || node.label.toLowerCase().includes(query)
            || String(node.secondaryText || node.description || "").toLowerCase().includes(query),
        );
        return { op: "search", nodes: cloneTreeNodes(roots) };
      }
      return {
        op: "children",
        nodeId: String(request.nodeId || ""),
        nodes: cloneTreeNodes(buildMockTreeChildren(String(request.nodeId || ""))),
      };
    }
    const waveformRequest = request as {
      startTime: number;
      endTime: number;
      signalIds: string[];
    };
    return {
      startTime: waveformRequest.startTime,
      endTime: waveformRequest.endTime,
      tracks: session.window.tracks.filter((track) => waveformRequest.signalIds.includes(track.signalId)),
    };
  }

  async disposePluginViewSession(_botAlias: string, pluginId: string, sessionId: string): Promise<void> {
    const session = this.ensurePluginSession(sessionId, pluginId);
    if (!session) {
      return;
    }
    this.pluginSessions.delete(sessionId);
  }

  async invokePluginAction(
    _botAlias: string,
    pluginId: string,
    input: PluginActionInvokeInput,
  ): Promise<PluginActionResult> {
    if (pluginId === "timing-report") {
      this.pluginArtifactCounter += 1;
      const artifactId = `artifact-${this.pluginArtifactCounter}`;
      const content = input.payload?.rowId
        ? `endpoint,slack\n${String(input.payload.rowId)},-0.132\n`
        : "endpoint,slack\nrx_data,-0.132\ntx_data,-0.081\n";
      this.pluginArtifacts.set(artifactId, { filename: "timing.csv", content, contentType: "text/csv" });
      return {
        message: "已导出",
        refresh: "session",
        hostEffects: [{ type: "download_artifact", artifactId, filename: "timing.csv" }],
      };
    }
    if (pluginId === "rtl-hierarchy") {
      if (input.actionId === "open-source") {
        return {
          message: "已打开源码",
          hostEffects: [{ type: "open_file", path: "src/index.ts", line: 12 }],
        };
      }
      return {
        hostEffects: [{ type: "copy_text", text: String(input.payload?.nodeId || "") }],
      };
    }
    if (pluginId === "repo-outline") {
      if (input.actionId === "refresh-tree") {
        return { message: "已刷新", refresh: "session" };
      }
      return { message: "已折叠" };
    }
    return { message: "已执行" };
  }

  async downloadPluginArtifact(_botAlias: string, artifactId: string, filename: string): Promise<void> {
    const artifact = this.pluginArtifacts.get(artifactId);
    const blob = new Blob([artifact?.content || ""], { type: artifact?.contentType || "text/plain" });
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = artifact?.filename || filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(downloadUrl);
  }

  async getPluginArtifactBlob(_botAlias: string, artifactId: string): Promise<Blob> {
    const artifact = this.pluginArtifacts.get(artifactId);
    return new Blob([artifact?.content || ""], { type: artifact?.contentType || "application/octet-stream" });
  }

  async writeFile(botAlias: string, path: string, content: string, expectedMtimeNs?: string, encoding?: string): Promise<FileWriteResult> {
    const browserPath = this.getBrowserPath(botAlias);
    const currentVersion = this.getFileVersion(botAlias, browserPath, path);
    if (expectedMtimeNs !== undefined && expectedMtimeNs !== String(currentVersion)) {
      throw new Error("文件已被修改，请重新打开后再试");
    }

    const nextVersion = this.setFileState(botAlias, browserPath, path, content);
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[browserPath] || [])];
    botFiles[browserPath] = currentEntries.map((entry) =>
      entry.name === path
        ? {
            ...entry,
            size: new TextEncoder().encode(content).length,
            updatedAt: new Date().toISOString(),
          }
        : entry,
    );

    return {
      path,
      fileSizeBytes: new TextEncoder().encode(content).length,
      lastModifiedNs: String(nextVersion),
      encoding,
    };
  }

  async createTextFile(botAlias: string, filename: string, content = "", parentPath?: string): Promise<FileCreateResult> {
    const fileName = filename.trim();
    if (!fileName) {
      throw new Error("文件名不能为空");
    }

    const targetDir = this.resolveTargetDir(botAlias, parentPath);
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[targetDir] || [])];
    if (currentEntries.some((entry) => entry.name === fileName)) {
      throw new Error("文件已存在");
    }

    currentEntries.push({
      name: fileName,
      isDir: false,
      size: new TextEncoder().encode(content).length,
      updatedAt: new Date().toISOString(),
    });
    currentEntries.sort((left, right) => {
      if (left.isDir !== right.isDir) {
        return left.isDir ? -1 : 1;
      }
      return left.name.localeCompare(right.name, "zh-CN");
    });
    botFiles[targetDir] = currentEntries;

    const nextVersion = this.setFileState(botAlias, targetDir, fileName, content);
    const browserPath = this.getBrowserPath(botAlias);
    const normalizedTargetDir = targetDir.replace(/\\/g, "/");
    const normalizedBrowserPath = browserPath.replace(/\\/g, "/");
    const relativeDir = normalizedTargetDir === normalizedBrowserPath
      ? ""
      : normalizedTargetDir.startsWith(`${normalizedBrowserPath}/`)
        ? normalizedTargetDir.slice(normalizedBrowserPath.length + 1)
        : "";
    return {
      path: relativeDir ? `${relativeDir}/${fileName}` : fileName,
      fileSizeBytes: new TextEncoder().encode(content).length,
      lastModifiedNs: String(nextVersion),
    };
  }

  async renamePath(botAlias: string, path: string, newName: string): Promise<FileRenameResult> {
    const browserPath = this.getBrowserPath(botAlias);
    const nextName = newName.trim();
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[browserPath] || [])];
    if (currentEntries.some((entry) => entry.name === nextName)) {
      throw new Error("目标已存在");
    }

    const source = currentEntries.find((entry) => entry.name === path);
    if (!source || source.isDir) {
      throw new Error("文件不存在");
    }

    botFiles[browserPath] = currentEntries.map((entry) =>
      entry.name === path
        ? {
            ...entry,
            name: nextName,
            updatedAt: new Date().toISOString(),
          }
        : entry,
    );

    const content = this.getFileContent(botAlias, browserPath, path);
    const version = this.getFileVersion(botAlias, browserPath, path);
    this.fileContents.delete(this.fileKey(botAlias, browserPath, path));
    this.fileVersions.delete(this.fileKey(botAlias, browserPath, path));
    this.fileContents.set(this.fileKey(botAlias, browserPath, nextName), content);
    this.fileVersions.set(this.fileKey(botAlias, browserPath, nextName), version);

    return {
      oldPath: path,
      path: nextName,
    };
  }

  async copyPath(botAlias: string, path: string): Promise<FileCopyResult> {
    const sourceFullPath = this.resolveFileTreePath(botAlias, path);
    const { dir: sourceDir, name: sourceName } = this.splitMockFilePath(sourceFullPath);
    const botFiles = (mockFiles[botAlias] ||= {});
    const source = (botFiles[sourceDir] || []).find((entry) => entry.name === sourceName);
    if (!source || source.isDir) {
      throw new Error("文件不存在");
    }

    const copyName = this.buildCopyName(botFiles, sourceDir, sourceName);
    const content = this.getFileContent(botAlias, sourceDir, sourceName);
    const version = this.setFileState(botAlias, sourceDir, copyName, content);
    const nextEntry = {
      ...source,
      name: copyName,
      updatedAt: new Date().toISOString(),
    };
    const entries = [...(botFiles[sourceDir] || []), nextEntry];
    this.sortFileEntries(entries);
    botFiles[sourceDir] = entries;

    const targetFullPath = sourceDir === "/" ? `/${copyName}` : `${sourceDir}/${copyName}`;
    return {
      sourcePath: this.relativeMockPath(botAlias, sourceFullPath),
      path: this.relativeMockPath(botAlias, targetFullPath),
      fileSizeBytes: source.size || new TextEncoder().encode(content).length,
      lastModifiedNs: String(version),
    };
  }

  async movePath(botAlias: string, path: string, targetParentPath: string): Promise<FileMoveResult> {
    const sourceFullPath = this.resolveFileTreePath(botAlias, path);
    const targetDir = this.resolveFileTreePath(botAlias, targetParentPath);
    const { dir: sourceDir, name: sourceName } = this.splitMockFilePath(sourceFullPath);
    const botFiles = (mockFiles[botAlias] ||= {});
    const sourceEntries = [...(botFiles[sourceDir] || [])];
    const source = sourceEntries.find((entry) => entry.name === sourceName);
    if (!source || source.isDir) {
      throw new Error("文件不存在");
    }
    if (sourceDir === targetDir) {
      throw new Error("文件已在目标文件夹中");
    }
    if (!(botFiles[targetDir] || []).some((entry) => entry.isDir) && !(targetDir in botFiles)) {
      throw new Error("目录不存在");
    }

    const targetEntries = [...(botFiles[targetDir] || [])];
    if (targetEntries.some((entry) => entry.name === sourceName)) {
      throw new Error("目标已存在");
    }

    botFiles[sourceDir] = sourceEntries.filter((entry) => entry.name !== sourceName);
    targetEntries.push({ ...source, updatedAt: new Date().toISOString() });
    this.sortFileEntries(targetEntries);
    botFiles[targetDir] = targetEntries;

    const content = this.getFileContent(botAlias, sourceDir, sourceName);
    const version = this.getFileVersion(botAlias, sourceDir, sourceName);
    this.fileContents.delete(this.fileKey(botAlias, sourceDir, sourceName));
    this.fileVersions.delete(this.fileKey(botAlias, sourceDir, sourceName));
    this.fileContents.set(this.fileKey(botAlias, targetDir, sourceName), content);
    this.fileVersions.set(this.fileKey(botAlias, targetDir, sourceName), version);

    const targetFullPath = targetDir === "/" ? `/${sourceName}` : `${targetDir}/${sourceName}`;
    return {
      oldPath: this.relativeMockPath(botAlias, sourceFullPath),
      path: this.relativeMockPath(botAlias, targetFullPath),
    };
  }

  async quickOpenWorkspace(botAlias: string, query: string, limit = 50): Promise<WorkspaceQuickOpenResult> {
    const q = query.trim().toLowerCase();
    const botFiles = mockFiles[botAlias] || {};
    const rootPath = this.getBrowserPath(botAlias).replace(/\\/g, "/");
    const items = Object.entries(botFiles)
      .flatMap(([directory, entries]) => entries
        .filter((entry) => !entry.isDir)
        .map((entry) => {
          const normalizedDir = directory.replace(/\\/g, "/");
          const relativeDir = normalizedDir === rootPath
            ? ""
            : normalizedDir.startsWith(`${rootPath}/`)
              ? normalizedDir.slice(rootPath.length + 1)
              : normalizedDir.replace(/^\/+/, "");
          const path = relativeDir ? `${relativeDir}/${entry.name}` : entry.name;
          const lowerPath = path.toLowerCase();
          const basename = entry.name.toLowerCase();
          const score = basename.includes(q) ? 1000 : lowerPath.includes(q) ? 300 : 0;
          return { path, score };
        }))
      .filter((item) => !q || item.path.toLowerCase().includes(q))
      .sort((left, right) => right.score - left.score || left.path.localeCompare(right.path, "zh-CN"))
      .slice(0, limit);
    return { items };
  }

  async searchWorkspace(
    botAlias: string,
    query: string,
    limit = 100,
    _signal?: AbortSignal,
  ): Promise<WorkspaceSearchResult> {
    const q = query.trim().toLowerCase();
    if (!q) {
      return { items: [] };
    }
    const quick = await this.quickOpenWorkspace(botAlias, "", 500);
    const root = this.getBrowserPath(botAlias);
    const items = quick.items.flatMap((item) => {
      const content = this.getFileContent(botAlias, root, item.path);
      const lines = content.split(/\r?\n/);
      return lines.flatMap((line, index) => {
        const column = line.toLowerCase().indexOf(q);
        return column >= 0
          ? [{
              path: item.path,
              line: index + 1,
              column: column + 1,
              preview: line,
            }]
          : [];
      });
    }).slice(0, limit);
    return { items };
  }

  async getWorkspaceOutline(botAlias: string, path: string): Promise<WorkspaceOutlineResult> {
    const content = this.getFileContent(botAlias, this.getBrowserPath(botAlias), path);
    const items: WorkspaceOutlineResult["items"] = [];
    content.split(/\r?\n/).forEach((line, index) => {
      const classMatch = line.match(/^\s*class\s+([A-Za-z_][\w]*)/);
      if (classMatch) {
        items.push({ name: classMatch[1], kind: "class", line: index + 1 });
        return;
      }
      const functionMatch = line.match(/^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)|^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/);
      if (functionMatch) {
        items.push({ name: functionMatch[1] || functionMatch[2], kind: "function", line: index + 1 });
        return;
      }
      const headingMatch = line.match(/^#{1,6}\s+(.+)/);
      if (headingMatch) {
        items.push({ name: headingMatch[1].trim(), kind: "heading", line: index + 1 });
      }
    });
    return { items };
  }

  async resolveWorkspaceDefinition(
    botAlias: string,
    input: { path: string; line: number; column: number; symbol?: string },
  ): Promise<WorkspaceDefinitionResult> {
    const symbol = input.symbol?.trim();
    if (symbol === "run") {
      return {
        items: [
          {
            path: "src/service.py",
            line: 12,
            matchKind: "workspace_search",
            confidence: 0.78,
          },
        ],
      };
    }
    return {
      items: [],
    };
  }

  async uploadChatAttachment(botAlias: string, file: File): Promise<ChatAttachmentUploadResult> {
    const filename = file.name || "attachment.bin";
    return {
      filename,
      savedPath: `C:\\Users\\demo\\.tcb\\chat-attachments\\${botAlias}\\1001\\${filename}`,
      size: file.size,
    };
  }

  async deleteChatAttachment(_botAlias: string, savedPath: string): Promise<ChatAttachmentDeleteResult> {
    const segments = savedPath.split(/[\\/]+/).filter(Boolean);
    return {
      filename: segments[segments.length - 1] || savedPath,
      savedPath,
      existed: true,
      deleted: true,
    };
  }

  async uploadFile(botAlias: string, file: File): Promise<void> {
    return;
  }

  async downloadFile(botAlias: string, filename: string, onProgress?: (progress: FileDownloadProgress) => void): Promise<void> {
    onProgress?.({ downloadedBytes: 0, totalBytes: 1, percent: 0 });
    onProgress?.({ downloadedBytes: 1, totalBytes: 1, percent: 100 });
    return;
  }

  async resetSession(botAlias: string): Promise<void> {
    return;
  }

  async killTask(botAlias: string, options: AgentScopedOptions = {}): Promise<string> {
    void options;
    return "已发送终止任务请求";
  }

  async replyNativeAgentPermission(
    botAlias: string,
    permissionId: string,
    options: NativeAgentPermissionReplyOptions,
  ): Promise<{ permissionId: string; approved: boolean }> {
    void botAlias;
    void options;
    return { permissionId, approved: Boolean(options.approved) };
  }

  async restartService(): Promise<void> {
    return;
  }

  async getGitProxySettings(): Promise<GitProxySettings> {
    return { ...this.gitProxySettings };
  }

  async getCliErrorStats(filters: CliErrorStatsFilters = {}): Promise<CliErrorStatsResult> {
    const items = this.cliErrorStats.items.filter((item) => {
      if (filters.alias && item.botAlias !== filters.alias) return false;
      if (filters.cliType && item.cliType !== filters.cliType) return false;
      if (filters.category && item.category !== filters.category) return false;
      return true;
    });
    const byCliType: Record<string, number> = {};
    const byBot: Record<string, number> = {};
    const byCategory: Record<string, number> = {};
    items.forEach((item) => {
      byCliType[item.cliType] = (byCliType[item.cliType] || 0) + 1;
      byBot[item.botAlias] = (byBot[item.botAlias] || 0) + 1;
      byCategory[item.category] = (byCategory[item.category] || 0) + 1;
    });
    return {
      summary: {
        total: items.length,
        byCliType,
        byBot,
        byCategory,
        latestAt: items[0]?.startedAt || "",
      },
      topErrors: this.cliErrorStats.topErrors.filter((item) => !filters.category || item.category === filters.category),
      items: items.slice(0, filters.limit || 200),
    };
  }

  async updateGitProxySettings(address: string): Promise<GitProxySettings> {
    const trimmed = (address || "").trim();
    const normalizedAddress = /^\d+$/.test(trimmed) ? `127.0.0.1:${trimmed}` : trimmed;
    this.gitProxySettings = {
      address: normalizedAddress,
      port: normalizedAddress ? normalizedAddress.split(":").pop() || "" : "",
    };
    return { ...this.gitProxySettings };
  }

  async getUpdateStatus(): Promise<AppUpdateStatus> {
    return { ...this.updateStatus };
  }

  async setUpdateEnabled(enabled: boolean): Promise<AppUpdateStatus> {
    this.updateStatus = {
      ...this.updateStatus,
      updateEnabled: enabled,
    };
    return { ...this.updateStatus };
  }

  async checkForUpdate(): Promise<AppUpdateStatus> {
    this.updateStatus = {
      ...this.updateStatus,
      lastCheckedAt: "2026-04-15T10:00:00+08:00",
      latestVersion: APP_VERSION,
      latestReleaseUrl: MOCK_RELEASE_URL,
      latestNotes: "Bugfixes",
      lastError: "",
    };
    return { ...this.updateStatus };
  }

  async downloadUpdate(): Promise<AppUpdateStatus> {
    const packageKind = this.updateStatus.currentPackageKind || "installer";
    const pendingUpdatePath = getMockUpdatePath(packageKind);
    const pendingUpdatePlatform = getMockUpdatePlatform(packageKind);
    this.updateStatus = {
      ...this.updateStatus,
      pendingUpdateVersion: this.updateStatus.latestVersion || APP_VERSION,
      pendingUpdatePath,
      pendingUpdateNotes: this.updateStatus.latestNotes || "Bugfixes",
      pendingUpdatePlatform,
      pendingUpdatePackageKind: packageKind,
      lastError: "",
    };
    return { ...this.updateStatus };
  }

  async downloadUpdateStream(onProgress: (event: AppUpdateDownloadProgress) => void): Promise<AppUpdateStatus> {
    onProgress({
      phase: "log",
      downloadedBytes: 0,
      message: "开始下载更新包",
    });
    await new Promise((resolve) => setTimeout(resolve, 40));
    onProgress({
      phase: "log",
      downloadedBytes: 1024,
      totalBytes: 1024,
      percent: 100,
      message: "下载完成",
    });
    return this.downloadUpdate();
  }

  async listOfflineUpdatePackages(): Promise<OfflineUpdatePackageList> {
    return {
      artifactsDir: this.offlineUpdatePackages.artifactsDir,
      items: this.offlineUpdatePackages.items.map((item) => ({ ...item })),
    };
  }

  async prepareOfflineUpdate(path: string, version = ""): Promise<AppUpdateStatus> {
    const normalizedPath = path.trim();
    if (!normalizedPath) {
      throw new WebApiClientError("离线包路径不能为空", { status: 400, code: "offline_package_path_required" });
    }
    const selected = this.offlineUpdatePackages.items.find((item) => item.path === normalizedPath);
    if (!selected) {
      throw new WebApiClientError("离线包不存在", { status: 404, code: "offline_package_not_found" });
    }
    if (!selected.valid) {
      throw new WebApiClientError(selected.error || "离线包校验失败", { status: 400, code: "offline_package_invalid" });
    }
    this.updateStatus = {
      ...this.updateStatus,
      pendingUpdateVersion: version || selected.version || this.updateStatus.latestVersion || APP_VERSION,
      pendingUpdatePath: selected.path,
      pendingUpdateNotes: `已选择离线包 ${selected.name}`,
      pendingUpdatePlatform: getMockUpdatePlatform(selected.packageKind),
      pendingUpdatePackageKind: selected.packageKind,
      lastError: "",
    };
    return { ...this.updateStatus };
  }

  async prepareOfflineUpdateStream(
    path: string,
    version: string | undefined,
    onProgress: (event: AppUpdateDownloadProgress) => void,
  ): Promise<AppUpdateStatus> {
    const normalizedPath = path.trim();
    const selected = this.offlineUpdatePackages.items.find((item) => item.path === normalizedPath);
    onProgress({ phase: "log", downloadedBytes: 0, message: `已选择包: ${normalizedPath}` });
    onProgress({ phase: "log", downloadedBytes: 0, message: "校验中" });
    await new Promise((resolve) => setTimeout(resolve, 40));
    if (!selected) {
      onProgress({ phase: "log", downloadedBytes: 0, message: "失败原因: 离线包不存在" });
      throw new WebApiClientError("离线包不存在", { status: 404, code: "offline_package_not_found" });
    }
    if (!selected.valid) {
      const reason = selected.error || "离线包校验失败";
      onProgress({ phase: "log", downloadedBytes: 0, message: `失败原因: ${reason}` });
      throw new WebApiClientError(reason, { status: 400, code: "offline_package_invalid" });
    }
    const status = await this.prepareOfflineUpdate(normalizedPath, version);
    onProgress({ phase: "log", downloadedBytes: 0, message: "已设置待应用" });
    return status;
  }

  async getGitOverview(botAlias: string): Promise<GitOverview> {
    const workingDir = this.workdirOverrides.get(botAlias) || this.getBotSummary(botAlias).workingDir;
    const overview = this.gitOverviews.get(botAlias);
    if (!overview) {
      return {
        repoFound: false,
        canInit: true,
        workingDir,
        repoPath: "",
        repoName: "",
        currentBranch: "",
        isClean: true,
        aheadCount: 0,
        behindCount: 0,
        changedFiles: [],
        recentCommits: [],
      };
    }
    return {
      ...overview,
      workingDir,
      repoPath: overview.repoPath || workingDir,
    };
  }

  async getGitTreeStatus(botAlias: string): Promise<GitTreeStatus> {
    const overview = await this.getGitOverview(botAlias);
    const items: GitTreeStatus["items"] = {};

    for (const item of overview.changedFiles) {
      items[item.path] = item.untracked || item.status.startsWith("A")
        ? "added"
        : "modified";
    }

    for (const path of MOCK_GIT_IGNORED_ITEMS[botAlias] || []) {
      items[path] = "ignored";
    }

    return {
      repoFound: overview.repoFound,
      workingDir: overview.workingDir,
      repoPath: overview.repoPath,
      items,
    };
  }

  async getGitCommitGraph(botAlias: string, options: GitCommitGraphOptions = {}): Promise<GitCommitGraphPayload> {
    const overview = await this.getGitOverview(botAlias);
    const scope = options.scope || "all";
    if (!overview.repoFound) {
      return {
        repoFound: false,
        scope,
        nodes: [],
        hasMore: false,
        nextCursor: "",
      };
    }

    const allNodes = [
      {
        hash: "f03a9c6d1e2b4a7890f1234567890abcdef0001",
        shortHash: "f03a9c6",
        parents: ["c9d8e7f6a5b4c321001122334455667788990000", "91a7b6c5d4e3f2011223344556677889900aabb"],
        authorName: "Web Bot",
        authoredAt: "2026-05-28T09:18:00+08:00",
        subject: "merge: sync release graph",
        refs: [
          { name: "HEAD", kind: "head" as const, current: true },
          { name: overview.currentBranch || "main", kind: "local_branch" as const, current: true },
          { name: "origin/main", kind: "remote_branch" as const, current: false },
        ],
        graph: { column: 0, width: 3, edges: [{ from: 0, to: 0 }, { from: 1, to: 0 }] },
        canReset: true,
      },
      {
        hash: "c9d8e7f6a5b4c321001122334455667788990000",
        shortHash: "c9d8e7f",
        parents: ["847b894000000000000000000000000000000000"],
        authorName: "Web Bot",
        authoredAt: "2026-05-27T21:40:00+08:00",
        subject: "feat: add git version tree",
        refs: [
          { name: "feature/git-panel", kind: "local_branch" as const, current: false },
          { name: "v0.9.0", kind: "tag" as const, current: false },
        ],
        graph: { column: 0, width: 2, edges: [{ from: 0, to: 0 }] },
        canReset: true,
      },
      {
        hash: "91a7b6c5d4e3f2011223344556677889900aabb",
        shortHash: "91a7b6c",
        parents: ["847b894000000000000000000000000000000000"],
        authorName: "Reviewer",
        authoredAt: "2026-05-27T18:12:00+08:00",
        subject: "fix: keep graph lanes stable",
        refs: [
          { name: "origin/release", kind: "remote_branch" as const, current: false },
        ],
        graph: { column: 1, width: 2, edges: [{ from: 1, to: 0 }] },
        canReset: true,
      },
      {
        hash: "847b894000000000000000000000000000000000",
        shortHash: "847b894",
        parents: [],
        authorName: "Web Bot",
        authoredAt: "2026-04-08T03:00:00+08:00",
        subject: "feat: 实现完整的Web前端与后端集成",
        refs: [],
        graph: { column: 0, width: 1, edges: [] },
        canReset: true,
      },
    ];
    const scopedNodes = scope === "current"
      ? allNodes.filter((node) => node.hash !== "91a7b6c5d4e3f2011223344556677889900aabb")
      : allNodes;
    const offset = Number(options.cursor || 0) || 0;
    const limit = Math.max(1, Math.min(Number(options.limit || 100), 300));
    const nodes = scopedNodes.slice(offset, offset + limit);
    const nextOffset = offset + nodes.length;
    return {
      repoFound: true,
      scope,
      nodes,
      hasMore: nextOffset < scopedNodes.length,
      nextCursor: nextOffset < scopedNodes.length ? String(nextOffset) : "",
    };
  }

  async initGitRepository(botAlias: string): Promise<GitOverview> {
    const workingDir = this.workdirOverrides.get(botAlias) || this.getBotSummary(botAlias).workingDir;
    const next: GitOverview = {
      repoFound: true,
      canInit: false,
      workingDir,
      repoPath: workingDir,
      repoName: workingDir.split(/[\\/]+/).filter(Boolean).pop() || "repo",
      currentBranch: "main",
      isClean: true,
      aheadCount: 0,
      behindCount: 0,
      changedFiles: [],
      recentCommits: [],
    };
    this.gitOverviews.set(botAlias, next);
    return next;
  }

  async getGitDiff(_botAlias: string, path: string, staged = false): Promise<GitDiffPayload> {
    return {
      path,
      staged,
      diff: `diff --git a/${path} b/${path}\n@@ -1 +1 @@\n-old line\n+new line`,
    };
  }

  private async actionWithOverview(botAlias: string, message: string, mutator?: (overview: GitOverview) => GitOverview): Promise<GitActionResult> {
    const current = await this.getGitOverview(botAlias);
    const next = mutator ? mutator(current) : current;
    this.gitOverviews.set(botAlias, next);
    return {
      message,
      overview: next,
    };
  }

  private setGitSmartCommitJob(job: GitSmartCommitJob) {
    this.gitSmartCommitJobs.set(job.jobId, job);
    this.gitSmartCommitActiveJobs.set(job.alias, job.jobId);
    if (job.overview) {
      this.gitOverviews.set(job.alias, job.overview);
    }
  }

  private cloneGitSmartCommitJob(job: GitSmartCommitJob | null | undefined): GitSmartCommitJob | null {
    if (!job) {
      return null;
    }
    return {
      ...job,
      overview: job.overview ? {
        ...job.overview,
        changedFiles: job.overview.changedFiles.map((item) => ({ ...item })),
        recentCommits: job.overview.recentCommits.map((item) => ({ ...item })),
      } : null,
    };
  }

  async stageGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已暂存所选文件", (overview) => ({
      ...overview,
      changedFiles: overview.changedFiles.map((item) =>
        paths.includes(item.path)
          ? { ...item, staged: true, untracked: false, status: item.unstaged ? "MM" : "M " }
          : item,
      ),
      isClean: false,
    }));
  }

  async unstageGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已取消暂存所选文件", (overview) => ({
      ...overview,
      changedFiles: overview.changedFiles.map((item) =>
        paths.includes(item.path)
          ? { ...item, staged: false, status: item.untracked ? "??" : " M" }
          : item,
      ),
    }));
  }

  async discardGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已丢弃所选文件改动", (overview) => {
      const changedFiles = overview.changedFiles.filter((item) => !paths.includes(item.path));
      return {
        ...overview,
        changedFiles,
        isClean: changedFiles.length === 0,
      };
    });
  }

  async discardAllGitChanges(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已丢弃全部改动", (overview) => ({
      ...overview,
      isClean: true,
      changedFiles: [],
    }));
  }

  async commitGitChanges(botAlias: string, message: string): Promise<GitActionResult> {
    const subject = (message || "").trim() || "mock commit";
    return this.actionWithOverview(botAlias, "已创建提交", (overview) => ({
      ...overview,
      isClean: true,
      changedFiles: [],
      recentCommits: [
        {
          hash: `${Date.now()}`,
          shortHash: `${Date.now()}`.slice(-7),
          authorName: "Web Bot",
          authoredAt: new Date().toISOString(),
          subject,
        },
        ...overview.recentCommits,
      ],
    }));
  }

  async fetchGitRemote(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已抓取远端更新");
  }

  async pullGitRemote(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已拉取远端更新");
  }

  async pushGitRemote(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已推送本地提交");
  }

  async stashGitChanges(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已暂存当前工作区", (overview) => ({
      ...overview,
      isClean: true,
      changedFiles: [],
    }));
  }

  async popGitStash(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已恢复最近一次暂存", (overview) => ({
      ...overview,
      isClean: false,
      changedFiles: [
        {
          path: "restored.txt",
          status: " M",
          staged: false,
          unstaged: true,
          untracked: false,
        },
      ],
    }));
  }

  private async getGitBranchListState(botAlias: string): Promise<GitBranchList> {
    const cached = this.gitBranches.get(botAlias);
    if (cached) {
      return cached;
    }
    const overview = await this.getGitOverview(botAlias);
    const currentBranch = overview.currentBranch || "main";
    const branches: GitBranchList = {
      currentBranch,
      branches: [
        {
          name: currentBranch,
          current: true,
          upstream: "origin/main",
          shortHash: overview.recentCommits[0]?.shortHash || "abc1234",
          subject: overview.recentCommits[0]?.subject || "feat: initial commit",
        },
        {
          name: "feature/git-panel",
          current: false,
          upstream: "",
          shortHash: "def5678",
          subject: "wip: git panel",
        },
      ],
    };
    this.gitBranches.set(botAlias, branches);
    return branches;
  }

  async listGitBranches(botAlias: string): Promise<GitBranchList> {
    return this.getGitBranchListState(botAlias);
  }

  async createGitBranch(botAlias: string, name: string, startPoint = ""): Promise<GitBranchList> {
    const current = await this.getGitBranchListState(botAlias);
    const overview = await this.getGitOverview(botAlias);
    const sourceCommit = overview.recentCommits.find((item) => item.hash === startPoint || item.shortHash === startPoint);
    const next = {
      currentBranch: current.currentBranch,
      branches: [
        ...current.branches.filter((item) => item.name !== name),
        {
          name,
          current: false,
          upstream: "",
          shortHash: sourceCommit?.shortHash || overview.recentCommits[0]?.shortHash || "abc1234",
          subject: sourceCommit?.subject || overview.recentCommits[0]?.subject || "created from current branch",
        },
      ],
    };
    this.gitBranches.set(botAlias, next);
    return next;
  }

  async switchGitBranch(botAlias: string, name: string): Promise<GitBranchList> {
    const current = await this.getGitBranchListState(botAlias);
    const overview = await this.getGitOverview(botAlias);
    this.gitOverviews.set(botAlias, { ...overview, currentBranch: name });
    const knownBranches = current.branches.some((item) => item.name === name)
      ? current.branches
      : [...current.branches, { name, current: false, upstream: "", shortHash: "abc1234", subject: "" }];
    const next = {
      currentBranch: name,
      branches: knownBranches.map((item) => ({ ...item, current: item.name === name })),
    };
    this.gitBranches.set(botAlias, next);
    return next;
  }

  async resetGitBranch(botAlias: string, commit: string, mode: GitResetMode): Promise<GitBranchResetResult> {
    const overview = await this.getGitOverview(botAlias);
    const target = overview.recentCommits.find((item) => item.hash === commit || item.shortHash === commit);
    const fallbackCommit = target || {
      hash: commit,
      shortHash: commit.slice(0, 7),
      authorName: "Web Bot",
      authoredAt: new Date().toISOString(),
      subject: `reset --${mode}`,
      message: `reset --${mode}`,
    };
    const nextOverview = {
      ...overview,
      isClean: true,
      changedFiles: [],
      recentCommits: [
        fallbackCommit,
        ...overview.recentCommits.filter((item) => item.hash !== fallbackCommit.hash),
      ],
    };
    this.gitOverviews.set(botAlias, nextOverview);
    const current = await this.getGitBranchListState(botAlias);
    const nextBranches = {
      currentBranch: current.currentBranch,
      branches: current.branches.map((item) => item.current
        ? { ...item, shortHash: fallbackCommit.shortHash, subject: fallbackCommit.subject }
        : item),
    };
    this.gitBranches.set(botAlias, nextBranches);
    return {
      message: "分支已重置",
      overview: nextOverview,
      branches: nextBranches.branches,
      currentBranch: nextBranches.currentBranch,
      headCommit: fallbackCommit.hash,
    };
  }

  async listGitStashes(botAlias: string): Promise<GitStashList> {
    return this.gitStashes.get(botAlias) || { items: [] };
  }

  async applyGitStash(botAlias: string, ref: string): Promise<GitActionResult> {
    const result = await this.actionWithOverview(botAlias, "已应用 stash", (overview) => ({
      ...overview,
      isClean: false,
      changedFiles: [{ path: "restored.txt", status: " M", staged: false, unstaged: true, untracked: false }],
    }));
    this.gitStashes.set(botAlias, {
      items: (this.gitStashes.get(botAlias)?.items || []).filter((item) => item.ref !== ref),
    });
    return result;
  }

  async dropGitStash(botAlias: string, ref: string): Promise<GitActionResult> {
    this.gitStashes.set(botAlias, {
      items: (this.gitStashes.get(botAlias)?.items || []).filter((item) => item.ref !== ref),
    });
    return this.actionWithOverview(botAlias, "已删除 stash");
  }

  async getGitBlame(_botAlias: string, path: string): Promise<GitBlamePayload> {
    return {
      path,
      lines: [
        {
          line: 1,
          commit: "abcdef0123456789",
          shortCommit: "abcdef0",
          authorName: "Web Bot",
          authorMail: "web-bot@example.com",
          authoredAt: "2026-04-28T02:30:00",
          summary: "feat: initial commit",
          content: "mock line",
        },
      ],
    };
  }

  async getGitIdentityConfig(botAlias: string): Promise<GitIdentityConfig> {
    const overview = await this.getGitOverview(botAlias);
    const cached = this.gitIdentityConfigs.get(botAlias);
    return cached
      ? { ...cached, repoFound: overview.repoFound, repoPath: overview.repoPath }
      : {
        repoFound: overview.repoFound,
        repoPath: overview.repoPath,
        global: { name: "", email: "" },
        local: { name: "", email: "" },
      };
  }

  async updateGitIdentityConfig(
    botAlias: string,
    input: { scope: GitIdentityScope; name: string; email: string },
  ): Promise<GitIdentityConfig> {
    const current = await this.getGitIdentityConfig(botAlias);
    const next = {
      ...current,
      [input.scope]: {
        name: input.name.trim(),
        email: input.email.trim(),
      },
    };
    this.gitIdentityConfigs.set(botAlias, next);
    return next;
  }

  async getGitCommitMessageConfig(botAlias: string): Promise<GitCommitMessageCliConfig> {
    this.getBotSummary(botAlias);
    const cached = this.gitCommitMessageConfig;
    if (cached) {
      return {
        ...cached,
        params: { ...cached.params },
        defaults: { ...cached.defaults },
        schema: { ...cached.schema },
      };
    }
    const bot = this.getBotSummary("main");
    return buildMockGitCommitMessageConfig(bot.cliType, bot.cliPath);
  }

  async updateGitCommitMessageConfig(
    botAlias: string,
    input: GitCommitMessageCliConfigUpdateInput,
  ): Promise<GitCommitMessageCliConfig> {
    const current = await this.getGitCommitMessageConfig(botAlias);
    const nextCliType = input.cliType || current.cliType;
    const base = buildMockGitCommitMessageConfig(nextCliType, input.cliPath || current.cliPath);
    const next: GitCommitMessageCliConfig = {
      ...base,
      cliPath: input.cliPath !== undefined ? input.cliPath.trim() || defaultCliPathForType(nextCliType) : base.cliPath,
      params: {
        ...base.params,
        ...current.params,
        ...(input.params || {}),
      },
    };
    this.gitCommitMessageConfig = next;
    return {
      ...next,
      params: { ...next.params },
      defaults: { ...next.defaults },
      schema: { ...next.schema },
    };
  }

  async resetGitCommitMessageConfig(botAlias: string): Promise<GitCommitMessageCliConfig> {
    this.getBotSummary(botAlias);
    const bot = this.getBotSummary("main");
    const next = buildMockGitCommitMessageConfig(bot.cliType, bot.cliPath);
    this.gitCommitMessageConfig = next;
    return {
      ...next,
      params: { ...next.params },
      defaults: { ...next.defaults },
      schema: { ...next.schema },
    };
  }

  async generateGitCommitMessage(botAlias: string): Promise<GitCommitMessageGenerateResult> {
    const overview = await this.getGitOverview(botAlias);
    const firstChanged = overview.changedFiles[0]?.path || "repo";
    const scope = firstChanged.includes("/")
      ? firstChanged.split("/")[0]
      : firstChanged.replace(/\.[^.]+$/, "") || "repo";
    return {
      message: `feat(${scope}): update changed files`,
    };
  }

  async startGitSmartCommit(botAlias: string): Promise<GitSmartCommitJob> {
    const current = this.gitSmartCommitActiveJobs.get(botAlias);
    if (current) {
      const existing = this.gitSmartCommitJobs.get(current);
      if (existing && (existing.status === "queued" || existing.status === "running")) {
        return this.cloneGitSmartCommitJob(existing) as GitSmartCommitJob;
      }
    }
    const overview = await this.getGitOverview(botAlias);
    const firstChanged = overview.changedFiles[0]?.path || "repo";
    const scope = firstChanged.includes("/")
      ? firstChanged.split("/")[0]
      : firstChanged.replace(/\.[^.]+$/, "") || "repo";
    const message = `feat(${scope}): update changed files`;
    const committedOverview: GitOverview = {
      ...overview,
      isClean: true,
      changedFiles: [],
      recentCommits: [
        {
          hash: `${Date.now()}`,
          shortHash: `${Date.now()}`.slice(-7),
          authorName: "Web Bot",
          authoredAt: new Date().toISOString(),
          subject: message,
          message,
        },
        ...overview.recentCommits,
      ],
    };
    const jobId = `git-smart-${this.gitSmartCommitJobSeq++}`;
    const job: GitSmartCommitJob = {
      jobId,
      alias: botAlias,
      userId: 1001,
      status: "running",
      phase: "generating",
      message: "",
      error: "",
      overview: null,
    };
    this.setGitSmartCommitJob(job);
    window.setTimeout(() => {
      this.setGitSmartCommitJob({
        ...job,
        status: "running",
        phase: "staging",
        message,
      });
    }, 50);
    window.setTimeout(() => {
      this.setGitSmartCommitJob({
        ...job,
        status: "running",
        phase: "committing",
        message,
      });
    }, 100);
    window.setTimeout(() => {
      this.setGitSmartCommitJob({
        ...job,
        status: "succeeded",
        phase: "done",
        message,
        overview: committedOverview,
      });
    }, 150);
    return this.cloneGitSmartCommitJob(job) as GitSmartCommitJob;
  }

  async getActiveGitSmartCommit(botAlias: string): Promise<GitSmartCommitJob | null> {
    return this.cloneGitSmartCommitJob(this.gitSmartCommitJobs.get(this.gitSmartCommitActiveJobs.get(botAlias) || ""));
  }

  async getGitSmartCommitJob(_botAlias: string, jobId: string): Promise<GitSmartCommitJob> {
    const job = this.gitSmartCommitJobs.get(jobId);
    if (!job) {
      throw new WebApiClientError("智能提交任务不存在", { status: 404, code: "git_smart_commit_not_found" });
    }
    return this.cloneGitSmartCommitJob(job) as GitSmartCommitJob;
  }

  async getLanChatConfig(): Promise<LanChatConfig> {
    return { ...this.lanChatConfig };
  }

  async updateLanChatConfig(input: LanChatConfigInput): Promise<LanChatConfig> {
    this.lanChatConfig = {
      ...this.lanChatConfig,
      ...(input.mode ? { mode: input.mode } : {}),
      ...(input.roomName !== undefined ? { roomName: input.roomName } : {}),
      ...(input.instanceName !== undefined ? { instanceName: input.instanceName } : {}),
      ...(input.hostUrl !== undefined ? { hostUrl: input.hostUrl } : {}),
      ...(input.roomKey !== undefined ? {
        roomKey: input.roomKey,
        roomKeyPreview: input.roomKey ? `tcbr...${input.roomKey.slice(-4)}` : "",
      } : {}),
      ...(input.lanOnly !== undefined ? { lanOnly: input.lanOnly } : {}),
      ...(input.autoConnect !== undefined ? { autoConnect: input.autoConnect } : {}),
    };
    const group = this.lanChatConversations.get("group:default");
    if (group) {
      this.lanChatConversations.set("group:default", {
        ...group,
        title: this.lanChatConfig.roomName,
        updatedAt: this.lanChatNow(),
      });
    }
    this.emitLanChatEvent({ type: "config_updated", config: { ...this.lanChatConfig } });
    this.emitLanChatEvent({ type: "presence_updated", status: this.buildLanChatStatus() });
    return { ...this.lanChatConfig };
  }

  async getLanChatStatus(): Promise<LanChatStatus> {
    return this.buildLanChatStatus();
  }

  async listLanChatConversations(): Promise<LanChatConversation[]> {
    return Array.from(this.lanChatConversations.values())
      .map((conversation) => this.lanChatConversationWithUnread(conversation))
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  }

  async listLanChatMessages(conversationId: string, afterSeq = 0, limit = 50): Promise<LanChatMessage[]> {
    return this.lanChatMessages
      .filter((message) => message.conversationId === conversationId && message.seq > afterSeq)
      .slice(-limit)
      .map((message) => this.cloneLanChatMessage(message));
  }

  async createLanChatPrivateConversation(targetRoomUserId: string): Promise<LanChatConversation> {
    const self = this.lanChatSelf();
    const target = this.lanChatUsers.find((user) => user.roomUserId === targetRoomUserId);
    if (!target) {
      throw new WebApiClientError("联机聊天用户不存在", { status: 404, code: "lan_chat_user_not_found" });
    }
    const conversationId = `dm:${targetRoomUserId}`;
    const current = this.lanChatConversations.get(conversationId);
    if (current) {
      return this.lanChatConversationWithUnread(current);
    }
    const conversation: LanChatConversation = {
      id: conversationId,
      kind: "dm",
      title: target.displayName,
      participantIds: [self.roomUserId, target.roomUserId],
      lastMessage: null,
      unreadCount: 0,
      updatedAt: this.lanChatNow(),
    };
    this.lanChatConversations.set(conversation.id, conversation);
    this.emitLanChatEvent({ type: "conversation_updated", conversation: this.cloneLanChatConversation(conversation) });
    return this.cloneLanChatConversation(conversation);
  }

  async sendLanChatMessage(conversationId: string, text: string): Promise<LanChatMessage> {
    const conversation = this.lanChatConversations.get(conversationId);
    if (!conversation) {
      throw new WebApiClientError("联机聊天会话不存在", { status: 404, code: "lan_chat_conversation_not_found" });
    }
    const message: LanChatMessage = {
      id: `msg_${this.lanChatMessages.length + 1}`,
      seq: this.lanChatMessages.length + 1,
      conversationId,
      kind: conversation.kind,
      sender: this.lanChatSelf(),
      text: text.trim(),
      createdAt: this.lanChatNow(),
    };
    this.lanChatMessages = [...this.lanChatMessages, message];
    const updatedConversation = {
      ...conversation,
      lastMessage: message,
      updatedAt: message.createdAt,
    };
    this.lanChatConversations.set(conversationId, updatedConversation);
    this.emitLanChatEvent({ type: "message_created", message: this.cloneLanChatMessage(message) });
    this.emitLanChatEvent({
      type: "conversation_updated",
      conversation: this.lanChatConversationWithUnread(updatedConversation),
    });
    return this.cloneLanChatMessage(message);
  }

  async markLanChatRead(conversationId: string, seq: number): Promise<void> {
    this.lanChatReadSeq.set(conversationId, Math.max(seq, this.lanChatReadSeq.get(conversationId) || 0));
    this.emitLanChatEvent({
      type: "read_updated",
      conversationId,
      lastReadSeq: this.lanChatReadSeq.get(conversationId) || 0,
    });
  }

  openLanChatSocket(onEvent: (event: LanChatEvent) => void): () => void {
    this.lanChatSocketListeners.add(onEvent);
    const timer = window.setTimeout(() => {
      onEvent({ type: "snapshot", status: this.buildLanChatStatus() });
    }, 0);
    return () => {
      window.clearTimeout(timer);
      this.lanChatSocketListeners.delete(onEvent);
    };
  }

  async updateBotCli(botAlias: string, cliType: string, cliPath: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    const next = {
      ...current,
      cliType: cliType as BotSummary["cliType"],
      cliPath: cliPath.trim(),
    };
    this.bots.set(botAlias, next);
    return this.getBotSummary(botAlias);
  }

  async updateBotExecutionConfig(botAlias: string, input: BotExecutionConfigInput): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    this.bots.set(botAlias, {
      ...current,
      supportedExecutionModes: input.supportedExecutionModes,
      defaultExecutionMode: input.defaultExecutionMode,
      nativeAgent: this.normalizeNativeAgentConfig(input.nativeAgent, current.nativeAgent),
    });
    return this.getBotSummary(botAlias);
  }

  async updateBotWorkdir(
    botAlias: string,
    workingDir: string,
    options: UpdateBotWorkdirOptions = {},
  ): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    if (current.botMode === "assistant") {
      throw new Error("assistant 型 Bot 不允许修改默认工作目录");
    }
    const nextDir = workingDir.trim();
    const historyCount = this.ensureAgents(botAlias)
      .reduce((count, agent) => count + this.getAgentMessages(botAlias, agent.id).length, 0);
    if (!options.forceReset && historyCount > 0) {
      throw new WebApiClientError("切换工作目录会丢失当前会话，确认后重试", {
        status: 409,
        code: "workdir_change_requires_reset",
        data: {
          currentWorkingDir: current.workingDir,
          requestedWorkingDir: nextDir,
          historyCount,
          messageCount: historyCount,
          botMode: current.botMode || "cli",
        },
      });
    }
    this.workdirOverrides.set(botAlias, nextDir);
    this.currentPaths.set(botAlias, nextDir);
    this.bots.set(botAlias, {
      ...current,
      workingDir: nextDir,
    });
    return this.getBotSummary(botAlias);
  }

  async updateBotAvatar(botAlias: string, avatarName: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    this.bots.set(botAlias, {
      ...current,
      avatarName: avatarName.trim(),
    });
    return this.getBotSummary(botAlias);
  }

  async updateBotPromptPresets(botAlias: string, presets: PromptPreset[]): Promise<BotSummary> {
    if (!this.hasAdminOps()) {
      throw new WebApiClientError("无权保存提示词预设", { status: 403, code: "forbidden" });
    }
    const current = this.getBotSummary(botAlias);
    this.bots.set(botAlias, {
      ...current,
      promptPresets: clonePromptPresets(presets),
    });
    return this.getBotSummary(botAlias);
  }

  async updateGlobalPromptPresets(presets: PromptPreset[]): Promise<PromptPreset[]> {
    if (!this.hasAdminOps()) {
      throw new WebApiClientError("无权保存提示词预设", { status: 403, code: "forbidden" });
    }
    this.globalPromptPresets = clonePromptPresets(presets);
    return clonePromptPresets(this.globalPromptPresets);
  }

  async listAssistantProposals(botAlias: string, status?: string): Promise<AssistantProposal[]> {
    return this.getAssistantProposals(botAlias).filter((item) => !status || item.status === status);
  }

  async listAssistantUpgradeTargets(botAlias: string): Promise<AssistantUpgradeTarget[]> {
    this.ensureAssistantOpsState(botAlias);
    return Array.from(this.bots.keys()).sort().map((alias) => this.buildMockUpgradeTarget(alias));
  }

  async getAssistantProposal(botAlias: string, proposalId: string): Promise<AssistantProposalDetail> {
    const proposal = this.getAssistantProposals(botAlias).find((item) => item.id === proposalId);
    if (!proposal) {
      throw new WebApiClientError("proposal 不存在", { status: 404, code: "proposal_not_found" });
    }
    const key = this.assistantProposalKey(botAlias, proposalId);
    const log = this.assistantProposalApplyLogs.get(key);
    const patchMetadata = this.getAssistantPatchMetadata(botAlias, proposalId);
    const patchDiffText = this.assistantProposalPatchDiffs.get(key) || "";
    const proposalDiffText = this.assistantProposalDiffs.get(key) || "";
    const diffText = patchDiffText || proposalDiffText;
    const diffSource = patchMetadata
      ? `upgrades/${patchMetadata.state}/${proposalId}.patch`
      : (proposalDiffText ? `proposals/${proposalId}.diff` : "");
    const upgrade = this.buildAssistantUpgradeState(botAlias, proposal);
    return {
      proposal,
      diff: {
        available: Boolean(diffText),
        source: diffSource,
        text: diffText,
        files: parseMockAssistantDiffFiles(diffText),
      },
      apply: {
        available: upgrade.canApply || upgrade.canDryRun,
        applied: proposal.status === "applied",
        lastError: log?.status === "failed" ? (log.error || "") : "",
        lastErrorAt: log?.status === "failed" ? (log.failedAt || "") : "",
        lastErrorLogPath: log?.status === "failed" ? `upgrades/applied/${proposalId}.last-error.json` : "",
      },
      upgrade,
      generationLog: {
        available: Boolean(patchMetadata),
        source: patchMetadata ? `upgrades/logs/${proposalId}.generate.jsonl` : "",
        items: patchMetadata ? [
          {
            event: "started",
            createdAt: patchMetadata.generatedAt,
            status: "",
            message: "",
            error: "",
            code: "",
            raw: { event: "started", created_at: patchMetadata.generatedAt, proposal_id: proposalId },
          },
          {
            event: patchMetadata.generator.status === "failed" ? "failed" : "succeeded",
            createdAt: patchMetadata.generatedAt,
            status: patchMetadata.generator.status,
            message: "",
            error: "",
            code: "",
            raw: { event: patchMetadata.generator.status === "failed" ? "failed" : "succeeded", status: patchMetadata.generator.status },
          },
        ] : [],
      },
    };
  }

  async getAssistantProposalApplyLog(botAlias: string, proposalId: string): Promise<AssistantUpgradeApplyLog> {
    const key = this.assistantProposalKey(botAlias, proposalId);
    const log = this.assistantProposalApplyLogs.get(key);
    if (!log) {
      throw new WebApiClientError("apply 日志不存在", { status: 404, code: "assistant_upgrade_log_not_found" });
    }
    return { ...log };
  }

  async approveAssistantProposal(botAlias: string, proposalId: string): Promise<AssistantProposal> {
    const items = this.getAssistantProposals(botAlias);
    const next = items.map((item) => (
      item.id === proposalId
        ? {
            ...item,
            status: "approved",
            reviewedBy: "127.0.0.1",
            reviewedAt: new Date().toISOString(),
          }
        : item
    ));
    const updated = next.find((item) => item.id === proposalId);
    if (!updated) {
      throw new WebApiClientError("proposal 不存在", { status: 404, code: "proposal_not_found" });
    }
    this.assistantProposals.set(botAlias, next);
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.proposal.approve",
      resource: "proposal",
      resourceId: proposalId,
      requestSummary: { proposalId },
      path: `/api/admin/bots/${botAlias}/assistant/proposals/${proposalId}/approve`,
    });
    return updated;
  }

  async generateAssistantProposalPatch(
    botAlias: string,
    proposalId: string,
    input: { targetAlias: string; regenerate?: boolean },
  ): Promise<AssistantPatchMetadata> {
    const proposal = this.getAssistantProposals(botAlias).find((item) => item.id === proposalId);
    if (!proposal) {
      throw new WebApiClientError("proposal 不存在", { status: 404, code: "proposal_not_found" });
    }
    if (proposal.status !== "approved") {
      throw new WebApiClientError("proposal 尚未批准", { status: 409, code: "proposal_not_approved" });
    }
    const target = this.buildMockUpgradeTarget(input.targetAlias);
    if (!target.available) {
      throw new WebApiClientError(
        target.reason === "upgrade_target_dirty" ? "目标仓库不干净，先提交或清理改动" : "目标工程不可用",
        {
          status: 409,
          code: target.reason || "upgrade_target_unavailable",
          data: { dirtyPaths: target.dirtyPaths },
        },
      );
    }
    const key = this.assistantProposalKey(botAlias, proposalId);
    const diffText = [
      "diff --git a/bot/assistant_memory_recall.py b/bot/assistant_memory_recall.py",
      "@@ -20,3 +20,8 @@",
      " def recall_assistant_memories(...):",
      "+    emit_audit('memory_recall')",
      "+    return []",
      "",
      "diff --git a/bot/assistant_memory_store.py b/bot/assistant_memory_store.py",
      "@@ -40,2 +40,5 @@",
      "+def record_recall_trace(...):",
      "+    return None",
      "",
    ].join("\n");
    this.assistantProposalPatchDiffs.set(key, diffText);
    const metadata: AssistantPatchMetadata = {
      id: proposalId,
      proposalId,
      state: "pending",
      lifecycle: "pending",
      chatConclusion: [
        "patch 已生成",
        `目标工程: ${target.alias}`,
        "变更文件: 2",
      ].join("\n"),
      targetAlias: target.alias,
      targetWorkingDir: target.workingDir,
      targetRepoRoot: target.repoRoot,
      baseCommit: target.head,
      worktreePath: `${botAlias}\\.assistant\\upgrades\\worktrees\\${proposalId}`,
      patchPath: `upgrades/pending/${proposalId}.patch`,
      generatedAt: new Date().toISOString(),
      generatedBy: String(this.session.userId || "1001"),
      generator: {
        cliType: target.cliType,
        cliPath: target.cliPath,
        status: "succeeded",
        elapsedSeconds: 3,
      },
      dryRun: {
        ok: false,
        checkedAt: "",
        stdout: "",
        stderr: "",
        patchPath: "",
        repoRoot: "",
      },
      sensitiveHits: [],
      changedFiles: [
        "bot/assistant_memory_recall.py",
        "bot/assistant_memory_store.py",
      ],
      additions: 5,
      deletions: 0,
    };
    this.assistantProposalPatchMetadata.set(key, metadata);
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.proposal.patch.generate",
      resource: "proposal",
      resourceId: proposalId,
      requestSummary: { proposalId, targetAlias: input.targetAlias, regenerate: Boolean(input.regenerate) },
      path: `/api/admin/bots/${botAlias}/assistant/proposals/${proposalId}/patch`,
    });
    return metadata;
  }

  async generateAssistantProposalPatchStream(
    botAlias: string,
    proposalId: string,
    input: { targetAlias: string; regenerate?: boolean },
    handlers?: AssistantPatchGenerationHandlers,
  ): Promise<AssistantPatchMetadata> {
    handlers?.onStatus?.({ phase: "setup", message: "准备生成", lifecycle: "running" });
    handlers?.onLog?.("开始生成 patch");
    handlers?.onTrace?.({
      kind: "tool_call",
      summary: "git worktree add",
      toolName: "git",
      callId: "call_git_worktree_add",
    });
    handlers?.onTrace?.({
      kind: "tool_result",
      summary: "Exit code: 0\nWall time: 1s",
      toolName: "git",
      callId: "call_git_worktree_add",
    });
    return this.generateAssistantProposalPatch(botAlias, proposalId, input);
  }

  async approveAssistantProposalPatch(botAlias: string, proposalId: string): Promise<AssistantPatchMetadata> {
    const key = this.assistantProposalKey(botAlias, proposalId);
    const current = this.getAssistantPatchMetadata(botAlias, proposalId);
    if (!current) {
      throw new WebApiClientError("pending patch 不存在", { status: 404, code: "pending_patch_not_found" });
    }
    if (current.state !== "pending") {
      return current;
    }
    const next: AssistantPatchMetadata = {
      ...current,
      state: "approved",
      lifecycle: "approved",
      patchPath: `upgrades/approved/${proposalId}.patch`,
      approvedBy: String(this.session.userId || "1001"),
      approvedAt: new Date().toISOString(),
    };
    this.assistantProposalPatchMetadata.set(key, next);
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.proposal.patch.approve",
      resource: "proposal",
      resourceId: proposalId,
      requestSummary: { proposalId },
      path: `/api/admin/bots/${botAlias}/assistant/proposals/${proposalId}/patch/approve`,
    });
    return next;
  }

  async rejectAssistantProposal(botAlias: string, proposalId: string): Promise<AssistantProposal> {
    const items = this.getAssistantProposals(botAlias);
    const next = items.map((item) => (
      item.id === proposalId
        ? {
            ...item,
            status: "rejected",
            reviewedBy: "127.0.0.1",
            reviewedAt: new Date().toISOString(),
          }
        : item
    ));
    const updated = next.find((item) => item.id === proposalId);
    if (!updated) {
      throw new WebApiClientError("proposal 不存在", { status: 404, code: "proposal_not_found" });
    }
    this.assistantProposals.set(botAlias, next);
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.proposal.reject",
      resource: "proposal",
      resourceId: proposalId,
      requestSummary: { proposalId },
      path: `/api/admin/bots/${botAlias}/assistant/proposals/${proposalId}/reject`,
    });
    return updated;
  }

  async applyAssistantUpgrade(botAlias: string, proposalId: string): Promise<AssistantUpgradeApplyResult> {
    const items = this.getAssistantProposals(botAlias);
    const proposal = items.find((item) => item.id === proposalId);
    if (!proposal) {
      throw new WebApiClientError("proposal 不存在", { status: 404, code: "proposal_not_found" });
    }
    if (proposal.status !== "approved") {
      throw new WebApiClientError("proposal 尚未批准", { status: 409, code: "proposal_not_approved" });
    }
    const patch = this.getAssistantPatchMetadata(botAlias, proposalId);
    if (!patch || patch.state !== "approved") {
      throw new WebApiClientError("approved patch 不存在", { status: 404, code: "upgrade_patch_not_found" });
    }
    const appliedAt = new Date().toISOString();
    this.assistantProposals.set(
      botAlias,
      items.map((item) => (item.id === proposalId ? { ...item, status: "applied", appliedAt } : item)),
    );
    this.assistantProposalApplyLogs.set(this.assistantProposalKey(botAlias, proposalId), {
      id: proposalId,
      status: "applied",
      repoRoot: patch.targetRepoRoot,
      patchPath: patch.patchPath,
      appliedAt,
    });
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.upgrade.apply",
      resource: "proposal",
      resourceId: proposalId,
      requestSummary: { proposalId },
      path: `/api/admin/bots/${botAlias}/assistant/upgrades/${proposalId}/apply`,
    });
    return {
      id: proposalId,
      status: "applied",
      patchPath: patch.patchPath,
      repoRoot: patch.targetRepoRoot,
      appliedAt,
    };
  }

  async dryRunAssistantUpgrade(botAlias: string, proposalId: string): Promise<AssistantUpgradeDryRunResult> {
    const proposal = this.getAssistantProposals(botAlias).find((item) => item.id === proposalId);
    if (!proposal) {
      throw new WebApiClientError("proposal 不存在", { status: 404, code: "proposal_not_found" });
    }
    const patch = this.getAssistantPatchMetadata(botAlias, proposalId);
    const checkedAt = new Date().toISOString();
    const result: AssistantUpgradeDryRunResult = {
      ok: proposal.status === "approved" && patch?.state === "approved",
      checkedAt,
      stdout: proposal.status === "approved" && patch?.state === "approved" ? "Patch cleanly applies" : "",
      stderr: proposal.status !== "approved"
        ? "proposal 尚未批准"
        : (patch?.state === "approved" ? "" : "approved patch 不存在"),
      patchPath: patch?.patchPath || "",
      repoRoot: patch?.targetRepoRoot || "",
    };
    if (patch) {
      this.assistantProposalPatchMetadata.set(this.assistantProposalKey(botAlias, proposalId), {
        ...patch,
        dryRun: result,
      });
    }
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.upgrade.dry_run",
      resource: "proposal",
      resourceId: proposalId,
      requestSummary: { proposalId },
      ok: result.ok,
      statusCode: result.ok ? 200 : 409,
      errorCode: result.ok ? undefined : "proposal_not_approved",
      errorMessage: result.ok ? undefined : result.stderr,
      path: `/api/admin/bots/${botAlias}/assistant/upgrades/${proposalId}/dry-run`,
    });
    return result;
  }

  async searchAssistantMemories(
    botAlias: string,
    query: string,
    options: AssistantMemorySearchOptions = {},
  ): Promise<AssistantMemorySearchResult> {
    const needle = query.trim().toLowerCase();
    const items = this.getAssistantMemories(botAlias)
      .filter((item) => options.includeInvalidated || !item.invalidatedAt)
      .filter((item) => !options.kinds?.length || options.kinds.includes(item.kind))
      .filter((item) => !options.scopes?.length || options.scopes.includes(item.scope))
      .filter((item) => {
        if (typeof options.userId !== "number") {
          return true;
        }
        return item.sourceRef?.includes(String(options.userId)) || options.userId === 1001;
      })
      .filter((item) => !needle || `${item.title}\n${item.summary}\n${item.body}`.toLowerCase().includes(needle))
      .slice(0, options.limit || 10);
    return { items };
  }

  async bulkInvalidateAssistantMemories(
    botAlias: string,
    memoryIds: string[],
    reason: string,
  ): Promise<AssistantMemoryBulkInvalidateResult> {
    const now = new Date().toISOString();
    const items = this.getAssistantMemories(botAlias);
    const wanted = new Set(memoryIds);
    let invalidated = 0;
    const missing: string[] = [];
    for (const memoryId of memoryIds) {
      if (!items.some((item) => item.id === memoryId)) {
        missing.push(memoryId);
      }
    }
    this.assistantMemories.set(botAlias, items.map((item) => {
      if (!wanted.has(item.id) || item.invalidatedAt) {
        return item;
      }
      invalidated += 1;
      return {
        ...item,
        invalidatedAt: now,
      };
    }));
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.memory.bulk_invalidate",
      resource: "memory",
      resourceId: "bulk",
      requestSummary: { memoryIds, reason },
      path: `/api/admin/bots/${botAlias}/assistant/memory/bulk-invalidate`,
    });
    return {
      invalidated,
      missing,
      reason,
    };
  }

  async invalidateAssistantMemory(
    botAlias: string,
    memoryId: string,
    reason: string,
  ): Promise<AssistantMemoryInvalidateResult> {
    const now = new Date().toISOString();
    const items = this.getAssistantMemories(botAlias);
    const exists = items.some((item) => item.id === memoryId);
    if (!exists) {
      throw new WebApiClientError("memory 不存在", { status: 404, code: "assistant_memory_not_found" });
    }
    this.assistantMemories.set(
      botAlias,
      items.map((item) => (item.id === memoryId ? { ...item, invalidatedAt: now } : item)),
    );
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.memory.invalidate",
      resource: "memory",
      resourceId: memoryId,
      requestSummary: { memoryId, reason },
      path: `/api/admin/bots/${botAlias}/assistant/memory/${memoryId}/invalidate`,
    });
    return {
      memoryId,
      invalidated: true,
      reason,
    };
  }

  async reindexAssistantMemory(
    botAlias: string,
    _options: { userId?: number; force?: boolean } = {},
  ): Promise<AssistantMemoryReindexResult> {
    this.ensureAssistantOpsState(botAlias);
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.memory.reindex",
      resource: "memory",
      resourceId: "index",
      requestSummary: { ..._options },
      path: `/api/admin/bots/${botAlias}/assistant/memory/reindex`,
    });
    return {
      working: {
        indexedCount: 4,
        memoryIds: ["wm_1", "wm_2", "wm_3", "wm_4"],
      },
      knowledge: {
        indexedCount: 2,
        memoryIds: ["kg_1", "kg_2"],
      },
    };
  }

  async runAssistantMemoryEval(
    botAlias: string,
    input: { userId?: number; cases: AssistantMemoryEvalCase[] },
  ): Promise<AssistantMemoryEvalRun> {
    const createdAt = new Date().toISOString();
    const reportPath = `.assistant/evals/memory/${createdAt.replace(/[-:.]/g, "").slice(0, 15)}Z.json`;
    const report: AssistantMemoryEvalReport = {
      reportPath,
      createdAt,
      metrics: {
        hitAt5: input.cases.length ? 1 : 0,
        staleRecallRate: 0,
      },
      rows: input.cases.map((item) => ({
        query: item.query,
        promptBlock: `<ASSISTANT_MEMORY_RECALL>\n1. [${item.expectedMemoryKind}/user] ${item.expectedHitTerms[0] || item.query}\n</ASSISTANT_MEMORY_RECALL>`,
        hit: true,
        stale: false,
        auditPath: `.assistant/audit/memory/${Date.now()}-${input.userId || 1001}.json`,
      })),
    };
    this.assistantMemoryEvalReports.set(botAlias, [report, ...this.getAssistantMemoryEvalReports(botAlias)]);
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.memory.eval",
      resource: "eval",
      resourceId: "memory",
      requestSummary: { userId: input.userId, cases: input.cases.length },
      path: `/api/admin/bots/${botAlias}/assistant/evals/memory/run`,
    });
    return {
      metrics: report.metrics,
      reportPath,
    };
  }

  async listAssistantMemoryEvalReports(botAlias: string, limit = 10): Promise<AssistantMemoryEvalReport[]> {
    return this.getAssistantMemoryEvalReports(botAlias).slice(0, limit);
  }

  async getAssistantDiagnostics(
    botAlias: string,
    filters: AssistantDiagnosticsFilters = {},
  ): Promise<AssistantPerfDiagnostics> {
    const items = this.getAssistantPerfRecords(botAlias)
      .filter((item) => !filters.source || item.source === filters.source)
      .filter((item) => !filters.status || item.status === filters.status)
      .filter((item) => typeof filters.userId !== "number" || item.userId === filters.userId)
      .filter((item) => !filters.from || item.createdAt >= filters.from)
      .filter((item) => !filters.to || item.createdAt <= filters.to)
      .slice(0, filters.limit || 20);
    return {
      items,
      summary: summarizeMockAssistantDiagnostics(items),
    };
  }

  async listAssistantCronJobs(botAlias: string): Promise<AssistantCronJob[]> {
    return this.getAssistantCronJobs(botAlias);
  }

  async createAssistantCronJob(botAlias: string, input: CreateAssistantCronJobInput): Promise<AssistantCronJob> {
    const current = this.getAssistantCronJobs(botAlias);
    const taskMode = input.task.mode || "standard";
    const job: AssistantCronJob = {
      ...input,
      task: {
        prompt: input.task.prompt,
        mode: taskMode,
        lookbackHours: input.task.lookbackHours ?? 24,
        historyLimit: input.task.historyLimit ?? 40,
        captureLimit: input.task.captureLimit ?? 20,
        deliverMode: input.task.deliverMode ?? (taskMode === "dream" ? "silent" : "chat_handoff"),
      },
      nextRunAt: input.schedule.type === "daily"
        ? "2026-04-17T09:00:00+08:00"
        : "2026-04-16T10:00:00+08:00",
      lastStatus: "",
      lastError: "",
      lastSuccessAt: "",
      pending: false,
      pendingRunId: "",
      coalescedCount: 0,
    };
    this.assistantCronJobs.set(botAlias, [...current.filter((item) => item.id !== job.id), job]);
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.cron.create",
      resource: "cron",
      resourceId: job.id,
      requestSummary: { jobId: job.id, title: job.title },
      path: `/api/admin/bots/${botAlias}/assistant/cron/jobs`,
    });
    return job;
  }

  async updateAssistantCronJob(
    botAlias: string,
    jobId: string,
    input: UpdateAssistantCronJobInput,
  ): Promise<AssistantCronJob> {
    const current = this.getAssistantCronJobs(botAlias);
    const existing = current.find((item) => item.id === jobId);
    if (!existing) {
      throw new Error("任务不存在");
    }
    const updated: AssistantCronJob = {
      ...existing,
      ...(typeof input.enabled === "boolean" ? { enabled: input.enabled } : {}),
      ...(input.title ? { title: input.title } : {}),
      schedule: {
        ...existing.schedule,
        ...(input.schedule || {}),
      },
      task: {
        ...existing.task,
        ...(input.task || {}),
        mode: input.task?.mode || existing.task.mode || "standard",
        lookbackHours: input.task?.lookbackHours ?? existing.task.lookbackHours ?? 24,
        historyLimit: input.task?.historyLimit ?? existing.task.historyLimit ?? 40,
        captureLimit: input.task?.captureLimit ?? existing.task.captureLimit ?? 20,
        deliverMode: input.task?.deliverMode
          ?? existing.task.deliverMode
          ?? ((input.task?.mode || existing.task.mode) === "dream" ? "silent" : "chat_handoff"),
      },
      execution: {
        ...existing.execution,
        ...(input.execution || {}),
      },
    };
    this.assistantCronJobs.set(
      botAlias,
      current.map((item) => (item.id === jobId ? updated : item)),
    );
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.cron.update",
      resource: "cron",
      resourceId: jobId,
      requestSummary: { jobId },
      method: "PATCH",
      path: `/api/admin/bots/${botAlias}/assistant/cron/jobs/${jobId}`,
    });
    return updated;
  }

  async deleteAssistantCronJob(botAlias: string, jobId: string): Promise<void> {
    this.assistantCronJobs.set(
      botAlias,
      this.getAssistantCronJobs(botAlias).filter((item) => item.id !== jobId),
    );
    this.assistantCronRuns.delete(this.cronRunKey(botAlias, jobId));
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.cron.delete",
      resource: "cron",
      resourceId: jobId,
      requestSummary: { jobId },
      method: "DELETE",
      path: `/api/admin/bots/${botAlias}/assistant/cron/jobs/${jobId}`,
    });
  }

  async runAssistantCronJob(botAlias: string, jobId: string): Promise<AssistantCronRunRequestResult> {
    const job = this.getAssistantCronJobs(botAlias).find((item) => item.id === jobId);
    const runId = `run_${Date.now()}`;
    const runs = this.assistantCronRuns.get(this.cronRunKey(botAlias, jobId)) || [];
    this.assistantCronRuns.set(this.cronRunKey(botAlias, jobId), [
      {
        runId,
        jobId,
        triggerSource: "manual",
        scheduledAt: new Date().toISOString(),
        enqueuedAt: new Date().toISOString(),
        startedAt: "",
        finishedAt: "",
        status: "queued",
        elapsedSeconds: 0,
        queueWaitSeconds: 0,
        timedOut: false,
        promptExcerpt: "",
        outputExcerpt: "",
        error: "",
      },
      ...runs,
    ]);
    this.assistantCronJobs.set(
      botAlias,
      this.getAssistantCronJobs(botAlias).map((item) =>
        item.id === jobId
          ? { ...item, pending: true, pendingRunId: runId, lastStatus: "queued" }
          : item,
      ),
    );
    this.pushAssistantAdminAudit(botAlias, {
      action: "assistant.cron.run",
      resource: "cron",
      resourceId: jobId,
      requestSummary: { jobId, runId },
      path: `/api/admin/bots/${botAlias}/assistant/cron/jobs/${jobId}/run`,
    });
    return {
      runId,
      status: "queued",
      taskMode: job?.task.mode || "standard",
      deliverMode: job?.task.deliverMode || "chat_handoff",
    };
  }

  async listAssistantCronRuns(botAlias: string, jobId: string, limit = 5): Promise<AssistantCronRun[]> {
    return (this.assistantCronRuns.get(this.cronRunKey(botAlias, jobId)) || []).slice(0, limit);
  }

  async listAssistantAdminAudit(
    botAlias: string,
    filters: { limit?: number; action?: string; resource?: string; status?: "ok" | "failed" | "" } = {},
  ): Promise<AssistantAdminAuditResult> {
    const items = this.getAssistantAdminAudit(botAlias)
      .filter((item) => !filters.action || item.action === filters.action)
      .filter((item) => !filters.resource || item.target.resource === filters.resource)
      .filter((item) => !filters.status || item.ok === (filters.status === "ok"))
      .slice(0, filters.limit || 20);
    return { items };
  }

  async addBot(input: CreateBotInput): Promise<BotSummary> {
    const alias = input.alias.trim().toLowerCase();
    if (!alias) {
      throw new WebApiClientError("Bot 别名不能为空", { status: 400, code: "bot_alias_required" });
    }
    if (this.bots.has(alias)) {
      throw new WebApiClientError("Bot 已存在", { status: 409, code: "bot_already_exists" });
    }
    const accountId = this.currentAccountId();
    if (!this.isLocalAdminSession()) {
      const ownedBots = this.getOwnedBotsForAccount(accountId);
      const limit = this.adminUsers.get(accountId)?.botCreateLimit || MEMBER_BOT_LIMIT;
      if (ownedBots.length >= limit) {
        throw new WebApiClientError("普通用户最多只能创建 3 个 Bot", { status: 403, code: "bot_quota_exceeded" });
      }
    }
    const bot: BotSummary = {
      alias,
      cliType: input.cliType,
      cliPath: input.cliPath.trim() || defaultCliPathForType(input.cliType),
      botMode: input.botMode,
      status: "running",
      workingDir: input.workingDir.trim(),
      lastActiveText: "运行中",
      avatarName: input.avatarName,
      enabled: true,
      isMain: false,
      serviceStatus: "online",
      activityStatus: "idle",
      busyAgentIds: [],
      busyAgentNames: [],
      busyAgentCount: 0,
      supportedExecutionModes: input.supportedExecutionModes || ["cli"],
      defaultExecutionMode: input.defaultExecutionMode || "cli",
      nativeAgent: this.normalizeNativeAgentConfig(input.nativeAgent),
      cluster: { ...DEFAULT_CLUSTER, modelTiers: { ...DEFAULT_CLUSTER.modelTiers } },
    };
    this.bots.set(alias, bot);
    if (!this.isLocalAdminSession()) {
      this.botOwners.set(alias, accountId);
      this.setAllowedBotsForAccount(accountId, [...this.getAllowedBotsForAccount(accountId), alias]);
    }
    this.currentPaths.set(alias, bot.workingDir);
    this.workdirOverrides.set(alias, bot.workingDir);
    if (bot.botMode === "assistant" && !this.assistantCronJobs.has(alias)) {
      this.assistantCronJobs.set(alias, []);
      this.ensureAssistantOpsState(alias);
    }
    return this.getBotSummary(alias);
  }

  async renameBot(botAlias: string, newAlias: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    const alias = newAlias.trim().toLowerCase();
    if (!alias) {
      throw new WebApiClientError("Bot 别名不能为空", { status: 400, code: "bot_alias_required" });
    }
    if (alias !== botAlias && this.bots.has(alias)) {
      throw new WebApiClientError("Bot 已存在", { status: 409, code: "bot_already_exists" });
    }
    this.bots.delete(botAlias);
    this.bots.set(alias, {
      ...current,
      alias,
    });
    if (this.botOwners.has(botAlias)) {
      const owner = this.botOwners.get(botAlias) || "";
      this.botOwners.delete(botAlias);
      this.botOwners.set(alias, owner);
    }
    for (const [accountId, user] of Array.from(this.adminUsers.entries())) {
      const nextAllowedBots = user.allowedBots.map((item) => (item === botAlias ? alias : item));
      if (nextAllowedBots.some((item, index) => nextAllowedBots.indexOf(item) !== index)) {
        this.setAllowedBotsForAccount(accountId, nextAllowedBots.filter((item, index) => nextAllowedBots.indexOf(item) === index));
      } else if (nextAllowedBots.join("\u0000") !== user.allowedBots.join("\u0000")) {
        this.setAllowedBotsForAccount(accountId, nextAllowedBots);
      }
    }
    this.moveKey(this.currentPaths, botAlias, alias);
    this.moveKey(this.workdirOverrides, botAlias, alias);
    this.moveKey(this.agentsByBot, botAlias, alias);
    this.moveAgentScopedKeys(this.conversationsByBot, botAlias, alias);
    this.moveAgentScopedKeys(this.activeConversationByBot, botAlias, alias);
    this.moveKey(this.gitOverviews, botAlias, alias);
    this.moveKey(this.gitIdentityConfigs, botAlias, alias);
    if (this.gitSmartCommitActiveJobs.has(botAlias)) {
      const activeJobId = this.gitSmartCommitActiveJobs.get(botAlias) || "";
      this.gitSmartCommitActiveJobs.delete(botAlias);
      this.gitSmartCommitActiveJobs.set(alias, activeJobId);
      const activeJob = this.gitSmartCommitJobs.get(activeJobId);
      if (activeJob) {
        this.gitSmartCommitJobs.set(activeJobId, { ...activeJob, alias });
      }
    }
    for (const [jobId, job] of Array.from(this.gitSmartCommitJobs.entries())) {
      if (job.alias === botAlias) {
        this.gitSmartCommitJobs.set(jobId, { ...job, alias });
      }
    }
    this.moveKey(this.assistantCronJobs, botAlias, alias);
    this.moveKey(this.assistantProposals, botAlias, alias);
    this.moveKey(this.assistantMemories, botAlias, alias);
    this.moveKey(this.assistantMemoryEvalReports, botAlias, alias);
    this.moveKey(this.assistantPerfRecords, botAlias, alias);
    this.moveKey(this.assistantAdminAudit, botAlias, alias);
    for (const [key, value] of Array.from(this.assistantProposalDiffs.entries())) {
      if (!key.startsWith(`${botAlias}:`)) {
        continue;
      }
      this.assistantProposalDiffs.delete(key);
      this.assistantProposalDiffs.set(`${alias}:${key.slice(botAlias.length + 1)}`, value);
    }
    for (const [key, value] of Array.from(this.assistantProposalPatchDiffs.entries())) {
      if (!key.startsWith(`${botAlias}:`)) {
        continue;
      }
      this.assistantProposalPatchDiffs.delete(key);
      this.assistantProposalPatchDiffs.set(`${alias}:${key.slice(botAlias.length + 1)}`, value);
    }
    for (const [key, value] of Array.from(this.assistantProposalPatchMetadata.entries())) {
      if (!key.startsWith(`${botAlias}:`)) {
        continue;
      }
      this.assistantProposalPatchMetadata.delete(key);
      this.assistantProposalPatchMetadata.set(`${alias}:${key.slice(botAlias.length + 1)}`, value);
    }
    for (const [key, value] of Array.from(this.assistantProposalApplyLogs.entries())) {
      if (!key.startsWith(`${botAlias}:`)) {
        continue;
      }
      this.assistantProposalApplyLogs.delete(key);
      this.assistantProposalApplyLogs.set(`${alias}:${key.slice(botAlias.length + 1)}`, value);
    }
    for (const [key, value] of Array.from(this.assistantCronRuns.entries())) {
      if (!key.startsWith(`${botAlias}:`)) {
        continue;
      }
      this.assistantCronRuns.delete(key);
      this.assistantCronRuns.set(`${alias}:${key.slice(botAlias.length + 1)}`, value);
    }
    return this.getBotSummary(alias);
  }

  async removeBot(botAlias: string, _options: { deleteHistory?: boolean } = {}): Promise<void> {
    if (botAlias === "main") {
      return;
    }
    this.bots.delete(botAlias);
    this.botOwners.delete(botAlias);
    for (const accountId of Array.from(this.adminUsers.keys())) {
      const filtered = this.getAllowedBotsForAccount(accountId).filter((item) => item !== botAlias);
      this.setAllowedBotsForAccount(accountId, filtered);
    }
    this.currentPaths.delete(botAlias);
    this.workdirOverrides.delete(botAlias);
    this.gitOverviews.delete(botAlias);
    this.gitIdentityConfigs.delete(botAlias);
    this.gitSmartCommitActiveJobs.delete(botAlias);
    for (const [jobId, job] of Array.from(this.gitSmartCommitJobs.entries())) {
      if (job.alias === botAlias) {
        this.gitSmartCommitJobs.delete(jobId);
      }
    }
    this.assistantCronJobs.delete(botAlias);
    this.assistantProposals.delete(botAlias);
    this.assistantMemories.delete(botAlias);
    this.assistantMemoryEvalReports.delete(botAlias);
    this.assistantPerfRecords.delete(botAlias);
    this.assistantAdminAudit.delete(botAlias);
    for (const key of Array.from(this.assistantProposalDiffs.keys())) {
      if (key.startsWith(`${botAlias}:`)) {
        this.assistantProposalDiffs.delete(key);
      }
    }
    for (const key of Array.from(this.assistantProposalPatchDiffs.keys())) {
      if (key.startsWith(`${botAlias}:`)) {
        this.assistantProposalPatchDiffs.delete(key);
      }
    }
    for (const key of Array.from(this.assistantProposalPatchMetadata.keys())) {
      if (key.startsWith(`${botAlias}:`)) {
        this.assistantProposalPatchMetadata.delete(key);
      }
    }
    for (const key of Array.from(this.assistantProposalApplyLogs.keys())) {
      if (key.startsWith(`${botAlias}:`)) {
        this.assistantProposalApplyLogs.delete(key);
      }
    }
    for (const key of Array.from(this.assistantCronRuns.keys())) {
      if (key.startsWith(`${botAlias}:`)) {
        this.assistantCronRuns.delete(key);
      }
    }
  }

  async startBot(botAlias: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    this.bots.set(botAlias, {
      ...current,
      status: "running",
      lastActiveText: "运行中",
      enabled: true,
      serviceStatus: "online",
    });
    return this.getBotSummary(botAlias);
  }

  async stopBot(botAlias: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    this.bots.set(botAlias, {
      ...current,
      status: "offline",
      lastActiveText: "离线",
      enabled: false,
      serviceStatus: "offline",
      activityStatus: "idle",
      busyAgentIds: [],
      busyAgentNames: [],
      busyAgentCount: 0,
    });
    return this.getBotSummary(botAlias);
  }

  async listAvatarAssets(): Promise<AvatarAsset[]> {
    return [...this.avatarAssets];
  }

  async getCliParams(botAlias: string): Promise<CliParamsPayload> {
    return buildMockCliParams(this.getBotSummary(botAlias).cliType);
  }

  async getNativeAgentModels(botAlias: string): Promise<NativeAgentModelsPayload> {
    const bot = this.getBotSummary(botAlias);
    return {
      items: this.nativeAgentModels.map((item) => ({ ...item })),
      selectedModel: bot.nativeAgent?.model || this.nativeAgentModels[0]?.id || "",
    };
  }

  async updateNativeAgentModel(botAlias: string, model: string): Promise<NativeAgentModelUpdateResult> {
    const bot = this.getBotSummary(botAlias);
    const nextNativeAgent = {
      ...(bot.nativeAgent || { provider: "", model: "", opencodeAgent: "" }),
      model,
    };
    this.bots.set(bot.alias, {
      ...bot,
      nativeAgent: nextNativeAgent,
    });
    return {
      items: this.nativeAgentModels.map((item) => ({ ...item })),
      selectedModel: model,
      bot: this.getBotSummary(bot.alias),
    };
  }

  async updateCliParam(botAlias: string, key: string, value: unknown): Promise<CliParamsPayload> {
    const payload = await this.getCliParams(botAlias);
    const nextValue = key === "model" && value === "none" ? null : value;
    return {
      ...payload,
      params: {
        ...payload.params,
        [key]: nextValue,
      },
    };
  }

  async resetCliParams(botAlias: string): Promise<CliParamsPayload> {
    return this.getCliParams(botAlias);
  }

  async getTunnelStatus(): Promise<TunnelSnapshot> {
    return {
      mode: "cloudflare_quick",
      status: "running",
      source: "quick_tunnel",
      publicUrl: "https://demo.trycloudflare.com",
      localUrl: "http://127.0.0.1:8765",
      lastError: "",
      verified: true,
      pid: 1234,
      fixedPublicForwardEnabled: false,
      nodeId: "demo-node",
      basePath: "",
      frpcStatus: "",
      frpcPid: null,
      frpcLastError: "",
      heartbeatStatus: "",
      heartbeatLastAt: "",
      heartbeatLastError: "",
    };
  }

  async startTunnel(): Promise<TunnelSnapshot> {
    return this.getTunnelStatus();
  }

  async stopTunnel(): Promise<TunnelSnapshot> {
    return {
      mode: "cloudflare_quick",
      status: "stopped",
      source: "quick_tunnel",
      publicUrl: "",
      localUrl: "http://127.0.0.1:8765",
      lastError: "",
      verified: false,
      pid: null,
      fixedPublicForwardEnabled: false,
      nodeId: "demo-node",
      basePath: "",
      frpcStatus: "",
      frpcPid: null,
      frpcLastError: "",
      heartbeatStatus: "",
      heartbeatLastAt: "",
      heartbeatLastError: "",
    };
  }

  async restartTunnel(): Promise<TunnelSnapshot> {
    return this.getTunnelStatus();
  }

}

export async function streamAssistantReply(onChunk: (chunk: string) => void) {
  const chunks = ["我先看一下问题。", "已经定位到可能原因。", "建议先检查 session 与工作目录。"];
  for (const chunk of chunks) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    onChunk(chunk);
  }
}
