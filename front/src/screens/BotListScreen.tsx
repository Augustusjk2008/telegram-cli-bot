import { useState } from "react";
import { AvatarPicker } from "../components/AvatarPicker";
import { BotActivitySummary } from "../components/BotActivitySummary";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { StatusPill } from "../components/StatusPill";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotSummary, CliType, CreateBotInput } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  EMPTY_CREATE_DRAFT,
  defaultCliPathForType,
  useBotManager,
  type CreateDraft,
} from "./useBotManager";
import { isBotOffline, isMainBot } from "./botManagerModel";

type Props = {
  client?: WebBotClient;
  onSelect: (alias: string) => void;
  onBotsChange?: (bots: BotSummary[]) => void;
  canManage?: boolean;
};

function DeleteBotDialog({
  botAlias,
  deleteHistory,
  busy,
  onDeleteHistoryChange,
  onCancel,
  onConfirm,
}: {
  botAlias: string;
  deleteHistory: boolean;
  busy: boolean;
  onDeleteHistoryChange: (value: boolean) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-[var(--surface)] p-5 shadow-[var(--shadow-card)]">
        <h2 className="text-base font-semibold">删除智能体 {botAlias}</h2>
        <label className="mt-4 flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={deleteHistory}
            onChange={(event) => onDeleteHistoryChange(event.target.checked)}
            disabled={busy}
            className="mt-0.5 h-4 w-4 rounded border-[var(--border)]"
          />
          <span>同时删除历史记录（包含所有子 agents）</span>
        </label>
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
            disabled={busy}
            className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
          >
            {busy ? "删除中..." : "删除"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function BotListScreen({ client = new MockWebBotClient(), onSelect, onBotsChange, canManage = true }: Props) {
  const [createDraft, setCreateDraft] = useState<CreateDraft>(EMPTY_CREATE_DRAFT);
  const [renamingAlias, setRenamingAlias] = useState("");
  const [renameDrafts, setRenameDrafts] = useState<Record<string, string>>({});
  const [showWorkdirPicker, setShowWorkdirPicker] = useState(false);
  const [pendingDeleteAlias, setPendingDeleteAlias] = useState("");
  const [deleteHistory, setDeleteHistory] = useState(false);
  const {
    bots,
    avatarAssets,
    loading,
    error,
    notice,
    savingAction,
    setError,
    createBot,
    toggleBot,
    renameBot,
    deleteBot,
    updateBotAvatar,
  } = useBotManager({ client, onBotsChange });

  const directoryBrowserAlias = bots.find((bot) => bot.isMain || bot.alias === "main")?.alias || bots[0]?.alias || "main";

  async function handleCreateBot() {
    const created = await createBot(createDraft);
    if (created) {
      setCreateDraft(EMPTY_CREATE_DRAFT);
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

  async function confirmDelete() {
    if (!pendingDeleteAlias) {
      return;
    }
    const bot = bots.find((item) => item.alias === pendingDeleteAlias);
    if (!bot) {
      setPendingDeleteAlias("");
      setDeleteHistory(false);
      return;
    }
    const removed = await deleteBot(bot, { deleteHistory });
    if (removed) {
      setPendingDeleteAlias("");
      setDeleteHistory(false);
    }
  }

  return (
    <main className="flex-1 overflow-y-auto bg-[var(--bg)] p-4">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">智能体管理</h1>
      </header>

      {error ? (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {notice}
        </div>
      ) : null}

      {canManage ? (
        <section className="mb-6 space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">新增智能体</h2>
          <AvatarPicker
            assets={avatarAssets}
            selectedName={createDraft.avatarName}
            previewAlt="新智能体头像预览"
            selectLabel="新智能体头像"
            onSelect={(avatarName) => setCreateDraft((prev) => ({ ...prev, avatarName }))}
          />
        </div>
        <div className="space-y-3">
          <input
            aria-label="新智能体别名"
            type="text"
            value={createDraft.alias}
            onChange={(event) => setCreateDraft((prev) => ({ ...prev, alias: event.target.value }))}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
            placeholder="team3"
          />
          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1 text-sm">
              <span className="text-[var(--muted)]">新智能体模式</span>
              <select
                aria-label="新智能体模式"
                value={createDraft.botMode}
                onChange={(event) => setCreateDraft((prev) => ({ ...prev, botMode: event.target.value as CreateBotInput["botMode"] }))}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
              >
                <option value="cli">cli</option>
                <option value="assistant">assistant</option>
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-[var(--muted)]">新智能体 CLI 类型</span>
              <select
                aria-label="新智能体 CLI 类型"
                value={createDraft.cliType}
                onChange={(event) => setCreateDraft((prev) => ({ ...prev, cliType: event.target.value as CliType }))}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
              >
                <option value="codex">codex</option>
                <option value="claude">claude</option>
                <option value="kimi">kimi</option>
              </select>
            </label>
          </div>
          <input
            aria-label="新智能体 CLI 路径"
            type="text"
            value={createDraft.cliPath}
            onChange={(event) => setCreateDraft((prev) => ({ ...prev, cliPath: event.target.value }))}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
            placeholder={defaultCliPathForType(createDraft.cliType)}
          />
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
        </div>
        <button
          type="button"
          onClick={() => void handleCreateBot()}
          disabled={savingAction !== ""}
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
        >
          {savingAction === "create" ? "创建中..." : "创建智能体"}
        </button>
        </section>
      ) : null}

      {loading ? (
        <div className="text-center text-[var(--muted)]">加载中...</div>
      ) : bots.length === 0 ? (
        <div className="text-center text-[var(--muted)]">暂无智能体</div>
      ) : (
        <div className="space-y-4">
          {bots.map((bot) => {
            const isMain = isMainBot(bot);
            const isRenaming = renamingAlias === bot.alias;
            const isOffline = isBotOffline(bot);
            const servicePillStatus = isOffline ? "offline" : "online";
            return (
              <section
                key={bot.alias}
                className={
                  isOffline
                    ? "space-y-3 rounded-2xl border border-red-200 bg-[var(--surface)] p-4"
                    : "space-y-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"
                }
              >
                <div className="flex items-start gap-3">
                  <AvatarPicker
                    assets={avatarAssets}
                    selectedName={bot.avatarName || ""}
                    previewAlt={`${bot.alias} 头像`}
                    selectLabel={`${bot.alias} 头像`}
                    disabled={savingAction !== ""}
                    onSelect={(avatarName) => {
                      void updateBotAvatar(bot, avatarName);
                    }}
                  />
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-lg font-semibold">{bot.alias}</h3>
                      {isMain ? (
                        <span className="rounded-full bg-[var(--surface-strong)] px-2 py-0.5 text-xs text-[var(--muted)]">主智能体</span>
                      ) : null}
                      {bot.status === "unread" ? <StatusPill status="unread" /> : null}
                      <StatusPill status={servicePillStatus} />
                    </div>
                    <BotActivitySummary bot={bot} />
                  </div>
                </div>

                <div
                  data-testid={`bot-actions-${bot.alias}`}
                  className="flex flex-wrap items-center gap-2"
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
                    className={
                      isOffline
                        ? "cursor-not-allowed rounded-lg border border-red-200 px-3 py-2 text-sm text-red-600 opacity-100"
                        : "rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
                    }
                  >
                    {isOffline ? "不可进入" : "进入"}
                  </button>
                  {canManage && !isMain ? (
                    <>
                      <button
                        type="button"
                        aria-label={isOffline ? `启动 ${bot.alias}` : `停止 ${bot.alias}`}
                        onClick={() => void toggleBot(bot)}
                        disabled={savingAction !== ""}
                        className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        {savingAction === `${bot.alias}:toggle` ? "处理中..." : isOffline ? "启动" : "停止"}
                      </button>
                      <button
                        type="button"
                        aria-label={`重命名 ${bot.alias}`}
                        onClick={() => {
                          setRenamingAlias((prev) => prev === bot.alias ? "" : bot.alias);
                          setRenameDrafts((prev) => ({ ...prev, [bot.alias]: bot.alias }));
                        }}
                        disabled={savingAction !== ""}
                        className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        改名
                      </button>
                      <button
                        type="button"
                        aria-label={`删除 ${bot.alias}`}
                        onClick={() => {
                          setPendingDeleteAlias(bot.alias);
                          setDeleteHistory(false);
                        }}
                        disabled={savingAction !== ""}
                        className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                      >
                        删除
                      </button>
                    </>
                  ) : null}
                </div>

                {isRenaming ? (
                  <div className="flex flex-wrap gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                    <input
                      aria-label={`${bot.alias} 新别名`}
                      type="text"
                      value={renameDrafts[bot.alias] || ""}
                      onChange={(event) => setRenameDrafts((prev) => ({ ...prev, [bot.alias]: event.target.value }))}
                      className="min-w-[220px] flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm"
                    />
                    <button
                      type="button"
                      aria-label={`保存别名 ${bot.alias}`}
                      onClick={() => void saveRename(bot)}
                      disabled={savingAction !== ""}
                      className="rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
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
      {showWorkdirPicker ? (
        <DirectoryPickerDialog
          title="选择工作目录"
          botAlias={directoryBrowserAlias}
          client={client}
          initialPath={createDraft.workingDir}
          onPick={(workingDir) => setCreateDraft((prev) => ({ ...prev, workingDir }))}
          onClose={() => setShowWorkdirPicker(false)}
        />
      ) : null}
      {pendingDeleteAlias ? (
        <DeleteBotDialog
          botAlias={pendingDeleteAlias}
          deleteHistory={deleteHistory}
          busy={savingAction === `${pendingDeleteAlias}:delete`}
          onDeleteHistoryChange={setDeleteHistory}
          onCancel={() => {
            if (savingAction === `${pendingDeleteAlias}:delete`) {
              return;
            }
            setPendingDeleteAlias("");
            setDeleteHistory(false);
          }}
          onConfirm={() => void confirmDelete()}
        />
      ) : null}
    </main>
  );
}
