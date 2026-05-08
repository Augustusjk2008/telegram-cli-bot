import { WebApiClientError } from "./types";
import type {
  AccountRole,
  AppUpdateDownloadProgress,
  AppUpdatePackageKind,
  AppUpdateStatus,
  AssistantCronJob,
  AssistantCronRun,
  AssistantCronRunRequestResult,
  AssistantAdminAuditResult,
  AssistantDiagnosticsFilters,
  AssistantMemoryBulkInvalidateResult,
  AssistantMemoryEvalReport,
  AssistantMemoryEvalRun,
  AssistantMemoryInvalidateResult,
  AssistantMemoryReindexResult,
  AssistantMemorySearchOptions,
  AssistantMemorySearchResult,
  AssistantPatchGenerationHandlers,
  AssistantPatchMetadata,
  AssistantPerfDiagnostics,
  AssistantPerfRecord,
  AssistantProposal,
  AssistantProposalDetail,
  AssistantRuntimePendingRun,
  AssistantRuntimeSnapshot,
  AssistantUpgradeApplyLog,
  AssistantUpgradeApplyResult,
  AssistantUpgradeDryRunResult,
  AssistantUpgradeState,
  AssistantUpgradeTarget,
  Capability,
  AgentInput,
  AgentListResult,
  AgentMutationResult,
  AgentScopedOptions,
  AgentSummary,
  CreateAssistantCronJobInput,
  GitActionResult,
  GitBlamePayload,
  GitBranchList,
  GitCommitSummary,
  GitDiffPayload,
  GitProxySettings,
  GitOverview,
  GitStashList,
  GitTreeStatus,
  BotOverview,
  BotStatus,
  BotSummary,
  ChatAttachmentDeleteResult,
  ChatAttachmentUploadResult,
  ChatSendOptions,
  ChatMessage,
  ChatTraceDetails,
  ChatMessageMetaInfo,
  ChatStatusUpdate,
  ChatTraceEvent,
  CliParamsPayload,
  CliType,
  AgentClusterConfig,
  BotClusterConfig,
  ClusterConfigUpdateInput,
  ClusterConfigUpdateResult,
  ClusterBundleApplyResult,
  ClusterBundleDiff,
  ClusterBundlePreviewResult,
  ClusterBundleSchemaResult,
  ClusterConfigBundle,
  ClusterConfigBundleAgent,
  ClusterMcpState,
  ClusterMcpTargetStatus,
  ClusterModelTiers,
  ClusterSetupPrepareResult,
  ClusterStatus,
  ClusterAgentTask,
  ClusterTaskStatus,
  ClusterTemplateListResult,
  ClusterTemplateSummary,
  ConversationListResult,
  ConversationSelectResult,
  ConversationSummary,
  CreateBotInput,
  DebugBreakpoint,
  DebugFrame,
  DebugProfile,
  DebugScope,
  DebugState,
  DebugVariable,
  DirectoryListing,
  AvatarAsset,
  FileOpenTarget,
  FileTreeRevealResult,
  FileCopyResult,
  FileCreateResult,
  FileEntry,
  FileMoveResult,
  FileReadMode,
  FileReadResult,
  FileRenameResult,
  FileWriteResult,
  PluginActionInvokeInput,
  PluginActionResult,
  InstallablePluginSummary,
  PluginViewWindowRequest,
  PluginViewWindowPayload,
  PluginRenderResult,
  PluginSummary,
  PluginUpdateInput,
  PersistentTerminalSnapshot,
  PublicHostInfo,
  RegisterCodeCreateResult,
  RegisterCodeItem,
  RunningReply,
  SessionState,
  TerminalActionRunInput,
  TerminalActionRunResult,
  TerminalActionsConfig,
  TerminalActionsEditableConfig,
  TunnelSnapshot,
  UpdateAssistantCronJobInput,
  UpdateBotWorkdirOptions,
  WorkspaceDefinitionResult,
  WorkspaceOutlineResult,
  WorkspaceQuickOpenResult,
  WorkspaceSearchResult,
  WorkdirChangeConflict,
  HistoryDeltaResult,
} from "./types";
import type { WebBotClient } from "./webBotClient";

type JsonEnvelope<T> = {
  ok: boolean;
  data: T;
  error?: {
    code?: string;
    message?: string;
    data?: unknown;
  };
};

type RawBotSummary = {
  alias: string;
  cli_type: CliType;
  cli_path?: string;
  status: string;
  is_processing?: boolean;
  service_status?: string;
  serviceStatus?: string;
  activity_status?: string;
  activityStatus?: string;
  busy_agent_ids?: string[];
  busyAgentIds?: string[];
  busy_agent_names?: string[];
  busyAgentNames?: string[];
  busy_agent_count?: number;
  busyAgentCount?: number;
  agents?: RawAgentSummary[];
  assistant_runtime?: RawAssistantRuntimeSnapshot | null;
  working_dir: string;
  avatar_name?: string;
  bot_mode?: string;
  enabled?: boolean;
  is_main?: boolean;
  cluster?: Record<string, unknown>;
};

type RawAgentSummary = {
  id?: string;
  name?: string;
  system_prompt?: string;
  systemPrompt?: string;
  enabled?: boolean;
  is_main?: boolean;
  isMain?: boolean;
  is_processing?: boolean;
  isProcessing?: boolean;
  message_count?: number;
  messageCount?: number;
  active_conversation_id?: string;
  activeConversationId?: string;
  created_at?: string;
  createdAt?: string;
  updated_at?: string;
  updatedAt?: string;
  cluster?: Record<string, unknown>;
};

type RawAvatarAsset = {
  name: string;
  url: string;
};

type RawPublicHostInfo = {
  username?: string;
  operating_system?: string;
  hardware_platform?: string;
  hardware_spec?: string;
};

type RawHealthResponse = {
  ok?: boolean;
  service?: string;
  web_enabled?: boolean;
  host?: string;
  port?: number;
  host_info?: RawPublicHostInfo;
};

type RawHistoryItem = {
  id?: string;
  timestamp?: string;
  created_at?: string;
  role: "user" | "assistant" | "system";
  content: string;
  state?: ChatMessage["state"];
  elapsed_seconds?: number;
  meta?: RawChatMessageMeta;
};

type RawConversationSummary = {
  id?: string;
  bot_alias?: string;
  agent_id?: string;
  bot_mode?: string;
  cli_type?: string;
  working_dir?: string;
  status?: string;
  native_provider?: string;
  native_session_id?: string;
  title?: string;
  last_message_preview?: string;
  message_count?: number;
  pinned?: boolean;
  active?: boolean;
  created_at?: string;
  updated_at?: string;
};

type RawChatTraceEvent = {
  kind?: string;
  summary?: string;
  source?: string;
  raw_type?: string;
  title?: string;
  tool_name?: string;
  call_id?: string;
  payload?: unknown;
};

type RawChatMessageMeta = {
  completion_state?: string;
  summary_kind?: string;
  trace_version?: number;
  trace_count?: number;
  tool_call_count?: number;
  process_count?: number;
  trace?: RawChatTraceEvent[];
  native_source?: {
    provider?: string;
    session_id?: string;
  };
};

type RawChatTraceDetails = {
  message_id?: string;
  trace_count?: number;
  tool_call_count?: number;
  process_count?: number;
  trace?: RawChatTraceEvent[];
};

type RawClusterAgentTask = {
  task_id?: string;
  agent_id?: string;
  status?: string;
  model_tier?: string;
  allow_write?: boolean;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  output?: string;
  error?: string;
};

type RawClusterTaskStatus = {
  tasks?: RawClusterAgentTask[];
  queued_count?: number;
  running_count?: number;
  completed_count?: number;
  failed_count?: number;
  pending_count?: number;
};

type RawActiveClusterRun = {
  run_id?: string;
  status?: string;
  tasks?: RawClusterTaskStatus;
};

type RawClusterTemplateSummary = {
  id?: string;
  name?: string;
  description?: string;
  agent_count?: number;
  write_agent_count?: number;
  max_parallel_agents?: number;
};

type RawFileEntry = {
  name: string;
  is_dir: boolean;
  size?: number;
  updated_at?: string;
};

type RawFileReadResult = {
  content: string;
  mode?: FileReadMode;
  working_dir?: string;
  file_size_bytes?: number;
  is_full_content?: boolean;
  last_modified_ns?: string | number;
  preview_kind?: "text" | "image";
  content_type?: string;
  content_base64?: string;
};

type RawFileWriteResult = {
  path: string;
  file_size_bytes: number;
  last_modified_ns: string | number;
};

type RawFileCreateResult = {
  path: string;
  file_size_bytes: number;
  last_modified_ns: string | number;
};

type RawFileCopyResult = {
  source_path: string;
  path: string;
  file_size_bytes: number;
  last_modified_ns: string | number;
};

type RawFileRenameResult = {
  old_path: string;
  path: string;
};

type RawFileMoveResult = {
  old_path: string;
  path: string;
};

type RawChatAttachmentUploadResult = {
  filename: string;
  saved_path: string;
  size: number;
};

type RawChatAttachmentDeleteResult = {
  filename: string;
  saved_path: string;
  existed: boolean;
  deleted: boolean;
};

type RawPersistentTerminalSnapshot = {
  started: boolean;
  closed: boolean;
  cwd: string;
  pty_mode?: boolean | null;
  connection_text?: string;
  last_seq?: number;
};

type RawTerminalActionRunResult = {
  actionId: string;
  command: string;
  cwd: string;
  startedTerminal: boolean;
  snapshot: RawPersistentTerminalSnapshot;
};

type RawRunningReply = {
  user_text?: string;
  preview_text?: string;
  started_at: string;
  updated_at?: string;
};

type RawAuthSession = {
  user_id?: number;
  account_id?: string;
  username?: string;
  role?: AccountRole;
  capabilities?: Capability[];
  current_bot_alias?: string;
  current_path?: string;
  is_logged_in?: boolean;
  token?: string;
  token_protected?: boolean;
  allowed_user_ids?: number[];
};

type RawRegisterCodeUsage = {
  used_at: string;
  used_by: string;
};

type RawRegisterCodeItem = {
  code_id: string;
  code_preview: string;
  disabled: boolean;
  max_uses: number;
  used_count: number;
  remaining_uses: number;
  created_at: string;
  created_by: string;
  last_used_at: string;
  usage: RawRegisterCodeUsage[];
};

type RawRegisterCodeCreateResult = RawRegisterCodeItem & {
  code: string;
};

type RawCliParamsPayload = {
  cli_type: CliType;
  params: Record<string, unknown>;
  defaults: Record<string, unknown>;
  schema: Record<string, {
    type: "boolean" | "string" | "number" | "string_list";
    enum?: string[];
    description?: string;
    nullable?: boolean;
    integer?: boolean;
  }>;
};

const RESTART_SERVICE_REQUEST_TIMEOUT_MS = 4000;

type RawTunnelSnapshot = {
  mode: "disabled" | "cloudflare_quick" | "manual";
  status: "stopped" | "starting" | "running" | "error";
  source: "disabled" | "quick_tunnel" | "manual_config";
  public_url?: string;
  local_url?: string;
  last_error?: string;
  pid?: number | null;
};

type RawGitChangedFile = {
  path: string;
  status: string;
  staged: boolean;
  unstaged: boolean;
  untracked: boolean;
};

type RawGitCommitSummary = {
  hash: string;
  short_hash: string;
  author_name: string;
  authored_at: string;
  subject: string;
};

type RawGitOverview = {
  repo_found: boolean;
  can_init: boolean;
  working_dir: string;
  repo_path: string;
  repo_name: string;
  current_branch: string;
  is_clean: boolean;
  ahead_count: number;
  behind_count: number;
  changed_files: RawGitChangedFile[];
  recent_commits: RawGitCommitSummary[];
};

type RawGitTreeStatus = {
  repo_found: boolean;
  working_dir: string;
  repo_path: string;
  items: Record<string, "added" | "modified" | "ignored">;
};

type RawGitDiffPayload = {
  path: string;
  staged: boolean;
  diff: string;
};

type RawGitActionResult = {
  message: string;
  overview: RawGitOverview;
};

type RawGitBranchSummary = {
  name: string;
  current: boolean;
  upstream?: string;
  short_hash?: string;
  subject?: string;
};

type RawGitBranchList = {
  current_branch?: string;
  branches?: RawGitBranchSummary[];
};

type RawGitStashEntry = {
  ref: string;
  hash?: string;
  created_at?: string;
  message?: string;
};

type RawGitStashList = {
  items?: RawGitStashEntry[];
};

type RawGitBlameLine = {
  line: number;
  commit?: string;
  short_commit?: string;
  author_name?: string;
  author_mail?: string;
  authored_at?: string;
  summary?: string;
  content?: string;
};

type RawGitBlamePayload = {
  path?: string;
  lines?: RawGitBlameLine[];
};

type RawGitProxySettings = {
  address?: string;
  port?: string;
};

type RawAppUpdateStatus = {
  current_version: string;
  current_package_kind?: AppUpdatePackageKind;
  update_enabled: boolean;
  update_channel: "release";
  last_checked_at?: string;
  last_available_version?: string;
  last_available_release_url?: string;
  last_available_notes?: string;
  pending_update_version?: string;
  pending_update_path?: string;
  pending_update_notes?: string;
  pending_update_platform?: string;
  pending_update_package_kind?: AppUpdatePackageKind;
  update_last_error?: string;
};

type RawAppUpdateDownloadProgress = {
  phase?: string;
  downloaded_bytes?: number;
  total_bytes?: number;
  percent?: number;
  message?: string;
};

type RawAssistantProposal = {
  id: string;
  kind: string;
  title: string;
  body: string;
  status: string;
  created_at?: string;
  reviewed_by?: string;
  reviewed_at?: string;
  applied_at?: string;
};

type RawAssistantUpgradeApplyState = {
  available?: boolean;
  applied?: boolean;
  last_error?: string;
  last_error_at?: string;
  last_error_log_path?: string;
};

type RawAssistantUpgradeTarget = {
  alias?: string;
  working_dir?: string;
  repo_root?: string;
  head?: string;
  dirty?: boolean;
  dirty_paths?: string[];
  bot_mode?: string;
  cli_type?: string;
  cli_path?: string;
  available?: boolean;
  reason?: string;
};

type RawAssistantDryRun = {
  ok?: boolean;
  checked_at?: string;
  stdout?: string;
  stderr?: string;
  patch_path?: string;
  repo_root?: string;
};

type RawAssistantUpgradeState = {
  state?: string;
  target_alias?: string;
  target_repo_root?: string;
  base_commit?: string;
  patch_source?: string;
  generation_status?: string;
  chat_conclusion?: string;
  sensitive_hits?: string[];
  dry_run?: RawAssistantDryRun;
  can_generate?: boolean;
  can_approve_patch?: boolean;
  can_dry_run?: boolean;
  can_apply?: boolean;
};

type RawAssistantPatchMetadata = {
  id?: string;
  proposal_id?: string;
  state?: string;
  lifecycle?: string;
  target_alias?: string;
  target_working_dir?: string;
  target_repo_root?: string;
  base_commit?: string;
  worktree_path?: string;
  patch_path?: string;
  generated_at?: string;
  generated_by?: string;
  approved_by?: string;
  approved_at?: string;
  generator?: {
    cli_type?: string;
    cli_path?: string;
    status?: string;
    elapsed_seconds?: number;
  };
  dry_run?: RawAssistantDryRun;
  sensitive_hits?: string[];
  changed_files?: string[];
  additions?: number;
  deletions?: number;
};

type RawAssistantGenerationLog = {
  available?: boolean;
  source?: string;
  items?: Array<Record<string, unknown>>;
};

type RawAssistantProposalDetail = {
  proposal: RawAssistantProposal;
  diff?: {
    available?: boolean;
    state?: string;
    source?: string;
    text?: string;
    files?: Array<{
      path?: string;
      old_path?: string;
      status?: string;
      additions?: number;
      deletions?: number;
      text?: string;
    }>;
  };
  apply?: RawAssistantUpgradeApplyState;
  upgrade?: RawAssistantUpgradeState;
  generation_log?: RawAssistantGenerationLog;
};

type RawAssistantUpgradeApplyResult = {
  id: string;
  status: string;
  patch_path?: string;
  repo_root?: string;
  applied_at?: string;
};

type RawAssistantUpgradeApplyLog = {
  id: string;
  status: string;
  repo_root?: string;
  patch_path?: string;
  applied_at?: string;
  failed_at?: string;
  error?: string;
};

type RawAssistantUpgradeDryRunResult = {
  ok?: boolean;
  checked_at?: string;
  stdout?: string;
  stderr?: string;
  patch_path?: string;
  repo_root?: string;
};

type RawAssistantMemorySearchItem = {
  id: string;
  kind: string;
  scope: string;
  title: string;
  summary: string;
  body: string;
  score?: number;
  source_type?: string;
  source_ref?: string;
  updated_at?: string;
  invalidated_at?: string;
};

type RawAssistantMemoryEvalReportRow = {
  query?: string;
  prompt_block?: string;
  hit?: boolean;
  stale?: boolean;
  audit_path?: string | null;
};

type RawAssistantMemoryEvalReport = {
  report_path?: string;
  created_at?: string;
  metrics?: {
    hit_at_5?: number;
    stale_recall_rate?: number;
  };
  rows?: RawAssistantMemoryEvalReportRow[];
};

type RawAssistantPerfRecord = {
  run_id?: string;
  created_at?: string;
  bot_alias?: string;
  source?: string;
  task_mode?: string;
  interactive?: boolean;
  user_id?: number;
  status?: string;
  stage_durations?: {
    sync_ms?: number;
    index_ms?: number;
    recall_ms?: number;
    cli_ms?: number;
    db_ms?: number;
    trace_ms?: number;
    plugin_ms?: number;
  };
  elapsed_ms?: number;
  prompt_chars?: number;
  output_chars?: number;
  trace_count?: number;
  tool_call_count?: number;
  process_count?: number;
  error?: string;
};

type RawAssistantPerfSummary = {
  total?: number;
  success?: number;
  failed?: number;
  avg_elapsed_ms?: number;
  p95_elapsed_ms?: number;
  by_source?: Record<string, number>;
  by_status?: Record<string, number>;
  slow_stages?: Array<{ stage?: string; total_ms?: number; avg_ms?: number }>;
  error_groups?: Array<{ message?: string; count?: number; latest_at?: string }>;
};

type RawAssistantCronSchedule = {
  type: "daily" | "interval";
  time?: string;
  timezone?: string;
  every_seconds?: number;
  misfire_policy?: "skip" | "once";
};

type RawAssistantCronTask = {
  prompt: string;
  mode?: "standard" | "dream";
  lookback_hours?: number;
  history_limit?: number;
  capture_limit?: number;
  deliver_mode?: "chat_handoff" | "silent";
};

type RawAssistantCronExecution = {
  timeout_seconds?: number;
};

type RawAssistantCronJob = {
  id: string;
  enabled: boolean;
  title: string;
  schedule: RawAssistantCronSchedule;
  task: RawAssistantCronTask;
  execution: RawAssistantCronExecution;
  next_run_at?: string;
  last_status?: string;
  last_error?: string;
  last_success_at?: string;
  pending?: boolean;
  pending_run_id?: string;
  coalesced_count?: number;
};

type RawAssistantCronRun = {
  run_id?: string;
  job_id?: string;
  trigger_source?: string;
  scheduled_at?: string;
  enqueued_at?: string;
  started_at?: string;
  finished_at?: string;
  status?: string;
  elapsed_seconds?: number;
  queue_wait_seconds?: number;
  timed_out?: boolean;
  prompt_excerpt?: string;
  output_excerpt?: string;
  error?: string;
};

type RawAssistantRuntimePendingRun = {
  run_id?: string;
  source?: "web" | "cron" | "manual";
  status?: "queued" | "running";
  task_mode?: string;
  interactive?: boolean;
  job_id?: string;
  job_title?: string;
  visible_text?: string;
  enqueued_at?: string;
};

type RawAssistantRuntimeSnapshot = {
  pending_count?: number;
  queued_count?: number;
  active?: RawAssistantRuntimePendingRun | null;
  queue?: RawAssistantRuntimePendingRun[];
};

type RawAssistantAdminAuditItem = {
  id?: string;
  created_at?: string;
  account_id?: string;
  user_id?: number;
  username?: string;
  method?: string;
  path?: string;
  action?: string;
  target?: {
    bot_alias?: string;
    resource?: string;
    resource_id?: string;
  };
  request_summary?: Record<string, unknown>;
  status_code?: number;
  ok?: boolean;
  error_code?: string;
  error_message?: string;
  elapsed_ms?: number;
};

type StreamEvent =
  | { type: "meta"; [key: string]: unknown }
  | { type: "delta"; text?: string }
  | RawAppUpdateDownloadProgress & { type: "progress" }
  | { type: "status"; elapsed_seconds?: number; preview_text?: string; phase?: string; message?: string; lifecycle?: string }
  | { type: "trace"; event?: RawChatTraceEvent }
  | { type: "log"; text?: string }
  | {
      type: "done";
      output?: string;
      elapsed_seconds?: number;
      script_name?: string;
      success?: boolean;
      message?: RawHistoryItem;
      status?: RawAppUpdateStatus;
      metadata?: RawAssistantPatchMetadata;
    }
  | { type: "error"; message?: string; code?: string };

function mapStatus(status: string, isProcessing = false): BotStatus {
  if (isProcessing) {
    return "busy";
  }
  if (status === "stopped" || status === "offline") {
    return "offline";
  }
  return "running";
}

function mapStatusText(status: BotStatus): string {
  if (status === "busy") {
    return "处理中";
  }
  if (status === "unread") {
    return "未读";
  }
  if (status === "offline") {
    return "离线";
  }
  return "运行中";
}

function mapBotSummary(raw: RawBotSummary, isProcessing = false): BotSummary {
  const hasPendingAssistantRun = Number(raw.assistant_runtime?.pending_count || 0) > 0;
  const busyAgentIds = (raw.busy_agent_ids ?? raw.busyAgentIds ?? []).map((item) => String(item));
  const busyAgentNames = (raw.busy_agent_names ?? raw.busyAgentNames ?? []).map((item) => String(item));
  const hasExplicitBusyAgentCount = typeof raw.busy_agent_count !== "undefined" || typeof raw.busyAgentCount !== "undefined";
  const legacyProcessing = busyAgentIds.length === 0 && isProcessing;
  const resolvedBusyAgentIds = legacyProcessing ? ["main"] : busyAgentIds;
  const resolvedBusyAgentNames = legacyProcessing ? ["主 agent"] : busyAgentNames;
  const busyAgentCount = legacyProcessing
    ? 1
    : Number(raw.busy_agent_count ?? raw.busyAgentCount ?? resolvedBusyAgentIds.length);
  const serviceStatus = (raw.service_status ?? raw.serviceStatus) === "offline" || raw.status === "stopped" || raw.status === "offline"
    ? "offline"
    : "online";
  const activityStatus = (raw.activity_status ?? raw.activityStatus) === "busy" || busyAgentCount > 0 || isProcessing || hasPendingAssistantRun
    ? "busy"
    : "idle";
  const status = mapStatus(raw.status, activityStatus === "busy");
  const summary: BotSummary = {
    alias: raw.alias,
    cliType: raw.cli_type,
    status,
    serviceStatus,
    activityStatus,
    busyAgentIds: resolvedBusyAgentIds,
    busyAgentNames: resolvedBusyAgentNames,
    busyAgentCount: hasExplicitBusyAgentCount || resolvedBusyAgentIds.length > 0 ? busyAgentCount : 0,
    workingDir: raw.working_dir,
    lastActiveText: mapStatusText(status),
    avatarName: raw.avatar_name || "",
  };
  if (Array.isArray(raw.agents)) {
    summary.agents = raw.agents.map(mapAgentSummary);
  }
  if (raw.cluster) {
    summary.cluster = mapBotClusterConfig(raw.cluster);
  }
  if (raw.cli_path) {
    summary.cliPath = raw.cli_path;
  }
  if (raw.bot_mode) {
    summary.botMode = raw.bot_mode;
  }
  if (typeof raw.enabled === "boolean") {
    summary.enabled = raw.enabled;
  }
  if (typeof raw.is_main === "boolean") {
    summary.isMain = raw.is_main;
  }
  return summary;
}

function mapClusterModelTiers(raw: unknown): ClusterModelTiers {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  return {
    low: String(value.low || ""),
    medium: String(value.medium || ""),
    high: String(value.high || ""),
  };
}

function mapBotClusterConfig(raw: unknown): BotClusterConfig {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  return {
    enabled: Boolean(value.enabled),
    writePolicy: String(value.write_policy ?? value.writePolicy ?? "selected_agents") as BotClusterConfig["writePolicy"],
    conflictPolicy: String(value.conflict_policy ?? value.conflictPolicy ?? "snapshot_diff") as BotClusterConfig["conflictPolicy"],
    maxParallelAgents: Number(value.max_parallel_agents ?? value.maxParallelAgents ?? 2),
    defaultTimeoutSeconds: Number(value.default_timeout_seconds ?? value.defaultTimeoutSeconds ?? 600),
    modelTiers: mapClusterModelTiers(value.model_tiers ?? value.modelTiers),
  };
}

function mapAgentClusterConfig(raw: unknown): AgentClusterConfig {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  return {
    allowCluster: value.allow_cluster !== false && value.allowCluster !== false,
    allowWrite: Boolean(value.allow_write ?? value.allowWrite ?? false),
    sessionPolicy: String(value.session_policy ?? value.sessionPolicy ?? "persistent") as AgentClusterConfig["sessionPolicy"],
    timeoutSeconds: Number(value.timeout_seconds ?? value.timeoutSeconds ?? 600),
  };
}

function mapAgentSummary(raw: RawAgentSummary): AgentSummary {
  return {
    id: String(raw.id || "main"),
    name: String(raw.name || (raw.id === "main" ? "主 agent" : raw.id || "agent")),
    systemPrompt: String(raw.system_prompt ?? raw.systemPrompt ?? ""),
    enabled: raw.enabled !== false,
    isMain: Boolean(raw.is_main ?? raw.isMain ?? raw.id === "main"),
    isProcessing: Boolean(raw.is_processing ?? raw.isProcessing ?? false),
    messageCount: Number(raw.message_count ?? raw.messageCount ?? 0),
    activeConversationId: String(raw.active_conversation_id ?? raw.activeConversationId ?? ""),
    createdAt: String(raw.created_at ?? raw.createdAt ?? ""),
    updatedAt: String(raw.updated_at ?? raw.updatedAt ?? ""),
    cluster: mapAgentClusterConfig(raw.cluster),
  };
}

function mapAgentInput(input: AgentInput): Record<string, unknown> {
  return {
    ...(typeof input.id !== "undefined" ? { id: input.id } : {}),
    ...(typeof input.name !== "undefined" ? { name: input.name } : {}),
    ...(typeof input.systemPrompt !== "undefined" ? { system_prompt: input.systemPrompt } : {}),
    ...(typeof input.enabled !== "undefined" ? { enabled: input.enabled } : {}),
    ...(input.cluster ? {
      cluster: {
        ...(typeof input.cluster.allowCluster !== "undefined" ? { allow_cluster: input.cluster.allowCluster } : {}),
        ...(typeof input.cluster.allowWrite !== "undefined" ? { allow_write: input.cluster.allowWrite } : {}),
        ...(input.cluster.sessionPolicy ? { session_policy: input.cluster.sessionPolicy } : {}),
        ...(typeof input.cluster.timeoutSeconds !== "undefined" ? { timeout_seconds: input.cluster.timeoutSeconds } : {}),
      },
    } : {}),
  };
}

function mapClusterStatus(raw: unknown): ClusterStatus {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const mcp = value.mcp && typeof value.mcp === "object" ? value.mcp as Record<string, unknown> : {};
  const mapTarget = (target: unknown): ClusterMcpTargetStatus => {
    const item = target && typeof target === "object" ? target as Record<string, unknown> : {};
    return {
      state: String(item.state || "not_checked") as ClusterMcpState,
      message: String(item.message || ""),
    };
  };
  return {
    enabled: Boolean(value.enabled),
    modelTiers: mapClusterModelTiers(value.model_tiers ?? value.modelTiers),
    mcp: {
      serverName: String(mcp.server_name || mcp.serverName || "tcb-cluster"),
      activeCliType: String(mcp.active_cli_type || mcp.activeCliType || "codex"),
      runtime: mapTarget(mcp.runtime),
      codex: mapTarget(mcp.codex),
      claude: mapTarget(mcp.claude),
    },
    agents: Array.isArray(value.agents) ? value.agents.map((rawAgent) => {
      const agent = rawAgent && typeof rawAgent === "object" ? rawAgent as Record<string, unknown> : {};
      return {
        id: String(agent.id || ""),
        name: String(agent.name || agent.id || ""),
        enabled: agent.enabled !== false,
        allowCluster: agent.allow_cluster !== false && agent.allowCluster !== false,
        allowWrite: Boolean(agent.allow_write ?? agent.allowWrite ?? false),
      };
    }) : [],
  };
}

function mapClusterAgentTask(raw: RawClusterAgentTask): ClusterAgentTask {
  return {
    taskId: String(raw.task_id || ""),
    agentId: String(raw.agent_id || ""),
    status: String(raw.status || "queued") as ClusterAgentTask["status"],
    modelTier: String(raw.model_tier || "") as ClusterAgentTask["modelTier"],
    allowWrite: Boolean(raw.allow_write),
    createdAt: String(raw.created_at || ""),
    startedAt: String(raw.started_at || ""),
    completedAt: String(raw.completed_at || ""),
    output: typeof raw.output === "string" ? raw.output : undefined,
    error: String(raw.error || ""),
  };
}

function mapClusterTaskStatus(raw: unknown): ClusterTaskStatus {
  const value = raw && typeof raw === "object" ? raw as RawClusterTaskStatus : {};
  return {
    tasks: (value.tasks || []).map(mapClusterAgentTask),
    queuedCount: Number(value.queued_count || 0),
    runningCount: Number(value.running_count || 0),
    completedCount: Number(value.completed_count || 0),
    failedCount: Number(value.failed_count || 0),
    pendingCount: Number(value.pending_count || 0),
  };
}

function mapActiveClusterRun(raw: unknown) {
  const value = raw && typeof raw === "object" ? raw as RawActiveClusterRun : null;
  const runId = String(value?.run_id || "");
  if (!runId) {
    return null;
  }
  return {
    runId,
    status: String(value?.status || ""),
    tasks: value?.tasks ? mapClusterTaskStatus(value.tasks) : undefined,
  };
}

function mapClusterSetupPrepare(raw: unknown): ClusterSetupPrepareResult {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const list = (snake: string, camel: string) => {
    const rawList = value[snake] ?? value[camel];
    return Array.isArray(rawList) ? rawList.map((item) => String(item)) : [];
  };
  return {
    serverName: String(value.server_name || value.serverName || "tcb-cluster"),
    launcherPath: String(value.launcher_path || value.launcherPath || ""),
    configPath: String(value.config_path || value.configPath || ""),
    tokenPath: String(value.token_path || value.tokenPath || ""),
    installCommand: list("install_command", "installCommand"),
    verifyCommand: list("verify_command", "verifyCommand"),
    removeCommand: list("remove_command", "removeCommand"),
  };
}

function mapClusterConfigInput(input: ClusterConfigUpdateInput): Record<string, unknown> {
  return {
    ...(typeof input.enabled !== "undefined" ? { enabled: input.enabled } : {}),
    ...(input.writePolicy ? { write_policy: input.writePolicy } : {}),
    ...(input.conflictPolicy ? { conflict_policy: input.conflictPolicy } : {}),
    ...(typeof input.maxParallelAgents !== "undefined" ? { max_parallel_agents: input.maxParallelAgents } : {}),
    ...(typeof input.defaultTimeoutSeconds !== "undefined" ? { default_timeout_seconds: input.defaultTimeoutSeconds } : {}),
    ...(input.modelTiers ? { model_tiers: input.modelTiers } : {}),
  };
}

function mapClusterTemplateSummary(raw: unknown): ClusterTemplateSummary {
  const value = raw && typeof raw === "object" ? raw as RawClusterTemplateSummary : {};
  return {
    id: String(value.id || ""),
    name: String(value.name || ""),
    description: String(value.description || ""),
    agentCount: Number(value.agent_count || 0),
    writeAgentCount: Number(value.write_agent_count || 0),
    maxParallelAgents: Number(value.max_parallel_agents || 0),
  };
}

function mapClusterConfigBundleAgent(raw: unknown): ClusterConfigBundleAgent {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  return {
    id: String(value.id || ""),
    name: String(value.name || ""),
    systemPrompt: String(value.system_prompt ?? value.systemPrompt ?? ""),
    enabled: value.enabled !== false,
    cluster: mapAgentClusterConfig(value.cluster),
  };
}

function mapClusterConfigBundle(raw: unknown): ClusterConfigBundle {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  return {
    id: String(value.id || ""),
    name: String(value.name || ""),
    description: String(value.description || ""),
    cluster: mapBotClusterConfig(value.cluster),
    agents: Array.isArray(value.agents) ? value.agents.map(mapClusterConfigBundleAgent) : [],
  };
}

function mapClusterBundleDiff(raw: unknown): ClusterBundleDiff {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const list = (key: string) => Array.isArray(value[key]) ? value[key].map((item) => String(item)) : [];
  return {
    deleteAgents: list("delete_agents"),
    createAgents: list("create_agents"),
    updateAgents: list("update_agents"),
    clusterChanges: value.cluster_changes && typeof value.cluster_changes === "object"
      ? value.cluster_changes as Record<string, { before: unknown; after: unknown }>
      : {},
    overwritesAgents: Boolean(value.overwrites_agents),
  };
}

function mapClusterBundlePreviewResult(raw: unknown): ClusterBundlePreviewResult {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  return {
    bundle: mapClusterConfigBundle(value.bundle),
    diff: mapClusterBundleDiff(value.diff),
  };
}

function mapClusterBundleApplyResult(raw: unknown): ClusterBundleApplyResult {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  return {
    cluster: mapBotClusterConfig(value.cluster),
    agents: Array.isArray(value.agents) ? value.agents.map((item) => mapAgentSummary(item as RawAgentSummary)) : [],
    bundle: mapClusterConfigBundle(value.bundle),
    diff: mapClusterBundleDiff(value.diff),
    status: mapClusterStatus(value.status),
  };
}

function appendAgentParam(params: URLSearchParams, agentId?: string) {
  const normalized = String(agentId || "").trim();
  if (normalized && normalized !== "main") {
    params.set("agent_id", normalized);
  }
}

function mapWorkdirChangeConflict(raw: unknown): WorkdirChangeConflict | undefined {
  if (!raw || typeof raw !== "object") {
    return undefined;
  }
  const data = raw as Record<string, unknown>;
  return {
    currentWorkingDir: String(data.current_working_dir || ""),
    requestedWorkingDir: String(data.requested_working_dir || ""),
    historyCount: Number(data.history_count || 0),
    messageCount: Number(data.message_count || 0),
    botMode: String(data.bot_mode || ""),
  };
}

function mapApiErrorData(code: string | undefined, raw: unknown): unknown {
  if (code === "workdir_change_requires_reset" || code === "workdir_change_blocked_processing") {
    return mapWorkdirChangeConflict(raw);
  }
  return raw;
}

function mapFileEntry(raw: RawFileEntry): FileEntry {
  return {
    name: raw.name,
    isDir: raw.is_dir,
    ...(typeof raw.size === "number" ? { size: raw.size } : {}),
    ...(raw.updated_at ? { updatedAt: raw.updated_at } : {}),
  };
}

function mapPersistentTerminalSnapshot(raw: RawPersistentTerminalSnapshot): PersistentTerminalSnapshot {
  return {
    started: Boolean(raw.started),
    closed: Boolean(raw.closed),
    cwd: String(raw.cwd || ""),
    ptyMode: typeof raw.pty_mode === "boolean" ? raw.pty_mode : null,
    connectionText: String(raw.connection_text || ""),
    lastSeq: Number(raw.last_seq || 0),
  };
}

function mapTerminalActionRunResult(raw: RawTerminalActionRunResult): TerminalActionRunResult {
  return {
    actionId: String(raw.actionId || ""),
    command: String(raw.command || ""),
    cwd: String(raw.cwd || ""),
    startedTerminal: Boolean(raw.startedTerminal),
    snapshot: mapPersistentTerminalSnapshot(raw.snapshot),
  };
}

function mapChatAttachmentUploadResult(raw: RawChatAttachmentUploadResult): ChatAttachmentUploadResult {
  return {
    filename: raw.filename,
    savedPath: raw.saved_path,
    size: raw.size,
  };
}

function mapChatAttachmentDeleteResult(raw: RawChatAttachmentDeleteResult): ChatAttachmentDeleteResult {
  return {
    filename: raw.filename,
    savedPath: raw.saved_path,
    existed: Boolean(raw.existed),
    deleted: Boolean(raw.deleted),
  };
}

function mapRunningReply(raw?: RawRunningReply | null): RunningReply | null {
  if (!raw?.started_at) {
    return null;
  }
  return {
    userText: raw.user_text,
    previewText: raw.preview_text,
    startedAt: raw.started_at,
    updatedAt: raw.updated_at,
  };
}

function mapTraceEvent(raw?: RawChatTraceEvent | null): ChatTraceEvent | null {
  if (!raw) {
    return null;
  }
  const kind = String(raw.kind || "").trim();
  const summary = String(raw.summary || "").trim();
  if (!kind && !summary) {
    return null;
  }

  const event: ChatTraceEvent = {
    kind: kind || "unknown",
    summary,
  };
  if (raw.source) {
    event.source = raw.source;
  }
  if (raw.raw_type) {
    event.rawType = raw.raw_type;
  }
  if (raw.title) {
    event.title = raw.title;
  }
  if (raw.tool_name) {
    event.toolName = raw.tool_name;
  }
  if (raw.call_id) {
    event.callId = raw.call_id;
  }
  if (typeof raw.payload !== "undefined") {
    event.payload = raw.payload;
  }
  return event;
}

function mapMessageMeta(raw?: RawChatMessageMeta | null): ChatMessageMetaInfo | undefined {
  if (!raw) {
    return undefined;
  }

  const trace = (raw.trace || [])
    .map((item) => mapTraceEvent(item))
    .filter((item): item is ChatTraceEvent => Boolean(item));
  const traceSummary = summarizeTrace(trace);

  const meta: ChatMessageMetaInfo = {};
  if (raw.completion_state) {
    meta.completionState = raw.completion_state;
  }
  if (raw.summary_kind) {
    meta.summaryKind = raw.summary_kind;
  }
  if (typeof raw.trace_version === "number") {
    meta.traceVersion = raw.trace_version;
  }
  if (typeof raw.trace_count === "number") {
    meta.traceCount = raw.trace_count;
  } else if (trace.length > 0) {
    meta.traceCount = traceSummary.traceCount;
  }
  if (typeof raw.tool_call_count === "number") {
    meta.toolCallCount = raw.tool_call_count;
  } else if (trace.length > 0) {
    meta.toolCallCount = traceSummary.toolCallCount;
  }
  if (typeof raw.process_count === "number") {
    meta.processCount = raw.process_count;
  } else if (trace.length > 0) {
    meta.processCount = traceSummary.processCount;
  }
  if (trace.length > 0) {
    meta.trace = trace;
  }
  if (raw.native_source?.provider || raw.native_source?.session_id) {
    meta.nativeSource = {
      provider: raw.native_source.provider || undefined,
      sessionId: raw.native_source.session_id || undefined,
    };
  }

  return Object.keys(meta).length > 0 ? meta : undefined;
}

function summarizeTrace(trace?: ChatTraceEvent[]) {
  return {
    traceCount: trace?.length || 0,
    toolCallCount: (trace || []).filter((item) => item.kind === "tool_call").length,
    processCount: (trace || []).filter((item) => item.kind !== "tool_call" && item.kind !== "tool_result").length,
  };
}

function traceEventKey(event: ChatTraceEvent): string {
  return [
    event.kind || "",
    event.rawType || "",
    event.callId || "",
    event.summary || "",
  ].join("|");
}

function mergeTraceEvents(...sources: Array<ChatTraceEvent[] | undefined>): ChatTraceEvent[] | undefined {
  const merged: ChatTraceEvent[] = [];
  const seen = new Set<string>();

  for (const source of sources) {
    for (const item of source || []) {
      const key = traceEventKey(item);
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      merged.push(item);
    }
  }

  return merged.length > 0 ? merged : undefined;
}

function maxDefinedNumber(...values: Array<number | undefined>) {
  const definedValues = values.filter((value): value is number => (
    typeof value === "number" && Number.isFinite(value)
  ));
  return definedValues.length > 0 ? Math.max(...definedValues) : undefined;
}

function mergeMessageMeta(
  base?: ChatMessageMetaInfo,
  incoming?: ChatMessageMetaInfo,
  streamedTrace?: ChatTraceEvent[],
): ChatMessageMetaInfo | undefined {
  const trace = mergeTraceEvents(base?.trace, incoming?.trace, streamedTrace);
  const traceSummary = trace ? summarizeTrace(trace) : undefined;
  const meta: ChatMessageMetaInfo = {
    completionState: incoming?.completionState || base?.completionState,
    summaryKind: incoming?.summaryKind || base?.summaryKind,
    traceVersion: incoming?.traceVersion ?? base?.traceVersion ?? (trace ? 1 : undefined),
    traceCount: maxDefinedNumber(incoming?.traceCount, base?.traceCount, traceSummary?.traceCount),
    toolCallCount: maxDefinedNumber(incoming?.toolCallCount, base?.toolCallCount, traceSummary?.toolCallCount),
    processCount: maxDefinedNumber(incoming?.processCount, base?.processCount, traceSummary?.processCount),
    nativeSource: incoming?.nativeSource || base?.nativeSource,
    trace,
  };

  return Object.values(meta).some((value) => typeof value !== "undefined") ? meta : undefined;
}

function mapChatMessage(raw: RawHistoryItem, index: number, fallbackState: ChatMessage["state"] = "done"): ChatMessage {
  return {
    id: raw.id || `${raw.timestamp || raw.created_at || "history"}-${index}`,
    role: raw.role,
    text: raw.content,
    createdAt: raw.created_at || raw.timestamp || new Date().toISOString(),
    state: raw.state || fallbackState,
    ...(typeof raw.elapsed_seconds === "number" ? { elapsedSeconds: raw.elapsed_seconds } : {}),
    ...(mapMessageMeta(raw.meta) ? { meta: mapMessageMeta(raw.meta) } : {}),
  };
}

function mapConversationSummary(raw: RawConversationSummary): ConversationSummary {
  const nativeProvider = String(raw.native_provider || "");
  const nativeSessionId = String(raw.native_session_id || "");
  return {
    id: String(raw.id || ""),
    title: String(raw.title || "新会话"),
    lastMessagePreview: String(raw.last_message_preview || ""),
    messageCount: Number(raw.message_count || 0),
    pinned: Boolean(raw.pinned),
    active: Boolean(raw.active),
    status: String(raw.status || "active"),
    botAlias: String(raw.bot_alias || ""),
    botMode: String(raw.bot_mode || ""),
    cliType: String(raw.cli_type || ""),
    agentId: String(raw.agent_id || "main"),
    workingDir: String(raw.working_dir || ""),
    ...(nativeProvider || nativeSessionId ? {
      nativeSource: {
        provider: nativeProvider,
        sessionId: nativeSessionId,
      },
    } : {}),
    createdAt: String(raw.created_at || ""),
    updatedAt: String(raw.updated_at || ""),
  };
}

function mapCliParamsPayload(raw: RawCliParamsPayload): CliParamsPayload {
  return {
    cliType: raw.cli_type,
    params: raw.params || {},
    defaults: raw.defaults || {},
    schema: raw.schema || {},
  };
}

function mapTunnelSnapshot(raw: RawTunnelSnapshot): TunnelSnapshot {
  return {
    mode: raw.mode,
    status: raw.status,
    source: raw.source,
    publicUrl: raw.public_url || "",
    localUrl: raw.local_url || "",
    lastError: raw.last_error || "",
    pid: raw.pid ?? null,
  };
}

function mapAvatarAsset(raw: RawAvatarAsset): AvatarAsset {
  return {
    name: raw.name,
    url: raw.url,
  };
}

function mapPublicHostInfo(raw?: RawPublicHostInfo | null): PublicHostInfo {
  return {
    username: raw?.username || "未知",
    operatingSystem: raw?.operating_system || "未知",
    hardwarePlatform: raw?.hardware_platform || "未知",
    hardwareSpec: raw?.hardware_spec || "未知",
  };
}

function mapSessionState(raw: RawAuthSession): SessionState {
  return {
    currentBotAlias: raw.current_bot_alias || "",
    currentPath: raw.current_path || "",
    isLoggedIn: raw.is_logged_in !== false,
    ...(raw.token ? { token: raw.token } : {}),
    ...(typeof raw.user_id === "number" ? { userId: raw.user_id } : {}),
    ...(raw.account_id ? { accountId: raw.account_id } : {}),
    username: raw.username || "",
    role: raw.role || "member",
    capabilities: Array.isArray(raw.capabilities) ? raw.capabilities : [],
    ...(typeof raw.token_protected === "boolean" ? { tokenProtected: raw.token_protected } : {}),
    ...(Array.isArray(raw.allowed_user_ids) ? { allowedUserIds: raw.allowed_user_ids } : {}),
  };
}

function mapRegisterCodeUsage(raw: RawRegisterCodeUsage) {
  return {
    usedAt: raw.used_at || "",
    usedBy: raw.used_by || "",
  };
}

function mapRegisterCodeItem(raw: RawRegisterCodeItem): RegisterCodeItem {
  return {
    codeId: raw.code_id || "",
    codePreview: raw.code_preview || "",
    disabled: Boolean(raw.disabled),
    maxUses: Number(raw.max_uses || 0),
    usedCount: Number(raw.used_count || 0),
    remainingUses: Number(raw.remaining_uses || 0),
    createdAt: raw.created_at || "",
    createdBy: raw.created_by || "",
    lastUsedAt: raw.last_used_at || "",
    usage: Array.isArray(raw.usage) ? raw.usage.map((item) => mapRegisterCodeUsage(item)) : [],
  };
}

function mapRegisterCodeCreateResult(raw: RawRegisterCodeCreateResult): RegisterCodeCreateResult {
  return {
    ...mapRegisterCodeItem(raw),
    code: raw.code || "",
  };
}

function mapGitChangedFile(raw: RawGitChangedFile) {
  return {
    path: raw.path,
    status: raw.status,
    staged: Boolean(raw.staged),
    unstaged: Boolean(raw.unstaged),
    untracked: Boolean(raw.untracked),
  };
}

function mapGitCommitSummary(raw: RawGitCommitSummary): GitCommitSummary {
  return {
    hash: raw.hash,
    shortHash: raw.short_hash,
    authorName: raw.author_name,
    authoredAt: raw.authored_at,
    subject: raw.subject,
  };
}

function mapGitOverview(raw: RawGitOverview): GitOverview {
  return {
    repoFound: Boolean(raw.repo_found),
    canInit: Boolean(raw.can_init),
    workingDir: raw.working_dir || "",
    repoPath: raw.repo_path || "",
    repoName: raw.repo_name || "",
    currentBranch: raw.current_branch || "",
    isClean: Boolean(raw.is_clean),
    aheadCount: Number(raw.ahead_count || 0),
    behindCount: Number(raw.behind_count || 0),
    changedFiles: (raw.changed_files || []).map(mapGitChangedFile),
    recentCommits: (raw.recent_commits || []).map(mapGitCommitSummary),
  };
}

function mapGitTreeStatus(raw: RawGitTreeStatus): GitTreeStatus {
  return {
    repoFound: Boolean(raw.repo_found),
    workingDir: raw.working_dir || "",
    repoPath: raw.repo_path || "",
    items: raw.items || {},
  };
}

function mapGitDiffPayload(raw: RawGitDiffPayload): GitDiffPayload {
  return {
    path: raw.path,
    staged: Boolean(raw.staged),
    diff: raw.diff || "",
  };
}

function mapGitActionResult(raw: RawGitActionResult): GitActionResult {
  return {
    message: raw.message || "",
    overview: mapGitOverview(raw.overview),
  };
}

function mapGitBranchList(raw: RawGitBranchList): GitBranchList {
  return {
    currentBranch: raw.current_branch || "",
    branches: (raw.branches || []).map((item) => ({
      name: item.name,
      current: Boolean(item.current),
      upstream: item.upstream || "",
      shortHash: item.short_hash || "",
      subject: item.subject || "",
    })),
  };
}

function mapGitStashList(raw: RawGitStashList): GitStashList {
  return {
    items: (raw.items || []).map((item) => ({
      ref: item.ref,
      hash: item.hash || "",
      createdAt: item.created_at || "",
      message: item.message || "",
    })),
  };
}

function mapGitBlamePayload(raw: RawGitBlamePayload): GitBlamePayload {
  return {
    path: raw.path || "",
    lines: (raw.lines || []).map((item) => ({
      line: Number(item.line || 0),
      commit: item.commit || "",
      shortCommit: item.short_commit || "",
      authorName: item.author_name || "",
      authorMail: item.author_mail || "",
      authoredAt: item.authored_at || "",
      summary: item.summary || "",
      content: item.content || "",
    })),
  };
}

function mapGitProxySettings(raw: RawGitProxySettings): GitProxySettings {
  const address = raw.address || (raw.port ? `127.0.0.1:${raw.port}` : "");
  return {
    address,
    port: raw.port || "",
  };
}

function mapAppUpdateStatus(raw: RawAppUpdateStatus): AppUpdateStatus {
  return {
    currentVersion: raw.current_version || "",
    currentPackageKind: raw.current_package_kind || "",
    updateEnabled: Boolean(raw.update_enabled),
    updateChannel: raw.update_channel || "release",
    lastCheckedAt: raw.last_checked_at || "",
    latestVersion: raw.last_available_version || "",
    latestReleaseUrl: raw.last_available_release_url || "",
    latestNotes: raw.last_available_notes || "",
    pendingUpdateVersion: raw.pending_update_version || "",
    pendingUpdatePath: raw.pending_update_path || "",
    pendingUpdateNotes: raw.pending_update_notes || "",
    pendingUpdatePlatform: raw.pending_update_platform || "",
    pendingUpdatePackageKind: raw.pending_update_package_kind || "",
    lastError: raw.update_last_error || "",
  };
}

function mapAppUpdateDownloadProgress(raw: RawAppUpdateDownloadProgress): AppUpdateDownloadProgress {
  return {
    phase: raw.phase || "",
    downloadedBytes: Number(raw.downloaded_bytes || 0),
    ...(typeof raw.total_bytes === "number" ? { totalBytes: raw.total_bytes } : {}),
    ...(typeof raw.percent === "number" ? { percent: raw.percent } : {}),
    ...(raw.message ? { message: raw.message } : {}),
  };
}

function mapAssistantProposal(raw: RawAssistantProposal): AssistantProposal {
  return {
    id: raw.id,
    kind: raw.kind || "",
    title: raw.title || raw.id,
    body: raw.body || "",
    status: raw.status || "proposed",
    createdAt: raw.created_at || "",
    reviewedBy: raw.reviewed_by || "",
    reviewedAt: raw.reviewed_at || "",
    appliedAt: raw.applied_at || "",
  };
}

function mapAssistantUpgradeTarget(raw: RawAssistantUpgradeTarget): AssistantUpgradeTarget {
  return {
    alias: raw.alias || "",
    workingDir: raw.working_dir || "",
    repoRoot: raw.repo_root || "",
    head: raw.head || "",
    dirty: Boolean(raw.dirty),
    dirtyPaths: (raw.dirty_paths || []).map((item) => String(item)),
    botMode: raw.bot_mode || "",
    cliType: raw.cli_type || "",
    cliPath: raw.cli_path || "",
    available: Boolean(raw.available),
    reason: raw.reason || "",
  };
}

function mapAssistantDryRun(raw: RawAssistantDryRun | undefined): AssistantUpgradeDryRunResult {
  return {
    ok: Boolean(raw?.ok),
    checkedAt: raw?.checked_at || "",
    stdout: raw?.stdout || "",
    stderr: raw?.stderr || "",
    patchPath: raw?.patch_path || "",
    repoRoot: raw?.repo_root || "",
  };
}

function mapAssistantUpgradeState(raw: RawAssistantUpgradeState | undefined): AssistantUpgradeState {
  return {
    state: raw?.state || "none",
    targetAlias: raw?.target_alias || "",
    targetRepoRoot: raw?.target_repo_root || "",
    baseCommit: raw?.base_commit || "",
    patchSource: raw?.patch_source || "",
    generationStatus: raw?.generation_status || "",
    chatConclusion: raw?.chat_conclusion || "",
    sensitiveHits: (raw?.sensitive_hits || []).map((item) => String(item)),
    dryRun: mapAssistantDryRun(raw?.dry_run),
    canGenerate: Boolean(raw?.can_generate),
    canApprovePatch: Boolean(raw?.can_approve_patch),
    canDryRun: Boolean(raw?.can_dry_run),
    canApply: Boolean(raw?.can_apply),
  };
}

function mapAssistantPatchMetadata(raw: RawAssistantPatchMetadata): AssistantPatchMetadata {
  return {
    id: raw.id || "",
    proposalId: raw.proposal_id || "",
    state: raw.state || "",
    lifecycle: raw.lifecycle || raw.state || "",
    targetAlias: raw.target_alias || "",
    targetWorkingDir: raw.target_working_dir || "",
    targetRepoRoot: raw.target_repo_root || "",
    baseCommit: raw.base_commit || "",
    worktreePath: raw.worktree_path || "",
    patchPath: raw.patch_path || "",
    generatedAt: raw.generated_at || "",
    generatedBy: raw.generated_by || "",
    ...(raw.approved_by ? { approvedBy: raw.approved_by } : {}),
    ...(raw.approved_at ? { approvedAt: raw.approved_at } : {}),
    generator: {
      cliType: raw.generator?.cli_type || "",
      cliPath: raw.generator?.cli_path || "",
      status: raw.generator?.status || "",
      elapsedSeconds: Number(raw.generator?.elapsed_seconds || 0),
    },
    dryRun: mapAssistantDryRun(raw.dry_run),
    sensitiveHits: (raw.sensitive_hits || []).map((item) => String(item)),
    changedFiles: (raw.changed_files || []).map((item) => String(item)),
    additions: Number(raw.additions || 0),
    deletions: Number(raw.deletions || 0),
  };
}

function mapAssistantGenerationLog(raw: RawAssistantGenerationLog | undefined) {
  return {
    available: Boolean(raw?.available),
    source: raw?.source || "",
    items: (raw?.items || []).map((item) => ({
      event: String(item.event || ""),
      createdAt: String(item.created_at || item.createdAt || ""),
      status: String(item.status || ""),
      message: String(item.message || ""),
      error: String(item.error || ""),
      code: String(item.code || ""),
      raw: item,
    })),
  };
}

function mapAssistantProposalDetail(raw: RawAssistantProposalDetail): AssistantProposalDetail {
  return {
    proposal: mapAssistantProposal(raw.proposal),
    diff: {
      available: Boolean(raw.diff?.available),
      source: raw.diff?.source || "",
      text: raw.diff?.text || "",
      files: (raw.diff?.files || []).map((item) => ({
        path: String(item.path || ""),
        ...(item.old_path ? { oldPath: String(item.old_path) } : {}),
        status: (
          item.status === "added"
          || item.status === "modified"
          || item.status === "deleted"
          || item.status === "renamed"
        ) ? item.status : "unknown",
        additions: Number(item.additions || 0),
        deletions: Number(item.deletions || 0),
        text: String(item.text || ""),
      })),
    },
    apply: {
      available: Boolean(raw.apply?.available),
      applied: Boolean(raw.apply?.applied),
      lastError: raw.apply?.last_error || "",
      lastErrorAt: raw.apply?.last_error_at || "",
      lastErrorLogPath: raw.apply?.last_error_log_path || "",
    },
    upgrade: mapAssistantUpgradeState(raw.upgrade),
    generationLog: mapAssistantGenerationLog(raw.generation_log),
  };
}

function mapAssistantUpgradeApplyResult(raw: RawAssistantUpgradeApplyResult): AssistantUpgradeApplyResult {
  return {
    id: raw.id,
    status: raw.status || "",
    patchPath: raw.patch_path || "",
    repoRoot: raw.repo_root || "",
    appliedAt: raw.applied_at || "",
  };
}

function mapAssistantUpgradeApplyLog(raw: RawAssistantUpgradeApplyLog): AssistantUpgradeApplyLog {
  return {
    id: raw.id,
    status: raw.status || "",
    repoRoot: raw.repo_root || "",
    patchPath: raw.patch_path || "",
    appliedAt: raw.applied_at || "",
    failedAt: raw.failed_at || "",
    error: raw.error || "",
  };
}

function mapAssistantUpgradeDryRunResult(raw: RawAssistantUpgradeDryRunResult): AssistantUpgradeDryRunResult {
  return {
    ok: Boolean(raw.ok),
    checkedAt: raw.checked_at || "",
    stdout: raw.stdout || "",
    stderr: raw.stderr || "",
    patchPath: raw.patch_path || "",
    repoRoot: raw.repo_root || "",
  };
}

function mapAssistantMemorySearchResult(raw: { items?: RawAssistantMemorySearchItem[] }): AssistantMemorySearchResult {
  return {
    items: (raw.items || []).map((item) => ({
      id: item.id,
      kind: item.kind || "",
      scope: item.scope || "",
      title: item.title || item.id,
      summary: item.summary || "",
      body: item.body || "",
      score: Number(item.score || 0),
      sourceType: item.source_type || "",
      sourceRef: item.source_ref || "",
      updatedAt: item.updated_at || "",
      invalidatedAt: item.invalidated_at || "",
    })),
  };
}

function mapAssistantMemoryInvalidateResult(raw: {
  memory_id?: string;
  invalidated?: boolean;
  reason?: string;
}): AssistantMemoryInvalidateResult {
  return {
    memoryId: raw.memory_id || "",
    invalidated: Boolean(raw.invalidated),
    reason: raw.reason || "",
  };
}

function mapAssistantMemoryReindexResult(raw: {
  working?: { indexed_count?: number; memory_ids?: string[] };
  knowledge?: { indexed_count?: number; memory_ids?: string[] };
}): AssistantMemoryReindexResult {
  return {
    working: {
      indexedCount: Number(raw.working?.indexed_count || 0),
      memoryIds: raw.working?.memory_ids || [],
    },
    knowledge: {
      indexedCount: Number(raw.knowledge?.indexed_count || 0),
      memoryIds: raw.knowledge?.memory_ids || [],
    },
  };
}

function mapAssistantMemoryEvalRun(raw: {
  metrics?: { hit_at_5?: number; stale_recall_rate?: number };
  report_path?: string;
}): AssistantMemoryEvalRun {
  return {
    metrics: {
      hitAt5: Number(raw.metrics?.hit_at_5 || 0),
      staleRecallRate: Number(raw.metrics?.stale_recall_rate || 0),
    },
    reportPath: raw.report_path || "",
  };
}

function mapAssistantMemoryEvalReport(raw: RawAssistantMemoryEvalReport): AssistantMemoryEvalReport {
  return {
    reportPath: raw.report_path || "",
    createdAt: raw.created_at || "",
    metrics: {
      hitAt5: Number(raw.metrics?.hit_at_5 || 0),
      staleRecallRate: Number(raw.metrics?.stale_recall_rate || 0),
    },
    rows: (raw.rows || []).map((row) => ({
      query: row.query || "",
      promptBlock: row.prompt_block || "",
      hit: Boolean(row.hit),
      stale: Boolean(row.stale),
      auditPath: row.audit_path || "",
    })),
  };
}

function mapAssistantPerfRecord(raw: RawAssistantPerfRecord): AssistantPerfRecord {
  return {
    runId: raw.run_id || "",
    createdAt: raw.created_at || "",
    botAlias: raw.bot_alias || "",
    source: raw.source || "",
    taskMode: raw.task_mode || "",
    interactive: Boolean(raw.interactive),
    userId: Number(raw.user_id || 0),
    status: raw.status || "",
    stageDurations: {
      syncMs: Number(raw.stage_durations?.sync_ms || 0),
      indexMs: Number(raw.stage_durations?.index_ms || 0),
      recallMs: Number(raw.stage_durations?.recall_ms || 0),
      cliMs: Number(raw.stage_durations?.cli_ms || 0),
      dbMs: Number(raw.stage_durations?.db_ms || 0),
      traceMs: Number(raw.stage_durations?.trace_ms || 0),
      pluginMs: Number(raw.stage_durations?.plugin_ms || 0),
    },
    elapsedMs: Number(raw.elapsed_ms || 0),
    promptChars: Number(raw.prompt_chars || 0),
    outputChars: Number(raw.output_chars || 0),
    traceCount: Number(raw.trace_count || 0),
    toolCallCount: Number(raw.tool_call_count || 0),
    processCount: Number(raw.process_count || 0),
    error: raw.error || "",
  };
}

function mapAssistantPerfDiagnostics(raw: {
  items?: RawAssistantPerfRecord[];
  summary?: RawAssistantPerfSummary;
}): AssistantPerfDiagnostics {
  const summary = raw.summary || {};
  return {
    items: (raw.items || []).map(mapAssistantPerfRecord),
    summary: {
      total: Number(summary.total || 0),
      success: Number(summary.success || 0),
      failed: Number(summary.failed || 0),
      avgElapsedMs: Number(summary.avg_elapsed_ms || 0),
      p95ElapsedMs: Number(summary.p95_elapsed_ms || 0),
      bySource: summary.by_source || {},
      byStatus: summary.by_status || {},
      slowStages: (summary.slow_stages || []).map((item) => ({
        stage: String(item.stage || ""),
        totalMs: Number(item.total_ms || 0),
        avgMs: Number(item.avg_ms || 0),
      })),
      errorGroups: (summary.error_groups || []).map((item) => ({
        message: String(item.message || ""),
        count: Number(item.count || 0),
        latestAt: String(item.latest_at || ""),
      })),
    },
  };
}

function mapAssistantCronJob(raw: RawAssistantCronJob): AssistantCronJob {
  return {
    id: raw.id,
    enabled: Boolean(raw.enabled),
    title: raw.title || raw.id,
    schedule: {
      type: raw.schedule.type,
      time: raw.schedule.time,
      timezone: raw.schedule.timezone || "Asia/Shanghai",
      everySeconds: raw.schedule.every_seconds,
      misfirePolicy: raw.schedule.misfire_policy || "skip",
    },
    task: {
      prompt: raw.task.prompt || "",
      mode: raw.task.mode || "standard",
      lookbackHours: Number(raw.task.lookback_hours || 24),
      historyLimit: Number(raw.task.history_limit || 40),
      captureLimit: Number(raw.task.capture_limit || 20),
      deliverMode: raw.task.deliver_mode || (raw.task.mode === "dream" ? "silent" : "chat_handoff"),
    },
    execution: {
      timeoutSeconds: Number(raw.execution.timeout_seconds || 1800),
    },
    nextRunAt: raw.next_run_at || "",
    lastStatus: raw.last_status || "",
    lastError: raw.last_error || "",
    lastSuccessAt: raw.last_success_at || "",
    pending: Boolean(raw.pending),
    pendingRunId: raw.pending_run_id || "",
    coalescedCount: Number(raw.coalesced_count || 0),
  };
}

function mapAssistantCronRun(raw: RawAssistantCronRun): AssistantCronRun {
  return {
    runId: raw.run_id || "",
    jobId: raw.job_id || "",
    triggerSource: raw.trigger_source || "",
    scheduledAt: raw.scheduled_at || "",
    enqueuedAt: raw.enqueued_at || "",
    startedAt: raw.started_at || "",
    finishedAt: raw.finished_at || "",
    status: raw.status || "",
    elapsedSeconds: Number(raw.elapsed_seconds || 0),
    queueWaitSeconds: Number(raw.queue_wait_seconds || 0),
    timedOut: Boolean(raw.timed_out),
    promptExcerpt: raw.prompt_excerpt || "",
    outputExcerpt: raw.output_excerpt || "",
    error: raw.error || "",
  };
}

function mapAssistantRuntimePendingRun(raw?: RawAssistantRuntimePendingRun | null): AssistantRuntimePendingRun | null {
  if (!raw?.run_id || !raw.source || !raw.status) {
    return null;
  }
  return {
    runId: raw.run_id,
    source: raw.source,
    status: raw.status,
    taskMode: raw.task_mode || "standard",
    interactive: Boolean(raw.interactive),
    ...(raw.job_id ? { jobId: raw.job_id } : {}),
    ...(raw.job_title ? { jobTitle: raw.job_title } : {}),
    ...(raw.visible_text ? { visibleText: raw.visible_text } : {}),
    ...(raw.enqueued_at ? { enqueuedAt: raw.enqueued_at } : {}),
  };
}

function mapAssistantRuntimeSnapshot(raw?: RawAssistantRuntimeSnapshot | null): AssistantRuntimeSnapshot | null {
  if (!raw) {
    return null;
  }
  return {
    pendingCount: Number(raw.pending_count || 0),
    queuedCount: Number(raw.queued_count || 0),
    active: mapAssistantRuntimePendingRun(raw.active),
    queue: (raw.queue || [])
      .map((item) => mapAssistantRuntimePendingRun(item))
      .filter((item): item is AssistantRuntimePendingRun => Boolean(item)),
  };
}

function mapAssistantAdminAuditResult(raw: { items?: RawAssistantAdminAuditItem[] }): AssistantAdminAuditResult {
  return {
    items: (raw.items || []).map((item) => ({
      id: String(item.id || ""),
      createdAt: String(item.created_at || ""),
      accountId: String(item.account_id || ""),
      userId: Number(item.user_id || 0),
      username: String(item.username || ""),
      method: String(item.method || ""),
      path: String(item.path || ""),
      action: String(item.action || ""),
      target: {
        ...(item.target?.bot_alias ? { botAlias: String(item.target.bot_alias) } : {}),
        ...(item.target?.resource ? { resource: String(item.target.resource) } : {}),
        ...(item.target?.resource_id ? { resourceId: String(item.target.resource_id) } : {}),
      },
      requestSummary: item.request_summary || {},
      statusCode: Number(item.status_code || 0),
      ok: Boolean(item.ok),
      errorCode: String(item.error_code || ""),
      errorMessage: String(item.error_message || ""),
      elapsedMs: Number(item.elapsed_ms || 0),
    })),
  };
}

function mapChatTraceDetails(raw: RawChatTraceDetails): ChatTraceDetails {
  const trace = (raw.trace || [])
    .map((item) => mapTraceEvent(item))
    .filter((item): item is ChatTraceEvent => Boolean(item));
  const summary = summarizeTrace(trace);
  return {
    traceCount: typeof raw.trace_count === "number" ? raw.trace_count : summary.traceCount,
    toolCallCount: typeof raw.tool_call_count === "number" ? raw.tool_call_count : summary.toolCallCount,
    processCount: typeof raw.process_count === "number" ? raw.process_count : summary.processCount,
    trace,
  };
}

function mapDebugVariable(raw: Record<string, unknown>): DebugVariable {
  return {
    name: String(raw.name || ""),
    value: String(raw.value || ""),
    ...(raw.type ? { type: String(raw.type) } : {}),
    ...(raw.variablesReference || raw.variables_reference
      ? { variablesReference: String(raw.variablesReference || raw.variables_reference || "") }
      : {}),
  };
}

function mapDebugState(raw: Record<string, unknown>): DebugState {
  return {
    phase: raw.phase as DebugState["phase"],
    message: String(raw.message || ""),
    breakpoints: Array.isArray(raw.breakpoints)
      ? raw.breakpoints
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
        .map((item) => ({
          source: String(item.source || ""),
          line: Number(item.line || 0),
          verified: Boolean(item.verified),
          status: String(item.status || (item.verified ? "verified" : "pending")) as DebugBreakpoint["status"],
          type: String(item.type || "line") as DebugBreakpoint["type"],
          function: String(item.function || ""),
          condition: String(item.condition || ""),
          hitCondition: String(item.hitCondition || item.hit_condition || ""),
          logMessage: String(item.logMessage || item.log_message || ""),
          message: String(item.message || ""),
        } satisfies DebugBreakpoint))
      : [],
    frames: Array.isArray(raw.frames)
      ? raw.frames
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
        .map((item) => ({
          id: String(item.id || ""),
          name: String(item.name || ""),
          source: String(item.source || ""),
          line: Number(item.line || 0),
          sourceResolved: Boolean(item.sourceResolved ?? item.source_resolved ?? true),
          sourceReason: String(item.sourceReason || item.source_reason || ""),
          originalSource: String(item.originalSource || item.original_source || ""),
        } satisfies DebugFrame))
      : [],
    currentFrameId: String(raw.current_frame_id || raw.currentFrameId || ""),
    scopes: Array.isArray(raw.scopes)
      ? raw.scopes
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
        .map((item) => ({
          name: String(item.name || ""),
          variablesReference: String(item.variablesReference || item.variables_reference || ""),
        } satisfies DebugScope))
      : [],
    variables: Object.fromEntries(
      Object.entries(raw.variables && typeof raw.variables === "object" ? raw.variables as Record<string, unknown> : {})
        .map(([key, value]) => [
          key,
          Array.isArray(value)
            ? value
              .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
              .map(mapDebugVariable)
            : [],
        ]),
    ) as Record<string, DebugVariable[]>,
  };
}

function parseSseBlock(block: string): StreamEvent | null {
  const lines = block.split("\n");
  let eventType = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  try {
    return {
      type: eventType,
      ...JSON.parse(dataLines.join("\n")),
    } as StreamEvent;
  } catch {
    return {
      type: "error",
      message: "无法解析流式响应",
      code: "invalid_stream_event",
    };
  }
}

export class RealWebBotClient implements WebBotClient {
  private token = "";

  private headers(extraHeaders: HeadersInit = {}) {
    return {
      ...extraHeaders,
      ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
    };
  }

  private async requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(path, {
      ...init,
      cache: "no-store",
      headers: this.headers(init.headers),
    });
    const responseClone = typeof response.clone === "function" ? response.clone() : null;
    let payload: JsonEnvelope<T>;
    try {
      payload = (await response.json()) as JsonEnvelope<T>;
    } catch {
      const contentType = response.headers?.get?.("content-type") || "";
      let previewText = "";
      try {
        previewText = responseClone && typeof responseClone.text === "function"
          ? await responseClone.text()
          : "";
      } catch {
        previewText = "";
      }
      const looksLikeHtml = contentType.includes("text/html") || /^\s*</.test(previewText);
      throw new Error(
        looksLikeHtml
          ? "服务返回了页面内容而不是 JSON，请确认 Web API 已启动，并且前后端版本已同步更新"
          : "服务返回了无法解析的数据，请刷新页面后重试",
      );
    }
    if (!response.ok || !payload.ok) {
      throw new WebApiClientError(payload.error?.message || "请求失败", {
        status: response.status,
        code: payload.error?.code,
        data: mapApiErrorData(payload.error?.code, payload.error?.data),
      });
    }
    return payload.data;
  }

  async getPublicHostInfo(): Promise<PublicHostInfo> {
    const response = await fetch("/api/health", {
      cache: "no-store",
      headers: this.headers(),
    });
    if (!response.ok) {
      throw new Error("读取主机信息失败");
    }

    let payload: RawHealthResponse;
    try {
      payload = (await response.json()) as RawHealthResponse;
    } catch {
      throw new Error("主机信息响应无法解析");
    }

    return mapPublicHostInfo(payload.host_info);
  }

  async login(input: { username: string; password: string } | string): Promise<SessionState> {
    if (typeof input === "string") {
      return this.restoreSession(input);
    }
    const data = await this.requestJson<RawAuthSession>("/api/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(input),
    });
    this.token = String(data.token || "").trim();
    return mapSessionState(data);
  }

  async register(input: { username: string; password: string; registerCode: string }): Promise<SessionState> {
    const data = await this.requestJson<RawAuthSession>("/api/auth/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        username: input.username,
        password: input.password,
        register_code: input.registerCode,
      }),
    });
    this.token = String(data.token || "").trim();
    return mapSessionState(data);
  }

  async loginGuest(): Promise<SessionState> {
    const data = await this.requestJson<RawAuthSession>("/api/auth/guest", {
      method: "POST",
    });
    this.token = String(data.token || "").trim();
    return mapSessionState(data);
  }

  async restoreSession(token = ""): Promise<SessionState> {
    this.token = token.trim();
    const data = await this.requestJson<RawAuthSession>("/api/auth/me");
    return mapSessionState(data);
  }

  async logout(): Promise<void> {
    try {
      await this.requestJson("/api/auth/logout", {
        method: "POST",
      });
    } finally {
      this.token = "";
    }
  }

  async listRegisterCodes(): Promise<RegisterCodeItem[]> {
    const data = await this.requestJson<{ items: RawRegisterCodeItem[] }>("/api/admin/register-codes");
    return Array.isArray(data.items) ? data.items.map((item) => mapRegisterCodeItem(item)) : [];
  }

  async createRegisterCode(maxUses = 1): Promise<RegisterCodeCreateResult> {
    const data = await this.requestJson<RawRegisterCodeCreateResult>("/api/admin/register-codes", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ max_uses: maxUses }),
    });
    return mapRegisterCodeCreateResult(data);
  }

  async updateRegisterCode(codeId: string, input: { maxUsesDelta?: number; disabled?: boolean }): Promise<RegisterCodeItem> {
    const data = await this.requestJson<RawRegisterCodeItem>(`/api/admin/register-codes/${encodeURIComponent(codeId)}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...(typeof input.maxUsesDelta === "number" ? { max_uses_delta: input.maxUsesDelta } : {}),
        ...(typeof input.disabled === "boolean" ? { disabled: input.disabled } : {}),
      }),
    });
    return mapRegisterCodeItem(data);
  }

  async deleteRegisterCode(codeId: string): Promise<void> {
    await this.requestJson(`/api/admin/register-codes/${encodeURIComponent(codeId)}`, {
      method: "DELETE",
    });
  }

  async listBots(): Promise<BotSummary[]> {
    const data = await this.requestJson<RawBotSummary[]>("/api/bots");
    return data.map((item) => mapBotSummary(item, Boolean(item.is_processing)));
  }

  async listPlugins(refresh = false): Promise<PluginSummary[]> {
    const data = await this.requestJson<PluginSummary[]>(refresh ? "/api/plugins?refresh=1" : "/api/plugins");
    return Array.isArray(data) ? data : [];
  }

  async listInstallablePlugins(): Promise<InstallablePluginSummary[]> {
    const data = await this.requestJson<InstallablePluginSummary[]>("/api/plugins/installable");
    return Array.isArray(data) ? data : [];
  }

  async installPlugin(input: string | { pluginId?: string; sourcePath?: string }): Promise<PluginSummary> {
    const body = typeof input === "string" ? { pluginId: input } : input;
    return this.requestJson<PluginSummary>("/api/plugins/install", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
  }

  async updatePlugin(pluginId: string, input: PluginUpdateInput): Promise<PluginSummary> {
    return this.requestJson<PluginSummary>(`/api/plugins/${encodeURIComponent(pluginId)}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(input),
    });
  }

  async listAgents(botAlias: string): Promise<AgentListResult> {
    const data = await this.requestJson<{ items: RawAgentSummary[] }>(
      `/api/bots/${encodeURIComponent(botAlias)}/agents`,
    );
    return { items: (data.items || []).map(mapAgentSummary) };
  }

  async createAgent(botAlias: string, input: AgentInput): Promise<AgentMutationResult> {
    const data = await this.requestJson<{ agent: RawAgentSummary }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/agents`,
      {
        method: "POST",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify(mapAgentInput(input)),
      },
    );
    return { agent: mapAgentSummary(data.agent) };
  }

  async updateAgent(botAlias: string, agentId: string, input: AgentInput): Promise<AgentMutationResult> {
    const data = await this.requestJson<{ agent: RawAgentSummary }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/agents/${encodeURIComponent(agentId)}`,
      {
        method: "PATCH",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify(mapAgentInput(input)),
      },
    );
    return { agent: mapAgentSummary(data.agent) };
  }

  async deleteAgent(botAlias: string, agentId: string): Promise<void> {
    await this.requestJson(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/agents/${encodeURIComponent(agentId)}`,
      {
        method: "DELETE",
        headers: this.headers(),
      },
    );
  }

  async getClusterStatus(botAlias: string): Promise<ClusterStatus> {
    const data = await this.requestJson<unknown>(`/api/bots/${encodeURIComponent(botAlias)}/cluster/status`);
    return mapClusterStatus(data);
  }

  async getClusterTaskStatus(botAlias: string, runId: string): Promise<ClusterTaskStatus> {
    const params = new URLSearchParams({ include_output: "1" });
    const data = await this.requestJson<unknown>(
      `/api/bots/${encodeURIComponent(botAlias)}/cluster/runs/${encodeURIComponent(runId)}/tasks?${params.toString()}`,
    );
    return mapClusterTaskStatus(data);
  }

  async prepareClusterSetup(botAlias: string): Promise<ClusterSetupPrepareResult> {
    const data = await this.requestJson<unknown>(`/api/admin/bots/${encodeURIComponent(botAlias)}/cluster/setup/prepare`, {
      method: "POST",
      headers: this.headers(),
    });
    return mapClusterSetupPrepare(data);
  }

  async updateClusterConfig(botAlias: string, input: ClusterConfigUpdateInput): Promise<ClusterConfigUpdateResult> {
    const data = await this.requestJson<{ cluster?: unknown; status?: unknown }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/cluster/config`,
      {
        method: "POST",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({ cluster: mapClusterConfigInput(input) }),
      },
    );
    return {
      cluster: mapBotClusterConfig(data.cluster),
      status: mapClusterStatus(data.status),
    };
  }

  async getClusterTemplates(botAlias: string): Promise<ClusterTemplateListResult> {
    const data = await this.requestJson<{ templates?: unknown[] }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/cluster/templates`, {
      method: "GET",
      headers: this.headers(),
      cache: "no-store",
    });
    return { templates: (data.templates || []).map(mapClusterTemplateSummary) };
  }

  async getClusterBundleSchema(botAlias: string): Promise<ClusterBundleSchemaResult> {
    const data = await this.requestJson<Record<string, unknown>>(`/api/admin/bots/${encodeURIComponent(botAlias)}/cluster/schema`, {
      method: "GET",
      headers: this.headers(),
      cache: "no-store",
    });
    return {
      version: Number(data.version || 1),
      schema: data.schema && typeof data.schema === "object" ? data.schema as Record<string, unknown> : {},
      instructions: String(data.instructions || ""),
    };
  }

  async previewClusterTemplate(botAlias: string, templateId: string): Promise<ClusterBundlePreviewResult> {
    const data = await this.requestJson<unknown>(`/api/admin/bots/${encodeURIComponent(botAlias)}/cluster/templates/preview`, {
      method: "POST",
      headers: this.headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ template_id: templateId }),
    });
    return mapClusterBundlePreviewResult(data);
  }

  async applyClusterTemplate(botAlias: string, templateId: string, confirmOverwriteAgents: boolean): Promise<ClusterBundleApplyResult> {
    const data = await this.requestJson<unknown>(`/api/admin/bots/${encodeURIComponent(botAlias)}/cluster/templates/apply`, {
      method: "POST",
      headers: this.headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ template_id: templateId, confirm_overwrite_agents: confirmOverwriteAgents }),
    });
    return mapClusterBundleApplyResult(data);
  }

  async previewClusterConfigBundle(botAlias: string, bundle: unknown): Promise<ClusterBundlePreviewResult> {
    const data = await this.requestJson<unknown>(`/api/admin/bots/${encodeURIComponent(botAlias)}/cluster/config-bundle/preview`, {
      method: "POST",
      headers: this.headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ bundle }),
    });
    return mapClusterBundlePreviewResult(data);
  }

  async applyClusterConfigBundle(botAlias: string, bundle: unknown, confirmOverwriteAgents: boolean): Promise<ClusterBundleApplyResult> {
    const data = await this.requestJson<unknown>(`/api/admin/bots/${encodeURIComponent(botAlias)}/cluster/config-bundle/apply`, {
      method: "POST",
      headers: this.headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ bundle, confirm_overwrite_agents: confirmOverwriteAgents }),
    });
    return mapClusterBundleApplyResult(data);
  }

  async getBotOverview(botAlias: string, options: AgentScopedOptions = {}): Promise<BotOverview> {
    const params = new URLSearchParams();
    appendAgentParam(params, options.agentId);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<{
      bot: RawBotSummary & { assistant_runtime?: RawAssistantRuntimeSnapshot | null };
      session: {
        working_dir: string;
        message_count: number;
        history_count: number;
        is_processing: boolean;
        running_reply?: RawRunningReply | null;
      };
      agents?: RawAgentSummary[];
      active_agent_id?: string;
      busy_agent_ids?: string[];
      active_cluster_run?: RawActiveClusterRun | null;
    }>(`/api/bots/${encodeURIComponent(botAlias)}${suffix}`);

    const summary = mapBotSummary(data.bot, data.session.is_processing);
    const overview: BotOverview = {
      ...summary,
      workingDir: data.session.working_dir || summary.workingDir,
      messageCount: data.session.message_count,
      historyCount: data.session.history_count,
      isProcessing: data.session.is_processing,
      runningReply: mapRunningReply(data.session.running_reply),
      assistantRuntime: mapAssistantRuntimeSnapshot(data.bot.assistant_runtime),
      agents: (data.agents || []).map(mapAgentSummary),
      activeClusterRun: mapActiveClusterRun(data.active_cluster_run),
      activeAgentId: String(data.active_agent_id || options.agentId || "main"),
      busyAgentIds: summary.busyAgentIds || [],
      busyAgentNames: summary.busyAgentNames || [],
      busyAgentCount: summary.busyAgentCount || 0,
    };
    if (data.bot.bot_mode) {
      overview.botMode = data.bot.bot_mode;
    }
    return overview;
  }

  async listMessages(botAlias: string, options: AgentScopedOptions = {}): Promise<ChatMessage[]> {
    const params = new URLSearchParams();
    appendAgentParam(params, options.agentId);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<{ items: RawHistoryItem[] }>(`/api/bots/${encodeURIComponent(botAlias)}/history${suffix}`);
    return data.items.map((item, index) => mapChatMessage(item, index));
  }

  async listConversations(botAlias: string, query = "", options: AgentScopedOptions = {}): Promise<ConversationListResult> {
    const params = new URLSearchParams({ limit: "80" });
    if (query.trim()) {
      params.set("q", query.trim());
    }
    appendAgentParam(params, options.agentId);
    const data = await this.requestJson<{ items: RawConversationSummary[]; active_conversation_id: string }>(
      `/api/bots/${encodeURIComponent(botAlias)}/conversations?${params.toString()}`,
    );
    return {
      items: data.items.map(mapConversationSummary),
      activeConversationId: String(data.active_conversation_id || ""),
    };
  }

  async createConversation(botAlias: string, title = "", options: AgentScopedOptions = {}): Promise<ConversationSelectResult> {
    const data = await this.requestJson<{ conversation: RawConversationSummary; messages: RawHistoryItem[] }>(
      `/api/bots/${encodeURIComponent(botAlias)}/conversations`,
      {
        method: "POST",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          title,
          ...(options.agentId ? { agent_id: options.agentId } : {}),
        }),
      },
    );
    return {
      conversation: mapConversationSummary(data.conversation),
      messages: data.messages.map((item, index) => mapChatMessage(item, index)),
    };
  }

  async selectConversation(botAlias: string, conversationId: string, options: AgentScopedOptions = {}): Promise<ConversationSelectResult> {
    const data = await this.requestJson<{ conversation: RawConversationSummary; messages: RawHistoryItem[] }>(
      `/api/bots/${encodeURIComponent(botAlias)}/conversations/${encodeURIComponent(conversationId)}/select`,
      {
        method: "POST",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify(options.agentId ? { agent_id: options.agentId } : {}),
      },
    );
    return {
      conversation: mapConversationSummary(data.conversation),
      messages: data.messages.map((item, index) => mapChatMessage(item, index)),
    };
  }

  async listMessageDelta(botAlias: string, afterId: string, limit = 50, options: AgentScopedOptions = {}): Promise<HistoryDeltaResult> {
    const params = new URLSearchParams({
      after_id: afterId,
      limit: String(limit),
    });
    appendAgentParam(params, options.agentId);
    const data = await this.requestJson<{ items: RawHistoryItem[]; reset: boolean }>(
      `/api/bots/${encodeURIComponent(botAlias)}/history/delta?${params.toString()}`,
    );
    return {
      items: data.items.map((item, index) => mapChatMessage(item, index)),
      reset: Boolean(data.reset),
    };
  }

  async getMessageTrace(botAlias: string, messageId: string, options: AgentScopedOptions = {}): Promise<ChatTraceDetails> {
    const params = new URLSearchParams();
    appendAgentParam(params, options.agentId);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<RawChatTraceDetails>(
      `/api/bots/${encodeURIComponent(botAlias)}/history/${encodeURIComponent(messageId)}/trace${suffix}`,
    );
    return mapChatTraceDetails(data);
  }

  async sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
    onTrace?: (trace: ChatTraceEvent) => void,
    options?: ChatSendOptions,
  ): Promise<ChatMessage> {
    const response = await fetch(`/api/bots/${encodeURIComponent(botAlias)}/chat/stream`, {
      method: "POST",
      headers: this.headers({
        "Content-Type": "application/json",
      }),
      body: JSON.stringify({
        message: text,
        ...(options?.taskMode ? { task_mode: options.taskMode } : {}),
        ...(options?.taskPayload ? { task_payload: options.taskPayload } : {}),
        ...(options?.visibleText ? { visible_text: options.visibleText } : {}),
        ...(options?.agentId ? { agent_id: options.agentId } : {}),
        ...(options?.cluster ? { cluster: true } : {}),
        ...(options?.mentions ? {
          mentions: options.mentions.map((mention) => ({
            agent_id: mention.agentId,
            label: mention.label,
            start: mention.start,
            end: mention.end,
          })),
        } : {}),
      }),
    });

    if (!response.ok || !response.body) {
      let message = "发送消息失败";
      try {
        const payload = (await response.json()) as JsonEnvelope<unknown>;
        message = payload.error?.message || message;
      } catch {
        // ignore parse failures
      }
      throw new Error(message);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let streamedText = "";
    let finalText = "";
    let finalElapsedSeconds: number | undefined;
    let finalMessage: ChatMessage | null = null;
    const streamedTrace: ChatTraceEvent[] = [];
    let streamFinished = false;

    while (!streamFinished) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex >= 0) {
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);

        const event = parseSseBlock(block);
        if (!event) {
          separatorIndex = buffer.indexOf("\n\n");
          continue;
        }

        if (event.type === "delta" && event.text) {
          streamedText += event.text;
          onChunk(event.text);
        } else if (event.type === "meta") {
          const clusterRunId = typeof event.cluster_run_id === "string" ? event.cluster_run_id : "";
          if (clusterRunId) {
            onStatus?.({ clusterRunId });
          }
        } else if (event.type === "status") {
          if (typeof event.elapsed_seconds === "number") {
            finalElapsedSeconds = event.elapsed_seconds;
          }
          onStatus?.({
            elapsedSeconds: event.elapsed_seconds,
            previewText: event.preview_text,
          });
        } else if (event.type === "trace") {
          const traceEvent = mapTraceEvent(event.event);
          if (traceEvent) {
            streamedTrace.push(traceEvent);
            onTrace?.(traceEvent);
          }
        } else if (event.type === "done") {
          if (event.message) {
            finalMessage = mapChatMessage(event.message, 0);
            finalMessage.meta = mergeMessageMeta(undefined, finalMessage.meta, streamedTrace);
            finalText = finalMessage.text;
          } else {
            finalText = event.output || streamedText;
          }
          if (typeof event.elapsed_seconds === "number") {
            finalElapsedSeconds = event.elapsed_seconds;
          }
          streamFinished = true;
          await reader.cancel().catch(() => undefined);
          break;
        } else if (event.type === "error") {
          throw new Error(event.message || "流式响应失败");
        }

        separatorIndex = buffer.indexOf("\n\n");
      }
    }

    if (finalMessage) {
      return {
        ...finalMessage,
        elapsedSeconds: finalMessage.elapsedSeconds ?? finalElapsedSeconds,
        meta: mergeMessageMeta(undefined, finalMessage.meta, streamedTrace),
      };
    }

    const messageText = finalText || streamedText;
    const meta = mergeMessageMeta(undefined, undefined, streamedTrace);
    return {
      id: `assistant-${Date.now()}`,
      role: "assistant",
      text: messageText,
      createdAt: new Date().toISOString(),
      state: "done",
      ...(typeof finalElapsedSeconds === "number" ? { elapsedSeconds: finalElapsedSeconds } : {}),
      ...(meta ? { meta } : {}),
    };
  }

  async getDebugProfile(botAlias: string): Promise<DebugProfile | null> {
    const data = await this.requestJson<Record<string, unknown> | null>(`/api/bots/${encodeURIComponent(botAlias)}/debug/profile`);
    if (!data) {
      return null;
    }
    const rawSourceMaps = data.sourceMaps || data.source_maps;
    return {
      specVersion: Number(data.specVersion || data.spec_version || 1),
      language: String(data.language || "cpp"),
      configName: String(data.config_name || ""),
      program: String(data.program || ""),
      cwd: String(data.cwd || ""),
      miDebuggerPath: String(data.mi_debugger_path || ""),
      compileCommands: typeof data.compile_commands === "string" ? data.compile_commands : undefined,
      prepareCommand: String(data.prepare_command || ".\\debug.bat"),
      stopAtEntry: Boolean(data.stop_at_entry),
      setupCommands: Array.isArray(data.setup_commands) ? data.setup_commands.map((item) => String(item)) : [],
      remoteHost: String(data.remote_host || ""),
      remoteUser: String(data.remote_user || ""),
      remoteDir: String(data.remote_dir || ""),
      remotePort: Number(data.remote_port || 0),
      target: data.target && typeof data.target === "object" ? data.target as Record<string, unknown> : undefined,
      prepare: data.prepare && typeof data.prepare === "object" ? data.prepare as Record<string, unknown> : undefined,
      remote: data.remote && typeof data.remote === "object" ? data.remote as Record<string, unknown> : undefined,
      gdb: data.gdb && typeof data.gdb === "object" ? data.gdb as Record<string, unknown> : undefined,
      sourceMaps: Array.isArray(rawSourceMaps)
        ? rawSourceMaps
          .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
          .map((item) => ({ remote: String(item.remote || ""), local: String(item.local || "") }))
        : undefined,
      capabilities: data.capabilities && typeof data.capabilities === "object" ? data.capabilities as Record<string, boolean> : undefined,
    };
  }

  async getDebugState(botAlias: string): Promise<DebugState> {
    const data = await this.requestJson<Record<string, unknown>>(`/api/bots/${encodeURIComponent(botAlias)}/debug/state`);
    return mapDebugState(data);
  }

  async getTerminalSession(ownerId: string): Promise<PersistentTerminalSnapshot> {
    const params = new URLSearchParams({ owner_id: ownerId });
    const data = await this.requestJson<RawPersistentTerminalSnapshot>(`/api/terminal/session?${params.toString()}`);
    return mapPersistentTerminalSnapshot(data);
  }

  async rebuildTerminalSession(ownerId: string, cwd: string, shell = "auto"): Promise<PersistentTerminalSnapshot> {
    const data = await this.requestJson<RawPersistentTerminalSnapshot>("/api/terminal/session/rebuild", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        owner_id: ownerId,
        cwd,
        shell,
      }),
    });
    return mapPersistentTerminalSnapshot(data);
  }

  async closeTerminalSession(ownerId: string): Promise<PersistentTerminalSnapshot> {
    const data = await this.requestJson<RawPersistentTerminalSnapshot>("/api/terminal/session/close", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        owner_id: ownerId,
      }),
    });
    return mapPersistentTerminalSnapshot(data);
  }

  async getTerminalActionsConfig(botAlias: string): Promise<TerminalActionsConfig> {
    return this.requestJson<TerminalActionsConfig>(
      `/api/bots/${encodeURIComponent(botAlias)}/terminal-actions/config`,
      { method: "GET" },
    );
  }

  async saveTerminalActionsConfig(
    botAlias: string,
    config: TerminalActionsEditableConfig,
    expectedMtimeNs: string,
  ): Promise<TerminalActionsConfig> {
    return this.requestJson<TerminalActionsConfig>(
      `/api/bots/${encodeURIComponent(botAlias)}/terminal-actions/config`,
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ config, expectedMtimeNs }),
      },
    );
  }

  async runTerminalAction(
    botAlias: string,
    actionId: string,
    input: TerminalActionRunInput,
  ): Promise<TerminalActionRunResult> {
    const data = await this.requestJson<RawTerminalActionRunResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/terminal-actions/${encodeURIComponent(actionId)}/run`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(input),
      },
    );
    return mapTerminalActionRunResult(data);
  }

  async getCurrentPath(botAlias: string): Promise<string> {
    const data = await this.requestJson<{ working_dir: string }>(`/api/bots/${encodeURIComponent(botAlias)}/pwd`);
    return data.working_dir;
  }

  async listFiles(botAlias: string, path?: string): Promise<DirectoryListing> {
    const params = new URLSearchParams();
    if (path && path.trim()) {
      params.set("path", path.trim());
    }
    const suffix = params.size > 0 ? `?${params.toString()}` : "";
    const data = await this.requestJson<{ working_dir: string; entries: RawFileEntry[]; is_virtual_root?: boolean }>(
      `/api/bots/${encodeURIComponent(botAlias)}/ls${suffix}`,
    );
    return {
      workingDir: data.working_dir,
      entries: data.entries.map(mapFileEntry),
      ...(data.is_virtual_root ? { isVirtualRoot: true } : {}),
    };
  }

  async revealFileTreePath(botAlias: string, path: string): Promise<FileTreeRevealResult> {
    const data = await this.requestJson<{
      root_path: string;
      highlight_path: string;
      expanded_paths?: string[];
      branches: Record<string, RawFileEntry[]>;
    }>(`/api/bots/${encodeURIComponent(botAlias)}/files/reveal`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ path }),
    });
    return {
      rootPath: data.root_path,
      highlightPath: data.highlight_path,
      expandedPaths: Array.isArray(data.expanded_paths) ? data.expanded_paths.map((item) => String(item)) : [],
      branches: Object.fromEntries(
        Object.entries(data.branches || {}).map(([branchPath, entries]) => [
          branchPath,
          entries.map(mapFileEntry),
        ]),
      ),
    };
  }

  async changeDirectory(botAlias: string, path: string): Promise<string> {
    const data = await this.requestJson<{ working_dir: string }>(`/api/bots/${encodeURIComponent(botAlias)}/cd`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ path }),
    });
    return data.working_dir;
  }

  async createDirectory(botAlias: string, name: string, parentPath?: string): Promise<void> {
    await this.requestJson(`/api/bots/${encodeURIComponent(botAlias)}/files/mkdir`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name,
        ...(parentPath ? { parent_path: parentPath } : {}),
      }),
    });
  }

  async deletePath(botAlias: string, path: string): Promise<void> {
    await this.requestJson(`/api/bots/${encodeURIComponent(botAlias)}/files/delete`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ path }),
    });
  }

  async resolveFileOpenTarget(botAlias: string, path: string): Promise<FileOpenTarget> {
    return this.requestJson<FileOpenTarget>(`/api/bots/${encodeURIComponent(botAlias)}/plugins/resolve-file-target`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ path }),
    });
  }

  async readFile(botAlias: string, filename: string): Promise<FileReadResult> {
    const params = new URLSearchParams({
      filename,
      mode: "head",
      lines: "80",
    });
    const data = await this.requestJson<RawFileReadResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/read?${params.toString()}`);
    const result: FileReadResult = {
      content: data.content || "",
      mode: data.mode || "head",
      workingDir: data.working_dir || "",
      fileSizeBytes: data.file_size_bytes,
      isFullContent: data.is_full_content,
      lastModifiedNs: typeof data.last_modified_ns === "undefined" ? undefined : String(data.last_modified_ns),
    };
    if (data.preview_kind) {
      result.previewKind = data.preview_kind;
    }
    if (data.content_type) {
      result.contentType = data.content_type;
    }
    if (data.content_base64) {
      result.contentBase64 = data.content_base64;
    }
    return result;
  }

  async readFileFull(botAlias: string, filename: string): Promise<FileReadResult> {
    const params = new URLSearchParams({
      filename,
      mode: "cat",
      lines: "0",
    });
    const data = await this.requestJson<RawFileReadResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/read?${params.toString()}`);
    const result: FileReadResult = {
      content: data.content || "",
      mode: data.mode || "cat",
      workingDir: data.working_dir || "",
      fileSizeBytes: data.file_size_bytes,
      isFullContent: data.is_full_content ?? true,
      lastModifiedNs: typeof data.last_modified_ns === "undefined" ? undefined : String(data.last_modified_ns),
    };
    if (data.preview_kind) {
      result.previewKind = data.preview_kind;
    }
    if (data.content_type) {
      result.contentType = data.content_type;
    }
    if (data.content_base64) {
      result.contentBase64 = data.content_base64;
    }
    return result;
  }

  async openPluginView(
    botAlias: string,
    pluginId: string,
    viewId: string,
    input: Record<string, unknown>,
  ): Promise<PluginRenderResult> {
    return this.requestJson<PluginRenderResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/plugins/${encodeURIComponent(pluginId)}/views/${encodeURIComponent(viewId)}/open`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ input }),
      },
    );
  }

  async queryPluginViewWindow(
    botAlias: string,
    pluginId: string,
    sessionId: string,
    request: PluginViewWindowRequest,
    signal?: AbortSignal,
  ): Promise<PluginViewWindowPayload> {
    return this.requestJson<PluginViewWindowPayload>(
      `/api/bots/${encodeURIComponent(botAlias)}/plugins/${encodeURIComponent(pluginId)}/sessions/${encodeURIComponent(sessionId)}/window`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(request),
        signal,
      },
    );
  }

  async disposePluginViewSession(botAlias: string, pluginId: string, sessionId: string): Promise<void> {
    await this.requestJson<{ disposed: boolean }>(
      `/api/bots/${encodeURIComponent(botAlias)}/plugins/${encodeURIComponent(pluginId)}/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "DELETE",
      },
    );
  }

  async invokePluginAction(
    botAlias: string,
    pluginId: string,
    input: PluginActionInvokeInput,
  ): Promise<PluginActionResult> {
    return this.requestJson<PluginActionResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/plugins/${encodeURIComponent(pluginId)}/actions/invoke`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(input),
      },
    );
  }

  async downloadPluginArtifact(botAlias: string, artifactId: string, filename: string): Promise<void> {
    const response = await fetch(
      `/api/bots/${encodeURIComponent(botAlias)}/plugins/artifacts/${encodeURIComponent(artifactId)}`,
      {
        headers: this.headers(),
      },
    );
    if (!response.ok) {
      throw new Error("下载插件产物失败");
    }
    const blob = await response.blob();
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(downloadUrl);
  }

  async writeFile(botAlias: string, path: string, content: string, expectedMtimeNs?: string): Promise<FileWriteResult> {
    const data = await this.requestJson<RawFileWriteResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/write`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        path,
        content,
        expected_mtime_ns: expectedMtimeNs,
      }),
    });
    return {
      path: data.path,
      fileSizeBytes: data.file_size_bytes,
      lastModifiedNs: String(data.last_modified_ns),
    };
  }

  async createTextFile(botAlias: string, filename: string, content = "", parentPath?: string): Promise<FileCreateResult> {
    const data = await this.requestJson<RawFileCreateResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/create`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        filename,
        content,
        ...(parentPath ? { parent_path: parentPath } : {}),
      }),
    });
    return {
      path: data.path,
      fileSizeBytes: data.file_size_bytes,
      lastModifiedNs: String(data.last_modified_ns),
    };
  }

  async renamePath(botAlias: string, path: string, newName: string): Promise<FileRenameResult> {
    const data = await this.requestJson<RawFileRenameResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/rename`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ path, new_name: newName }),
    });
    return {
      oldPath: data.old_path,
      path: data.path,
    };
  }

  async copyPath(botAlias: string, path: string): Promise<FileCopyResult> {
    const data = await this.requestJson<RawFileCopyResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/copy`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ path }),
    });
    return {
      sourcePath: data.source_path,
      path: data.path,
      fileSizeBytes: data.file_size_bytes,
      lastModifiedNs: String(data.last_modified_ns),
    };
  }

  async movePath(botAlias: string, path: string, targetParentPath: string): Promise<FileMoveResult> {
    const data = await this.requestJson<RawFileMoveResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/move`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ path, target_parent_path: targetParentPath }),
    });
    return {
      oldPath: data.old_path,
      path: data.path,
    };
  }

  async quickOpenWorkspace(botAlias: string, query: string, limit = 50): Promise<WorkspaceQuickOpenResult> {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
    });
    return this.requestJson<WorkspaceQuickOpenResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/workspace/quick-open?${params.toString()}`,
    );
  }

  async searchWorkspace(
    botAlias: string,
    query: string,
    limit = 100,
    signal?: AbortSignal,
  ): Promise<WorkspaceSearchResult> {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
    });
    return this.requestJson<WorkspaceSearchResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/workspace/search?${params.toString()}`,
      { signal },
    );
  }

  async getWorkspaceOutline(botAlias: string, path: string): Promise<WorkspaceOutlineResult> {
    const params = new URLSearchParams({ path });
    return this.requestJson<WorkspaceOutlineResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/workspace/outline?${params.toString()}`,
    );
  }

  async resolveWorkspaceDefinition(
    botAlias: string,
    input: { path: string; line: number; column: number; symbol?: string },
  ): Promise<WorkspaceDefinitionResult> {
    const data = await this.requestJson<{
      items?: Array<{
        path: string;
        line: number;
        column?: number;
        match_kind?: "import" | "same_file" | "workspace_search";
        confidence?: number;
      }>;
    }>(`/api/bots/${encodeURIComponent(botAlias)}/workspace/resolve-definition`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(input),
    });
    return {
      items: (data.items || []).map((item) => ({
        path: item.path,
        line: item.line,
        ...(typeof item.column === "number" ? { column: item.column } : {}),
        matchKind: item.match_kind || "workspace_search",
        confidence: typeof item.confidence === "number" ? item.confidence : 0,
      })),
    };
  }

  async uploadChatAttachment(botAlias: string, file: File): Promise<ChatAttachmentUploadResult> {
    const formData = new FormData();
    formData.append("file", file);
    const data = await this.requestJson<RawChatAttachmentUploadResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/chat/attachments`,
      {
        method: "POST",
        body: formData,
      },
    );
    return mapChatAttachmentUploadResult(data);
  }

  async deleteChatAttachment(botAlias: string, savedPath: string): Promise<ChatAttachmentDeleteResult> {
    const data = await this.requestJson<RawChatAttachmentDeleteResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/chat/attachments/delete`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          saved_path: savedPath,
        }),
      },
    );
    return mapChatAttachmentDeleteResult(data);
  }

  async uploadFile(botAlias: string, file: File): Promise<void> {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`/api/bots/${encodeURIComponent(botAlias)}/files/upload`, {
      method: "POST",
      headers: this.headers(),
      body: formData,
    });
    if (!response.ok) {
      throw new Error("上传失败");
    }
  }

  async downloadFile(botAlias: string, filename: string): Promise<void> {
    const params = new URLSearchParams({ filename });
    const response = await fetch(`/api/bots/${encodeURIComponent(botAlias)}/files/download?${params.toString()}`, {
      headers: this.headers(),
    });
    if (!response.ok) {
      throw new Error("下载失败");
    }
    const blob = await response.blob();
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(downloadUrl);
  }

  async resetSession(botAlias: string): Promise<void> {
    await this.requestJson(`/api/bots/${encodeURIComponent(botAlias)}/reset`, {
      method: "POST",
    });
  }

  async killTask(botAlias: string): Promise<string> {
    const data = await this.requestJson<{ message?: string }>(`/api/bots/${encodeURIComponent(botAlias)}/kill`, {
      method: "POST",
    });
    return data.message || "已发送终止任务请求";
  }

  async restartService(): Promise<void> {
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timeoutId = controller
      ? window.setTimeout(() => {
          controller.abort();
        }, RESTART_SERVICE_REQUEST_TIMEOUT_MS)
      : null;
    try {
      const response = await fetch("/api/admin/restart", {
        method: "POST",
        cache: "no-store",
        keepalive: true,
        headers: this.headers(),
        signal: controller?.signal,
      });
      try {
        const payload = (await response.json()) as JsonEnvelope<{ restart_requested: boolean }>;
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error?.message || "请求失败");
        }
      } catch (error) {
        if (!response.ok) {
          throw error;
        }
      }
    } catch (error) {
      if (error instanceof TypeError) {
        return;
      }
      if (typeof DOMException !== "undefined" && error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      throw error;
    } finally {
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    }
  }

  async getGitProxySettings(): Promise<GitProxySettings> {
    const data = await this.requestJson<RawGitProxySettings>("/api/admin/git-proxy");
    return mapGitProxySettings(data);
  }

  async updateGitProxySettings(address: string): Promise<GitProxySettings> {
    const data = await this.requestJson<RawGitProxySettings>("/api/admin/git-proxy", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ address }),
    });
    return mapGitProxySettings(data);
  }

  async getUpdateStatus(): Promise<AppUpdateStatus> {
    const data = await this.requestJson<RawAppUpdateStatus>("/api/admin/update");
    return mapAppUpdateStatus(data);
  }

  async setUpdateEnabled(enabled: boolean): Promise<AppUpdateStatus> {
    const data = await this.requestJson<RawAppUpdateStatus>("/api/admin/update", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ update_enabled: enabled }),
    });
    return mapAppUpdateStatus(data);
  }

  async checkForUpdate(): Promise<AppUpdateStatus> {
    const data = await this.requestJson<RawAppUpdateStatus>("/api/admin/update/check", {
      method: "POST",
    });
    return mapAppUpdateStatus(data);
  }

  async downloadUpdate(): Promise<AppUpdateStatus> {
    const data = await this.requestJson<RawAppUpdateStatus>("/api/admin/update/download", {
      method: "POST",
    });
    return mapAppUpdateStatus(data);
  }

  async downloadUpdateStream(onProgress: (event: AppUpdateDownloadProgress) => void): Promise<AppUpdateStatus> {
    const response = await fetch("/api/admin/update/download/stream", {
      method: "POST",
      headers: this.headers({
        "Content-Type": "application/json",
      }),
      body: JSON.stringify({}),
    });

    if (!response.ok || !response.body) {
      let message = "下载更新失败";
      try {
        const payload = (await response.json()) as JsonEnvelope<unknown>;
        message = payload.error?.message || message;
      } catch {
        // ignore parse failures
      }
      throw new Error(message);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalStatus: AppUpdateStatus | null = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex >= 0) {
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);

        const event = parseSseBlock(block);
        if (!event) {
          separatorIndex = buffer.indexOf("\n\n");
          continue;
        }

        if (event.type === "progress") {
          onProgress(mapAppUpdateDownloadProgress(event));
        } else if (event.type === "done" && event.status) {
          finalStatus = mapAppUpdateStatus(event.status);
        } else if (event.type === "error") {
          throw new Error(event.message || "下载更新失败");
        }

        separatorIndex = buffer.indexOf("\n\n");
      }
    }

    if (!finalStatus) {
      throw new Error("更新下载已中断");
    }
    return finalStatus;
  }

  async getGitOverview(botAlias: string): Promise<GitOverview> {
    const data = await this.requestJson<RawGitOverview>(`/api/bots/${encodeURIComponent(botAlias)}/git`);
    return mapGitOverview(data);
  }

  async getGitTreeStatus(botAlias: string): Promise<GitTreeStatus> {
    const data = await this.requestJson<RawGitTreeStatus>(`/api/bots/${encodeURIComponent(botAlias)}/git/tree-status`);
    return mapGitTreeStatus(data);
  }

  async initGitRepository(botAlias: string): Promise<GitOverview> {
    const data = await this.requestJson<RawGitOverview>(`/api/bots/${encodeURIComponent(botAlias)}/git/init`, {
      method: "POST",
    });
    return mapGitOverview(data);
  }

  async getGitDiff(botAlias: string, path: string, staged = false): Promise<GitDiffPayload> {
    const params = new URLSearchParams({
      path,
      staged: staged ? "true" : "false",
    });
    const data = await this.requestJson<RawGitDiffPayload>(`/api/bots/${encodeURIComponent(botAlias)}/git/diff?${params.toString()}`);
    return mapGitDiffPayload(data);
  }

  async stageGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/stage`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ paths }),
    });
    return mapGitActionResult(data);
  }

  async unstageGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/unstage`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ paths }),
    });
    return mapGitActionResult(data);
  }

  async discardGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/discard`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ paths }),
    });
    return mapGitActionResult(data);
  }

  async discardAllGitChanges(botAlias: string): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/discard-all`, {
      method: "POST",
    });
    return mapGitActionResult(data);
  }

  async commitGitChanges(botAlias: string, message: string): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/commit`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message }),
    });
    return mapGitActionResult(data);
  }

  async fetchGitRemote(botAlias: string): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/fetch`, {
      method: "POST",
    });
    return mapGitActionResult(data);
  }

  async pullGitRemote(botAlias: string): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/pull`, {
      method: "POST",
    });
    return mapGitActionResult(data);
  }

  async pushGitRemote(botAlias: string): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/push`, {
      method: "POST",
    });
    return mapGitActionResult(data);
  }

  async stashGitChanges(botAlias: string): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/stash`, {
      method: "POST",
    });
    return mapGitActionResult(data);
  }

  async popGitStash(botAlias: string): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/stash/pop`, {
      method: "POST",
    });
    return mapGitActionResult(data);
  }

  async listGitBranches(botAlias: string): Promise<GitBranchList> {
    const data = await this.requestJson<RawGitBranchList>(`/api/bots/${encodeURIComponent(botAlias)}/git/branches`);
    return mapGitBranchList(data);
  }

  async createGitBranch(botAlias: string, name: string, startPoint = ""): Promise<GitBranchList> {
    const data = await this.requestJson<RawGitBranchList>(`/api/bots/${encodeURIComponent(botAlias)}/git/branches`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name, start_point: startPoint }),
    });
    return mapGitBranchList(data);
  }

  async switchGitBranch(botAlias: string, name: string): Promise<GitBranchList> {
    const data = await this.requestJson<RawGitBranchList>(`/api/bots/${encodeURIComponent(botAlias)}/git/branches/switch`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name }),
    });
    return mapGitBranchList(data);
  }

  async listGitStashes(botAlias: string): Promise<GitStashList> {
    const data = await this.requestJson<RawGitStashList>(`/api/bots/${encodeURIComponent(botAlias)}/git/stashes`);
    return mapGitStashList(data);
  }

  async applyGitStash(botAlias: string, ref: string): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/stashes/apply`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref }),
    });
    return mapGitActionResult(data);
  }

  async dropGitStash(botAlias: string, ref: string): Promise<GitActionResult> {
    const data = await this.requestJson<RawGitActionResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/stashes/drop`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref }),
    });
    return mapGitActionResult(data);
  }

  async getGitBlame(botAlias: string, path: string): Promise<GitBlamePayload> {
    const params = new URLSearchParams({ path });
    const data = await this.requestJson<RawGitBlamePayload>(`/api/bots/${encodeURIComponent(botAlias)}/git/blame?${params.toString()}`);
    return mapGitBlamePayload(data);
  }

  async updateBotCli(botAlias: string, cliType: string, cliPath: string): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/cli`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ cli_type: cliType, cli_path: cliPath }),
    });
    return mapBotSummary(data.bot, Boolean(data.bot.is_processing));
  }

  async updateBotWorkdir(
    botAlias: string,
    workingDir: string,
    options: UpdateBotWorkdirOptions = {},
  ): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/workdir`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        working_dir: workingDir,
        force_reset: Boolean(options.forceReset),
      }),
    });
    return mapBotSummary(data.bot, Boolean(data.bot.is_processing));
  }

  async updateBotAvatar(botAlias: string, avatarName: string): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/avatar`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ avatar_name: avatarName }),
    });
    return mapBotSummary(data.bot, Boolean(data.bot.is_processing));
  }

  async listAssistantProposals(botAlias: string, status?: string): Promise<AssistantProposal[]> {
    const params = new URLSearchParams();
    if (status) {
      params.set("status", status);
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<{ items: RawAssistantProposal[] }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/proposals${suffix}`,
    );
    return (data.items || []).map(mapAssistantProposal);
  }

  async listAssistantUpgradeTargets(botAlias: string): Promise<AssistantUpgradeTarget[]> {
    const data = await this.requestJson<{ items: RawAssistantUpgradeTarget[] }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/upgrade-targets`,
    );
    return (data.items || []).map(mapAssistantUpgradeTarget);
  }

  async getAssistantProposal(botAlias: string, proposalId: string): Promise<AssistantProposalDetail> {
    const data = await this.requestJson<RawAssistantProposalDetail>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/proposals/${encodeURIComponent(proposalId)}`,
    );
    return mapAssistantProposalDetail(data);
  }

  async getAssistantProposalApplyLog(botAlias: string, proposalId: string): Promise<AssistantUpgradeApplyLog> {
    const data = await this.requestJson<RawAssistantUpgradeApplyLog>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/proposals/${encodeURIComponent(proposalId)}/apply-log`,
    );
    return mapAssistantUpgradeApplyLog(data);
  }

  async approveAssistantProposal(botAlias: string, proposalId: string): Promise<AssistantProposal> {
    const data = await this.requestJson<RawAssistantProposal>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/proposals/${encodeURIComponent(proposalId)}/approve`,
      {
        method: "POST",
      },
    );
    return mapAssistantProposal(data);
  }

  async generateAssistantProposalPatch(
    botAlias: string,
    proposalId: string,
    input: { targetAlias: string; regenerate?: boolean },
  ): Promise<AssistantPatchMetadata> {
    const data = await this.requestJson<RawAssistantPatchMetadata>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/proposals/${encodeURIComponent(proposalId)}/patch`,
      {
        method: "POST",
        body: JSON.stringify({
          target_alias: input.targetAlias,
          regenerate: Boolean(input.regenerate),
        }),
      },
    );
    return mapAssistantPatchMetadata(data);
  }

  async generateAssistantProposalPatchStream(
    botAlias: string,
    proposalId: string,
    input: { targetAlias: string; regenerate?: boolean },
    handlers?: AssistantPatchGenerationHandlers,
  ): Promise<AssistantPatchMetadata> {
    const response = await fetch(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/proposals/${encodeURIComponent(proposalId)}/patch/stream`,
      {
        method: "POST",
        headers: this.headers({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          target_alias: input.targetAlias,
          regenerate: Boolean(input.regenerate),
        }),
      },
    );

    if (!response.ok || !response.body) {
      let message = "生成 patch 失败";
      try {
        const payload = (await response.json()) as JsonEnvelope<unknown>;
        message = payload.error?.message || message;
      } catch {
        // ignore parse failures
      }
      throw new Error(message);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalMetadata: AssistantPatchMetadata | null = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex >= 0) {
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);

        const event = parseSseBlock(block);
        if (!event) {
          separatorIndex = buffer.indexOf("\n\n");
          continue;
        }

        if (event.type === "status") {
          handlers?.onStatus?.({
            phase: typeof event.phase === "string" ? event.phase : undefined,
            message: typeof event.message === "string" ? event.message : undefined,
            lifecycle: typeof event.lifecycle === "string" ? event.lifecycle : undefined,
          });
        } else if (event.type === "log" && typeof event.text === "string" && event.text) {
          handlers?.onLog?.(event.text);
        } else if (event.type === "trace") {
          const traceEvent = mapTraceEvent(event.event);
          if (traceEvent) {
            handlers?.onTrace?.(traceEvent);
          }
        } else if (event.type === "done" && event.metadata) {
          finalMetadata = mapAssistantPatchMetadata(event.metadata);
        } else if (event.type === "error") {
          throw new Error(event.message || "生成 patch 失败");
        }

        separatorIndex = buffer.indexOf("\n\n");
      }
    }

    if (!finalMetadata) {
      throw new Error("patch 生成连接已断开，请到 Proposal 详情查看生成状态");
    }
    return finalMetadata;
  }

  async approveAssistantProposalPatch(botAlias: string, proposalId: string): Promise<AssistantPatchMetadata> {
    const data = await this.requestJson<RawAssistantPatchMetadata>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/proposals/${encodeURIComponent(proposalId)}/patch/approve`,
      {
        method: "POST",
      },
    );
    return mapAssistantPatchMetadata(data);
  }

  async rejectAssistantProposal(botAlias: string, proposalId: string): Promise<AssistantProposal> {
    const data = await this.requestJson<RawAssistantProposal>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/proposals/${encodeURIComponent(proposalId)}/reject`,
      {
        method: "POST",
      },
    );
    return mapAssistantProposal(data);
  }

  async applyAssistantUpgrade(botAlias: string, proposalId: string): Promise<AssistantUpgradeApplyResult> {
    const data = await this.requestJson<RawAssistantUpgradeApplyResult>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/upgrades/${encodeURIComponent(proposalId)}/apply`,
      {
        method: "POST",
      },
    );
    return mapAssistantUpgradeApplyResult(data);
  }

  async dryRunAssistantUpgrade(botAlias: string, proposalId: string): Promise<AssistantUpgradeDryRunResult> {
    const data = await this.requestJson<RawAssistantUpgradeDryRunResult>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/upgrades/${encodeURIComponent(proposalId)}/dry-run`,
      {
        method: "POST",
      },
    );
    return mapAssistantUpgradeDryRunResult(data);
  }

  async searchAssistantMemories(
    botAlias: string,
    query: string,
    options: AssistantMemorySearchOptions = {},
  ): Promise<AssistantMemorySearchResult> {
    const params = new URLSearchParams({
      query,
    });
    if (typeof options.userId === "number") {
      params.set("user_id", String(options.userId));
    }
    if (typeof options.limit === "number") {
      params.set("limit", String(options.limit));
    }
    if (options.kinds?.length) {
      params.set("kinds", options.kinds.join(","));
    }
    if (options.scopes?.length) {
      params.set("scopes", options.scopes.join(","));
    }
    if (options.includeInvalidated) {
      params.set("include_invalidated", "true");
    }
    const data = await this.requestJson<{ items: RawAssistantMemorySearchItem[] }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/memory/search?${params.toString()}`,
    );
    return mapAssistantMemorySearchResult(data);
  }

  async bulkInvalidateAssistantMemories(
    botAlias: string,
    memoryIds: string[],
    reason: string,
  ): Promise<AssistantMemoryBulkInvalidateResult> {
    const data = await this.requestJson<{ invalidated?: number; missing?: string[]; reason?: string }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/memory/bulk-invalidate`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ memory_ids: memoryIds, reason }),
      },
    );
    return {
      invalidated: Number(data.invalidated || 0),
      missing: data.missing || [],
      reason: data.reason || "",
    };
  }

  async invalidateAssistantMemory(
    botAlias: string,
    memoryId: string,
    reason: string,
  ): Promise<AssistantMemoryInvalidateResult> {
    const data = await this.requestJson<{ memory_id?: string; invalidated?: boolean; reason?: string }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/memory/${encodeURIComponent(memoryId)}/invalidate`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ reason }),
      },
    );
    return mapAssistantMemoryInvalidateResult(data);
  }

  async reindexAssistantMemory(
    botAlias: string,
    options: { userId?: number; force?: boolean } = {},
  ): Promise<AssistantMemoryReindexResult> {
    const data = await this.requestJson<{
      working?: { indexed_count?: number; memory_ids?: string[] };
      knowledge?: { indexed_count?: number; memory_ids?: string[] };
    }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/memory/reindex`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...(typeof options.userId === "number" ? { user_id: options.userId } : {}),
        ...(typeof options.force === "boolean" ? { force: options.force } : {}),
      }),
    });
    return mapAssistantMemoryReindexResult(data);
  }

  async runAssistantMemoryEval(
    botAlias: string,
    input: { userId?: number; cases: Array<{ query: string; expectedMemoryKind: string; expectedHitTerms: string[]; mustNotHitTerms: string[] }> },
  ): Promise<AssistantMemoryEvalRun> {
    const data = await this.requestJson<{ metrics?: { hit_at_5?: number; stale_recall_rate?: number }; report_path?: string }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/evals/memory/run`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ...(typeof input.userId === "number" ? { user_id: input.userId } : {}),
          cases: input.cases.map((item) => ({
            query: item.query,
            expected_memory_kind: item.expectedMemoryKind,
            expected_hit_terms: item.expectedHitTerms,
            must_not_hit_terms: item.mustNotHitTerms,
          })),
        }),
      },
    );
    return mapAssistantMemoryEvalRun(data);
  }

  async listAssistantMemoryEvalReports(botAlias: string, limit = 10): Promise<AssistantMemoryEvalReport[]> {
    const params = new URLSearchParams({
      limit: String(limit),
    });
    const data = await this.requestJson<{ items: RawAssistantMemoryEvalReport[] }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/evals/memory/reports?${params.toString()}`,
    );
    return (data.items || []).map(mapAssistantMemoryEvalReport);
  }

  async getAssistantDiagnostics(
    botAlias: string,
    filters: AssistantDiagnosticsFilters = {},
  ): Promise<AssistantPerfDiagnostics> {
    const params = new URLSearchParams();
    if (typeof filters.limit === "number") {
      params.set("limit", String(filters.limit));
    } else {
      params.set("limit", "20");
    }
    if (filters.source) {
      params.set("source", filters.source);
    }
    if (filters.status) {
      params.set("status", filters.status);
    }
    if (typeof filters.userId === "number") {
      params.set("user_id", String(filters.userId));
    }
    if (filters.from) {
      params.set("from", filters.from);
    }
    if (filters.to) {
      params.set("to", filters.to);
    }
    const data = await this.requestJson<{ items?: RawAssistantPerfRecord[]; summary?: RawAssistantPerfSummary }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/diagnostics/perf?${params.toString()}`,
    );
    return mapAssistantPerfDiagnostics(data);
  }

  async listAssistantCronJobs(botAlias: string): Promise<AssistantCronJob[]> {
    const data = await this.requestJson<{ items: RawAssistantCronJob[] }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/cron/jobs`,
    );
    return (data.items || []).map(mapAssistantCronJob);
  }

  async createAssistantCronJob(botAlias: string, input: CreateAssistantCronJobInput): Promise<AssistantCronJob> {
    const data = await this.requestJson<{ job: RawAssistantCronJob }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/cron/jobs`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          id: input.id,
          enabled: input.enabled,
          title: input.title,
          schedule: {
            type: input.schedule.type,
            time: input.schedule.time,
            timezone: input.schedule.timezone,
            every_seconds: input.schedule.everySeconds,
            misfire_policy: input.schedule.misfirePolicy,
          },
          task: {
            prompt: input.task.prompt,
            mode: input.task.mode || "standard",
            lookback_hours: input.task.lookbackHours,
            history_limit: input.task.historyLimit,
            capture_limit: input.task.captureLimit,
            deliver_mode: input.task.deliverMode,
          },
          execution: {
            timeout_seconds: input.execution.timeoutSeconds,
          },
        }),
      },
    );
    return mapAssistantCronJob(data.job);
  }

  async updateAssistantCronJob(
    botAlias: string,
    jobId: string,
    input: UpdateAssistantCronJobInput,
  ): Promise<AssistantCronJob> {
    const data = await this.requestJson<{ job: RawAssistantCronJob }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/cron/jobs/${encodeURIComponent(jobId)}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ...(typeof input.enabled === "boolean" ? { enabled: input.enabled } : {}),
          ...(input.title ? { title: input.title } : {}),
          ...(input.schedule ? {
            schedule: {
              ...(input.schedule.type ? { type: input.schedule.type } : {}),
              ...(input.schedule.time ? { time: input.schedule.time } : {}),
              ...(input.schedule.timezone ? { timezone: input.schedule.timezone } : {}),
              ...(typeof input.schedule.everySeconds === "number"
                ? { every_seconds: input.schedule.everySeconds }
                : {}),
              ...(input.schedule.misfirePolicy ? { misfire_policy: input.schedule.misfirePolicy } : {}),
            },
          } : {}),
          ...(input.task ? {
            task: {
              ...(input.task.prompt ? { prompt: input.task.prompt } : {}),
              ...(input.task.mode ? { mode: input.task.mode } : {}),
              ...(typeof input.task.lookbackHours === "number"
                ? { lookback_hours: input.task.lookbackHours }
                : {}),
              ...(typeof input.task.historyLimit === "number"
                ? { history_limit: input.task.historyLimit }
                : {}),
              ...(typeof input.task.captureLimit === "number"
                ? { capture_limit: input.task.captureLimit }
                : {}),
              ...(input.task.deliverMode ? { deliver_mode: input.task.deliverMode } : {}),
            },
          } : {}),
          ...(input.execution ? {
            execution: {
              ...(typeof input.execution.timeoutSeconds === "number"
                ? { timeout_seconds: input.execution.timeoutSeconds }
                : {}),
            },
          } : {}),
        }),
      },
    );
    return mapAssistantCronJob(data.job);
  }

  async deleteAssistantCronJob(botAlias: string, jobId: string): Promise<void> {
    await this.requestJson(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/cron/jobs/${encodeURIComponent(jobId)}`,
      {
        method: "DELETE",
      },
    );
  }

  async runAssistantCronJob(botAlias: string, jobId: string): Promise<AssistantCronRunRequestResult> {
    const data = await this.requestJson<{
      run_id: string;
      status: string;
      task_mode?: "standard" | "dream";
      deliver_mode?: "chat_handoff" | "silent";
    }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/cron/jobs/${encodeURIComponent(jobId)}/run`,
      {
        method: "POST",
      },
    );
    return {
      runId: data.run_id,
      status: data.status,
      taskMode: data.task_mode,
      deliverMode: data.deliver_mode,
    };
  }

  async listAssistantCronRuns(botAlias: string, jobId: string, limit = 5): Promise<AssistantCronRun[]> {
    const params = new URLSearchParams({
      limit: String(limit),
    });
    const data = await this.requestJson<{ items: RawAssistantCronRun[] }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/cron/jobs/${encodeURIComponent(jobId)}/runs?${params.toString()}`,
    );
    return (data.items || []).map(mapAssistantCronRun);
  }

  async listAssistantAdminAudit(
    botAlias: string,
    filters: { limit?: number; action?: string; resource?: string; status?: "ok" | "failed" | "" } = {},
  ): Promise<AssistantAdminAuditResult> {
    const params = new URLSearchParams();
    if (typeof filters.limit === "number") {
      params.set("limit", String(filters.limit));
    }
    if (filters.action) {
      params.set("action", filters.action);
    }
    if (filters.resource) {
      params.set("resource", filters.resource);
    }
    if (filters.status) {
      params.set("status", filters.status);
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<{ items?: RawAssistantAdminAuditItem[] }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/audit${suffix}`,
    );
    return mapAssistantAdminAuditResult(data);
  }

  async addBot(input: CreateBotInput): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>("/api/admin/bots", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        alias: input.alias,
        bot_mode: input.botMode,
        cli_type: input.cliType,
        cli_path: input.cliPath,
        working_dir: input.workingDir,
        avatar_name: input.avatarName,
      }),
    });
    return mapBotSummary(data.bot, Boolean(data.bot.is_processing));
  }

  async renameBot(botAlias: string, newAlias: string): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/alias`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ new_alias: newAlias }),
    });
    return mapBotSummary(data.bot, Boolean(data.bot.is_processing));
  }

  async removeBot(botAlias: string): Promise<void> {
    await this.requestJson(`/api/admin/bots/${encodeURIComponent(botAlias)}`, {
      method: "DELETE",
    });
  }

  async startBot(botAlias: string): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/start`, {
      method: "POST",
    });
    return mapBotSummary(data.bot, Boolean(data.bot.is_processing));
  }

  async stopBot(botAlias: string): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/stop`, {
      method: "POST",
    });
    return mapBotSummary(data.bot, Boolean(data.bot.is_processing));
  }

  async listAvatarAssets(): Promise<AvatarAsset[]> {
    const data = await this.requestJson<{ items: RawAvatarAsset[] }>("/api/admin/assets/avatars");
    return (data.items || []).map(mapAvatarAsset);
  }

  async getCliParams(botAlias: string): Promise<CliParamsPayload> {
    const data = await this.requestJson<RawCliParamsPayload>(`/api/bots/${encodeURIComponent(botAlias)}/cli-params`);
    return mapCliParamsPayload(data);
  }

  async updateCliParam(botAlias: string, key: string, value: unknown, cliType?: string): Promise<CliParamsPayload> {
    const data = await this.requestJson<RawCliParamsPayload>(`/api/bots/${encodeURIComponent(botAlias)}/cli-params`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        key,
        value,
        ...(cliType ? { cli_type: cliType } : {}),
      }),
    });
    return mapCliParamsPayload(data);
  }

  async resetCliParams(botAlias: string, cliType?: string): Promise<CliParamsPayload> {
    const data = await this.requestJson<RawCliParamsPayload>(`/api/bots/${encodeURIComponent(botAlias)}/cli-params/reset`, {
      method: "POST",
      ...(cliType ? {
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ cli_type: cliType }),
      } : {}),
    });
    return mapCliParamsPayload(data);
  }

  async getTunnelStatus(): Promise<TunnelSnapshot> {
    const data = await this.requestJson<RawTunnelSnapshot>("/api/admin/tunnel");
    return mapTunnelSnapshot(data);
  }

  async startTunnel(): Promise<TunnelSnapshot> {
    const data = await this.requestJson<RawTunnelSnapshot>("/api/admin/tunnel/start", {
      method: "POST",
    });
    return mapTunnelSnapshot(data);
  }

  async stopTunnel(): Promise<TunnelSnapshot> {
    const data = await this.requestJson<RawTunnelSnapshot>("/api/admin/tunnel/stop", {
      method: "POST",
    });
    return mapTunnelSnapshot(data);
  }

  async restartTunnel(): Promise<TunnelSnapshot> {
    const data = await this.requestJson<RawTunnelSnapshot>("/api/admin/tunnel/restart", {
      method: "POST",
    });
    return mapTunnelSnapshot(data);
  }

}
