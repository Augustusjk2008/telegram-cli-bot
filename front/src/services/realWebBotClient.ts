import type {
  AppUpdateDownloadProgress,
  AppUpdateStatus,
  AssistantCronJob,
  AssistantCronRun,
  AssistantCronRunRequestResult,
  CreateAssistantCronJobInput,
  GitActionResult,
  GitCommitSummary,
  GitDiffPayload,
  GitProxySettings,
  GitOverview,
  BotOverview,
  BotStatus,
  BotSummary,
  ChatMessage,
  ChatTraceDetails,
  ChatMessageMetaInfo,
  ChatStatusUpdate,
  ChatTraceEvent,
  CliParamsPayload,
  CliType,
  CreateBotInput,
  DirectoryListing,
  AvatarAsset,
  FileEntry,
  FileReadMode,
  FileReadResult,
  PublicHostInfo,
  RunningReply,
  SessionState,
  SystemScript,
  SystemScriptResult,
  TunnelSnapshot,
  UpdateAssistantCronJobInput,
} from "./types";
import type { WebBotClient } from "./webBotClient";

type JsonEnvelope<T> = {
  ok: boolean;
  data: T;
  error?: {
    code?: string;
    message?: string;
  };
};

type RawBotSummary = {
  alias: string;
  cli_type: CliType;
  cli_path?: string;
  status: string;
  is_processing?: boolean;
  working_dir: string;
  avatar_name?: string;
  bot_mode?: string;
  enabled?: boolean;
  is_main?: boolean;
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
  elapsed_seconds?: number;
  meta?: RawChatMessageMeta;
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
};

type RawSystemScript = {
  script_name: string;
  display_name: string;
  description: string;
  path: string;
};

type RawRunningReply = {
  user_text?: string;
  preview_text?: string;
  started_at: string;
  updated_at?: string;
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

type RawGitDiffPayload = {
  path: string;
  staged: boolean;
  diff: string;
};

type RawGitActionResult = {
  message: string;
  overview: RawGitOverview;
};

type RawGitProxySettings = {
  port?: string;
};

type RawAppUpdateStatus = {
  current_version: string;
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
  update_last_error?: string;
};

type RawAppUpdateDownloadProgress = {
  phase?: string;
  downloaded_bytes?: number;
  total_bytes?: number;
  percent?: number;
  message?: string;
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

type StreamEvent =
  | { type: "meta"; [key: string]: unknown }
  | { type: "delta"; text?: string }
  | RawAppUpdateDownloadProgress & { type: "progress" }
  | { type: "status"; elapsed_seconds?: number; preview_text?: string }
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
  const status = mapStatus(raw.status, isProcessing);
  const summary: BotSummary = {
    alias: raw.alias,
    cliType: raw.cli_type,
    status,
    workingDir: raw.working_dir,
    lastActiveText: mapStatusText(status),
    avatarName: raw.avatar_name || "bot-default.png",
  };
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

function mapFileEntry(raw: RawFileEntry): FileEntry {
  return {
    name: raw.name,
    isDir: raw.is_dir,
    ...(typeof raw.size === "number" ? { size: raw.size } : {}),
    ...(raw.updated_at ? { updatedAt: raw.updated_at } : {}),
  };
}

function mapSystemScript(raw: RawSystemScript): SystemScript {
  return {
    scriptName: raw.script_name,
    displayName: raw.display_name,
    description: raw.description,
    path: raw.path,
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
    traceCount: incoming?.traceCount ?? base?.traceCount ?? traceSummary?.traceCount,
    toolCallCount: incoming?.toolCallCount ?? base?.toolCallCount ?? traceSummary?.toolCallCount,
    processCount: incoming?.processCount ?? base?.processCount ?? traceSummary?.processCount,
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
    state: fallbackState,
    ...(typeof raw.elapsed_seconds === "number" ? { elapsedSeconds: raw.elapsed_seconds } : {}),
    ...(mapMessageMeta(raw.meta) ? { meta: mapMessageMeta(raw.meta) } : {}),
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

function mapGitProxySettings(raw: RawGitProxySettings): GitProxySettings {
  return {
    port: raw.port || "",
  };
}

function mapAppUpdateStatus(raw: RawAppUpdateStatus): AppUpdateStatus {
  return {
    currentVersion: raw.current_version || "",
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
      throw new Error(payload.error?.message || "请求失败");
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

  async login(token: string): Promise<SessionState> {
    this.token = token.trim();
    const data = await this.requestJson<{ user_id: number }>("/api/auth/me");
    return {
      currentBotAlias: "",
      currentPath: "",
      isLoggedIn: Boolean(data.user_id),
      canExec: true,
      canAdmin: true,
    };
  }

  async listBots(): Promise<BotSummary[]> {
    const data = await this.requestJson<RawBotSummary[]>("/api/bots");
    return data.map((item) => mapBotSummary(item, Boolean(item.is_processing)));
  }

  async getBotOverview(botAlias: string): Promise<BotOverview> {
    const data = await this.requestJson<{
      bot: RawBotSummary;
      session: {
        working_dir: string;
        message_count: number;
        history_count: number;
        is_processing: boolean;
        running_reply?: RawRunningReply | null;
      };
    }>(`/api/bots/${encodeURIComponent(botAlias)}`);

    const summary = mapBotSummary(data.bot, data.session.is_processing);
    const overview: BotOverview = {
      ...summary,
      workingDir: data.session.working_dir || summary.workingDir,
      messageCount: data.session.message_count,
      historyCount: data.session.history_count,
      isProcessing: data.session.is_processing,
      runningReply: mapRunningReply(data.session.running_reply),
    };
    if (data.bot.bot_mode) {
      overview.botMode = data.bot.bot_mode;
    }
    return overview;
  }

  async listMessages(botAlias: string): Promise<ChatMessage[]> {
    const data = await this.requestJson<{ items: RawHistoryItem[] }>(`/api/bots/${encodeURIComponent(botAlias)}/history`);
    return data.items.map((item, index) => mapChatMessage(item, index));
  }

  async getMessageTrace(botAlias: string, messageId: string): Promise<ChatTraceDetails> {
    const data = await this.requestJson<RawChatTraceDetails>(
      `/api/bots/${encodeURIComponent(botAlias)}/history/${encodeURIComponent(messageId)}/trace`,
    );
    return mapChatTraceDetails(data);
  }

  async sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
    onTrace?: (trace: ChatTraceEvent) => void,
  ): Promise<ChatMessage> {
    const response = await fetch(`/api/bots/${encodeURIComponent(botAlias)}/chat/stream`, {
      method: "POST",
      headers: this.headers({
        "Content-Type": "application/json",
      }),
      body: JSON.stringify({ message: text }),
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

        if (event.type === "delta" && event.text) {
          streamedText += event.text;
          onChunk(event.text);
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

  async getCurrentPath(botAlias: string): Promise<string> {
    const data = await this.requestJson<{ working_dir: string }>(`/api/bots/${encodeURIComponent(botAlias)}/pwd`);
    return data.working_dir;
  }

  async listFiles(botAlias: string): Promise<DirectoryListing> {
    const data = await this.requestJson<{ working_dir: string; entries: RawFileEntry[]; is_virtual_root?: boolean }>(`/api/bots/${encodeURIComponent(botAlias)}/ls`);
    return {
      workingDir: data.working_dir,
      entries: data.entries.map(mapFileEntry),
      ...(data.is_virtual_root ? { isVirtualRoot: true } : {}),
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

  async createDirectory(botAlias: string, name: string): Promise<void> {
    await this.requestJson(`/api/bots/${encodeURIComponent(botAlias)}/files/mkdir`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name }),
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

  async readFile(botAlias: string, filename: string): Promise<FileReadResult> {
    const params = new URLSearchParams({
      filename,
      mode: "head",
      lines: "80",
    });
    const data = await this.requestJson<RawFileReadResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/read?${params.toString()}`);
    return {
      content: data.content || "",
      mode: data.mode || "head",
      workingDir: data.working_dir || "",
      fileSizeBytes: data.file_size_bytes,
      isFullContent: data.is_full_content,
    };
  }

  async readFileFull(botAlias: string, filename: string): Promise<FileReadResult> {
    const params = new URLSearchParams({
      filename,
      mode: "cat",
      lines: "0",
    });
    const data = await this.requestJson<RawFileReadResult>(`/api/bots/${encodeURIComponent(botAlias)}/files/read?${params.toString()}`);
    return {
      content: data.content || "",
      mode: data.mode || "cat",
      workingDir: data.working_dir || "",
      fileSizeBytes: data.file_size_bytes,
      isFullContent: data.is_full_content ?? true,
    };
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

  async updateGitProxySettings(port: string): Promise<GitProxySettings> {
    const data = await this.requestJson<RawGitProxySettings>("/api/admin/git-proxy", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ port }),
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

  async updateBotWorkdir(botAlias: string, workingDir: string): Promise<BotSummary> {
    const data = await this.requestJson<{ bot: RawBotSummary }>(`/api/admin/bots/${encodeURIComponent(botAlias)}/workdir`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ working_dir: workingDir }),
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
    const data = await this.requestJson<{ run_id: string; status: string }>(
      `/api/admin/bots/${encodeURIComponent(botAlias)}/assistant/cron/jobs/${encodeURIComponent(jobId)}/run`,
      {
        method: "POST",
      },
    );
    return {
      runId: data.run_id,
      status: data.status,
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

  async listSystemScripts(): Promise<SystemScript[]> {
    const data = await this.requestJson<{ items: RawSystemScript[] }>("/api/admin/scripts");
    return data.items.map(mapSystemScript);
  }

  async runSystemScript(scriptName: string): Promise<SystemScriptResult> {
    const data = await this.requestJson<{ script_name: string; success: boolean; output: string }>("/api/admin/scripts/run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ script_name: scriptName }),
    });
    return {
      scriptName: data.script_name,
      success: data.success,
      output: data.output,
    };
  }

  async runSystemScriptStream(scriptName: string, onLog: (line: string) => void): Promise<SystemScriptResult> {
    const response = await fetch("/api/admin/scripts/run/stream", {
      method: "POST",
      headers: this.headers({
        "Content-Type": "application/json",
      }),
      body: JSON.stringify({ script_name: scriptName }),
    });

    if (!response.ok || !response.body) {
      let message = "执行脚本失败";
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
    let finalResult: SystemScriptResult | null = null;

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

        if (event.type === "log" && event.text) {
          onLog(event.text);
        } else if (event.type === "done") {
          finalResult = {
            scriptName: event.script_name || scriptName,
            success: Boolean(event.success),
            output: event.output || "",
          };
        } else if (event.type === "error") {
          throw new Error(event.message || "脚本执行失败");
        }

        separatorIndex = buffer.indexOf("\n\n");
      }
    }

    if (!finalResult) {
      throw new Error("脚本执行已中断");
    }

    return finalResult;
  }
}
