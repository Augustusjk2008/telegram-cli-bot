import { render, screen } from "@testing-library/react";
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

test("管理中心桥接 tab 显示状态、链接和 Codex 配置提示", async () => {
  const user = userEvent.setup();
  const client = createAdminClient({
    enabled: true,
    running: true,
    status: "running",
    localUrl: "http://127.0.0.1:8080",
    bridgePageUrl: "/api/transfer/page",
    responsesBaseUrl: "http://127.0.0.1:8080/v1",
    chatCompletionsBaseUrl: "http://127.0.0.1:8080/v1",
    remoteBaseUrl: "https://max.jojocode.com/v1",
    remoteModel: "gpt-5.5",
    remoteApiKeySet: true,
    requestCount: 1,
    totalInputTokens: 15381,
    totalOutputTokens: 30,
    totalBytesIn: 75420,
    totalBytesOut: 3400,
    requestStreamUsage: true,
    retryWithoutStreamOptions: true,
    reasoningMode: "chat_reasoning_effort",
    downgradeDeveloperToSystem: false,
    useLegacyMaxTokens: false,
    startedAt: "2026-06-29T12:00:00Z",
    lastRequestAt: "2026-06-29T12:01:00Z",
    lastError: "",
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "桥接" }));

  expect(await screen.findByText("桥接状态")).toBeInTheDocument();
  expect(screen.getByText("运行中")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "打开桥接调试页面" })).toHaveAttribute("href", "/api/transfer/page");
  expect(screen.getByText("http://127.0.0.1:8080/v1")).toBeInTheDocument();
  expect(screen.getByText("gpt-5.5")).toBeInTheDocument();
  expect(screen.getByText("已设置")).toBeInTheDocument();
  expect(screen.getByLabelText("remote base URL")).toHaveValue("https://max.jojocode.com/v1");
  expect(screen.getByLabelText("remote model")).toHaveValue("gpt-5.5");
  expect(screen.getByText("request_count = 1")).toBeInTheDocument();
  expect(screen.getByText("wire_api = \"responses\"")).toBeInTheDocument();
});

test("管理中心桥接 tab 显示未配置提示", async () => {
  const user = userEvent.setup();
  const client = createAdminClient({
    enabled: false,
    running: false,
    status: "not_configured",
    localUrl: "http://127.0.0.1:8080",
    bridgePageUrl: "/api/transfer/page",
    responsesBaseUrl: "http://127.0.0.1:8080/v1",
    chatCompletionsBaseUrl: "http://127.0.0.1:8080/v1",
    remoteApiKeySet: false,
    requestCount: 0,
    totalInputTokens: 0,
    totalOutputTokens: 0,
    totalBytesIn: 0,
    totalBytesOut: 0,
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "桥接" }));

  expect(await screen.findByText("未配置")).toBeInTheDocument();
  expect(screen.getByText("桥接尚未配置 remote provider。" )).toBeInTheDocument();
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

test("管理中心桥接 tab 保存配置并重置统计", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateTransferBridgeConfig = vi.spyOn(client, "updateTransferBridgeConfig");
  const resetTransferBridgeStats = vi.spyOn(client, "resetTransferBridgeStats");
  vi.spyOn(client, "listAdminUsers").mockResolvedValue([]);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "桥接" }));
  await user.clear(await screen.findByLabelText("remote base URL"));
  await user.type(screen.getByLabelText("remote base URL"), "https://api.example.test/v1");
  await user.clear(screen.getByLabelText("remote model"));
  await user.type(screen.getByLabelText("remote model"), "gpt-next");
  await user.type(screen.getByLabelText("remote API key"), "sk-new");
  await user.click(screen.getByLabelText("developer 消息降级为 system"));
  await user.click(screen.getByRole("button", { name: "保存桥接配置" }));

  expect(updateTransferBridgeConfig).toHaveBeenCalledWith(expect.objectContaining<Partial<TransferBridgeConfigInput>>({
    remoteBaseUrl: "https://api.example.test/v1",
    remoteModel: "gpt-next",
    remoteApiKey: "sk-new",
    downgradeDeveloperToSystem: true,
  }));
  expect(await screen.findByText("桥接配置已保存")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "重置统计" }));
  expect(resetTransferBridgeStats).toHaveBeenCalled();
  expect(await screen.findByText("桥接统计已重置")).toBeInTheDocument();
  expect(screen.getByText("request_count = 0")).toBeInTheDocument();
});
