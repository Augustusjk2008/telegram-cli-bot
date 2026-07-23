import type {
  AdminUser,
  AdminUserUpdateInput,
  AnnouncementItem,
  AnnouncementListResult,
  CreateAnnouncementInput,
  BotOverview,
  BotWorkdirOpenResult,
  BotSummary,
  AgentInput,
  AgentListResult,
  AgentMutationResult,
  AgentScopedOptions,
  ChatMessage,
  ChatStatusUpdate,
  ChatTraceDetails,
  ChatTraceEvent,
  CliErrorStatsFilters,
  CliErrorStatsResult,
  BotExecutionConfigInput,
  CliParamsPayload,
  CreateBotInput,
  DebugProfile,
  DebugState,
  DirectoryListing,
  DirectoryListingOptions,
  EnvConfigPatchInput,
  EnvConfigPatchResult,
  EnvConfigSnapshot,
  FileOpenTarget,
  FileTreeRevealResult,
  FileCopyResult,
  FileCreateResult,
  FileDownloadProgress,
  FileMoveResult,
  FileReadResult,
  FileRenameResult,
  FileWriteResult,
  AppUpdateDownloadProgress,
  AppUpdateStatus,
  OfflineUpdatePackageList,
  GitActionResult,
  GitBranchResetResult,
  GitBranchList,
  GitCommitGraphOptions,
  GitCommitGraphPayload,
  GitCommitMessageCliConfig,
  GitCommitMessageCliConfigUpdateInput,
  GitCommitMessageGenerateResult,
  GitSmartCommitJob,
  GitDiffPayload,
  GitIdentityConfig,
  GitIdentityScope,
  GitProxySettings,
  GitResetMode,
  GitOverview,
  GitStashList,
  GitTreeStatus,
  LanChatConfig,
  LanChatConfigInput,
  LanChatConversation,
  LanChatEvent,
  LanChatMessage,
  LanChatStatus,
  NotificationSettingsStatus,
  NotificationTestResult,
  NotificationSubscription,
  NotificationSubscriptionOptions,
  NotificationPresenceUpdate,
  WebNotificationEvent,
  ChatAttachmentUploadResult,
  ChatAttachmentDeleteResult,
  NativeAgentPermissionReplyOptions,
  NativeAgentConfigPayload,
  NativeAgentPreflightResult,
  NativeAgentModelUpdateResult,
  NativeAgentModelUpdateOptions,
  NativeAgentModelsPayload,
  NativeAgentHistoryChangesPayload,
  NativeAgentHistoryDiffPayload,
  NativeAgentHistoryRollbackResult,
  ChatSendOptions,
  ClusterConfigUpdateInput,
  ClusterConfigUpdateResult,
  ClusterBundleApplyResult,
  ClusterBundlePreviewResult,
  ClusterBundleSchemaResult,
  ClusterSetupPrepareResult,
  ClusterStatus,
  ClusterTaskStatus,
  ClusterTemplateListResult,
  ConversationListResult,
  ConversationBulkDeleteResult,
  ConversationDeleteResult,
  FavoriteAnswerInput,
  FavoriteAnswerItem,
  FavoriteAnswerListResult,
  PlanExecuteInput,
  PlanExecuteResult,
  ConversationSelectResult,
  HistoryDeltaOptions,
  HistoryDeltaResult,
  PublicHostInfo,
  PluginViewWindowRequest,
  PluginViewWindowPayload,
  RemoveBotOptions,
  RemoveBotResult,
  InstallablePluginSummary,
  PluginRenderResult,
  PluginSummary,
  PluginUpdateInput,
  PluginActionInvokeInput,
  PluginActionResult,
  PromptPreset,
  RegisterCodeCreateResult,
  RegisterCodeItem,
  SessionState,
  PersistentTerminalSnapshot,
  TerminalActionRunInput,
  TerminalActionRunResult,
  TerminalActionsConfig,
  TerminalActionsEditableConfig,
  TransferBridgeConfigInput,
  TransferBridgeStatus,
  InlineCompletionConfig,
  InlineCompletionConfigInput,
  InlineCompletionRequest,
  InlineCompletionResult,
  LanguageServerCatalog,
  LanguageServerInstallOptions,
  LanguageServerProviderId,
  TunnelSnapshot,
  UpdateBotWorkdirOptions,
  UserBotPermissions,
  CodeNavigationRequest,
  CodeNavigationResult,
  WorkspaceDocumentSyncInput,
  WorkspaceDocumentSyncResult,
  WorkspaceDocumentCloseInput,
  WorkspaceDocumentCloseResult,
  WorkspaceOutlineResult,
  WorkspaceQuickOpenResult,
  WorkspaceSearchResult,
} from "./types";
import type { AgUiEvent } from "./agUiProtocol";

export interface WebBotClient {
  getPublicHostInfo(): Promise<PublicHostInfo>;
  login(input: { username: string; password: string } | string): Promise<SessionState>;
  register(input: { username: string; password: string; registerCode: string }): Promise<SessionState>;
  loginGuest(): Promise<SessionState>;
  restoreSession(token?: string): Promise<SessionState>;
  logout(): Promise<void>;
  listAnnouncements(): Promise<AnnouncementListResult>;
  markAnnouncementsSeen(latestId: string): Promise<AnnouncementListResult>;
  upsertAnnouncement(input: CreateAnnouncementInput): Promise<AnnouncementItem>;
  deleteAnnouncement(id: string): Promise<{ deleted: boolean }>;
  listRegisterCodes(): Promise<RegisterCodeItem[]>;
  createRegisterCode(maxUses?: number): Promise<RegisterCodeCreateResult>;
  updateRegisterCode(codeId: string, input: { maxUsesDelta?: number; disabled?: boolean }): Promise<RegisterCodeItem>;
  deleteRegisterCode(codeId: string): Promise<void>;
  listAdminUsers(): Promise<AdminUser[]>;
  updateUser(accountId: string, input: AdminUserUpdateInput): Promise<AdminUser>;
  updateUserBotPermissions(accountId: string, allowedBots: string[]): Promise<UserBotPermissions>;
  getTransferBridgeStatus(): Promise<TransferBridgeStatus>;
  getTransferAdminStatus(): Promise<TransferBridgeStatus>;
  updateTransferBridgeConfig(input: TransferBridgeConfigInput): Promise<TransferBridgeStatus>;
  resetTransferBridgeStats(): Promise<TransferBridgeStatus>;
  getInlineCompletionConfig(): Promise<InlineCompletionConfig>;
  updateInlineCompletionConfig(input: InlineCompletionConfigInput): Promise<InlineCompletionConfig>;
  getInlineCompletionRuntimeConfig(botAlias: string): Promise<InlineCompletionConfig>;
  requestInlineCompletion(botAlias: string, input: InlineCompletionRequest, signal?: AbortSignal): Promise<InlineCompletionResult>;
  getLanguageServerCatalog(botAlias: string, provider?: LanguageServerProviderId): Promise<LanguageServerCatalog>;
  refreshLanguageServerCatalog(): Promise<LanguageServerCatalog>;
  installLanguageServer(provider: LanguageServerProviderId, options?: LanguageServerInstallOptions): Promise<LanguageServerCatalog>;
  getEnvConfig(): Promise<EnvConfigSnapshot>;
  previewEnvConfig(input: EnvConfigPatchInput): Promise<EnvConfigPatchResult>;
  updateEnvConfig(input: EnvConfigPatchInput): Promise<EnvConfigPatchResult>;
  getNativeAgentConfig(): Promise<NativeAgentConfigPayload>;
  runNativeAgentPreflight(options?: { cwd?: string; piCommand?: string }): Promise<NativeAgentPreflightResult>;
  updateNativeAgentConfig(config: Record<string, unknown>): Promise<NativeAgentConfigPayload>;
  getCliErrorStats(filters?: CliErrorStatsFilters): Promise<CliErrorStatsResult>;
  listBots(): Promise<BotSummary[]>;
  listPlugins(refresh?: boolean): Promise<PluginSummary[]>;
  listInstallablePlugins(): Promise<InstallablePluginSummary[]>;
  installPlugin(input: string | {
    pluginId?: string;
    sourcePath?: string;
    force?: boolean;
    allowDevSourcePath?: boolean;
  }): Promise<PluginSummary>;
  uninstallPlugin(pluginId: string): Promise<void>;
  updatePlugin(pluginId: string, input: PluginUpdateInput): Promise<PluginSummary>;
  listAgents(botAlias: string): Promise<AgentListResult>;
  createAgent(botAlias: string, input: AgentInput): Promise<AgentMutationResult>;
  updateAgent(botAlias: string, agentId: string, input: AgentInput): Promise<AgentMutationResult>;
  deleteAgent(botAlias: string, agentId: string): Promise<void>;
  getClusterStatus(botAlias: string): Promise<ClusterStatus>;
  getClusterTaskStatus(botAlias: string, runId: string): Promise<ClusterTaskStatus>;
  prepareClusterSetup(botAlias: string): Promise<ClusterSetupPrepareResult>;
  updateClusterConfig(botAlias: string, input: ClusterConfigUpdateInput): Promise<ClusterConfigUpdateResult>;
  updateBotPromptPresets(botAlias: string, presets: PromptPreset[]): Promise<BotSummary>;
  updateGlobalPromptPresets(presets: PromptPreset[]): Promise<PromptPreset[]>;
  getClusterTemplates(botAlias: string): Promise<ClusterTemplateListResult>;
  getClusterBundleSchema(botAlias: string): Promise<ClusterBundleSchemaResult>;
  previewClusterTemplate(botAlias: string, templateId: string): Promise<ClusterBundlePreviewResult>;
  applyClusterTemplate(botAlias: string, templateId: string, confirmOverwriteAgents: boolean): Promise<ClusterBundleApplyResult>;
  previewClusterConfigBundle(botAlias: string, bundle: unknown): Promise<ClusterBundlePreviewResult>;
  applyClusterConfigBundle(botAlias: string, bundle: unknown, confirmOverwriteAgents: boolean): Promise<ClusterBundleApplyResult>;
  getBotOverview(botAlias: string, options?: AgentScopedOptions): Promise<BotOverview>;
  listConversations(botAlias: string, query?: string, options?: AgentScopedOptions): Promise<ConversationListResult>;
  createConversation(botAlias: string, title?: string, options?: AgentScopedOptions): Promise<ConversationSelectResult>;
  selectConversation(botAlias: string, conversationId: string, options?: AgentScopedOptions): Promise<ConversationSelectResult>;
  listFavoriteAnswers(botAlias: string, query?: string, options?: AgentScopedOptions): Promise<FavoriteAnswerListResult>;
  favoriteAnswer(botAlias: string, input: FavoriteAnswerInput, options?: AgentScopedOptions): Promise<FavoriteAnswerItem>;
  deleteFavoriteAnswer(botAlias: string, favoriteId: string, options?: AgentScopedOptions): Promise<{ deleted: boolean; favoriteId: string }>;
  deleteConversation(
    botAlias: string,
    conversationId: string,
    options?: AgentScopedOptions & { deleteNativeSession?: boolean },
  ): Promise<ConversationDeleteResult>;
  deleteAllConversations(
    botAlias: string,
    options?: AgentScopedOptions & { deleteNativeSession?: boolean },
  ): Promise<ConversationBulkDeleteResult>;
  executePlan(botAlias: string, input: PlanExecuteInput): Promise<PlanExecuteResult>;
  listMessages(botAlias: string, options?: AgentScopedOptions): Promise<ChatMessage[]>;
  listMessageDelta(botAlias: string, afterId: string, limit?: number, options?: HistoryDeltaOptions): Promise<HistoryDeltaResult>;
  getMessageTrace(botAlias: string, messageId: string, options?: AgentScopedOptions): Promise<ChatTraceDetails>;
  sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
    onTrace?: (trace: ChatTraceEvent) => void,
    options?: ChatSendOptions,
    onAgUiEvent?: (event: AgUiEvent) => void,
  ): Promise<ChatMessage>;
  replyNativeAgentPermission(
    botAlias: string,
    permissionId: string,
    options: NativeAgentPermissionReplyOptions,
  ): Promise<{ permissionId: string; approved: boolean }>;
  getNativeAgentModels(botAlias: string): Promise<NativeAgentModelsPayload>;
  updateNativeAgentModel(botAlias: string, model: string, options?: NativeAgentModelUpdateOptions): Promise<NativeAgentModelUpdateResult>;
  getNativeAgentHistoryChanges(
    botAlias: string,
    input: { conversationId: string; turnId: string; agentId?: string },
  ): Promise<NativeAgentHistoryChangesPayload>;
  getNativeAgentHistoryDiff(
    botAlias: string,
    input: { conversationId: string; turnId: string; path: string; agentId?: string },
  ): Promise<NativeAgentHistoryDiffPayload>;
  rollbackNativeAgentHistory(
    botAlias: string,
    input: { conversationId: string; targetTurnId: string; agentId?: string },
  ): Promise<NativeAgentHistoryRollbackResult>;
  getDebugProfile(botAlias: string): Promise<DebugProfile | null>;
  getDebugState(botAlias: string): Promise<DebugState>;
  getTerminalSession(ownerId: string): Promise<PersistentTerminalSnapshot>;
  rebuildTerminalSession(ownerId: string, cwd: string, shell?: string): Promise<PersistentTerminalSnapshot>;
  closeTerminalSession(ownerId: string): Promise<PersistentTerminalSnapshot>;
  getTerminalActionsConfig(botAlias: string): Promise<TerminalActionsConfig>;
  saveTerminalActionsConfig(botAlias: string, config: TerminalActionsEditableConfig, expectedMtimeNs: string): Promise<TerminalActionsConfig>;
  runTerminalAction(botAlias: string, actionId: string, input: TerminalActionRunInput): Promise<TerminalActionRunResult>;
  getCurrentPath(botAlias: string): Promise<string>;
  listFiles(botAlias: string, path?: string, options?: DirectoryListingOptions): Promise<DirectoryListing>;
  openBotWorkdir(botAlias: string): Promise<BotWorkdirOpenResult>;
  revealFileTreePath(botAlias: string, path: string): Promise<FileTreeRevealResult>;
  changeDirectory(botAlias: string, path: string): Promise<string>;
  createDirectory(botAlias: string, name: string, parentPath?: string): Promise<void>;
  createWorkdirDirectory(botAlias: string, parentPath: string, name: string): Promise<void>;
  deletePath(botAlias: string, path: string): Promise<void>;
  resolveFileOpenTarget(botAlias: string, path: string): Promise<FileOpenTarget>;
  readFile(botAlias: string, filename: string): Promise<FileReadResult>;
  readFileFull(botAlias: string, filename: string): Promise<FileReadResult>;
  openPluginView(
    botAlias: string,
    pluginId: string,
    viewId: string,
    input: Record<string, unknown>,
  ): Promise<PluginRenderResult>;
  queryPluginViewWindow(
    botAlias: string,
    pluginId: string,
    sessionId: string,
    request: PluginViewWindowRequest,
    signal?: AbortSignal,
  ): Promise<PluginViewWindowPayload>;
  disposePluginViewSession(botAlias: string, pluginId: string, sessionId: string): Promise<void>;
  invokePluginAction(botAlias: string, pluginId: string, input: PluginActionInvokeInput): Promise<PluginActionResult>;
  getPluginArtifactBlob(botAlias: string, artifactId: string): Promise<Blob>;
  downloadPluginArtifact(botAlias: string, artifactId: string, filename: string): Promise<void>;
  writeFile(botAlias: string, path: string, content: string, expectedMtimeNs?: string, encoding?: string): Promise<FileWriteResult>;
  createTextFile(botAlias: string, filename: string, content?: string, parentPath?: string): Promise<FileCreateResult>;
  renamePath(botAlias: string, path: string, newName: string): Promise<FileRenameResult>;
  copyPath(botAlias: string, path: string): Promise<FileCopyResult>;
  movePath(botAlias: string, path: string, targetParentPath: string): Promise<FileMoveResult>;
  quickOpenWorkspace(botAlias: string, query: string, limit?: number): Promise<WorkspaceQuickOpenResult>;
  searchWorkspace(botAlias: string, query: string, limit?: number, signal?: AbortSignal): Promise<WorkspaceSearchResult>;
  getWorkspaceOutline(botAlias: string, path: string): Promise<WorkspaceOutlineResult>;
  resolveCodeNavigation(
    botAlias: string,
    input: CodeNavigationRequest,
    signal?: AbortSignal,
  ): Promise<CodeNavigationResult>;
  syncWorkspaceDocuments(
    botAlias: string,
    input: WorkspaceDocumentSyncInput,
    signal?: AbortSignal,
  ): Promise<WorkspaceDocumentSyncResult>;
  closeWorkspaceDocuments(
    botAlias: string,
    input: WorkspaceDocumentCloseInput,
    signal?: AbortSignal,
  ): Promise<WorkspaceDocumentCloseResult>;
  uploadChatAttachment(botAlias: string, file: File): Promise<ChatAttachmentUploadResult>;
  deleteChatAttachment(botAlias: string, savedPath: string): Promise<ChatAttachmentDeleteResult>;
  uploadFile(botAlias: string, file: File): Promise<void>;
  downloadFile(botAlias: string, filename: string, onProgress?: (progress: FileDownloadProgress) => void): Promise<void>;
  resetSession(botAlias: string): Promise<void>;
  killTask(botAlias: string, options?: AgentScopedOptions): Promise<string>;
  restartService(): Promise<void>;
  getGitProxySettings(): Promise<GitProxySettings>;
  updateGitProxySettings(address: string): Promise<GitProxySettings>;
  getUpdateStatus(): Promise<AppUpdateStatus>;
  setUpdateEnabled(enabled: boolean): Promise<AppUpdateStatus>;
  checkForUpdate(): Promise<AppUpdateStatus>;
  downloadUpdateStream(onProgress: (event: AppUpdateDownloadProgress) => void): Promise<AppUpdateStatus>;
  downloadUpdate(): Promise<AppUpdateStatus>;
  listOfflineUpdatePackages(): Promise<OfflineUpdatePackageList>;
  prepareOfflineUpdate(path: string, version?: string): Promise<AppUpdateStatus>;
  prepareOfflineUpdateStream(
    path: string,
    version: string | undefined,
    onProgress: (event: AppUpdateDownloadProgress) => void,
  ): Promise<AppUpdateStatus>;
  getGitOverview(botAlias: string): Promise<GitOverview>;
  getGitTreeStatus(botAlias: string): Promise<GitTreeStatus>;
  getGitCommitGraph(botAlias: string, options?: GitCommitGraphOptions): Promise<GitCommitGraphPayload>;
  initGitRepository(botAlias: string): Promise<GitOverview>;
  getGitDiff(botAlias: string, path: string, staged?: boolean): Promise<GitDiffPayload>;
  stageGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult>;
  unstageGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult>;
  discardGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult>;
  discardAllGitChanges(botAlias: string): Promise<GitActionResult>;
  commitGitChanges(botAlias: string, message: string): Promise<GitActionResult>;
  fetchGitRemote(botAlias: string): Promise<GitActionResult>;
  pullGitRemote(botAlias: string): Promise<GitActionResult>;
  pushGitRemote(botAlias: string): Promise<GitActionResult>;
  stashGitChanges(botAlias: string): Promise<GitActionResult>;
  popGitStash(botAlias: string): Promise<GitActionResult>;
  listGitBranches(botAlias: string): Promise<GitBranchList>;
  createGitBranch(botAlias: string, name: string, startPoint?: string): Promise<GitBranchList>;
  switchGitBranch(botAlias: string, name: string): Promise<GitBranchList>;
  resetGitBranch(botAlias: string, commit: string, mode: GitResetMode): Promise<GitBranchResetResult>;
  listGitStashes(botAlias: string): Promise<GitStashList>;
  applyGitStash(botAlias: string, ref: string): Promise<GitActionResult>;
  dropGitStash(botAlias: string, ref: string): Promise<GitActionResult>;
  getGitIdentityConfig(botAlias: string): Promise<GitIdentityConfig>;
  updateGitIdentityConfig(botAlias: string, input: { scope: GitIdentityScope; name: string; email: string }): Promise<GitIdentityConfig>;
  getGitCommitMessageConfig(botAlias: string): Promise<GitCommitMessageCliConfig>;
  updateGitCommitMessageConfig(botAlias: string, input: GitCommitMessageCliConfigUpdateInput): Promise<GitCommitMessageCliConfig>;
  resetGitCommitMessageConfig(botAlias: string): Promise<GitCommitMessageCliConfig>;
  generateGitCommitMessage(botAlias: string): Promise<GitCommitMessageGenerateResult>;
  startGitSmartCommit(botAlias: string): Promise<GitSmartCommitJob>;
  getActiveGitSmartCommit(botAlias: string): Promise<GitSmartCommitJob | null>;
  getGitSmartCommitJob(botAlias: string, jobId: string): Promise<GitSmartCommitJob>;
  getLanChatConfig(): Promise<LanChatConfig>;
  updateLanChatConfig(input: LanChatConfigInput): Promise<LanChatConfig>;
  getLanChatStatus(): Promise<LanChatStatus>;
  listLanChatConversations(): Promise<LanChatConversation[]>;
  listLanChatMessages(conversationId: string, afterSeq?: number, limit?: number): Promise<LanChatMessage[]>;
  createLanChatPrivateConversation(targetRoomUserId: string): Promise<LanChatConversation>;
  sendLanChatMessage(conversationId: string, text: string): Promise<LanChatMessage>;
  markLanChatRead(conversationId: string, seq: number): Promise<void>;
  openLanChatSocket?(onEvent: (event: LanChatEvent) => void): () => void;
  getNotificationSettings?(): Promise<NotificationSettingsStatus>;
  sendPushPlusTest?(): Promise<NotificationTestResult>;
  subscribeNotifications?(
    onEvent: (event: WebNotificationEvent) => void,
    options?: NotificationSubscriptionOptions,
  ): NotificationSubscription;
  sendNotificationPresenceUpdate?(presence: NotificationPresenceUpdate): void;
  updateBotCli(botAlias: string, cliType: string, cliPath: string): Promise<BotSummary>;
  updateBotExecutionConfig(botAlias: string, input: BotExecutionConfigInput): Promise<BotSummary>;
  updateBotWorkdir(botAlias: string, workingDir: string, options?: UpdateBotWorkdirOptions): Promise<BotSummary>;
  addBot(input: CreateBotInput): Promise<BotSummary>;
  renameBot(botAlias: string, newAlias: string): Promise<BotSummary>;
  removeBot(botAlias: string, options?: RemoveBotOptions): Promise<RemoveBotResult>;
  startBot(botAlias: string): Promise<BotSummary>;
  stopBot(botAlias: string): Promise<BotSummary>;
  getCliParams(botAlias: string): Promise<CliParamsPayload>;
  updateCliParam(botAlias: string, key: string, value: unknown, cliType?: string): Promise<CliParamsPayload>;
  resetCliParams(botAlias: string, cliType?: string): Promise<CliParamsPayload>;
  getTunnelStatus(): Promise<TunnelSnapshot>;
  startTunnel(): Promise<TunnelSnapshot>;
  stopTunnel(): Promise<TunnelSnapshot>;
  restartTunnel(): Promise<TunnelSnapshot>;
}
