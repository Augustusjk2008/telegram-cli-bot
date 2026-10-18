import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { SettingsScreen } from "../screens/SettingsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotExecutionConfigInput, BotOverview, BotSummary } from "../services/types";

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

class RemoteSettingsClient extends MockWebBotClient {
  async getBotOverview(botAlias: string): Promise<BotOverview> {
    const overview = await super.getBotOverview(botAlias);
    return {
      ...overview,
      cliType: "antigravity",
      remoteWorkspace: {
        platform: "posix",
        connectionId: "ssh-remote",
        host: "remote.example",
        port: 22,
        username: "builder",
        root: "/work/project",
        hostKeyFingerprint: "SHA256:private-host-key",
      },
      remoteWorkspaceMcp: {
        state: "installed",
        serverName: "tcb-remote",
        configPath: "C:\\workspace\\.agents\\mcp_config.json",
        scope: "workspace",
        allowedTools: ["exec", "read", "write", "edit", "list"],
        setupInstructions: "自动发现工作区 MCP",
        statusLineSnippet: "{\"statusLine\":{}}",
        mcpSetupSnippet: "{\"mcpServers\":{\"tcb-remote\":{}}}",
        askPolicy: "ask",
      },
    };
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

test("updates the local Enter-to-send preference", async () => {
  const user = userEvent.setup();
  const onChatEnterToSendChange = vi.fn();

  render(
    <SettingsScreen
      botAlias="main"
      client={new MockWebBotClient()}
      onLogout={() => undefined}
      chatEnterToSend={false}
      onChatEnterToSendChange={onChatEnterToSendChange}
    />,
  );

  const toggle = await screen.findByLabelText("Enter 键发送消息");
  expect(toggle).not.toBeChecked();

  await user.click(toggle);

  expect(onChatEnterToSendChange).toHaveBeenCalledWith(true);
});

test("settings do not expose manual child agent configuration", async () => {
  render(
    <SettingsScreen
      botAlias="main"
      client={new MockWebBotClient()}
      onLogout={() => undefined}
    />,
  );

  expect(await screen.findByLabelText("运行后端")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "子 agent" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "新增 agent" })).not.toBeInTheDocument();
});

test("remote Antigravity settings expose MCP status, scope and copyable setup guidance", async () => {
  const user = userEvent.setup();
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  const client = new RemoteSettingsClient();

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  const panel = await screen.findByTestId("remote-workspace-mcp-panel");
  expect(within(panel).getByText("已配置")).toBeInTheDocument();
  expect(within(panel).getByText("tcb-remote")).toBeInTheDocument();
  expect(within(panel).getByText("exec, read, write, edit, list")).toBeInTheDocument();
  expect(within(panel).getByText("权限策略：ask")).toBeInTheDocument();

  const copyButtons = within(panel).getAllByRole("button", { name: "复制" });
  await user.click(copyButtons[0]);
  expect(writeText).toHaveBeenCalledWith("{\"mcpServers\":{\"tcb-remote\":{}}}");
});


test("switches a local bot to DeepSeek with its own command and parameter schema", async () => {
  const client = new MockWebBotClient();
  await addNativeBot(client, "deepseek-migration");
  client.setClusterStatus("deepseek-migration", { enabled: true });
  const updateCli = vi.spyOn(client, "updateBotCli");
  const updateExecution = vi.spyOn(client, "updateBotExecutionConfig");
  const updateCluster = vi.spyOn(client, "updateClusterConfig");
  render(<SettingsScreen botAlias="deepseek-migration" client={client} onLogout={() => undefined} />);
  await userEvent.selectOptions(await screen.findByLabelText("运行后端"), "cli");
  await userEvent.selectOptions(await screen.findByLabelText("CLI 类型"), "deepseek");
  expect(screen.getByLabelText("CLI 路径")).toHaveValue("dsh");
  expect(within(screen.getByLabelText("运行后端")).queryByRole("option", { name: "原生 agent" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "保存 CLI 配置" }));
  await waitFor(() => expect(updateCli).toHaveBeenCalledWith("deepseek-migration", "deepseek", "dsh"));
  expect(updateExecution.mock.invocationCallOrder[0]).toBeLessThan(updateCli.mock.invocationCallOrder[0]);
  expect(updateCluster).not.toHaveBeenCalled();
  const params = await client.getCliParams("deepseek-migration");
  expect(params).toMatchObject({
    cliType: "deepseek",
    params: { model: null, reasoning_effort: null, extra_args: [] },
    defaults: { model: null, reasoning_effort: null, extra_args: [] },
  });
  expect(Object.keys(params.schema)).toEqual(["model", "reasoning_effort", "extra_args"]);
});
