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
  await addNativeBot(client);

  render(<SettingsScreen botAlias="native1" client={client} onLogout={() => undefined} />);

  expect(await screen.findByLabelText("运行后端")).toHaveValue("native_agent");
  expect(screen.queryByLabelText("CLI 类型")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("CLI 路径")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Native model")).toHaveValue("claude-sonnet-4-5");
  expect(screen.queryByText("sk-settings-1234")).not.toBeInTheDocument();
  expect(screen.queryByText("https://provider.example/v1")).not.toBeInTheDocument();
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

test("non-admin session cannot mutate current agent runtime settings", async () => {
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
  await userEvent.click(await screen.findByRole("button", { name: "生成安装命令" }));
  expect(await screen.findByText(/DeepSeek Harness 集群轮次会自动注入/)).toBeInTheDocument();
  expect(screen.queryByText("安装命令", { exact: true })).not.toBeInTheDocument();
  expect(screen.queryByText("验证命令", { exact: true })).not.toBeInTheDocument();
});

test("cluster settings stay local until saved together, and the enable switch keeps unsaved edits", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateCluster = vi.spyOn(client, "updateClusterConfig");
  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  const size = await screen.findByLabelText("集群规模");
  const saveButton = screen.getByRole("button", { name: "保存集群配置" });
  expect(saveButton).toBeDisabled();
  await waitFor(() => expect(screen.getByLabelText("启用集群模式")).toBeEnabled());

  await user.selectOptions(size, "5");
  await user.selectOptions(screen.getByLabelText("子 Agent 写入策略"), "main_only");
  const timeout = screen.getByLabelText("任务超时（秒）");
  await user.clear(timeout);
  await user.type(timeout, "900");
  await user.type(screen.getByLabelText("低档 CLI 路径"), "/opt/codex");
  expect(updateCluster).not.toHaveBeenCalled();
  expect(within(screen.getByRole("navigation", { name: "设置分区" })).getByRole("button", { name: /集群/ })).toContainElement(screen.getAllByLabelText("有未保存更改")[0]);

  await user.click(screen.getByLabelText("启用集群模式"));
  await waitFor(() => expect(updateCluster).toHaveBeenCalledTimes(1));
  expect(updateCluster.mock.calls[0][1]).toMatchObject({ enabled: true, maxParallelAgents: 3, writePolicy: "all_agents" });
  expect(screen.getByLabelText("集群规模")).toHaveValue("5");

  await user.click(saveButton);
  await waitFor(() => expect(updateCluster).toHaveBeenCalledTimes(2));
  expect(updateCluster.mock.calls[1][1]).toMatchObject({
    enabled: true,
    maxParallelAgents: 5,
    writePolicy: "main_only",
    defaultTimeoutSeconds: 900,
    tierConfigs: { low: expect.objectContaining({ cliPath: "/opt/codex" }) },
  });
  await waitFor(() => expect(saveButton).toBeDisabled());
  expect(screen.queryByLabelText("有未保存更改")).not.toBeInTheDocument();
});

test("cluster settings revert discards the draft and invalid timeouts are not saved", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateCluster = vi.spyOn(client, "updateClusterConfig");
  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  const timeout = await screen.findByLabelText("任务超时（秒）");
  const original = (timeout as HTMLInputElement).value;
  await user.clear(timeout);
  await user.type(timeout, "30{Enter}");
  expect(await screen.findByText("任务超时必须是 60 到 3600 之间的整数")).toBeInTheDocument();
  expect(updateCluster).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "还原" }));
  expect(timeout).toHaveValue(Number(original));
  expect(screen.getByRole("button", { name: "保存集群配置" })).toBeDisabled();
});

test("switching CLI type fills another agent's path and saving it opens a new conversation", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.login({ username: "127.0.0.1", password: "test" });
  await client.addBot({ alias: "reviewer", cliType: "claude", cliPath: "/opt/claude/bin/claude", workingDir: "C:\\workspace\\reviewer" });
  const createConversation = vi.spyOn(client, "createConversation");
  const onCliSwitched = vi.fn();
  render(<SettingsScreen botAlias="main" client={client} onCliSwitched={onCliSwitched} />);

  const cliType = await screen.findByLabelText("CLI 类型");
  await user.selectOptions(cliType, "antigravity");
  expect(screen.getByLabelText("CLI 路径")).toHaveValue("agy");
  await user.selectOptions(cliType, "claude");
  expect(screen.getByLabelText("CLI 路径")).toHaveValue("/opt/claude/bin/claude");

  await user.click(screen.getByRole("button", { name: "保存 CLI 配置" }));
  await waitFor(() => expect(onCliSwitched).toHaveBeenCalledWith("main"));
  expect(createConversation).toHaveBeenCalledWith("main");
  expect(await client.getBotOverview("main")).toMatchObject({ cliType: "claude", cliPath: "/opt/claude/bin/claude" });
  expect(screen.getByText("已切换到 claude，并开启新会话")).toBeInTheDocument();
});

test("saving only a new CLI path keeps the current conversation", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.login({ username: "127.0.0.1", password: "test" });
  const createConversation = vi.spyOn(client, "createConversation");
  const onCliSwitched = vi.fn();
  render(<SettingsScreen botAlias="main" client={client} onCliSwitched={onCliSwitched} />);

  const cliPath = await screen.findByLabelText("CLI 路径");
  await user.clear(cliPath);
  await user.type(cliPath, "/opt/codex/bin/codex");
  await user.click(screen.getByRole("button", { name: "保存 CLI 配置" }));
  expect(await screen.findByText("CLI 配置已更新")).toBeInTheDocument();
  expect(createConversation).not.toHaveBeenCalled();
  expect(onCliSwitched).not.toHaveBeenCalled();
});
