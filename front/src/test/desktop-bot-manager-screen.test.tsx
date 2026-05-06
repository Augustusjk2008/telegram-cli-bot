import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { DesktopBotManagerScreen } from "../screens/DesktopBotManagerScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotSummary, CreateBotInput, DirectoryListing } from "../services/types";

class DesktopManagerClient extends MockWebBotClient {
  browserPath = "C:\\workspace";
  addBotCalls: CreateBotInput[] = [];
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
        cliPath: "codex",
        botMode: "cli",
        status: "running",
        serviceStatus: "online",
        activityStatus: "idle",
        workingDir: "C:\\workspace\\main",
        lastActiveText: "运行中",
        avatarName: "avatar_01.png",
        isMain: true,
      },
      {
        alias: "review",
        cliType: "claude",
        cliPath: "claude",
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
    ];
  }

  async getCurrentPath(): Promise<string> {
    return "C:\\workspace";
  }

  async listFiles(): Promise<DirectoryListing> {
    return {
      workingDir: this.browserPath,
      entries: this.directoryMap[this.browserPath] || [],
    };
  }

  async changeDirectory(_botAlias: string, path: string): Promise<string> {
    if (path === "..") {
      this.browserPath = "C:\\workspace";
      return this.browserPath;
    }
    this.browserPath = path.includes(":")
      ? path
      : `${this.browserPath}\\${path}`;
    return this.browserPath;
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
  removeBotCalls: string[] = [];

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

  async removeBot(botAlias: string): Promise<void> {
    this.removeBotCalls.push(botAlias);
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

test("desktop bot manager searches busy agent names", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.type(screen.getByLabelText("搜索智能体"), "代码审查");

  const list = screen.getByTestId("desktop-bot-manager-list");
  expect(within(list).getByRole("button", { name: /review/ })).toBeInTheDocument();
  expect(within(list).queryByRole("button", { name: /main/ })).not.toBeInTheDocument();
});

test("desktop bot manager selects rows without entering and enters from details", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();
  const onSelect = vi.fn();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={onSelect} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: /review/ }));
  expect(onSelect).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "进入 review" }));
  expect(onSelect).toHaveBeenCalledWith("review");
});

test("desktop bot manager creates a bot from detail panel", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: "新增智能体" }));
  await user.type(screen.getByLabelText("新智能体别名"), "team3");
  await user.type(screen.getByLabelText("新智能体 CLI 路径"), "codex");
  await user.type(screen.getByLabelText("新智能体工作目录"), "C:\\workspace\\team3");
  await user.click(screen.getByRole("button", { name: "创建智能体" }));

  await waitFor(() => {
    expect(client.addBotCalls).toHaveLength(1);
  });
  expect(client.addBotCalls[0]).toMatchObject({
    alias: "team3",
    cliPath: "codex",
    workingDir: "C:\\workspace\\team3",
  });
});

test("desktop bot manager edits alias and blocks main destructive actions", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();
  const renameSpy = vi.spyOn(client, "renameBot");
  const removeSpy = vi.spyOn(client, "removeBot");

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  expect(screen.queryByRole("button", { name: "删除 main" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /review/ }));
  await user.click(screen.getByRole("button", { name: "编辑 review" }));
  const aliasInput = screen.getByLabelText("智能体别名");
  await user.clear(aliasInput);
  await user.type(aliasInput, "reviewer");
  await user.click(screen.getByRole("button", { name: "保存智能体" }));

  await waitFor(() => {
    expect(renameSpy).toHaveBeenCalledWith("review", "reviewer");
  });
  expect(removeSpy).not.toHaveBeenCalled();
});

test("desktop bot manager requires confirmation before deleting managed bot", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  const removeSpy = vi.spyOn(client, "removeBot");

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: /review/ }));
  await user.click(screen.getByRole("button", { name: "删除 review" }));

  expect(confirmSpy).toHaveBeenCalledWith("确定删除智能体 review 吗？");
  expect(removeSpy).toHaveBeenCalledWith("review");
});

test("desktop bot manager confirms before leaving dirty edit", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: /review/ }));
  await user.click(screen.getByRole("button", { name: "编辑 review" }));
  await user.type(screen.getByLabelText("智能体 CLI 路径"), ".cmd");
  await user.click(screen.getByRole("button", { name: /offline-team/ }));

  expect(confirmSpy).toHaveBeenCalledWith("当前智能体配置有未保存修改，继续会丢失这些修改。确定继续吗？");
  expect(screen.getByRole("button", { name: "保存智能体" })).toBeInTheDocument();
});

test("desktop bot manager shows fleet table, attention filter, and agent inspector", async () => {
  const user = userEvent.setup();
  const client = new FleetConsoleClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  expect(await screen.findByRole("table", { name: "智能体舰队" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "需处理" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Agent" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "需处理" }));
  const table = screen.getByRole("table", { name: "智能体舰队" });
  expect(within(table).queryByText("main")).not.toBeInTheDocument();
  expect(within(table).getByText("review")).toBeInTheDocument();
  expect(within(table).getByText("offline-team")).toBeInTheDocument();
  expect(within(table).getByText("duplicate-a")).toBeInTheDocument();
  expect(screen.getAllByText("工作目录重复").length).toBeGreaterThan(0);

  await user.click(within(table).getByRole("button", { name: "聚焦 review" }));
  await user.click(screen.getByRole("button", { name: "Agent" }));
  const agentPanel = (await screen.findByRole("heading", { name: "子 agent" })).closest("section");
  expect(agentPanel).not.toBeNull();
  expect(within(agentPanel as HTMLElement).getAllByText("主 agent").length).toBeGreaterThan(0);
  expect(within(agentPanel as HTMLElement).getByText("代码审查")).toBeInTheDocument();
  expect(screen.getAllByText("处理中").length).toBeGreaterThan(0);
});

test("desktop bot manager agent tab loads real child agents and config tab embeds cli params", async () => {
  const user = userEvent.setup();
  const client = new DesktopManagerClient();
  const listAgents = vi.spyOn(client, "listAgents");

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.click(screen.getByRole("button", { name: /review/ }));
  await user.click(screen.getByRole("button", { name: "编辑 review" }));
  expect(await screen.findByText("CLI 参数")).toBeInTheDocument();
  expect(screen.getByLabelText("推理努力程度")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Agent" }));
  await waitFor(() => {
    expect(listAgents).toHaveBeenCalledWith("review");
  });
  const agentPanel = (await screen.findByRole("heading", { name: "子 agent" })).closest("section");
  expect(agentPanel).not.toBeNull();
  expect(within(agentPanel as HTMLElement).getByText("代码审查")).toBeInTheDocument();
  expect(within(agentPanel as HTMLElement).getAllByText("主 agent").length).toBeGreaterThan(0);
});

test("desktop bot manager bulk starts only offline managed bots", async () => {
  const user = userEvent.setup();
  const client = new FleetConsoleClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("table", { name: "智能体舰队" });
  await user.click(screen.getByLabelText("选择 main"));
  await user.click(screen.getByLabelText("选择 offline-team"));
  await user.click(screen.getByRole("button", { name: "批量启动" }));

  await waitFor(() => {
    expect(client.startBotCalls).toEqual(["offline-team"]);
  });
  expect(screen.getByText("已启动 1 个，跳过 1 个")).toBeInTheDocument();
  expect(screen.getByText("main: 主 bot 不支持批量启动")).toBeInTheDocument();
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

test("desktop bot manager confirms bulk delete and skips main", async () => {
  const user = userEvent.setup();
  const client = new FleetConsoleClient();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("table", { name: "智能体舰队" });
  await user.click(screen.getByLabelText("选择 main"));
  await user.click(screen.getByLabelText("选择 duplicate-a"));
  await user.click(screen.getByRole("button", { name: "批量删除" }));

  expect(confirmSpy).toHaveBeenCalledWith("确定删除 1 个智能体吗？将跳过 1 个不可删除项。");
  await waitFor(() => {
    expect(client.removeBotCalls).toEqual(["duplicate-a"]);
  });
  expect(screen.getByText("已删除 1 个，跳过 1 个")).toBeInTheDocument();
});
