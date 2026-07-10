import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { NotificationSettingsStatus, TransferBridgeConfigInput, TransferBridgeStatus, TunnelSnapshot } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function createAdminClient(transferStatus: TransferBridgeStatus): WebBotClient {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getTransferAdminStatus: vi.fn(async () => transferStatus),
  });
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
