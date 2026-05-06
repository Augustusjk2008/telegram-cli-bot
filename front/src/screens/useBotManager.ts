import { useEffect, useMemo, useState } from "react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError } from "../services/types";
import type {
  AvatarAsset,
  BotStatus,
  BotSummary,
  CliType,
  CreateBotInput,
  UpdateBotWorkdirOptions,
  WorkdirChangeConflict,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DEFAULT_AVATAR_ASSETS, pickAvailableAvatarName } from "../utils/avatar";
import { normalizePathInput } from "../utils/pathInput";

export type CreateDraft = CreateBotInput;

export type EditDraft = {
  alias: string;
  botMode: "cli" | "assistant";
  cliType: CliType;
  cliPath: string;
  workingDir: string;
  avatarName: string;
};

export const EMPTY_CREATE_DRAFT: CreateDraft = {
  alias: "",
  botMode: "cli",
  cliType: "codex",
  cliPath: "",
  workingDir: "",
  avatarName: "",
};

export function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function asWebApiClientError(error: unknown): WebApiClientError | null {
  return error instanceof WebApiClientError ? error : null;
}

export function isBotOffline(bot: BotSummary) {
  return bot.serviceStatus === "offline" || bot.status === "offline";
}

export function isMainBot(bot: BotSummary) {
  return bot.alias === "main" || Boolean(bot.isMain);
}

export function isBotBusy(bot: BotSummary) {
  return bot.activityStatus === "busy" || bot.status === "busy" || (bot.busyAgentCount || 0) > 0;
}

export function getBotManagerStatus(bot: BotSummary): BotStatus {
  if (isBotOffline(bot)) {
    return "offline";
  }
  if (bot.status === "unread") {
    return "unread";
  }
  if (isBotBusy(bot)) {
    return "busy";
  }
  return "running";
}

export function botMatchesManagerQuery(bot: BotSummary, query: string) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  const haystack = [
    bot.alias,
    bot.workingDir,
    bot.cliType,
    bot.botMode || "",
    ...(bot.busyAgentNames || []),
  ].join(" ").toLowerCase();
  return haystack.includes(normalized);
}

const MANAGER_STATUS_PRIORITY: Record<BotStatus, number> = {
  unread: 0,
  running: 1,
  busy: 2,
  offline: 3,
};

export function sortManagedBots(items: BotSummary[]) {
  return [...items].sort((left, right) => {
    const leftMain = isMainBot(left);
    const rightMain = isMainBot(right);
    if (leftMain !== rightMain) {
      return leftMain ? -1 : 1;
    }

    const statusDelta = MANAGER_STATUS_PRIORITY[getBotManagerStatus(left)] - MANAGER_STATUS_PRIORITY[getBotManagerStatus(right)];
    if (statusDelta !== 0) {
      return statusDelta;
    }

    return left.alias.localeCompare(right.alias, "zh-CN", {
      numeric: true,
      sensitivity: "base",
    });
  });
}

export function countBotManagerStats(items: BotSummary[]) {
  return {
    total: items.length,
    online: items.filter((bot) => !isBotOffline(bot)).length,
    busy: items.filter(isBotBusy).length,
    offline: items.filter(isBotOffline).length,
  };
}

export function draftFromBot(bot: BotSummary): EditDraft {
  return {
    alias: bot.alias,
    botMode: bot.botMode === "assistant" ? "assistant" : "cli",
    cliType: bot.cliType,
    cliPath: bot.cliPath || bot.cliType,
    workingDir: bot.workingDir,
    avatarName: bot.avatarName || "",
  };
}

type SaveBotEditsResult =
  | { ok: true; bot: BotSummary }
  | { ok: false; conflict?: WorkdirChangeConflict };

type UseBotManagerArgs = {
  client?: WebBotClient;
  onBotsChange?: (bots: BotSummary[]) => void;
};

export function useBotManager({
  client = new MockWebBotClient(),
  onBotsChange,
}: UseBotManagerArgs = {}) {
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [avatarAssets, setAvatarAssets] = useState<AvatarAsset[]>(DEFAULT_AVATAR_ASSETS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [savingAction, setSavingAction] = useState("");

  const resolvedAvatarAssets = useMemo(
    () => (avatarAssets.length > 0 ? avatarAssets : DEFAULT_AVATAR_ASSETS),
    [avatarAssets],
  );

  async function loadBots() {
    setLoading(true);
    setError("");
    try {
      const [data, assets] = await Promise.all([
        client.listBots(),
        client.listAvatarAssets().catch(() => DEFAULT_AVATAR_ASSETS),
      ]);
      const nextAssets = assets.length > 0 ? assets : DEFAULT_AVATAR_ASSETS;
      setBots(data);
      setAvatarAssets(nextAssets);
      onBotsChange?.(data);
      return data;
    } catch (err) {
      setError(getErrorMessage(err, "加载智能体失败"));
      return [];
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadBots();
  }, [client]);

  async function createBot(draft: CreateDraft) {
    if (!draft.alias.trim()) {
      setError("别名不能为空");
      return null;
    }

    setSavingAction("create");
    setError("");
    setNotice("");
    try {
      const created = await client.addBot({
        ...draft,
        alias: draft.alias.trim(),
        cliPath: normalizePathInput(draft.cliPath),
        workingDir: normalizePathInput(draft.workingDir),
        avatarName: pickAvailableAvatarName(draft.avatarName, resolvedAvatarAssets, "bot"),
      });
      setNotice("智能体已创建");
      await loadBots();
      return created;
    } catch (err) {
      setError(getErrorMessage(err, "创建智能体失败"));
      return null;
    } finally {
      setSavingAction("");
    }
  }

  async function toggleBot(bot: BotSummary) {
    if (isMainBot(bot)) {
      return null;
    }

    setSavingAction(`${bot.alias}:toggle`);
    setError("");
    setNotice("");
    try {
      const nextBot = isBotOffline(bot)
        ? await client.startBot(bot.alias)
        : await client.stopBot(bot.alias);
      setNotice(isBotOffline(bot) ? `已启动 ${bot.alias}` : `已停止 ${bot.alias}`);
      await loadBots();
      return nextBot;
    } catch (err) {
      setError(getErrorMessage(err, "更新智能体状态失败"));
      return null;
    } finally {
      setSavingAction("");
    }
  }

  async function renameBot(bot: BotSummary, nextAlias: string) {
    const normalizedAlias = nextAlias.trim();
    if (!normalizedAlias) {
      setError("新别名不能为空");
      return null;
    }

    if (normalizedAlias === bot.alias) {
      return bot;
    }

    setSavingAction(`${bot.alias}:rename`);
    setError("");
    setNotice("");
    try {
      const renamed = await client.renameBot(bot.alias, normalizedAlias);
      setNotice(`已将 ${bot.alias} 改名为 ${normalizedAlias}`);
      await loadBots();
      return renamed;
    } catch (err) {
      setError(getErrorMessage(err, "智能体改名失败"));
      return null;
    } finally {
      setSavingAction("");
    }
  }

  async function deleteBot(bot: BotSummary) {
    if (isMainBot(bot)) {
      return false;
    }
    if (!window.confirm(`确定删除智能体 ${bot.alias} 吗？`)) {
      return false;
    }

    setSavingAction(`${bot.alias}:delete`);
    setError("");
    setNotice("");
    try {
      await client.removeBot(bot.alias);
      setNotice(`已删除 ${bot.alias}`);
      await loadBots();
      return true;
    } catch (err) {
      setError(getErrorMessage(err, "删除智能体失败"));
      return false;
    } finally {
      setSavingAction("");
    }
  }

  async function updateBotAvatar(bot: BotSummary, avatarName: string) {
    const nextAvatarName = pickAvailableAvatarName(avatarName, resolvedAvatarAssets, "bot");
    if (nextAvatarName === pickAvailableAvatarName(bot.avatarName, resolvedAvatarAssets, "bot")) {
      return bot;
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
      const updated = await client.updateBotAvatar(bot.alias, nextAvatarName);
      setNotice(`已更新 ${bot.alias} 的头像`);
      await loadBots();
      return updated;
    } catch (err) {
      await loadBots();
      setError(getErrorMessage(err, "更新头像失败"));
      return null;
    } finally {
      setSavingAction("");
    }
  }

  async function updateBotCli(bot: BotSummary, cliType: CliType, cliPath: string) {
    const nextCliPath = normalizePathInput(cliPath);
    if (!nextCliPath) {
      setError("CLI 路径不能为空");
      return null;
    }
    if (bot.cliType === cliType && (bot.cliPath || bot.cliType) === nextCliPath) {
      return bot;
    }

    setSavingAction(`${bot.alias}:cli`);
    setError("");
    setNotice("");
    try {
      const updated = await client.updateBotCli(bot.alias, cliType, nextCliPath);
      setNotice("CLI 配置已更新");
      await loadBots();
      return updated;
    } catch (err) {
      setError(getErrorMessage(err, "更新 CLI 配置失败"));
      return null;
    } finally {
      setSavingAction("");
    }
  }

  async function updateBotWorkdir(
    bot: BotSummary,
    workingDir: string,
    options: UpdateBotWorkdirOptions = {},
  ) {
    const nextWorkdir = normalizePathInput(workingDir);
    if (!nextWorkdir) {
      setError("工作目录不能为空");
      return { ok: false } as const;
    }
    if (bot.workingDir === nextWorkdir) {
      return { ok: true, bot } as const;
    }

    setSavingAction(`${bot.alias}:workdir`);
    setError("");
    setNotice("");
    try {
      const updated = await client.updateBotWorkdir(bot.alias, nextWorkdir, options);
      setNotice("工作目录已更新");
      await loadBots();
      return { ok: true, bot: updated } as const;
    } catch (err) {
      const clientError = asWebApiClientError(err);
      if (clientError?.code === "workdir_change_requires_reset" && clientError.data) {
        return {
          ok: false,
          conflict: clientError.data as WorkdirChangeConflict,
        } as const;
      }
      if (clientError?.code === "workdir_change_blocked_processing") {
        setError("当前仍有任务运行，请先停止任务再切换工作目录");
        return { ok: false } as const;
      }
      setError(getErrorMessage(err, "更新工作目录失败"));
      return { ok: false } as const;
    } finally {
      setSavingAction("");
    }
  }

  async function saveBotEdits(
    bot: BotSummary,
    draft: EditDraft,
    options: UpdateBotWorkdirOptions = {},
  ): Promise<SaveBotEditsResult> {
    let nextBot = bot;

    if (!isMainBot(bot) && draft.alias.trim() !== bot.alias) {
      const renamed = await renameBot(bot, draft.alias);
      if (!renamed) {
        return { ok: false };
      }
      nextBot = renamed;
    }

    const cliUpdated = await updateBotCli(nextBot, draft.cliType, draft.cliPath);
    if (!cliUpdated) {
      return { ok: false };
    }
    nextBot = cliUpdated;

    const workdirResult = await updateBotWorkdir(nextBot, draft.workingDir, options);
    if (!workdirResult.ok) {
      return {
        ok: false,
        conflict: workdirResult.conflict,
      };
    }
    nextBot = workdirResult.bot;

    const avatarUpdated = await updateBotAvatar(nextBot, draft.avatarName);
    if (avatarUpdated) {
      nextBot = avatarUpdated;
    }

    return { ok: true, bot: nextBot };
  }

  return {
    client,
    bots,
    avatarAssets: resolvedAvatarAssets,
    loading,
    error,
    notice,
    savingAction,
    setError,
    setNotice,
    loadBots,
    createBot,
    toggleBot,
    renameBot,
    deleteBot,
    updateBotAvatar,
    updateBotCli,
    updateBotWorkdir,
    saveBotEdits,
  };
}
