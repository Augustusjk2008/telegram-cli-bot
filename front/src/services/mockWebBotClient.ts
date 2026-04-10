import type {
  BotOverview,
  BotSummary,
  ChatMessage,
  ChatStatusUpdate,
  CliParamsPayload,
  DirectoryListing,
  GitActionResult,
  GitDiffPayload,
  GitOverview,
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
  private workdirOverrides = new Map<string, string>();
  private gitOverviews = new Map<string, GitOverview>([
    [
      "main",
      {
        repoFound: true,
        canInit: false,
        workingDir: "C:\\workspace\\demo",
        repoPath: "C:\\workspace\\demo",
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
        workingDir: "C:\\workspace\\plans",
        repoPath: "C:\\workspace\\plans",
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
  private readonly scripts: SystemScript[] = [
    {
      scriptName: "network_traffic",
      displayName: "网络流量",
      description: "查看网络状态",
      path: "C:\\scripts\\network_traffic.ps1",
    },
  ];

  private getBotSummary(botAlias: string): BotSummary {
    const fallback = mockBots[0];
    const base = mockBots.find((item) => item.alias === botAlias) || fallback;
    const workingDir = this.workdirOverrides.get(base.alias) || this.currentPaths.get(base.alias) || base.workingDir;
    return {
      ...base,
      workingDir,
    };
  }

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
    return mockBots.map((item) => this.getBotSummary(item.alias));
  }

  async getBotOverview(botAlias: string): Promise<BotOverview> {
    const bot = this.getBotSummary(botAlias);
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
      elapsedSeconds: 1,
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

  async readFileFull(botAlias: string, filename: string): Promise<string> {
    return `Mock full content for ${filename}\n\nThis is the full file content.`;
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

  async restartService(): Promise<void> {
    return;
  }

  async getGitOverview(botAlias: string): Promise<GitOverview> {
    const workingDir = this.workdirOverrides.get(botAlias) || this.currentPaths.get(botAlias) || this.getBotSummary(botAlias).workingDir;
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

  async initGitRepository(botAlias: string): Promise<GitOverview> {
    const workingDir = this.workdirOverrides.get(botAlias) || this.currentPaths.get(botAlias) || this.getBotSummary(botAlias).workingDir;
    const next: GitOverview = {
      repoFound: true,
      canInit: false,
      workingDir,
      repoPath: workingDir,
      repoName: workingDir.split("\\").filter(Boolean).pop() || "repo",
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

  async updateBotWorkdir(botAlias: string, workingDir: string): Promise<BotSummary> {
    const nextDir = workingDir.trim();
    this.workdirOverrides.set(botAlias, nextDir);
    this.currentPaths.set(botAlias, nextDir);
    return this.getBotSummary(botAlias);
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

  async runSystemScriptStream(scriptName: string, onLog: (line: string) => void): Promise<SystemScriptResult> {
    const logs = [
      "cd /d front",
      "npm run build",
      "Web 前端构建完成",
    ];
    for (const line of logs) {
      onLog(line);
      await new Promise((resolve) => setTimeout(resolve, 40));
    }
    return {
      scriptName,
      success: true,
      output: "Web 前端构建完成",
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
