import type {
  BotOverview,
  BotSummary,
  AgentInput,
  AgentListResult,
  AgentMutationResult,
  AgentScopedOptions,
  ChatMessage,
  ChatStatusUpdate,
  ChatTraceDetails,
  ChatTraceEvent,
  AssistantAdminAuditResult,
  AssistantDiagnosticsFilters,
  AssistantMemoryBulkInvalidateResult,
  AssistantProposal,
  AssistantProposalDetail,
  AssistantPerfDiagnostics,
  AssistantMemoryEvalCase,
  AssistantMemoryEvalReport,
  AssistantMemoryEvalRun,
  AssistantMemoryInvalidateResult,
  AssistantMemoryReindexResult,
  AssistantMemorySearchOptions,
  AssistantMemorySearchResult,
  AssistantPatchGenerationHandlers,
  AssistantPatchMetadata,
  AssistantUpgradeApplyLog,
  AssistantUpgradeApplyResult,
  AssistantUpgradeDryRunResult,
  AssistantUpgradeTarget,
  AssistantCronJob,
  AssistantCronRun,
  AssistantCronRunRequestResult,
  CreateAssistantCronJobInput,
  UpdateAssistantCronJobInput,
  CliParamsPayload,
  CreateBotInput,
  DebugProfile,
  DebugState,
  DirectoryListing,
  FileOpenTarget,
  FileTreeRevealResult,
  FileCopyResult,
  FileCreateResult,
  FileMoveResult,
  FileReadResult,
  FileRenameResult,
  FileWriteResult,
  AvatarAsset,
  AppUpdateDownloadProgress,
  AppUpdateStatus,
  GitActionResult,
  GitBlamePayload,
  GitBranchList,
  GitDiffPayload,
  GitProxySettings,
  GitOverview,
  GitStashList,
  GitTreeStatus,
  ChatAttachmentUploadResult,
  ChatAttachmentDeleteResult,
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
  ConversationSelectResult,
  HistoryDeltaResult,
  PublicHostInfo,
  PluginViewWindowRequest,
  PluginViewWindowPayload,
  RemoveBotOptions,
  InstallablePluginSummary,
  PluginRenderResult,
  PluginSummary,
  PluginUpdateInput,
  PluginActionInvokeInput,
  PluginActionResult,
  RegisterCodeCreateResult,
  RegisterCodeItem,
  SessionState,
  PersistentTerminalSnapshot,
  TerminalActionRunInput,
  TerminalActionRunResult,
  TerminalActionsConfig,
  TerminalActionsEditableConfig,
  TunnelSnapshot,
  UpdateBotWorkdirOptions,
  WorkspaceDefinitionResult,
  WorkspaceOutlineResult,
  WorkspaceQuickOpenResult,
  WorkspaceSearchResult,
} from "./types";

export interface WebBotClient {
  getPublicHostInfo(): Promise<PublicHostInfo>;
  login(input: { username: string; password: string } | string): Promise<SessionState>;
  register(input: { username: string; password: string; registerCode: string }): Promise<SessionState>;
  loginGuest(): Promise<SessionState>;
  restoreSession(token?: string): Promise<SessionState>;
  logout(): Promise<void>;
  listRegisterCodes(): Promise<RegisterCodeItem[]>;
  createRegisterCode(maxUses?: number): Promise<RegisterCodeCreateResult>;
  updateRegisterCode(codeId: string, input: { maxUsesDelta?: number; disabled?: boolean }): Promise<RegisterCodeItem>;
  deleteRegisterCode(codeId: string): Promise<void>;
  listBots(): Promise<BotSummary[]>;
  listPlugins(refresh?: boolean): Promise<PluginSummary[]>;
  listInstallablePlugins(): Promise<InstallablePluginSummary[]>;
  installPlugin(input: string | { pluginId?: string; sourcePath?: string }): Promise<PluginSummary>;
  updatePlugin(pluginId: string, input: PluginUpdateInput): Promise<PluginSummary>;
  listAgents(botAlias: string): Promise<AgentListResult>;
  createAgent(botAlias: string, input: AgentInput): Promise<AgentMutationResult>;
  updateAgent(botAlias: string, agentId: string, input: AgentInput): Promise<AgentMutationResult>;
  deleteAgent(botAlias: string, agentId: string): Promise<void>;
  getClusterStatus(botAlias: string): Promise<ClusterStatus>;
  getClusterTaskStatus(botAlias: string, runId: string): Promise<ClusterTaskStatus>;
  prepareClusterSetup(botAlias: string): Promise<ClusterSetupPrepareResult>;
  updateClusterConfig(botAlias: string, input: ClusterConfigUpdateInput): Promise<ClusterConfigUpdateResult>;
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
  listMessages(botAlias: string, options?: AgentScopedOptions): Promise<ChatMessage[]>;
  listMessageDelta(botAlias: string, afterId: string, limit?: number, options?: AgentScopedOptions): Promise<HistoryDeltaResult>;
  getMessageTrace(botAlias: string, messageId: string, options?: AgentScopedOptions): Promise<ChatTraceDetails>;
  sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
    onTrace?: (trace: ChatTraceEvent) => void,
    options?: ChatSendOptions,
  ): Promise<ChatMessage>;
  getDebugProfile(botAlias: string): Promise<DebugProfile | null>;
  getDebugState(botAlias: string): Promise<DebugState>;
  getTerminalSession(ownerId: string): Promise<PersistentTerminalSnapshot>;
  rebuildTerminalSession(ownerId: string, cwd: string, shell?: string): Promise<PersistentTerminalSnapshot>;
  closeTerminalSession(ownerId: string): Promise<PersistentTerminalSnapshot>;
  getTerminalActionsConfig(botAlias: string): Promise<TerminalActionsConfig>;
  saveTerminalActionsConfig(botAlias: string, config: TerminalActionsEditableConfig, expectedMtimeNs: string): Promise<TerminalActionsConfig>;
  runTerminalAction(botAlias: string, actionId: string, input: TerminalActionRunInput): Promise<TerminalActionRunResult>;
  getCurrentPath(botAlias: string): Promise<string>;
  listFiles(botAlias: string, path?: string): Promise<DirectoryListing>;
  revealFileTreePath(botAlias: string, path: string): Promise<FileTreeRevealResult>;
  changeDirectory(botAlias: string, path: string): Promise<string>;
  createDirectory(botAlias: string, name: string, parentPath?: string): Promise<void>;
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
  downloadPluginArtifact(botAlias: string, artifactId: string, filename: string): Promise<void>;
  writeFile(botAlias: string, path: string, content: string, expectedMtimeNs?: string, encoding?: string): Promise<FileWriteResult>;
  createTextFile(botAlias: string, filename: string, content?: string, parentPath?: string): Promise<FileCreateResult>;
  renamePath(botAlias: string, path: string, newName: string): Promise<FileRenameResult>;
  copyPath(botAlias: string, path: string): Promise<FileCopyResult>;
  movePath(botAlias: string, path: string, targetParentPath: string): Promise<FileMoveResult>;
  quickOpenWorkspace(botAlias: string, query: string, limit?: number): Promise<WorkspaceQuickOpenResult>;
  searchWorkspace(botAlias: string, query: string, limit?: number, signal?: AbortSignal): Promise<WorkspaceSearchResult>;
  getWorkspaceOutline(botAlias: string, path: string): Promise<WorkspaceOutlineResult>;
  resolveWorkspaceDefinition(
    botAlias: string,
    input: { path: string; line: number; column: number; symbol?: string },
  ): Promise<WorkspaceDefinitionResult>;
  uploadChatAttachment(botAlias: string, file: File): Promise<ChatAttachmentUploadResult>;
  deleteChatAttachment(botAlias: string, savedPath: string): Promise<ChatAttachmentDeleteResult>;
  uploadFile(botAlias: string, file: File): Promise<void>;
  downloadFile(botAlias: string, filename: string): Promise<void>;
  resetSession(botAlias: string): Promise<void>;
  killTask(botAlias: string): Promise<string>;
  restartService(): Promise<void>;
  getGitProxySettings(): Promise<GitProxySettings>;
  updateGitProxySettings(address: string): Promise<GitProxySettings>;
  getUpdateStatus(): Promise<AppUpdateStatus>;
  setUpdateEnabled(enabled: boolean): Promise<AppUpdateStatus>;
  checkForUpdate(): Promise<AppUpdateStatus>;
  downloadUpdateStream(onProgress: (event: AppUpdateDownloadProgress) => void): Promise<AppUpdateStatus>;
  downloadUpdate(): Promise<AppUpdateStatus>;
  getGitOverview(botAlias: string): Promise<GitOverview>;
  getGitTreeStatus(botAlias: string): Promise<GitTreeStatus>;
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
  listGitStashes(botAlias: string): Promise<GitStashList>;
  applyGitStash(botAlias: string, ref: string): Promise<GitActionResult>;
  dropGitStash(botAlias: string, ref: string): Promise<GitActionResult>;
  getGitBlame(botAlias: string, path: string): Promise<GitBlamePayload>;
  updateBotCli(botAlias: string, cliType: string, cliPath: string): Promise<BotSummary>;
  updateBotWorkdir(botAlias: string, workingDir: string, options?: UpdateBotWorkdirOptions): Promise<BotSummary>;
  updateBotAvatar(botAlias: string, avatarName: string): Promise<BotSummary>;
  addBot(input: CreateBotInput): Promise<BotSummary>;
  renameBot(botAlias: string, newAlias: string): Promise<BotSummary>;
  removeBot(botAlias: string, options?: RemoveBotOptions): Promise<void>;
  startBot(botAlias: string): Promise<BotSummary>;
  stopBot(botAlias: string): Promise<BotSummary>;
  listAssistantProposals(botAlias: string, status?: string): Promise<AssistantProposal[]>;
  listAssistantUpgradeTargets(botAlias: string): Promise<AssistantUpgradeTarget[]>;
  getAssistantProposal(botAlias: string, proposalId: string): Promise<AssistantProposalDetail>;
  getAssistantProposalApplyLog(botAlias: string, proposalId: string): Promise<AssistantUpgradeApplyLog>;
  approveAssistantProposal(botAlias: string, proposalId: string): Promise<AssistantProposal>;
  generateAssistantProposalPatch(
    botAlias: string,
    proposalId: string,
    input: { targetAlias: string; regenerate?: boolean },
  ): Promise<AssistantPatchMetadata>;
  generateAssistantProposalPatchStream(
    botAlias: string,
    proposalId: string,
    input: { targetAlias: string; regenerate?: boolean },
    handlers?: AssistantPatchGenerationHandlers,
  ): Promise<AssistantPatchMetadata>;
  approveAssistantProposalPatch(botAlias: string, proposalId: string): Promise<AssistantPatchMetadata>;
  rejectAssistantProposal(botAlias: string, proposalId: string): Promise<AssistantProposal>;
  applyAssistantUpgrade(botAlias: string, proposalId: string): Promise<AssistantUpgradeApplyResult>;
  dryRunAssistantUpgrade(botAlias: string, proposalId: string): Promise<AssistantUpgradeDryRunResult>;
  searchAssistantMemories(botAlias: string, query: string, options?: AssistantMemorySearchOptions): Promise<AssistantMemorySearchResult>;
  bulkInvalidateAssistantMemories(botAlias: string, memoryIds: string[], reason: string): Promise<AssistantMemoryBulkInvalidateResult>;
  invalidateAssistantMemory(
    botAlias: string,
    memoryId: string,
    reason: string,
  ): Promise<AssistantMemoryInvalidateResult>;
  reindexAssistantMemory(botAlias: string, options?: { userId?: number; force?: boolean }): Promise<AssistantMemoryReindexResult>;
  runAssistantMemoryEval(
    botAlias: string,
    input: { userId?: number; cases: AssistantMemoryEvalCase[] },
  ): Promise<AssistantMemoryEvalRun>;
  listAssistantMemoryEvalReports(botAlias: string, limit?: number): Promise<AssistantMemoryEvalReport[]>;
  getAssistantDiagnostics(botAlias: string, filters?: AssistantDiagnosticsFilters): Promise<AssistantPerfDiagnostics>;
  listAssistantCronJobs(botAlias: string): Promise<AssistantCronJob[]>;
  createAssistantCronJob(botAlias: string, input: CreateAssistantCronJobInput): Promise<AssistantCronJob>;
  updateAssistantCronJob(botAlias: string, jobId: string, input: UpdateAssistantCronJobInput): Promise<AssistantCronJob>;
  deleteAssistantCronJob(botAlias: string, jobId: string): Promise<void>;
  runAssistantCronJob(botAlias: string, jobId: string): Promise<AssistantCronRunRequestResult>;
  listAssistantCronRuns(botAlias: string, jobId: string, limit?: number): Promise<AssistantCronRun[]>;
  listAssistantAdminAudit(
    botAlias: string,
    filters?: { limit?: number; action?: string; resource?: string; status?: "ok" | "failed" | "" },
  ): Promise<AssistantAdminAuditResult>;
  listAvatarAssets(): Promise<AvatarAsset[]>;
  getCliParams(botAlias: string): Promise<CliParamsPayload>;
  updateCliParam(botAlias: string, key: string, value: unknown, cliType?: string): Promise<CliParamsPayload>;
  resetCliParams(botAlias: string, cliType?: string): Promise<CliParamsPayload>;
  getTunnelStatus(): Promise<TunnelSnapshot>;
  startTunnel(): Promise<TunnelSnapshot>;
  stopTunnel(): Promise<TunnelSnapshot>;
  restartTunnel(): Promise<TunnelSnapshot>;
}
