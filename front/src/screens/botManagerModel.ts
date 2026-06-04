import type {
  AgentSummary,
  BotOverview,
  BotStatus,
  BotSummary,
  ChatExecutionMode,
  CliType,
  EnvConfigSnapshot,
  NativeAgentConfig,
} from "../services/types";

export type ManagerViewFilter = "all" | BotStatus | "attention";
export type BulkAction = "start" | "stop" | "delete";

export type EditDraft = {
  alias: string;
  botMode: "cli" | "assistant";
  cliType: CliType;
  cliPath: string;
  workingDir: string;
  avatarName: string;
  runtimeBackend: ChatExecutionMode;
  nativeAgent: NativeAgentConfig;
};

export type BotIssueCode =
  | "offline"
  | "busy"
  | "unread"
  | "missing_workdir"
  | "missing_cli_path"
  | "duplicate_workdir";

export type BotIssue = {
  code: BotIssueCode;
  severity: "info" | "warning";
  label: string;
  names?: string[];
  aliases?: string[];
};

export type BulkActionPlan = {
  action: BulkAction;
  targets: BotSummary[];
  skipped: Array<{ alias: string; reason: string }>;
  destructive: boolean;
};

export type BulkActionResult = {
  action: BulkAction;
  succeeded: string[];
  failed: Array<{ alias: string; message: string }>;
  skipped: Array<{ alias: string; reason: string }>;
};

export type BotConfigSnapshot = {
  alias: string;
  botMode: string;
  cliType: CliType;
  cliPath: string;
  workingDir: string;
  avatarName: string;
  runtimeBackend: ChatExecutionMode;
  nativeAgent: NativeAgentConfig;
  agents: AgentSummary[];
};

export const DEFAULT_NATIVE_AGENT_CONFIG: NativeAgentConfig = {
  provider: "",
  model: "",
  opencodeAgent: "",
};

type ExecutionModeSource =
  | Pick<BotSummary, "supportedExecutionModes" | "defaultExecutionMode" | "executionMode">
  | Pick<BotOverview, "supportedExecutionModes" | "defaultExecutionMode" | "executionMode">;

export function getSupportedExecutionModes(source?: ExecutionModeSource | null): ChatExecutionMode[] {
  return source?.supportedExecutionModes?.length ? source.supportedExecutionModes : ["cli"];
}

export function getRuntimeBackend(source?: ExecutionModeSource | null): ChatExecutionMode {
  const supported = getSupportedExecutionModes(source);
  const preferred = source?.executionMode ?? source?.defaultExecutionMode;
  if (preferred && supported.includes(preferred)) {
    return preferred;
  }
  if (supported.includes("cli")) {
    return "cli";
  }
  return supported[0] || "cli";
}

export function buildExecutionConfig(runtimeBackend: ChatExecutionMode) {
  return runtimeBackend === "native_agent"
    ? { supportedExecutionModes: ["native_agent"] as ChatExecutionMode[], defaultExecutionMode: "native_agent" as const }
    : { supportedExecutionModes: ["cli"] as ChatExecutionMode[], defaultExecutionMode: "cli" as const };
}

export function isNativeAgentGloballyEnabled(snapshot?: EnvConfigSnapshot | null) {
  const item = snapshot?.items?.find((entry) => entry.key === "NATIVE_AGENT_ENABLED");
  if (!item) {
    return null;
  }
  if (typeof item.value === "boolean") {
    return item.value;
  }
  return String(item.value || "").trim().toLowerCase() === "true";
}

export function isPureNativeBot(source?: ExecutionModeSource | null) {
  const supported = getSupportedExecutionModes(source);
  return supported.length === 1 && supported[0] === "native_agent";
}

export function nativeAgentConfigFromBot(bot: BotSummary): NativeAgentConfig {
  return {
    ...DEFAULT_NATIVE_AGENT_CONFIG,
    ...(bot.nativeAgent || {}),
  };
}

export function supportsNativeAgent(bot: BotSummary) {
  return getSupportedExecutionModes(bot).includes("native_agent");
}

const MANAGER_STATUS_PRIORITY: Record<BotStatus, number> = {
  unread: 0,
  running: 1,
  busy: 2,
  offline: 3,
};

function normalizeWorkdir(path: string | undefined) {
  return (path || "").trim().replace(/[\\/]+$/, "").toLowerCase();
}

export function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
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

export function getBusyAgentNames(bot: BotSummary) {
  const names = (bot.busyAgentNames || []).filter(Boolean);
  if (names.length > 0) {
    return names;
  }
  if (isBotBusy(bot)) {
    return ["主 agent"];
  }
  return [];
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
    getRuntimeBackend(bot),
    bot.nativeAgent?.provider || "",
    bot.nativeAgent?.model || "",
    bot.nativeAgent?.opencodeAgent || "",
    ...(bot.busyAgentNames || []),
  ].join(" ").toLowerCase();
  return haystack.includes(normalized);
}

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
    runtimeBackend: getRuntimeBackend(bot),
    nativeAgent: nativeAgentConfigFromBot(bot),
  };
}

export function detectBotIssues(bot: BotSummary, allBots: BotSummary[]): BotIssue[] {
  const issues: BotIssue[] = [];

  if (isBotOffline(bot)) {
    issues.push({ code: "offline", severity: "warning", label: "离线" });
  }
  if (isBotBusy(bot)) {
    issues.push({ code: "busy", severity: "info", label: "处理中", names: getBusyAgentNames(bot) });
  }
  if (bot.status === "unread") {
    issues.push({ code: "unread", severity: "info", label: "未读" });
  }
  if (!bot.workingDir.trim()) {
    issues.push({ code: "missing_workdir", severity: "warning", label: "缺少工作目录" });
  }
  if (getRuntimeBackend(bot) === "cli" && bot.cliPath !== undefined && !bot.cliPath.trim()) {
    issues.push({ code: "missing_cli_path", severity: "warning", label: "CLI 路径为空" });
  }

  const normalized = normalizeWorkdir(bot.workingDir);
  if (normalized && !isMainBot(bot)) {
    const duplicates = allBots
      .filter((item) => !isMainBot(item) && normalizeWorkdir(item.workingDir) === normalized)
      .map((item) => item.alias);
    if (duplicates.length > 1) {
      issues.push({
        code: "duplicate_workdir",
        severity: "warning",
        label: "工作目录重复",
        aliases: duplicates,
      });
    }
  }

  return issues;
}

export function botNeedsAttention(bot: BotSummary, allBots: BotSummary[]) {
  return detectBotIssues(bot, allBots).length > 0;
}

export function getVisibleManagedBots({
  bots,
  query,
  filter,
}: {
  bots: BotSummary[];
  query: string;
  filter: ManagerViewFilter;
}) {
  return sortManagedBots(bots).filter((bot) => {
    if (!botMatchesManagerQuery(bot, query)) {
      return false;
    }
    if (filter === "all") {
      return true;
    }
    if (filter === "attention") {
      return botNeedsAttention(bot, bots);
    }
    return getBotManagerStatus(bot) === filter;
  });
}

export function buildBulkActionPlan(action: BulkAction, bots: BotSummary[]): BulkActionPlan {
  const targets: BotSummary[] = [];
  const skipped: Array<{ alias: string; reason: string }> = [];

  bots.forEach((bot) => {
    if (action === "start") {
      if (isMainBot(bot)) {
        skipped.push({ alias: bot.alias, reason: "主 bot 不支持批量启动" });
        return;
      }
      if (!isBotOffline(bot)) {
        skipped.push({ alias: bot.alias, reason: "智能体已在线" });
        return;
      }
      targets.push(bot);
      return;
    }

    if (action === "stop") {
      if (isMainBot(bot)) {
        skipped.push({ alias: bot.alias, reason: "主 bot 不可停止" });
        return;
      }
      if (isBotOffline(bot)) {
        skipped.push({ alias: bot.alias, reason: "智能体已离线" });
        return;
      }
      targets.push(bot);
      return;
    }

    if (isMainBot(bot)) {
      skipped.push({ alias: bot.alias, reason: "主 bot 不可删除" });
      return;
    }
    targets.push(bot);
  });

  return {
    action,
    targets,
    skipped,
    destructive: action === "delete",
  };
}

export function getBotConfigSnapshot(bot: BotSummary): BotConfigSnapshot {
  return {
    alias: bot.alias,
    botMode: bot.botMode || "cli",
    cliType: bot.cliType,
    cliPath: bot.cliPath || bot.cliType,
    workingDir: bot.workingDir,
    avatarName: bot.avatarName || "",
    runtimeBackend: getRuntimeBackend(bot),
    nativeAgent: nativeAgentConfigFromBot(bot),
    agents: bot.agents || [],
  };
}
