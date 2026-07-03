export type CliType = "claude" | "codex";
export type ChatExecutionMode = "cli" | "native_agent";
export type BotStatus = "running" | "busy" | "unread" | "offline";
export type BotServiceStatus = "online" | "offline";
export type BotActivityStatus = "idle" | "busy";
export type AccountRole = "member" | "guest";
export type Capability =
  | "view_bots"
  | "view_bot_status"
  | "view_file_tree"
  | "mutate_browse_state"
  | "view_chat_history"
  | "view_chat_trace"
  | "read_file_content"
  | "write_files"
  | "chat_send"
  | "terminal_exec"
  | "debug_exec"
  | "git_ops"
  | "manage_cli_params"
  | "manage_bots"
  | "create_workdir_directory"
  | "view_plugins"
  | "run_plugins"
  | "run_unsafe_cli"
  | "manage_register_codes"
  | "admin_ops";

export type RegisterCodeUsage = {
  usedAt: string;
  usedBy: string;
};

export type RegisterCodeItem = {
  codeId: string;
  codePreview: string;
  disabled: boolean;
  maxUses: number;
  usedCount: number;
  remainingUses: number;
  createdAt: string;
  createdBy: string;
  lastUsedAt: string;
  usage: RegisterCodeUsage[];
};

export type RegisterCodeCreateResult = RegisterCodeItem & {
  code: string;
};

export type AnnouncementSeverity = "info" | "success" | "warning" | "danger";
export type AnnouncementCategory = "release" | "feature" | "fix" | "maintenance" | "notice";

export type AnnouncementSection = {
  label: string;
  items: string[];
};

export type AnnouncementItem = {
  id: string;
  publishedAt: string;
  publisher: string;
  title: string;
  category: AnnouncementCategory;
  severity: AnnouncementSeverity;
  summary: string;
  sections: AnnouncementSection[];
};

export type CreateAnnouncementInput = Omit<AnnouncementItem, "id" | "publishedAt">;

export type AnnouncementListResult = {
  items: AnnouncementItem[];
  latestId: string;
  lastSeenId: string;
  hasUnseen: boolean;
};

export type AdminUser = {
  accountId: string;
  username: string;
  role: AccountRole | "member";
  disabled: boolean;
  capabilities: Capability[];
  createdAt: string;
  allowedBots: string[];
  ownedBots: string[];
  ownedBotCount: number;
  botCreateLimit: number;
};

export type AdminUserUpdateInput = {
  disabled?: boolean;
  capabilities?: Capability[];
};

export type UserBotPermissions = {
  accountId: string;
  allowedBots: string[];
};

export type TransferTrafficRecord = {
  id: string;
  timestamp: string;
  method: string;
  endpoint: string;
  status: number;
  bytesIn: number;
  bytesOut: number;
  durationMs: number;
  model: string;
  error: string;
};

export type TransferBridgeStatus = {
  enabled: boolean;
  running: boolean;
  status: "running" | "stopped" | "not_configured" | "error" | "unknown";
  localUrl: string;
  localEndpoint?: string;
  localHost?: string;
  localPort?: number;
  bridgePageUrl: string;
  responsesBaseUrl: string;
  chatCompletionsBaseUrl: string;
  remoteBaseUrl?: string;
  remoteModel?: string;
  remoteApiKeySet: boolean;
  requestCount: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalBytesIn: number;
  totalBytesOut: number;
  uptimeSeconds?: number;
  recentTraffic?: TransferTrafficRecord[];
  startedAt?: string;
  lastRequestAt?: string;
  lastError?: string;
  requestStreamUsage?: boolean;
  retryWithoutStreamOptions?: boolean;
  reasoningMode?: string;
  downgradeDeveloperToSystem?: boolean;
  useLegacyMaxTokens?: boolean;
  restartRequired?: boolean;
  restartRequiredReason?: string;
};

export type TransferBridgeConfigInput = {
  remoteBaseUrl?: string;
  remoteModel?: string;
  remoteApiKey?: string;
  clearRemoteApiKey?: boolean;
  requestStreamUsage?: boolean;
  retryWithoutStreamOptions?: boolean;
  reasoningMode?: string;
  downgradeDeveloperToSystem?: boolean;
  useLegacyMaxTokens?: boolean;
};

export type EnvConfigFieldType = "string" | "number" | "boolean" | "select" | "csv" | "path" | "password";

export type EnvConfigValue = string | number | boolean | string[];

export type EnvConfigOption = {
  value: string;
  label: string;
};

export type EnvConfigItem = {
  key: string;
  label: string;
  description: string;
  type: EnvConfigFieldType;
  category: string;
  value: EnvConfigValue;
  defaultValue: EnvConfigValue;
  source: string;
  sensitive: boolean;
  masked: boolean;
  restartRequired: boolean;
  rebuildRequired: boolean;
  processOverridden?: boolean;
  options?: EnvConfigOption[];
  validation?: Record<string, unknown>;
};

export type EnvConfigSnapshot = {
  envPath: string;
  examplePath: string;
  items: EnvConfigItem[];
};

export type EnvConfigPatchValue =
  | EnvConfigValue
  | ""
  | null
  | {
      value?: EnvConfigValue | "";
      masked?: boolean;
      action?: "clear" | "regenerate";
    };

export type EnvConfigPatchInput = {
  values: Record<string, EnvConfigPatchValue>;
};

export type EnvConfigPatchResult = {
  changedKeys: string[];
  restartRequiredKeys: string[];
  rebuildRequiredKeys: string[];
  backupPath: string;
};

export type CliErrorStatsItem = {
  botAlias: string;
  cliType: CliType | string;
  workingDir: string;
  conversationId: string;
  turnId: string;
  startedAt: string;
  completedAt: string;
  errorCode: string;
  errorMessage: string;
  category: string;
  durationMs: number | null;
};

export type CliErrorTopItem = {
  message: string;
  count: number;
  category: string;
  latestAt: string;
};

export type CliErrorStatsSummary = {
  total: number;
  byCliType: Record<string, number>;
  byBot: Record<string, number>;
  byCategory: Record<string, number>;
  latestAt: string;
};

export type CliErrorStatsResult = {
  summary: CliErrorStatsSummary;
  topErrors: CliErrorTopItem[];
  items: CliErrorStatsItem[];
};

export type CliErrorStatsFilters = {
  hours?: number;
  alias?: string;
  cliType?: string;
  category?: string;
  limit?: number;
};

export type NativeAgentConfigView = {
  provider: string;
  model: string;
  piAgent: string;
  baseUrl?: string;
  hasApiKey?: boolean;
  apiKeyMasked?: string;
  reasoningEffort?: string;
  thinkingDepth?: string;
};

export type NativeAgentConfigInput = {
  provider: string;
  model: string;
  piAgent: string;
  baseUrl?: string;
  apiKey?: string;
  clearApiKey?: boolean;
  reasoningEffort?: string;
  thinkingDepth?: string;
};

export type NativeAgentModelOption = {
  id: string;
  provider: string;
  model: string;
  name: string;
  label: string;
  contextWindow?: number;
  outputLimit?: number;
  reasoningEfforts?: string[];
  defaultReasoningEffort?: string;
};

export type NativeAgentPreflightCheck = {
  key: string;
  ok: boolean;
  severity: "info" | "warning" | "error" | string;
  message: string;
  fix?: string;
  path?: string;
  command?: string;
  version?: string;
};

export type NativeAgentPreflightResult = {
  ok: boolean;
  code: string;
  message: string;
  platform: string;
  checks: NativeAgentPreflightCheck[];
};

export type NativeAgentConfigPayload = {
  config: Record<string, unknown>;
  backend: string;
  configPath: string;
  modelsPath?: string;
  workspaceHistoryEnabled: boolean;
  models: NativeAgentModelOption[];
  selectedModel: string;
  selectedReasoningEffort?: string;
  needsRestart?: boolean;
  preflight?: NativeAgentPreflightResult;
};

export type NativeAgentModelsPayload = {
  items: NativeAgentModelOption[];
  selectedModel: string;
  selectedReasoningEffort?: string;
};

export type NativeAgentModelUpdateResult = NativeAgentModelsPayload & {
  bot?: BotSummary;
};

export type NativeAgentModelUpdateOptions = {
  reasoningEffort?: string;
};

export type NativeAgentDraft = NativeAgentConfigView & {
  baseUrl: string;
  hasApiKey: boolean;
  apiKeyMasked: string;
  apiKey: string;
  clearApiKey: boolean;
};

export type NativeAgentConfig = NativeAgentConfigView;

export type BotExecutionConfigInput = {
  supportedExecutionModes: ChatExecutionMode[];
  defaultExecutionMode: ChatExecutionMode;
  nativeAgent: NativeAgentConfigInput;
};

export type BotSummary = {
  alias: string;
  cliType: CliType;
  status: BotStatus;
  workingDir: string;
  lastActiveText: string;
  serviceStatus?: BotServiceStatus;
  activityStatus?: BotActivityStatus;
  busyAgentIds?: string[];
  busyAgentNames?: string[];
  busyAgentCount?: number;
  agents?: AgentSummary[];
  cliPath?: string;
  enabled?: boolean;
  isMain?: boolean;
  canOperate?: boolean;
  effectiveCapabilities?: Capability[];
  ownerAccountId?: string;
  ownerUsername?: string;
  isOwnedByCurrentUser?: boolean;
  cluster?: BotClusterConfig;
  promptPresets?: PromptPreset[];
  globalPromptPresets?: PromptPreset[];
  supportedExecutionModes?: ChatExecutionMode[];
  defaultExecutionMode?: ChatExecutionMode;
  executionMode?: ChatExecutionMode;
  nativeAgent?: NativeAgentConfigView;
};

export type PromptPreset = {
  id: string;
  title: string;
  content: string;
};

export type AgentSummary = {
  id: string;
  name: string;
  systemPrompt: string;
  enabled: boolean;
  isMain: boolean;
  isProcessing?: boolean;
  messageCount?: number;
  activeConversationId?: string;
  createdAt?: string;
  updatedAt?: string;
  cluster?: AgentClusterConfig;
};

export type AgentListResult = {
  items: AgentSummary[];
};

export type AgentInput = {
  id?: string;
  name?: string;
  systemPrompt?: string;
  enabled?: boolean;
  cluster?: Partial<AgentClusterConfig>;
};

export type ClusterModelTier = "low" | "medium" | "high";

export type ClusterModelTiers = {
  low: string;
  medium: string;
  high: string;
};

export type BotClusterConfig = {
  enabled: boolean;
  writePolicy: "main_only" | "selected_agents" | "all_agents";
  conflictPolicy: "warn_only" | "snapshot_diff" | "block_same_file";
  maxParallelAgents: number;
  defaultTimeoutSeconds: number;
  modelTiers: ClusterModelTiers;
};

export type AgentClusterConfig = {
  allowCluster: boolean;
  allowWrite: boolean;
  sessionPolicy: "persistent" | "ephemeral" | "fork";
  timeoutSeconds: number;
};

export type ClusterMcpState =
  | "not_checked"
  | "cli_missing"
  | "launcher_missing"
  | "mcp_missing"
  | "runtime_ready"
  | "installed"
  | "stale"
  | "broken"
  | "app_not_running";

export type ClusterMcpTargetStatus = {
  state: ClusterMcpState;
  message: string;
};

export type ClusterAgentStatus = {
  id: string;
  name: string;
  enabled: boolean;
  allowCluster: boolean;
  allowWrite: boolean;
  sessionPolicy: AgentClusterConfig["sessionPolicy"];
  timeoutSeconds: number;
};

export type ClusterStatus = {
  enabled: boolean;
  modelTiers: ClusterModelTiers;
  mcp: {
    serverName: string;
    activeCliType: CliType | string;
    runtime?: ClusterMcpTargetStatus;
    codex: ClusterMcpTargetStatus;
    claude: ClusterMcpTargetStatus;
    pi?: ClusterMcpTargetStatus;
  };
  agents: ClusterAgentStatus[];
};

export type ClusterAgentTask = {
  taskId: string;
  agentId: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | string;
  modelTier: ClusterModelTier | string;
  allowWrite: boolean;
  createdAt: string;
  startedAt: string;
  completedAt: string;
  message?: string;
  timeoutSeconds?: number;
  deadlineExceeded?: boolean;
  messageCount?: number;
  latestMessageSequence?: number;
  messages?: ClusterTaskMessage[];
  output?: string;
  error: string;
};

export type ClusterTaskStatus = {
  tasks: ClusterAgentTask[];
  queuedCount: number;
  runningCount: number;
  completedCount: number;
  failedCount: number;
  pendingCount: number;
};

export type ActiveClusterRun = {
  runId: string;
  status: string;
  tasks?: ClusterTaskStatus;
};

export type ClusterTaskMessage = {
  sequence: number;
  taskId: string;
  agentId: string;
  kind: "progress" | "final" | string;
  content: string;
  createdAt: string;
};

export type ClusterSetupPrepareResult = {
  serverName: string;
  launcherPath: string;
  configPath: string;
  tokenPath: string;
  installCommand: string[];
  verifyCommand: string[];
  removeCommand: string[];
  piSettingsPath?: string;
  piSettingsSnippet?: string;
  piExtensionPath?: string;
  piExtensionName?: string;
  selfTestCommand?: string[];
};

export type ClusterConfigUpdateInput = {
  enabled?: boolean;
  writePolicy?: BotClusterConfig["writePolicy"];
  conflictPolicy?: BotClusterConfig["conflictPolicy"];
  maxParallelAgents?: number;
  defaultTimeoutSeconds?: number;
  modelTiers?: ClusterModelTiers;
};

export type ClusterConfigUpdateResult = {
  cluster: BotClusterConfig;
  status: ClusterStatus;
};

export type ClusterTemplateSummary = {
  id: string;
  name: string;
  description: string;
  agentCount: number;
  writeAgentCount: number;
  maxParallelAgents: number;
};

export type ClusterConfigBundleAgent = {
  id: string;
  name: string;
  systemPrompt: string;
  enabled: boolean;
  cluster: AgentClusterConfig;
};

export type ClusterConfigBundle = {
  id: string;
  name: string;
  description: string;
  cluster: BotClusterConfig;
  agents: ClusterConfigBundleAgent[];
};

export type ClusterBundleDiff = {
  deleteAgents: string[];
  createAgents: string[];
  updateAgents: string[];
  clusterChanges: Record<string, { before: unknown; after: unknown }>;
  overwritesAgents: boolean;
};

export type ClusterTemplateListResult = {
  templates: ClusterTemplateSummary[];
};

export type ClusterBundlePreviewResult = {
  bundle: ClusterConfigBundle;
  diff: ClusterBundleDiff;
};

export type ClusterBundleApplyResult = {
  cluster: BotClusterConfig;
  agents: AgentSummary[];
  bundle: ClusterConfigBundle;
  diff: ClusterBundleDiff;
  status: ClusterStatus;
};

export type ClusterBundleSchemaResult = {
  version: number;
  schema: Record<string, unknown>;
  instructions: string;
};

export type AgentMention = {
  agentId: string;
  label: string;
  start: number;
  end: number;
};

export type AgentMutationResult = {
  agent: AgentSummary;
};

export type AgentScopedOptions = {
  agentId?: string;
  executionMode?: ChatExecutionMode;
};

export type WorkdirChangeConflict = {
  currentWorkingDir: string;
  requestedWorkingDir: string;
  historyCount: number;
  messageCount: number;
};

export type UpdateBotWorkdirOptions = {
  forceReset?: boolean;
};

export type RemoveBotOptions = {
  deleteHistory?: boolean;
  deleteWorkspace?: boolean;
};

export type RemoveBotResult = {
  removed: boolean;
  alias: string;
  historyDeleted: boolean;
  historyDeletedCount: number;
  favoriteDeletedCount: number;
  workspacePath: string;
  workspaceDeleted: boolean;
  workspaceMissing: boolean;
  errors: Array<{ code?: string; message: string }>;
};

export class WebApiClientError extends Error {
  status?: number;
  code?: string;
  data?: unknown;

  constructor(message: string, init: { status?: number; code?: string; data?: unknown } = {}) {
    super(message);
    this.name = "WebApiClientError";
    this.status = init.status;
    this.code = init.code;
    this.data = init.data;
    Object.setPrototypeOf(this, WebApiClientError.prototype);
  }
}

export type RunningReply = {
  userText?: string;
  previewText?: string;
  startedAt: string;
  updatedAt?: string;
};

export type BotOverview = {
  alias: string;
  cliType: CliType;
  status: BotStatus;
  workingDir: string;
  cliPath?: string;
  enabled?: boolean;
  isMain?: boolean;
  messageCount?: number;
  historyCount?: number;
  isProcessing?: boolean;
  runningReply?: RunningReply | null;
  agents?: AgentSummary[];
  cluster?: BotClusterConfig;
  activeClusterRun?: ActiveClusterRun | null;
  activeAgentId?: string;
  busyAgentIds?: string[];
  busyAgentNames?: string[];
  busyAgentCount?: number;
  canOperate?: boolean;
  effectiveCapabilities?: Capability[];
  promptPresets?: PromptPreset[];
  globalPromptPresets?: PromptPreset[];
  supportedExecutionModes?: ChatExecutionMode[];
  defaultExecutionMode?: ChatExecutionMode;
  executionMode?: ChatExecutionMode;
  nativeAgent?: NativeAgentConfigView;
};

export type ChatTraceEvent = {
  id?: string;
  ordinal?: number;
  sequence?: number;
  createdAt?: string;
  kind: string;
  summary: string;
  source?: string;
  rawType?: string;
  title?: string;
  toolName?: string;
  callId?: string;
  payload?: unknown;
};

export type ChatMessageNativeSource = {
  provider?: string;
  sessionId?: string;
};

export type ChatMessageContextUsage = {
  provider?: string;
  source?: string;
  sessionId?: string;
  usedTokens?: number;
  contextWindow?: number;
  contextLeftPercent?: number;
  usedDisplay?: string;
  windowDisplay?: string;
  statusText?: string;
  compactionCount?: number;
  contextUsed?: number;
  contextUsedPercent?: number;
  inputTokens?: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  outputTokens?: number;
  reasoningTokens?: number;
  model?: string;
};

export type ChatMessageMetaInfo = {
  completionState?: string;
  summaryKind?: string;
  traceVersion?: number;
  traceCount?: number;
  toolCallCount?: number;
  processCount?: number;
  trace?: ChatTraceEvent[];
  nativeSource?: ChatMessageNativeSource;
  contextUsage?: ChatMessageContextUsage;
  agUiRunState?: unknown;
  tracePresentation?: "native_agent_flat" | "generic";
  workspaceHistoryHead?: string;
  linearIndex?: number;
  rollbackSupported?: boolean;
  degraded?: boolean;
  degradedReason?: string;
};

export type ChatMessageAuthor = {
  userId?: number;
  accountId?: string;
  username?: string;
  isCurrentUser?: boolean;
};

export type ChatTraceDetails = {
  traceCount: number;
  toolCallCount: number;
  processCount: number;
  trace: ChatTraceEvent[];
};

export type ChatMessage = {
  id: string;
  turnId?: string;
  conversationId?: string;
  role: "user" | "assistant" | "system";
  text: string;
  createdAt: string;
  updatedAt?: string;
  elapsedSeconds?: number;
  state?: "done" | "streaming" | "error";
  meta?: ChatMessageMetaInfo;
  author?: ChatMessageAuthor;
};

export type HistoryDeltaResult = {
  items: ChatMessage[];
  reset: boolean;
};

export type NativeAgentHistoryFileStatus = "added" | "modified" | "deleted" | "renamed" | "copied" | "unknown";

export type NativeAgentHistoryChangedFile = {
  path: string;
  oldPath: string;
  status: NativeAgentHistoryFileStatus | string;
  additions: number;
  deletions: number;
  binary: boolean;
};

export type NativeAgentHistoryChangesPayload = {
  conversationId: string;
  turnId: string;
  linearIndex: number;
  baseHead: string;
  head: string;
  files: NativeAgentHistoryChangedFile[];
  discarded?: boolean;
  message?: string;
};

export type NativeAgentHistoryDiffPayload = {
  conversationId: string;
  turnId: string;
  path: string;
  oldPath: string;
  status: NativeAgentHistoryFileStatus | string;
  diff: string;
  truncated?: boolean;
  binary?: boolean;
};

export type NativeAgentHistoryRollbackResult = {
  conversationId: string;
  currentTurnId: string;
  rollbackSupported: boolean;
  message: string;
};

export type ConversationSummary = {
  id: string;
  title: string;
  lastMessagePreview: string;
  messageCount: number;
  pinned: boolean;
  active: boolean;
  status: string;
  botAlias: string;
  cliType: string;
  agentId?: string;
  workingDir: string;
  nativeSource?: ChatMessageNativeSource;
  workspaceHistoryHead?: string;
  linearIndex?: number;
  rollbackSupported?: boolean;
  degraded?: boolean;
  degradedReason?: string;
  createdAt: string;
  updatedAt: string;
};

export type ConversationListResult = {
  items: ConversationSummary[];
  activeConversationId: string;
};

export type ConversationSelectResult = {
  conversation: ConversationSummary;
  messages: ChatMessage[];
};

export type ConversationDeleteResult = {
  deletedConversationId: string;
  deletedFavoriteCount?: number;
  activeConversationId: string;
  nativeSessionCleared: boolean;
  items: ConversationSummary[];
  messages?: ChatMessage[];
};

export type ConversationBulkDeleteResult = {
  deletedCount: number;
  deletedFavoriteCount?: number;
  activeConversationId: string;
  nativeSessionCleared: boolean;
  items: ConversationSummary[];
  messages: ChatMessage[];
};

export type FavoriteAnswerItem = {
  id: string;
  botId: number;
  botAlias: string;
  userId: number;
  agentId: string;
  executionMode: ChatExecutionMode;
  conversationId: string;
  messageId: string;
  messageKey: string;
  turnId: string;
  title: string;
  preview: string;
  answerText: string;
  createdAt: string;
  favoritedAt: string;
};

export type FavoriteAnswerListResult = {
  items: FavoriteAnswerItem[];
  executionMode: ChatExecutionMode;
};

export type FavoriteAnswerInput = {
  conversationId: string;
  messageId: string;
  messageKey: string;
  turnId?: string;
  title?: string;
  preview?: string;
  answerText?: string;
};

export type ChatStatusUpdate = {
  elapsedSeconds?: number;
  previewText?: string;
  replaceText?: string;
  clusterRunId?: string;
  turnId?: string;
  assistantMessageId?: string;
  contextUsage?: ChatMessageContextUsage;
};

export type ChatTaskMode = "standard" | "plan";

export type PlanExecuteInput = {
  content: string;
  title?: string;
  agentId?: string;
  executionMode?: ChatExecutionMode;
  cluster?: boolean;
  mentions?: AgentMention[];
};

export type PlanExecuteResult = {
  planPath: string;
  conversation: ConversationSummary;
  messages: ChatMessage[];
  executionMessage: string;
};

export type ChatSendOptions = {
  taskMode?: ChatTaskMode;
  taskPayload?: Record<string, unknown>;
  visibleText?: string;
  agentId?: string;
  cluster?: boolean;
  mentions?: AgentMention[];
  executionMode?: ChatExecutionMode;
  soloMode?: boolean;
};

export type NativeAgentPermissionReplyOptions = AgentScopedOptions & {
  approved: boolean;
  message?: string;
  value?: unknown;
};

export type BrowserNotificationPermission = NotificationPermission | "unsupported";

export type NotificationPresenceUpdate = {
  visible: boolean;
  focused: boolean;
  permission: BrowserNotificationPermission;
  webNotificationsEnabled: boolean;
  currentBotAlias?: string | null;
  updatedAt?: string;
};

export type ChatCompletedNotificationEvent = {
  type: "chat_completed";
  id: string;
  dedupeKey: string;
  botAlias: string;
  agentId?: string;
  conversationId?: string;
  status: "success" | "error" | string;
  title: string;
  preview: string;
  elapsedSeconds?: number;
  completedAt: string;
  url?: string;
};

export type WebNotificationEvent =
  | ChatCompletedNotificationEvent
  | {
      type: string;
      id?: string;
      dedupeKey?: string;
      [key: string]: unknown;
    };

export type NotificationSocketStatus = "connecting" | "open" | "closed" | "reconnecting" | "error";

export type NotificationSubscriptionOptions = {
  onStatus?: (status: NotificationSocketStatus) => void;
};

export type NotificationSubscription = {
  close: () => void;
  sendPresenceUpdate: (presence: NotificationPresenceUpdate) => void;
};

export type NotificationSettingsStatus = {
  pushPlusEnabled: boolean;
  pushPlusConfigured: boolean;
  pushPlusTopicConfigured?: boolean;
};

export type NotificationTestResult = {
  sent: boolean;
};

export type TerminalRuntimePlatform = "windows" | "linux" | "macos";

export type TerminalAction = {
  id: string;
  label: string;
  icon: string;
  windowsCommand: string;
  linuxCommand: string;
  macosCommand: string;
  cwd: string;
  confirm: boolean;
  enabled: boolean;
};

export type TerminalActionsEditableConfig = {
  schemaVersion: 1;
  actions: TerminalAction[];
};

export type TerminalActionsConfig = TerminalActionsEditableConfig & {
  configPath: string;
  exists: boolean;
  mtimeNs: string;
  editable: boolean;
  errors: string[];
  runtimePlatform: TerminalRuntimePlatform;
};

export type TerminalActionRunInput = {
  ownerId: string;
  confirmed?: boolean;
  cols?: number;
  rows?: number;
  shell?: string;
};

export type TerminalActionRunResult = {
  actionId: string;
  command: string;
  cwd: string;
  startedTerminal: boolean;
  snapshot: PersistentTerminalSnapshot;
};

export type FileEntry = {
  name: string;
  isDir: boolean;
  size?: number;
  updatedAt?: string;
};

export type FileDownloadProgress = {
  downloadedBytes: number;
  totalBytes?: number;
  percent?: number;
};

export type FileReadMode = "head" | "cat";
export type FilePreviewKind = "text" | "image" | "html";

export type FileReadResult = {
  content: string;
  mode: FileReadMode;
  workingDir?: string;
  fileSizeBytes?: number;
  isFullContent?: boolean;
  lastModifiedNs?: string;
  encoding?: string;
  previewKind?: FilePreviewKind;
  contentType?: string;
  contentBase64?: string;
};

export type FileWriteResult = {
  path: string;
  fileSizeBytes: number;
  lastModifiedNs: string;
  encoding?: string;
};

export type PluginViewRenderer = "waveform" | "table" | "tree" | "document" | "hex";
export type PluginViewMode = "snapshot" | "session";
export type PluginViewDataProfile = "light" | "heavy";

export type HostEffect =
  | { type: "open_file"; path: string; line?: number; column?: number }
  | { type: "reveal_in_files"; path: string }
  | { type: "copy_text"; text: string }
  | { type: "download_artifact"; artifactId: string; filename: string }
  | {
      type: "open_plugin_view";
      pluginId: string;
      viewId: string;
      title: string;
      input: Record<string, unknown>;
    };

export type PluginAction = {
  id: string;
  label: string;
  target: "plugin" | "host";
  location: "catalog" | "toolbar" | "row" | "node";
  icon?: string;
  tooltip?: string;
  variant?: "default" | "primary" | "danger";
  disabled?: boolean;
  payload?: Record<string, unknown>;
  confirm?: {
    title?: string;
    message?: string;
    confirmLabel?: string;
  };
  hostAction?: HostEffect;
};

export type PluginActionResult = {
  message?: string;
  refresh?: "none" | "view" | "session";
  hostEffects?: HostEffect[];
  closeSession?: boolean;
};

export type PluginActionInvokeInput = {
  viewId: string;
  sessionId?: string;
  actionId: string;
  payload?: Record<string, unknown>;
};

export type PluginConfigFieldOption = {
  value: string;
  label: string;
};

export type PluginConfigField =
  | {
      key: string;
      label: string;
      type: "boolean";
      default?: boolean;
      description?: string;
    }
  | {
      key: string;
      label: string;
      type: "string";
      default?: string;
      description?: string;
      placeholder?: string;
    }
  | {
      key: string;
      label: string;
      type: "integer" | "number";
      default?: number;
      description?: string;
      placeholder?: string;
      minimum?: number;
      maximum?: number;
      step?: number;
    }
  | {
      key: string;
      label: string;
      type: "select";
      default?: string;
      description?: string;
      options: PluginConfigFieldOption[];
    };

export type PluginConfigSchema = {
  title?: string;
  sections: Array<{
    id: string;
    title?: string;
    description?: string;
    fields: PluginConfigField[];
  }>;
};

export type PluginRuntimePermissions = {
  workspaceRead: boolean;
  workspaceList: boolean;
  tempArtifacts: boolean;
};

export type PluginSummary = {
  id: string;
  schemaVersion: 2;
  name: string;
  version: string;
  description: string;
  enabled?: boolean;
  config?: Record<string, unknown>;
  views: Array<{
    id: string;
    title: string;
    renderer: PluginViewRenderer;
    viewMode: PluginViewMode;
    dataProfile: PluginViewDataProfile;
  }>;
  fileHandlers: Array<{ id: string; label: string; extensions: string[]; viewId: string }>;
  configSchema?: PluginConfigSchema;
  catalogActions: PluginAction[];
  runtime: {
    type: string;
    entry: string;
    protocol: string;
    permissions: PluginRuntimePermissions;
  };
};

export type InstallablePluginSummary = {
  id: string;
  pluginId?: string;
  name: string;
  version: string;
  description: string;
  installed: boolean;
};

export type PluginUpdateInput = {
  enabled?: boolean;
  config?: Record<string, unknown>;
};

export type PluginOpenTarget = {
  pluginId: string;
  viewId: string;
  title: string;
  input: Record<string, unknown>;
};

export type FileOpenTarget =
  | { kind: "file"; pluginTargets?: PluginOpenTarget[] }
  | ({ kind: "plugin_view" } & PluginOpenTarget);

export type WaveformTrackSegment = {
  start: number;
  end: number;
  value: string;
  kind?: "dense";
  transitionCount?: number;
};

export type WaveformTrack = {
  signalId: string;
  label: string;
  width: number;
  segments: WaveformTrackSegment[];
};

export type WaveformSignalKind = "scalar" | "bus";

export type WaveformSignalSummary = {
  signalId: string;
  label: string;
  width: number;
  kind: WaveformSignalKind;
};

export type WaveformBusStyle = "cross" | "box";

export type WaveformDisplayOptions = {
  defaultZoom?: number;
  zoomLevels?: number[];
  showTimeAxis?: boolean;
  busStyle?: WaveformBusStyle;
  labelWidth?: number;
  minWaveWidth?: number;
  pixelsPerTime?: number;
  axisHeight?: number;
  trackHeight?: number;
};

export type WaveformViewPayload = {
  path: string;
  timescale: string;
  startTime: number;
  endTime: number;
  tracks: WaveformTrack[];
  display?: WaveformDisplayOptions;
};

export type WaveformViewSummary = {
  path: string;
  timescale: string;
  startTime: number;
  endTime: number;
  display?: WaveformDisplayOptions;
  signals: WaveformSignalSummary[];
  defaultSignalIds: string[];
};

export type WaveformWindowPayload = {
  startTime: number;
  endTime: number;
  tracks: WaveformTrack[];
};

export type TableColumn = {
  id: string;
  title: string;
  kind?: "text" | "number" | "badge" | "code" | "link";
  width?: number;
  align?: "left" | "center" | "right";
  sortable?: boolean;
  wrap?: boolean;
};

export type TableRow = {
  id: string;
  cells: Record<string, unknown>;
  actions?: PluginAction[];
};

export type TableSort = {
  columnId: string;
  direction: "asc" | "desc";
};

export type TableViewPayload = {
  columns: TableColumn[];
  rows: TableRow[];
  actions?: PluginAction[];
};

export type TableViewSummary = {
  columns: TableColumn[];
  totalRows: number;
  defaultPageSize: number;
  actions?: PluginAction[];
};

export type TableWindowRequest = {
  offset: number;
  limit: number;
  sort?: TableSort;
  query?: string;
  filters?: Record<string, unknown>;
};

export type TableWindowPayload = {
  offset?: number;
  limit?: number;
  totalRows: number;
  rows: TableRow[];
  appliedSort?: TableSort;
};

export type TreeNode = {
  id: string;
  label: string;
  kind?: "folder" | "file" | "class" | "function" | "method" | "heading" | "symbol";
  secondaryText?: string;
  badges?: Array<{
    text: string;
    tone?: "default" | "info" | "success" | "warning" | "danger";
  }>;
  hasChildren?: boolean;
  payload?: Record<string, unknown>;
  description?: string;
  badge?: string;
  expandable?: boolean;
  children?: TreeNode[];
  actions?: PluginAction[];
};

export type TreeViewPayload = {
  roots: TreeNode[];
  actions?: PluginAction[];
  searchable?: boolean;
  searchPlaceholder?: string;
  statsText?: string;
  emptySearchText?: string;
};

export type TreeViewSummary = {
  roots?: TreeNode[];
  actions?: PluginAction[];
  searchable?: boolean;
  searchPlaceholder?: string;
  statsText?: string;
  emptySearchText?: string;
};

export type TreeWindowRequest = {
  op?: "children" | "search";
  kind?: "children" | "search";
  nodeId?: string;
  query?: string;
};

export type TreeWindowPayload = {
  op?: "children" | "search";
  nodeId?: string;
  roots?: TreeNode[];
  nodes?: TreeNode[];
  statsText?: string;
};

export type DocumentTextRun = {
  text: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  code?: boolean;
  color?: string;
  fontSizePx?: number;
};

export type DocumentSlideFrame = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type DocumentSlideImageRef = {
  artifactId: string;
  filename: string;
  contentType: string;
  alt?: string;
  title?: string;
  widthPx?: number;
  heightPx?: number;
};

export type DocumentSlideBackground = {
  color?: string;
  image?: DocumentSlideImageRef;
};

export type DocumentSlideParagraph = {
  runs: DocumentTextRun[];
  bullet?: string;
  level?: number;
  align?: "left" | "center" | "right";
};

export type DocumentSlideItem =
  | {
      type: "text";
      frame: DocumentSlideFrame;
      paragraphs: DocumentSlideParagraph[];
      zIndex?: number;
    }
  | {
      type: "image";
      frame: DocumentSlideFrame;
      image: DocumentSlideImageRef;
      zIndex?: number;
    }
  | {
      type: "table";
      frame: DocumentSlideFrame;
      rows: Array<{
        cells: Array<{
          runs: DocumentTextRun[];
        }>;
      }>;
      zIndex?: number;
    }
  | {
      type: "unsupported";
      frame: DocumentSlideFrame;
      label: string;
      zIndex?: number;
    };

export type DocumentImageBlock = DocumentSlideImageRef & {
  type: "image";
  caption?: string;
};

export type DocumentBlock =
  | {
      type: "heading";
      level: 1 | 2 | 3 | 4 | 5 | 6;
      runs: DocumentTextRun[];
    }
  | {
      type: "paragraph";
      runs: DocumentTextRun[];
    }
  | {
      type: "list_item";
      ordered?: boolean;
      depth?: number;
      marker?: string;
      runs: DocumentTextRun[];
    }
  | {
      type: "slide";
      slideNumber: number;
      title?: string;
      widthPx: number;
      heightPx: number;
      background?: DocumentSlideBackground;
      items: DocumentSlideItem[];
    }
  | DocumentImageBlock
  | {
      type: "table";
      rows: Array<{
        cells: Array<{
          runs: DocumentTextRun[];
        }>;
      }>;
    };

export type DocumentViewPayload = {
  path: string;
  title?: string;
  statsText?: string;
  blocks: DocumentBlock[];
};

export type HexEntropyBucket = {
  index: number;
  startOffset: number;
  endOffset: number;
  entropy: number;
};

export type HexRow = {
  offset: number;
  hex: string[];
  ascii: string;
};

export type HexViewPayload = {
  path: string;
  fileSizeBytes: number;
  previewBytes: number;
  bytesPerRow: number;
  truncated?: boolean;
  statsText?: string;
  entropyBuckets: HexEntropyBucket[];
  rows: HexRow[];
};

export type PluginViewWindowRequest = Record<string, unknown>;
export type PluginViewWindowPayload = Record<string, unknown>;

export type WaveformSnapshotRenderResult = {
  pluginId: string;
  viewId: string;
  title: string;
  renderer: "waveform";
  mode: "snapshot";
  payload: WaveformViewPayload;
};

export type TableSnapshotRenderResult = {
  pluginId: string;
  viewId: string;
  title: string;
  renderer: "table";
  mode: "snapshot";
  payload: TableViewPayload;
};

export type TreeSnapshotRenderResult = {
  pluginId: string;
  viewId: string;
  title: string;
  renderer: "tree";
  mode: "snapshot";
  payload: TreeViewPayload;
};

export type DocumentSnapshotRenderResult = {
  pluginId: string;
  viewId: string;
  title: string;
  renderer: "document";
  mode: "snapshot";
  payload: DocumentViewPayload;
};

export type HexSnapshotRenderResult = {
  pluginId: string;
  viewId: string;
  title: string;
  renderer: "hex";
  mode: "snapshot";
  payload: HexViewPayload;
};

export type WaveformSessionRenderResult = {
  pluginId: string;
  viewId: string;
  title: string;
  renderer: "waveform";
  mode: "session";
  sessionId: string;
  summary: WaveformViewSummary;
  initialWindow: WaveformWindowPayload;
};

export type TableSessionRenderResult = {
  pluginId: string;
  viewId: string;
  title: string;
  renderer: "table";
  mode: "session";
  sessionId: string;
  summary: TableViewSummary;
  initialWindow: TableWindowPayload;
};

export type TreeSessionRenderResult = {
  pluginId: string;
  viewId: string;
  title: string;
  renderer: "tree";
  mode: "session";
  sessionId: string;
  summary: TreeViewSummary;
  initialWindow: TreeWindowPayload;
};

export type PluginSnapshotRenderResult =
  | WaveformSnapshotRenderResult
  | TableSnapshotRenderResult
  | TreeSnapshotRenderResult
  | DocumentSnapshotRenderResult
  | HexSnapshotRenderResult;

export type PluginSessionRenderResult =
  | WaveformSessionRenderResult
  | TableSessionRenderResult
  | TreeSessionRenderResult;

export type PluginRenderResult = PluginSnapshotRenderResult | PluginSessionRenderResult;

export type FileCreateResult = {
  path: string;
  fileSizeBytes: number;
  lastModifiedNs: string;
};

export type FileCopyResult = {
  sourcePath: string;
  path: string;
  fileSizeBytes: number;
  lastModifiedNs: string;
};

export type FileRenameResult = {
  oldPath: string;
  path: string;
};

export type FileMoveResult = {
  oldPath: string;
  path: string;
};

export type WorkspaceQuickOpenItem = {
  path: string;
  score: number;
};

export type WorkspaceQuickOpenResult = {
  items: WorkspaceQuickOpenItem[];
};

export type WorkspaceSearchMatch = {
  path: string;
  line: number;
  column: number;
  preview: string;
};

export type WorkspaceSearchResult = {
  items: WorkspaceSearchMatch[];
};

export type WorkspaceOutlineItem = {
  name: string;
  kind: "class" | "function" | "method" | "heading";
  line: number;
  level?: number;
  children?: WorkspaceOutlineItem[];
};

export type WorkspaceOutlineResult = {
  items: WorkspaceOutlineItem[];
};

export type WorkspaceDefinitionItem = {
  path: string;
  line: number;
  column?: number;
  matchKind: "import" | "same_file" | "workspace_search";
  confidence: number;
};

export type WorkspaceDefinitionResult = {
  items: WorkspaceDefinitionItem[];
};

export type ChatAttachmentUploadResult = {
  filename: string;
  savedPath: string;
  size: number;
};

export type ChatAttachmentDeleteResult = {
  filename: string;
  savedPath: string;
  existed: boolean;
  deleted: boolean;
};

export type PublicHostInfo = {
  username: string;
  operatingSystem: string;
  hardwarePlatform: string;
  hardwareSpec: string;
};

export type SessionState = {
  currentBotAlias: string;
  currentPath: string;
  isLoggedIn: boolean;
  token?: string;
  userId?: number;
  accountId?: string;
  username: string;
  role: AccountRole;
  capabilities: Capability[];
  tokenProtected?: boolean;
  allowedUserIds?: number[];
  isLocalAdmin?: boolean;
};

export type PersistentTerminalSnapshot = {
  started: boolean;
  closed: boolean;
  cwd: string;
  ptyMode: boolean | null;
  connectionText: string;
  lastSeq: number;
};

export type DebugProfile = {
  specVersion?: number;
  providerId: string;
  providerLabel: string;
  language?: string;
  configName: string;
  workspace?: string;
  target: Record<string, unknown>;
  prepare?: Record<string, unknown>;
  capabilities: DebugCapabilityMap;
  ui?: Record<string, unknown>;
  launchSchema: DebugLaunchSchema;
  launchDefaults: Record<string, unknown>;
  providerConfig?: Record<string, unknown>;
  program: string;
  cwd: string;
  miDebuggerPath: string;
  compileCommands?: string;
  prepareCommand: string;
  stopAtEntry: boolean;
  setupCommands: string[];
  remoteHost: string;
  remoteUser: string;
  remoteDir: string;
  remotePort: number;
  remote?: Record<string, unknown>;
  gdb?: Record<string, unknown>;
  sourceMaps?: Array<{ remote: string; local: string }>;
};

export type DebugPhase = "idle" | "starting" | "running" | "paused" | "stopping" | "error";

export type DebugCapabilityMap = {
  continue?: boolean;
  continueExecution?: boolean;
  pause?: boolean;
  next?: boolean;
  stepIn?: boolean;
  stepOut?: boolean;
  variables?: boolean;
  evaluate?: boolean;
  threads?: boolean;
  functionBreakpoints?: boolean;
  conditionalBreakpoints?: boolean;
  logpoints?: boolean;
  memory?: boolean;
  registers?: boolean;
  disassembly?: boolean;
};

export type DebugLaunchField = {
  key: string;
  label: string;
  type: "string" | "path" | "number" | "boolean" | "stringList" | "env" | "select";
  required?: boolean;
  secret?: boolean;
  placeholder?: string;
  options?: Array<{ value: string; label: string }>;
};

export type DebugLaunchSchema = {
  fields: DebugLaunchField[];
};

export type DebugBreakpoint = {
  source: string;
  line: number;
  verified: boolean;
  status?: "pending" | "verified" | "rejected";
  type?: "line" | "function";
  function?: string;
  condition?: string;
  hitCondition?: string;
  logMessage?: string;
  message?: string;
};

export type DebugFrame = {
  id: string;
  name: string;
  source: string;
  line: number;
  sourceResolved?: boolean;
  sourceReason?: string;
  originalSource?: string;
};

export type DebugScope = {
  name: string;
  variablesReference: string;
};

export type DebugVariable = {
  name: string;
  value: string;
  type?: string;
  variablesReference?: string;
};

export type DebugState = {
  phase: DebugPhase;
  detailPhase?: string;
  message: string;
  breakpoints: DebugBreakpoint[];
  frames: DebugFrame[];
  currentFrameId: string;
  scopes: DebugScope[];
  variables: Record<string, DebugVariable[]>;
};

export type DirectoryListing = {
  workingDir: string;
  entries: FileEntry[];
  isVirtualRoot?: boolean;
};

export type BotWorkdirOpenResult = {
  opened: boolean;
  path: string;
  platform: string;
};

export type FileTreeRevealResult = {
  rootPath: string;
  highlightPath: string;
  expandedPaths: string[];
  branches: Record<string, FileEntry[]>;
};

export type CliParamField = {
  type: "boolean" | "string" | "number" | "string_list";
  enum?: string[];
  description?: string;
  nullable?: boolean;
  integer?: boolean;
};

export type CliParamsPayload = {
  cliType: CliType;
  params: Record<string, unknown>;
  defaults: Record<string, unknown>;
  schema: Record<string, CliParamField>;
};

export type CreateBotInput = {
  alias: string;
  cliType: CliType;
  cliPath: string;
  workingDir: string;
  supportedExecutionModes?: ChatExecutionMode[];
  defaultExecutionMode?: ChatExecutionMode;
  nativeAgent?: NativeAgentConfigInput;
};

export type PublicExposureSnapshot = {
  mode: "disabled" | "cloudflare_quick" | "manual" | "fixed_public_forward";
  status: "stopped" | "waiting_local" | "waiting_url" | "connected" | "verifying_public" | "starting" | "running" | "error";
  phase?: string;
  source: "disabled" | "quick_tunnel" | "manual_config" | "fixed_public_forward";
  publicUrl: string;
  localUrl: string;
  lastError: string;
  verified?: boolean;
  lastProbeAt?: string;
  lastProbeElapsedMs?: number;
  lastProbeError?: {
    errorClass?: string;
    errorText?: string;
    statusCode?: number | null;
  };
  registeredAt?: string;
  logTail?: string[];
  pid?: number | null;
  fixedPublicForwardEnabled?: boolean;
  nodeId?: string;
  basePath?: string;
  frpcManaged?: boolean;
  frpcExternal?: boolean;
  frpcNote?: string;
  frpcStatus?: string;
  frpcPid?: number | null;
  frpcLastError?: string;
  heartbeatStatus?: string;
  heartbeatLastAt?: string;
  heartbeatLastError?: string;
};

export type TunnelSnapshot = PublicExposureSnapshot;

export type GitChangedFile = {
  path: string;
  status: string;
  staged: boolean;
  unstaged: boolean;
  untracked: boolean;
  additions: number;
  deletions: number;
  stagedAdditions: number;
  stagedDeletions: number;
  unstagedAdditions: number;
  unstagedDeletions: number;
};

export type GitCommitSummary = {
  hash: string;
  shortHash: string;
  authorName: string;
  authoredAt: string;
  subject: string;
  message?: string;
};

export type GitTreeDecorationKind = "added" | "modified" | "ignored";

export type GitTreeStatus = {
  repoFound: boolean;
  workingDir: string;
  repoPath: string;
  items: Record<string, GitTreeDecorationKind>;
};

export type GitGraphScope = "all" | "current";

export type GitCommitGraphOptions = {
  scope?: GitGraphScope;
  limit?: number;
  cursor?: string;
};

export type GitCommitGraphRefKind = "head" | "local_branch" | "remote_branch" | "tag";

export type GitCommitGraphRef = {
  name: string;
  kind: GitCommitGraphRefKind;
  current: boolean;
};

export type GitCommitGraphEdge = {
  from: number;
  to: number;
  commit?: string;
};

export type GitCommitGraphLane = {
  column: number;
  width: number;
  edges: GitCommitGraphEdge[];
};

export type GitCommitGraphNode = {
  hash: string;
  shortHash: string;
  parents: string[];
  authorName: string;
  authoredAt: string;
  subject: string;
  message?: string;
  refs: GitCommitGraphRef[];
  graph: GitCommitGraphLane;
  canReset?: boolean;
};

export type GitCommitGraphPayload = {
  repoFound: boolean;
  scope: GitGraphScope;
  nodes: GitCommitGraphNode[];
  hasMore: boolean;
  nextCursor: string;
};

export type GitOverview = {
  repoFound: boolean;
  canInit: boolean;
  workingDir: string;
  repoPath: string;
  repoName: string;
  currentBranch: string;
  isClean: boolean;
  aheadCount: number;
  behindCount: number;
  changedFiles: GitChangedFile[];
  recentCommits: GitCommitSummary[];
};

export type GitDiffPayload = {
  path: string;
  staged: boolean;
  diff: string;
  truncated?: boolean;
};

export type GitActionResult = {
  message: string;
  overview: GitOverview;
};

export type GitSmartCommitStatus = "queued" | "running" | "succeeded" | "failed" | "canceled" | string;

export type GitSmartCommitPhase = "preflight" | "generating" | "staging" | "committing" | "done" | string;

export type GitSmartCommitJob = {
  jobId: string;
  alias: string;
  userId: number;
  status: GitSmartCommitStatus;
  phase: GitSmartCommitPhase;
  message: string;
  error: string;
  overview: GitOverview | null;
};

export type GitBranchSummary = {
  name: string;
  current: boolean;
  upstream: string;
  shortHash: string;
  subject: string;
};

export type GitBranchList = {
  currentBranch: string;
  branches: GitBranchSummary[];
};

export type GitResetMode = "soft" | "mixed" | "hard";

export type GitBranchResetResult = {
  message: string;
  overview: GitOverview;
  branches: GitBranchSummary[];
  currentBranch: string;
  headCommit: string;
};

export type GitStashEntry = {
  ref: string;
  hash: string;
  createdAt: string;
  message: string;
};

export type GitStashList = {
  items: GitStashEntry[];
};

export type GitIdentityScope = "global" | "local";

export type GitIdentity = {
  name: string;
  email: string;
};

export type GitIdentityConfig = {
  repoFound: boolean;
  repoPath: string;
  global: GitIdentity;
  local: GitIdentity;
};

export type GitCommitMessageCliConfig = {
  cliType: CliType;
  cliPath: string;
  params: Record<string, unknown>;
  defaults: Record<string, unknown>;
  schema: Record<string, CliParamField>;
};

export type GitCommitMessageCliConfigUpdateInput = Partial<{
  cliType: CliType;
  cliPath: string;
  params: Record<string, unknown>;
}>;

export type GitCommitMessageGenerateResult = {
  message: string;
};

export type GitProxySettings = {
  address: string;
  port: string;
};

export type AppUpdatePackageKind = "installer" | "portable" | "linux" | "macos" | "unknown" | "";

export type AppUpdateStatus = {
  currentVersion: string;
  currentPackageKind: AppUpdatePackageKind;
  updateEnabled: boolean;
  updateChannel: "release";
  lastCheckedAt: string;
  latestVersion: string;
  latestReleaseUrl: string;
  latestNotes: string;
  pendingUpdateVersion: string;
  pendingUpdatePath: string;
  pendingUpdateNotes: string;
  pendingUpdatePlatform: string;
  pendingUpdatePackageKind: AppUpdatePackageKind;
  lastError: string;
};

export type AppUpdateDownloadProgress = {
  phase: string;
  downloadedBytes: number;
  totalBytes?: number;
  percent?: number;
  message?: string;
};

export type OfflineUpdatePackageItem = {
  name: string;
  path: string;
  version: string;
  packageKind: AppUpdatePackageKind;
  sizeBytes: number;
  valid: boolean;
  error: string;
};

export type OfflineUpdatePackageList = {
  artifactsDir: string;
  items: OfflineUpdatePackageItem[];
};

export type LanChatMode = "off" | "host" | "join";
export type LanChatConversationKind = "group" | "dm";

export type LanChatConfig = {
  mode: LanChatMode;
  roomName: string;
  instanceId: string;
  instanceName: string;
  hostUrl: string;
  roomKey?: string;
  roomKeyPreview: string;
  lanOnly: boolean;
  autoConnect: boolean;
};

export type LanChatConfigInput = Partial<{
  mode: LanChatMode;
  roomName: string;
  instanceName: string;
  hostUrl: string;
  roomKey: string;
  lanOnly: boolean;
  autoConnect: boolean;
}>;

export type LanChatParticipant = {
  roomUserId: string;
  accountId: string;
  username: string;
  displayName: string;
  instanceId: string;
  instanceName: string;
  online: boolean;
  lastSeenAt: string;
};

export type LanChatMessage = {
  id: string;
  seq: number;
  conversationId: string;
  kind: LanChatConversationKind;
  sender: LanChatParticipant;
  text: string;
  createdAt: string;
};

export type LanChatConversation = {
  id: string;
  kind: LanChatConversationKind;
  title: string;
  participantIds: string[];
  lastMessage: LanChatMessage | null;
  unreadCount: number;
  updatedAt: string;
};

export type LanChatStatus = {
  mode: LanChatMode;
  connected: boolean;
  roomName: string;
  self: LanChatParticipant;
  onlineUsers: LanChatParticipant[];
  onlineNodes: Array<{ instanceId: string; connected: boolean }>;
  lastError: string;
};

export type LanChatEvent =
  | { type: "snapshot"; status: LanChatStatus }
  | { type: "message_created"; message: LanChatMessage }
  | { type: "conversation_updated"; conversation: LanChatConversation }
  | { type: "presence_updated"; status?: LanChatStatus }
  | { type: "read_updated"; conversationId: string; lastReadSeq: number }
  | { type: "config_updated"; config: LanChatConfig };

