import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { GENERAL_CODEX_RATE_LIMIT_ID } from "../services/types";
import type { TunnelSnapshot } from "../services/types";

function createAdminClient() {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
  });
}

async function openCodexUsageTab(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 额度" }));
  await screen.findByRole("heading", { name: "Codex 额度" });
}

async function openNetworkTab(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "网络访问" }));
  await screen.findByRole("heading", { name: "公网访问" });
}

function fixedForwardSnapshot(overrides: Partial<TunnelSnapshot> = {}): TunnelSnapshot {
  return {
    mode: "fixed_public_forward",
    status: "error",
    source: "fixed_public_forward",
    publicUrl: "http://hub.example.test/node/node-a/",
    localUrl: "http://127.0.0.1:8765",
    lastError: "frps 端口不通/安全组未放通",
    verified: false,
    fixedPublicForwardEnabled: true,
    nodeId: "node-a",
    basePath: "/node/node-a",
    frpcStatus: "error",
    frpcPid: null,
    frpcLastError: "frps 端口不通/安全组未放通",
    heartbeatStatus: "error",
    heartbeatLastAt: "2026-08-18T01:52:39Z",
    heartbeatLastError: "Hub 心跳失败",
    ...overrides,
  };
}

test("固定公网转发异常时可以手动尝试恢复", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  vi.spyOn(client, "getTunnelStatus").mockResolvedValue(fixedForwardSnapshot());
  const restartTunnel = vi.spyOn(client, "restartTunnel").mockResolvedValue(fixedForwardSnapshot({
    status: "running",
    lastError: "",
    verified: true,
    frpcStatus: "running",
    frpcPid: 4321,
    frpcLastError: "",
    heartbeatStatus: "online",
    heartbeatLastError: "",
  }));

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openNetworkTab(user);
  await user.click(screen.getByRole("button", { name: "尝试恢复" }));

  await waitFor(() => expect(restartTunnel).toHaveBeenCalledTimes(1));
  expect(await screen.findByText("固定公网转发已恢复")).toBeInTheDocument();
});

test("Codex 额度趋势按额度桶分组", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples[0].sampledAt = "2026-07-20T18:45:00+08:00";
  stats.rateLimitSamples[0].resetsAt = "2026-07-20T18:45:00+08:00";
  stats.rateLimitSamples[1].sampledAt = "2026-07-21T18:45:00+08:00";
  stats.rateLimitSamples[1].resetsAt = "2026-07-25T06:45:00+08:00";
  stats.rateLimitSamples[2].sampledAt = "2026-07-26T18:45:00+08:00";
  stats.rateLimitSamples[2].resetsAt = "2026-08-02T18:45:00+08:00";
  stats.rateLimitSamples.push(
    {
      limitId: "codex_bengalfox",
      sampledAt: "2026-07-25T18:45:00+08:00",
      usedPercent: 40,
      windowMinutes: 300,
      resetsAt: "2026-07-25T20:45:00+08:00",
      planType: "pro",
    },
    {
      limitId: "codex_bengalfox",
      sampledAt: "2026-07-26T18:45:00+08:00",
      usedPercent: 50,
      windowMinutes: 300,
      resetsAt: "2026-07-26T19:45:00+08:00",
      planType: "pro",
    },
  );
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  const { container } = render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  const chart = await screen.findByRole("img", { name: /通用 Codex.*共 3 个样本，当前剩余 92%/ });
  expect(screen.getByRole("img", { name: /gpt-5\.3-codex-spark.*共 2 个样本/ })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "通用 Codex · Pro", level: 4 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "gpt-5.3-codex-spark · Pro", level: 4 })).toBeInTheDocument();
  expect(screen.getByText("当前剩余 92%")).toBeInTheDocument();
  expect(screen.getByText("剩余时长 7 天")).toBeInTheDocument();
  expect(screen.getByText("已用 8%")).toBeInTheDocument();
  expect(screen.getByText("7 天窗口")).toBeInTheDocument();
  expect(screen.queryByText("纵轴为剩余额度，固定显示 0% 至 100%。")).not.toBeInTheDocument();
  expect(screen.queryByText("暂无符合筛选条件的 Codex 额度数据。")).not.toBeInTheDocument();
  expect(screen.queryByText("总 token")).not.toBeInTheDocument();
  expect(chart.querySelector("title")?.textContent).toBe("通用 Codex · Pro 剩余额度与剩余时长趋势");
  expect(chart.querySelector("desc")?.textContent).toContain("剩余时长");
  const quotaAxisTitle = chart.querySelector(".codex-usage-rate-limit-quota-axis-title");
  const durationAxisTitle = chart.querySelector(".codex-usage-rate-limit-duration-axis-title");
  expect(quotaAxisTitle?.textContent).toBe("剩余额度");
  expect(durationAxisTitle?.textContent).toBe("剩余时长");
  expect(Number(quotaAxisTitle?.getAttribute("x"))).toBeLessThan(Number(durationAxisTitle?.getAttribute("x")));
  const durationTicks = Array.from(chart.querySelectorAll(".codex-usage-rate-limit-duration-tick"));
  expect(durationTicks.map((tick) => tick.textContent?.trim())).toEqual([
    "0 天", "1.75 天", "3.5 天", "5.25 天", "7 天",
  ]);
  expect(durationTicks.at(-1)?.getAttribute("y")).toBe("36");
  const quotaLine = container.querySelector(".codex-usage-rate-limit-line");
  const durationLine = container.querySelector(".codex-usage-rate-limit-duration-line");
  expect(quotaLine).toBeInTheDocument();
  expect(durationLine).toBeInTheDocument();
  expect(quotaLine?.getAttribute("points")).not.toBe(durationLine?.getAttribute("points"));
  expect(container.querySelector(".codex-usage-rate-limit-chart circle")).not.toBeInTheDocument();
  const durationCoordinates = durationLine?.getAttribute("points")?.split(" ").map((point) => (
    point.split(",").map(Number)
  ));
  expect(durationCoordinates?.map(([, y]) => y)).toEqual([208, 120, 32]);
  const xCoordinates = durationCoordinates?.map(([x]) => x) || [];
  const firstGap = xCoordinates[1] - xCoordinates[0];
  const secondGap = xCoordinates[2] - xCoordinates[1];
  expect(firstGap).toBeGreaterThan(0);
  expect(secondGap).toBeCloseTo(firstGap * 5);
});

test("Codex 额度趋势按套餐拆分相同额度桶", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-08-27T18:00:00+08:00",
      usedPercent: 57,
      windowMinutes: 10080,
      resetsAt: "2026-09-01T22:15:24+08:00",
      planType: "pro",
    },
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-08-27T19:00:00+08:00",
      usedPercent: 0,
      windowMinutes: 43200,
      resetsAt: "2026-09-26T19:00:00+08:00",
      planType: "free",
    },
  ];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  expect(await screen.findByRole("heading", { name: "通用 Codex · Pro", level: 4 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "通用 Codex · Free", level: 4 })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /通用 Codex · Pro.*共 1 个样本，当前剩余 43%/ })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /通用 Codex · Free.*共 1 个样本，当前剩余 100%/ })).toBeInTheDocument();
});

test("Codex Free 额度趋势按 30 天窗口显示剩余时长", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-08-27T19:00:00+08:00",
      usedPercent: 0,
      windowMinutes: 43200,
      resetsAt: "2026-09-26T19:00:00+08:00",
      planType: "free",
    },
  ];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  const chart = await screen.findByRole("img", { name: /通用 Codex · Free.*剩余时长 30 天/ });
  const durationTicks = Array.from(chart.querySelectorAll(".codex-usage-rate-limit-duration-tick"));
  expect(screen.getByText("剩余时长 30 天")).toBeInTheDocument();
  expect(durationTicks.at(-1)?.textContent?.trim()).toBe("30 天");
});

test("Codex 额度趋势仅有一个样本时不绘制折线或数据点", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = stats.rateLimitSamples.slice(0, 1);
  stats.rateLimitSamples[0].resetsAt = "not-a-time";
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  const { container } = render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  await screen.findByRole("img", { name: /共 1 个样本/ });
  expect(screen.getByText("剩余时长 0 分钟")).toBeInTheDocument();
  expect(container.querySelector(".codex-usage-rate-limit-chart circle")).not.toBeInTheDocument();
  expect(container.querySelector(".codex-usage-rate-limit-line")).not.toBeInTheDocument();
  expect(container.querySelector(".codex-usage-rate-limit-duration-line")).not.toBeInTheDocument();
});

test("Codex 额度趋势纵轴按额度和时长的查询范围同步缩放", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-07-20T00:00:00+08:00",
      usedPercent: 90,
      windowMinutes: 10080,
      resetsAt: "2026-07-22T02:24:00+08:00",
      planType: "pro",
    },
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-07-21T00:00:00+08:00",
      usedPercent: 40,
      windowMinutes: 10080,
      resetsAt: "2026-07-25T21:36:00+08:00",
      planType: "pro",
    },
  ];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  const chart = await screen.findByRole("img", { name: /通用 Codex.*共 2 个样本/ });
  const quotaTicks = Array.from(chart.querySelectorAll(".codex-usage-rate-limit-quota-tick"));
  const durationTicks = Array.from(chart.querySelectorAll(".codex-usage-rate-limit-duration-tick"));
  expect(quotaTicks.map((tick) => tick.textContent?.trim())).toEqual([
    "10%", "25%", "40%", "55%", "70%",
  ]);
  expect(durationTicks.map((tick) => tick.textContent?.trim())).toEqual([
    "0.7 天", "1.75 天", "2.8 天", "3.85 天", "4.9 天",
  ]);
  expect(chart.querySelector("desc")?.textContent).toContain("左轴为10%到70%");
  expect(chart.querySelector("desc")?.textContent).toContain("右轴为0.7天到4.9天");
});

test("Codex 额度趋势没有样本时仍显示通用和次要额度入口", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  expect(await screen.findByText("暂无通用 Codex 限额样本。")).toBeInTheDocument();
  expect(screen.getByText("暂无 gpt-5.3-codex-spark 限额样本。")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "通用 Codex", level: 4 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "gpt-5.3-codex-spark", level: 4 })).toBeInTheDocument();
  expect(screen.queryByRole("img", { name: /Codex 剩余额度与剩余时长趋势/ })).not.toBeInTheDocument();
});
