import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { LanguageServicesPanel } from "../components/LanguageServicesPanel";
import { SettingsScreen } from "../screens/SettingsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotExecutionConfigInput, BotSummary, DirectoryListing, LanguageServerCatalog } from "../services/types";
import { CHAT_COMPLETION_WEB_NOTIFICATION_KEY } from "../utils/chatNotificationEvents";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  localStorage.removeItem(CHAT_COMPLETION_WEB_NOTIFICATION_KEY);
});

class SettingsDirectoryPickerClient extends MockWebBotClient {
  browserPath = "C:\\workspace";
  private readonly directoryMap: Record<string, DirectoryListing["entries"]> = {
    "C:\\workspace": [
      { name: "repos", isDir: true },
    ],
    "C:\\workspace\\repos": [
      { name: "team-a", isDir: true },
    ],
    "C:\\workspace\\repos\\team-a": [],
  };

  async getCurrentPath(): Promise<string> {
    return "C:\\workspace";
  }

  async getBotOverview(botAlias: string) {
    const overview = await super.getBotOverview(botAlias);
    return {
      ...overview,
      workingDir: "C:\\workspace",
    };
  }

  async listFiles(): Promise<DirectoryListing> {
    return {
      workingDir: this.browserPath,
      entries: this.directoryMap[this.browserPath] || [],
    };
  }

  async changeDirectory(_botAlias: string, path: string): Promise<string> {
    if (path === "..") {
      const next = this.browserPath.replace(/\\[^\\]+$/, "");
      this.browserPath = next.length > 2 ? next : "C:\\workspace";
      return this.browserPath;
    }
    this.browserPath = /^[A-Za-z]:\\/.test(path)
      ? path
      : `${this.browserPath}\\${path}`;
    return this.browserPath;
  }
}

class SettingsRuntimeClient extends MockWebBotClient {
  updateBotExecutionConfigCalls: Array<{ botAlias: string; input: BotExecutionConfigInput }> = [];

  async updateBotExecutionConfig(botAlias: string, input: BotExecutionConfigInput): Promise<BotSummary> {
    this.updateBotExecutionConfigCalls.push({ botAlias, input });
    return super.updateBotExecutionConfig(botAlias, input);
  }
}

class DeferredLanguageServicesClient extends MockWebBotClient {
  private resolveRefreshPromise: ((catalog: LanguageServerCatalog) => void) | null = null;

  async refreshLanguageServerCatalog(): Promise<LanguageServerCatalog> {
    return new Promise<LanguageServerCatalog>((resolve) => {
      this.resolveRefreshPromise = resolve;
    });
  }

  resolveRefresh(catalog: LanguageServerCatalog) {
    this.resolveRefreshPromise?.(catalog);
  }
}


test("native bots hide cli settings and params", async () => {
  const client = new MockWebBotClient();
  const openManager = vi.fn();
  await client.login({ username: "127.0.0.1", password: "test" });
  await client.addBot({
    alias: "native1",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\native1",
    supportedExecutionModes: ["native_agent"],
    defaultExecutionMode: "native_agent",
    nativeAgent: {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      piAgent: "reviewer",
      baseUrl: "https://cdn.codeflow.asia/v1",
      apiKey: "sk-settings-1234",
    },
  });

  render(<SettingsScreen botAlias="native1" client={client} onLogout={() => undefined} onOpenBotManager={openManager} />);

  expect(await screen.findByText("运行后端:")).toBeInTheDocument();
  expect(screen.getAllByText("原生 agent").length).toBeGreaterThan(0);
  expect(screen.getByLabelText("运行后端")).toHaveValue("native_agent");
  expect(screen.queryByLabelText("CLI 类型")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("CLI 路径")).not.toBeInTheDocument();
  expect(screen.queryByText("保存 CLI 配置")).not.toBeInTheDocument();
  expect(screen.getByText("Model:")).toBeInTheDocument();
  expect(screen.getAllByText("claude-sonnet-4-5").length).toBeGreaterThan(0);
  expect(screen.getByLabelText("Native model")).toHaveValue("claude-sonnet-4-5");
  expect(screen.getByLabelText("Reasoning effort")).toBeInTheDocument();
  expect(screen.queryByText("anthropic")).not.toBeInTheDocument();
  expect(screen.queryByText("https://cdn.codeflow.asia/v1")).not.toBeInTheDocument();
  expect(screen.queryByText("已保存 sk-****1234")).not.toBeInTheDocument();
  expect(screen.queryByText("sk-settings-1234")).not.toBeInTheDocument();
  expect(screen.getByText("Pi agent:")).toBeInTheDocument();
  expect(screen.getByText("reviewer")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "查看管理中心" }));
  expect(openManager).toHaveBeenCalled();
});

test("settings screen edits native agent config", async () => {
  const user = userEvent.setup();
  const client = new SettingsRuntimeClient();
  await client.login({ username: "127.0.0.1", password: "test" });
  await client.addBot({
    alias: "native1",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\native1",
    supportedExecutionModes: ["native_agent"],
    defaultExecutionMode: "native_agent",
    nativeAgent: {
      provider: "",
      model: "",
      piAgent: "reviewer",
    },
  });

  render(<SettingsScreen botAlias="native1" client={client} onLogout={() => undefined} />);

  expect(await screen.findByLabelText("运行后端")).toHaveValue("native_agent");
  expect(screen.queryByLabelText("CLI 类型")).not.toBeInTheDocument();
  await user.clear(screen.getByLabelText("Pi agent"));
  await user.type(screen.getByLabelText("Pi agent"), "qa");
  await user.click(screen.getByRole("button", { name: "保存原生 agent 配置" }));

  await waitFor(() => {
    expect(client.updateBotExecutionConfigCalls).toHaveLength(1);
  });
  expect(client.updateBotExecutionConfigCalls[0]).toMatchObject({
    botAlias: "native1",
    input: {
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
      nativeAgent: {
        piAgent: "qa",
      },
    },
  });
  expect(await screen.findByText("原生 agent 配置已更新")).toBeInTheDocument();
});

test("settings screen switches cli bot to native agent", async () => {
  const user = userEvent.setup();
  const client = new SettingsRuntimeClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  await user.selectOptions(await screen.findByLabelText("运行后端"), "native_agent");
  expect(screen.queryByLabelText("CLI 类型")).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("Pi agent"), "reviewer");
  await user.click(screen.getByRole("button", { name: "保存原生 agent 配置" }));

  await waitFor(() => {
    expect(client.updateBotExecutionConfigCalls).toHaveLength(1);
  });
  expect(client.updateBotExecutionConfigCalls[0]).toMatchObject({
    botAlias: "main",
    input: {
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
      nativeAgent: {
        piAgent: "reviewer",
      },
    },
  });
});

test("native settings shows pi cluster extension setup", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "native1",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\native1",
    supportedExecutionModes: ["native_agent"],
    defaultExecutionMode: "native_agent",
    nativeAgent: {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      piAgent: "reviewer",
    },
  });

  render(<SettingsScreen botAlias="native1" client={client} onLogout={() => undefined} />);

  expect(await screen.findByText("集群 MCP")).toBeInTheDocument();
  expect((await screen.findAllByText(/Pi 集群扩展已配置/)).length).toBeGreaterThan(0);
  await user.click(screen.getByRole("button", { name: "生成安装命令" }));
  expect(await screen.findByText("Pi 扩展")).toBeInTheDocument();
  expect(screen.getAllByText(/tcb-cluster\.ts/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/tcb-cluster/).length).toBeGreaterThan(0);
  expect(screen.getByText("本项目自检")).toBeInTheDocument();
  expect(screen.getByText("Pi 验证步骤")).toBeInTheDocument();
  expect(screen.getByText(/当前 run_id 调 cluster_status/)).toBeInTheDocument();
});

test("settings screen keeps system admin controls out", async () => {
  render(<SettingsScreen botAlias="main" client={new MockWebBotClient()} onLogout={() => undefined} />);

  expect(await screen.findByText("界面与阅读")).toBeInTheDocument();
  expect(screen.queryByLabelText("Git 代理地址")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存 Git 代理" })).not.toBeInTheDocument();
  expect(screen.queryByText("公网访问")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "启动 Tunnel" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "停止 Tunnel" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /重启 Tunnel/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "测试 PushPlus 推送" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "PushPlus 配置教程" })).not.toBeInTheDocument();
  expect(screen.queryByText("AI inline 补全（全局）")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("启用 AI inline 补全")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存 AI inline 补全配置" })).not.toBeInTheDocument();
});

test("settings screen creates child agent", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const createAgent = vi.spyOn(client, "createAgent");

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  await user.click(await screen.findByRole("button", { name: "新增 agent" }));
  await user.type(screen.getByLabelText("Agent ID"), "reviewer");
  await user.type(screen.getByLabelText("名称"), "代码审查");
  await user.type(screen.getByLabelText("系统提示词"), "先列风险");
  await user.click(screen.getByRole("button", { name: "保存" }));

  await waitFor(() => {
    expect(createAgent).toHaveBeenCalledWith("main", {
      id: "reviewer",
      name: "代码审查",
      systemPrompt: "先列风险",
      enabled: true,
    });
  });
  expect(await screen.findByText("agent 已新增")).toBeInTheDocument();
});

test("settings screen shows language service discovery details and keeps install asynchronous", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const refresh = vi.spyOn(client, "refreshLanguageServerCatalog");
  const install = vi.spyOn(client, "installLanguageServer");

  render(
    <SettingsScreen
      botAlias="main"
      client={client}
      onLogout={() => undefined}
      sessionCapabilities={["admin_ops"]}
    />,
  );

  expect(await screen.findByRole("heading", { name: "语言服务" })).toBeInTheDocument();
  const pyright = screen.getByTestId("language-service-pyright");
  expect(within(pyright).getByText("Python · Pyright")).toBeInTheDocument();
  expect(within(pyright).getByText("缺失")).toBeInTheDocument();
  expect(within(pyright).getByText("未发现")).toBeInTheDocument();
  expect(within(pyright).getByText("pyright-langserver --stdio")).toBeInTheDocument();
  expect(within(screen.getByTestId("language-service-typescript")).getByText("PATH")).toBeInTheDocument();
  expect(within(screen.getByTestId("language-service-clangd")).getByText("错误")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "重新检测语言服务" }));
  expect(refresh).toHaveBeenCalledTimes(1);

  await user.click(screen.getByRole("button", { name: "安装 Pyright" }));
  await waitFor(() => {
    expect(install).toHaveBeenCalledWith("pyright", { update: false });
  });
  expect(within(pyright).getByText("托管安装")).toBeInTheDocument();
  expect(within(pyright).getByText("可用")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "更新 Pyright" })).toBeEnabled();
});

test("settings screen recovers after an admin language service re-detect failure", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const refresh = vi.spyOn(client, "refreshLanguageServerCatalog")
    .mockRejectedValueOnce(new Error("网络暂不可用"))
    .mockImplementation(() => MockWebBotClient.prototype.refreshLanguageServerCatalog.call(client));

  render(
    <SettingsScreen
      botAlias="main"
      client={client}
      onLogout={() => undefined}
      sessionCapabilities={["admin_ops"]}
    />,
  );

  expect(await screen.findByRole("heading", { name: "语言服务" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重新检测语言服务" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("网络暂不可用");
  expect(screen.getByRole("button", { name: "重新检测语言服务" })).toBeEnabled();

  await user.click(screen.getByRole("button", { name: "重新检测语言服务" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("settings screen hides language service admin actions from non-admin users", async () => {
  render(
    <SettingsScreen
      botAlias="main"
      client={new MockWebBotClient()}
      onLogout={() => undefined}
      sessionCapabilities={["view_file_tree"]}
    />,
  );

  expect(await screen.findByRole("heading", { name: "语言服务" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "安装 Pyright" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重新检测语言服务" })).not.toBeInTheDocument();
  expect(screen.getAllByText("仅管理员可以安装或更新语言服务。")).toHaveLength(2);
});

test("language service panel ignores a stale re-detect response after installation", async () => {
  const user = userEvent.setup();
  const client = new DeferredLanguageServicesClient();
  const staleCatalog = await client.getLanguageServerCatalog("main");

  render(<LanguageServicesPanel botAlias="main" client={client} canManage />);

  const pyright = await screen.findByTestId("language-service-pyright");
  await user.click(screen.getByRole("button", { name: "重新检测语言服务" }));
  await user.click(screen.getByRole("button", { name: "安装 Pyright" }));
  await waitFor(() => expect(within(pyright).getByText("可用")).toBeInTheDocument());

  await act(async () => {
    client.resolveRefresh(staleCatalog);
    await Promise.resolve();
  });

  expect(within(pyright).getByText("可用")).toBeInTheDocument();
});

test("language service panel keeps an admin rejection recoverable", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.loginGuest();

  render(<LanguageServicesPanel botAlias="main" client={client} canManage />);

  const install = await screen.findByRole("button", { name: "安装 Pyright" });
  await user.click(install);
  expect(await screen.findByRole("alert")).toHaveTextContent("当前账号没有此操作权限，请联系管理员");
  expect(install).toBeEnabled();

  await client.login({ username: "alice", password: "test" });
  await user.click(install);
  await waitFor(() => expect(screen.getByTestId("language-service-status-pyright")).toHaveTextContent("可用"));
});
