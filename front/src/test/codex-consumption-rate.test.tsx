import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { CodexUsagePanel } from "../components/admin/CodexUsagePanel";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { GENERAL_CODEX_RATE_LIMIT_ID, type CodexRateLimitSample } from "../services/types";
import { codexConsumptionCurve, type QuotaCurveSegment } from "../utils/codexConsumptionRate";

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

test("直接对三次额度曲线求导，保留二次速度曲线及末端斜率", () => {
  // x = 2t, screen y = 8t³, hence dy/dx = 12t².
  const curve = codexConsumptionCurve([{
    start: { x: 0, y: 0 }, end: { x: 2, y: 8 }, controls: [0, 0],
  }], 1);
  const segment = curve.segments[0]!;
  for (const t of [0, 0.25, 0.5, 0.75, 1]) {
    const rate = (1 - t) ** 2 * segment.start.y
      + 2 * (1 - t) * t * segment.control.y + t ** 2 * segment.end.y;
    expect(rate).toBeCloseTo(12 * t ** 2);
  }
  expect(curve.latestRate).toBe(12);
  expect(curve.maxRate).toBe(12);
});

test("速度范围包含曲线内部极值，不把贝塞尔控制值当作峰值", () => {
  const quota: QuotaCurveSegment = {
    start: { x: 0, y: 0 }, end: { x: 1, y: 1 }, controls: [0, 1],
  };
  const curve = codexConsumptionCurve([quota], 1);
  expect(curve.maxRate).toBe(1.5);
  expect(curve.latestRate).toBe(0);
  const falling = codexConsumptionCurve([{ ...quota, end: { x: 1, y: -1 }, controls: [0, -1] }], 1);
  expect(falling.minRate).toBe(-1.5);
});

test("屏幕斜率按真实横轴时间和额度纵轴转换为百分点/小时", () => {
  const quota: QuotaCurveSegment = { start: { x: 64, y: 32 }, end: { x: 576, y: 208 } };
  const unitsPerSlope = (100 / 176) * (512 / (2 * 3600000)) * 3600000;
  expect(codexConsumptionCurve([quota], unitsPerSlope).latestRate).toBeCloseTo(50);
  expect(codexConsumptionCurve([quota], unitsPerSlope / 2).latestRate).toBeCloseTo(25);
});

test("重置连接、重复横坐标和无效时间范围不求导，正常平段为零", () => {
  const flat: QuotaCurveSegment = { start: { x: 0, y: 10 }, end: { x: 2, y: 10 } };
  expect(codexConsumptionCurve([flat], 1).latestRate).toBe(0);
  expect(codexConsumptionCurve([], 1).latestRate).toBeNull();
  for (const units of [0, NaN, Infinity]) {
    expect(codexConsumptionCurve([flat], units).segments).toEqual([null]);
  }
  const curve = codexConsumptionCurve([
    flat,
    { ...flat, reset: true },
    { ...flat, end: { x: 0, y: 20 } },
  ], 1);
  expect(curve.segments.slice(1)).toEqual([null, null]);
  expect(curve.latestRate).toBeNull();
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

test("速度曲线逐段对应平滑额度的导数，并随横轴范围一起调整", async () => {
  const client = new MockWebBotClient();
  const stats = await client.getCodexUsageStats();
  const denseSamples = (limitId: string, finalHour: number) => [
    ...Array.from({ length: 50 }, (_, index) => sample(0, 10 + (index / 10) ** 2, {
      limitId,
      sampledAt: new Date(Date.UTC(2026, 8, 5, 0, index)).toISOString(),
    })),
    sample(finalHour, 40, { limitId }),
  ];
  stats.rateLimitSamples = [...denseSamples("codex", 2), ...denseSamples("codex_bengalfox", 48)];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);
  render(<CodexUsagePanel client={client} />);
  await screen.findByRole("img", { name: /通用 Codex/ });
  await userEvent.setup().click(screen.getByRole("button", { name: "消耗速度" }));
  const charts = screen.getAllByRole("img");
  const segmentCounts: number[] = [];
  for (const [chartIndex, chart] of charts.entries()) {
    const quotaPath = chart.querySelector(".codex-usage-rate-limit-line")!.getAttribute("d")!;
    const ratePath = chart.querySelector(".codex-usage-rate-limit-consumption-line")!.getAttribute("d")!;
    const quotaSegments = [...quotaPath.matchAll(/C ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+)/g)]
      .map((match) => match.slice(1).map(Number));
    const rateSegments = [...ratePath.matchAll(/Q ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+)/g)]
      .map((match) => match.slice(1).map(Number));
    expect(rateSegments).toHaveLength(quotaSegments.length);
    expect(ratePath.match(/M /g)).toHaveLength(1);
    segmentCounts.push(rateSegments.length);

    const quotaTicks = [...chart.querySelectorAll(".codex-usage-rate-limit-quota-tick")].map((tick) => parseFloat(tick.textContent!));
    const rateTicks = [...chart.querySelectorAll(".codex-usage-rate-limit-consumption-tick")].map((tick) => parseFloat(tick.textContent!));
    const quotaRange = quotaTicks.at(-1)! - quotaTicks[0];
    const rateRange = rateTicks.at(-1)! - rateTicks[0];
    const hours = chartIndex === 0 ? 2 : 48;
    let [quotaX, quotaY] = quotaPath.split(" ").slice(1, 3).map(Number);
    let rateY = Number(ratePath.split(" ")[2]);
    for (const [index, [c1x, c1y, c2x, c2y, endX, endY]] of quotaSegments.entries()) {
      const [controlX, controlY, rateEndX, rateEndY] = rateSegments[index];
      expect(controlX).toBeCloseTo((quotaX + endX) / 2);
      expect(rateEndX).toBe(endX);
      // Compare the rendered derivative with a finite difference of the rendered quota cubic.
      const yAt = (t: number) => (1 - t) ** 3 * quotaY + 3 * (1 - t) ** 2 * t * c1y
        + 3 * (1 - t) * t ** 2 * c2y + t ** 3 * endY;
      expect(c1x).toBeCloseTo(quotaX + (endX - quotaX) / 3);
      expect(c2x).toBeCloseTo(quotaX + 2 * (endX - quotaX) / 3);
      for (const t of [0.2, 0.5, 0.8]) {
        const screenSlope = (yAt(t + 1e-5) - yAt(t - 1e-5)) / (2e-5 * (endX - quotaX));
        const expectedRate = screenSlope * quotaRange / 176 * 512 / hours;
        const renderedY = (1 - t) ** 2 * rateY + 2 * (1 - t) * t * controlY + t ** 2 * rateEndY;
        const actualRate = rateTicks.at(-1)! - (renderedY - 32) / 176 * rateRange;
        expect(actualRate).toBeCloseTo(expectedRate, 4);
      }
      quotaX = endX;
      quotaY = endY;
      rateY = rateEndY;
    }
  }
  expect(segmentCounts[0]).toBeGreaterThan(segmentCounts[1]);
});
