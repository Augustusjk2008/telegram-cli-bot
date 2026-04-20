export type CliType = "claude" | "codex";
export type BotStatus = "running" | "busy" | "unread" | "offline";

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

export type FileCreateResult = {
  path: string;
  fileSizeBytes: number;
  lastModifiedNs: string;
};

export type FileRenameResult = {
  oldPath: string;
  path: string;
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
  canExec: boolean;
  canAdmin: boolean;
};

export type DirectoryListing = {
  workingDir: string;
  entries: FileEntry[];
  isVirtualRoot?: boolean;
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

export type AssistantCronSchedule = {
  type: AssistantCronScheduleType;
  time?: string;
  timezone: string;
  everySeconds?: number;
  misfirePolicy: AssistantCronMisfirePolicy;
};

export type AssistantCronTask = {
  prompt: string;
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
};
