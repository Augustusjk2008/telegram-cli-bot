import { WebApiClientError } from "./types";
import type {
  AppUpdateDownloadProgress,
  AppUpdateStatus,
  AssistantCronJob,
  AssistantCronRun,
  AssistantCronRunRequestResult,
  CreateAssistantCronJobInput,
  BotOverview,
  BotSummary,
  ChatAttachmentDeleteResult,
  ChatAttachmentUploadResult,
  ChatMessage,
  ChatStatusUpdate,
  ChatTraceDetails,
  ChatTraceEvent,
  CliParamsPayload,
  CreateBotInput,
  DebugProfile,
  DebugState,
  DirectoryListing,
  AvatarAsset,
  FileCreateResult,
  GitActionResult,
  GitDiffPayload,
  GitProxySettings,
  GitOverview,
  FileRenameResult,
  FileWriteResult,
  PublicHostInfo,
  SessionState,
  SystemScript,
  SystemScriptResult,
  TaskRunResult,
  TaskRunStreamEvent,
  TaskRunStreamOptions,
  TunnelSnapshot,
  UpdateAssistantCronJobInput,
  UpdateBotWorkdirOptions,
  WorkspaceOutlineResult,
  WorkspaceProblem,
  WorkspaceQuickOpenResult,
  WorkspaceSearchResult,
  WorkspaceTask,
} from "./types";
import { WebBotClient } from "./webBotClient";
import { mockBots } from "../mocks/bots";
import { mockChatMessages } from "../mocks/chat";
import { mockFiles } from "../mocks/files";
import {
  DEMO_MAIN_WORKDIR,
  DEMO_SYSTEM_SCRIPTS_BY_BOT,
  DEMO_TEAM_WORKDIR,
} from "../mocks/demoEnvironment";
import { APP_VERSION } from "../theme";

const MOCK_RELEASE_URL = `https://github.com/example/cli-bridge/releases/tag/v${APP_VERSION}`;

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
  private gitProxySettings: GitProxySettings = { port: "" };
  private updateStatus: AppUpdateStatus = {
    currentVersion: APP_VERSION,
    updateEnabled: true,
    updateChannel: "release",
    lastCheckedAt: "",
    latestVersion: APP_VERSION,
    latestReleaseUrl: MOCK_RELEASE_URL,
    latestNotes: "Bugfixes",
    pendingUpdateVersion: "",
    pendingUpdatePath: "",
    pendingUpdateNotes: "",
    pendingUpdatePlatform: "",
    lastError: "",
  };
  private readonly avatarAssets: AvatarAsset[] = [
    { name: "avatar_01.png", url: "/assets/avatars/avatar_01.png" },
    { name: "avatar_02.png", url: "/assets/avatars/avatar_02.png" },
    { name: "avatar_03.png", url: "/assets/avatars/avatar_03.png" },
    { name: "avatar_04.png", url: "/assets/avatars/avatar_04.png" },
  ];
  private assistantCronJobs = new Map<string, AssistantCronJob[]>();
  private assistantCronRuns = new Map<string, AssistantCronRun[]>();
  private taskProblems = new Map<string, WorkspaceProblem[]>();
  private fileContents = new Map<string, string>();
  private fileVersions = new Map<string, number>();

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
        avatarName: "avatar_01.png",
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

  private resolveTargetDir(botAlias: string, parentPath?: string): string {
    const candidate = parentPath?.trim();
    return candidate && candidate.length > 0 ? candidate : this.getBrowserPath(botAlias);
  }

  private cronRunKey(botAlias: string, jobId: string): string {
    return `${botAlias}:${jobId}`;
  }

  private fileKey(botAlias: string, browserPath: string, filename: string): string {
    return `${botAlias}:${browserPath}:${filename}`;
  }

  private getFileContent(botAlias: string, browserPath: string, filename: string): string {
    const key = this.fileKey(botAlias, browserPath, filename);
    if (this.fileContents.has(key)) {
      return this.fileContents.get(key) || "";
    }
    return `Mock full content for ${filename}\n\nThis is the full file content.`;
  }

  private getFileVersion(botAlias: string, browserPath: string, filename: string): number {
    const key = this.fileKey(botAlias, browserPath, filename);
    if (!this.fileVersions.has(key)) {
      this.fileVersions.set(key, Date.now() * 1_000_000);
    }
    return this.fileVersions.get(key) || Date.now() * 1_000_000;
  }

  private setFileState(botAlias: string, browserPath: string, filename: string, content: string): number {
    const key = this.fileKey(botAlias, browserPath, filename);
    const version = Date.now() * 1_000_000 + Math.floor(Math.random() * 1_000);
    this.fileContents.set(key, content);
    this.fileVersions.set(key, version);
    return version;
  }

  private getAssistantCronJobs(botAlias: string): AssistantCronJob[] {
    return [...(this.assistantCronJobs.get(botAlias) || [])];
  }

  async getPublicHostInfo(): Promise<PublicHostInfo> {
    return {
      username: "demo",
      operatingSystem: "Windows 11",
      hardwarePlatform: "AMD64",
      hardwareSpec: "16 逻辑核心 · 32 GB 内存",
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

  async getDebugProfile(_botAlias: string): Promise<DebugProfile | null> {
    return {
      configName: "(gdb) Remote Debug",
      program: "H:\\Resources\\RTLinux\\Demos\\MB_DDF\\build\\aarch64\\Debug\\MB_DDF",
      cwd: "H:\\Resources\\RTLinux\\Demos\\MB_DDF",
      miDebuggerPath: "D:\\Toolchain\\aarch64-none-linux-gnu-gdb.exe",
      compileCommands: "H:\\Resources\\RTLinux\\Demos\\MB_DDF\\.vscode\\compile_commands.json",
      prepareCommand: ".\\debug.bat",
      stopAtEntry: true,
      setupCommands: [
        "-enable-pretty-printing",
        "set print thread-events off",
        "set pagination off",
        "set sysroot H:/Resources/RTLinux/Demos/MB_DDF/build/aarch64/sysroot",
      ],
      remoteHost: "192.168.1.29",
      remoteUser: "root",
      remoteDir: "/home/sast8/tmp",
      remotePort: 1234,
    };
  }

  async getDebugState(_botAlias: string): Promise<DebugState> {
    return {
      phase: "idle",
      message: "",
      breakpoints: [],
      frames: [],
      currentFrameId: "",
      scopes: [],
      variables: {},
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

  async listFiles(botAlias: string, path?: string): Promise<DirectoryListing> {
    const currentPath = path?.trim() || this.getBrowserPath(botAlias);
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

  async createDirectory(botAlias: string, name: string, parentPath?: string): Promise<void> {
    const folderName = name.trim();
    if (!folderName) {
      throw new Error("文件夹名称不能为空");
    }

    const currentPath = this.resolveTargetDir(botAlias, parentPath);
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
    const browserPath = this.getBrowserPath(botAlias);
    const content = this.getFileContent(botAlias, browserPath, filename);
    return {
      content,
      mode: "head" as const,
      fileSizeBytes: new TextEncoder().encode(content).length,
      isFullContent: true,
      lastModifiedNs: String(this.getFileVersion(botAlias, browserPath, filename)),
    };
  }

  async readFileFull(botAlias: string, filename: string) {
    const browserPath = this.getBrowserPath(botAlias);
    const content = this.getFileContent(botAlias, browserPath, filename);
    return {
      content,
      mode: "cat" as const,
      fileSizeBytes: new TextEncoder().encode(content).length,
      isFullContent: true,
      lastModifiedNs: String(this.getFileVersion(botAlias, browserPath, filename)),
    };
  }

  async writeFile(botAlias: string, path: string, content: string, expectedMtimeNs?: string): Promise<FileWriteResult> {
    const browserPath = this.getBrowserPath(botAlias);
    const currentVersion = this.getFileVersion(botAlias, browserPath, path);
    if (expectedMtimeNs !== undefined && expectedMtimeNs !== String(currentVersion)) {
      throw new Error("文件已被修改，请重新打开后再试");
    }

    const nextVersion = this.setFileState(botAlias, browserPath, path, content);
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[browserPath] || [])];
    botFiles[browserPath] = currentEntries.map((entry) =>
      entry.name === path
        ? {
            ...entry,
            size: new TextEncoder().encode(content).length,
            updatedAt: new Date().toISOString(),
          }
        : entry,
    );

    return {
      path,
      fileSizeBytes: new TextEncoder().encode(content).length,
      lastModifiedNs: String(nextVersion),
    };
  }

  async createTextFile(botAlias: string, filename: string, content = "", parentPath?: string): Promise<FileCreateResult> {
    const fileName = filename.trim();
    if (!fileName) {
      throw new Error("文件名不能为空");
    }

    const targetDir = this.resolveTargetDir(botAlias, parentPath);
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[targetDir] || [])];
    if (currentEntries.some((entry) => entry.name === fileName)) {
      throw new Error("文件已存在");
    }

    currentEntries.push({
      name: fileName,
      isDir: false,
      size: new TextEncoder().encode(content).length,
      updatedAt: new Date().toISOString(),
    });
    currentEntries.sort((left, right) => {
      if (left.isDir !== right.isDir) {
        return left.isDir ? -1 : 1;
      }
      return left.name.localeCompare(right.name, "zh-CN");
    });
    botFiles[targetDir] = currentEntries;

    const nextVersion = this.setFileState(botAlias, targetDir, fileName, content);
    const browserPath = this.getBrowserPath(botAlias);
    const normalizedTargetDir = targetDir.replace(/\\/g, "/");
    const normalizedBrowserPath = browserPath.replace(/\\/g, "/");
    const relativeDir = normalizedTargetDir === normalizedBrowserPath
      ? ""
      : normalizedTargetDir.startsWith(`${normalizedBrowserPath}/`)
        ? normalizedTargetDir.slice(normalizedBrowserPath.length + 1)
        : "";
    return {
      path: relativeDir ? `${relativeDir}/${fileName}` : fileName,
      fileSizeBytes: new TextEncoder().encode(content).length,
      lastModifiedNs: String(nextVersion),
    };
  }

  async renamePath(botAlias: string, path: string, newName: string): Promise<FileRenameResult> {
    const browserPath = this.getBrowserPath(botAlias);
    const nextName = newName.trim();
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[browserPath] || [])];
    if (currentEntries.some((entry) => entry.name === nextName)) {
      throw new Error("目标已存在");
    }

    const source = currentEntries.find((entry) => entry.name === path);
    if (!source || source.isDir) {
      throw new Error("文件不存在");
    }

    botFiles[browserPath] = currentEntries.map((entry) =>
      entry.name === path
        ? {
            ...entry,
            name: nextName,
            updatedAt: new Date().toISOString(),
          }
        : entry,
    );

    const content = this.getFileContent(botAlias, browserPath, path);
    const version = this.getFileVersion(botAlias, browserPath, path);
    this.fileContents.delete(this.fileKey(botAlias, browserPath, path));
    this.fileVersions.delete(this.fileKey(botAlias, browserPath, path));
    this.fileContents.set(this.fileKey(botAlias, browserPath, nextName), content);
    this.fileVersions.set(this.fileKey(botAlias, browserPath, nextName), version);

    return {
      oldPath: path,
      path: nextName,
    };
  }

  async quickOpenWorkspace(botAlias: string, query: string, limit = 50): Promise<WorkspaceQuickOpenResult> {
    const q = query.trim().toLowerCase();
    const botFiles = mockFiles[botAlias] || {};
    const rootPath = this.getBrowserPath(botAlias).replace(/\\/g, "/");
    const items = Object.entries(botFiles)
      .flatMap(([directory, entries]) => entries
        .filter((entry) => !entry.isDir)
        .map((entry) => {
          const normalizedDir = directory.replace(/\\/g, "/");
          const relativeDir = normalizedDir === rootPath
            ? ""
            : normalizedDir.startsWith(`${rootPath}/`)
              ? normalizedDir.slice(rootPath.length + 1)
              : normalizedDir.replace(/^\/+/, "");
          const path = relativeDir ? `${relativeDir}/${entry.name}` : entry.name;
          const lowerPath = path.toLowerCase();
          const basename = entry.name.toLowerCase();
          const score = basename.includes(q) ? 1000 : lowerPath.includes(q) ? 300 : 0;
          return { path, score };
        }))
      .filter((item) => !q || item.path.toLowerCase().includes(q))
      .sort((left, right) => right.score - left.score || left.path.localeCompare(right.path, "zh-CN"))
      .slice(0, limit);
    return { items };
  }

  async searchWorkspace(botAlias: string, query: string, limit = 100): Promise<WorkspaceSearchResult> {
    const q = query.trim().toLowerCase();
    if (!q) {
      return { items: [] };
    }
    const quick = await this.quickOpenWorkspace(botAlias, "", 500);
    const root = this.getBrowserPath(botAlias);
    const items = quick.items.flatMap((item) => {
      const content = this.getFileContent(botAlias, root, item.path);
      const lines = content.split(/\r?\n/);
      return lines.flatMap((line, index) => {
        const column = line.toLowerCase().indexOf(q);
        return column >= 0
          ? [{
              path: item.path,
              line: index + 1,
              column: column + 1,
              preview: line,
            }]
          : [];
      });
    }).slice(0, limit);
    return { items };
  }

  async getWorkspaceOutline(botAlias: string, path: string): Promise<WorkspaceOutlineResult> {
    const content = this.getFileContent(botAlias, this.getBrowserPath(botAlias), path);
    const items: WorkspaceOutlineResult["items"] = [];
    content.split(/\r?\n/).forEach((line, index) => {
      const classMatch = line.match(/^\s*class\s+([A-Za-z_][\w]*)/);
      if (classMatch) {
        items.push({ name: classMatch[1], kind: "class", line: index + 1 });
        return;
      }
      const functionMatch = line.match(/^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)|^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/);
      if (functionMatch) {
        items.push({ name: functionMatch[1] || functionMatch[2], kind: "function", line: index + 1 });
        return;
      }
      const headingMatch = line.match(/^#{1,6}\s+(.+)/);
      if (headingMatch) {
        items.push({ name: headingMatch[1].trim(), kind: "heading", line: index + 1 });
      }
    });
    return { items };
  }

  async listTasks(_botAlias: string): Promise<WorkspaceTask[]> {
    return [
      { id: "npm:test", label: "npm test", command: "npm run test", source: "package.json", detail: "vitest" },
      { id: "npm:build", label: "npm build", command: "npm run build", source: "package.json", detail: "vite build" },
      { id: "python:pytest", label: "pytest", command: "python -m pytest", source: "tests", detail: "运行 Python 测试" },
    ];
  }

  async runTaskStream(
    botAlias: string,
    taskId: string,
    onEvent: (event: TaskRunStreamEvent) => void,
    options: TaskRunStreamOptions = {},
  ): Promise<TaskRunResult> {
    if (options.signal?.aborted) {
      throw new Error("任务已取消");
    }
    onEvent({ type: "meta", taskId, command: taskId.startsWith("npm:") ? ["npm", "run", taskId.slice(4)] : ["python", "-m", "pytest"] });
    await new Promise((resolve) => setTimeout(resolve, 20));
    if (options.signal?.aborted) {
      throw new Error("任务已取消");
    }
    const text = `mock task ${taskId}`;
    onEvent({ type: "log", text });
    const problems: WorkspaceProblem[] = [];
    const result = {
      taskId,
      success: true,
      returnCode: 0,
      output: `${text}\n`,
      problems,
    };
    this.taskProblems.set(botAlias, problems);
    onEvent({ type: "done", result });
    return result;
  }

  async getProblems(botAlias: string): Promise<WorkspaceProblem[]> {
    return [...(this.taskProblems.get(botAlias) || [])];
  }

  async uploadChatAttachment(botAlias: string, file: File): Promise<ChatAttachmentUploadResult> {
    const filename = file.name || "attachment.bin";
    return {
      filename,
      savedPath: `C:\\Users\\demo\\.tcb\\chat-attachments\\${botAlias}\\1001\\${filename}`,
      size: file.size,
    };
  }

  async deleteChatAttachment(_botAlias: string, savedPath: string): Promise<ChatAttachmentDeleteResult> {
    const segments = savedPath.split(/[\\/]+/).filter(Boolean);
    return {
      filename: segments[segments.length - 1] || savedPath,
      savedPath,
      existed: true,
      deleted: true,
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
      latestVersion: APP_VERSION,
      latestReleaseUrl: MOCK_RELEASE_URL,
      latestNotes: "Bugfixes",
      lastError: "",
    };
    return { ...this.updateStatus };
  }

  async downloadUpdate(): Promise<AppUpdateStatus> {
    this.updateStatus = {
      ...this.updateStatus,
      pendingUpdateVersion: this.updateStatus.latestVersion || APP_VERSION,
      pendingUpdatePath: ".updates/cli-bridge-windows-x64.zip",
      pendingUpdateNotes: this.updateStatus.latestNotes || "Bugfixes",
      pendingUpdatePlatform: "windows-x64",
      lastError: "",
    };
    return { ...this.updateStatus };
  }

  async downloadUpdateStream(onProgress: (event: AppUpdateDownloadProgress) => void): Promise<AppUpdateStatus> {
    onProgress({
      phase: "log",
      downloadedBytes: 0,
      message: "开始下载更新包",
    });
    await new Promise((resolve) => setTimeout(resolve, 40));
    onProgress({
      phase: "log",
      downloadedBytes: 1024,
      totalBytes: 1024,
      percent: 100,
      message: "下载完成",
    });
    return this.downloadUpdate();
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

  async updateBotWorkdir(
    botAlias: string,
    workingDir: string,
    options: UpdateBotWorkdirOptions = {},
  ): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    if (current.botMode === "assistant") {
      throw new Error("assistant 型 Bot 不允许修改默认工作目录");
    }
    const nextDir = workingDir.trim();
    const historyCount = mockChatMessages[botAlias]?.length || 0;
    if (!options.forceReset && historyCount > 0) {
      throw new WebApiClientError("切换工作目录会丢失当前会话，确认后重试", {
        status: 409,
        code: "workdir_change_requires_reset",
        data: {
          currentWorkingDir: current.workingDir,
          requestedWorkingDir: nextDir,
          historyCount,
          messageCount: historyCount,
          botMode: current.botMode || "cli",
        },
      });
    }
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
      avatarName: avatarName.trim(),
    });
    return this.getBotSummary(botAlias);
  }

  async listAssistantCronJobs(botAlias: string): Promise<AssistantCronJob[]> {
    return this.getAssistantCronJobs(botAlias);
  }

  async createAssistantCronJob(botAlias: string, input: CreateAssistantCronJobInput): Promise<AssistantCronJob> {
    const current = this.getAssistantCronJobs(botAlias);
    const taskMode = input.task.mode || "standard";
    const job: AssistantCronJob = {
      ...input,
      task: {
        prompt: input.task.prompt,
        mode: taskMode,
        lookbackHours: input.task.lookbackHours ?? 24,
        historyLimit: input.task.historyLimit ?? 40,
        captureLimit: input.task.captureLimit ?? 20,
        deliverMode: input.task.deliverMode ?? (taskMode === "dream" ? "silent" : "chat_handoff"),
      },
      nextRunAt: input.schedule.type === "daily"
        ? "2026-04-17T09:00:00+08:00"
        : "2026-04-16T10:00:00+08:00",
      lastStatus: "",
      lastError: "",
      lastSuccessAt: "",
      pending: false,
      pendingRunId: "",
      coalescedCount: 0,
    };
    this.assistantCronJobs.set(botAlias, [...current.filter((item) => item.id !== job.id), job]);
    return job;
  }

  async updateAssistantCronJob(
    botAlias: string,
    jobId: string,
    input: UpdateAssistantCronJobInput,
  ): Promise<AssistantCronJob> {
    const current = this.getAssistantCronJobs(botAlias);
    const existing = current.find((item) => item.id === jobId);
    if (!existing) {
      throw new Error("任务不存在");
    }
    const updated: AssistantCronJob = {
      ...existing,
      ...(typeof input.enabled === "boolean" ? { enabled: input.enabled } : {}),
      ...(input.title ? { title: input.title } : {}),
      schedule: {
        ...existing.schedule,
        ...(input.schedule || {}),
      },
      task: {
        ...existing.task,
        ...(input.task || {}),
        mode: input.task?.mode || existing.task.mode || "standard",
        lookbackHours: input.task?.lookbackHours ?? existing.task.lookbackHours ?? 24,
        historyLimit: input.task?.historyLimit ?? existing.task.historyLimit ?? 40,
        captureLimit: input.task?.captureLimit ?? existing.task.captureLimit ?? 20,
        deliverMode: input.task?.deliverMode
          ?? existing.task.deliverMode
          ?? ((input.task?.mode || existing.task.mode) === "dream" ? "silent" : "chat_handoff"),
      },
      execution: {
        ...existing.execution,
        ...(input.execution || {}),
      },
    };
    this.assistantCronJobs.set(
      botAlias,
      current.map((item) => (item.id === jobId ? updated : item)),
    );
    return updated;
  }

  async deleteAssistantCronJob(botAlias: string, jobId: string): Promise<void> {
    this.assistantCronJobs.set(
      botAlias,
      this.getAssistantCronJobs(botAlias).filter((item) => item.id !== jobId),
    );
    this.assistantCronRuns.delete(this.cronRunKey(botAlias, jobId));
  }

  async runAssistantCronJob(botAlias: string, jobId: string): Promise<AssistantCronRunRequestResult> {
    const job = this.getAssistantCronJobs(botAlias).find((item) => item.id === jobId);
    const runId = `run_${Date.now()}`;
    const runs = this.assistantCronRuns.get(this.cronRunKey(botAlias, jobId)) || [];
    this.assistantCronRuns.set(this.cronRunKey(botAlias, jobId), [
      {
        runId,
        jobId,
        triggerSource: "manual",
        scheduledAt: new Date().toISOString(),
        enqueuedAt: new Date().toISOString(),
        startedAt: "",
        finishedAt: "",
        status: "queued",
        elapsedSeconds: 0,
        queueWaitSeconds: 0,
        timedOut: false,
        promptExcerpt: "",
        outputExcerpt: "",
        error: "",
      },
      ...runs,
    ]);
    this.assistantCronJobs.set(
      botAlias,
      this.getAssistantCronJobs(botAlias).map((item) =>
        item.id === jobId
          ? { ...item, pending: true, pendingRunId: runId, lastStatus: "queued" }
          : item,
      ),
    );
    return {
      runId,
      status: "queued",
      taskMode: job?.task.mode || "standard",
      deliverMode: job?.task.deliverMode || "chat_handoff",
    };
  }

  async listAssistantCronRuns(botAlias: string, jobId: string, limit = 5): Promise<AssistantCronRun[]> {
    return (this.assistantCronRuns.get(this.cronRunKey(botAlias, jobId)) || []).slice(0, limit);
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
      avatarName: input.avatarName,
      enabled: true,
      isMain: false,
    };
    this.bots.set(alias, bot);
    this.currentPaths.set(alias, bot.workingDir);
    this.workdirOverrides.set(alias, bot.workingDir);
    if (bot.botMode === "assistant" && !this.assistantCronJobs.has(alias)) {
      this.assistantCronJobs.set(alias, []);
    }
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
    this.moveKey(this.assistantCronJobs, botAlias, alias);
    for (const [key, value] of Array.from(this.assistantCronRuns.entries())) {
      if (!key.startsWith(`${botAlias}:`)) {
        continue;
      }
      this.assistantCronRuns.delete(key);
      this.assistantCronRuns.set(`${alias}:${key.slice(botAlias.length + 1)}`, value);
    }
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
    this.assistantCronJobs.delete(botAlias);
    for (const key of Array.from(this.assistantCronRuns.keys())) {
      if (key.startsWith(`${botAlias}:`)) {
        this.assistantCronRuns.delete(key);
      }
    }
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

  async listSystemScripts(botAlias: string): Promise<SystemScript[]> {
    return [...(DEMO_SYSTEM_SCRIPTS_BY_BOT[botAlias] || [])];
  }

  async runSystemScript(botAlias: string, scriptName: string): Promise<SystemScriptResult> {
    return {
      scriptName,
      success: true,
      output: `${botAlias}:${scriptName} 执行完成（Mock）`,
    };
  }

  async runSystemScriptStream(botAlias: string, scriptName: string, onLog: (line: string) => void): Promise<SystemScriptResult> {
    const logs = [
      "cd scripts",
      scriptName,
      "系统功能执行完成",
    ];
    for (const line of logs) {
      onLog(line);
      await new Promise((resolve) => setTimeout(resolve, 40));
    }
    return {
      scriptName,
      success: true,
      output: `${botAlias}:${scriptName} 执行完成（Mock）`,
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
