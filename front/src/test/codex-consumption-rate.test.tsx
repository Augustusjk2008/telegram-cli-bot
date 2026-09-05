import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { CodexUsagePanel } from "../components/admin/CodexUsagePanel";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { GENERAL_CODEX_RATE_LIMIT_ID, type CodexRateLimitSample } from "../services/types";
import { codexConsumptionBars, codexConsumptionCurve, type QuotaCurveSegment } from "../utils/codexConsumptionRate";

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
  expect(curve.resetBridges.size).toBe(0);
});

test("reset 过渡连续且不越过两侧速度，普通导数和摘要保持原值", () => {
  const left: QuotaCurveSegment = { start: { x: 0, y: 0 }, end: { x: 1, y: 1 }, controls: [0, 0] };
  const reset: QuotaCurveSegment = { start: left.end, end: { x: 2, y: -100 }, reset: true };
  const right: QuotaCurveSegment = { start: reset.end, end: { x: 3, y: -91 }, controls: [-98, -95] };
  const curve = codexConsumptionCurve([left, reset, right], 1);
  const bridge = curve.resetBridges.get(2)!;
  expect(bridge.start).toEqual(curve.segments[0]!.end);
  expect(bridge.end).toEqual(curve.segments[2]!.start);
  expect(3 * (bridge.controls[0].y - bridge.start.y) / (bridge.end.x - bridge.start.x)).toBe(6);
  expect(3 * (bridge.end.y - bridge.controls[1].y) / (bridge.end.x - bridge.start.x)).toBe(6);
  const values = Array.from({ length: 21 }, (_, index) => {
    const t = index / 20;
    return (1 - t) ** 3 * bridge.start.y + 3 * (1 - t) ** 2 * t * bridge.controls[0].y
      + 3 * (1 - t) * t ** 2 * bridge.controls[1].y + t ** 3 * bridge.end.y;
  });
  expect(values[0]).toBe(3);
  expect(values.at(-1)).toBe(6);
  expect(values.every((value, index) => value >= 3 && value <= 6 && (!index || value >= values[index - 1]))).toBe(true);
  expect(curve.segments[0]).toEqual(codexConsumptionCurve([left], 1).segments[0]);
  expect(curve.segments[2]).toEqual(codexConsumptionCurve([right], 1).segments[0]);
  expect(curve.latestRate).toBe(12);
  expect(curve.maxRate).toBe(12);
});

test("连续 reset 可整体衔接，非 reset 无效间隔和单侧数据不外推", () => {
  const left: QuotaCurveSegment = { start: { x: 0, y: 0 }, end: { x: 1, y: 3 } };
  const resets: QuotaCurveSegment[] = [
    { start: left.end, end: { x: 2, y: -10 }, reset: true },
    { start: { x: 2, y: -10 }, end: { x: 3, y: -20 }, reset: true },
  ];
  const right: QuotaCurveSegment = { start: resets[1].end, end: { x: 4, y: -19 } };
  const curve = codexConsumptionCurve([left, ...resets, right], 1);
  const bridge = curve.resetBridges.get(3)!;
  expect(bridge.controls.map((point) => point.y)).toEqual([3, 1]);
  expect(bridge.start.x).toBe(1);
  expect(bridge.end.x).toBe(3);
  expect(codexConsumptionCurve([left, ...resets], 1).resetBridges.size).toBe(0);
  expect(codexConsumptionCurve([...resets, right], 1).resetBridges.size).toBe(0);
  expect(codexConsumptionCurve([left, { ...resets[0], reset: false, controls: [NaN, 0] }, resets[1], right], 1).resetBridges.size).toBe(0);
  expect(codexConsumptionCurve([left, { ...resets[0], end: left.end }, resets[1], right], 1).resetBridges.size).toBe(0);
  expect(codexConsumptionCurve([left, { ...resets[0], start: { x: 1.5, y: 3 } }, resets[1], right], 1).resetBridges.size).toBe(0);
});

test("右轴可切换消耗速度柱状图，保留额度曲线及重置过渡", async () => {
  const client = new MockWebBotClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    sample(0, 10), sample(2, 14),
    sample(3, 2, { resetsAt: "2026-09-17T00:00:00Z" }),
    sample(5, 8, { resetsAt: "2026-09-17T00:00:00Z" }),
  ].map((item) => ({ ...item, sampledAt: item.sampledAt.replace("Z", "+08:00") }));
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
  const bars = chart.querySelectorAll(".codex-usage-rate-limit-consumption-bar");
  expect(bars).toHaveLength(30);
  expect(bars[15].querySelector("title")).toHaveTextContent(
    "2026/09/05-02:30~02:40，2.62%每小时",
  );
  expect(Number(bars[15].getAttribute("height"))).toBeGreaterThan(0);
  expect(Array.from(chart.querySelectorAll(".codex-usage-rate-limit-consumption-tick"), (tick) => tick.textContent))
    .toEqual(["0", "1", "2", "3", "4"]);
  await user.click(screen.getByRole("button", { name: "剩余时长" }));
  expect(chart.querySelector(".codex-usage-rate-limit-duration-line")).toBeInTheDocument();
  expect(chart.querySelector(".codex-usage-rate-limit-consumption-bar")).toBeNull();
});

test("最新区间跨重置时不把过去的消耗速度显示为最近速度", async () => {
  const client = new MockWebBotClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [sample(0, 10), sample(1, 12), sample(2, 2, { resetsAt: "2026-09-17T00:00:00Z" })];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);
  render(<CodexUsagePanel client={client} />);
  expect(await screen.findByText("最近消耗 —")).toBeInTheDocument();
});

test("等宽速度柱对应平滑额度曲线的区间平均速度，随横轴范围调整", async () => {
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
  for (const [chartIndex, chart] of charts.entries()) {
    const quotaPath = chart.querySelector(".codex-usage-rate-limit-line")!.getAttribute("d")!;
    const quotaSegments = [...quotaPath.matchAll(/C ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+)/g)]
      .map((match) => match.slice(1).map(Number));
    const bars = [...chart.querySelectorAll(".codex-usage-rate-limit-consumption-bar")];
    expect(bars).toHaveLength(24);

    const quotaTicks = [...chart.querySelectorAll(".codex-usage-rate-limit-quota-tick")].map((tick) => parseFloat(tick.textContent!));
    const rateTicks = [...chart.querySelectorAll(".codex-usage-rate-limit-consumption-tick")].map((tick) => parseFloat(tick.textContent!));
    const quotaRange = quotaTicks.at(-1)! - quotaTicks[0];
    const rateRange = rateTicks.at(-1)! - rateTicks[0];
    const hours = chartIndex === 0 ? 2 : 48;
    const quotaYAt = (x: number) => {
      let [quotaX, quotaY] = quotaPath.split(" ").slice(1, 3).map(Number);
      for (const [, c1y, , c2y, endX, endY] of quotaSegments) {
        if (x <= endX + 1e-8) {
          const t = Math.min(1, Math.max(0, (x - quotaX) / (endX - quotaX)));
          return (1 - t) ** 3 * quotaY + 3 * (1 - t) ** 2 * t * c1y
            + 3 * (1 - t) * t ** 2 * c2y + t ** 3 * endY;
        }
        quotaX = endX;
        quotaY = endY;
      }
      throw new Error("区间超出额度曲线");
    };
    for (const bar of bars) {
      const barWidth = Number(bar.getAttribute("width"));
      const start = Number(bar.getAttribute("x")) - barWidth * 0.15 / 0.7;
      const end = start + barWidth / 0.7;
      const expectedRate = (quotaYAt(end) - quotaYAt(start)) / (end - start) * quotaRange / 176 * 512 / hours;
      const actualRate = Number(bar.getAttribute("height")) / 176 * rateRange;
      expect(actualRate).toBeCloseTo(expectedRate, 4);
      expect(barWidth).toBeCloseTo(512 / 24 * 0.7);
    }
  }
});

test("柱高精确平均跨曲线段的速度，并保留数据不足的空区间", () => {
  // dy/dx = 12t² over x=2t: the two one-unit bins average to 1 and 7.
  const curve = codexConsumptionCurve([{
    start: { x: 0, y: 0 }, end: { x: 2, y: 8 }, controls: [0, 0],
  }], 1);
  expect(codexConsumptionBars(curve, 0, 2, 2)).toEqual([
    { start: 0, end: 1, rate: 1 }, { start: 1, end: 2, rate: 7 },
  ]);
  const split = codexConsumptionCurve([
    { start: { x: 0, y: 0 }, end: { x: 0.25, y: 0.5 } },
    { start: { x: 0.25, y: 0.5 }, end: { x: 1, y: 3.5 } },
  ], 1);
  expect(codexConsumptionBars(split, 0, 1, 1)[0].rate).toBe(3.5);
  expect(codexConsumptionBars(curve, 0, 3, 3)).toHaveLength(2);
  expect(codexConsumptionBars(curve, 0, 2, 1)[0].rate).toBe(4);
});

test("消耗速度柱和坐标轴以 0 为下限", async () => {
  const falling = codexConsumptionCurve([{
    start: { x: 0, y: 8 }, end: { x: 2, y: 0 }, controls: [8, 8],
  }], 1);
  expect(codexConsumptionBars(falling, 0, 2, 2).map((bar) => bar.rate)).toEqual([0, 0]);

  const client = new MockWebBotClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [sample(0, 20), sample(1, 10), sample(2, 5)];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);
  render(<CodexUsagePanel client={client} />);
  await screen.findByRole("img", { name: /通用 Codex/ });
  await userEvent.setup().click(screen.getByRole("button", { name: "消耗速度" }));
  const chart = screen.getByRole("img", { name: /通用 Codex.*消耗速度趋势/ });
  const ticks = Array.from(
    chart.querySelectorAll(".codex-usage-rate-limit-consumption-tick"),
    (tick) => Number(tick.textContent),
  );
  expect(ticks[0]).toBe(0);
  expect(ticks.every((tick) => tick >= 0)).toBe(true);
  expect(screen.getByText("最近消耗 0 百分点/小时")).toBeInTheDocument();
  expect(Array.from(
    chart.querySelectorAll(".codex-usage-rate-limit-consumption-bar title"),
    (title) => title.textContent,
  ).every((title) => title?.endsWith("，0%每小时"))).toBe(true);
});

test("速度柱使用对齐到整点的固定区间，并允许首尾区间超出采样点", async () => {
  const client = new MockWebBotClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    sample(0, 10, { sampledAt: "2026-09-05T19:32:00+08:00" }),
    sample(10, 50, { sampledAt: "2026-09-06T05:32:00+08:00" }),
  ];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);
  render(<CodexUsagePanel client={client} />);
  await screen.findByRole("img", { name: /通用 Codex/ });
  await userEvent.setup().click(screen.getByRole("button", { name: "消耗速度" }));
  const chart = screen.getByRole("img", { name: /通用 Codex.*消耗速度趋势/ });
  const titles = Array.from(
    chart.querySelectorAll(".codex-usage-rate-limit-consumption-bar title"),
    (title) => title.textContent,
  );
  expect(titles[0]).toBe("2026/09/05-19:30~20:00，4%每小时");
  expect(titles[8]).toBe("2026/09/05-23:30~2026/09/06-00:00，4%每小时");
  expect(titles.at(-1)).toBe("2026/09/06-05:30~06:00，4%每小时");
  expect(titles.every((title) => !title?.includes("时间段") && !title?.includes("平均消耗"))).toBe(true);
});
