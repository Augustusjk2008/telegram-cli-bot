import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { TransferBridgeConfigInput, TransferBridgeStatus } from "../services/types";

function transferStatus(overrides: Partial<TransferBridgeStatus> = {}): TransferBridgeStatus {
  return {
    enabled: true,
    configured: true,
    running: true,
    status: "running",
    localUrl: "http://127.0.0.1:8080",
    bridgePageUrl: "/api/transfer/page",
    responsesBaseUrl: "http://127.0.0.1:8080/v1",
    chatCompletionsBaseUrl: "http://127.0.0.1:8080/v1",
    litellmModel: "openai/gpt-5",
    modelAlias: "gpt-5",
    endpointMode: "auto",
    extraLitellmParams: {},
    providerBaseUrl: "https://provider.example/v1",
    providerApiKeySet: true,
    routes: [{
      id: "default",
      endpointMode: "auto",
      litellmModel: "openai/gpt-5",
      modelAlias: "gpt-5",
      providerBaseUrl: "https://provider.example/v1",
      extraLitellmParams: {},
      providerApiKeySet: true,
    }],
    requestCount: 1,
    totalInputTokens: 2,
    totalOutputTokens: 3,
    totalBytesIn: 4,
    totalBytesOut: 5,
    ...overrides,
  };
}

function createAdminClient(status = transferStatus()) {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getTransferAdminStatus: vi.fn(async () => status),
  });
}

async function openTransferTab(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "LiteLLM 网关" }));
  await screen.findByRole("heading", { name: "LiteLLM 网关" });
}

async function openCodexUsageTab(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));
  await screen.findByRole("heading", { name: "Codex 用量" });
}

test("Transfer Admin Center exposes only providerApiKeySet, never an upstream key returned by status", async () => {
  const user = userEvent.setup();
  const leakedStatus = Object.assign(transferStatus(), { providerApiKey: "sk-status-must-not-render" });
  const client = createAdminClient(leakedStatus);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openTransferTab(user);

  expect(screen.getByText("运行中")).toBeInTheDocument();
  expect(screen.getByText("已设置")).toBeInTheDocument();
  expect(screen.getByLabelText("上游 API key")).toHaveValue("");
  expect(screen.getByRole("link", { name: "打开网关调试页面" })).toHaveAttribute("href", "/api/transfer/page");
  expect(screen.queryByText("sk-status-must-not-render")).not.toBeInTheDocument();
});

test("Transfer Admin Center saves an explicit route config without weakening key handling", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const updateTransferBridgeConfig = vi.spyOn(client, "updateTransferBridgeConfig");

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openTransferTab(user);

  await user.clear(screen.getByLabelText("上游 base URL"));
  await user.type(screen.getByLabelText("上游 base URL"), "https://api.example.test/v1");
  await user.clear(screen.getByLabelText("LiteLLM model"));
  await user.type(screen.getByLabelText("LiteLLM model"), "openai/gpt-next");
  await user.clear(screen.getByLabelText("模型别名"));
  await user.type(screen.getByLabelText("模型别名"), "gpt-next");
  await user.selectOptions(screen.getByLabelText("LiteLLM endpoint mode"), "responses");
  await user.type(screen.getByLabelText("上游 API key"), "sk-new");
  fireEvent.change(screen.getByLabelText("高级 LiteLLM params JSON"), { target: { value: '{"rpm":120}' } });
  await user.click(screen.getByRole("button", { name: "保存网关配置" }));

  await waitFor(() => expect(updateTransferBridgeConfig).toHaveBeenCalledTimes(1));
  expect(updateTransferBridgeConfig).toHaveBeenCalledWith(expect.objectContaining<Partial<TransferBridgeConfigInput>>({
    routes: [expect.objectContaining({
      endpointMode: "responses",
      litellmModel: "openai/gpt-next",
      modelAlias: "gpt-next",
      providerBaseUrl: "https://api.example.test/v1",
      providerApiKey: "sk-new",
      clearProviderApiKey: false,
      extraLitellmParams: { rpm: 120 },
    })],
  }));
  expect(await screen.findByText("网关配置已保存")).toBeInTheDocument();
});

test("Transfer Admin Center rejects advanced params that could override the upstream API key", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const updateTransferBridgeConfig = vi.spyOn(client, "updateTransferBridgeConfig");

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openTransferTab(user);
  fireEvent.change(screen.getByLabelText("高级 LiteLLM params JSON"), { target: { value: '{"api_key":"sk-override"}' } });
  await user.click(screen.getByRole("button", { name: "保存网关配置" }));

  expect(updateTransferBridgeConfig).not.toHaveBeenCalled();
  expect(await screen.findByText("高级 LiteLLM params 不能包含 api_key")).toBeInTheDocument();
});

test("Codex 用量趋势展示双曲线、不绘制数据点并支持仅限额样本状态", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.totals = {
    requestCount: 0,
    inputTokens: 0,
    cachedInputTokens: 0,
    uncachedInputTokens: 0,
    outputTokens: 0,
    reasoningOutputTokens: 0,
    totalTokens: 0,
    cacheHitRate: null,
  };
  stats.byProvider = [];
  stats.byProviderModel = [];
  stats.byDay = [];
  stats.dailyByProvider = [];
  stats.dailyByProviderModel = [];
  stats.rateLimitSamples[0].sampledAt = "2026-07-20T18:45:00+08:00";
  stats.rateLimitSamples[0].resetsAt = "2026-07-20T18:45:00+08:00";
  stats.rateLimitSamples[1].sampledAt = "2026-07-21T18:45:00+08:00";
  stats.rateLimitSamples[1].resetsAt = "2026-07-25T06:45:00+08:00";
  stats.rateLimitSamples[2].sampledAt = "2026-07-26T18:45:00+08:00";
  stats.rateLimitSamples[2].resetsAt = "2026-08-02T18:45:00+08:00";
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  const { container } = render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  const chart = await screen.findByRole("img", { name: /共 3 个样本，当前剩余 92%/ });
  expect(screen.getByText("当前剩余 92%")).toBeInTheDocument();
  expect(screen.getByText("剩余时长 7 天")).toBeInTheDocument();
  expect(screen.getByText("已用 8%")).toBeInTheDocument();
  expect(screen.getByText("7 天窗口")).toBeInTheDocument();
  expect(screen.queryByText("纵轴为剩余额度，固定显示 0% 至 100%。")).not.toBeInTheDocument();
  expect(screen.queryByText("暂无符合筛选条件的 Codex 用量数据。")).not.toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Codex 用量 Provider 汇总" })).not.toBeInTheDocument();
  expect(chart.querySelector("title")?.textContent).toBe("通用 Codex 剩余额度与剩余时长趋势");
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

test("Codex 用量趋势仅有一个样本时不绘制折线或数据点", async () => {
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

test("Codex 用量趋势在没有官方限额样本时显示中文空状态", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  expect(await screen.findByText(
    "暂无通用 Codex 限额样本；开启采集并完成一次 OpenAI 官方 Codex turn 后显示。",
  )).toBeInTheDocument();
  expect(screen.queryByRole("img", { name: /通用 Codex 剩余额度与剩余时长趋势/ })).not.toBeInTheDocument();
});

test("Codex 用量 Provider 筛选排除 OpenAI 官方时清空趋势", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const getCodexUsageStats = vi.spyOn(client, "getCodexUsageStats");

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);
  await screen.findByRole("img", { name: /通用 Codex 剩余额度与剩余时长趋势/ });

  await user.click(screen.getByLabelText("筛选 Provider：OpenAI 官方"));
  await user.click(screen.getByRole("button", { name: "查询" }));

  await waitFor(() => expect(getCodexUsageStats).toHaveBeenLastCalledWith(expect.objectContaining({
    providerKeys: ["base_url:https://api.example.test/v1"],
  })));
  expect(await screen.findByText(
    "暂无通用 Codex 限额样本；开启采集并完成一次 OpenAI 官方 Codex turn 后显示。",
  )).toBeInTheDocument();
  expect(screen.queryByText("当前剩余 92%")).not.toBeInTheDocument();
});
