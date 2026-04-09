import type {
  BotOverview,
  BotStatus,
  BotSummary,
  ChatMessage,
  ChatStatusUpdate,
  CliParamsPayload,
  CliType,
  DirectoryListing,
  FileEntry,
  RunningReply,
  SessionState,
  SystemScript,
  SystemScriptResult,
  TunnelSnapshot,
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
  status: string;
  working_dir: string;
  bot_mode?: string;
};

type RawHistoryItem = {
  timestamp?: string;
  role: "user" | "assistant" | "system";
  content: string;
};

type RawFileEntry = {
  name: string;
  is_dir: boolean;
  size?: number;
  updated_at?: string;
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

type RawTunnelSnapshot = {
  mode: "disabled" | "cloudflare_quick" | "manual";
  status: "stopped" | "starting" | "running" | "error";
  source: "disabled" | "quick_tunnel" | "manual_config";
  public_url?: string;
  local_url?: string;
  last_error?: string;
  pid?: number | null;
};

type StreamEvent =
  | { type: "meta"; [key: string]: unknown }
  | { type: "delta"; text?: string }
  | { type: "status"; elapsed_seconds?: number; preview_text?: string }
  | { type: "done"; output?: string }
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
  if (status === "offline") {
    return "离线";
  }
  return "运行中";
}

function mapBotSummary(raw: RawBotSummary, isProcessing = false): BotSummary {
  const status = mapStatus(raw.status, isProcessing);
  return {
    alias: raw.alias,
    cliType: raw.cli_type,
    status,
    workingDir: raw.working_dir,
    lastActiveText: mapStatusText(status),
  };
}

function mapFileEntry(raw: RawFileEntry): FileEntry {
  return {
    name: raw.name,
    isDir: raw.is_dir,
    size: raw.size,
    updatedAt: raw.updated_at,
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
      headers: this.headers(init.headers),
    });
    const payload = (await response.json()) as JsonEnvelope<T>;
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error?.message || "请求失败");
    }
    return payload.data;
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
    return data.map((item) => mapBotSummary(item));
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
    return {
      ...summary,
      botMode: data.bot.bot_mode,
      messageCount: data.session.message_count,
      historyCount: data.session.history_count,
      isProcessing: data.session.is_processing,
      runningReply: mapRunningReply(data.session.running_reply),
    };
  }

  async listMessages(botAlias: string): Promise<ChatMessage[]> {
    const data = await this.requestJson<{ items: RawHistoryItem[] }>(`/api/bots/${encodeURIComponent(botAlias)}/history`);
    return data.items.map((item, index) => ({
      id: `${item.timestamp || "history"}-${index}`,
      role: item.role,
      text: item.content,
      createdAt: item.timestamp || new Date().toISOString(),
      state: "done",
    }));
  }

  async sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
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
          onStatus?.({
            elapsedSeconds: event.elapsed_seconds,
            previewText: event.preview_text,
          });
        } else if (event.type === "done") {
          finalText = event.output || streamedText;
        } else if (event.type === "error") {
          throw new Error(event.message || "流式响应失败");
        }

        separatorIndex = buffer.indexOf("\n\n");
      }
    }

    const messageText = finalText || streamedText;
    return {
      id: `assistant-${Date.now()}`,
      role: "assistant",
      text: messageText,
      createdAt: new Date().toISOString(),
      state: "done",
    };
  }

  async getCurrentPath(botAlias: string): Promise<string> {
    const data = await this.requestJson<{ working_dir: string }>(`/api/bots/${encodeURIComponent(botAlias)}/pwd`);
    return data.working_dir;
  }

  async listFiles(botAlias: string): Promise<DirectoryListing> {
    const data = await this.requestJson<{ working_dir: string; entries: RawFileEntry[] }>(`/api/bots/${encodeURIComponent(botAlias)}/ls`);
    return {
      workingDir: data.working_dir,
      entries: data.entries.map(mapFileEntry),
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

  async readFile(botAlias: string, filename: string): Promise<string> {
    const params = new URLSearchParams({
      filename,
      mode: "head",
      lines: "80",
    });
    const data = await this.requestJson<{ content: string }>(`/api/bots/${encodeURIComponent(botAlias)}/files/read?${params.toString()}`);
    return data.content;
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
}
