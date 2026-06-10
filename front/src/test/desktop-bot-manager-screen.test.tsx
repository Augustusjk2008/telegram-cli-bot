import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { DesktopBotManagerScreen } from "../screens/DesktopBotManagerScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotExecutionConfigInput, BotSummary, CreateBotInput, DirectoryListing } from "../services/types";

class DesktopManagerClient extends MockWebBotClient {
  browserPath = "C:\\workspace";
  listPaths: Array<string | undefined> = [];
  changeDirectoryCalls: Array<{ botAlias: string; path: string }> = [];
  addBotCalls: CreateBotInput[] = [];
  updateBotExecutionConfigCalls: Array<{ botAlias: string; input: BotExecutionConfigInput }> = [];
  createDirectoryCalls: Array<{ botAlias: string; name: string; parentPath?: string }> = [];
  removeBotCalls: Array<{ botAlias: string; deleteHistory: boolean }> = [];
  private readonly directoryMap: Record<string, DirectoryListing["entries"]> = {
    "C:\\workspace": [
      { name: "team3", isDir: true },
    ],
    "C:\\workspace\\team3": [],
  };

  async listBots(): Promise<BotSummary[]> {
    return [
      {
        alias: "main",
        cliType: "codex",
        cliPath: "C:\\tools\\codex.exe",
        botMode: "cli",
        status: "running",
        serviceStatus: "online",
        activityStatus: "idle",
        workingDir: "C:\\workspace\\main",
        lastActiveText: "运行中",
        avatarName: "avatar_01.png",
        isMain: true,
        supportedExecutionModes: ["cli"],
        defaultExecutionMode: "cli",
        nativeAgent: { provider: "", model: "", piAgent: "" },
      },
      {
        alias: "review",
        cliType: "claude",
        cliPath: "C:\\tools\\claude.cmd",
        botMode: "cli",
        status: "busy",
        serviceStatus: "online",
        activityStatus: "busy",
        busyAgentIds: ["reviewer"],
        busyAgentNames: ["代码审查"],
        busyAgentCount: 1,
        workingDir: "C:\\workspace\\review",
        lastActiveText: "处理中",
        avatarName: "avatar_02.png",
        supportedExecutionModes: ["native_agent"],
        defaultExecutionMode: "native_agent",
        nativeAgent: {
          provider: "anthropic",
          model: "claude-sonnet-4-5",
          piAgent: "reviewer",
          baseUrl: "https://cdn.codeflow.asia/v1",
          hasApiKey: true,
          apiKeyMasked: "sk-****1234",
        },
      },
      {
        alias: "offline-team",
        cliType: "codex",
        cliPath: "codex",
        botMode: "cli",
        status: "offline",
        serviceStatus: "offline",
        activityStatus: "idle",
        workingDir: "C:\\workspace\\offline",
        lastActiveText: "离线",
        avatarName: "avatar_03.png",
        supportedExecutionModes: ["cli"],
        defaultExecutionMode: "cli",
        nativeAgent: { provider: "", model: "", piAgent: "" },
      },
    ];
  }

  async getCurrentPath(): Promise<string> {
    return "C:\\workspace";
  }

  async listFiles(_botAlias?: string, path?: string): Promise<DirectoryListing> {
    this.listPaths.push(path);
    const nextPath = path || this.browserPath;
    return {
      workingDir: nextPath,
      entries: this.directoryMap[nextPath] || [],
    };
  }

  async changeDirectory(_botAlias: string, path: string): Promise<string> {
    this.changeDirectoryCalls.push({ botAlias: _botAlias, path });
    if (path === "..") {
      this.browserPath = "C:\\workspace";
      return this.browserPath;
    }
    this.browserPath = path.includes(":")
      ? path
      : `${this.browserPath}\\${path}`;
    return this.browserPath;
  }

  async createDirectory(botAlias: string, name: string, parentPath?: string): Promise<void> {
    this.createDirectoryCalls.push({ botAlias, name, parentPath });
    const basePath = parentPath || this.browserPath;
    const currentEntries = [...(this.directoryMap[basePath] || [])];
    currentEntries.push({ name, isDir: true });
    this.directoryMap[basePath] = currentEntries;
    this.directoryMap[`${basePath}\\${name}`] = [];
  }

  async addBot(input: CreateBotInput) {
    this.addBotCalls.push(input);
    return {
      alias: input.alias,
      cliType: input.cliType,
      cliPath: input.cliPath,
      botMode: input.botMode,
      status: "running" as const,
      serviceStatus: "online" as const,
      activityStatus: "idle" as const,
      workingDir: input.workingDir,
      lastActiveText: "运行中",
      avatarName: input.avatarName,
      supportedExecutionModes: input.supportedExecutionModes,
      defaultExecutionMode: input.defaultExecutionMode,
      nativeAgent: input.nativeAgent,
    };
  }

  async updateBotCli(botAlias: string, cliType: string, cliPath: string): Promise<BotSummary> {
    const bot = (await this.listBots()).find((item) => item.alias === botAlias);
    return {
      ...(bot || {
        alias: botAlias,
        status: "running" as const,
        serviceStatus: "online" as const,
        activityStatus: "idle" as const,
        workingDir: `C:\\workspace\\${botAlias}`,
        lastActiveText: "运行中",
      }),
      cliType: cliType as BotSummary["cliType"],
      cliPath,
    };
  }

  async updateBotExecutionConfig(botAlias: string, input: BotExecutionConfigInput): Promise<BotSummary> {
    this.updateBotExecutionConfigCalls.push({ botAlias, input });
    return {
      alias: botAlias,
      cliType: "claude",
      cliPath: "C:\\tools\\claude.cmd",
      botMode: "cli",
      status: "running",
      serviceStatus: "online",
      activityStatus: "idle",
      workingDir: `C:\\workspace\\${botAlias}`,
      lastActiveText: "运行中",
      supportedExecutionModes: input.supportedExecutionModes,
      defaultExecutionMode: input.defaultExecutionMode,
      nativeAgent: input.nativeAgent,
    };
  }

  async updateBotWorkdir(botAlias: string, workingDir: string): Promise<BotSummary> {
    const bot = (await this.listBots()).find((item) => item.alias === botAlias);
    return {
      ...(bot || {
        alias: botAlias,
        cliType: "codex" as const,
        cliPath: "codex",
        botMode: "cli",
        status: "running" as const,
        serviceStatus: "online" as const,
        activityStatus: "idle" as const,
        lastActiveText: "运行中",
      }),
      workingDir,
    };
  }

  async updateBotAvatar(botAlias: string, avatarName: string): Promise<BotSummary> {
    const bot = (await this.listBots()).find((item) => item.alias === botAlias);
    return {
      ...(bot || {
        alias: botAlias,
        cliType: "codex" as const,
        cliPath: "codex",
        botMode: "cli",
        status: "running" as const,
        serviceStatus: "online" as const,
        activityStatus: "idle" as const,
        workingDir: `C:\\workspace\\${botAlias}`,
        lastActiveText: "运行中",
      }),
      avatarName,
    };
  }

  async listAgents(botAlias: string) {
    if (botAlias === "review") {
      return {
        items: [
          { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true, isProcessing: true, messageCount: 5 },
          { id: "reviewer", name: "代码审查", systemPrompt: "先列风险", enabled: true, isMain: false, isProcessing: true, messageCount: 3 },
        ],
      };
    }
    return {
      items: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true, isProcessing: false, messageCount: 2 },
      ],
    };
  }

  async getCliParams() {
    return {
      cliType: "codex" as const,
      params: {
        model: "gpt-5.5",
        reasoning_effort: "xhigh",
      },
      defaults: {
        model: "gpt-5.4",
        reasoning_effort: "xhigh",
      },
      schema: {
        model: {
          type: "string" as const,
          description: "模型选择",
          nullable: true,
          enum: ["gpt-5.5", "gpt-5.4", "none"],
        },
        reasoning_effort: {
          type: "string" as const,
          description: "推理努力程度",
          enum: ["xhigh", "high", "medium", "low"],
        },
      },
    };
  }
}

class FleetConsoleClient extends MockWebBotClient {
  startBotCalls: string[] = [];
  stopBotCalls: string[] = [];
  removeBotCalls: Array<{ botAlias: string; deleteHistory: boolean }> = [];

  async listBots(): Promise<BotSummary[]> {
    return [
      {
        alias: "main",
        cliType: "codex",
        cliPath: "codex",
        botMode: "cli",
        status: "running",
        serviceStatus: "online",
        activityStatus: "idle",
        workingDir: "C:\\workspace\\main",
        lastActiveText: "运行中",
        avatarName: "avatar_01.png",
        isMain: true,
        agents: [
          { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true, isProcessing: false, messageCount: 2 },
        ],
      },
      {
        alias: "review",
        cliType: "claude",
        cliPath: "claude",
        botMode: "cli",
        status: "busy",
        serviceStatus: "online",
        activityStatus: "busy",
        busyAgentIds: ["main", "reviewer"],
        busyAgentNames: ["主 agent", "代码审查"],
        busyAgentCount: 2,
        workingDir: "C:\\workspace\\shared",
        lastActiveText: "处理中",
        avatarName: "avatar_02.png",
        agents: [
          { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true, isProcessing: true, messageCount: 5 },
          { id: "reviewer", name: "代码审查", systemPrompt: "", enabled: true, isMain: false, isProcessing: true, messageCount: 3 },
        ],
      },
      {
        alias: "offline-team",
        cliType: "codex",
        cliPath: "codex",
        botMode: "cli",
        status: "offline",
        serviceStatus: "offline",
        activityStatus: "idle",
        workingDir: "C:\\workspace\\offline",
        lastActiveText: "离线",
        avatarName: "avatar_03.png",
      },
      {
        alias: "duplicate-a",
        cliType: "codex",
        cliPath: "",
        botMode: "cli",
        status: "unread",
        serviceStatus: "online",
        activityStatus: "idle",
        workingDir: "C:\\workspace\\shared",
        lastActiveText: "有新消息",
        avatarName: "avatar_04.png",
      },
    ];
  }

  async startBot(botAlias: string): Promise<BotSummary> {
    this.startBotCalls.push(botAlias);
    return {
      alias: botAlias,
      cliType: "codex",
      cliPath: "codex",
      botMode: "cli",
      status: "running",
      serviceStatus: "online",
      activityStatus: "idle",
      workingDir: `C:\\workspace\\${botAlias}`,
      lastActiveText: "运行中",
    };
  }

  async stopBot(botAlias: string): Promise<BotSummary> {
    this.stopBotCalls.push(botAlias);
    return {
      alias: botAlias,
      cliType: "codex",
      cliPath: "codex",
      botMode: "cli",
      status: "offline",
      serviceStatus: "offline",
      activityStatus: "idle",
      workingDir: `C:\\workspace\\${botAlias}`,
      lastActiveText: "离线",
    };
  }

  async removeBot(botAlias: string, options?: { deleteHistory?: boolean }): Promise<void> {
    this.removeBotCalls.push({ botAlias, deleteHistory: Boolean(options?.deleteHistory) });
  }

  async listAgents(botAlias: string) {
    if (botAlias === "review") {
      return {
        items: [
          { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true, isProcessing: true, messageCount: 5 },
          { id: "reviewer", name: "代码审查", systemPrompt: "", enabled: true, isMain: false, isProcessing: true, messageCount: 3 },
        ],
      };
    }
    return {
      items: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true, isProcessing: false, messageCount: 2 },
      ],
    };
  }
}

test("desktop bot manager shows dense list and selected details", async () => {
  const client = new DesktopManagerClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  expect(await screen.findByRole("heading", { name: "智能体管理" })).toBeInTheDocument();
  expect(screen.getByTestId("desktop-bot-manager-screen")).toBeInTheDocument();
  expect(screen.getByText("总数 3")).toBeInTheDocument();
  expect(screen.getByText("在线 2")).toBeInTheDocument();
  expect(screen.getByText("处理中 1")).toBeInTheDocument();
  expect(screen.getByText("离线 1")).toBeInTheDocument();

  const list = screen.getByTestId("desktop-bot-manager-list");
  expect(within(list).getByRole("button", { name: /main/ })).toBeInTheDocument();
  expect(within(list).getByRole("button", { name: /review/ })).toBeInTheDocument();
  expect(within(list).getByRole("button", { name: /offline-team/ })).toBeInTheDocument();
  expect(screen.getAllByText("C:\\workspace\\main").length).toBeGreaterThan(0);
});



test("desktop bot manager creates a bot from detail panel", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: "新增智能体" }));
  expect(screen.getByLabelText("新智能体 CLI 路径")).toHaveValue("C:\\tools\\codex.exe");
  await user.selectOptions(screen.getByLabelText("新智能体 CLI 类型"), "claude");
  expect(screen.getByLabelText("新智能体 CLI 路径")).toHaveValue("C:\\tools\\claude.cmd");
  expect(screen.getByRole("option", { name: "kimi" })).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("新智能体 CLI 类型"), "kimi");
  expect(screen.getByLabelText("新智能体 CLI 路径")).toHaveValue("kimi");
  await user.type(screen.getByLabelText("新智能体别名"), "team3");
  expect(screen.getByLabelText("新智能体 CLI 路径")).toHaveAttribute("placeholder", "kimi");
  await user.type(screen.getByLabelText("新智能体工作目录"), "C:\\workspace\\team3");
  await user.click(screen.getByRole("button", { name: "创建智能体" }));

  await waitFor(() => {
    expect(client.addBotCalls).toHaveLength(1);
  });
  expect(client.addBotCalls[0]).toMatchObject({
    alias: "team3",
    cliType: "kimi",
    cliPath: "kimi",
    workingDir: "C:\\workspace\\team3",
  });
});

test("desktop bot manager creates a bot with native agent config", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: "新增智能体" }));
  await user.type(screen.getByLabelText("新智能体别名"), "native1");
  await user.type(screen.getByLabelText("新智能体工作目录"), "C:\\workspace\\native1");
  await user.selectOptions(screen.getByLabelText("运行后端"), "native_agent");
  expect(screen.queryByLabelText("原生 agent Provider")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("原生 agent Model")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("原生 agent Base URL")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("原生 agent API Key")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Pi agent"), { target: { value: "reviewer" } });
  await user.click(screen.getByRole("button", { name: "创建智能体" }));

  await waitFor(() => {
    expect(client.addBotCalls).toHaveLength(1);
  });
  expect(client.addBotCalls[0]).toMatchObject({
    alias: "native1",
    supportedExecutionModes: ["native_agent"],
    defaultExecutionMode: "native_agent",
    nativeAgent: {
      piAgent: "reviewer",
    },
  });
});

test("desktop bot manager edits native agent config", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="review" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: "配置" }));

  expect(screen.getByLabelText("运行后端")).toHaveValue("native_agent");
  expect(screen.queryByLabelText("智能体 CLI 类型")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("原生 agent Provider")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("原生 agent Model")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("原生 agent Base URL")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("原生 agent API Key")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Pi agent")).toHaveValue("reviewer");

  fireEvent.change(screen.getByLabelText("Pi agent"), { target: { value: "qa" } });
  await user.click(screen.getByRole("button", { name: "保存智能体" }));

  await waitFor(() => {
    expect(client.updateBotExecutionConfigCalls).toHaveLength(1);
  });
  expect(client.updateBotExecutionConfigCalls[0]).toMatchObject({
    botAlias: "review",
    input: {
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
      nativeAgent: {
        piAgent: "qa",
      },
    },
  });
});

test("desktop bot manager keeps native api key global", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="review" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: "配置" }));
  expect(screen.queryByRole("button", { name: "清除" })).not.toBeInTheDocument();
  expect(screen.getByText("Provider、模型、Base URL、API Key 和推理参数在全局环境配置中设置。")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "保存智能体" }));

  expect(client.updateBotExecutionConfigCalls).toHaveLength(0);
});

test("desktop bot manager switches native bot to cli backend", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="review" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: "配置" }));
  await user.selectOptions(screen.getByLabelText("运行后端"), "cli");
  await user.click(screen.getByRole("button", { name: "保存智能体" }));

  await waitFor(() => {
    expect(client.updateBotExecutionConfigCalls).toHaveLength(1);
  });
  expect(client.updateBotExecutionConfigCalls[0].input.supportedExecutionModes).toEqual(["cli"]);
  expect(client.updateBotExecutionConfigCalls[0].input.defaultExecutionMode).toBe("cli");
});

test("desktop bot manager shows native agent disabled note when global switch is off", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();
  vi.spyOn(client, "getEnvConfig").mockResolvedValue({
    envPath: ".env",
    examplePath: ".env.example",
    items: [{
      key: "NATIVE_AGENT_ENABLED",
      label: "启用原生 agent",
      description: "",
      type: "boolean",
      category: "native_agent",
      value: false,
      defaultValue: false,
      source: "env",
      sensitive: false,
      masked: false,
      restartRequired: true,
      rebuildRequired: false,
    }],
  });

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: "新增智能体" }));
  expect(await screen.findByText("原生 agent 全局未启用")).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "原生 agent" })).not.toBeInTheDocument();
});








test("desktop bot manager exposes cluster templates in config tab", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();
  const updateClusterConfig = vi.spyOn(client, "updateClusterConfig");

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: "聚焦 main" }));
  await user.click(screen.getByRole("button", { name: "配置" }));

  const parallelSelect = await screen.findByLabelText("并发子 agent 数");
  await user.selectOptions(parallelSelect, "4");

  await waitFor(() => expect(updateClusterConfig).toHaveBeenCalledWith("main", expect.objectContaining({
    maxParallelAgents: 4,
    writePolicy: "selected_agents",
    conflictPolicy: "snapshot_diff",
    defaultTimeoutSeconds: 600,
  })));
  expect(await screen.findByText("集群模板")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "预览 全量测试集群" })).toBeInTheDocument();
});







test("desktop bot manager bulk stops online managed bots and skips main", async () => {
  const user = userEvent.setup();
  const client = new FleetConsoleClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("table", { name: "智能体舰队" });
  await user.click(screen.getByLabelText("选择 main"));
  await user.click(screen.getByLabelText("选择 review"));
  await user.click(screen.getByRole("button", { name: "批量停止" }));

  await waitFor(() => {
    expect(client.stopBotCalls).toEqual(["review"]);
  });
  expect(screen.getByText("已停止 1 个，跳过 1 个")).toBeInTheDocument();
  expect(screen.getByText("main: 主 bot 不可停止")).toBeInTheDocument();
});

