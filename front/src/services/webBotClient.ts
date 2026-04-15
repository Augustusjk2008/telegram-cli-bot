import type {
  BotOverview,
  BotSummary,
  ChatMessage,
  ChatStatusUpdate,
  ChatTraceDetails,
  ChatTraceEvent,
  CliParamsPayload,
  CreateBotInput,
  DirectoryListing,
  FileReadResult,
  AvatarAsset,
  AppUpdateDownloadProgress,
  AppUpdateStatus,
  GitActionResult,
  GitDiffPayload,
  GitProxySettings,
  GitOverview,
  SessionState,
  SystemScript,
  SystemScriptResult,
  TunnelSnapshot,
} from "./types";

export interface WebBotClient {
  login(token: string): Promise<SessionState>;
  listBots(): Promise<BotSummary[]>;
  getBotOverview(botAlias: string): Promise<BotOverview>;
  listMessages(botAlias: string): Promise<ChatMessage[]>;
  getMessageTrace(botAlias: string, messageId: string): Promise<ChatTraceDetails>;
  sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
    onTrace?: (trace: ChatTraceEvent) => void,
  ): Promise<ChatMessage>;
  getCurrentPath(botAlias: string): Promise<string>;
  listFiles(botAlias: string): Promise<DirectoryListing>;
  changeDirectory(botAlias: string, path: string): Promise<string>;
  createDirectory(botAlias: string, name: string): Promise<void>;
  deletePath(botAlias: string, path: string): Promise<void>;
  readFile(botAlias: string, filename: string): Promise<FileReadResult>;
  readFileFull(botAlias: string, filename: string): Promise<FileReadResult>;
  uploadFile(botAlias: string, file: File): Promise<void>;
  downloadFile(botAlias: string, filename: string): Promise<void>;
  resetSession(botAlias: string): Promise<void>;
  killTask(botAlias: string): Promise<string>;
  restartService(): Promise<void>;
  getGitProxySettings(): Promise<GitProxySettings>;
  updateGitProxySettings(port: string): Promise<GitProxySettings>;
  getUpdateStatus(): Promise<AppUpdateStatus>;
  setUpdateEnabled(enabled: boolean): Promise<AppUpdateStatus>;
  checkForUpdate(): Promise<AppUpdateStatus>;
  downloadUpdateStream(onProgress: (event: AppUpdateDownloadProgress) => void): Promise<AppUpdateStatus>;
  downloadUpdate(): Promise<AppUpdateStatus>;
  getGitOverview(botAlias: string): Promise<GitOverview>;
  initGitRepository(botAlias: string): Promise<GitOverview>;
  getGitDiff(botAlias: string, path: string, staged?: boolean): Promise<GitDiffPayload>;
  stageGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult>;
  unstageGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult>;
  commitGitChanges(botAlias: string, message: string): Promise<GitActionResult>;
  fetchGitRemote(botAlias: string): Promise<GitActionResult>;
  pullGitRemote(botAlias: string): Promise<GitActionResult>;
  pushGitRemote(botAlias: string): Promise<GitActionResult>;
  stashGitChanges(botAlias: string): Promise<GitActionResult>;
  popGitStash(botAlias: string): Promise<GitActionResult>;
  updateBotCli(botAlias: string, cliType: string, cliPath: string): Promise<BotSummary>;
  updateBotWorkdir(botAlias: string, workingDir: string): Promise<BotSummary>;
  updateBotAvatar(botAlias: string, avatarName: string): Promise<BotSummary>;
  addBot(input: CreateBotInput): Promise<BotSummary>;
  renameBot(botAlias: string, newAlias: string): Promise<BotSummary>;
  removeBot(botAlias: string): Promise<void>;
  startBot(botAlias: string): Promise<BotSummary>;
  stopBot(botAlias: string): Promise<BotSummary>;
  listAvatarAssets(): Promise<AvatarAsset[]>;
  getCliParams(botAlias: string): Promise<CliParamsPayload>;
  updateCliParam(botAlias: string, key: string, value: unknown, cliType?: string): Promise<CliParamsPayload>;
  resetCliParams(botAlias: string, cliType?: string): Promise<CliParamsPayload>;
  getTunnelStatus(): Promise<TunnelSnapshot>;
  startTunnel(): Promise<TunnelSnapshot>;
  stopTunnel(): Promise<TunnelSnapshot>;
  restartTunnel(): Promise<TunnelSnapshot>;
  listSystemScripts(): Promise<SystemScript[]>;
  runSystemScript(scriptName: string): Promise<SystemScriptResult>;
  runSystemScriptStream(scriptName: string, onLog: (line: string) => void): Promise<SystemScriptResult>;
}
