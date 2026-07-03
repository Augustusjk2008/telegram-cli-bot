import { WebApiClientError } from "./types";
import { buildWsUrl, withApiBase } from "../utils/publicBase";
import type {
  AdminUser,
  AdminUserUpdateInput,
  AccountRole,
  AnnouncementCategory,
  CreateAnnouncementInput,
  AnnouncementItem,
  AnnouncementListResult,
  AnnouncementSeverity,
  AppUpdateDownloadProgress,
  AppUpdatePackageKind,
  AppUpdateStatus,
  Capability,
  AgentInput,
  AgentListResult,
  AgentMutationResult,
  AgentScopedOptions,
  AgentSummary,
  GitActionResult,
  GitBranchResetResult,
  GitBranchList,
  GitCommitGraphEdge,
  GitCommitGraphOptions,
  GitCommitGraphPayload,
  GitCommitGraphRefKind,
  GitCommitMessageCliConfig,
  GitCommitMessageCliConfigUpdateInput,
  GitCommitMessageGenerateResult,
  GitCommitSummary,
  GitDiffPayload,
  GitIdentityConfig,
  GitIdentityScope,
  GitProxySettings,
  GitResetMode,
  GitGraphScope,
  GitOverview,
  GitSmartCommitJob,
  GitStashList,
  GitTreeStatus,
  BotOverview,
  BotExecutionConfigInput,
  BotWorkdirOpenResult,
  BotStatus,
  BotSummary,
  ChatAttachmentDeleteResult,
  ChatAttachmentUploadResult,
  ChatExecutionMode,
  ChatSendOptions,
  ChatMessage,
  ChatMessageContextUsage,
  ChatTraceDetails,
  ChatMessageMetaInfo,
  ChatStatusUpdate,
  ChatTraceEvent,
  NativeAgentPermissionReplyOptions,
  NativeAgentConfig,
  NativeAgentConfigInput,
  NativeAgentConfigPayload,
  NativeAgentHistoryChangesPayload,
  NativeAgentHistoryDiffPayload,
  NativeAgentHistoryRollbackResult,
  NativeAgentPreflightResult,
  NativeAgentModelOption,
  NativeAgentModelsPayload,
  NativeAgentModelUpdateResult,
  NativeAgentModelUpdateOptions,
  CliErrorStatsFilters,
  CliErrorStatsItem,
  CliErrorStatsResult,
  CliErrorStatsSummary,
  CliErrorTopItem,
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
  ClusterTaskMessage,
  ClusterTaskStatus,
  ClusterTemplateListResult,
  ClusterTemplateSummary,
  ConversationBulkDeleteResult,
  ConversationListResult,
  ConversationDeleteResult,
  FavoriteAnswerInput,
  FavoriteAnswerItem,
  FavoriteAnswerListResult,
  PlanExecuteInput,
  PlanExecuteResult,
  ConversationSelectResult,
  ConversationSummary,
  CreateBotInput,
  RemoveBotOptions,
  RemoveBotResult,
  DebugBreakpoint,
  DebugCapabilityMap,
  DebugFrame,
  DebugLaunchField,
  DebugLaunchSchema,
  DebugProfile,
  DebugScope,
  DebugState,
  DebugVariable,
  DirectoryListing,
  EnvConfigFieldType,
  EnvConfigItem,
  EnvConfigPatchInput,
  EnvConfigPatchResult,
  EnvConfigPatchValue,
  EnvConfigSnapshot,
  FileOpenTarget,
  FileTreeRevealResult,
  FileCopyResult,
  FileCreateResult,
  FileDownloadProgress,
  FileEntry,
  FileMoveResult,
  FileReadMode,
  FileReadResult,
  FileRenameResult,
  FileWriteResult,
  PluginActionInvokeInput,
  PluginActionResult,
  InstallablePluginSummary,
  OfflineUpdatePackageList,
  PluginViewWindowRequest,
  PluginViewWindowPayload,
  PluginRenderResult,
  PluginSummary,
  PluginUpdateInput,
  PromptPreset,
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
  TransferBridgeConfigInput,
  TransferBridgeStatus,
  TunnelSnapshot,
  UpdateBotWorkdirOptions,
  UserBotPermissions,
  WorkspaceDefinitionResult,
  WorkspaceOutlineResult,
  WorkspaceQuickOpenResult,
  WorkspaceSearchResult,
  WorkdirChangeConflict,
  HistoryDeltaResult,
  LanChatConfig,
  LanChatConfigInput,
  LanChatConversation,
  LanChatEvent,
  LanChatMessage,
  LanChatParticipant,
  LanChatStatus,
  NotificationPresenceUpdate,
  NotificationSettingsStatus,
  NotificationSocketStatus,
  NotificationSubscription,
  NotificationSubscriptionOptions,
  NotificationTestResult,
  WebNotificationEvent,
} from "./types";
import type { WebBotClient } from "./webBotClient";
import { createAgUiStreamAdapter, isAgUiEventType } from "./agUiStreamAdapter";
import {
  EventType,
  type AgUiEvent,
} from "./agUiProtocol";
import {
  buildAgUiMessageMeta,
  createAgUiRunState,
  findAgUiActivityForDelta,
  reduceAgUiRunEvent,
  type AgUiActivityItem,
} from "../utils/agUiRunReducer";
import { mergeMessageMeta, summarizeTrace } from "../utils/chatMessageMeta";
import { mapChatMessageContextUsage } from "../utils/contextUsage";
import { mergeChatTraceEvents } from "../utils/nativeAgentTranscript";

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
  working_dir: string;
  enabled?: boolean;
  is_main?: boolean;
  can_operate?: boolean;
  canOperate?: boolean;
  effective_capabilities?: Capability[];
  effectiveCapabilities?: Capability[];
  owner_account_id?: string;
  ownerAccountId?: string;
  owner_username?: string;
  ownerUsername?: string;
  is_owned_by_current_user?: boolean;
  isOwnedByCurrentUser?: boolean;
  cluster?: Record<string, unknown>;
  prompt_presets?: RawPromptPreset[];
  promptPresets?: RawPromptPreset[];
  global_prompt_presets?: RawPromptPreset[];
  globalPromptPresets?: RawPromptPreset[];
  supported_execution_modes?: string[];
  supportedExecutionModes?: string[];
  default_execution_mode?: string;
  defaultExecutionMode?: string;
  execution_mode?: string;
  executionMode?: string;
  native_agent?: Record<string, unknown>;
  nativeAgent?: Record<string, unknown>;
};

type RawPromptPreset = {
  id?: unknown;
  title?: unknown;
  content?: unknown;
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

type RawTransferBridgeStatus = {
  enabled?: boolean;
  running?: boolean;
  is_running?: boolean;
  status?: string;
  local_url?: string;
  local_endpoint?: string;
  local_host?: string;
  local_port?: number;
  bridge_page_url?: string;
  responses_base_url?: string;
  chat_completions_base_url?: string;
  remote_base_url?: string;
  remote_model?: string;
  remote_api_key_set?: boolean;
  request_count?: number;
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_bytes_in?: number;
  total_bytes_out?: number;
  uptime_seconds?: number;
  recent_traffic?: Array<{
    id?: string;
    timestamp?: string;
    method?: string;
    endpoint?: string;
    status?: number;
    bytes_in?: number;
    bytes_out?: number;
    duration_ms?: number;
    model?: string;
    error?: string;
  }>;
  started_at?: string;
  last_request_at?: string;
  last_error?: string;
  request_stream_usage?: boolean;
  retry_without_stream_options?: boolean;
  reasoning_mode?: string;
  downgrade_developer_to_system?: boolean;
  use_legacy_max_tokens?: boolean;
  restart_required?: boolean;
  restart_required_reason?: string;
};

type RawNotificationSettings = {
  pushplus_enabled?: boolean;
  pushplus_configured?: boolean;
  pushplus_topic_configured?: boolean;
  pushPlusEnabled?: boolean;
  pushPlusConfigured?: boolean;
  pushPlusTopicConfigured?: boolean;
};

type RawHistoryItem = {
  id?: string;
  turn_id?: string;
  turnId?: string;
  conversation_id?: string;
  conversationId?: string;
  timestamp?: string;
  created_at?: string;
  updated_at?: string;
  updatedAt?: string;
  role: "user" | "assistant" | "system";
  content: string;
  state?: ChatMessage["state"];
  elapsed_seconds?: number;
  meta?: RawChatMessageMeta;
  author?: RawChatMessageAuthor | null;
};

type RawChatMessageAuthor = {
  user_id?: number | string | null;
  userId?: number | string | null;
  account_id?: string | null;
  accountId?: string | null;
  username?: string | null;
  is_current_user?: boolean | null;
  isCurrentUser?: boolean | null;
};

type RawConversationSummary = {
  id?: string;
  bot_alias?: string;
  botAlias?: string;
  agent_id?: string;
  agentId?: string;
  cli_type?: string;
  cliType?: string;
  working_dir?: string;
  workingDir?: string;
  status?: string;
  native_provider?: string;
  nativeProvider?: string;
  native_session_id?: string;
  nativeSessionId?: string;
  title?: string;
  last_message_preview?: string;
  lastMessagePreview?: string;
  message_count?: number;
  messageCount?: number;
  pinned?: boolean;
  active?: boolean;
  workspace_history_head?: string;
  workspaceHistoryHead?: string;
  linear_index?: number;
  linearIndex?: number;
  rollback_supported?: boolean;
  rollbackSupported?: boolean;
  degraded?: boolean;
  degraded_reason?: string;
  degradedReason?: string;
  created_at?: string;
  createdAt?: string;
  updated_at?: string;
  updatedAt?: string;
};

type RawFavoriteAnswerItem = {
  id?: string;
  bot_id?: number;
  botId?: number;
  bot_alias?: string;
  botAlias?: string;
  user_id?: number;
  userId?: number;
  agent_id?: string;
  agentId?: string;
  execution_mode?: string;
  executionMode?: string;
  conversation_id?: string;
  conversationId?: string;
  message_id?: string;
  messageId?: string;
  message_key?: string;
  messageKey?: string;
  turn_id?: string;
  turnId?: string;
  title?: string;
  preview?: string;
  answer_text?: string;
  answerText?: string;
  created_at?: string;
  createdAt?: string;
  favorited_at?: string;
  favoritedAt?: string;
};

type RawPlanExecuteResult = {
  plan_path?: string;
  conversation: RawConversationSummary;
  messages: RawHistoryItem[];
  execution_message?: string;
};

type RawConversationDeleteResult = {
  deleted_conversation_id?: string;
  deleted_favorite_count?: number;
  active_conversation_id?: string;
  native_session_cleared?: boolean;
  items?: RawConversationSummary[];
  messages?: RawHistoryItem[] | null;
};

type RawConversationBulkDeleteResult = {
  deleted_count?: number;
  deleted_favorite_count?: number;
  active_conversation_id?: string;
  native_session_cleared?: boolean;
  items?: RawConversationSummary[];
  messages?: RawHistoryItem[] | null;
};

type RawRemoveBotResult = {
  removed?: boolean;
  alias?: string;
  history_deleted?: boolean;
  history_deleted_count?: number;
  favorite_deleted_count?: number;
  workspace_path?: string;
  workspace_deleted?: boolean;
  workspace_missing?: boolean;
  errors?: Array<{ code?: string; message?: string }>;
};

type RawChatTraceEvent = {
  id?: string;
  ordinal?: number;
  sequence?: number;
  created_at?: string;
  createdAt?: string;
  kind?: string;
  summary?: string;
  source?: string;
  raw_type?: string;
  rawType?: string;
  title?: string;
  tool_name?: string;
  toolName?: string;
  call_id?: string;
  callId?: string;
  payload?: unknown;
};

type RawChatMessageMeta = {
  completion_state?: string;
  completionState?: string;
  summary_kind?: string;
  summaryKind?: string;
  trace_version?: number;
  traceVersion?: number;
  trace_count?: number;
  traceCount?: number;
  tool_call_count?: number;
  toolCallCount?: number;
  process_count?: number;
  processCount?: number;
  trace?: RawChatTraceEvent[];
  native_source?: {
    provider?: string;
    session_id?: string;
  };
  nativeSource?: {
    provider?: string;
    sessionId?: string;
  };
  context_usage?: RawChatMessageContextUsage | null;
  contextUsage?: RawChatMessageContextUsage | null;
  workspace_history_head?: string;
  workspaceHistoryHead?: string;
  linear_index?: number;
  linearIndex?: number;
  rollback_supported?: boolean;
  rollbackSupported?: boolean;
  degraded?: boolean;
  degraded_reason?: string;
  degradedReason?: string;
};

type RawChatMessageContextUsage = {
  provider?: string;
  source?: string;
  session_id?: string;
  used_tokens?: number;
  context_window?: number;
  context_left_percent?: number;
  context_used?: number;
  context_used_percent?: number;
  input_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  model?: string;
  used_display?: string;
  window_display?: string;
  status_text?: string;
  compaction_count?: number;
};

type RawChatTraceDetails = {
  message_id?: string;
  trace_count?: number;
  tool_call_count?: number;
  process_count?: number;
  trace?: RawChatTraceEvent[];
};

type RawNativeAgentHistoryChangedFile = {
  path?: string;
  old_path?: string;
  oldPath?: string;
  status?: string;
  additions?: number;
  deletions?: number;
  binary?: boolean;
};

type RawNativeAgentHistoryChangesPayload = {
  conversation_id?: string;
  conversationId?: string;
  turn_id?: string;
  turnId?: string;
  linear_index?: number;
  linearIndex?: number;
  base_head?: string;
  baseHead?: string;
  head?: string;
  files?: RawNativeAgentHistoryChangedFile[];
  discarded?: boolean;
  message?: string;
};

type RawNativeAgentHistoryDiffPayload = {
  conversation_id?: string;
  conversationId?: string;
  turn_id?: string;
  turnId?: string;
  path?: string;
  old_path?: string;
  oldPath?: string;
  status?: string;
  diff?: string;
  truncated?: boolean;
  binary?: boolean;
};

type RawNativeAgentHistoryRollbackResult = {
  conversation_id?: string;
  conversationId?: string;
  current_turn_id?: string;
  currentTurnId?: string;
  rollback_supported?: boolean;
  rollbackSupported?: boolean;
  message?: string;
};

type RawClusterAgentTask = {
  task_id?: string;
  taskId?: string;
  agent_id?: string;
  agentId?: string;
  message?: string;
  status?: string;
  model_tier?: string;
  modelTier?: string;
  timeout_seconds?: number;
  timeoutSeconds?: number;
  deadline_exceeded?: boolean;
  deadlineExceeded?: boolean;
  allow_write?: boolean;
  allowWrite?: boolean;
  created_at?: string;
  createdAt?: string;
  started_at?: string;
  startedAt?: string;
  completed_at?: string;
  completedAt?: string;
  message_count?: number;
  messageCount?: number;
  latest_message_sequence?: number;
  latestMessageSequence?: number;
  messages?: RawClusterTaskMessage[];
  output?: string;
  error?: string;
};

type RawClusterTaskMessage = {
  sequence?: number;
  task_id?: string;
  taskId?: string;
  agent_id?: string;
  agentId?: string;
  kind?: string;
  content?: string;
  created_at?: string;
  createdAt?: string;
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
  encoding?: string;
  preview_kind?: "text" | "image";
  content_type?: string;
  content_base64?: string;
};

type RawFileWriteResult = {
  path: string;
  file_size_bytes: number;
  last_modified_ns: string | number;
  encoding?: string;
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
  is_local_admin?: boolean;
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

type RawAdminUser = {
  account_id?: string;
  username?: string;
  role?: string;
  disabled?: boolean;
  capabilities?: Capability[];
  created_at?: string;
  allowed_bots?: string[];
  owned_bots?: string[];
  owned_bot_count?: number;
  bot_create_limit?: number;
};

type RawEnvConfigOption = string | {
  value?: string;
  label?: string;
};

type RawEnvConfigItem = {
  key?: string;
  label?: string;
  description?: string;
  type?: string;
  category?: string;
  value?: unknown;
  default?: unknown;
  default_value?: unknown;
  defaultValue?: unknown;
  source?: string;
  sensitive?: boolean;
  masked?: boolean;
  restart_required?: boolean;
  restartRequired?: boolean;
  rebuild_required?: boolean;
  rebuildRequired?: boolean;
  process_overridden?: boolean;
  processOverridden?: boolean;
  options?: RawEnvConfigOption[];
  validation?: Record<string, unknown>;
};

type RawEnvConfigSnapshot = {
  envPath?: string;
  env_path?: string;
  examplePath?: string;
  example_path?: string;
  items?: RawEnvConfigItem[];
};

type RawEnvConfigPatchResult = {
  changedKeys?: string[];
  changed_keys?: string[];
  restartRequiredKeys?: string[];
  restart_required_keys?: string[];
  rebuildRequiredKeys?: string[];
  rebuild_required_keys?: string[];
  backupPath?: string;
  backup_path?: string;
};

type RawAnnouncementSection = {
  label?: string;
  items?: unknown[];
};

type RawAnnouncementItem = {
  id?: string;
  published_at?: string;
  publishedAt?: string;
  publisher?: string;
  title?: string;
  category?: string;
  severity?: string;
  summary?: string;
  sections?: RawAnnouncementSection[];
};

type RawAnnouncementListResult = {
  items?: RawAnnouncementItem[];
  latest_id?: string;
  latestId?: string;
  last_seen_id?: string;
  lastSeenId?: string;
  has_unseen?: boolean;
  hasUnseen?: boolean;
};

type RawOfflineUpdatePackageItem = {
  name?: string;
  path?: string;
  version?: string;
  package_kind?: AppUpdatePackageKind;
  size_bytes?: number;
  valid?: boolean;
  error?: string;
};

type RawOfflineUpdatePackageList = {
  artifacts_dir?: string;
  items?: RawOfflineUpdatePackageItem[];
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
  mode: "disabled" | "cloudflare_quick" | "manual" | "fixed_public_forward";
  status: "stopped" | "waiting_local" | "waiting_url" | "connected" | "verifying_public" | "starting" | "running" | "error";
  phase?: string;
  source: "disabled" | "quick_tunnel" | "manual_config" | "fixed_public_forward";
  public_url?: string;
  local_url?: string;
  last_error?: string;
  verified?: boolean;
  last_probe_at?: string;
  last_probe_elapsed_ms?: number;
  last_probe_error?: {
    error_class?: string;
    error_text?: string;
    status_code?: number | null;
  };
  registered_at?: string;
  log_tail?: string[];
  pid?: number | null;
  fixed_public_forward_enabled?: boolean;
  node_id?: string;
  base_path?: string;
  frpc_managed?: boolean;
  frpc_external?: boolean;
  frpc_note?: string;
  frpc_status?: string;
  frpc_pid?: number | null;
  frpc_last_error?: string;
  heartbeat_status?: string;
  heartbeat_last_at?: string;
  heartbeat_last_error?: string;
};

type RawGitChangedFile = {
  path: string;
  status: string;
  staged: boolean;
  unstaged: boolean;
  untracked: boolean;
  additions?: number;
  deletions?: number;
  staged_additions?: number;
  staged_deletions?: number;
  unstaged_additions?: number;
  unstaged_deletions?: number;
};

type RawGitCommitSummary = {
  hash: string;
  short_hash: string;
  author_name: string;
  authored_at: string;
  subject: string;
  message?: string;
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

type RawGitCommitGraphRef = {
  name?: string;
  kind?: string;
  current?: boolean;
};

type RawGitCommitGraphEdge = {
  from?: unknown;
  to?: unknown;
  commit?: string;
};

type RawGitCommitGraphNode = {
  hash?: string;
  short_hash?: string;
  parents?: string[];
  author_name?: string;
  authored_at?: string;
  subject?: string;
  message?: string;
  refs?: RawGitCommitGraphRef[];
  graph?: {
    column?: number;
    width?: number;
    edges?: RawGitCommitGraphEdge[];
  };
  can_reset?: boolean;
};

type RawGitCommitGraphPayload = {
  repo_found?: boolean;
  scope?: string;
  nodes?: RawGitCommitGraphNode[];
  has_more?: boolean;
  next_cursor?: string;
};

type RawGitDiffPayload = {
  path: string;
  staged: boolean;
  diff: string;
  truncated?: boolean;
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

type RawGitBranchResetResult = {
  message?: string;
  overview: RawGitOverview;
  branches?: RawGitBranchSummary[];
  current_branch?: string;
  head_commit?: string;
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

type RawGitIdentity = {
  name?: string;
  email?: string;
};

type RawGitIdentityConfig = {
  repo_found?: boolean;
  repo_path?: string;
  global?: RawGitIdentity;
  local?: RawGitIdentity;
};

type RawGitCommitMessageCliConfig = {
  cli_type?: CliType;
  cli_path?: string;
  params?: Record<string, unknown>;
  defaults?: Record<string, unknown>;
  schema?: RawCliParamsPayload["schema"];
};

type RawGitCommitMessageGenerateResult = {
  message?: string;
};

type RawGitSmartCommitJob = {
  job_id?: string;
  alias?: string;
  user_id?: number;
  status?: string;
  phase?: string;
  message?: string;
  error?: string;
  overview?: RawGitOverview | null;
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

type RawCliErrorStatsItem = {
  bot_alias?: string;
  cli_type?: string;
  working_dir?: string;
  conversation_id?: string;
  turn_id?: string;
  started_at?: string;
  completed_at?: string;
  error_code?: string;
  error_message?: string;
  category?: string;
  duration_ms?: number | null;
};

type RawCliErrorTopItem = {
  message?: string;
  count?: number;
  category?: string;
  latest_at?: string;
};

type RawCliErrorStatsSummary = {
  total?: number;
  by_cli_type?: Record<string, number>;
  by_bot?: Record<string, number>;
  by_category?: Record<string, number>;
  latest_at?: string;
};

type RawCliErrorStatsResult = {
  summary?: RawCliErrorStatsSummary;
  top_errors?: RawCliErrorTopItem[];
  items?: RawCliErrorStatsItem[];
};

type StreamEvent =
  | { type: "meta"; [key: string]: unknown }
  | { type: "delta"; text?: string }
  | { type: "snapshot"; text?: string; elapsed_seconds?: number }
  | RawAppUpdateDownloadProgress & { type: "progress" }
  | {
      type: "status";
      elapsed_seconds?: number;
      preview_text?: string;
      context_usage?: RawChatMessageContextUsage | null;
      phase?: string;
      message?: string;
      lifecycle?: string;
    }
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
    }
  | { type: "error"; message?: string; code?: string };

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function mapAgUiTraceEvent(event: AgUiEvent, activityContent?: Record<string, unknown>): ChatTraceEvent | null {
  if (event.type === EventType.TOOL_CALL_START) {
    return {
      kind: "tool_call",
      summary: "",
      title: event.toolCallName,
      toolName: event.toolCallName,
      callId: event.toolCallId,
      payload: {
        arguments: "",
      },
    };
  }
  if (event.type === EventType.TOOL_CALL_ARGS) {
    return {
      kind: "tool_call",
      summary: event.delta,
      callId: event.toolCallId,
      payload: {
        arguments: event.delta,
      },
    };
  }
  if (event.type === EventType.TOOL_CALL_RESULT) {
    return {
      kind: "tool_result",
      summary: event.content,
      callId: event.toolCallId,
      payload: {
        output: event.content,
      },
    };
  }
  if (event.type === EventType.ACTIVITY_SNAPSHOT || event.type === EventType.ACTIVITY_DELTA) {
    const content = (
      activityContent
      || (event.type === EventType.ACTIVITY_SNAPSHOT ? asRecord(event.content) : {})
    );
    const summary = String(content.summary || content.previewText || content.message || content.reason || "").trim();
    if (!summary && event.activityType === "TCB_NATIVE_AGENT_TRACE") {
      return null;
    }
    const rawKind = String(content.rawKind || "").trim();
    if (event.activityType === "TCB_META") {
      return null;
    }
    return {
      ...(String(content.id || "").trim() ? { id: String(content.id || "").trim() } : {}),
      ...(typeof content.ordinal === "number" ? { ordinal: content.ordinal } : {}),
      ...(typeof content.sequence === "number" ? { sequence: content.sequence } : {}),
      ...(String(content.createdAt || content.created_at || "").trim()
        ? { createdAt: String(content.createdAt || content.created_at || "").trim() }
        : {}),
      kind: event.activityType === "TCB_PERMISSION_REQUEST"
        ? "permission"
        : rawKind || (event.activityType === "TCB_STATUS" ? "status" : "event"),
      summary,
      source: String(content.source || "").trim() || undefined,
      rawType: String(content.rawType || event.activityType).trim() || undefined,
      title: String(content.title || "").trim() || undefined,
      toolName: String(content.toolName || content.tool_name || "").trim() || undefined,
      callId: String(content.callId || content.call_id || "").trim() || undefined,
      payload: content,
    };
  }
  if (event.type === EventType.REASONING_MESSAGE_CONTENT) {
    return {
      kind: "reasoning",
      summary: event.delta,
      source: "reasoning",
      rawType: EventType.REASONING_MESSAGE_CONTENT,
    };
  }
  if (event.type === EventType.RUN_ERROR) {
    return {
      kind: "error",
      summary: event.message,
      rawType: event.code,
    };
  }
  return null;
}

function contentForAgUiActivityEvent(
  activities: AgUiActivityItem[],
  event: AgUiEvent,
): Record<string, unknown> {
  if (event.type !== EventType.ACTIVITY_SNAPSHOT && event.type !== EventType.ACTIVITY_DELTA) {
    return {};
  }
  if (event.type === EventType.ACTIVITY_SNAPSHOT) {
    return asRecord(event.content);
  }
  return findAgUiActivityForDelta(activities, event.activityType, event.messageId)?.content || {};
}

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

function mapPromptPresets(raw: unknown): PromptPreset[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((item, index) => {
    const value = item && typeof item === "object" ? item as RawPromptPreset : {};
    return {
      id: String(value.id || `preset-${index + 1}`),
      title: String(value.title || ""),
      content: String(value.content || ""),
    };
  }).filter((item) => item.title.trim() && item.content.trim());
}

function serializePromptPresets(presets: PromptPreset[]) {
  return presets.map((preset) => ({
    id: preset.id,
    title: preset.title,
    content: preset.content,
  }));
}

function mapCliType(value: unknown): CliType {
  return value === "claude" ? "claude" : "codex";
}

function mapBotSummary(raw: RawBotSummary, isProcessing = false): BotSummary {
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
  const activityStatus = (raw.activity_status ?? raw.activityStatus) === "busy" || busyAgentCount > 0 || isProcessing
    ? "busy"
    : "idle";
  const status = mapStatus(raw.status, activityStatus === "busy");
  const summary: BotSummary = {
    alias: raw.alias,
    cliType: mapCliType(raw.cli_type),
    status,
    serviceStatus,
    activityStatus,
    busyAgentIds: resolvedBusyAgentIds,
    busyAgentNames: resolvedBusyAgentNames,
    busyAgentCount: hasExplicitBusyAgentCount || resolvedBusyAgentIds.length > 0 ? busyAgentCount : 0,
    workingDir: raw.working_dir,
    lastActiveText: mapStatusText(status),
  };
  if (Array.isArray(raw.agents)) {
    summary.agents = raw.agents.map(mapAgentSummary);
  }
  if (raw.cluster) {
    summary.cluster = mapBotClusterConfig(raw.cluster);
  }
  const rawPromptPresets = raw.prompt_presets ?? raw.promptPresets;
  if (Array.isArray(rawPromptPresets)) {
    summary.promptPresets = mapPromptPresets(rawPromptPresets);
  }
  const rawGlobalPromptPresets = raw.global_prompt_presets ?? raw.globalPromptPresets;
  if (Array.isArray(rawGlobalPromptPresets)) {
    summary.globalPromptPresets = mapPromptPresets(rawGlobalPromptPresets);
  }
  if (raw.cli_path) {
    summary.cliPath = raw.cli_path;
  }
  if (typeof raw.enabled === "boolean") {
    summary.enabled = raw.enabled;
  }
  if (typeof raw.is_main === "boolean") {
    summary.isMain = raw.is_main;
  }
  if (typeof raw.can_operate === "boolean" || typeof raw.canOperate === "boolean") {
    summary.canOperate = raw.can_operate ?? raw.canOperate;
  }
  if (Array.isArray(raw.effective_capabilities) || Array.isArray(raw.effectiveCapabilities)) {
    summary.effectiveCapabilities = (raw.effective_capabilities ?? raw.effectiveCapabilities ?? []).map((item) => item as Capability);
  }
  const supportedExecutionModes = mapExecutionModes(raw.supported_execution_modes ?? raw.supportedExecutionModes);
  if (supportedExecutionModes) {
    summary.supportedExecutionModes = supportedExecutionModes;
  }
  const defaultExecutionMode = normalizeExecutionMode(raw.default_execution_mode ?? raw.defaultExecutionMode);
  if (defaultExecutionMode) {
    summary.defaultExecutionMode = defaultExecutionMode;
  }
  const executionMode = normalizeExecutionMode(raw.execution_mode ?? raw.executionMode);
  if (executionMode) {
    summary.executionMode = executionMode;
  }
  const nativeAgent = mapNativeAgentConfig(raw.native_agent ?? raw.nativeAgent);
  if (nativeAgent) {
    summary.nativeAgent = nativeAgent;
  }
  if (raw.owner_account_id || raw.ownerAccountId) {
    summary.ownerAccountId = String(raw.owner_account_id ?? raw.ownerAccountId ?? "");
  }
  if (raw.owner_username || raw.ownerUsername) {
    summary.ownerUsername = String(raw.owner_username ?? raw.ownerUsername ?? "");
  }
  if (typeof raw.is_owned_by_current_user === "boolean" || typeof raw.isOwnedByCurrentUser === "boolean") {
    summary.isOwnedByCurrentUser = raw.is_owned_by_current_user ?? raw.isOwnedByCurrentUser;
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
      pi: mcp.pi ? mapTarget(mcp.pi) : undefined,
    },
    agents: Array.isArray(value.agents) ? value.agents.map((rawAgent) => {
      const agent = rawAgent && typeof rawAgent === "object" ? rawAgent as Record<string, unknown> : {};
      return {
        id: String(agent.id || ""),
        name: String(agent.name || agent.id || ""),
        enabled: agent.enabled !== false,
        allowCluster: agent.allow_cluster !== false && agent.allowCluster !== false,
        allowWrite: Boolean(agent.allow_write ?? agent.allowWrite ?? false),
        sessionPolicy: String(agent.session_policy ?? agent.sessionPolicy ?? "persistent") as AgentClusterConfig["sessionPolicy"],
        timeoutSeconds: Number(agent.timeout_seconds ?? agent.timeoutSeconds ?? 600),
      };
    }) : [],
  };
}

function mapClusterTaskMessage(raw: RawClusterTaskMessage): ClusterTaskMessage {
  return {
    sequence: Number(raw.sequence ?? 0),
    taskId: String(raw.task_id ?? raw.taskId ?? ""),
    agentId: String(raw.agent_id ?? raw.agentId ?? ""),
    kind: String(raw.kind || "progress"),
    content: String(raw.content || ""),
    createdAt: String(raw.created_at ?? raw.createdAt ?? ""),
  };
}

function mapClusterAgentTask(raw: RawClusterAgentTask): ClusterAgentTask {
  return {
    taskId: String(raw.task_id ?? raw.taskId ?? ""),
    agentId: String(raw.agent_id ?? raw.agentId ?? ""),
    status: String(raw.status || "queued") as ClusterAgentTask["status"],
    modelTier: String(raw.model_tier ?? raw.modelTier ?? "") as ClusterAgentTask["modelTier"],
    allowWrite: Boolean(raw.allow_write ?? raw.allowWrite),
    createdAt: String(raw.created_at ?? raw.createdAt ?? ""),
    startedAt: String(raw.started_at ?? raw.startedAt ?? ""),
    completedAt: String(raw.completed_at ?? raw.completedAt ?? ""),
    message: typeof raw.message === "string" ? raw.message : undefined,
    timeoutSeconds:
      typeof raw.timeout_seconds === "number"
        ? raw.timeout_seconds
        : typeof raw.timeoutSeconds === "number"
          ? raw.timeoutSeconds
          : undefined,
    deadlineExceeded:
      typeof raw.deadline_exceeded === "boolean"
        ? raw.deadline_exceeded
        : typeof raw.deadlineExceeded === "boolean"
          ? raw.deadlineExceeded
          : undefined,
    messageCount:
      typeof raw.message_count === "number"
        ? raw.message_count
        : typeof raw.messageCount === "number"
          ? raw.messageCount
          : undefined,
    latestMessageSequence:
      typeof raw.latest_message_sequence === "number"
        ? raw.latest_message_sequence
        : typeof raw.latestMessageSequence === "number"
          ? raw.latestMessageSequence
          : undefined,
    messages: Array.isArray(raw.messages) ? raw.messages.map(mapClusterTaskMessage) : undefined,
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
    piSettingsPath: String(value.pi_settings_path || value.piSettingsPath || ""),
    piSettingsSnippet: String(value.pi_settings_snippet || value.piSettingsSnippet || ""),
    piExtensionPath: String(value.pi_extension_path || value.piExtensionPath || ""),
    piExtensionName: String(value.pi_extension_name || value.piExtensionName || ""),
    selfTestCommand: list("self_test_command", "selfTestCommand"),
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

function appendExecutionModeParam(params: URLSearchParams, executionMode?: ChatExecutionMode) {
  if (executionMode === "native_agent") {
    params.set("execution_mode", executionMode);
  }
}

function scopedRequestBody(options: AgentScopedOptions = {}) {
  return {
    ...(options.agentId ? { agent_id: options.agentId } : {}),
    ...(options.executionMode === "native_agent" ? { execution_mode: options.executionMode } : {}),
  };
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
  if (raw.id) {
    event.id = raw.id;
  }
  if (typeof raw.ordinal === "number") {
    event.ordinal = raw.ordinal;
  }
  if (typeof raw.sequence === "number") {
    event.sequence = raw.sequence;
  }
  if (raw.created_at || raw.createdAt) {
    event.createdAt = raw.created_at || raw.createdAt;
  }
  if (raw.source) {
    event.source = raw.source;
  }
  if (raw.raw_type || raw.rawType) {
    event.rawType = raw.raw_type || raw.rawType;
  }
  if (raw.title) {
    event.title = raw.title;
  }
  if (raw.tool_name || raw.toolName) {
    event.toolName = raw.tool_name || raw.toolName;
  }
  if (raw.call_id || raw.callId) {
    event.callId = raw.call_id || raw.callId;
  }
  if (typeof raw.payload !== "undefined") {
    event.payload = raw.payload;
  }
  return event;
}

function normalizeExecutionMode(value: unknown): ChatExecutionMode | undefined {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "cli" || normalized === "native_agent") {
    return normalized;
  }
  return undefined;
}

function mapExecutionModes(value: unknown): ChatExecutionMode[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const modes = value
    .map((item) => normalizeExecutionMode(item))
    .filter((item): item is ChatExecutionMode => Boolean(item));
  return modes.length > 0 ? Array.from(new Set(modes)) : undefined;
}

function mapNativeAgentConfig(value: unknown): NativeAgentConfig | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const raw = value as Record<string, unknown>;
  const reasoningEffort = String(raw.reasoning_effort ?? raw.reasoningEffort ?? "").trim();
  const thinkingDepth = String(raw.thinking_depth ?? raw.thinkingDepth ?? "").trim();
  return {
    provider: String(raw.provider || ""),
    model: String(raw.model || ""),
    piAgent: String(raw.pi_agent ?? raw.piAgent ?? raw.agent ?? ""),
    baseUrl: String(raw.base_url ?? raw.baseUrl ?? ""),
    hasApiKey: Boolean(raw.has_api_key ?? raw.hasApiKey ?? raw.api_key_masked ?? raw.apiKeyMasked),
    apiKeyMasked: String(raw.api_key_masked ?? raw.apiKeyMasked ?? ""),
    ...(reasoningEffort ? { reasoningEffort } : {}),
    ...(thinkingDepth ? { thinkingDepth } : {}),
  };
}

function mapNativeAgentModelOption(raw: unknown): NativeAgentModelOption {
  const item = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const reasoningEfforts = toStringArray(item.reasoning_efforts ?? item.reasoningEfforts);
  const defaultReasoningEffort = String(item.default_reasoning_effort ?? item.defaultReasoningEffort ?? "").trim();
  return {
    id: String(item.id || ""),
    provider: String(item.provider || ""),
    model: String(item.model || ""),
    name: String(item.name || item.model || ""),
    label: String(item.label || item.id || ""),
    ...(typeof item.context_window === "number" ? { contextWindow: item.context_window } : {}),
    ...(typeof item.contextWindow === "number" ? { contextWindow: item.contextWindow } : {}),
    ...(typeof item.output_limit === "number" ? { outputLimit: item.output_limit } : {}),
    ...(typeof item.outputLimit === "number" ? { outputLimit: item.outputLimit } : {}),
    ...(reasoningEfforts.length ? { reasoningEfforts } : {}),
    ...(defaultReasoningEffort ? { defaultReasoningEffort } : {}),
  };
}

function mapNativeAgentPreflightResult(raw: unknown): NativeAgentPreflightResult {
  const item = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const checks = Array.isArray(item.checks) ? item.checks : [];
  return {
    ok: Boolean(item.ok),
    code: String(item.code ?? ""),
    message: String(item.message ?? ""),
    platform: String(item.platform ?? ""),
    checks: checks.map((rawCheck) => {
      const check = rawCheck && typeof rawCheck === "object" ? rawCheck as Record<string, unknown> : {};
      return {
        key: String(check.key ?? ""),
        ok: Boolean(check.ok),
        severity: String(check.severity ?? (check.ok ? "info" : "error")),
        message: String(check.message ?? ""),
        fix: String(check.fix ?? ""),
        ...(check.path ? { path: String(check.path) } : {}),
        ...(check.command ? { command: String(check.command) } : {}),
        ...(check.version ? { version: String(check.version) } : {}),
      };
    }),
  };
}

function mapNativeAgentConfigPayload(raw: unknown): NativeAgentConfigPayload {
  const item = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const models = Array.isArray(item.models) ? item.models.map(mapNativeAgentModelOption) : [];
  const rawPreflight = item.preflight ?? item.preflightResult;
  return {
    config: item.config && typeof item.config === "object" ? item.config as Record<string, unknown> : {},
    backend: String(item.backend ?? "pi"),
    configPath: String(item.config_path ?? item.configPath ?? ""),
    modelsPath: String(item.models_path ?? item.modelsPath ?? ""),
    workspaceHistoryEnabled: Boolean(item.workspace_history_enabled ?? item.workspaceHistoryEnabled),
    models,
    selectedModel: String(item.selected_model ?? item.selectedModel ?? ""),
    selectedReasoningEffort: String(item.selected_reasoning_effort ?? item.selectedReasoningEffort ?? "").trim(),
    needsRestart: Boolean(item.needs_restart ?? item.needsRestart),
    ...(rawPreflight ? { preflight: mapNativeAgentPreflightResult(rawPreflight) } : {}),
  };
}

function mapNativeAgentModelsPayload(raw: unknown): NativeAgentModelsPayload {
  const item = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const items = Array.isArray(item.items) ? item.items.map(mapNativeAgentModelOption) : [];
  return {
    items,
    selectedModel: String(item.selected_model ?? item.selectedModel ?? ""),
    selectedReasoningEffort: String(item.selected_reasoning_effort ?? item.selectedReasoningEffort ?? "").trim(),
  };
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return Array.from(new Set(
    value
      .map((item) => String(item || "").trim())
      .filter(Boolean),
  ));
}

function serializeNativeAgentConfig(input: NativeAgentConfigInput | undefined) {
  const nativeAgent = input || { provider: "", model: "", piAgent: "", baseUrl: "" };
  return {
    backend: "pi",
    pi_agent: nativeAgent.piAgent,
  };
}

function displayNativeProvider(provider?: string) {
  const normalized = String(provider || "").trim().toLowerCase();
  if (normalized === "native_agent") {
    return "原生 agent";
  }
  return provider || undefined;
}

function mapContextUsage(raw?: unknown): ChatMessageContextUsage | undefined {
  return mapChatMessageContextUsage(raw);
}

function mapMessageMeta(raw?: RawChatMessageMeta | null): ChatMessageMetaInfo | undefined {
  if (!raw) {
    return undefined;
  }

  const rawNativeSource = raw.native_source || (raw.nativeSource
    ? {
        provider: raw.nativeSource.provider,
        session_id: raw.nativeSource.sessionId,
      }
    : undefined);
  const rawContextUsage = raw.context_usage ?? raw.contextUsage;
  const rawWorkspaceHistoryHead = raw.workspace_history_head ?? raw.workspaceHistoryHead;
  const rawLinearIndex = raw.linear_index ?? raw.linearIndex;
  const rawRollbackSupported = raw.rollback_supported ?? raw.rollbackSupported;
  const rawDegraded = raw.degraded;
  const rawDegradedReason = raw.degraded_reason ?? raw.degradedReason;
  const rawTrace = (raw.trace || [])
    .map((item) => mapTraceEvent(item))
    .filter((item): item is ChatTraceEvent => Boolean(item));
  const isNativeFlat = String(rawNativeSource?.provider || "").trim().toLowerCase() === "native_agent";
  const trace = mergeChatTraceEvents([rawTrace], {
    nativeFlat: isNativeFlat,
    autoNativeFlat: isNativeFlat,
  });
  const traceSummary = summarizeTrace(trace);

  const meta: ChatMessageMetaInfo = {};
  if (raw.completion_state || raw.completionState) {
    meta.completionState = raw.completion_state || raw.completionState;
  }
  if (raw.summary_kind || raw.summaryKind) {
    meta.summaryKind = raw.summary_kind || raw.summaryKind;
  }
  if (typeof (raw.trace_version ?? raw.traceVersion) === "number") {
    meta.traceVersion = raw.trace_version ?? raw.traceVersion;
  }
  if (traceSummary.traceCount > 0) {
    meta.traceCount = traceSummary.traceCount;
  } else if (typeof (raw.trace_count ?? raw.traceCount) === "number") {
    meta.traceCount = raw.trace_count ?? raw.traceCount;
  }
  if (traceSummary.traceCount > 0) {
    meta.toolCallCount = traceSummary.toolCallCount;
    meta.processCount = traceSummary.processCount;
  } else {
    if (typeof (raw.tool_call_count ?? raw.toolCallCount) === "number") {
      meta.toolCallCount = raw.tool_call_count ?? raw.toolCallCount;
    }
    if (typeof (raw.process_count ?? raw.processCount) === "number") {
      meta.processCount = raw.process_count ?? raw.processCount;
    }
  }
  if ((trace || []).length > 0) {
    meta.trace = trace;
  }
  if (rawNativeSource?.provider || rawNativeSource?.session_id) {
    if (isNativeFlat) {
      meta.tracePresentation = "native_agent_flat";
    }
    meta.nativeSource = {
      provider: displayNativeProvider(rawNativeSource.provider),
      sessionId: rawNativeSource.session_id || undefined,
    };
  }
  const contextUsage = mapContextUsage(rawContextUsage);
  if (contextUsage) {
    meta.contextUsage = contextUsage;
  }
  if (typeof rawWorkspaceHistoryHead === "string") {
    meta.workspaceHistoryHead = rawWorkspaceHistoryHead;
  }
  if (typeof rawLinearIndex === "number" && Number.isFinite(rawLinearIndex)) {
    meta.linearIndex = rawLinearIndex;
  }
  if (typeof rawRollbackSupported === "boolean") {
    meta.rollbackSupported = rawRollbackSupported;
  }
  if (typeof rawDegraded === "boolean") {
    meta.degraded = rawDegraded;
  }
  if (typeof rawDegradedReason === "string") {
    meta.degradedReason = rawDegradedReason;
  }

  return Object.keys(meta).length > 0 ? meta : undefined;
}

function normalizeResolvedFinalMessage(message: ChatMessage): ChatMessage {
  if (message.state === "error") {
    return message;
  }
  const completionState = String(message.meta?.completionState || "").trim().toLowerCase();
  if (["cancelled", "canceled", "error", "failed"].includes(completionState)) {
    return {
      ...message,
      state: "error",
    };
  }
  return {
    ...message,
    state: "done",
  };
}

function mapChatMessageAuthor(raw?: RawChatMessageAuthor | null): ChatMessage["author"] | undefined {
  if (!raw || typeof raw !== "object") {
    return undefined;
  }
  const rawUserId = raw.user_id ?? raw.userId;
  const parsedUserId = typeof rawUserId === "number" ? rawUserId : Number.parseInt(String(rawUserId || ""), 10);
  const accountId = String(raw.account_id ?? raw.accountId ?? "").trim();
  const username = String(raw.username ?? "").trim();
  const isCurrentUser = raw.is_current_user ?? raw.isCurrentUser;
  const author = {
    ...(Number.isFinite(parsedUserId) ? { userId: parsedUserId } : {}),
    ...(accountId ? { accountId } : {}),
    ...(username ? { username } : {}),
    ...(typeof isCurrentUser === "boolean" ? { isCurrentUser } : {}),
  };
  return Object.keys(author).length > 0 ? author : undefined;
}

function mapChatMessage(raw: RawHistoryItem, index: number, fallbackState: ChatMessage["state"] = "done"): ChatMessage {
  const author = mapChatMessageAuthor(raw.author);
  const turnId = raw.turn_id ?? raw.turnId;
  const conversationId = raw.conversation_id ?? raw.conversationId;
  const meta = mapMessageMeta(raw.meta);
  return {
    id: raw.id || `${raw.timestamp || raw.created_at || "history"}-${index}`,
    ...(typeof turnId === "string" && turnId ? { turnId } : {}),
    ...(typeof conversationId === "string" && conversationId ? { conversationId } : {}),
    role: raw.role,
    text: raw.content,
    createdAt: raw.created_at || raw.timestamp || new Date().toISOString(),
    ...(raw.updated_at || raw.updatedAt ? { updatedAt: raw.updated_at || raw.updatedAt } : {}),
    state: raw.state || fallbackState,
    ...(typeof raw.elapsed_seconds === "number" ? { elapsedSeconds: raw.elapsed_seconds } : {}),
    ...(meta ? { meta } : {}),
    ...(author ? { author } : {}),
  };
}

function mapNativeAgentHistoryChangedFile(raw: RawNativeAgentHistoryChangedFile) {
  return {
    path: String(raw.path || ""),
    oldPath: String(raw.old_path ?? raw.oldPath ?? ""),
    status: String(raw.status || "unknown"),
    additions: Number(raw.additions || 0),
    deletions: Number(raw.deletions || 0),
    binary: Boolean(raw.binary),
  };
}

function mapNativeAgentHistoryChanges(raw: RawNativeAgentHistoryChangesPayload): NativeAgentHistoryChangesPayload {
  const linearIndex = Number(raw.linear_index ?? raw.linearIndex ?? 0);
  return {
    conversationId: String(raw.conversation_id ?? raw.conversationId ?? ""),
    turnId: String(raw.turn_id ?? raw.turnId ?? ""),
    linearIndex: Number.isFinite(linearIndex) ? linearIndex : 0,
    baseHead: String(raw.base_head ?? raw.baseHead ?? ""),
    head: String(raw.head || ""),
    files: Array.isArray(raw.files) ? raw.files.map(mapNativeAgentHistoryChangedFile) : [],
    ...(typeof raw.discarded === "boolean" ? { discarded: raw.discarded } : {}),
    ...(typeof raw.message === "string" ? { message: raw.message } : {}),
  };
}

function mapNativeAgentHistoryDiff(raw: RawNativeAgentHistoryDiffPayload): NativeAgentHistoryDiffPayload {
  return {
    conversationId: String(raw.conversation_id ?? raw.conversationId ?? ""),
    turnId: String(raw.turn_id ?? raw.turnId ?? ""),
    path: String(raw.path || ""),
    oldPath: String(raw.old_path ?? raw.oldPath ?? ""),
    status: String(raw.status || "unknown"),
    diff: String(raw.diff || ""),
    truncated: Boolean(raw.truncated),
    binary: Boolean(raw.binary),
  };
}

function mapNativeAgentHistoryRollback(raw: RawNativeAgentHistoryRollbackResult): NativeAgentHistoryRollbackResult {
  return {
    conversationId: String(raw.conversation_id ?? raw.conversationId ?? ""),
    currentTurnId: String(raw.current_turn_id ?? raw.currentTurnId ?? ""),
    rollbackSupported: Boolean(raw.rollback_supported ?? raw.rollbackSupported),
    message: String(raw.message || ""),
  };
}

function mapConversationSummary(raw: RawConversationSummary): ConversationSummary {
  const nativeProvider = String(raw.native_provider ?? raw.nativeProvider ?? "");
  const nativeSessionId = String(raw.native_session_id ?? raw.nativeSessionId ?? "");
  const workspaceHistoryHead = raw.workspace_history_head ?? raw.workspaceHistoryHead;
  const linearIndex = raw.linear_index ?? raw.linearIndex;
  const rollbackSupported = raw.rollback_supported ?? raw.rollbackSupported;
  const degraded = raw.degraded;
  const degradedReason = raw.degraded_reason ?? raw.degradedReason;
  return {
    id: String(raw.id || ""),
    title: String(raw.title || "新会话"),
    lastMessagePreview: String(raw.last_message_preview ?? raw.lastMessagePreview ?? ""),
    messageCount: Number(raw.message_count ?? raw.messageCount ?? 0),
    pinned: Boolean(raw.pinned),
    active: Boolean(raw.active),
    status: String(raw.status || "active"),
    botAlias: String(raw.bot_alias ?? raw.botAlias ?? ""),
    cliType: String(raw.cli_type ?? raw.cliType ?? ""),
    agentId: String(raw.agent_id ?? raw.agentId ?? "main"),
    workingDir: String(raw.working_dir ?? raw.workingDir ?? ""),
    ...(nativeProvider || nativeSessionId ? {
      nativeSource: {
        provider: displayNativeProvider(nativeProvider),
        sessionId: nativeSessionId,
      },
    } : {}),
    ...(typeof workspaceHistoryHead === "string" ? { workspaceHistoryHead } : {}),
    ...(typeof linearIndex === "number" && Number.isFinite(linearIndex) ? { linearIndex } : {}),
    ...(typeof rollbackSupported === "boolean" ? { rollbackSupported } : {}),
    ...(typeof degraded === "boolean" ? { degraded } : {}),
    ...(typeof degradedReason === "string" ? { degradedReason } : {}),
    createdAt: String(raw.created_at ?? raw.createdAt ?? ""),
    updatedAt: String(raw.updated_at ?? raw.updatedAt ?? ""),
  };
}

function normalizeFavoriteExecutionMode(value: unknown): ChatExecutionMode {
  return String(value || "").trim() === "native_agent" ? "native_agent" : "cli";
}

function mapFavoriteAnswerItem(raw: RawFavoriteAnswerItem): FavoriteAnswerItem {
  return {
    id: String(raw.id || ""),
    botId: Number(raw.bot_id ?? raw.botId ?? 0),
    botAlias: String(raw.bot_alias ?? raw.botAlias ?? ""),
    userId: Number(raw.user_id ?? raw.userId ?? 0),
    agentId: String(raw.agent_id ?? raw.agentId ?? "main"),
    executionMode: normalizeFavoriteExecutionMode(raw.execution_mode ?? raw.executionMode),
    conversationId: String(raw.conversation_id ?? raw.conversationId ?? ""),
    messageId: String(raw.message_id ?? raw.messageId ?? ""),
    messageKey: String(raw.message_key ?? raw.messageKey ?? ""),
    turnId: String(raw.turn_id ?? raw.turnId ?? ""),
    title: String(raw.title || ""),
    preview: String(raw.preview || ""),
    answerText: String(raw.answer_text ?? raw.answerText ?? ""),
    createdAt: String(raw.created_at ?? raw.createdAt ?? ""),
    favoritedAt: String(raw.favorited_at ?? raw.favoritedAt ?? ""),
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
    phase: raw.phase || raw.status,
    source: raw.source,
    publicUrl: raw.public_url || "",
    localUrl: raw.local_url || "",
    lastError: raw.last_error || "",
    verified: Boolean(raw.verified),
    lastProbeAt: raw.last_probe_at || "",
    lastProbeElapsedMs: typeof raw.last_probe_elapsed_ms === "number" ? raw.last_probe_elapsed_ms : 0,
    lastProbeError: raw.last_probe_error
      ? {
          errorClass: raw.last_probe_error.error_class || "",
          errorText: raw.last_probe_error.error_text || "",
          statusCode: raw.last_probe_error.status_code ?? null,
        }
      : undefined,
    registeredAt: raw.registered_at || "",
    logTail: Array.isArray(raw.log_tail) ? raw.log_tail.map(String) : [],
    pid: raw.pid ?? null,
    fixedPublicForwardEnabled: Boolean(raw.fixed_public_forward_enabled),
    nodeId: raw.node_id || "",
    basePath: raw.base_path || "",
    frpcManaged: Boolean(raw.frpc_managed),
    frpcExternal: Boolean(raw.frpc_external),
    frpcNote: raw.frpc_note || "",
    frpcStatus: raw.frpc_status || "",
    frpcPid: raw.frpc_pid ?? null,
    frpcLastError: raw.frpc_last_error || "",
    heartbeatStatus: raw.heartbeat_status || "",
    heartbeatLastAt: raw.heartbeat_last_at || "",
    heartbeatLastError: raw.heartbeat_last_error || "",
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

function asLanChatRecord(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
}

function mapLanChatParticipant(raw: unknown): LanChatParticipant {
  const item = asLanChatRecord(raw);
  return {
    roomUserId: String(item.room_user_id || item.roomUserId || ""),
    accountId: String(item.account_id || item.accountId || ""),
    username: String(item.username || ""),
    displayName: String(item.display_name || item.displayName || item.username || ""),
    instanceId: String(item.instance_id || item.instanceId || ""),
    instanceName: String(item.instance_name || item.instanceName || ""),
    online: Boolean(item.online),
    lastSeenAt: String(item.last_seen_at || item.lastSeenAt || ""),
  };
}

function mapLanChatMessage(raw: unknown): LanChatMessage {
  const item = asLanChatRecord(raw);
  return {
    id: String(item.id || ""),
    seq: Number(item.seq || 0),
    conversationId: String(item.conversation_id || item.conversationId || ""),
    kind: item.kind === "dm" ? "dm" : "group",
    sender: mapLanChatParticipant(item.sender),
    text: String(item.text || ""),
    createdAt: String(item.created_at || item.createdAt || ""),
  };
}

function mapLanChatConversation(raw: unknown): LanChatConversation {
  const item = asLanChatRecord(raw);
  const participantIds = item.participant_ids || item.participantIds;
  const lastMessage = item.last_message || item.lastMessage;
  return {
    id: String(item.id || ""),
    kind: item.kind === "dm" ? "dm" : "group",
    title: String(item.title || ""),
    participantIds: Array.isArray(participantIds) ? participantIds.map(String) : [],
    lastMessage: lastMessage ? mapLanChatMessage(lastMessage) : null,
    unreadCount: Number(item.unread_count || item.unreadCount || 0),
    updatedAt: String(item.updated_at || item.updatedAt || ""),
  };
}

function mapLanChatConfig(raw: unknown): LanChatConfig {
  const item = asLanChatRecord(raw);
  return {
    mode: item.mode === "host" || item.mode === "join" ? item.mode : "off",
    roomName: String(item.room_name || item.roomName || "工作室"),
    instanceId: String(item.instance_id || item.instanceId || ""),
    instanceName: String(item.instance_name || item.instanceName || ""),
    hostUrl: String(item.host_url || item.hostUrl || ""),
    roomKey: item.room_key || item.roomKey ? String(item.room_key || item.roomKey) : undefined,
    roomKeyPreview: String(item.room_key_preview || item.roomKeyPreview || ""),
    lanOnly: Boolean(item.lan_only ?? item.lanOnly),
    autoConnect: Boolean(item.auto_connect ?? item.autoConnect),
  };
}

function mapLanChatStatus(raw: unknown): LanChatStatus {
  const item = asLanChatRecord(raw);
  const onlineUsers = item.online_users || item.onlineUsers;
  const onlineNodes = item.online_nodes || item.onlineNodes;
  return {
    mode: item.mode === "host" || item.mode === "join" ? item.mode : "off",
    connected: Boolean(item.connected),
    roomName: String(item.room_name || item.roomName || "工作室"),
    self: mapLanChatParticipant(item.self),
    onlineUsers: Array.isArray(onlineUsers) ? onlineUsers.map(mapLanChatParticipant) : [],
    onlineNodes: Array.isArray(onlineNodes) ? onlineNodes.map((node) => {
      const itemNode = asLanChatRecord(node);
      return {
        instanceId: String(itemNode.instance_id || itemNode.instanceId || ""),
        connected: Boolean(itemNode.connected),
      };
    }) : [],
    lastError: String(item.last_error || item.lastError || ""),
  };
}

function mapLanChatEvent(raw: unknown): LanChatEvent | null {
  const event = asLanChatRecord(raw);
  if (event.type === "snapshot") {
    return { type: "snapshot", status: mapLanChatStatus(event.status) };
  }
  if (event.type === "message_created") {
    return { type: "message_created", message: mapLanChatMessage(event.message) };
  }
  if (event.type === "conversation_updated") {
    return { type: "conversation_updated", conversation: mapLanChatConversation(event.conversation) };
  }
  if (event.type === "presence_updated") {
    return {
      type: "presence_updated",
      ...(event.status ? { status: mapLanChatStatus(event.status) } : {}),
    };
  }
  if (event.type === "read_updated") {
    return {
      type: "read_updated",
      conversationId: String(event.conversation_id || event.conversationId || ""),
      lastReadSeq: Number(event.last_read_seq || event.lastReadSeq || 0),
    };
  }
  if (event.type === "config_updated") {
    return { type: "config_updated", config: mapLanChatConfig(event.config) };
  }
  return null;
}

function normalizeEnvFieldType(type: unknown): EnvConfigFieldType {
  return type === "number"
    || type === "boolean"
    || type === "select"
    || type === "csv"
    || type === "path"
    || type === "password"
    ? type
    : "string";
}

function normalizeEnvConfigValue(value: unknown, type: EnvConfigFieldType) {
  if (type === "boolean") {
    return value === true || value === "true" || value === "1";
  }
  if (type === "number") {
    return typeof value === "number" ? value : Number(value || 0);
  }
  if (type === "csv") {
    if (Array.isArray(value)) {
      return value.map(String);
    }
    return typeof value === "string" && value.trim()
      ? value.split(",").map((item) => item.trim()).filter(Boolean)
      : [];
  }
  return value === null || typeof value === "undefined" ? "" : String(value);
}

function mapEnvConfigItem(raw: RawEnvConfigItem): EnvConfigItem {
  const fieldType = normalizeEnvFieldType(raw.type);
  return {
    key: String(raw.key || ""),
    label: String(raw.label || raw.key || ""),
    description: String(raw.description || ""),
    type: fieldType,
    category: String(raw.category || "advanced"),
    value: normalizeEnvConfigValue(raw.value, fieldType),
    defaultValue: normalizeEnvConfigValue(raw.default_value ?? raw.defaultValue ?? raw.default, fieldType),
    source: String(raw.source || ""),
    sensitive: Boolean(raw.sensitive),
    masked: Boolean(raw.masked),
    restartRequired: Boolean(raw.restart_required ?? raw.restartRequired),
    rebuildRequired: Boolean(raw.rebuild_required ?? raw.rebuildRequired),
    processOverridden: Boolean(raw.process_overridden ?? raw.processOverridden),
    options: (raw.options || []).map((option) => {
      if (typeof option === "string") {
        return { value: option, label: option };
      }
      return {
        value: String(option.value || ""),
        label: String(option.label || option.value || ""),
      };
    }),
    validation: raw.validation || {},
  };
}

function mapEnvConfigSnapshot(raw: RawEnvConfigSnapshot): EnvConfigSnapshot {
  return {
    envPath: String(raw.env_path || raw.envPath || ""),
    examplePath: String(raw.example_path || raw.examplePath || ""),
    items: (raw.items || []).map(mapEnvConfigItem),
  };
}

function mapEnvPatchValue(value: EnvConfigPatchValue): unknown {
  if (value && typeof value === "object" && !Array.isArray(value) && !(value instanceof Date)) {
    return {
      ...("value" in value ? { value: value.value } : {}),
      ...(typeof value.masked === "boolean" ? { masked: value.masked } : {}),
      ...(value.action ? { action: value.action } : {}),
    };
  }
  return value;
}

function mapEnvPatchInput(input: EnvConfigPatchInput) {
  return {
    values: Object.fromEntries(
      Object.entries(input.values).map(([key, value]) => [key, mapEnvPatchValue(value)]),
    ),
  };
}

function mapEnvPatchResult(raw: RawEnvConfigPatchResult): EnvConfigPatchResult {
  return {
    changedKeys: raw.changed_keys || raw.changedKeys || [],
    restartRequiredKeys: raw.restart_required_keys || raw.restartRequiredKeys || [],
    rebuildRequiredKeys: raw.rebuild_required_keys || raw.rebuildRequiredKeys || [],
    backupPath: String(raw.backup_path || raw.backupPath || ""),
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
    ...(typeof raw.is_local_admin === "boolean" ? { isLocalAdmin: raw.is_local_admin } : {}),
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

function mapAdminUser(raw: RawAdminUser): AdminUser {
  return {
    accountId: String(raw.account_id || ""),
    username: String(raw.username || ""),
    role: (raw.role as AdminUser["role"]) || "member",
    disabled: Boolean(raw.disabled),
    capabilities: Array.isArray(raw.capabilities) ? raw.capabilities.map((item) => item as Capability) : [],
    createdAt: String(raw.created_at || ""),
    allowedBots: Array.isArray(raw.allowed_bots) ? raw.allowed_bots.map((item) => String(item)) : [],
    ownedBots: Array.isArray(raw.owned_bots) ? raw.owned_bots.map((item) => String(item)) : [],
    ownedBotCount: Number(raw.owned_bot_count || 0),
    botCreateLimit: Number(raw.bot_create_limit || 0),
  };
}

function mapAnnouncementCategory(value: unknown): AnnouncementCategory {
  const normalized = String(value || "notice");
  return ["release", "feature", "fix", "maintenance", "notice"].includes(normalized)
    ? normalized as AnnouncementCategory
    : "notice";
}

function mapAnnouncementSeverity(value: unknown): AnnouncementSeverity {
  const normalized = String(value || "info");
  return ["info", "success", "warning", "danger"].includes(normalized)
    ? normalized as AnnouncementSeverity
    : "info";
}

function mapAnnouncementItem(raw: RawAnnouncementItem): AnnouncementItem {
  return {
    id: String(raw.id || ""),
    publishedAt: String(raw.published_at || raw.publishedAt || ""),
    publisher: String(raw.publisher || ""),
    title: String(raw.title || ""),
    category: mapAnnouncementCategory(raw.category),
    severity: mapAnnouncementSeverity(raw.severity),
    summary: String(raw.summary || ""),
    sections: Array.isArray(raw.sections)
      ? raw.sections.map((section) => ({
          label: String(section.label || ""),
          items: Array.isArray(section.items) ? section.items.map((item) => String(item)) : [],
        })).filter((section) => section.label || section.items.length > 0)
      : [],
  };
}

function mapAnnouncementList(raw: RawAnnouncementListResult): AnnouncementListResult {
  return {
    items: Array.isArray(raw.items) ? raw.items.map((item) => mapAnnouncementItem(item)) : [],
    latestId: String(raw.latest_id || raw.latestId || ""),
    lastSeenId: String(raw.last_seen_id || raw.lastSeenId || ""),
    hasUnseen: Boolean(raw.has_unseen ?? raw.hasUnseen),
  };
}

function mapAnnouncementInput(input: CreateAnnouncementInput): Record<string, unknown> {
  return {
    publisher: input.publisher,
    title: input.title,
    category: input.category,
    severity: input.severity,
    summary: input.summary,
    sections: input.sections.map((section) => ({
      label: section.label,
      items: [...section.items],
    })),
  };
}

function mapUserBotPermissions(raw: { account_id?: string; allowed_bots?: string[] }): UserBotPermissions {
  return {
    accountId: String(raw.account_id || ""),
    allowedBots: Array.isArray(raw.allowed_bots) ? raw.allowed_bots.map((item) => String(item)) : [],
  };
}

function mapOfflineUpdatePackageList(raw: RawOfflineUpdatePackageList): OfflineUpdatePackageList {
  return {
    artifactsDir: String(raw.artifacts_dir || ""),
    items: Array.isArray(raw.items)
      ? raw.items.map((item) => ({
          name: String(item.name || ""),
          path: String(item.path || ""),
          version: String(item.version || ""),
          packageKind: (item.package_kind || "") as AppUpdatePackageKind,
          sizeBytes: Number(item.size_bytes || 0),
          valid: item.valid !== false,
          error: String(item.error || ""),
        }))
      : [],
  };
}

function mapGitChangedFile(raw: RawGitChangedFile) {
  return {
    path: raw.path,
    status: raw.status,
    staged: Boolean(raw.staged),
    unstaged: Boolean(raw.unstaged),
    untracked: Boolean(raw.untracked),
    additions: Number(raw.additions || 0),
    deletions: Number(raw.deletions || 0),
    stagedAdditions: Number(raw.staged_additions || 0),
    stagedDeletions: Number(raw.staged_deletions || 0),
    unstagedAdditions: Number(raw.unstaged_additions || 0),
    unstagedDeletions: Number(raw.unstaged_deletions || 0),
  };
}

function mapGitCommitSummary(raw: RawGitCommitSummary): GitCommitSummary {
  const subject = raw.subject || "";
  return {
    hash: raw.hash,
    shortHash: raw.short_hash,
    authorName: raw.author_name,
    authoredAt: raw.authored_at,
    subject,
    message: raw.message || subject,
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

function mapGitCommitGraph(raw: RawGitCommitGraphPayload): GitCommitGraphPayload {
  return {
    repoFound: Boolean(raw.repo_found),
    scope: raw.scope === "current" ? "current" : "all",
    nodes: (raw.nodes || []).map((node) => {
      const graph = node.graph || {};
      return {
        hash: node.hash || "",
        shortHash: node.short_hash || "",
        parents: Array.isArray(node.parents) ? node.parents : [],
        authorName: node.author_name || "",
        authoredAt: node.authored_at || "",
        subject: node.subject || "",
        message: node.message || "",
        refs: (node.refs || []).map((ref) => ({
          name: ref.name || "",
          kind: (ref.kind || "local_branch") as GitCommitGraphRefKind,
          current: Boolean(ref.current),
        })),
        graph: {
          column: mapGitCommitGraphNumber(graph.column, 0),
          width: mapGitCommitGraphNumber(graph.width, 1),
          edges: mapGitCommitGraphEdges(graph.edges),
        },
        ...(typeof node.can_reset === "boolean" ? { canReset: node.can_reset } : {}),
      };
    }),
    hasMore: Boolean(raw.has_more),
    nextCursor: raw.next_cursor || "",
  };
}

function mapGitCommitGraphEdges(raw: RawGitCommitGraphEdge[] | undefined): GitCommitGraphEdge[] {
  return (raw || [])
    .filter((edge): edge is RawGitCommitGraphEdge => Boolean(edge) && typeof edge === "object")
    .map((edge) => {
      const from = Number(edge.from);
      const to = Number(edge.to);
      return {
        from: Number.isFinite(from) ? from : 0,
        to: Number.isFinite(to) ? to : 0,
        ...(edge.commit ? { commit: String(edge.commit) } : {}),
      };
    });
}

function mapGitCommitGraphNumber(value: unknown, fallback: number) {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : fallback;
}

function mapGitDiffPayload(raw: RawGitDiffPayload): GitDiffPayload {
  return {
    path: raw.path,
    staged: Boolean(raw.staged),
    diff: raw.diff || "",
    truncated: Boolean(raw.truncated),
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

function mapGitBranchResetResult(raw: RawGitBranchResetResult): GitBranchResetResult {
  return {
    message: raw.message || "",
    overview: mapGitOverview(raw.overview),
    branches: mapGitBranchList({ current_branch: raw.current_branch, branches: raw.branches }).branches,
    currentBranch: raw.current_branch || "",
    headCommit: raw.head_commit || "",
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

function mapGitIdentityConfig(raw: RawGitIdentityConfig): GitIdentityConfig {
  return {
    repoFound: Boolean(raw.repo_found),
    repoPath: raw.repo_path || "",
    global: {
      name: raw.global?.name || "",
      email: raw.global?.email || "",
    },
    local: {
      name: raw.local?.name || "",
      email: raw.local?.email || "",
    },
  };
}

function defaultCliPathForType(cliType: CliType) {
  return cliType === "claude" ? "claude" : "codex";
}

function mapGitCommitMessageCliConfig(raw: RawGitCommitMessageCliConfig): GitCommitMessageCliConfig {
  const cliType = mapCliType(raw.cli_type);
  return {
    cliType,
    cliPath: raw.cli_path || defaultCliPathForType(cliType),
    params: raw.params || {},
    defaults: raw.defaults || {},
    schema: raw.schema || {},
  };
}

function mapGitCommitMessageGenerateResult(raw: RawGitCommitMessageGenerateResult): GitCommitMessageGenerateResult {
  return {
    message: raw.message || "",
  };
}

function hasRawGitOverview(raw: RawGitOverview | null | undefined): raw is RawGitOverview {
  return Boolean(raw && ("repo_found" in raw || "working_dir" in raw || "repo_path" in raw));
}

function mapGitSmartCommitJob(raw: RawGitSmartCommitJob): GitSmartCommitJob {
  return {
    jobId: raw.job_id || "",
    alias: raw.alias || "",
    userId: Number(raw.user_id || 0),
    status: raw.status || "",
    phase: raw.phase || "",
    message: raw.message || "",
    error: raw.error || "",
    overview: hasRawGitOverview(raw.overview) ? mapGitOverview(raw.overview) : null,
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

function mapTransferBridgeStatus(raw: RawTransferBridgeStatus): TransferBridgeStatus {
  const status = String(raw.status || "unknown") as TransferBridgeStatus["status"];
  return {
    enabled: Boolean(raw.enabled),
    running: Boolean(raw.running),
    status,
    localUrl: String(raw.local_url || ""),
    localEndpoint: raw.local_endpoint ? String(raw.local_endpoint) : undefined,
    localHost: raw.local_host ? String(raw.local_host) : undefined,
    localPort: typeof raw.local_port === "number" ? raw.local_port : undefined,
    bridgePageUrl: String(raw.bridge_page_url || ""),
    responsesBaseUrl: String(raw.responses_base_url || ""),
    chatCompletionsBaseUrl: String(raw.chat_completions_base_url || ""),
    remoteBaseUrl: raw.remote_base_url ? String(raw.remote_base_url) : undefined,
    remoteModel: raw.remote_model ? String(raw.remote_model) : undefined,
    remoteApiKeySet: Boolean(raw.remote_api_key_set),
    requestCount: Number(raw.request_count || 0),
    totalInputTokens: Number(raw.total_input_tokens || 0),
    totalOutputTokens: Number(raw.total_output_tokens || 0),
    totalBytesIn: Number(raw.total_bytes_in || 0),
    totalBytesOut: Number(raw.total_bytes_out || 0),
    uptimeSeconds: typeof raw.uptime_seconds === "number" ? raw.uptime_seconds : undefined,
    recentTraffic: Array.isArray(raw.recent_traffic)
      ? raw.recent_traffic.map((record) => ({
          id: String(record.id || ""),
          timestamp: String(record.timestamp || ""),
          method: String(record.method || ""),
          endpoint: String(record.endpoint || ""),
          status: Number(record.status || 0),
          bytesIn: Number(record.bytes_in || 0),
          bytesOut: Number(record.bytes_out || 0),
          durationMs: Number(record.duration_ms || 0),
          model: String(record.model || ""),
          error: String(record.error || ""),
        }))
      : undefined,
    startedAt: raw.started_at ? String(raw.started_at) : undefined,
    lastRequestAt: raw.last_request_at ? String(raw.last_request_at) : undefined,
    lastError: raw.last_error !== undefined ? String(raw.last_error) : undefined,
    requestStreamUsage: typeof raw.request_stream_usage === "boolean" ? raw.request_stream_usage : undefined,
    retryWithoutStreamOptions: typeof raw.retry_without_stream_options === "boolean" ? raw.retry_without_stream_options : undefined,
    reasoningMode: raw.reasoning_mode ? String(raw.reasoning_mode) : undefined,
    downgradeDeveloperToSystem: typeof raw.downgrade_developer_to_system === "boolean" ? raw.downgrade_developer_to_system : undefined,
    useLegacyMaxTokens: typeof raw.use_legacy_max_tokens === "boolean" ? raw.use_legacy_max_tokens : undefined,
    restartRequired: typeof raw.restart_required === "boolean" ? raw.restart_required : undefined,
    restartRequiredReason: raw.restart_required_reason ? String(raw.restart_required_reason) : undefined,
  };
}

function mapTransferBridgeConfigInput(input: TransferBridgeConfigInput) {
  return {
    ...(input.remoteBaseUrl !== undefined ? { remote_base_url: input.remoteBaseUrl } : {}),
    ...(input.remoteModel !== undefined ? { remote_model: input.remoteModel } : {}),
    ...(input.remoteApiKey ? { remote_api_key: input.remoteApiKey } : {}),
    ...(input.clearRemoteApiKey !== undefined ? { clear_remote_api_key: input.clearRemoteApiKey } : {}),
    ...(input.requestStreamUsage !== undefined ? { request_stream_usage: input.requestStreamUsage } : {}),
    ...(input.retryWithoutStreamOptions !== undefined ? { retry_without_stream_options: input.retryWithoutStreamOptions } : {}),
    ...(input.reasoningMode !== undefined ? { reasoning_mode: input.reasoningMode } : {}),
    ...(input.downgradeDeveloperToSystem !== undefined ? { downgrade_developer_to_system: input.downgradeDeveloperToSystem } : {}),
    ...(input.useLegacyMaxTokens !== undefined ? { use_legacy_max_tokens: input.useLegacyMaxTokens } : {}),
  };
}

function mapCliErrorStatsSummary(raw: RawCliErrorStatsSummary | undefined): CliErrorStatsSummary {
  return {
    total: Number(raw?.total || 0),
    byCliType: raw?.by_cli_type || {},
    byBot: raw?.by_bot || {},
    byCategory: raw?.by_category || {},
    latestAt: raw?.latest_at || "",
  };
}

function mapCliErrorStatsItem(raw: RawCliErrorStatsItem): CliErrorStatsItem {
  return {
    botAlias: raw.bot_alias || "",
    cliType: raw.cli_type || "",
    workingDir: raw.working_dir || "",
    conversationId: raw.conversation_id || "",
    turnId: raw.turn_id || "",
    startedAt: raw.started_at || "",
    completedAt: raw.completed_at || "",
    errorCode: raw.error_code || "",
    errorMessage: raw.error_message || "",
    category: raw.category || "unknown",
    durationMs: typeof raw.duration_ms === "number" ? raw.duration_ms : null,
  };
}

function mapCliErrorTopItem(raw: RawCliErrorTopItem): CliErrorTopItem {
  return {
    message: raw.message || "",
    count: Number(raw.count || 0),
    category: raw.category || "unknown",
    latestAt: raw.latest_at || "",
  };
}

function mapCliErrorStatsResult(raw: RawCliErrorStatsResult): CliErrorStatsResult {
  return {
    summary: mapCliErrorStatsSummary(raw.summary),
    topErrors: (raw.top_errors || []).map(mapCliErrorTopItem),
    items: (raw.items || []).map(mapCliErrorStatsItem),
  };
}

function calculateDownloadPercent(downloadedBytes: number, totalBytes?: number) {
  if (!totalBytes || totalBytes <= 0) {
    return undefined;
  }
  return Math.min(100, Math.round((downloadedBytes / totalBytes) * 100));
}

function emitFileDownloadProgress(
  onProgress: ((progress: FileDownloadProgress) => void) | undefined,
  downloadedBytes: number,
  totalBytes?: number,
) {
  if (!onProgress) {
    return;
  }
  const percent = calculateDownloadPercent(downloadedBytes, totalBytes);
  onProgress({
    downloadedBytes,
    ...(typeof totalBytes === "number" ? { totalBytes } : {}),
    ...(typeof percent === "number" ? { percent } : {}),
  });
}

async function readDownloadBlobWithProgress(
  response: Response,
  onProgress?: (progress: FileDownloadProgress) => void,
): Promise<Blob> {
  const totalValue = Number(response.headers.get("content-length") || 0);
  const totalBytes = Number.isFinite(totalValue) && totalValue > 0 ? totalValue : undefined;
  emitFileDownloadProgress(onProgress, 0, totalBytes);

  if (!response.body) {
    const blob = await response.blob();
    emitFileDownloadProgress(onProgress, blob.size, totalBytes || blob.size || undefined);
    return blob;
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let downloadedBytes = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    if (!value) {
      continue;
    }
    chunks.push(value);
    downloadedBytes += value.byteLength;
    emitFileDownloadProgress(onProgress, downloadedBytes, totalBytes);
  }

  const contentType = response.headers.get("content-type") || "application/octet-stream";
  return new Blob(chunks, { type: contentType });
}

function mapChatTraceDetails(raw: RawChatTraceDetails): ChatTraceDetails {
  const rawTrace = (raw.trace || [])
    .map((item) => mapTraceEvent(item))
    .filter((item): item is ChatTraceEvent => Boolean(item));
  const nativeFlat = rawTrace.some((item) => String(item.source || "").trim().toLowerCase() === "native_agent");
  const trace = mergeChatTraceEvents([rawTrace], {
    nativeFlat,
    autoNativeFlat: nativeFlat,
  }) || [];
  const summary = summarizeTrace(trace);
  return {
    traceCount: summary.traceCount,
    toolCallCount: summary.toolCallCount,
    processCount: summary.processCount,
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

function mapDebugPhase(rawPhase: unknown): DebugState["phase"] {
  const phase = String(rawPhase || "idle");
  if (phase === "preparing" || phase === "deploying" || phase === "starting_gdb" || phase === "connecting_remote") {
    return "starting";
  }
  if (phase === "terminating") {
    return "stopping";
  }
  if (phase === "idle" || phase === "starting" || phase === "running" || phase === "paused" || phase === "stopping" || phase === "error") {
    return phase;
  }
  return "idle";
}

function mapDebugState(raw: Record<string, unknown>): DebugState {
  return {
    phase: mapDebugPhase(raw.phase),
    detailPhase: String(raw.detailPhase || raw.detail_phase || ""),
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

function mapDebugLaunchSchema(raw: unknown): DebugLaunchSchema {
  if (!raw || typeof raw !== "object") {
    return { fields: [] };
  }
  const schema = raw as Record<string, unknown>;
  return {
    ...schema,
    fields: Array.isArray(schema.fields) ? schema.fields as DebugLaunchField[] : [],
  } as DebugLaunchSchema;
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

function findSseSeparator(buffer: string): { index: number; length: number } | null {
  const lfIndex = buffer.indexOf("\n\n");
  const crlfIndex = buffer.indexOf("\r\n\r\n");
  if (lfIndex < 0 && crlfIndex < 0) {
    return null;
  }
  if (lfIndex < 0) {
    return { index: crlfIndex, length: 4 };
  }
  if (crlfIndex < 0 || lfIndex < crlfIndex) {
    return { index: lfIndex, length: 2 };
  }
  return { index: crlfIndex, length: 4 };
}

function mapNotificationSettings(data: RawNotificationSettings | null | undefined): NotificationSettingsStatus {
  return {
    pushPlusEnabled: Boolean(data?.pushplus_enabled ?? data?.pushPlusEnabled),
    pushPlusConfigured: Boolean(data?.pushplus_configured ?? data?.pushPlusConfigured),
    pushPlusTopicConfigured: Boolean(data?.pushplus_topic_configured ?? data?.pushPlusTopicConfigured),
  };
}

function buildWebSocketUrl(path: string) {
  return buildWsUrl(path);
}

function isWebNotificationEvent(value: unknown): value is WebNotificationEvent {
  return Boolean(value && typeof value === "object" && typeof (value as { type?: unknown }).type === "string");
}

export class RealWebBotClient implements WebBotClient {
  private token = "";
  private notificationPresence: NotificationPresenceUpdate | null = null;
  private notificationPresenceSenders = new Set<(presence: NotificationPresenceUpdate) => void>();

  private headers(extraHeaders: HeadersInit = {}) {
    return {
      ...extraHeaders,
      ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
    };
  }

  private async requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(withApiBase(path), {
      ...init,
      cache: "no-store",
      credentials: "same-origin",
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

  private async requestUpdateStatusStream(
    path: string,
    body: Record<string, unknown>,
    onProgress: (event: AppUpdateDownloadProgress) => void,
    fallbackMessage: string,
  ): Promise<AppUpdateStatus> {
    const response = await fetch(withApiBase(path), {
      method: "POST",
      credentials: "same-origin",
      headers: this.headers({
        "Content-Type": "application/json",
      }),
      body: JSON.stringify(body),
    });

    if (!response.ok || !response.body) {
      let message = fallbackMessage;
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

      let separator = findSseSeparator(buffer);
      while (separator) {
        const block = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator.length);

        const event = parseSseBlock(block);
        if (!event) {
          separator = findSseSeparator(buffer);
          continue;
        }

        if (event.type === "progress") {
          onProgress(mapAppUpdateDownloadProgress(event));
        } else if (event.type === "log" && event.text) {
          onProgress({
            phase: "log",
            downloadedBytes: 0,
            message: event.text,
          });
        } else if (event.type === "done" && event.status) {
          finalStatus = mapAppUpdateStatus(event.status);
        } else if (event.type === "error") {
          throw new Error(event.message || fallbackMessage);
        }

        separator = findSseSeparator(buffer);
      }
    }

    if (!finalStatus) {
      throw new Error(`${fallbackMessage}，连接已中断`);
    }
    return finalStatus;
  }

  async getPublicHostInfo(): Promise<PublicHostInfo> {
    const response = await fetch(withApiBase("/api/health"), {
      cache: "no-store",
      credentials: "same-origin",
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

  async getNotificationSettings(): Promise<NotificationSettingsStatus> {
    const data = await this.requestJson<RawNotificationSettings>("/api/notifications/settings");
    return mapNotificationSettings(data);
  }

  async sendPushPlusTest(): Promise<NotificationTestResult> {
    const data = await this.requestJson<NotificationTestResult>("/api/notifications/pushplus/test", {
      method: "POST",
      headers: this.headers({ "Content-Type": "application/json" }),
    });
    return { sent: Boolean(data.sent) };
  }

  subscribeNotifications(
    onEvent: (event: WebNotificationEvent) => void,
    options: NotificationSubscriptionOptions = {},
  ): NotificationSubscription {
    const HEARTBEAT_INTERVAL_MS = 25000;
    const MAX_RECONNECT_DELAY_MS = 30000;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let heartbeatTimer: number | null = null;
    let closedByClient = false;
    let reconnectAttempt = 0;

    const clearReconnectTimer = () => {
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const clearHeartbeatTimer = () => {
      if (heartbeatTimer !== null) {
        window.clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
    };

    const sendJson = (payload: Record<string, unknown>) => {
      if (socket?.readyState !== WebSocket.OPEN) {
        return;
      }
      try {
        socket.send(JSON.stringify(payload));
      } catch {
        // Socket may close while the page is being hidden.
      }
    };

    const sendPresence = (presence: NotificationPresenceUpdate) => {
      this.notificationPresence = presence;
      sendJson({ type: "presence_update", ...presence });
    };

    const startHeartbeat = () => {
      clearHeartbeatTimer();
      heartbeatTimer = window.setInterval(() => {
        sendJson({ type: "heartbeat", sentAt: new Date().toISOString() });
      }, HEARTBEAT_INTERVAL_MS);
    };

    const notifyStatus = (status: NotificationSocketStatus) => {
      options.onStatus?.(status);
    };

    const scheduleReconnect = () => {
      if (closedByClient || reconnectTimer !== null) {
        return;
      }
      const delay = Math.min(1000 * (2 ** reconnectAttempt), MAX_RECONNECT_DELAY_MS);
      reconnectAttempt += 1;
      notifyStatus("reconnecting");
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (closedByClient) {
        return;
      }
      clearReconnectTimer();
      clearHeartbeatTimer();
      if (socket && socket.readyState !== WebSocket.CLOSED) {
        try {
          socket.close();
        } catch {
          // ignore close failures
        }
      }
      notifyStatus(reconnectAttempt === 0 ? "connecting" : "reconnecting");
      socket = new WebSocket(buildWebSocketUrl("/api/notifications/ws"));
      socket.addEventListener("open", () => {
        reconnectAttempt = 0;
        notifyStatus("open");
        sendJson({ type: "hello", sentAt: new Date().toISOString() });
        if (this.notificationPresence) {
          sendPresence(this.notificationPresence);
        }
        startHeartbeat();
      });
      socket.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (isWebNotificationEvent(payload)) {
            onEvent(payload);
          }
        } catch {
          return;
        }
      });
      socket.addEventListener("close", () => {
        clearHeartbeatTimer();
        if (closedByClient) {
          notifyStatus("closed");
          return;
        }
        scheduleReconnect();
      });
      socket.addEventListener("error", () => {
        notifyStatus("error");
      });
    };

    const trackedSendPresence = (presence: NotificationPresenceUpdate) => {
      sendPresence(presence);
    };

    this.notificationPresenceSenders.add(trackedSendPresence);
    connect();

    return {
      close: () => {
        closedByClient = true;
        clearReconnectTimer();
        clearHeartbeatTimer();
        this.notificationPresenceSenders.delete(trackedSendPresence);
        if (socket && socket.readyState !== WebSocket.CLOSED) {
          socket.close();
        } else {
          notifyStatus("closed");
        }
      },
      sendPresenceUpdate: trackedSendPresence,
    };
  }

  sendNotificationPresenceUpdate(presence: NotificationPresenceUpdate): void {
    this.notificationPresence = presence;
    this.notificationPresenceSenders.forEach((sendPresence) => sendPresence(presence));
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
    this.token = "";
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
    this.token = "";
    return mapSessionState(data);
  }

  async loginGuest(): Promise<SessionState> {
    const data = await this.requestJson<RawAuthSession>("/api/auth/guest", {
      method: "POST",
    });
    this.token = "";
    return mapSessionState(data);
  }

  async restoreSession(token = ""): Promise<SessionState> {
    const legacyToken = token.trim();
    this.token = legacyToken;
    try {
      const data = await this.requestJson<RawAuthSession>("/api/auth/me");
      return {
        ...mapSessionState(data),
        token: "",
      };
    } finally {
      this.token = "";
    }
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

  async listAnnouncements(): Promise<AnnouncementListResult> {
    const data = await this.requestJson<RawAnnouncementListResult>("/api/announcements");
    return mapAnnouncementList(data);
  }

  async markAnnouncementsSeen(latestId: string): Promise<AnnouncementListResult> {
    const data = await this.requestJson<RawAnnouncementListResult>("/api/announcements/seen", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ latest_id: latestId }),
    });
    return mapAnnouncementList(data);
  }

  async upsertAnnouncement(input: CreateAnnouncementInput): Promise<AnnouncementItem> {
    const data = await this.requestJson<RawAnnouncementItem>("/api/admin/announcements", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(mapAnnouncementInput(input)),
    });
    return mapAnnouncementItem(data);
  }

  async deleteAnnouncement(id: string): Promise<{ deleted: boolean }> {
    const data = await this.requestJson<{ deleted?: boolean }>(`/api/admin/announcements/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    return { deleted: Boolean(data.deleted) };
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

  async listAdminUsers(): Promise<AdminUser[]> {
    const data = await this.requestJson<{ items: RawAdminUser[] }>("/api/admin/users");
    return Array.isArray(data.items) ? data.items.map((item) => mapAdminUser(item)) : [];
  }

  async updateUser(accountId: string, input: AdminUserUpdateInput): Promise<AdminUser> {
    const data = await this.requestJson<RawAdminUser>(`/api/admin/users/${encodeURIComponent(accountId)}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...(typeof input.disabled === "boolean" ? { disabled: input.disabled } : {}),
        ...(Array.isArray(input.capabilities) ? { capabilities: input.capabilities } : {}),
      }),
    });
    return mapAdminUser(data);
  }

  async updateUserBotPermissions(accountId: string, allowedBots: string[]): Promise<UserBotPermissions> {
    const data = await this.requestJson<{ account_id?: string; allowed_bots?: string[] }>(
      `/api/admin/users/${encodeURIComponent(accountId)}/permissions`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          allowed_bots: allowedBots,
        }),
      },
    );
    return mapUserBotPermissions(data);
  }

  async getTransferBridgeStatus(): Promise<TransferBridgeStatus> {
    const data = await this.requestJson<RawTransferBridgeStatus>("/api/transfer/status");
    return mapTransferBridgeStatus(data);
  }

  async getTransferAdminStatus(): Promise<TransferBridgeStatus> {
    const data = await this.requestJson<RawTransferBridgeStatus>("/api/admin/transfer/status");
    return mapTransferBridgeStatus(data);
  }

  async updateTransferBridgeConfig(input: TransferBridgeConfigInput): Promise<TransferBridgeStatus> {
    const data = await this.requestJson<RawTransferBridgeStatus>("/api/admin/transfer/config", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(mapTransferBridgeConfigInput(input)),
    });
    return mapTransferBridgeStatus(data);
  }

  async resetTransferBridgeStats(): Promise<TransferBridgeStatus> {
    const data = await this.requestJson<RawTransferBridgeStatus>("/api/admin/transfer/reset", {
      method: "POST",
    });
    return mapTransferBridgeStatus(data);
  }

  async getEnvConfig(): Promise<EnvConfigSnapshot> {
    const data = await this.requestJson<RawEnvConfigSnapshot>("/api/admin/env");
    return mapEnvConfigSnapshot(data);
  }

  async previewEnvConfig(input: EnvConfigPatchInput): Promise<EnvConfigPatchResult> {
    const data = await this.requestJson<RawEnvConfigPatchResult>("/api/admin/env/reload-preview", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(mapEnvPatchInput(input)),
    });
    return mapEnvPatchResult(data);
  }

  async updateEnvConfig(input: EnvConfigPatchInput): Promise<EnvConfigPatchResult> {
    const data = await this.requestJson<RawEnvConfigPatchResult>("/api/admin/env", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(mapEnvPatchInput(input)),
    });
    return mapEnvPatchResult(data);
  }

  async getCliErrorStats(filters: CliErrorStatsFilters = {}): Promise<CliErrorStatsResult> {
    const params = new URLSearchParams();
    if (filters.hours) params.set("hours", String(filters.hours));
    if (filters.alias) params.set("alias", filters.alias);
    if (filters.cliType) params.set("cli_type", filters.cliType);
    if (filters.category) params.set("category", filters.category);
    if (filters.limit) params.set("limit", String(filters.limit));
    const query = params.toString();
    const data = await this.requestJson<RawCliErrorStatsResult>(`/api/admin/cli-errors${query ? `?${query}` : ""}`);
    return mapCliErrorStatsResult(data);
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

  async installPlugin(input: string | {
    pluginId?: string;
    sourcePath?: string;
    force?: boolean;
    allowDevSourcePath?: boolean;
  }): Promise<PluginSummary> {
    const body = typeof input === "string" ? { pluginId: input } : input;
    return this.requestJson<PluginSummary>("/api/plugins/install", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
  }

  async uninstallPlugin(pluginId: string): Promise<void> {
    await this.requestJson(`/api/plugins/${encodeURIComponent(pluginId)}`, {
      method: "DELETE",
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
    appendExecutionModeParam(params, options.executionMode);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<{
      bot: RawBotSummary;
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
      agents: (data.agents || []).map(mapAgentSummary),
      activeClusterRun: mapActiveClusterRun(data.active_cluster_run),
      activeAgentId: String(data.active_agent_id || options.agentId || "main"),
      busyAgentIds: summary.busyAgentIds || [],
      busyAgentNames: summary.busyAgentNames || [],
      busyAgentCount: summary.busyAgentCount || 0,
    };
    return overview;
  }

  async listMessages(botAlias: string, options: AgentScopedOptions = {}): Promise<ChatMessage[]> {
    const params = new URLSearchParams();
    appendAgentParam(params, options.agentId);
    appendExecutionModeParam(params, options.executionMode);
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
    appendExecutionModeParam(params, options.executionMode);
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
          ...scopedRequestBody(options),
        }),
      },
    );
    return {
      conversation: mapConversationSummary(data.conversation),
      messages: data.messages.map((item, index) => mapChatMessage(item, index)),
    };
  }

  async executePlan(botAlias: string, input: PlanExecuteInput): Promise<PlanExecuteResult> {
    const data = await this.requestJson<RawPlanExecuteResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/plans/execute`,
      {
        method: "POST",
        headers: this.headers({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          content: input.content,
          ...(input.title ? { title: input.title } : {}),
          ...(input.agentId ? { agent_id: input.agentId } : {}),
          ...(input.executionMode ? { execution_mode: input.executionMode } : {}),
          ...(input.cluster ? { cluster: true } : {}),
          ...(input.mentions ? {
            mentions: input.mentions.map((mention) => ({
              agent_id: mention.agentId,
              label: mention.label,
              start: mention.start,
              end: mention.end,
            })),
          } : {}),
        }),
      },
    );
    return {
      planPath: String(data.plan_path || ""),
      conversation: mapConversationSummary(data.conversation),
      messages: (data.messages || []).map((item, index) => mapChatMessage(item, index)),
      executionMessage: String(data.execution_message || ""),
    };
  }

  async selectConversation(botAlias: string, conversationId: string, options: AgentScopedOptions = {}): Promise<ConversationSelectResult> {
    const data = await this.requestJson<{ conversation: RawConversationSummary; messages: RawHistoryItem[] }>(
      `/api/bots/${encodeURIComponent(botAlias)}/conversations/${encodeURIComponent(conversationId)}/select`,
      {
        method: "POST",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify(scopedRequestBody(options)),
      },
    );
    return {
      conversation: mapConversationSummary(data.conversation),
      messages: data.messages.map((item, index) => mapChatMessage(item, index)),
    };
  }

  async listFavoriteAnswers(botAlias: string, query = "", options: AgentScopedOptions = {}): Promise<FavoriteAnswerListResult> {
    const params = new URLSearchParams();
    if (query.trim()) {
      params.set("q", query.trim());
    }
    appendAgentParam(params, options.agentId);
    appendExecutionModeParam(params, options.executionMode);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<{ items?: RawFavoriteAnswerItem[]; execution_mode?: string; executionMode?: string }>(
      `/api/bots/${encodeURIComponent(botAlias)}/favorites${suffix}`,
    );
    return {
      items: (data.items || []).map(mapFavoriteAnswerItem),
      executionMode: normalizeFavoriteExecutionMode(data.execution_mode ?? data.executionMode ?? options.executionMode),
    };
  }

  async favoriteAnswer(botAlias: string, input: FavoriteAnswerInput, options: AgentScopedOptions = {}): Promise<FavoriteAnswerItem> {
    const data = await this.requestJson<{ item: RawFavoriteAnswerItem }>(
      `/api/bots/${encodeURIComponent(botAlias)}/favorites`,
      {
        method: "POST",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          conversation_id: input.conversationId,
          message_id: input.messageId,
          message_key: input.messageKey,
          ...(input.turnId ? { turn_id: input.turnId } : {}),
          ...(input.title ? { title: input.title } : {}),
          ...(input.preview ? { preview: input.preview } : {}),
          ...(input.answerText ? { answer_text: input.answerText } : {}),
          ...scopedRequestBody(options),
        }),
      },
    );
    return mapFavoriteAnswerItem(data.item);
  }

  async deleteFavoriteAnswer(botAlias: string, favoriteId: string, options: AgentScopedOptions = {}): Promise<{ deleted: boolean; favoriteId: string }> {
    const params = new URLSearchParams();
    appendAgentParam(params, options.agentId);
    appendExecutionModeParam(params, options.executionMode);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<{ deleted?: boolean; favorite_id?: string; favoriteId?: string }>(
      `/api/bots/${encodeURIComponent(botAlias)}/favorites/${encodeURIComponent(favoriteId)}${suffix}`,
      {
        method: "DELETE",
        headers: this.headers(),
      },
    );
    return {
      deleted: Boolean(data.deleted),
      favoriteId: String(data.favorite_id ?? data.favoriteId ?? favoriteId),
    };
  }

  async deleteConversation(
    botAlias: string,
    conversationId: string,
    options: AgentScopedOptions & { deleteNativeSession?: boolean } = {},
  ): Promise<ConversationDeleteResult> {
    const params = new URLSearchParams();
    appendAgentParam(params, options.agentId);
    appendExecutionModeParam(params, options.executionMode);
    if (options.deleteNativeSession) {
      params.set("delete_native_session", "true");
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<RawConversationDeleteResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/conversations/${encodeURIComponent(conversationId)}${suffix}`,
      {
        method: "DELETE",
        headers: this.headers(),
      },
    );
    return {
      deletedConversationId: String(data.deleted_conversation_id || ""),
      deletedFavoriteCount: Number(data.deleted_favorite_count || 0),
      activeConversationId: String(data.active_conversation_id || ""),
      nativeSessionCleared: Boolean(data.native_session_cleared),
      items: (data.items || []).map(mapConversationSummary),
      ...(Array.isArray(data.messages) ? { messages: data.messages.map((item, index) => mapChatMessage(item, index)) } : {}),
    };
  }

  async deleteAllConversations(
    botAlias: string,
    options: AgentScopedOptions & { deleteNativeSession?: boolean } = {},
  ): Promise<ConversationBulkDeleteResult> {
    const params = new URLSearchParams();
    appendAgentParam(params, options.agentId);
    appendExecutionModeParam(params, options.executionMode);
    if (options.deleteNativeSession) {
      params.set("delete_native_session", "true");
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<RawConversationBulkDeleteResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/conversations${suffix}`,
      {
        method: "DELETE",
        headers: this.headers(),
      },
    );
    return {
      deletedCount: Number(data.deleted_count || 0),
      deletedFavoriteCount: Number(data.deleted_favorite_count || 0),
      activeConversationId: String(data.active_conversation_id || ""),
      nativeSessionCleared: Boolean(data.native_session_cleared),
      items: (data.items || []).map(mapConversationSummary),
      messages: Array.isArray(data.messages) ? data.messages.map((item, index) => mapChatMessage(item, index)) : [],
    };
  }

  async listMessageDelta(botAlias: string, afterId: string, limit = 50, options: AgentScopedOptions = {}): Promise<HistoryDeltaResult> {
    const params = new URLSearchParams({
      after_id: afterId,
      limit: String(limit),
    });
    appendAgentParam(params, options.agentId);
    appendExecutionModeParam(params, options.executionMode);
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
    appendExecutionModeParam(params, options.executionMode);
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
    onAgUiEvent?: (event: AgUiEvent) => void,
  ): Promise<ChatMessage> {
    const useAgUiProtocol = options?.executionMode === "native_agent";
    const streamUrl = `/api/bots/${encodeURIComponent(botAlias)}/chat/stream${useAgUiProtocol ? "?protocol=ag-ui" : ""}`;
    const response = await fetch(withApiBase(streamUrl), {
      method: "POST",
      credentials: "same-origin",
      headers: this.headers({
        "Content-Type": "application/json",
      }),
      body: JSON.stringify({
        message: text,
        ...(options?.taskMode ? { task_mode: options.taskMode } : {}),
        ...(options?.taskPayload ? { task_payload: options.taskPayload } : {}),
        ...(options?.visibleText ? { visible_text: options.visibleText } : {}),
        ...(options?.agentId ? { agent_id: options.agentId } : {}),
        ...(options?.executionMode ? { execution_mode: options.executionMode } : {}),
        ...(options?.soloMode ? { solo_mode: true } : {}),
        ...(useAgUiProtocol ? { protocol: "ag-ui" } : {}),
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
    let streamTurnId = "";
    let streamAssistantMessageId = "";
    const streamedTrace: ChatTraceEvent[] = [];
    let streamedContextUsage: ChatMessageContextUsage | undefined;
    let streamFinished = false;
    const agUiAdapter = createAgUiStreamAdapter();
    let agUiState = createAgUiRunState();
    let sawAgUiEvent = false;

    while (!streamFinished) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      let separator = findSseSeparator(buffer);
      while (separator) {
        const block = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator.length);

        const event = parseSseBlock(block);
        if (!event) {
          separator = findSseSeparator(buffer);
          continue;
        }

        const shouldAdaptAgUiEvent = useAgUiProtocol || isAgUiEventType(event.type);
        const agUiEvents = shouldAdaptAgUiEvent ? agUiAdapter.adapt(event) : [];
        if (agUiEvents.length > 0) {
          sawAgUiEvent = true;
          for (const agUiEvent of agUiEvents) {
            agUiState = reduceAgUiRunEvent(agUiState, agUiEvent);
            onAgUiEvent?.(agUiEvent);
            const activityContent = contentForAgUiActivityEvent(agUiState.activities, agUiEvent);
            const traceEvent = mapAgUiTraceEvent(agUiEvent, activityContent);
            if (traceEvent) {
              const nativeFlatTrace = options?.executionMode === "native_agent";
              const mergedTrace = mergeChatTraceEvents([streamedTrace, [traceEvent]], {
                nativeFlat: nativeFlatTrace,
                autoNativeFlat: nativeFlatTrace,
              });
              streamedTrace.splice(0, streamedTrace.length, ...(mergedTrace || []));
            }
            if (agUiEvent.type === EventType.ACTIVITY_SNAPSHOT || agUiEvent.type === EventType.ACTIVITY_DELTA) {
              const content = activityContent;
              if (agUiEvent.activityType === "TCB_STATUS") {
                const contextUsage = mapContextUsage(content.contextUsage ?? content.context_usage);
                if (contextUsage) {
                  streamedContextUsage = contextUsage;
                }
                if (typeof content.elapsedSeconds === "number") {
                  finalElapsedSeconds = content.elapsedSeconds;
                }
              }
            }
            if (agUiEvent.type === EventType.RUN_ERROR) {
              finalText = agUiState.assistantText || finalText || streamedText || agUiEvent.message;
            }
            if (agUiEvent.type === EventType.RUN_FINISHED) {
              const result = agUiEvent.result && typeof agUiEvent.result === "object" && !Array.isArray(agUiEvent.result)
                ? agUiEvent.result as Record<string, unknown>
                : {};
              const resultContent = typeof result.content === "string" ? result.content.trim() : "";
              finalText = resultContent || finalText || agUiState.assistantText || streamedText;
              finalElapsedSeconds = agUiState.elapsedSeconds ?? finalElapsedSeconds;
              streamFinished = true;
              await reader.cancel().catch(() => undefined);
              break;
            }
          }
          if (streamFinished) {
            break;
          }
        }

        if (sawAgUiEvent && event.type !== "done" && event.type !== "error") {
          separator = findSseSeparator(buffer);
          continue;
        }

        if (event.type === "delta" && event.text) {
          streamedText += event.text;
          onChunk(event.text);
        } else if (event.type === "snapshot") {
          streamedText = typeof event.text === "string" ? event.text : "";
          onStatus?.({
            elapsedSeconds: event.elapsed_seconds,
            previewText: streamedText,
            replaceText: streamedText,
          });
        } else if (event.type === "meta") {
          const clusterRunId = typeof event.cluster_run_id === "string" ? event.cluster_run_id : "";
          const turnId = typeof (event.turn_id ?? event.turnId) === "string" ? (event.turn_id ?? event.turnId) as string : "";
          const assistantMessageId = typeof (event.assistant_message_id ?? event.assistantMessageId) === "string"
            ? (event.assistant_message_id ?? event.assistantMessageId) as string
            : "";
          if (turnId) {
            streamTurnId = turnId;
          }
          if (assistantMessageId) {
            streamAssistantMessageId = assistantMessageId;
          }
          if (clusterRunId || turnId || assistantMessageId) {
            onStatus?.({
              ...(clusterRunId ? { clusterRunId } : {}),
              ...(turnId ? { turnId } : {}),
              ...(assistantMessageId ? { assistantMessageId } : {}),
            });
          }
        } else if (event.type === "status") {
          if (typeof event.elapsed_seconds === "number") {
            finalElapsedSeconds = event.elapsed_seconds;
          }
          const contextUsage = mapContextUsage(event.context_usage);
          if (contextUsage) {
            streamedContextUsage = contextUsage;
          }
          const statusUpdate: ChatStatusUpdate = {
            elapsedSeconds: event.elapsed_seconds,
            previewText: event.preview_text,
          };
          if (contextUsage) {
            statusUpdate.contextUsage = contextUsage;
          }
          onStatus?.(statusUpdate);
        } else if (event.type === "trace") {
          const traceEvent = mapTraceEvent(event.event);
          if (traceEvent) {
            const nativeFlatTrace = options?.executionMode === "native_agent";
            const mergedTrace = mergeChatTraceEvents([streamedTrace, [traceEvent]], {
              nativeFlat: nativeFlatTrace,
              autoNativeFlat: nativeFlatTrace,
            });
            streamedTrace.splice(0, streamedTrace.length, ...(mergedTrace || []));
            onTrace?.(traceEvent);
          }
        } else if (event.type === "done") {
          if (event.message) {
            finalMessage = mapChatMessage(event.message, 0);
            finalMessage.meta = mergeMessageMeta(
              streamedContextUsage ? { contextUsage: streamedContextUsage } : undefined,
              finalMessage.meta,
              streamedTrace,
            );
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

        separator = findSseSeparator(buffer);
      }
    }

    if (finalMessage) {
      if (sawAgUiEvent) {
        return normalizeResolvedFinalMessage({
          ...finalMessage,
          text: finalMessage.text || finalText || agUiState.assistantText,
          elapsedSeconds: finalMessage.elapsedSeconds ?? agUiState.elapsedSeconds ?? finalElapsedSeconds,
          meta: mergeMessageMeta(
            agUiState.contextUsage ? { contextUsage: agUiState.contextUsage } : undefined,
            mergeMessageMeta(
              finalMessage.meta,
              buildAgUiMessageMeta(agUiState, { nativeAgent: options?.executionMode === "native_agent" }),
            ),
          ),
        });
      }
      return normalizeResolvedFinalMessage({
        ...finalMessage,
        ...(!finalMessage.turnId && streamTurnId ? { turnId: streamTurnId } : {}),
        elapsedSeconds: finalMessage.elapsedSeconds ?? finalElapsedSeconds,
        meta: finalMessage.meta,
      });
    }

    if (sawAgUiEvent) {
      const meta = mergeMessageMeta(
        agUiState.contextUsage ? { contextUsage: agUiState.contextUsage } : undefined,
        buildAgUiMessageMeta(agUiState, { nativeAgent: options?.executionMode === "native_agent" }),
      );
      const completionState = meta?.completionState || "";
      return {
        id: agUiState.messageId || streamAssistantMessageId || `assistant-${Date.now()}`,
        ...(streamTurnId ? { turnId: streamTurnId } : {}),
        role: "assistant",
        text: finalText || agUiState.assistantText || streamedText,
        createdAt: new Date().toISOString(),
        state: agUiState.error || (completionState && completionState !== "completed") ? "error" : "done",
        ...(typeof (agUiState.elapsedSeconds ?? finalElapsedSeconds) === "number"
          ? { elapsedSeconds: agUiState.elapsedSeconds ?? finalElapsedSeconds }
          : {}),
        ...(meta ? { meta } : {}),
      };
    }

    const messageText = finalText || streamedText;
    const meta = mergeMessageMeta(
      streamedContextUsage ? { contextUsage: streamedContextUsage } : undefined,
      undefined,
      streamedTrace,
    );
    return {
      id: streamAssistantMessageId || `assistant-${Date.now()}`,
      ...(streamTurnId ? { turnId: streamTurnId } : {}),
      role: "assistant",
      text: messageText,
      createdAt: new Date().toISOString(),
      state: "done",
      ...(typeof finalElapsedSeconds === "number" ? { elapsedSeconds: finalElapsedSeconds } : {}),
      ...(meta ? { meta } : {}),
    };
  }

  async replyNativeAgentPermission(
    botAlias: string,
    permissionId: string,
    options: NativeAgentPermissionReplyOptions,
  ): Promise<{ permissionId: string; approved: boolean }> {
    const data = await this.requestJson<{
      permission_id?: string;
      permissionId?: string;
      approved?: boolean;
    }>(
      `/api/bots/${encodeURIComponent(botAlias)}/native-agent/permissions/${encodeURIComponent(permissionId)}/reply`,
      {
        method: "POST",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          ...scopedRequestBody(options),
          approved: Boolean(options.approved),
          ...(options.message ? { message: options.message } : {}),
          ...(typeof options.value !== "undefined" ? { value: options.value } : {}),
        }),
      },
    );
    return {
      permissionId: String(data.permission_id || data.permissionId || permissionId),
      approved: Boolean(data.approved),
    };
  }

  async getDebugProfile(botAlias: string): Promise<DebugProfile | null> {
    const data = await this.requestJson<Record<string, unknown> | null>(`/api/bots/${encodeURIComponent(botAlias)}/debug/profile`);
    if (!data) {
      return null;
    }
    const rawSourceMaps = data.sourceMaps || data.source_maps;
    const target = data.target && typeof data.target === "object" ? data.target as Record<string, unknown> : {};
    const prepare = data.prepare && typeof data.prepare === "object" ? data.prepare as Record<string, unknown> : {};
    const launchSchema = mapDebugLaunchSchema(data.launchSchema || data.launch_schema);
    const capabilities = data.capabilities && typeof data.capabilities === "object"
      ? data.capabilities as DebugCapabilityMap
      : {};
    const remoteConfig = data.remote && typeof data.remote === "object" ? data.remote as Record<string, unknown> : undefined;
    const ui = data.ui && typeof data.ui === "object" ? data.ui as Record<string, unknown> : {};
    return {
      specVersion: Number(data.specVersion || data.spec_version || 0) || undefined,
      providerId: String(data.providerId || data.provider_id || "cpp-gdb"),
      providerLabel: String(data.providerLabel || data.provider_label || "C++ GDB"),
      language: String(data.language || ""),
      configName: String(data.configName || data.config_name || ""),
      workspace: String(data.workspace || ""),
      target,
      prepare,
      capabilities,
      ui,
      launchSchema,
      launchDefaults: data.launchDefaults && typeof data.launchDefaults === "object" ? data.launchDefaults as Record<string, unknown> : {},
      providerConfig: data.providerConfig && typeof data.providerConfig === "object" ? data.providerConfig as Record<string, unknown> : {},
      program: String(data.program || target.program || ""),
      cwd: String(data.cwd || target.cwd || ""),
      miDebuggerPath: String(data.mi_debugger_path || data.miDebuggerPath || ""),
      compileCommands: String(data.compile_commands || data.compileCommands || ""),
      prepareCommand: String(data.prepare_command || data.prepareCommand || prepare.command || ""),
      stopAtEntry: Boolean(data.stop_at_entry ?? data.stopAtEntry ?? ui.stopAtEntry ?? true),
      setupCommands: Array.isArray(data.setup_commands) ? data.setup_commands.map((item) => String(item)) : [],
      remoteHost: String(data.remote_host || data.remoteHost || remoteConfig?.host || ""),
      remoteUser: String(data.remote_user || data.remoteUser || remoteConfig?.user || ""),
      remoteDir: String(data.remote_dir || data.remoteDir || remoteConfig?.dir || ""),
      remotePort: Number(data.remote_port || data.remotePort || remoteConfig?.port || 0),
      remote: remoteConfig,
      gdb: data.gdb && typeof data.gdb === "object" ? data.gdb as Record<string, unknown> : undefined,
      sourceMaps: Array.isArray(rawSourceMaps)
        ? rawSourceMaps
          .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
          .map((item) => ({ remote: String(item.remote || ""), local: String(item.local || "") }))
        : [],
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

  async openBotWorkdir(botAlias: string): Promise<BotWorkdirOpenResult> {
    return this.requestJson<BotWorkdirOpenResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/open-workdir`, {
      method: "POST",
    });
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

  async createWorkdirDirectory(botAlias: string, parentPath: string, name: string): Promise<void> {
    await this.requestJson(`/api/bots/${encodeURIComponent(botAlias)}/workdir/mkdir`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        parent_path: parentPath,
        name,
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
      encoding: data.encoding,
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
      encoding: data.encoding,
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

  async getPluginArtifactBlob(botAlias: string, artifactId: string): Promise<Blob> {
    const response = await fetch(
      withApiBase(`/api/bots/${encodeURIComponent(botAlias)}/plugins/artifacts/${encodeURIComponent(artifactId)}`),
      {
        credentials: "same-origin",
        headers: this.headers(),
      },
    );
    if (!response.ok) {
      throw new Error("读取插件产物失败");
    }
    return response.blob();
  }

  async downloadPluginArtifact(botAlias: string, artifactId: string, filename: string): Promise<void> {
    const response = await fetch(
      withApiBase(`/api/bots/${encodeURIComponent(botAlias)}/plugins/artifacts/${encodeURIComponent(artifactId)}`),
      {
        credentials: "same-origin",
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

  async writeFile(botAlias: string, path: string, content: string, expectedMtimeNs?: string, encoding?: string): Promise<FileWriteResult> {
    const data = await this.requestJson<RawFileWriteResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/write`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        path,
        content,
        expected_mtime_ns: expectedMtimeNs,
        encoding,
      }),
    });
    return {
      path: data.path,
      fileSizeBytes: data.file_size_bytes,
      lastModifiedNs: String(data.last_modified_ns),
      encoding: data.encoding,
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
    const response = await fetch(withApiBase(`/api/bots/${encodeURIComponent(botAlias)}/files/upload`), {
      method: "POST",
      credentials: "same-origin",
      headers: this.headers(),
      body: formData,
    });
    if (!response.ok) {
      throw new Error("上传失败");
    }
  }

  async downloadFile(botAlias: string, filename: string, onProgress?: (progress: FileDownloadProgress) => void): Promise<void> {
    const params = new URLSearchParams({ filename });
    const response = await fetch(withApiBase(`/api/bots/${encodeURIComponent(botAlias)}/files/download?${params.toString()}`), {
      credentials: "same-origin",
      headers: this.headers(),
    });
    if (!response.ok) {
      throw new Error("下载失败");
    }
    const blob = await readDownloadBlobWithProgress(response as Response, onProgress);
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

  async killTask(botAlias: string, options: AgentScopedOptions = {}): Promise<string> {
    const data = await this.requestJson<{ message?: string }>(`/api/bots/${encodeURIComponent(botAlias)}/kill`, {
      method: "POST",
      headers: this.headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(scopedRequestBody(options)),
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
      const response = await fetch(withApiBase("/api/admin/restart"), {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
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
    return this.requestUpdateStatusStream(
      "/api/admin/update/download/stream",
      {},
      onProgress,
      "下载更新失败",
    );
  }

  async listOfflineUpdatePackages(): Promise<OfflineUpdatePackageList> {
    const data = await this.requestJson<RawOfflineUpdatePackageList>("/api/admin/update/offline/packages");
    return mapOfflineUpdatePackageList(data);
  }

  async prepareOfflineUpdate(path: string, version = ""): Promise<AppUpdateStatus> {
    const data = await this.requestJson<RawAppUpdateStatus>("/api/admin/update/offline/prepare", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        path,
        ...(version ? { version } : {}),
      }),
    });
    return mapAppUpdateStatus(data);
  }

  async prepareOfflineUpdateStream(
    path: string,
    version: string | undefined,
    onProgress: (event: AppUpdateDownloadProgress) => void,
  ): Promise<AppUpdateStatus> {
    return this.requestUpdateStatusStream(
      "/api/admin/update/offline/prepare/stream",
      {
        path,
        ...(version ? { version } : {}),
      },
      onProgress,
      "设置离线更新失败",
    );
  }

  async getGitOverview(botAlias: string): Promise<GitOverview> {
    const data = await this.requestJson<RawGitOverview>(`/api/bots/${encodeURIComponent(botAlias)}/git`);
    return mapGitOverview(data);
  }

  async getGitTreeStatus(botAlias: string): Promise<GitTreeStatus> {
    const data = await this.requestJson<RawGitTreeStatus>(`/api/bots/${encodeURIComponent(botAlias)}/git/tree-status`);
    return mapGitTreeStatus(data);
  }

  async getGitCommitGraph(botAlias: string, options: GitCommitGraphOptions = {}): Promise<GitCommitGraphPayload> {
    const params = new URLSearchParams();
    params.set("scope", options.scope || "all");
    if (typeof options.limit === "number") {
      params.set("limit", String(options.limit));
    }
    if (options.cursor) {
      params.set("cursor", options.cursor);
    }
    const data = await this.requestJson<RawGitCommitGraphPayload>(
      `/api/bots/${encodeURIComponent(botAlias)}/git/graph?${params.toString()}`,
    );
    return mapGitCommitGraph(data);
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

  async resetGitBranch(botAlias: string, commit: string, mode: GitResetMode): Promise<GitBranchResetResult> {
    const data = await this.requestJson<RawGitBranchResetResult>(`/api/bots/${encodeURIComponent(botAlias)}/git/branches/reset`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ commit, mode }),
    });
    return mapGitBranchResetResult(data);
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

  async getGitIdentityConfig(botAlias: string): Promise<GitIdentityConfig> {
    const data = await this.requestJson<RawGitIdentityConfig>(`/api/bots/${encodeURIComponent(botAlias)}/git/identity`);
    return mapGitIdentityConfig(data);
  }

  async updateGitIdentityConfig(
    botAlias: string,
    input: { scope: GitIdentityScope; name: string; email: string },
  ): Promise<GitIdentityConfig> {
    const data = await this.requestJson<RawGitIdentityConfig>(`/api/bots/${encodeURIComponent(botAlias)}/git/identity`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        scope: input.scope,
        name: input.name,
        email: input.email,
      }),
    });
    return mapGitIdentityConfig(data);
  }

  async getGitCommitMessageConfig(botAlias: string): Promise<GitCommitMessageCliConfig> {
    const data = await this.requestJson<RawGitCommitMessageCliConfig>(
      `/api/bots/${encodeURIComponent(botAlias)}/git/commit-message/config`,
    );
    return mapGitCommitMessageCliConfig(data);
  }

  async updateGitCommitMessageConfig(
    botAlias: string,
    input: GitCommitMessageCliConfigUpdateInput,
  ): Promise<GitCommitMessageCliConfig> {
    const data = await this.requestJson<RawGitCommitMessageCliConfig>(
      `/api/bots/${encodeURIComponent(botAlias)}/git/commit-message/config`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ...(input.cliType ? { cli_type: input.cliType } : {}),
          ...(input.cliPath !== undefined ? { cli_path: input.cliPath } : {}),
          ...(input.params ? { params: input.params } : {}),
        }),
      },
    );
    return mapGitCommitMessageCliConfig(data);
  }

  async resetGitCommitMessageConfig(botAlias: string): Promise<GitCommitMessageCliConfig> {
    const data = await this.requestJson<RawGitCommitMessageCliConfig>(
      `/api/bots/${encodeURIComponent(botAlias)}/git/commit-message/config/reset`,
      {
        method: "POST",
      },
    );
    return mapGitCommitMessageCliConfig(data);
  }

  async generateGitCommitMessage(botAlias: string): Promise<GitCommitMessageGenerateResult> {
    const data = await this.requestJson<RawGitCommitMessageGenerateResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/git/commit-message/generate`,
      {
        method: "POST",
      },
    );
    return mapGitCommitMessageGenerateResult(data);
  }

  async startGitSmartCommit(botAlias: string): Promise<GitSmartCommitJob> {
    const data = await this.requestJson<RawGitSmartCommitJob>(`/api/bots/${encodeURIComponent(botAlias)}/git/smart-commit`, {
      method: "POST",
    });
    return mapGitSmartCommitJob(data);
  }

  async getActiveGitSmartCommit(botAlias: string): Promise<GitSmartCommitJob | null> {
    const data = await this.requestJson<RawGitSmartCommitJob | null>(
      `/api/bots/${encodeURIComponent(botAlias)}/git/smart-commit/active`,
    );
    return data ? mapGitSmartCommitJob(data) : null;
  }

  async getGitSmartCommitJob(botAlias: string, jobId: string): Promise<GitSmartCommitJob> {
    const data = await this.requestJson<RawGitSmartCommitJob>(
      `/api/bots/${encodeURIComponent(botAlias)}/git/smart-commit/${encodeURIComponent(jobId)}`,
    );
    return mapGitSmartCommitJob(data);
  }

  async getLanChatConfig(): Promise<LanChatConfig> {
    return mapLanChatConfig(await this.requestJson("/api/admin/lan-chat/config"));
  }

  async updateLanChatConfig(input: LanChatConfigInput): Promise<LanChatConfig> {
    return mapLanChatConfig(await this.requestJson("/api/admin/lan-chat/config", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...(input.mode ? { mode: input.mode } : {}),
        ...(input.roomName !== undefined ? { room_name: input.roomName } : {}),
        ...(input.instanceName !== undefined ? { instance_name: input.instanceName } : {}),
        ...(input.hostUrl !== undefined ? { host_url: input.hostUrl } : {}),
        ...(input.roomKey !== undefined ? { room_key: input.roomKey } : {}),
        ...(input.lanOnly !== undefined ? { lan_only: input.lanOnly } : {}),
        ...(input.autoConnect !== undefined ? { auto_connect: input.autoConnect } : {}),
      }),
    }));
  }

  async getLanChatStatus(): Promise<LanChatStatus> {
    return mapLanChatStatus(await this.requestJson("/api/lan-chat/status"));
  }

  async listLanChatConversations(): Promise<LanChatConversation[]> {
    const data = await this.requestJson<{ items?: unknown[] }>("/api/lan-chat/conversations");
    return Array.isArray(data.items) ? data.items.map(mapLanChatConversation) : [];
  }

  async listLanChatMessages(conversationId: string, afterSeq = 0, limit = 50): Promise<LanChatMessage[]> {
    const data = await this.requestJson<{ items?: unknown[] }>(
      `/api/lan-chat/conversations/${encodeURIComponent(conversationId)}/messages?after_seq=${afterSeq}&limit=${limit}`,
    );
    return Array.isArray(data.items) ? data.items.map(mapLanChatMessage) : [];
  }

  async createLanChatPrivateConversation(targetRoomUserId: string): Promise<LanChatConversation> {
    return mapLanChatConversation(await this.requestJson("/api/lan-chat/private-conversations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ target_room_user_id: targetRoomUserId }),
    }));
  }

  async sendLanChatMessage(conversationId: string, text: string): Promise<LanChatMessage> {
    return mapLanChatMessage(await this.requestJson(
      `/api/lan-chat/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ text }),
      },
    ));
  }

  async markLanChatRead(conversationId: string, seq: number): Promise<void> {
    await this.requestJson(`/api/lan-chat/conversations/${encodeURIComponent(conversationId)}/read`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ seq }),
    });
  }

  openLanChatSocket(onEvent: (event: LanChatEvent) => void): () => void {
    const socket = new WebSocket(buildWsUrl("/lan-chat/ws"));
    socket.addEventListener("message", (event) => {
      try {
        const mapped = mapLanChatEvent(JSON.parse(event.data));
        if (mapped) {
          onEvent(mapped);
        }
      } catch {
        return;
      }
    });
    return () => socket.close();
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

  async updateBotExecutionConfig(botAlias: string, input: BotExecutionConfigInput): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/execution`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        supported_execution_modes: input.supportedExecutionModes,
        default_execution_mode: input.defaultExecutionMode,
        native_agent: serializeNativeAgentConfig(input.nativeAgent),
      }),
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

  async updateBotPromptPresets(botAlias: string, presets: PromptPreset[]): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/prompt-presets`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ prompt_presets: serializePromptPresets(presets) }),
    });
    return mapBotSummary(data.bot, Boolean(data.bot.is_processing));
  }

  async updateGlobalPromptPresets(presets: PromptPreset[]): Promise<PromptPreset[]> {
    const data = await this.requestJson<{ global_prompt_presets: RawPromptPreset[] }>(
      "/api/admin/prompt-presets/global",
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ prompt_presets: serializePromptPresets(presets) }),
      },
    );
    return mapPromptPresets(data.global_prompt_presets);
  }

  async addBot(input: CreateBotInput): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>("/api/admin/bots", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        alias: input.alias,
        cli_type: input.cliType,
        cli_path: input.cliPath,
        working_dir: input.workingDir,
        ...(input.supportedExecutionModes ? { supported_execution_modes: input.supportedExecutionModes } : {}),
        ...(input.defaultExecutionMode ? { default_execution_mode: input.defaultExecutionMode } : {}),
        ...(input.nativeAgent ? {
          native_agent: serializeNativeAgentConfig(input.nativeAgent),
        } : {}),
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

  async removeBot(botAlias: string, options: RemoveBotOptions = {}): Promise<RemoveBotResult> {
    const params = new URLSearchParams();
    if (options.deleteHistory || options.deleteWorkspace) {
      params.set("delete_history", "true");
    }
    if (options.deleteWorkspace) {
      params.set("delete_workspace", "true");
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const data = await this.requestJson<RawRemoveBotResult>(`/api/admin/bots/${encodeURIComponent(botAlias)}${suffix}`, {
      method: "DELETE",
    });
    return {
      removed: Boolean(data.removed),
      alias: String(data.alias || botAlias),
      historyDeleted: Boolean(data.history_deleted),
      historyDeletedCount: Number(data.history_deleted_count || 0),
      favoriteDeletedCount: Number(data.favorite_deleted_count || 0),
      workspacePath: String(data.workspace_path || ""),
      workspaceDeleted: Boolean(data.workspace_deleted),
      workspaceMissing: Boolean(data.workspace_missing),
      errors: Array.isArray(data.errors)
        ? data.errors.map((item) => ({ code: item?.code ? String(item.code) : undefined, message: String(item?.message || "") }))
        : [],
    };
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

  async getCliParams(botAlias: string): Promise<CliParamsPayload> {
    const data = await this.requestJson<RawCliParamsPayload>(`/api/bots/${encodeURIComponent(botAlias)}/cli-params`);
    return mapCliParamsPayload(data);
  }

  async getNativeAgentConfig(): Promise<NativeAgentConfigPayload> {
    return mapNativeAgentConfigPayload(await this.requestJson("/api/admin/native-agent/config"));
  }

  async runNativeAgentPreflight(options: { cwd?: string; piCommand?: string } = {}): Promise<NativeAgentPreflightResult> {
    const params = new URLSearchParams();
    if (options.cwd) params.set("cwd", options.cwd);
    if (options.piCommand) params.set("pi_command", options.piCommand);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return mapNativeAgentPreflightResult(await this.requestJson(`/api/admin/native-agent/preflight${suffix}`));
  }

  async updateNativeAgentConfig(config: Record<string, unknown>): Promise<NativeAgentConfigPayload> {
    return mapNativeAgentConfigPayload(await this.requestJson("/api/admin/native-agent/config", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ config }),
    }));
  }

  async getNativeAgentModels(botAlias: string): Promise<NativeAgentModelsPayload> {
    return mapNativeAgentModelsPayload(await this.requestJson(`/api/bots/${encodeURIComponent(botAlias)}/native-agent/models`));
  }

  async updateNativeAgentModel(botAlias: string, model: string, options: NativeAgentModelUpdateOptions = {}): Promise<NativeAgentModelUpdateResult> {
    const body: Record<string, unknown> = { model };
    if (Object.prototype.hasOwnProperty.call(options, "reasoningEffort")) {
      body.reasoning_effort = options.reasoningEffort || "";
    }
    const raw = await this.requestJson<Record<string, unknown>>(`/api/bots/${encodeURIComponent(botAlias)}/native-agent/model`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    const mapped = mapNativeAgentModelsPayload(raw);
    const bot = raw.bot ? mapBotSummary(raw.bot as RawBotSummary, Boolean((raw.bot as RawBotSummary).is_processing)) : undefined;
    return { ...mapped, ...(bot ? { bot } : {}) };
  }

  async getNativeAgentHistoryChanges(
    botAlias: string,
    input: { conversationId: string; turnId: string; agentId?: string },
  ): Promise<NativeAgentHistoryChangesPayload> {
    const params = new URLSearchParams({
      conversation_id: input.conversationId,
      turn_id: input.turnId,
    });
    appendAgentParam(params, input.agentId);
    const data = await this.requestJson<RawNativeAgentHistoryChangesPayload>(
      `/api/bots/${encodeURIComponent(botAlias)}/native-agent/history/changes?${params.toString()}`,
    );
    return mapNativeAgentHistoryChanges(data);
  }

  async getNativeAgentHistoryDiff(
    botAlias: string,
    input: { conversationId: string; turnId: string; path: string; agentId?: string },
  ): Promise<NativeAgentHistoryDiffPayload> {
    const params = new URLSearchParams({
      conversation_id: input.conversationId,
      turn_id: input.turnId,
      path: input.path,
    });
    appendAgentParam(params, input.agentId);
    const data = await this.requestJson<RawNativeAgentHistoryDiffPayload>(
      `/api/bots/${encodeURIComponent(botAlias)}/native-agent/history/diff?${params.toString()}`,
    );
    return mapNativeAgentHistoryDiff(data);
  }

  async rollbackNativeAgentHistory(
    botAlias: string,
    input: { conversationId: string; targetTurnId: string; agentId?: string },
  ): Promise<NativeAgentHistoryRollbackResult> {
    const normalizedAgentId = String(input.agentId || "").trim();
    const data = await this.requestJson<RawNativeAgentHistoryRollbackResult>(
      `/api/bots/${encodeURIComponent(botAlias)}/native-agent/history/rollback`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          conversation_id: input.conversationId,
          target_turn_id: input.targetTurnId,
          ...(normalizedAgentId && normalizedAgentId !== "main" ? { agent_id: normalizedAgentId } : {}),
        }),
      },
    );
    return mapNativeAgentHistoryRollback(data);
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

