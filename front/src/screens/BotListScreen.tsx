import { useEffect, useState } from "react";
import { AvatarPicker } from "../components/AvatarPicker";
import { BotActivitySummary } from "../components/BotActivitySummary";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { NativeAgentConfigFields } from "../components/NativeAgentConfigFields";
import { StatusPill } from "../components/StatusPill";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotSummary, CliType, CreateBotInput } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  buildCreateDraft,
  defaultCliPathForType,
  useBotManager,
  type CreateDraft,
} from "./useBotManager";
import { DEFAULT_NATIVE_AGENT_DRAFT, isBotOffline, isMainBot, isNativeAgentGloballyEnabled } from "./botManagerModel";

type Props = {
  client?: WebBotClient;
  onSelect: (alias: string) => void;
  onBotsChange?: (bots: BotSummary[]) => void;
  canManage?: boolean;
  canCreateWorkdirDirectory?: boolean;
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

export function BotListScreen({
  client = new MockWebBotClient(),
  onSelect,
  onBotsChange,
  canManage = true,
  canCreateWorkdirDirectory = true,
}: Props) {
  const [renamingAlias, setRenamingAlias] = useState("");
  const [renameDrafts, setRenameDrafts] = useState<Record<string, string>>({});
  const [showWorkdirPicker, setShowWorkdirPicker] = useState(false);
  const [pendingDeleteAlias, setPendingDeleteAlias] = useState("");
  const [deleteHistory, setDeleteHistory] = useState(false);
  const [nativeAgentFeatureEnabled, setNativeAgentFeatureEnabled] = useState<boolean | null>(null);
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
  const [createDraft, setCreateDraft] = useState<CreateDraft>(() => buildCreateDraft());

  const directoryBrowserAlias = bots.find((bot) => bot.isMain || bot.alias === "main")?.alias || bots[0]?.alias || "main";

  useEffect(() => {
    if (bots.length === 0) {
      return;
    }
    setCreateDraft((prev) => {
      const userEditedPath = prev.cliPath.trim() && prev.cliPath.trim() !== defaultCliPathForType(prev.cliType);
      if (prev.alias.trim() || prev.workingDir.trim() || prev.avatarName.trim() || userEditedPath) {
        return prev;
      }
      return { ...prev, cliPath: buildCreateDraft(prev.cliType, bots).cliPath };
    });
  }, [bots]);

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

  async function handleCreateBot() {
    const created = await createBot(createDraft);
    if (created) {
      setCreateDraft(buildCreateDraft(createDraft.cliType, bots));
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

  const nativeAgentOptionVisible = nativeAgentFeatureEnabled !== false || createDraft.runtimeBackend === "native_agent";

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
                {nativeAgentOptionVisible ? <option value="native_agent">原生 agent</option> : null}
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
                    setCreateDraft((prev) => ({ ...prev, cliType, cliPath: buildCreateDraft(cliType, bots).cliPath }));
                  }}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                >
                  <option value="codex">codex</option>
                  <option value="claude">claude</option>
                  <option value="kimi">kimi</option>
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
          {createDraft.runtimeBackend === "native_agent" ? (
            <NativeAgentConfigFields
              provider={createDraft.nativeAgent?.provider || DEFAULT_NATIVE_AGENT_DRAFT.provider}
              model={createDraft.nativeAgent?.model || DEFAULT_NATIVE_AGENT_DRAFT.model}
              opencodeAgent={createDraft.nativeAgent?.opencodeAgent || DEFAULT_NATIVE_AGENT_DRAFT.opencodeAgent}
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
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] hover:opacity-90 disabled:opacity-60"
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
                      className="rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-[var(--accent-foreground)] hover:opacity-90 disabled:opacity-60"
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
