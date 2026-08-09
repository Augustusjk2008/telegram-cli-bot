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
