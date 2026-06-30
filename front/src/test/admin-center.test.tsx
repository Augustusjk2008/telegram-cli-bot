import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { TransferBridgeStatus } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function createAdminClient(transferStatus: TransferBridgeStatus): WebBotClient {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    getTransferBridgeStatus: vi.fn(async () => transferStatus),
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
