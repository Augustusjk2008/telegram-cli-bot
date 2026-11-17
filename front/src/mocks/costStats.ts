import type {
  CostStats,
  CostStatsConfig,
  CostStatsGranularity,
  CostStatsProvider,
  CostStatsQuery,
  CostStatsRow,
} from "../services/types";

const DAY_MS = 24 * 60 * 60 * 1000;
const PROVIDERS = ["claude", "codex"];
const BOTS = ["main", "docs"];
const AGENTS = ["main", "implementer", "reviewer"];
const USERS = ["alice", "bob", "carol", ""];
const MODELS = ["claude-fable-5-2", "claude-opus-5-5", "gpt-6-sol", "gpt-6-luna"];

function parseDay(value: string) {
  return Date.parse(`${value}T00:00:00Z`);
}

function formatDay(time: number) {
  return new Date(time).toISOString().slice(0, 10);
}

function resolveGranularity(days: number, requested: CostStatsQuery["granularity"]): CostStatsGranularity {
  if (requested && requested !== "auto") return requested === "hour" && days > 7 ? "day" : requested;
  if (days <= 2) return "hour";
  if (days <= 92) return "day";
  return days <= 730 ? "week" : "month";
}

function bucketOf(day: number, hour: number, granularity: CostStatsGranularity) {
  if (granularity === "hour") return `${formatDay(day)}T${String(hour).padStart(2, "0")}`;
  if (granularity === "day") return formatDay(day);
  if (granularity === "month") return `${formatDay(day).slice(0, 7)}-01`;
  const weekday = (new Date(day).getUTCDay() + 6) % 7;
  return formatDay(day - weekday * DAY_MS);
}

/** Small deterministic generator so mock charts are stable between renders. */
function noise(seed: number) {
  const value = Math.sin(seed * 12.9898) * 43758.5453;
  return value - Math.floor(value);
}

/** Deterministic demo cube shaped like `/api/admin/cost-stats/stats`. */
export function buildMockCostStats(query: CostStatsQuery, config: CostStatsConfig): CostStats {
  const today = config.timeBasis.today;
  const endDate = query.endDate || today;
  const startDate = query.startDate || formatDay(parseDay(endDate) - 29 * DAY_MS);
  const start = parseDay(startDate);
  const end = parseDay(endDate);
  const days = Math.max(1, Math.round((end - start) / DAY_MS) + 1);
  const granularity = resolveGranularity(days, query.granularity);

  const buckets: string[] = [];
  for (let day = start; day <= end; day += DAY_MS) {
    for (const hour of granularity === "hour" ? Array.from({ length: 24 }, (_, index) => index) : [0]) {
      const bucket = bucketOf(day, hour, granularity);
      if (buckets[buckets.length - 1] !== bucket) buckets.push(bucket);
    }
  }
  const bucketIndex = new Map(buckets.map((bucket, index) => [bucket, index]));

  const cells = new Map<string, number[]>();
  const topTurns: CostStats["topTurns"] = [];
  for (let day = start; day <= Math.min(end, parseDay(today)); day += DAY_MS) {
    const dayNumber = Math.round(day / DAY_MS);
    const weekend = [0, 6].includes(new Date(day).getUTCDay());
    PROVIDERS.forEach((provider, providerIndex) => {
      USERS.forEach((user, userIndex) => {
        AGENTS.forEach((agent, agentIndex) => {
          const seed = dayNumber * 31 + providerIndex * 7 + userIndex * 13 + agentIndex * 17;
          const activity = noise(seed);
          if (activity < (weekend ? 0.7 : 0.35) + userIndex * 0.08 + agentIndex * 0.12) return;
          const turns = 1 + Math.floor(activity * (6 - userIndex));
          const amount = Number((turns * (0.4 + noise(seed + 1) * (providerIndex === 0 ? 5.5 : 2.4))).toFixed(4));
          const hour = 9 + Math.floor(noise(seed + 2) * 13);
          const botIndex = noise(seed + 3) > 0.8 ? 1 : 0;
          const modelIndex = providerIndex * 2 + (noise(seed + 4) > 0.7 ? 1 : 0);
          const bucket = bucketIndex.get(bucketOf(day, hour, granularity)) ?? 0;
          const key = [bucket, providerIndex, botIndex, agentIndex, userIndex, modelIndex, 0].join(":");
          const cell = cells.get(key) || [bucket, providerIndex, botIndex, agentIndex, userIndex, modelIndex, 0, 0, 0, 0];
          cell[7] = Number((cell[7] + amount).toFixed(6));
          cell[8] += turns;
          cell[9] += activity > 0.97 ? 1 : 0;
          cells.set(key, cell);
          topTurns.push({
            provider,
            recordedAt: `${formatDay(day)}T${String(hour).padStart(2, "0")}:${String(Math.floor(activity * 59)).padStart(2, "0")}:00${config.timeBasis.utcOffset}`,
            bot: BOTS[botIndex],
            agent,
            user,
            model: MODELS[modelIndex],
            currency: "USD",
            amount: Number((amount / turns * (1 + noise(seed + 5))).toFixed(4)),
            isPartial: activity > 0.97,
            conversationId: `conv_mock_${seed}`,
            turnId: `turn_mock_${seed}`,
          });
        });
      });
    });
  }

  const rows = [...cells.values()].sort((left, right) => left[0] - right[0]) as unknown as CostStatsRow[];
  const totals = PROVIDERS.map((provider, providerIndex) => {
    const own = rows.filter((row) => row[1] === providerIndex);
    return {
      provider,
      currency: "USD",
      amount: Number((own.reduce((sum, row) => sum + row[7], 0) * 0.82).toFixed(4)),
      turns: Math.round(own.reduce((sum, row) => sum + row[8], 0) * 0.9),
    };
  }).filter((item) => item.turns > 0);

  return {
    range: { startDate, endDate },
    granularity,
    enabled: { ...config.enabled },
    timeBasis: { ...config.timeBasis },
    availableRange: { ...config.availableRange },
    buckets,
    dimensions: { provider: PROVIDERS, bot: BOTS, agent: AGENTS, user: USERS, model: MODELS, currency: ["USD"] },
    rows,
    previousPeriod: {
      startDate: formatDay(start - days * DAY_MS),
      endDate: formatDay(start - DAY_MS),
      totals,
    },
    topTurns: (PROVIDERS as CostStatsProvider[]).flatMap((provider) => topTurns
      .filter((turn) => turn.provider === provider)
      .sort((left, right) => right.amount - left.amount)
      .slice(0, 10)),
  };
}
