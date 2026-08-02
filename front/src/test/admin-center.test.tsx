import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { CodexUsageStats, NotificationSettingsStatus, TransferBridgeConfigInput, TransferBridgeStatus, TunnelSnapshot } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function createAdminClient(transferStatus: TransferBridgeStatus): WebBotClient {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getTransferAdminStatus: vi.fn(async () => transferStatus),
  });
}

const codexUsageConfigFixture = {
  enabled: false,
  currentProvider: {
    key: "openai_official",
    kind: "openai_official",
    label: "OpenAI 官方",
    baseUrl: null,
    resolution: "resolved",
  },
  timeBasis: {
    mode: "server_local",
    utcOffset: "+08:00",
    today: "2026-07-26",
  },
  availableRange: {
    firstDate: "2026-07-20",
    lastDate: "2026-07-26",
  },
};

const codexUsageStatsFixture = {
  range: {
    startDate: "2026-06-27",
    endDate: "2026-07-26",
  },
  enabled: false,
  timeBasis: codexUsageConfigFixture.timeBasis,
  availableRange: codexUsageConfigFixture.availableRange,
  availableProviders: [codexUsageConfigFixture.currentProvider],
  selectedProviderKeys: [],
  totals: {
    requestCount: 42,
    inputTokens: 1200,
    cachedInputTokens: 300,
    uncachedInputTokens: 900,
    outputTokens: 400,
    reasoningOutputTokens: 80,
    totalTokens: 1600,
    cacheHitRate: 0.25,
  },
  byProvider: [{
    provider: codexUsageConfigFixture.currentProvider,
    requestCount: 42,
    inputTokens: 1200,
    cachedInputTokens: 300,
    uncachedInputTokens: 900,
    outputTokens: 400,
    reasoningOutputTokens: 80,
    totalTokens: 1600,
    cacheHitRate: 0.25,
  }],
  byDay: [{
    date: "2026-07-26",
    requestCount: 42,
    inputTokens: 1200,
    cachedInputTokens: 300,
    uncachedInputTokens: 900,
    outputTokens: 400,
    reasoningOutputTokens: 80,
    totalTokens: 1600,
    cacheHitRate: 0.25,
  }],
  dailyByProvider: [{
    date: "2026-07-26",
    provider: codexUsageConfigFixture.currentProvider,
    requestCount: 42,
    inputTokens: 1200,
    cachedInputTokens: 300,
    uncachedInputTokens: 900,
    outputTokens: 400,
    reasoningOutputTokens: 80,
    totalTokens: 1600,
    cacheHitRate: 0.25,
  }],
  dailyPagination: {
    page: 1,
    pageSize: 10,
    totalItems: 1,
    totalPages: 1,
    hasPrevious: false,
    hasNext: false,
  },
};

function createPagedCodexUsageStats(page: number, pageSize: number, totalItems = 101) {
  const allRows = Array.from({ length: totalItems }, (_, index) => {
    const ordinal = index + 1;
    return {
      date: "2026-07-26",
      provider: codexUsageConfigFixture.currentProvider,
      model: `model-${String(ordinal).padStart(3, "0")}`,
      requestCount: ordinal,
      inputTokens: ordinal * 10,
      cachedInputTokens: ordinal,
      uncachedInputTokens: ordinal * 9,
      outputTokens: ordinal * 5,
      reasoningOutputTokens: 0,
      totalTokens: ordinal * 15,
      cacheHitRate: 0.1,
    };
  });
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const rows = allRows.slice((page - 1) * pageSize, page * pageSize);
  return {
    ...codexUsageStatsFixture,
    dailyByProvider: rows.map(({ model: _model, ...row }) => row),
    dailyByProviderModel: rows,
    dailyPagination: {
      page,
      pageSize,
      totalItems,
      totalPages,
      hasPrevious: page > 1,
      hasNext: page < totalPages,
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("管理中心 LiteLLM 网关 tab 显示状态、链接和 Codex 配置提示", async () => {
  const user = userEvent.setup();
  const client = createAdminClient({
    enabled: true,
    configured: true,
    running: true,
    status: "running",
    localUrl: "http://127.0.0.1:8080",
    bridgePageUrl: "/api/transfer/page",
    responsesBaseUrl: "http://127.0.0.1:8080/v1",
    chatCompletionsBaseUrl: "http://127.0.0.1:8080/v1",
    litellmRunning: true,
    litellmPid: 4321,
    litellmModel: "openai/gpt-5",
    modelAlias: "gpt-5",
    endpointMode: "auto",
    extraLitellmParams: {},
    providerBaseUrl: "https://max.jojocode.com/v1",
    providerApiKeySet: true,
    dropParams: true,
    requestCount: 1,
    totalInputTokens: 15381,
    totalOutputTokens: 30,
    totalBytesIn: 75420,
    totalBytesOut: 3400,
    startedAt: "2026-06-29T12:00:00Z",
    lastRequestAt: "2026-06-29T12:01:00Z",
    lastError: "",
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "LiteLLM 网关" }));

  expect(await screen.findByRole("heading", { name: "LiteLLM 网关" })).toBeInTheDocument();
  expect(screen.getByText("运行中")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "打开网关调试页面" })).toHaveAttribute("href", "/api/transfer/page");
  expect(screen.getByText("http://127.0.0.1:8080/v1")).toBeInTheDocument();
  expect(screen.getByText("openai/gpt-5")).toBeInTheDocument();
  expect(screen.getByText("gpt-5")).toBeInTheDocument();
  expect(screen.getByText("已设置")).toBeInTheDocument();
  expect(screen.getByLabelText("上游 base URL")).toHaveValue("https://max.jojocode.com/v1");
  expect(screen.getByLabelText("LiteLLM model")).toHaveValue("openai/gpt-5");
  expect(screen.getByLabelText("模型别名")).toHaveValue("gpt-5");
  expect(screen.getByLabelText("LiteLLM endpoint mode")).toHaveValue("auto");
  expect(screen.getByLabelText("高级 LiteLLM params JSON")).toHaveValue("{}");
  expect(screen.getByLabelText("启用 LiteLLM 网关")).toBeChecked();
  expect(screen.getByText("request_count = 1")).toBeInTheDocument();
  expect(screen.getByText("wire_api = \"responses\"")).toBeInTheDocument();
  expect(screen.queryByLabelText("转换类型")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("上游 API")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("reasoning mode")).not.toBeInTheDocument();
  expect(screen.queryByText("developer 消息降级为 system")).not.toBeInTheDocument();
});

test("管理中心 LiteLLM 网关 tab 显示未配置提示", async () => {
  const user = userEvent.setup();
  const client = createAdminClient({
    enabled: false,
    configured: false,
    running: false,
    status: "not_configured",
    localUrl: "http://127.0.0.1:8080",
    bridgePageUrl: "/api/transfer/page",
    responsesBaseUrl: "http://127.0.0.1:8080/v1",
    chatCompletionsBaseUrl: "http://127.0.0.1:8080/v1",
    providerApiKeySet: false,
    requestCount: 0,
    totalInputTokens: 0,
    totalOutputTokens: 0,
    totalBytesIn: 0,
    totalBytesOut: 0,
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "LiteLLM 网关" }));

  expect(await screen.findByText("未配置")).toBeInTheDocument();
  expect(screen.getByText("LiteLLM 网关尚未配置模型或上游 API key。")).toBeInTheDocument();
  expect(screen.getByLabelText("启用 LiteLLM 网关")).not.toBeChecked();
  expect(screen.getByText("未设置")).toBeInTheDocument();
});

test("管理中心网络访问 tab 保存 Git 代理并显示固定公网转发详情", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateGitProxySettings = vi.spyOn(client, "updateGitProxySettings");
  const fixedTunnel: TunnelSnapshot = {
    mode: "fixed_public_forward",
    status: "error",
    source: "fixed_public_forward",
    publicUrl: "http://124.221.226.63:18088/node/nanjing-laptop",
    localUrl: "http://127.0.0.1:8765",
    lastError: "dial tcp 124.221.226.63:7000: i/o timeout",
    verified: false,
    fixedPublicForwardEnabled: true,
    nodeId: "nanjing-laptop",
    basePath: "/node/nanjing-laptop",
    frpcStatus: "error",
    frpcPid: null,
    frpcLastError: "login to server failed: authorization failed",
    heartbeatStatus: "error",
    heartbeatLastAt: "",
    heartbeatLastError: "heartbeat 403 forbidden: invalid node token",
  };
  vi.spyOn(client, "getTunnelStatus").mockResolvedValue(fixedTunnel);
  vi.spyOn(client, "listAdminUsers").mockResolvedValue([]);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "网络访问" }));
  await user.type(await screen.findByLabelText("Git 代理地址"), "7897");
  await user.click(screen.getByRole("button", { name: "保存 Git 代理" }));

  expect(updateGitProxySettings).toHaveBeenCalledWith("7897");
  expect(await screen.findByText("Git 代理设置已保存")).toBeInTheDocument();
  expect(screen.getByText("固定公网转发")).toBeInTheDocument();
  expect(screen.getByText("frpc 状态")).toBeInTheDocument();
  expect(screen.getByText("Node ID:")).toBeInTheDocument();
  expect(screen.getByText("nanjing-laptop")).toBeInTheDocument();
  expect(screen.getByText("错误: login to server failed: authorization failed")).toBeInTheDocument();
  expect(screen.getByText("提示: frps token 错")).toBeInTheDocument();
  expect(screen.getByText("错误: heartbeat 403 forbidden: invalid node token")).toBeInTheDocument();
  expect(screen.getByText("提示: 节点 token 错")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "启动 Tunnel" })).not.toBeInTheDocument();
});

test("管理中心通知 tab 显示 PushPlus 状态、测试和教程", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const settings: NotificationSettingsStatus = {
    pushPlusEnabled: true,
    pushPlusConfigured: true,
    pushPlusTopicConfigured: false,
  };
  const sendPushPlusTest = vi.spyOn(client, "sendPushPlusTest");
  vi.spyOn(client, "getNotificationSettings").mockResolvedValue(settings);
  vi.spyOn(client, "listAdminUsers").mockResolvedValue([]);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "通知" }));
  expect(await screen.findByText("PushPlus:")).toBeInTheDocument();
  expect(screen.getAllByText("已配置").length).toBeGreaterThan(0);

  await user.click(screen.getByRole("button", { name: "测试 PushPlus 推送" }));
  expect(sendPushPlusTest).toHaveBeenCalled();
  expect(await screen.findByText("PushPlus 测试推送已发送")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "PushPlus 配置教程" }));
  expect(await screen.findByRole("dialog", { name: "PushPlus 配置教程" })).toBeInTheDocument();
  expect(screen.getByText(/PUSHPLUS_ENABLED=true/)).toBeInTheDocument();
});

test("管理中心 AI 补全 tab 保存全局配置", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateInlineCompletionConfig = vi.spyOn(client, "updateInlineCompletionConfig");
  vi.spyOn(client, "listAdminUsers").mockResolvedValue([]);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "AI 补全" }));

  expect(await screen.findByText("AI inline 补全（全局）")).toBeInTheDocument();

  await user.click(screen.getByLabelText("启用 AI inline 补全"));
  await user.clear(screen.getByLabelText("服务地址"));
  await user.type(screen.getByLabelText("服务地址"), "https://provider.test/v1");
  await user.clear(screen.getByLabelText("模型"));
  await user.type(screen.getByLabelText("模型"), "coder");
  await user.type(screen.getByLabelText("API 密钥"), "sk-test");
  await user.click(screen.getByRole("button", { name: "保存 AI inline 补全配置" }));

  await waitFor(() => {
    expect(updateInlineCompletionConfig).toHaveBeenCalledWith(expect.objectContaining({
      enabled: true,
      baseUrl: "https://provider.test/v1",
      model: "coder",
      apiKey: "sk-test",
    }));
  });
  expect(await screen.findByText("AI inline 补全配置已保存")).toBeInTheDocument();
});

test("管理中心 LiteLLM 网关 tab 保存配置并重置统计", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateTransferBridgeConfig = vi.spyOn(client, "updateTransferBridgeConfig");
  const resetTransferBridgeStats = vi.spyOn(client, "resetTransferBridgeStats");
  vi.spyOn(client, "listAdminUsers").mockResolvedValue([]);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "LiteLLM 网关" }));
  await user.click(await screen.findByLabelText("启用 LiteLLM 网关"));
  await user.clear(await screen.findByLabelText("上游 base URL"));
  await user.type(screen.getByLabelText("上游 base URL"), "https://api.example.test/v1");
  await user.clear(screen.getByLabelText("LiteLLM model"));
  await user.type(screen.getByLabelText("LiteLLM model"), "openai/gpt-next");
  await user.clear(screen.getByLabelText("模型别名"));
  await user.type(screen.getByLabelText("模型别名"), "gpt-next");
  await user.type(screen.getByLabelText("上游 API key"), "sk-new");
  await user.click(screen.getByRole("button", { name: "添加路由" }));
  await user.selectOptions(screen.getByLabelText("LiteLLM endpoint mode 2"), "chat_completions");
  await user.type(screen.getByLabelText("LiteLLM model 2"), "anthropic/claude-next");
  await user.type(screen.getByLabelText("模型别名 2"), "claude-next");
  await user.type(screen.getByLabelText("上游 base URL 2"), "https://api.anthropic.test/v1");
  await user.type(screen.getByLabelText("上游 API key 2"), "sk-route-2");
  fireEvent.change(screen.getByLabelText("高级 LiteLLM params JSON 2"), { target: { value: '{"rpm":120}' } });
  await user.click(screen.getByLabelText("LiteLLM drop params"));
  await user.click(screen.getByRole("button", { name: "保存网关配置" }));

  expect(updateTransferBridgeConfig).toHaveBeenCalledWith(expect.objectContaining<Partial<TransferBridgeConfigInput>>({
    enabled: true,
    dropParams: false,
    routes: [
      expect.objectContaining({
        endpointMode: "auto",
        extraLitellmParams: {},
        providerBaseUrl: "https://api.example.test/v1",
        litellmModel: "openai/gpt-next",
        modelAlias: "gpt-next",
        providerApiKey: "sk-new",
        clearProviderApiKey: false,
      }),
      expect.objectContaining({
        endpointMode: "chat_completions",
        extraLitellmParams: { rpm: 120 },
        providerBaseUrl: "https://api.anthropic.test/v1",
        litellmModel: "anthropic/claude-next",
        modelAlias: "claude-next",
        providerApiKey: "sk-route-2",
        clearProviderApiKey: false,
      }),
    ],
  }));
  expect(await screen.findByText("网关配置已保存")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "重置统计" }));
  expect(resetTransferBridgeStats).toHaveBeenCalled();
  expect(await screen.findByText("网关统计已重置")).toBeInTheDocument();
  expect(screen.getByText("request_count = 0")).toBeInTheDocument();
});

test("管理中心 LiteLLM 网关 tab 拒绝高级参数覆盖核心字段", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateTransferBridgeConfig = vi.spyOn(client, "updateTransferBridgeConfig");
  vi.spyOn(client, "listAdminUsers").mockResolvedValue([]);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "LiteLLM 网关" }));
  fireEvent.change(await screen.findByLabelText("高级 LiteLLM params JSON"), { target: { value: '{"api_key":"sk-override"}' } });
  await user.click(screen.getByRole("button", { name: "保存网关配置" }));

  expect(updateTransferBridgeConfig).not.toHaveBeenCalled();
  expect(await screen.findByText("高级 LiteLLM params 不能包含 api_key")).toBeInTheDocument();
});

test("管理中心 Codex 用量页签惰性加载并展示关闭后的历史统计", async () => {
  const user = userEvent.setup();
  const client = Object.assign(new MockWebBotClient(), {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getCodexUsageConfig: vi.fn(async () => codexUsageConfigFixture),
    getCodexUsageStats: vi.fn(async () => codexUsageStatsFixture),
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  expect(client.getCodexUsageConfig).not.toHaveBeenCalled();
  expect(client.getCodexUsageStats).not.toHaveBeenCalled();

  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));

  expect(await screen.findByRole("heading", { name: "Codex 用量" })).toBeInTheDocument();
  await waitFor(() => {
    expect(client.getCodexUsageConfig).toHaveBeenCalledTimes(1);
    expect(client.getCodexUsageStats).toHaveBeenCalledWith({
      startDate: "2026-06-27",
      endDate: "2026-07-26",
      dailyPage: 1,
      dailyPageSize: 10,
    });
  });
  expect(screen.getByText("统计采集已关闭，历史数据仍可查询。")).toBeInTheDocument();
  expect(screen.getAllByText("OpenAI 官方").length).toBeGreaterThan(0);
  expect(screen.getAllByText("1.6K").length).toBeGreaterThan(0);
  expect(screen.getByRole("table", { name: "Codex 用量每日明细" })).toBeInTheDocument();
});

test("管理中心 Codex 用量按模型展示并为大数保留精确值", async () => {
  const user = userEvent.setup();
  const largeMetrics = {
    requestCount: 42,
    inputTokens: 1_200_000,
    cachedInputTokens: 300_000,
    uncachedInputTokens: 900_000,
    outputTokens: 50_000,
    reasoningOutputTokens: 8_000,
    totalTokens: 1_250_000,
    cacheHitRate: 0.25,
  };
  const client = Object.assign(new MockWebBotClient(), {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getCodexUsageConfig: vi.fn(async () => codexUsageConfigFixture),
    getCodexUsageStats: vi.fn(async () => ({
      ...codexUsageStatsFixture,
      totals: largeMetrics,
      byProviderModel: [{
        provider: codexUsageConfigFixture.currentProvider,
        model: "gpt-5.6-sol",
        ...largeMetrics,
      }],
      dailyByProviderModel: [{
        date: "2026-07-26",
        provider: codexUsageConfigFixture.currentProvider,
        model: "gpt-5.6-sol",
        ...largeMetrics,
      }],
    })),
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));

  expect((await screen.findAllByText("gpt-5.6-sol")).length).toBeGreaterThan(0);
  const compactValues = screen.getAllByText("1.25M");
  expect(compactValues.some((element) => element.getAttribute("title") === "1,250,000")).toBe(true);
});

test("管理中心 Codex 用量开关失败时恢复原状态", async () => {
  const user = userEvent.setup();
  const client = Object.assign(new MockWebBotClient(), {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getCodexUsageConfig: vi.fn(async () => codexUsageConfigFixture),
    getCodexUsageStats: vi.fn(async () => codexUsageStatsFixture),
    updateCodexUsageConfig: vi.fn(async () => {
      throw new Error("网络异常");
    }),
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));
  const toggle = await screen.findByLabelText("启用 Codex 用量采集");
  expect(toggle).not.toBeChecked();

  await user.click(toggle);

  await waitFor(() => {
    expect(client.updateCodexUsageConfig).toHaveBeenCalledWith({ enabled: true });
  });
  expect(await screen.findByText("保存 Codex 用量采集设置失败：网络异常")).toBeInTheDocument();
  expect(screen.getByLabelText("启用 Codex 用量采集")).not.toBeChecked();
});

test("管理中心 Codex 用量筛选支持快捷日期且清空 Provider 不发请求", async () => {
  const user = userEvent.setup();
  const getCodexUsageStats = vi.fn(async () => codexUsageStatsFixture);
  const client = Object.assign(new MockWebBotClient(), {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getCodexUsageConfig: vi.fn(async () => codexUsageConfigFixture),
    getCodexUsageStats,
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));
  await screen.findByRole("heading", { name: "Codex 用量" });
  await waitFor(() => expect(getCodexUsageStats).toHaveBeenCalledTimes(1));
  getCodexUsageStats.mockClear();

  await user.click(screen.getByRole("button", { name: "近 7 天" }));
  await waitFor(() => {
    expect(getCodexUsageStats).toHaveBeenCalledWith({
      startDate: "2026-07-20",
      endDate: "2026-07-26",
      dailyPage: 1,
      dailyPageSize: 10,
    });
  });

  getCodexUsageStats.mockClear();
  await user.click(screen.getByRole("button", { name: "清空" }));
  await user.click(screen.getByRole("button", { name: "查询" }));
  expect(await screen.findByText("请至少选择一个 Provider 后再查询。")).toBeInTheDocument();
  expect(getCodexUsageStats).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "全选" }));
  await user.click(screen.getByRole("button", { name: "查询" }));
  await waitFor(() => {
    expect(getCodexUsageStats).toHaveBeenCalledWith({
      startDate: "2026-07-20",
      endDate: "2026-07-26",
      dailyPage: 1,
      dailyPageSize: 10,
    });
  });
});

test("管理中心 Codex 用量每日明细支持展开、翻页和收起", async () => {
  const user = userEvent.setup();
  const getCodexUsageStats = vi.fn(async (query: { dailyPage?: number; dailyPageSize?: number } = {}) => {
    return createPagedCodexUsageStats(query.dailyPage || 1, query.dailyPageSize || 10);
  });
  const client = Object.assign(new MockWebBotClient(), {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getCodexUsageConfig: vi.fn(async () => codexUsageConfigFixture),
    getCodexUsageStats,
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));

  await waitFor(() => {
    expect(getCodexUsageStats).toHaveBeenCalledWith(expect.objectContaining({
      dailyPage: 1,
      dailyPageSize: 10,
    }));
  });
  const dailyTable = await screen.findByRole("table", { name: "Codex 用量每日明细" });
  expect(dailyTable.querySelectorAll("tbody tr")).toHaveLength(10);
  expect(screen.getByText("model-001")).toBeInTheDocument();
  expect(screen.queryByText("model-011")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "展开更多" }));
  await waitFor(() => {
    expect(getCodexUsageStats).toHaveBeenLastCalledWith(expect.objectContaining({
      dailyPage: 1,
      dailyPageSize: 100,
    }));
  });
  expect(dailyTable.querySelectorAll("tbody tr")).toHaveLength(100);
  expect(screen.getByText("model-100")).toBeInTheDocument();
  expect(screen.queryByText("model-101")).not.toBeInTheDocument();
  expect(screen.getByText("第 1 / 2 页，共 101 条")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "下一页" }));
  await waitFor(() => {
    expect(getCodexUsageStats).toHaveBeenLastCalledWith(expect.objectContaining({
      dailyPage: 2,
      dailyPageSize: 100,
    }));
  });
  expect(dailyTable.querySelectorAll("tbody tr")).toHaveLength(1);
  expect(screen.getByText("model-101")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "收起" }));
  await waitFor(() => {
    expect(getCodexUsageStats).toHaveBeenLastCalledWith(expect.objectContaining({
      dailyPage: 1,
      dailyPageSize: 10,
    }));
  });
  expect(dailyTable.querySelectorAll("tbody tr")).toHaveLength(10);
});

test("管理中心 Codex 用量快捷日期和重置会恢复每日明细第一页", async () => {
  const user = userEvent.setup();
  const getCodexUsageStats = vi.fn(async (query: { dailyPage?: number; dailyPageSize?: number } = {}) => {
    return createPagedCodexUsageStats(query.dailyPage || 1, query.dailyPageSize || 10);
  });
  const client = Object.assign(new MockWebBotClient(), {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getCodexUsageConfig: vi.fn(async () => codexUsageConfigFixture),
    getCodexUsageStats,
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));
  await screen.findByRole("button", { name: "展开更多" });

  await user.click(screen.getByRole("button", { name: "展开更多" }));
  await waitFor(() => expect(getCodexUsageStats).toHaveBeenLastCalledWith(expect.objectContaining({ dailyPageSize: 100 })));

  await user.click(screen.getByRole("button", { name: "近 7 天" }));
  await waitFor(() => {
    expect(getCodexUsageStats).toHaveBeenLastCalledWith(expect.objectContaining({
      startDate: "2026-07-20",
      endDate: "2026-07-26",
      dailyPage: 1,
      dailyPageSize: 10,
    }));
  });

  await user.click(screen.getByRole("button", { name: "展开更多" }));
  await waitFor(() => expect(getCodexUsageStats).toHaveBeenLastCalledWith(expect.objectContaining({ dailyPageSize: 100 })));

  await user.click(screen.getByRole("button", { name: "重置" }));
  await waitFor(() => {
    expect(getCodexUsageStats).toHaveBeenLastCalledWith({
      startDate: "2026-06-27",
      endDate: "2026-07-26",
      dailyPage: 1,
      dailyPageSize: 10,
    });
  });
});

test("管理中心 Codex 用量请求期间禁用筛选按钮", async () => {
  const user = userEvent.setup();
  const sevenDayQuery = deferred<typeof codexUsageStatsFixture>();
  const getCodexUsageStats = vi
    .fn()
    .mockResolvedValueOnce(codexUsageStatsFixture)
    .mockReturnValueOnce(sevenDayQuery.promise);
  const client = Object.assign(new MockWebBotClient(), {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getCodexUsageConfig: vi.fn(async () => codexUsageConfigFixture),
    getCodexUsageStats,
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));
  await screen.findByRole("heading", { name: "Codex 用量" });
  await waitFor(() => expect(getCodexUsageStats).toHaveBeenCalledTimes(1));

  await user.click(screen.getByRole("button", { name: "近 7 天" }));
  expect(screen.getByRole("button", { name: "近 30 天" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "近 30 天" }));
  expect(getCodexUsageStats).toHaveBeenCalledTimes(2);

  await act(async () => {
    sevenDayQuery.resolve({
      ...codexUsageStatsFixture,
      range: { startDate: "2026-07-20", endDate: "2026-07-26" },
      totals: { ...codexUsageStatsFixture.totals, totalTokens: 7_007 },
    });
    await sevenDayQuery.promise;
  });

  expect(screen.getByText("7.01K")).toBeInTheDocument();
});

test("管理中心 Codex 用量统计加载失败时仍保留采集设置", async () => {
  const user = userEvent.setup();
  const client = Object.assign(new MockWebBotClient(), {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getCodexUsageConfig: vi.fn(async () => codexUsageConfigFixture),
    getCodexUsageStats: vi.fn(async () => {
      throw new Error("统计暂不可用");
    }),
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("统计暂不可用");
  expect(screen.getByLabelText("启用 Codex 用量采集")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "查询" })).toBeEnabled();
});

test("Codex 用量 mock 客户端按筛选后的日明细重算汇总", async () => {
  const client = new MockWebBotClient();

  const stats = await client.getCodexUsageStats({
    startDate: "2026-07-20",
    endDate: "2026-07-20",
  });

  expect(stats.totals).toMatchObject({
    requestCount: 0,
    inputTokens: 0,
    cachedInputTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
    cacheHitRate: null,
  });
  expect(stats.byProvider).toEqual([]);
  expect(stats.byDay).toEqual([]);
  expect(stats.dailyByProvider).toEqual([]);
});

test("Codex 用量 mock 客户端在完整汇总后再分页每日明细", async () => {
  const client = new MockWebBotClient();
  const internals = client as unknown as { codexUsageStats: CodexUsageStats };
  const firstDaily = internals.codexUsageStats.dailyByProvider[0]!;
  const firstDetailed = internals.codexUsageStats.dailyByProviderModel[0]!;
  const secondMetrics = {
    requestCount: 3,
    inputTokens: 100,
    cachedInputTokens: 20,
    uncachedInputTokens: 80,
    outputTokens: 50,
    reasoningOutputTokens: 10,
    totalTokens: 150,
    cacheHitRate: 0.2,
  };
  internals.codexUsageStats = {
    ...internals.codexUsageStats,
    dailyByProvider: [
      firstDaily,
      { ...firstDaily, date: "2026-07-25", ...secondMetrics },
    ],
    dailyByProviderModel: [
      firstDetailed,
      { ...firstDetailed, date: "2026-07-25", model: "gpt-5.6-pro", ...secondMetrics },
    ],
  };

  const stats = await client.getCodexUsageStats({ dailyPage: 1, dailyPageSize: 1 });

  expect(stats.dailyPagination).toEqual({
    page: 1,
    pageSize: 1,
    totalItems: 2,
    totalPages: 2,
    hasPrevious: false,
    hasNext: true,
  });
  expect(stats.dailyByProviderModel).toHaveLength(1);
  expect(stats.dailyByProvider).toEqual([]);
  expect(stats.totals).toMatchObject({ requestCount: 15, totalTokens: 23_150 });

  const outOfRange = await client.getCodexUsageStats({ dailyPage: 3, dailyPageSize: 1 });
  expect(outOfRange.dailyPagination).toMatchObject({ page: 3, totalPages: 2 });
  expect(outOfRange.dailyByProviderModel).toEqual([]);

  internals.codexUsageStats = {
    ...internals.codexUsageStats,
    dailyByProvider: [],
    dailyByProviderModel: [],
  };
  const empty = await client.getCodexUsageStats({ dailyPage: 4, dailyPageSize: 10 });
  expect(empty.dailyPagination).toMatchObject({ page: 4, totalItems: 0, totalPages: 0 });
});

test("管理中心 Codex 用量每日分页保持服务端行顺序", async () => {
  const user = userEvent.setup();
  const firstProvider = {
    ...codexUsageConfigFixture.currentProvider,
    key: "base_url_sha256:a",
    label: "Z Provider",
  };
  const secondProvider = {
    ...codexUsageConfigFixture.currentProvider,
    key: "base_url_sha256:z",
    label: "A Provider",
  };
  const serverOrderedStats = {
    ...codexUsageStatsFixture,
    dailyByProvider: [],
    dailyByProviderModel: [
      { ...codexUsageStatsFixture.dailyByProvider[0], provider: firstProvider, model: "model-a" },
      { ...codexUsageStatsFixture.dailyByProvider[0], provider: secondProvider, model: "model-z" },
    ],
    dailyPagination: {
      page: 1,
      pageSize: 10,
      totalItems: 2,
      totalPages: 1,
      hasPrevious: false,
      hasNext: false,
    },
  };
  const client = Object.assign(new MockWebBotClient(), {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getCodexUsageConfig: vi.fn(async () => codexUsageConfigFixture),
    getCodexUsageStats: vi.fn(async () => serverOrderedStats),
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));

  const table = await screen.findByRole("table", { name: "Codex 用量每日明细" });
  const rows = Array.from(table.querySelectorAll("tbody tr"));
  expect(rows[0]).toHaveTextContent("Z Provider");
  expect(rows[1]).toHaveTextContent("A Provider");
});

test("管理中心 Codex 用量不会把缺失的 Provider 解析状态显示为已解析", async () => {
  const user = userEvent.setup();
  const client = Object.assign(new MockWebBotClient(), {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getCodexUsageConfig: vi.fn(async () => ({
      ...codexUsageConfigFixture,
      currentProvider: {
        ...codexUsageConfigFixture.currentProvider,
        resolution: undefined,
      },
    })),
    getCodexUsageStats: vi.fn(async () => codexUsageStatsFixture),
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 用量" }));

  expect(await screen.findByText("未知/未提供")).toBeInTheDocument();
  expect(screen.queryByText("已解析")).not.toBeInTheDocument();
});
