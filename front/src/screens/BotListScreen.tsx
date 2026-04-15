import { useEffect, useState } from "react";
import { AvatarPicker } from "../components/AvatarPicker";
import { StatusPill } from "../components/StatusPill";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { AvatarAsset, BotSummary, CliType, CreateBotInput } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DEFAULT_AVATAR_ASSETS, pickAvailableAvatarName } from "../utils/avatar";
import { normalizePathInput } from "../utils/pathInput";

type Props = {
  client?: WebBotClient;
  onSelect: (alias: string) => void;
};

type CreateDraft = CreateBotInput;

const EMPTY_CREATE_DRAFT: CreateDraft = {
  alias: "",
  botMode: "cli",
  cliType: "codex",
  cliPath: "",
  workingDir: "",
  avatarName: "bot-default.png",
};

export function BotListScreen({ client = new MockWebBotClient(), onSelect }: Props) {
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [avatarAssets, setAvatarAssets] = useState<AvatarAsset[]>(DEFAULT_AVATAR_ASSETS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [createDraft, setCreateDraft] = useState<CreateDraft>(EMPTY_CREATE_DRAFT);
  const [savingAction, setSavingAction] = useState("");
  const [renamingAlias, setRenamingAlias] = useState("");
  const [renameDrafts, setRenameDrafts] = useState<Record<string, string>>({});

  async function loadBots() {
    setLoading(true);
    setError("");
    try {
      const [data, assets] = await Promise.all([
        client.listBots(),
        client.listAvatarAssets().catch(() => DEFAULT_AVATAR_ASSETS),
      ]);
      const resolvedAssets = assets.length > 0 ? assets : DEFAULT_AVATAR_ASSETS;
      setBots(data);
      setAvatarAssets(resolvedAssets);
      setCreateDraft((prev) => ({
        ...prev,
        avatarName: pickAvailableAvatarName(prev.avatarName, resolvedAssets, "bot"),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 Bot 失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadBots();
  }, [client]);

  async function createBot() {
    if (!createDraft.alias.trim()) {
      setError("别名不能为空");
      return;
    }

    setSavingAction("create");
    setError("");
    setNotice("");
    try {
      await client.addBot({
        ...createDraft,
        alias: createDraft.alias.trim(),
        cliPath: normalizePathInput(createDraft.cliPath),
        workingDir: normalizePathInput(createDraft.workingDir),
        avatarName: pickAvailableAvatarName(createDraft.avatarName, avatarAssets, "bot"),
      });
      setCreateDraft(EMPTY_CREATE_DRAFT);
      setNotice("Bot 已创建");
      await loadBots();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建 Bot 失败");
    } finally {
      setSavingAction("");
    }
  }

  async function toggleBot(bot: BotSummary) {
    if (bot.alias === "main") {
      return;
    }

    setSavingAction(`${bot.alias}:toggle`);
    setError("");
    setNotice("");
    try {
      if (bot.status === "offline") {
        await client.startBot(bot.alias);
        setNotice(`已启动 ${bot.alias}`);
      } else {
        await client.stopBot(bot.alias);
        setNotice(`已停止 ${bot.alias}`);
      }
      await loadBots();
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新 Bot 状态失败");
    } finally {
      setSavingAction("");
    }
  }

  async function saveRename(bot: BotSummary) {
    const nextAlias = (renameDrafts[bot.alias] || "").trim();
    if (!nextAlias) {
      setError("新别名不能为空");
      return;
    }

    setSavingAction(`${bot.alias}:rename`);
    setError("");
    setNotice("");
    try {
      await client.renameBot(bot.alias, nextAlias);
      setNotice(`已将 ${bot.alias} 改名为 ${nextAlias}`);
      setRenamingAlias("");
      setRenameDrafts((prev) => {
        const next = { ...prev };
        delete next[bot.alias];
        return next;
      });
      await loadBots();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bot 改名失败");
    } finally {
      setSavingAction("");
    }
  }

  async function deleteBot(bot: BotSummary) {
    if (bot.alias === "main") {
      return;
    }
    if (!window.confirm(`确定删除 Bot ${bot.alias} 吗？`)) {
      return;
    }

    setSavingAction(`${bot.alias}:delete`);
    setError("");
    setNotice("");
    try {
      await client.removeBot(bot.alias);
      setNotice(`已删除 ${bot.alias}`);
      await loadBots();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除 Bot 失败");
    } finally {
      setSavingAction("");
    }
  }

  async function updateExistingBotAvatar(bot: BotSummary, avatarName: string) {
    const nextAvatarName = pickAvailableAvatarName(avatarName, avatarAssets, "bot");
    if (nextAvatarName === (bot.avatarName || "bot-default.png")) {
      return;
    }

    setSavingAction(`${bot.alias}:avatar`);
    setError("");
    setNotice("");
    setBots((prev) => prev.map((item) => (
      item.alias === bot.alias
        ? { ...item, avatarName: nextAvatarName }
        : item
    )));
    try {
      await client.updateBotAvatar(bot.alias, nextAvatarName);
      setNotice(`已更新 ${bot.alias} 的头像`);
      await loadBots();
    } catch (err) {
      await loadBots();
      setError(err instanceof Error ? err.message : "更新头像失败");
    } finally {
      setSavingAction("");
    }
  }

  return (
    <main className="flex-1 overflow-y-auto bg-[var(--bg)] p-4">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">Bot 管理</h1>
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

      <section className="mb-6 space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">新增 Bot</h2>
          <AvatarPicker
            assets={avatarAssets}
            selectedName={createDraft.avatarName}
            previewAlt="新 Bot 头像预览"
            selectLabel="新 Bot 头像"
            onSelect={(avatarName) => setCreateDraft((prev) => ({ ...prev, avatarName }))}
          />
        </div>
        <div className="space-y-3">
          <input
            aria-label="新 Bot 别名"
            type="text"
            value={createDraft.alias}
            onChange={(event) => setCreateDraft((prev) => ({ ...prev, alias: event.target.value }))}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
            placeholder="team3"
          />
          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1 text-sm">
              <span className="text-[var(--muted)]">新 Bot 模式</span>
              <select
                aria-label="新 Bot 模式"
                value={createDraft.botMode}
                onChange={(event) => setCreateDraft((prev) => ({ ...prev, botMode: event.target.value as CreateBotInput["botMode"] }))}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
              >
                <option value="cli">cli</option>
                <option value="assistant">assistant</option>
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-[var(--muted)]">新 Bot CLI 类型</span>
              <select
                aria-label="新 Bot CLI 类型"
                value={createDraft.cliType}
                onChange={(event) => setCreateDraft((prev) => ({ ...prev, cliType: event.target.value as CliType }))}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
              >
                <option value="codex">codex</option>
                <option value="claude">claude</option>
              </select>
            </label>
          </div>
          <input
            aria-label="新 Bot CLI 路径"
            type="text"
            value={createDraft.cliPath}
            onChange={(event) => setCreateDraft((prev) => ({ ...prev, cliPath: event.target.value }))}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
            placeholder="codex"
          />
          <input
            aria-label="新 Bot 工作目录"
            type="text"
            value={createDraft.workingDir}
            onChange={(event) => setCreateDraft((prev) => ({ ...prev, workingDir: event.target.value }))}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
            placeholder="/srv/telegram-cli-bridge/team3"
          />
        </div>
        <button
          type="button"
          onClick={() => void createBot()}
          disabled={savingAction !== ""}
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
        >
          {savingAction === "create" ? "创建中..." : "创建 Bot"}
        </button>
      </section>

      {loading ? (
        <div className="text-center text-[var(--muted)]">加载中...</div>
      ) : bots.length === 0 ? (
        <div className="text-center text-[var(--muted)]">暂无 Bot</div>
      ) : (
        <div className="space-y-4">
          {bots.map((bot) => {
            const isMain = bot.alias === "main" || bot.isMain;
            const isRenaming = renamingAlias === bot.alias;
            const isOffline = bot.status === "offline";
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
                    selectedName={bot.avatarName || "bot-default.png"}
                    previewAlt={`${bot.alias} 头像`}
                    selectLabel={`${bot.alias} 头像`}
                    disabled={savingAction !== ""}
                    onSelect={(avatarName) => {
                      void updateExistingBotAvatar(bot, avatarName);
                    }}
                  />
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-lg font-semibold">{bot.alias}</h3>
                      {isMain ? (
                        <span className="rounded-full bg-[var(--surface-strong)] px-2 py-0.5 text-xs text-[var(--muted)]">主 Bot</span>
                      ) : null}
                      <StatusPill status={bot.status} />
                    </div>
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
                  {!isMain ? (
                    <>
                      <button
                        type="button"
                        aria-label={bot.status === "offline" ? `启动 ${bot.alias}` : `停止 ${bot.alias}`}
                        onClick={() => void toggleBot(bot)}
                        disabled={savingAction !== ""}
                        className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        {savingAction === `${bot.alias}:toggle` ? "处理中..." : bot.status === "offline" ? "启动" : "停止"}
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
                        onClick={() => void deleteBot(bot)}
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
    </main>
  );
}
