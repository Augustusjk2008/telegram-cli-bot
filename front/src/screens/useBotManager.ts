import { useEffect, useMemo, useState } from "react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError } from "../services/types";
import type {
  AvatarAsset,
  BotSummary,
  ChatExecutionMode,
  CliType,
  CreateBotInput,
  RemoveBotOptions,
  UpdateBotWorkdirOptions,
  WorkdirChangeConflict,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DEFAULT_AVATAR_ASSETS, pickAvailableAvatarName } from "../utils/avatar";
import { normalizePathInput } from "../utils/pathInput";
import {
  buildExecutionConfig,
  DEFAULT_NATIVE_AGENT_CONFIG,
  DEFAULT_NATIVE_AGENT_DRAFT,
  getErrorMessage,
  getRuntimeBackend,
  isBotOffline,
  isMainBot,
  type EditDraft,
} from "./botManagerModel";

export type CreateDraft = CreateBotInput & {
  runtimeBackend: ChatExecutionMode;
};
export type { EditDraft } from "./botManagerModel";

export const EMPTY_CREATE_DRAFT: CreateDraft = {
  alias: "",
  botMode: "cli",
  cliType: "codex",
  cliPath: "",
  workingDir: "",
  avatarName: "",
  supportedExecutionModes: ["cli"],
  defaultExecutionMode: "cli",
  runtimeBackend: "cli",
  nativeAgent: { ...DEFAULT_NATIVE_AGENT_DRAFT },
};

export function defaultCliPathForType(cliType: CliType) {
  return cliType === "kimi" ? "kimi" : cliType === "claude" ? "claude" : "codex";
}

export function resolveDefaultCliPath(cliType: CliType, bots: BotSummary[]) {
  const fallback = defaultCliPathForType(cliType);
  const mainBot = bots.find((bot) => bot.isMain || bot.alias === "main");
  if (mainBot?.cliType === cliType && mainBot.cliPath?.trim() && mainBot.cliPath.trim() !== fallback) {
    return mainBot.cliPath.trim();
  }
  const existingBot = bots.find((bot) => bot.cliType === cliType && bot.cliPath?.trim() && bot.cliPath.trim() !== fallback);
  if (existingBot?.cliPath?.trim()) {
    return existingBot.cliPath.trim();
  }
  if (mainBot?.cliType === cliType && mainBot.cliPath?.trim()) {
    return mainBot.cliPath.trim();
  }
  const anyBot = bots.find((bot) => bot.cliType === cliType && bot.cliPath?.trim());
  return anyBot?.cliPath?.trim() || fallback;
}

export function buildCreateDraft(cliType: CliType = "codex", bots: BotSummary[] = []): CreateDraft {
  return {
    ...EMPTY_CREATE_DRAFT,
    cliType,
    cliPath: resolveDefaultCliPath(cliType, bots),
    runtimeBackend: "cli",
    nativeAgent: { ...DEFAULT_NATIVE_AGENT_DRAFT },
  };
}

export function asWebApiClientError(error: unknown): WebApiClientError | null {
  return error instanceof WebApiClientError ? error : null;
}

type SaveBotEditsResult =
  | { ok: true; bot: BotSummary }
  | { ok: false; conflict?: WorkdirChangeConflict };

type UseBotManagerArgs = {
  client?: WebBotClient;
  onBotsChange?: (bots: BotSummary[]) => void;
};

function normalizeNativeAgentInput(nativeAgent: CreateBotInput["nativeAgent"] | EditDraft["nativeAgent"] | undefined) {
  return {
    ...DEFAULT_NATIVE_AGENT_CONFIG,
    ...(nativeAgent || {}),
    provider: "",
    model: "",
    opencodeAgent: nativeAgent?.opencodeAgent?.trim() || "",
    baseUrl: "",
    apiKey: "",
    clearApiKey: false,
  };
}

function comparableNativeAgentInput(nativeAgent: CreateBotInput["nativeAgent"] | EditDraft["nativeAgent"] | undefined) {
  const normalized = normalizeNativeAgentInput(nativeAgent);
  return {
    opencodeAgent: normalized.opencodeAgent,
  };
}

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
      const { runtimeBackend, ...input } = draft;
      const executionConfig = buildExecutionConfig(runtimeBackend);
      const created = await client.addBot({
        ...input,
        ...executionConfig,
        alias: draft.alias.trim(),
        cliPath: normalizePathInput(draft.cliPath),
        workingDir: normalizePathInput(draft.workingDir),
        avatarName: pickAvailableAvatarName(draft.avatarName, resolvedAvatarAssets, "bot"),
        nativeAgent: normalizeNativeAgentInput(draft.nativeAgent),
      });
      setNotice("智能体已创建");
      await loadBots();
      return created;
    } catch (err) {
      const clientError = asWebApiClientError(err);
      if (clientError?.code === "bot_quota_exceeded") {
        setError("普通用户最多只能创建 3 个 Bot");
        return null;
      }
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

  async function deleteBot(bot: BotSummary, options: RemoveBotOptions = {}) {
    if (isMainBot(bot)) {
      return false;
    }

    setSavingAction(`${bot.alias}:delete`);
    setError("");
    setNotice("");
    try {
      await client.removeBot(bot.alias, options);
      setNotice(options.deleteHistory ? `已删除 ${bot.alias} 和历史记录` : `已删除 ${bot.alias}`);
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

    if (draft.runtimeBackend === "cli") {
      const cliUpdated = await updateBotCli(nextBot, draft.cliType, draft.cliPath);
      if (!cliUpdated) {
        return { ok: false };
      }
      nextBot = cliUpdated;
    }

    const executionConfig = buildExecutionConfig(draft.runtimeBackend);
    const executionChanged = JSON.stringify({
      runtimeBackend: getRuntimeBackend(nextBot),
      nativeAgent: comparableNativeAgentInput(nextBot.nativeAgent),
    }) !== JSON.stringify({
      runtimeBackend: draft.runtimeBackend,
      nativeAgent: comparableNativeAgentInput(draft.nativeAgent),
    });
    if (executionChanged) {
      nextBot = await client.updateBotExecutionConfig(nextBot.alias, {
        supportedExecutionModes: executionConfig.supportedExecutionModes,
        defaultExecutionMode: executionConfig.defaultExecutionMode,
        nativeAgent: {
          ...normalizeNativeAgentInput(draft.nativeAgent),
        },
      });
      setNotice("执行模式配置已更新");
      await loadBots();
    }

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
