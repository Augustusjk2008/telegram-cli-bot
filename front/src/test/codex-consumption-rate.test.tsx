import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { CodexUsagePanel } from "../components/admin/CodexUsagePanel";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { GENERAL_CODEX_RATE_LIMIT_ID, type CodexRateLimitSample } from "../services/types";
import { codexConsumptionRates } from "../utils/codexConsumptionRate";

function sample(hour: number, usedPercent: number, overrides: Partial<CodexRateLimitSample> = {}): CodexRateLimitSample {
  return {
    limitId: GENERAL_CODEX_RATE_LIMIT_ID,
    sampledAt: new Date(Date.UTC(2026, 8, 5, hour)).toISOString(),
    resetsAt: "2026-09-10T00:00:00Z",
    windowMinutes: 10080,
    planType: "pro",
    usedPercent,
    ...overrides,
  };
}

test("消耗速度按实际间隔计算百分点/小时，并区分零消耗和样本不足", () => {
  expect(codexConsumptionRates([])).toEqual([]);
  expect(codexConsumptionRates([sample(0, 10)])).toEqual([null]);
  expect(codexConsumptionRates([sample(0, 10), sample(2, 14), sample(3, 14), sample(7, 20)]))
    .toEqual([null, 2, 0, 1.5]);
});

test.each([
  { resetsAt: "2026-09-17T00:00:00Z", usedPercent: 2 },
  { resetsAt: "2026-09-17T00:00:00Z", usedPercent: 50 },
  { windowMinutes: 43200 },
  { usedPercent: 9 },
  { sampledAt: "2026-09-05T00:00:00Z" },
  { sampledAt: "invalid" },
  { resetsAt: "invalid" },
  { sampledAt: "2026-09-10T00:00:00Z" },
])("消耗速度跳过重置、回补、窗口变化和无效时间：%j", (overrides) => {
  expect(codexConsumptionRates([sample(0, 10), sample(1, 12, overrides)]))
    .toEqual([null, null]);
});

test("相同时间戳采用绝对时间比较", () => {
  expect(codexConsumptionRates([
    sample(0, 10),
    sample(2, 14, { sampledAt: "2026-09-05T10:00:00+08:00", resetsAt: "2026-09-10T08:00:00+08:00" }),
  ])).toEqual([null, 2]);
});

test("重复样本不产生瞬时速度，冲突时间点两侧均留空并在后续恢复", () => {
  expect(codexConsumptionRates([sample(0, 10), sample(1, 12), sample(1, 12), sample(2, 14)]))
    .toEqual([null, 2, null, 2]);
  expect(codexConsumptionRates([sample(0, 10), sample(1, 12), sample(1, 13), sample(2, 14), sample(3, 16)]))
    .toEqual([null, null, null, null, 2]);
});

test("右轴可切换消耗速度，保留额度曲线且不跨重置连接速率", async () => {
  const client = new MockWebBotClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    sample(0, 10), sample(2, 14),
    sample(3, 2, { resetsAt: "2026-09-17T00:00:00Z" }),
    sample(5, 8, { resetsAt: "2026-09-17T00:00:00Z" }),
  ];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);
  render(<CodexUsagePanel client={client} />);
  const chart = await screen.findByRole("img", { name: /通用 Codex.*剩余额度与剩余时长趋势/ });
  const quotaPath = chart.querySelector(".codex-usage-rate-limit-line")?.getAttribute("d");
  expect(screen.getByText("最近消耗 3 百分点/小时")).toBeInTheDocument();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "消耗速度" }));
  expect(screen.getByRole("button", { name: "消耗速度" })).toHaveAttribute("aria-pressed", "true");
  expect(chart).toHaveAccessibleName(/剩余额度与消耗速度趋势/);
  expect(chart.querySelector(".codex-usage-rate-limit-line")?.getAttribute("d")).toBe(quotaPath);
  expect(chart.querySelector(".codex-usage-rate-limit-duration-line")).toBeNull();
  const ratePath = chart.querySelector(".codex-usage-rate-limit-consumption-line")?.getAttribute("d");
  expect(ratePath?.match(/M /g)).toHaveLength(2);
  expect(ratePath).not.toMatch(/NaN|Infinity/);
  expect(Array.from(chart.querySelectorAll(".codex-usage-rate-limit-consumption-tick"), (tick) => tick.textContent))
    .toEqual(["0", "1", "2", "3", "4"]);
  await user.click(screen.getByRole("button", { name: "剩余时长" }));
  expect(chart.querySelector(".codex-usage-rate-limit-duration-line")).toBeInTheDocument();
  expect(chart.querySelector(".codex-usage-rate-limit-consumption-line")).toBeNull();
});

test("最新区间跨重置时不把过去的消耗速度显示为最近速度", async () => {
  const client = new MockWebBotClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [sample(0, 10), sample(1, 12), sample(2, 2, { resetsAt: "2026-09-17T00:00:00Z" })];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);
  render(<CodexUsagePanel client={client} />);
  expect(await screen.findByText("最近消耗 —")).toBeInTheDocument();
});
