import type {
  AppUpdateStatus,
  BotOverview,
  BotSummary,
  ChatMessage,
  ChatStatusUpdate,
  ChatTraceDetails,
  ChatTraceEvent,
  CliParamsPayload,
  CreateBotInput,
  DirectoryListing,
  AvatarAsset,
  GitActionResult,
  GitDiffPayload,
  GitProxySettings,
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
import {
  DEMO_MAIN_WORKDIR,
  DEMO_SYSTEM_SCRIPTS,
  DEMO_TEAM_WORKDIR,
} from "../mocks/demoEnvironment";

export class MockWebBotClient implements WebBotClient {
  private bots = new Map<string, BotSummary>(
    mockBots.map((item) => [
      item.alias,
      {
        ...item,
        cliPath: item.cliType,
        botMode: "cli",
        enabled: true,
        isMain: item.alias === "main",
      },
    ]),
  );
  private currentPaths = new Map<string, string>();
  private workdirOverrides = new Map<string, string>();
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
  private readonly scripts: SystemScript[] = DEMO_SYSTEM_SCRIPTS;
  private gitProxySettings: GitProxySettings = { port: "" };
  private updateStatus: AppUpdateStatus = {
    currentVersion: "1.0.1",
    updateEnabled: true,
    updateChannel: "release",
    lastCheckedAt: "",
    latestVersion: "1.0.1",
    latestReleaseUrl: "https://github.com/example/cli-bridge/releases/tag/v1.0.1",
    latestNotes: "Bugfixes",
    pendingUpdateVersion: "",
    pendingUpdatePath: "",
    pendingUpdateNotes: "",
    pendingUpdatePlatform: "",
    lastError: "",
  };
  private readonly avatarAssets: AvatarAsset[] = [
    { name: "user-default.png", url: "/assets/avatars/user-default.png" },
    { name: "bot-default.png", url: "/assets/avatars/bot-default.png" },
    { name: "claude-blue.png", url: "/assets/avatars/claude-blue.png" },
    { name: "codex-slate.png", url: "/assets/avatars/codex-slate.png" },
  ];

  private moveKey<T>(map: Map<string, T>, oldKey: string, newKey: string) {
    if (!map.has(oldKey)) {
      return;
    }
    const value = map.get(oldKey) as T;
    map.delete(oldKey);
    map.set(newKey, value);
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
        avatarName: "bot-default.png",
        cliPath: "codex",
        botMode: "cli",
        enabled: true,
        isMain: false,
      };
    }
    const workingDir = this.workdirOverrides.get(base.alias) || base.workingDir;
    return {
      ...base,
      workingDir,
    };
  }

  private getBrowserPath(botAlias: string): string {
    return this.currentPaths.get(botAlias) || this.getBotSummary(botAlias).workingDir;
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
    return Array.from(this.bots.values()).map((item) => this.getBotSummary(item.alias));
  }

  async getBotOverview(botAlias: string): Promise<BotOverview> {
    const bot = this.getBotSummary(botAlias);
    return {
      ...bot,
      botMode: bot.botMode || "cli",
      cliPath: bot.cliPath,
      enabled: bot.enabled,
      isMain: bot.isMain,
      messageCount: mockChatMessages[bot.alias]?.length || 0,
      historyCount: mockChatMessages[bot.alias]?.length || 0,
      isProcessing: false,
    };
  }

  async listMessages(botAlias: string): Promise<ChatMessage[]> {
    return mockChatMessages[botAlias] || [];
  }

  async getMessageTrace(_botAlias: string, _messageId: string): Promise<ChatTraceDetails> {
    return {
      traceCount: 0,
      toolCallCount: 0,
      processCount: 0,
      trace: [],
    };
  }

  async sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
    onTrace?: (trace: ChatTraceEvent) => void,
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
    return this.getBotSummary(botAlias).workingDir;
  }

  async listFiles(botAlias: string): Promise<DirectoryListing> {
    const currentPath = this.getBrowserPath(botAlias);
    const botFiles = mockFiles[botAlias] || {};
    return {
      workingDir: currentPath,
      entries: botFiles[currentPath] || [],
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

  async createDirectory(botAlias: string, name: string): Promise<void> {
    const folderName = name.trim();
    if (!folderName) {
      throw new Error("文件夹名称不能为空");
    }

    const currentPath = this.getBrowserPath(botAlias);
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

  async readFile(botAlias: string, filename: string) {
    return {
      content: `Mock preview for ${filename}\n\nThis is a local preview.`,
      mode: "head" as const,
      fileSizeBytes: 1024,
      isFullContent: false,
    };
  }

  async readFileFull(botAlias: string, filename: string) {
    return {
      content: `Mock full content for ${filename}\n\nThis is the full file content.`,
      mode: "cat" as const,
      fileSizeBytes: 1024,
      isFullContent: true,
    };
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

  async getGitProxySettings(): Promise<GitProxySettings> {
    return { ...this.gitProxySettings };
  }

  async updateGitProxySettings(port: string): Promise<GitProxySettings> {
    this.gitProxySettings = {
      port: (port || "").trim(),
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
      latestVersion: "1.0.1",
      latestReleaseUrl: "https://github.com/example/cli-bridge/releases/tag/v1.0.1",
      latestNotes: "Bugfixes",
      lastError: "",
    };
    return { ...this.updateStatus };
  }

  async downloadUpdate(): Promise<AppUpdateStatus> {
    this.updateStatus = {
      ...this.updateStatus,
      pendingUpdateVersion: this.updateStatus.latestVersion || "1.0.1",
      pendingUpdatePath: ".updates/cli-bridge-windows-x64.zip",
      pendingUpdateNotes: this.updateStatus.latestNotes || "Bugfixes",
      pendingUpdatePlatform: "windows-x64",
      lastError: "",
    };
    return { ...this.updateStatus };
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

  async updateBotWorkdir(botAlias: string, workingDir: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    if (current.botMode === "assistant") {
      throw new Error("assistant 型 Bot 不允许修改默认工作目录");
    }
    const nextDir = workingDir.trim();
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
      avatarName: avatarName.trim() || "bot-default.png",
    });
    return this.getBotSummary(botAlias);
  }

  async addBot(input: CreateBotInput): Promise<BotSummary> {
    const alias = input.alias.trim().toLowerCase();
    const bot: BotSummary = {
      alias,
      cliType: input.cliType,
      cliPath: input.cliPath.trim(),
      botMode: input.botMode,
      status: "running",
      workingDir: input.workingDir.trim(),
      lastActiveText: "运行中",
      avatarName: input.avatarName || "bot-default.png",
      enabled: true,
      isMain: false,
    };
    this.bots.set(alias, bot);
    this.currentPaths.set(alias, bot.workingDir);
    this.workdirOverrides.set(alias, bot.workingDir);
    return this.getBotSummary(alias);
  }

  async renameBot(botAlias: string, newAlias: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    const alias = newAlias.trim().toLowerCase();
    this.bots.delete(botAlias);
    this.bots.set(alias, {
      ...current,
      alias,
    });
    this.moveKey(this.currentPaths, botAlias, alias);
    this.moveKey(this.workdirOverrides, botAlias, alias);
    this.moveKey(this.gitOverviews, botAlias, alias);
    return this.getBotSummary(alias);
  }

  async removeBot(botAlias: string): Promise<void> {
    if (botAlias === "main") {
      return;
    }
    this.bots.delete(botAlias);
    this.currentPaths.delete(botAlias);
    this.workdirOverrides.delete(botAlias);
    this.gitOverviews.delete(botAlias);
  }

  async startBot(botAlias: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    this.bots.set(botAlias, {
      ...current,
      status: "running",
      lastActiveText: "运行中",
      enabled: true,
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
    });
    return this.getBotSummary(botAlias);
  }

  async listAvatarAssets(): Promise<AvatarAsset[]> {
    return [...this.avatarAssets];
  }

  async getCliParams(botAlias: string): Promise<CliParamsPayload> {
    const cliType = this.getBotSummary(botAlias).cliType;
    return {
      cliType,
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
      "cd front",
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
