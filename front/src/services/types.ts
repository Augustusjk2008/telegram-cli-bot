export type CliType = "claude" | "codex";
export type BotStatus = "running" | "busy" | "unread" | "offline";
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
  | "run_scripts"
  | "manage_cli_params"
  | "view_plugins"
  | "run_plugins"
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

export type BotSummary = {
  alias: string;
  cliType: CliType;
  status: BotStatus;
  workingDir: string;
  lastActiveText: string;
  avatarName?: string;
  cliPath?: string;
  botMode?: string;
  enabled?: boolean;
  isMain?: boolean;
};

export type WorkdirChangeConflict = {
  currentWorkingDir: string;
  requestedWorkingDir: string;
  historyCount: number;
  messageCount: number;
  botMode: string;
};

export type UpdateBotWorkdirOptions = {
  forceReset?: boolean;
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
  avatarName?: string;
  cliPath?: string;
  botMode?: string;
  enabled?: boolean;
  isMain?: boolean;
  messageCount?: number;
  historyCount?: number;
  isProcessing?: boolean;
  runningReply?: RunningReply | null;
};

export type ChatTraceEvent = {
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

export type ChatMessageMetaInfo = {
  completionState?: string;
  summaryKind?: string;
  traceVersion?: number;
  traceCount?: number;
  toolCallCount?: number;
  processCount?: number;
  trace?: ChatTraceEvent[];
  nativeSource?: ChatMessageNativeSource;
};

export type ChatTraceDetails = {
  traceCount: number;
  toolCallCount: number;
  processCount: number;
  trace: ChatTraceEvent[];
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  createdAt: string;
  elapsedSeconds?: number;
  state?: "done" | "streaming" | "error";
  meta?: ChatMessageMetaInfo;
};

export type HistoryDeltaResult = {
  items: ChatMessage[];
  reset: boolean;
};

export type ChatStatusUpdate = {
  elapsedSeconds?: number;
  previewText?: string;
};

export type SystemScript = {
  scriptName: string;
  displayName: string;
  description: string;
  path: string;
};

export type SystemScriptResult = {
  scriptName: string;
  success: boolean;
  output: string;
};

export type FileEntry = {
  name: string;
  isDir: boolean;
  size?: number;
  updatedAt?: string;
};

export type FileReadMode = "head" | "cat";

export type FileReadResult = {
  content: string;
  mode: FileReadMode;
  workingDir?: string;
  fileSizeBytes?: number;
  isFullContent?: boolean;
  lastModifiedNs?: string;
};

export type FileWriteResult = {
  path: string;
  fileSizeBytes: number;
  lastModifiedNs: string;
};

export type PluginViewRenderer = "waveform" | "table" | "tree" | "document";
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
  workspaceRead?: boolean;
  workspaceList?: boolean;
  tempArtifacts?: boolean;
};

export type PluginSummary = {
  id: string;
  schemaVersion?: number;
  name: string;
  version: string;
  description: string;
  enabled?: boolean;
  config?: Record<string, unknown>;
  views: Array<{
    id: string;
    title: string;
    renderer: PluginViewRenderer;
    viewMode?: PluginViewMode;
    dataProfile?: PluginViewDataProfile;
  }>;
  fileHandlers: Array<{ id: string; label: string; extensions: string[]; viewId: string }>;
  configSchema?: PluginConfigSchema;
  catalogActions?: PluginAction[];
  runtime?: {
    type?: string;
    entry?: string;
    protocol?: string;
    permissions?: PluginRuntimePermissions;
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

export type FileOpenTarget =
  | { kind: "file" }
  | {
      kind: "plugin_view";
      pluginId: string;
      viewId: string;
      title: string;
      input: Record<string, unknown>;
    };

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
  | DocumentSnapshotRenderResult;

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
};

export type DebugProfile = {
  specVersion?: number;
  language?: string;
  configName: string;
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
  target?: Record<string, unknown>;
  prepare?: Record<string, unknown>;
  remote?: Record<string, unknown>;
  gdb?: Record<string, unknown>;
  sourceMaps?: Array<{ remote: string; local: string }>;
  capabilities?: Record<string, boolean>;
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
  phase: "idle" | "preparing" | "deploying" | "starting_gdb" | "connecting_remote" | "paused" | "running" | "terminating" | "error";
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
  botMode: "cli" | "assistant";
  cliType: CliType;
  cliPath: string;
  workingDir: string;
  avatarName: string;
};

export type AvatarAsset = {
  name: string;
  url: string;
};

export type TunnelSnapshot = {
  mode: "disabled" | "cloudflare_quick" | "manual";
  status: "stopped" | "starting" | "running" | "error";
  source: "disabled" | "quick_tunnel" | "manual_config";
  publicUrl: string;
  localUrl: string;
  lastError: string;
  pid?: number | null;
};

export type GitChangedFile = {
  path: string;
  status: string;
  staged: boolean;
  unstaged: boolean;
  untracked: boolean;
};

export type GitCommitSummary = {
  hash: string;
  shortHash: string;
  authorName: string;
  authoredAt: string;
  subject: string;
};

export type GitTreeDecorationKind = "added" | "modified" | "ignored";

export type GitTreeStatus = {
  repoFound: boolean;
  workingDir: string;
  repoPath: string;
  items: Record<string, GitTreeDecorationKind>;
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
};

export type GitActionResult = {
  message: string;
  overview: GitOverview;
};

export type GitProxySettings = {
  port: string;
};

export type AppUpdateStatus = {
  currentVersion: string;
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
  lastError: string;
};

export type AppUpdateDownloadProgress = {
  phase: string;
  downloadedBytes: number;
  totalBytes?: number;
  percent?: number;
  message?: string;
};

export type AssistantCronScheduleType = "daily" | "interval";
export type AssistantCronMisfirePolicy = "skip" | "once";
export type AssistantCronTaskMode = "standard" | "dream";
export type AssistantCronDeliverMode = "chat_handoff" | "silent";

export type AssistantCronSchedule = {
  type: AssistantCronScheduleType;
  time?: string;
  timezone: string;
  everySeconds?: number;
  misfirePolicy: AssistantCronMisfirePolicy;
};

export type AssistantCronTask = {
  prompt: string;
  mode?: AssistantCronTaskMode;
  lookbackHours?: number;
  historyLimit?: number;
  captureLimit?: number;
  deliverMode?: AssistantCronDeliverMode;
};

export type AssistantCronExecution = {
  timeoutSeconds: number;
};

export type AssistantCronJob = {
  id: string;
  enabled: boolean;
  title: string;
  schedule: AssistantCronSchedule;
  task: AssistantCronTask;
  execution: AssistantCronExecution;
  nextRunAt: string;
  lastStatus: string;
  lastError: string;
  lastSuccessAt: string;
  pending: boolean;
  pendingRunId: string;
  coalescedCount: number;
};

export type CreateAssistantCronJobInput = {
  id: string;
  enabled: boolean;
  title: string;
  schedule: AssistantCronSchedule;
  task: AssistantCronTask;
  execution: AssistantCronExecution;
};

export type UpdateAssistantCronJobInput = Partial<{
  enabled: boolean;
  title: string;
  schedule: Partial<AssistantCronSchedule>;
  task: Partial<AssistantCronTask>;
  execution: Partial<AssistantCronExecution>;
}>;

export type AssistantCronRun = {
  runId: string;
  jobId: string;
  triggerSource: string;
  scheduledAt: string;
  enqueuedAt: string;
  startedAt: string;
  finishedAt: string;
  status: string;
  elapsedSeconds: number;
  queueWaitSeconds: number;
  timedOut: boolean;
  promptExcerpt: string;
  outputExcerpt: string;
  error: string;
};

export type AssistantCronRunRequestResult = {
  runId: string;
  status: string;
  taskMode?: AssistantCronTaskMode;
  deliverMode?: AssistantCronDeliverMode;
};
