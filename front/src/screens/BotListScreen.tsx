import { cliTypeLabel } from "../utils/cliType";
import { RemoteWorkspacePicker } from "../components/RemoteWorkspacePicker";
import { RemoteReconnectButton } from "../components/RemoteConnectionForm";
import { workspaceLabel } from "../services/remoteWorkspace";
import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { BotActivitySummary } from "../components/BotActivitySummary";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { NativeAgentConfigFields } from "../components/NativeAgentConfigFields";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { getBotIdentityTextStyle } from "../utils/botVisual";
import { FleetAvatar, FleetStats, FleetStatusChip } from "./AgentManagerParts";
import "../styles/agent-manager.css";
import type { BotSummary, CliType, CreateBotInput } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  buildCreateDraft,
  defaultCliPathForType,
  useBotManager,
  type CreateDraft,
} from "./useBotManager";
import { countBotManagerStats, DEFAULT_NATIVE_AGENT_DRAFT, getRuntimeBackend, isBotArchived, isBotOffline, isMainBot, isNativeAgentGloballyEnabled } from "./botManagerModel";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";

const DELETE_WORKSPACE_CONFIRM_TEXT = "永久删除";

type Props = {
  client?: WebBotClient;
  onSelect: (alias: string) => void;
  onOpenBotSettings?: (alias: string) => void;
  onBotCreated?: (alias: string) => void;
  onLogout?: () => void;
  onBotsChange?: (bots: BotSummary[]) => void;
  canManage?: boolean;
  canCreateWorkdirDirectory?: boolean;
  canRunUnsafeCli?: boolean;
};

function DeleteBotDialog({
  botAlias,
  workspacePath,
  remote = false,
  deleteHistory,
  deleteWorkspace,
  workspaceConfirmText,
  busy,
  onDeleteHistoryChange,
  onDeleteWorkspaceChange,
  onWorkspaceConfirmTextChange,
  onCancel,
  onConfirm,
}: {
  botAlias: string;
  workspacePath: string;
  remote?: boolean;
  deleteHistory: boolean;
  deleteWorkspace: boolean;
  workspaceConfirmText: string;
  busy: boolean;
  onDeleteHistoryChange: (value: boolean) => void;
  onDeleteWorkspaceChange: (value: boolean) => void;
  onWorkspaceConfirmTextChange: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const workspaceConfirmMatched = workspaceConfirmText.trim() === DELETE_WORKSPACE_CONFIRM_TEXT;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay-backdrop-50)] p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-bot-dialog-title"
        className="w-full max-w-md rounded-2xl bg-[var(--surface)] p-5 shadow-[var(--shadow-card)]"
      >
        <h2 id="delete-bot-dialog-title" className="text-base font-semibold">删除智能体 {botAlias}</h2>
        <label className="mt-4 flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={deleteWorkspace || deleteHistory}
            onChange={(event) => onDeleteHistoryChange(event.target.checked)}
            disabled={busy || deleteWorkspace}
            className="mt-0.5 h-4 w-4 rounded border-[var(--border)]"
          />
          <span>同时删除历史记录（包含所有子 agents）</span>
        </label>
        <label className="mt-3 flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={deleteWorkspace}
            onChange={(event) => onDeleteWorkspaceChange(event.target.checked)}
            disabled={busy || remote}
            className="mt-0.5 h-4 w-4 rounded border-[var(--border)]"
          />
          <span>{remote ? "远程工作区不支持从此处删除" : "同时删除工作区和所有记录"}</span>
        </label>
        {deleteWorkspace ? (
          <div className="mt-3 space-y-3 rounded-lg border border-[var(--feedback-error-border-light)] bg-[var(--feedback-error-background-subtle)] px-3 py-2 text-sm text-[var(--feedback-error-text-stronger)]">
            <p>将删除该 Bot 的磁盘工作区目录，且会一并删除历史记录和 session 记录。</p>
            <div className="break-all font-mono text-xs">{workspacePath || "未设置工作区"}</div>
            <label className="block text-sm">
              <span>输入“{DELETE_WORKSPACE_CONFIRM_TEXT}”确认</span>
              <input
                aria-label="输入永久删除确认词"
                value={workspaceConfirmText}
                onChange={(event) => onWorkspaceConfirmTextChange(event.target.value)}
                className="mt-2 h-9 w-full rounded-md border border-[var(--feedback-error-border-light)] bg-[var(--access-badge-background)] px-3 text-sm text-[var(--feedback-error-text-emphasis)] outline-none focus:border-[var(--feedback-error-border)]"
                autoFocus
              />
            </label>
          </div>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy || (deleteWorkspace && !workspaceConfirmMatched)}
            className="rounded-lg border border-[var(--feedback-error-border-light)] px-3 py-2 text-sm text-[var(--feedback-error-text-deep)] hover:bg-[var(--feedback-error-background-subtle)] disabled:opacity-60"
          >
            {busy ? "删除中..." : deleteWorkspace ? "彻底删除" : "删除"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function BotListScreen({
  client = new MockWebBotClient(),
  onSelect,
  onOpenBotSettings,
  onBotCreated,
  onLogout,
  onBotsChange,
  canManage = true,
  canCreateWorkdirDirectory = true,
  canRunUnsafeCli = false,
}: Props) {
  const [renamingAlias, setRenamingAlias] = useState("");
  const [renameDrafts, setRenameDrafts] = useState<Record<string, string>>({});
  const [showWorkdirPicker, setShowWorkdirPicker] = useState(false);
  const [pendingDeleteAlias, setPendingDeleteAlias] = useState("");
  const [deleteHistory, setDeleteHistory] = useState(false);
  const [deleteWorkspace, setDeleteWorkspace] = useState(false);
  const [deleteWorkspaceConfirmText, setDeleteWorkspaceConfirmText] = useState("");
  const [selectedAliases, setSelectedAliases] = useState<string[]>([]);
  const [nativeAgentFeatureEnabled, setNativeAgentFeatureEnabled] = useState<boolean | null>(null);
  const {
    bots,
    loading,
    error,
    notice,
    savingAction,
    setError,
    createBot,
    toggleBot,
    runBatchToggle,
    archiveBot,
    unarchiveBot,
    renameBot,
    deleteBot,
  } = useBotManager({ client, onBotsChange, includeArchived: canManage });
  const [remoteCreate, setRemoteCreate] = useState(false);
  const [createDraft, setCreateDraft] = useState<CreateDraft>(() => buildCreateDraft());

  const directoryBrowserAlias = bots.find((bot) => bot.isMain || bot.alias === "main")?.alias || bots[0]?.alias || "main";

  useEffect(() => {
    if (bots.length === 0) {
      return;
    }
    setCreateDraft((prev) => {
      const userEditedPath = prev.cliPath.trim() && prev.cliPath.trim() !== defaultCliPathForType(prev.cliType);
      if (prev.alias.trim() || prev.workingDir.trim() || userEditedPath) {
        return prev;
      }
      return { ...prev, cliPath: buildCreateDraft(prev.cliType, bots).cliPath };
    });
  }, [bots]);

  useEffect(() => {
    const available = new Set(bots.filter((bot) => canManage && !isMainBot(bot) && !isBotArchived(bot)).map((bot) => bot.alias));
    setSelectedAliases((current) => current.filter((alias) => available.has(alias)));
  }, [bots, canManage]);

  useEffect(() => {
    let cancelled = false;
    void client.getEnvConfig()
      .then((snapshot) => {
        if (cancelled) return;
        setNativeAgentFeatureEnabled(isNativeAgentGloballyEnabled(snapshot));
      })
      .catch(() => {
        if (cancelled) return;
        setNativeAgentFeatureEnabled(null);
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  useEffect(() => {
    if (nativeAgentFeatureEnabled === false && createDraft.runtimeBackend === "native_agent") {
      setCreateDraft((prev) => ({
        ...prev,
        runtimeBackend: "cli",
        supportedExecutionModes: ["cli"],
        defaultExecutionMode: "cli",
      }));
    }
  }, [createDraft.runtimeBackend, nativeAgentFeatureEnabled]);

  useEffect(() => {
    if (!canRunUnsafeCli && createDraft.bypassApprovalAndSandbox) {
      setCreateDraft((prev) => ({ ...prev, bypassApprovalAndSandbox: false }));
    }
  }, [canRunUnsafeCli, createDraft.bypassApprovalAndSandbox]);

  async function handleCreateBot() {
    const created = await createBot(createDraft);
    if (created) {
      setCreateDraft(buildCreateDraft(createDraft.cliType, bots));
      setRemoteCreate(false);
      onBotCreated?.(created.alias);
    }
  }

  async function saveRename(bot: BotSummary) {
    const renamed = await renameBot(bot, renameDrafts[bot.alias] || "");
    if (renamed) {
      setRenamingAlias("");
      setRenameDrafts((prev) => {
        const next = { ...prev };
        delete next[bot.alias];
        return next;
      });
    }
  }

  async function handleBatchToggle(target: "start" | "stop") {
    const selected = bots.filter((bot) => selectedAliases.includes(bot.alias));
    const updated = await runBatchToggle(selected, target);
    if (updated) setSelectedAliases([]);
  }

  async function confirmDelete() {
    if (!pendingDeleteAlias) {
      return;
    }
    const bot = bots.find((item) => item.alias === pendingDeleteAlias);
    if (!bot) {
      setPendingDeleteAlias("");
      setDeleteHistory(false);
      setDeleteWorkspace(false);
      setDeleteWorkspaceConfirmText("");
      return;
    }
    const removed = await deleteBot(bot, { deleteHistory: deleteHistory || deleteWorkspace, deleteWorkspace });
    if (removed) {
      setPendingDeleteAlias("");
      setDeleteHistory(false);
      setDeleteWorkspace(false);
      setDeleteWorkspaceConfirmText("");
    }
  }

  const nativeAgentOptionVisible = nativeAgentFeatureEnabled !== false || createDraft.runtimeBackend === "native_agent";

  return (
    <main data-ui-density="compact" className="am-screen am-mobile orbit-shell">
      <header className="am-cover am-cover--compact orbit-cover">
        <div className="orbit-cover-art">
          <ThemeIllustrationLayer surface="agentManager" />
        </div>
        <div className="am-cover-row">
          <div>
            <p className="am-cover-eyebrow">ORBIT 舰队</p>
            <h1 className="am-cover-title">智能体管理</h1>
          </div>
          {onLogout ? (
            <button
              type="button"
              aria-label="退出登录"
              title="退出登录"
              onClick={onLogout}
              className="orbit-btn orbit-btn--icon am-glass-btn shrink-0"
            >
              <LogOut className="h-4 w-4" />
            </button>
          ) : null}
        </div>
        <div className="am-cover-main">
          <FleetStats stats={countBotManagerStats(bots)} />
        </div>
      </header>

      <div className="am-mobile-body">
      {error ? (
        <div role="alert" className="am-banner" data-tone="danger">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="am-banner" data-tone="success">
          {notice}
        </div>
      ) : null}

      {canManage && bots.some((bot) => !isMainBot(bot) && !isBotArchived(bot)) ? (
        <section aria-label="批量操作" className="am-mobile-bulk orbit-island">
          <span>已选择 {selectedAliases.length} 个智能体</span>
          <button type="button" onClick={() => void handleBatchToggle("start")} disabled={selectedAliases.length === 0 || savingAction !== ""} className="orbit-btn orbit-btn--ghost orbit-btn--sm">批量启动</button>
          <button type="button" onClick={() => void handleBatchToggle("stop")} disabled={selectedAliases.length === 0 || savingAction !== ""} className="orbit-btn orbit-btn--ghost orbit-btn--sm">批量停止</button>
          <button type="button" onClick={() => setSelectedAliases([])} disabled={selectedAliases.length === 0 || savingAction !== ""} className="orbit-btn orbit-btn--ghost orbit-btn--sm">清除选择</button>
        </section>
      ) : null}

      {loading ? (
        <div className="am-empty">加载中...</div>
      ) : bots.length === 0 ? (
        <div className="am-empty">暂无智能体</div>
      ) : (
        <div className="grid gap-2.5">
          {bots.map((bot) => {
            const isMain = isMainBot(bot);
            const isRenaming = renamingAlias === bot.alias;
            const isArchived = isBotArchived(bot);
            const isOffline = isBotOffline(bot);
            const servicePillStatus = isOffline ? "offline" : "online";
            return (
              <section
                key={bot.alias}
                data-offline={isOffline ? "true" : undefined}
                className="am-card orbit-island orbit-island--reading"
              >
                <div className="am-card-head">
                  {canManage && !isMain && !isArchived ? (
                    <input
                      type="checkbox"
                      aria-label={`选择 ${bot.alias}`}
                      checked={selectedAliases.includes(bot.alias)}
                      onChange={(event) => setSelectedAliases((current) => event.target.checked ? [...new Set([...current, bot.alias])] : current.filter((alias) => alias !== bot.alias))}
                      className="am-check shrink-0"
                    />
                  ) : null}
                  <FleetAvatar alias={bot.alias} />
                  <div className="am-card-meta flex-1">
                    <div className="am-name-line">
                      <h3 className="am-card-title">{bot.alias}</h3>
                      {isMain ? <span className="am-tag">主</span> : null}
                      {bot.remoteWorkspace ? <span className="am-tag">远程</span> : null}
                      {isArchived ? <span className="am-tag" data-tone="warning">已归档</span> : null}
                      {bot.canOperate === false ? <span className="am-tag" data-tone="restricted">无权限 · 只读</span> : null}
                    </div>
                    <div className="am-type">
                      <span aria-hidden="true" className="am-type-mark" style={getBotIdentityTextStyle(bot.cliType)} />
                      {getRuntimeBackend(bot) === "cli" ? `CLI / ${cliTypeLabel(bot.cliType)}` : "原生 agent"}
                    </div>
                  </div>
                  <div className="am-status shrink-0 justify-end">
                    {bot.status === "unread" ? <FleetStatusChip status="unread" /> : null}
                    <FleetStatusChip status={servicePillStatus} />
                  </div>
                </div>
                <div className="am-path" title={workspaceLabel(bot)}>
                  {workspaceLabel(bot) || "未设置"}
                </div>
                {bot.remoteWorkspace && <RemoteReconnectButton client={client} botAlias={bot.alias} remote={bot.remoteWorkspace} disabled={bot.canOperate === false} />}
                <BotActivitySummary bot={bot} />

                <div
                  data-testid={`bot-actions-${bot.alias}`}
                  className="am-card-actions"
                >
                  <button
                    type="button"
                    aria-label={isOffline ? `${bot.alias} 当前离线，不可进入` : `进入 ${bot.alias}`}
                    onClick={() => {
                      if (isOffline) {
                        return;
                      }
                      onSelect(bot.alias);
                    }}
                    disabled={isOffline}
                    className={isOffline ? "orbit-btn orbit-btn--secondary orbit-btn--sm am-tone-danger cursor-not-allowed" : "orbit-btn orbit-btn--primary orbit-btn--sm"}
                  >
                    {isOffline ? "不可进入" : "进入"}
                  </button>
                  {onOpenBotSettings ? (
                    <button
                      type="button"
                      aria-label={`打开 ${bot.alias} 设置`}
                      onClick={() => onOpenBotSettings(bot.alias)}
                      className="orbit-btn orbit-btn--secondary orbit-btn--sm"
                    >
                      打开设置
                    </button>
                  ) : null}
                  {canManage && !isMain ? (
                    <>
                      <button
                        type="button"
                        aria-label={isArchived ? `取消归档 ${bot.alias}` : isOffline ? `启动 ${bot.alias}` : `停止 ${bot.alias}`}
                        onClick={() => void (isArchived ? unarchiveBot(bot) : toggleBot(bot))}
                        disabled={savingAction !== ""}
                        className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                      >
                        {savingAction === `${bot.alias}:archive`
                          ? "处理中..."
                          : isArchived ? "取消归档" : savingAction === `${bot.alias}:toggle` ? "处理中..." : isOffline ? "启动" : "停止"}
                      </button>
                      {!isArchived ? (
                        <button
                          type="button"
                          aria-label={`归档 ${bot.alias}`}
                          onClick={() => void archiveBot(bot)}
                          disabled={savingAction !== ""}
                          className="orbit-btn orbit-btn--ghost orbit-btn--sm am-tone-warning"
                        >
                          归档
                        </button>
                      ) : null}
                      <button
                        type="button"
                        aria-label={`重命名 ${bot.alias}`}
                        onClick={() => {
                          setRenamingAlias((prev) => prev === bot.alias ? "" : bot.alias);
                          setRenameDrafts((prev) => ({ ...prev, [bot.alias]: bot.alias }));
                        }}
                        disabled={savingAction !== "" || isArchived}
                        className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                      >
                        改名
                      </button>
                      <button
                        type="button"
                        aria-label={`删除 ${bot.alias}`}
                        onClick={() => {
                          setPendingDeleteAlias(bot.alias);
                          setDeleteHistory(false);
                          setDeleteWorkspace(false);
                          setDeleteWorkspaceConfirmText("");
                        }}
                        disabled={savingAction !== ""}
                        className="orbit-btn orbit-btn--ghost orbit-btn--sm am-tone-danger"
                      >
                        删除
                      </button>
                    </>
                  ) : null}
                </div>

                {isRenaming ? (
                  <div className="am-rename">
                    <input
                      aria-label={`${bot.alias} 新别名`}
                      type="text"
                      value={renameDrafts[bot.alias] || ""}
                      onChange={(event) => setRenameDrafts((prev) => ({ ...prev, [bot.alias]: event.target.value }))}
                      className="orbit-field"
                    />
                    <button
                      type="button"
                      aria-label={`保存别名 ${bot.alias}`}
                      onClick={() => void saveRename(bot)}
                      disabled={savingAction !== ""}
                      className="orbit-btn orbit-btn--primary"
                    >
                      {savingAction === `${bot.alias}:rename` ? "保存中..." : "保存别名"}
                    </button>
                  </div>
                ) : null}
              </section>
            );
          })}
        </div>
      )}

      {canManage ? (
        <section className="am-mobile-section orbit-island orbit-island--reading">
        <h2>新增智能体</h2>
        <div className="space-y-3">
          <input
            aria-label="新智能体别名"
            type="text"
            value={createDraft.alias}
            onChange={(event) => setCreateDraft((prev) => ({ ...prev, alias: event.target.value }))}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
            placeholder="team3"
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="text-[var(--muted)]">运行后端</span>
              <select
                aria-label="运行后端"
                value={createDraft.runtimeBackend}
                onChange={(event) => {
                  const runtimeBackend = event.target.value as CreateDraft["runtimeBackend"];
                  setCreateDraft((prev) => ({
                    ...prev,
                    runtimeBackend,
                    supportedExecutionModes: [runtimeBackend],
                    defaultExecutionMode: runtimeBackend,
                  }));
                }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
              >
                <option value="cli">CLI</option>
                {nativeAgentOptionVisible && createDraft.cliType !== "deepseek" ? <option value="native_agent">原生 agent</option> : null}
              </select>
              {nativeAgentFeatureEnabled === false ? (
                <p className="text-xs text-[var(--muted)]">原生 agent 全局未启用</p>
              ) : null}
            </label>
          </div>
          {createDraft.runtimeBackend === "cli" ? (
            <div className="grid grid-cols-2 gap-3">
              <label className="space-y-1 text-sm">
                <span className="text-[var(--muted)]">新智能体 CLI 类型</span>
                <select
                  aria-label="新智能体 CLI 类型"
                  value={createDraft.cliType}
                  onChange={(event) => {
                    const cliType = event.target.value as CliType;
                    if (cliType === "deepseek") setRemoteCreate(false);
                    setCreateDraft((prev) => ({ ...prev, cliType, cliPath: buildCreateDraft(cliType, bots).cliPath, ...(cliType === "deepseek" ? { remoteWorkspace: undefined, bypassApprovalAndSandbox: false } : {}) }));
                  }}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                >
                  <option value="codex">codex</option>
                  <option value="codex_server">codex server</option>
                  <option value="claude">claude</option>
                  <option value="antigravity">Antigravity CLI</option>
                  <option value="deepseek">DeepSeek Harness</option>
                </select>
              </label>
            </div>
          ) : null}
          {createDraft.runtimeBackend === "cli" ? (
            <input
              aria-label="新智能体 CLI 路径"
              type="text"
              value={createDraft.cliPath}
              onChange={(event) => setCreateDraft((prev) => ({ ...prev, cliPath: event.target.value }))}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
              placeholder={defaultCliPathForType(createDraft.cliType)}
            />
          ) : null}
          {createDraft.runtimeBackend === "cli" && createDraft.cliType !== "deepseek" ? (
            <label className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm">
              <input
                type="checkbox"
                aria-label="新智能体默认绕过审批和沙箱"
                checked={canRunUnsafeCli ? Boolean(createDraft.bypassApprovalAndSandbox) : false}
                onChange={(event) => setCreateDraft((prev) => ({
                  ...prev,
                  bypassApprovalAndSandbox: canRunUnsafeCli ? event.target.checked : false,
                }))}
                disabled={!canManage || !canRunUnsafeCli || savingAction !== ""}
                className="mt-0.5 h-4 w-4 rounded border-[var(--border)]"
              />
              <span>默认绕过审批和沙箱</span>
            </label>
          ) : null}
          {createDraft.runtimeBackend === "native_agent" ? (
            <NativeAgentConfigFields
              provider={createDraft.nativeAgent?.provider || DEFAULT_NATIVE_AGENT_DRAFT.provider}
              model={createDraft.nativeAgent?.model || DEFAULT_NATIVE_AGENT_DRAFT.model}
              piAgent={createDraft.nativeAgent?.piAgent || DEFAULT_NATIVE_AGENT_DRAFT.piAgent}
              baseUrl={createDraft.nativeAgent?.baseUrl || DEFAULT_NATIVE_AGENT_DRAFT.baseUrl}
              apiKey={createDraft.nativeAgent?.apiKey || ""}
              disabled={!canManage || savingAction !== ""}
              onNativeAgentChange={(patch) => setCreateDraft((prev) => ({
                ...prev,
                nativeAgent: {
                  ...DEFAULT_NATIVE_AGENT_DRAFT,
                  ...(prev.nativeAgent || {}),
                  ...patch,
                },
              }))}
            />
          ) : null}
          <label className="block text-sm">工作区位置<select aria-label="工作区位置" className="ml-2 rounded border border-[var(--border)] bg-[var(--surface)] p-2" value={remoteCreate ? "remote" : "local"} onChange={(e) => { setRemoteCreate(e.target.value === "remote"); setCreateDraft((prev) => ({ ...prev, remoteWorkspace: undefined })); }}><option value="local">本地</option><option value="remote" disabled={createDraft.cliType === "deepseek"}>远程 SSH（Linux / Windows）</option></select></label>
          {remoteCreate ? <RemoteWorkspacePicker client={client} onPick={(remote) => setCreateDraft((prev) => ({ ...prev, remoteWorkspace: { connectionId: remote.connectionId, root: remote.root } }))} /> : (
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              aria-label="新智能体工作目录"
              type="text"
              value={createDraft.workingDir}
              onChange={(event) => setCreateDraft((prev) => ({ ...prev, workingDir: event.target.value }))}
              className="w-full flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
              placeholder="/srv/telegram-cli-bridge/team3"
            />
            <button
              type="button"
              aria-label="浏览新智能体工作目录"
              onClick={() => setShowWorkdirPicker(true)}
              disabled={savingAction !== ""}
              className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              浏览目录
            </button>
          </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => void handleCreateBot()}
          disabled={savingAction !== "" || (remoteCreate && !createDraft.remoteWorkspace)}
          className="orbit-btn orbit-btn--primary justify-self-start"
        >
          {savingAction === "create" ? "创建中..." : "创建智能体"}
        </button>
        </section>
      ) : null}
      </div>
      {showWorkdirPicker ? (
        <DirectoryPickerDialog
          title="选择工作目录"
          botAlias={directoryBrowserAlias}
          client={client}
          initialPath={createDraft.workingDir}
          mutateBrowseState={false}
          mode="workdir"
          canCreateDirectory={canCreateWorkdirDirectory}
          onPick={(workingDir) => setCreateDraft((prev) => ({ ...prev, workingDir }))}
          onClose={() => setShowWorkdirPicker(false)}
        />
      ) : null}
      {pendingDeleteAlias ? (
        <DeleteBotDialog
          botAlias={pendingDeleteAlias}
          remote={Boolean(bots.find((item) => item.alias === pendingDeleteAlias)?.remoteWorkspace)}
          workspacePath={bots.find((item) => item.alias === pendingDeleteAlias)?.workingDir || ""}
          deleteHistory={deleteHistory}
          deleteWorkspace={deleteWorkspace}
          workspaceConfirmText={deleteWorkspaceConfirmText}
          busy={savingAction === `${pendingDeleteAlias}:delete`}
          onDeleteHistoryChange={setDeleteHistory}
          onDeleteWorkspaceChange={(value) => {
            setDeleteWorkspace(value);
            if (value) {
              setDeleteHistory(true);
            }
            setDeleteWorkspaceConfirmText("");
          }}
          onWorkspaceConfirmTextChange={setDeleteWorkspaceConfirmText}
          onCancel={() => {
            if (savingAction === `${pendingDeleteAlias}:delete`) {
              return;
            }
            setPendingDeleteAlias("");
            setDeleteHistory(false);
            setDeleteWorkspace(false);
            setDeleteWorkspaceConfirmText("");
          }}
          onConfirm={() => void confirmDelete()}
        />
      ) : null}
    </main>
  );
}
