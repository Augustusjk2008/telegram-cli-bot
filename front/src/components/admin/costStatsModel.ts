import type { CostStats, CostStatsGranularity, CostStatsProvider } from "../../services/types";

/** The breakdowns the panel can pivot the cube by without another request. */
export type CostGroupDimension = "user" | "bot" | "model";

/**
 * Labels follow the rest of the UI, where a Bot is shown as "智能体". Cluster child
 * tasks are deliberately not a dimension: their cost is summed into their Bot.
 */
export const COST_GROUP_DIMENSIONS: ReadonlyArray<{ key: CostGroupDimension; label: string }> = [
  { key: "user", label: "用户" },
  { key: "bot", label: "智能体" },
  { key: "model", label: "模型" },
];

/** Series beyond this many fold into "其他" so every series keeps a distinct color. */
export const COST_MAX_SERIES = 5;

const COLUMN = { bucket: 0, provider: 1, bot: 2, agent: 3, user: 4, model: 5, currency: 6, amount: 7, turns: 8, partial: 9 } as const;

export type CostSeries = {
  key: string;
  label: string;
  /** 1-based categorical color slot; `0` is the neutral "其他" bucket. */
  slot: number;
  total: number;
  turns: number;
  values: number[];
};

export type CostRankItem = {
  key: string;
  label: string;
  /** Matches the chart series color, or `0` when folded into "其他". */
  slot: number;
  total: number;
  turns: number;
  partialTurns: number;
  share: number;
};

export type CostView = {
  buckets: string[];
  bucketTotals: number[];
  series: CostSeries[];
  ranking: CostRankItem[];
  total: number;
  turns: number;
  partialTurns: number;
  peak: { bucket: string; amount: number } | null;
  previous: { amount: number; turns: number } | null;
};

export function costDimensionLabel(dimension: CostGroupDimension, value: string) {
  if (value) return value;
  return dimension === "user" ? "未署名" : "未知";
}

/** Currencies that actually carry cost for the provider, largest first. */
export function costCurrencies(stats: CostStats, provider: CostStatsProvider): string[] {
  const providerIndex = stats.dimensions.provider.indexOf(provider);
  const totals = new Map<number, number>();
  for (const row of stats.rows) {
    if (row[COLUMN.provider] !== providerIndex) continue;
    totals.set(row[COLUMN.currency], (totals.get(row[COLUMN.currency]) || 0) + row[COLUMN.amount]);
  }
  return [...totals.entries()]
    .sort((left, right) => right[1] - left[1])
    .map(([index]) => stats.dimensions.currency[index]);
}

export function buildCostView(
  stats: CostStats,
  options: { provider: CostStatsProvider; currency: string; dimension: CostGroupDimension },
): CostView {
  const providerIndex = stats.dimensions.provider.indexOf(options.provider);
  const currencyIndex = stats.dimensions.currency.indexOf(options.currency);
  const dimensionColumn = COLUMN[options.dimension];
  const labels = stats.dimensions[options.dimension];
  const bucketCount = stats.buckets.length;
  const bucketTotals = new Array<number>(bucketCount).fill(0);
  const groups = new Map<number, { total: number; turns: number; partialTurns: number; values: number[] }>();
  let total = 0;
  let turns = 0;
  let partialTurns = 0;

  for (const row of stats.rows) {
    if (row[COLUMN.provider] !== providerIndex || row[COLUMN.currency] !== currencyIndex) continue;
    const amount = row[COLUMN.amount];
    const bucket = row[COLUMN.bucket];
    let group = groups.get(row[dimensionColumn]);
    if (!group) {
      group = { total: 0, turns: 0, partialTurns: 0, values: new Array<number>(bucketCount).fill(0) };
      groups.set(row[dimensionColumn], group);
    }
    group.total += amount;
    group.turns += row[COLUMN.turns];
    group.partialTurns += row[COLUMN.partial];
    group.values[bucket] += amount;
    bucketTotals[bucket] += amount;
    total += amount;
    turns += row[COLUMN.turns];
    partialTurns += row[COLUMN.partial];
  }

  // 金额相同时按名称排序，保证同一份数据的配色稳定。
  const ordered = [...groups.entries()]
    .map(([index, group]) => ({ key: labels[index] ?? "", ...group }))
    .sort((left, right) => right.total - left.total || left.key.localeCompare(right.key));

  const leading = ordered.length > COST_MAX_SERIES ? ordered.slice(0, COST_MAX_SERIES - 1) : ordered;
  const rest = ordered.slice(leading.length);
  const series: CostSeries[] = leading.map((group, index) => ({
    key: group.key,
    label: costDimensionLabel(options.dimension, group.key),
    slot: index + 1,
    total: group.total,
    turns: group.turns,
    values: group.values,
  }));
  if (rest.length) {
    const values = new Array<number>(bucketCount).fill(0);
    for (const group of rest) group.values.forEach((value, index) => { values[index] += value; });
    series.push({
      key: "__other__",
      label: `其他 ${rest.length} 项`,
      slot: 0,
      total: rest.reduce((sum, group) => sum + group.total, 0),
      turns: rest.reduce((sum, group) => sum + group.turns, 0),
      values,
    });
  }

  const ranking: CostRankItem[] = ordered.map((group, index) => ({
    key: group.key,
    label: costDimensionLabel(options.dimension, group.key),
    slot: index < leading.length ? index + 1 : 0,
    total: group.total,
    turns: group.turns,
    partialTurns: group.partialTurns,
    share: total > 0 ? group.total / total : 0,
  }));

  let peak: CostView["peak"] = null;
  bucketTotals.forEach((amount, index) => {
    if (amount > 0 && (!peak || amount > peak.amount)) peak = { bucket: stats.buckets[index], amount };
  });

  const previousTotal = stats.previousPeriod.totals.find(
    (item) => item.provider === options.provider && item.currency === options.currency,
  );

  return {
    buckets: stats.buckets,
    bucketTotals,
    series,
    ranking,
    total,
    turns,
    partialTurns,
    peak,
    previous: previousTotal ? { amount: previousTotal.amount, turns: previousTotal.turns } : null,
  };
}

/** Inclusive number of calendar days in a `YYYY-MM-DD` range. */
export function costRangeDays(startDate: string, endDate: string) {
  const start = Date.parse(`${startDate}T00:00:00Z`);
  const end = Date.parse(`${endDate}T00:00:00Z`);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return 1;
  return Math.round((end - start) / 86_400_000) + 1;
}

const CURRENCY_SYMBOLS: Record<string, string> = { USD: "$", CNY: "¥", EUR: "€", GBP: "£", JPY: "¥" };

/** Amounts keep two decimals, and small ones keep enough digits to stay non-zero. */
export function formatCostAmount(amount: number, currency: string, options: { compact?: boolean } = {}) {
  const symbol = CURRENCY_SYMBOLS[currency];
  const absolute = Math.abs(amount);
  let text: string;
  if (options.compact && absolute >= 10_000) {
    text = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(amount);
  } else {
    const digits = absolute === 0 || absolute >= 1 ? 2 : absolute >= 0.01 ? 3 : 4;
    text = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: options.compact ? 0 : Math.min(digits, 2),
      maximumFractionDigits: digits,
    }).format(amount);
  }
  return symbol ? `${symbol}${text}` : `${text} ${currency}`;
}

/** Axis and tooltip label for one bucket of the requested granularity. */
export function formatCostBucket(bucket: string, granularity: CostStatsGranularity, style: "axis" | "full" = "axis") {
  const date = bucket.slice(0, 10);
  if (granularity === "hour") {
    const hour = `${bucket.slice(11, 13)}:00`;
    return style === "axis" ? hour : `${date.slice(5)} ${hour}`;
  }
  if (granularity === "month") return bucket.slice(0, 7);
  if (granularity === "week") return style === "axis" ? date.slice(5) : `${date} 起一周`;
  return style === "axis" ? date.slice(5) : date;
}

/** Rounds an axis maximum up to a 1/2/2.5/5 × 10ⁿ step so ticks stay readable. */
export function costAxisScale(maxValue: number, intervals = 4) {
  if (!(maxValue > 0)) return { max: 1, ticks: Array.from({ length: intervals + 1 }, (_, index) => index / intervals) };
  const rawStep = maxValue / intervals;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const step = [1, 2, 2.5, 5, 10].map((factor) => factor * magnitude).find((candidate) => candidate >= rawStep) || rawStep;
  const ticks = Array.from({ length: intervals + 1 }, (_, index) => Number((step * index).toPrecision(12)));
  return { max: ticks[intervals], ticks };
}
