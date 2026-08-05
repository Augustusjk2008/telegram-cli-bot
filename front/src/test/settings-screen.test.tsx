import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { SettingsScreen } from "../screens/SettingsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotExecutionConfigInput, BotSummary } from "../services/types";

afterEach(() => {
  vi.restoreAllMocks();
});

class SettingsRuntimeClient extends MockWebBotClient {
  updateCalls: Array<{ botAlias: string; input: BotExecutionConfigInput }> = [];

  async updateBotExecutionConfig(botAlias: string, input: BotExecutionConfigInput): Promise<BotSummary> {
    this.updateCalls.push({ botAlias, input });
    return super.updateBotExecutionConfig(botAlias, input);
  }
}

async function addNativeBot(client: MockWebBotClient, alias = "native1", piAgent = "reviewer") {
  await client.login({ username: "127.0.0.1", password: "test" });
  await client.addBot({
    alias,
    cliType: "codex",
    cliPath: "codex",
    workingDir: `C:\\workspace\\${alias}`,
    supportedExecutionModes: ["native_agent"],
    defaultExecutionMode: "native_agent",
    nativeAgent: {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      piAgent,
      baseUrl: "https://provider.example/v1",
      apiKey: "sk-settings-1234",
    },
  });
}

test("native bot settings hide CLI-only controls and never echo its API key", async () => {
  const client = new MockWebBotClient();
  const openManager = vi.fn();
  await addNativeBot(client);

  render(<SettingsScreen botAlias="native1" client={client} onLogout={() => undefined} onOpenBotManager={openManager} />);

  expect(await screen.findByLabelText("运行后端")).toHaveValue("native_agent");
  expect(screen.queryByLabelText("CLI 类型")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("CLI 路径")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Native model")).toHaveValue("claude-sonnet-4-5");
  expect(screen.queryByText("sk-settings-1234")).not.toBeInTheDocument();
  expect(screen.queryByText("https://provider.example/v1")).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "查看管理中心" }));
  expect(openManager).toHaveBeenCalledTimes(1);
});

test("native settings persist the selected Pi agent through the execution config", async () => {
  const user = userEvent.setup();
  const client = new SettingsRuntimeClient();
  await addNativeBot(client);

  render(<SettingsScreen botAlias="native1" client={client} onLogout={() => undefined} />);

  await user.clear(await screen.findByLabelText("Pi agent"));
  await user.type(screen.getByLabelText("Pi agent"), "qa");
  await user.click(screen.getByRole("button", { name: "保存原生 agent 配置" }));

  await waitFor(() => expect(client.updateCalls).toHaveLength(1));
  expect(client.updateCalls[0]).toMatchObject({
    botAlias: "native1",
    input: {
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
      nativeAgent: { piAgent: "qa" },
    },
  });
  expect(await screen.findByText("原生 agent 配置已更新")).toBeInTheDocument();
});

test("non-admin session cannot mutate runtime or language-service settings", async () => {
  render(
    <SettingsScreen
      botAlias="main"
      client={new MockWebBotClient()}
      onLogout={() => undefined}
      sessionCapabilities={["view_file_tree"]}
    />,
  );

  expect(await screen.findByLabelText("运行后端")).toBeDisabled();
  expect(screen.getByRole("button", { name: "保存 CLI 配置" })).toBeDisabled();
  expect(await screen.findByRole("heading", { name: "语言服务" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重新检测语言服务" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "安装 Pyright" })).not.toBeInTheDocument();
});
