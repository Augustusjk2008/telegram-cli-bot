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
