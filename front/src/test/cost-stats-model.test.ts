import { expect, test } from "vitest";
import { buildCostView, costAxisScale, costCurrencies, formatCostAmount } from "../components/admin/costStatsModel";
import type { CostStats, CostStatsRow } from "../services/types";

function stats(rows: CostStatsRow[]): CostStats {
  return {
    range: { startDate: "2026-11-15", endDate: "2026-11-17" },
    granularity: "day",
    enabled: { codex: true, claude: true },
    timeBasis: { mode: "server_local", utcOffset: "+13:00", today: "2026-11-17" },
    availableRange: { firstDate: "2026-11-15", lastDate: "2026-11-17" },
    buckets: ["2026-11-15", "2026-11-16", "2026-11-17"],
    dimensions: {
      provider: ["claude", "codex"],
      bot: ["main"],
      agent: ["main"],
      user: ["u1", "u2", "u3", "u4", "u5", "u6", ""],
      model: ["claude-opus-5-5"],
      currency: ["USD", "CNY"],
    },
    rows,
    previousPeriod: {
      startDate: "2026-11-12",
      endDate: "2026-11-14",
      totals: [{ provider: "claude", currency: "USD", amount: 5, turns: 2 }],
    },
    topTurns: [],
  };
}

// [bucket, provider, bot, agent, user, model, currency, amount, turns, partialTurns]
const row = (bucket: number, user: number, amount: number, provider = 0, currency = 0): CostStatsRow =>
  [bucket, provider, 0, 0, user, 0, currency, amount, 1, 0];

test("pivots one provider and currency, keeps rank colors and folds the tail into 其他", () => {
  const data = stats([
    row(0, 0, 6), row(1, 0, 4), row(2, 1, 8), row(0, 2, 3), row(1, 3, 2),
    row(2, 4, 1.5), row(2, 5, 0.5), row(0, 6, 1),
    row(0, 0, 100, 1), // Codex never leaks into the Claude view.
    row(0, 0, 50, 0, 1), // Neither does another currency.
  ]);

  const view = buildCostView(data, { provider: "claude", currency: "USD", dimension: "user" });

  expect(view.total).toBe(26);
  expect(view.turns).toBe(8);
  expect(view.bucketTotals).toEqual([10, 6, 10]);
  expect(view.series.map((series) => [series.label, series.slot, series.total])).toEqual([
    ["u1", 1, 10], ["u2", 2, 8], ["u3", 3, 3], ["u4", 4, 2], ["其他 3 项", 0, 3],
  ]);
  expect(view.series.at(-1)?.values).toEqual([1, 0, 2]);
  expect(view.ranking.map((item) => [item.label, item.slot])).toEqual([
    ["u1", 1], ["u2", 2], ["u3", 3], ["u4", 4], ["u5", 0], ["未署名", 0], ["u6", 0],
  ]);
  expect(view.peak).toEqual({ bucket: "2026-11-15", amount: 10 });
  expect(view.previous).toEqual({ amount: 5, turns: 2 });
  expect(costCurrencies(data, "claude")).toEqual(["CNY", "USD"]);
});

test("rounds the axis to readable steps and formats small amounts without hiding them", () => {
  expect(costAxisScale(7.3)).toEqual({ max: 8, ticks: [0, 2, 4, 6, 8] });
  expect(costAxisScale(9).ticks).toEqual([0, 2.5, 5, 7.5, 10]);
  expect(costAxisScale(0).max).toBe(1);
  expect(formatCostAmount(1234.5, "USD")).toBe("$1,234.50");
  expect(formatCostAmount(0.0042, "USD")).toBe("$0.0042");
  expect(formatCostAmount(12.5, "CNY")).toBe("¥12.50");
  expect(formatCostAmount(3, "AUD")).toBe("3.00 AUD");
});
