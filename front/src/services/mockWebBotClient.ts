import type {
  BotOverview,
  BotSummary,
  ChatMessage,
  ChatStatusUpdate,
  CliParamsPayload,
  DirectoryListing,
  SessionState,
  SystemScript,
  SystemScriptResult,
  TunnelSnapshot,
} from "./types";
import { WebBotClient } from "./webBotClient";
import { mockBots } from "../mocks/bots";
import { mockChatMessages } from "../mocks/chat";
import { mockFiles } from "../mocks/files";

export class MockWebBotClient implements WebBotClient {
  private currentPaths = new Map<string, string>();
  private readonly scripts: SystemScript[] = [
    {
      scriptName: "network_traffic",
      displayName: "网络流量",
      description: "查看网络状态",
      path: "C:\\scripts\\network_traffic.ps1",
    },
  ];

  async login(password: string): Promise<SessionState> {
    return {
      currentBotAlias: "main",
      currentPath: "/",
      isLoggedIn: true,
      canExec: true,
      canAdmin: true,
    };
  }

  async listBots(): Promise<BotSummary[]> {
    return mockBots;
  }

  async getBotOverview(botAlias: string): Promise<BotOverview> {
    const bot = mockBots.find((item) => item.alias === botAlias) || mockBots[0];
    return {
      ...bot,
      botMode: "cli",
      messageCount: mockChatMessages[bot.alias]?.length || 0,
      historyCount: mockChatMessages[bot.alias]?.length || 0,
      isProcessing: false,
    };
  }

  async listMessages(botAlias: string): Promise<ChatMessage[]> {
    return mockChatMessages[botAlias] || [];
  }

  async sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
  ): Promise<ChatMessage> {
    let streamed = "";
    await streamAssistantReply((chunk) => {
      streamed += chunk;
      onChunk(chunk);
      onStatus?.({
        elapsedSeconds: streamed.length > 0 ? 1 : 0,
      });
    });
    return {
      id: Date.now().toString(),
      role: "assistant",
      text: streamed || "Mock response",
      createdAt: new Date().toISOString(),
      state: "done"
    };
  }

  async getCurrentPath(botAlias: string): Promise<string> {
    return this.currentPaths.get(botAlias) || "/";
  }

  async listFiles(botAlias: string): Promise<DirectoryListing> {
    const currentPath = await this.getCurrentPath(botAlias);
    const botFiles = mockFiles[botAlias] || {};
    return {
      workingDir: currentPath,
      entries: botFiles[currentPath] || [],
    };
  }

  async changeDirectory(botAlias: string, path: string): Promise<string> {
    const currentPath = await this.getCurrentPath(botAlias);
    let nextPath = currentPath;
    if (path === "..") {
      if (currentPath !== "/") {
        const parts = currentPath.split("/").filter(Boolean);
        parts.pop();
        nextPath = parts.length ? `/${parts.join("/")}` : "/";
      }
    } else {
      nextPath = currentPath === "/" ? `/${path}` : `${currentPath}/${path}`;
    }
    this.currentPaths.set(botAlias, nextPath);
    return nextPath;
  }

  async readFile(botAlias: string, filename: string): Promise<string> {
    return `Mock preview for ${filename}\n\nThis is a local preview.`;
  }

  async uploadFile(botAlias: string, file: File): Promise<void> {
    return;
  }

  async downloadFile(botAlias: string, filename: string): Promise<void> {
    return;
  }

  async resetSession(botAlias: string): Promise<void> {
    return;
  }

  async killTask(botAlias: string): Promise<string> {
    return "已发送终止任务请求";
  }

  async getCliParams(botAlias: string): Promise<CliParamsPayload> {
    return {
      cliType: botAlias === "main" ? "codex" : "kimi",
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

  async updateCliParam(botAlias: string, key: string, value: unknown): Promise<CliParamsPayload> {
    const payload = await this.getCliParams(botAlias);
    return {
      ...payload,
      params: {
        ...payload.params,
        [key]: value,
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
      pid: 1234,
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
      pid: null,
    };
  }

  async restartTunnel(): Promise<TunnelSnapshot> {
    return this.getTunnelStatus();
  }

  async listSystemScripts(): Promise<SystemScript[]> {
    return this.scripts;
  }

  async runSystemScript(scriptName: string): Promise<SystemScriptResult> {
    return {
      scriptName,
      success: true,
      output: `${scriptName} 执行完成（Mock）`,
    };
  }
}

export async function streamAssistantReply(onChunk: (chunk: string) => void) {
  const chunks = ["我先看一下问题。", "已经定位到可能原因。", "建议先检查 session 与工作目录。"];
  for (const chunk of chunks) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    onChunk(chunk);
  }
}
