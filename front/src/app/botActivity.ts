import type { BotSummary } from "../services/types";

export type BotActivityChange = Pick<BotSummary, "activityStatus" | "busyAgentIds" | "busyAgentNames" | "busyAgentCount"> & {
  agentId?: string;
  agentName?: string;
};

export type BotAgentActivityOverride = {
  name: string;
  busy: boolean;
  updatedAt: number;
};

export type BotAgentActivityOverrides = Record<string, Record<string, BotAgentActivityOverride>>;

const BOT_AGENT_ACTIVITY_TTL_MS = 2 * 60 * 1000;

function isOffline(bot: BotSummary) {
  return bot.serviceStatus === "offline" || bot.status === "offline";
}

function normalizeAgentId(agentId: string | undefined) {
  const trimmed = String(agentId || "").trim();
  return trimmed || "main";
}

function normalizeAgentName(name: string | undefined, agentId: string) {
  const trimmed = String(name || "").trim();
  if (trimmed) {
    return trimmed;
  }
  return agentId === "main" ? "主 agent" : agentId;
}

function collectBackendBusyAgents(bot: BotSummary) {
  const busyById = new Map<string, string>();
  const ids = bot.busyAgentIds || [];
  const names = bot.busyAgentNames || [];

  ids.forEach((id, index) => {
    const agentId = normalizeAgentId(id);
    busyById.set(agentId, normalizeAgentName(names[index], agentId));
  });

  if (busyById.size === 0 && (bot.activityStatus === "busy" || bot.status === "busy")) {
    busyById.set("main", "主 agent");
  }

  return busyById;
}

export function updateBotAgentActivityOverrides(
  previous: BotAgentActivityOverrides,
  alias: string,
  activity: BotActivityChange,
  now = Date.now(),
): BotAgentActivityOverrides {
  const agentId = normalizeAgentId(activity.agentId || activity.busyAgentIds?.[0]);
  const agentName = normalizeAgentName(activity.agentName || activity.busyAgentNames?.[0], agentId);
  const busy = activity.activityStatus === "busy" || (activity.busyAgentCount || 0) > 0;
  const currentBotOverrides = previous[alias] || {};
  const nextBotOverrides = { ...currentBotOverrides };

  if (busy) {
    nextBotOverrides[agentId] = {
      name: agentName,
      busy: true,
      updatedAt: now,
    };
  } else {
    delete nextBotOverrides[agentId];
  }

  const next = { ...previous };
  if (Object.keys(nextBotOverrides).length > 0) {
    next[alias] = nextBotOverrides;
  } else {
    delete next[alias];
  }
  return next;
}

export function mergeBotActivity(
  bot: BotSummary,
  overrides: Record<string, BotAgentActivityOverride> | undefined,
  now = Date.now(),
): BotSummary {
  const busyById = collectBackendBusyAgents(bot);

  Object.entries(overrides || {}).forEach(([agentId, activity]) => {
    if (!activity.busy || now - activity.updatedAt > BOT_AGENT_ACTIVITY_TTL_MS) {
      return;
    }
    const normalizedId = normalizeAgentId(agentId);
    busyById.set(normalizedId, normalizeAgentName(activity.name, normalizedId));
  });

  const backendCount = bot.busyAgentCount || 0;
  const busyAgentIds = Array.from(busyById.keys());
  const busyAgentNames = Array.from(busyById.values());
  const busyAgentCount = Math.max(backendCount, busyAgentIds.length);
  const busy = busyAgentCount > 0 || bot.activityStatus === "busy" || bot.status === "busy";
  const offline = isOffline(bot);

  return {
    ...bot,
    activityStatus: busy ? "busy" : "idle",
    busyAgentIds,
    busyAgentNames,
    busyAgentCount,
    status: busy ? "busy" : offline ? "offline" : "running",
    lastActiveText: busy ? "处理中" : offline ? "离线" : "运行中",
  };
}

export function applyBotActivityOverrides(
  bots: BotSummary[],
  overrides: BotAgentActivityOverrides,
  now = Date.now(),
) {
  return bots.map((bot) => mergeBotActivity(bot, overrides[bot.alias], now));
}
