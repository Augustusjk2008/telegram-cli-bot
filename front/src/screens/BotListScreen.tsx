import { cliTypeLabel } from "../utils/cliType";
import { RemoteReconnectButton } from "../components/RemoteConnectionForm";
import { workspaceLabel } from "../services/remoteWorkspace";
import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { BotActivitySummary } from "../components/BotActivitySummary";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { getBotIdentityTextStyle } from "../utils/botVisual";
import { AgentCreateForm } from "./AgentCreateForm";
import { FleetAvatar, FleetStats, FleetStatusChip } from "./AgentManagerParts";
import "../styles/agent-manager.css";
import type { BotSummary } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { useBotManager } from "./useBotManager";
import { countBotManagerStats, isBotArchived, isBotOffline, isMainBot, } from "./botManagerModel";
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
  const [pendingDeleteAlias, setPendingDeleteAlias] = useState("");
  const [deleteHistory, setDeleteHistory] = useState(false);
  const [deleteWorkspace, setDeleteWorkspace] = useState(false);
  const [deleteWorkspaceConfirmText, setDeleteWorkspaceConfirmText] = useState("");
  const [selectedAliases, setSelectedAliases] = useState<string[]>([]);

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

  useEffect(() => {
    const available = new Set(bots.filter((bot) => canManage && !isMainBot(bot) && !isBotArchived(bot)).map((bot) => bot.alias));
    setSelectedAliases((current) => current.filter((alias) => available.has(alias)));
  }, [bots, canManage]);

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
                      {`CLI / ${cliTypeLabel(bot.cliType)}`}
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
          <AgentCreateForm
            layout="card"
            description="配置运行方式与工作区后即可创建。"
            client={client}
            bots={bots}
            savingAction={savingAction}
            onCreate={createBot}
            canManage={canManage}
            canCreateWorkdirDirectory={canCreateWorkdirDirectory}
            canRunUnsafeCli={canRunUnsafeCli}

            onCreated={onBotCreated}
          />
        </section>
      ) : null}
      </div>
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
