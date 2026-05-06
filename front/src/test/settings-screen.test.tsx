import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { SettingsScreen } from "../screens/SettingsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { AppUpdateStatus, DirectoryListing } from "../services/types";

class StreamingUpdateClient extends MockWebBotClient {
  releaseDownload: (() => void) | null = null;

  async downloadUpdateStream(
    onProgress: (event: { phase: string; downloadedBytes: number; totalBytes?: number; percent?: number; message?: string }) => void,
  ): Promise<AppUpdateStatus> {
    onProgress({
      phase: "log",
      downloadedBytes: 0,
      message: "开始下载更新包",
    });
    onProgress({
      phase: "log",
      downloadedBytes: 0,
      message: "已下载 50%",
    });
    await new Promise<void>((resolve) => {
      this.releaseDownload = resolve;
    });
    onProgress({
      phase: "log",
      downloadedBytes: 0,
      message: "下载完成",
    });
    return this.downloadUpdate();
  }
}

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

test("assistant bots lock the default workdir in settings", async () => {
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "assistant1",
    botMode: "assistant",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\assistant1",
    avatarName: "avatar_01.png",
  });

  render(<SettingsScreen botAlias="assistant1" client={client} onLogout={() => undefined} />);

  expect(await screen.findByLabelText("工作目录")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存工作目录" })).not.toBeInTheDocument();
  expect(screen.getByText("assistant 型 Bot 的默认工作目录已锁定")).toBeInTheDocument();
});

test("assistant settings do not render assistant ops console", async () => {
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "assistant1",
    botMode: "assistant",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\assistant1",
    avatarName: "avatar_01.png",
  });

  render(<SettingsScreen botAlias="assistant1" client={client} onLogout={() => undefined} />);

  expect(await screen.findByLabelText("工作目录")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Assistant 运维台" })).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Proposal" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Automation 定时任务" })).not.toBeInTheDocument();
});

test("settings screen shows child agent empty state on cli bot page", async () => {
  const client = new MockWebBotClient();

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  expect(await screen.findByText("暂无子 agent")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "新增 agent" })).toBeInTheDocument();
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

test("agent settings save cluster write permission", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const createAgent = vi.spyOn(client, "createAgent");

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  await user.click(await screen.findByRole("button", { name: "新增 agent" }));
  await user.type(screen.getByLabelText("Agent ID"), "impl");
  await user.type(screen.getByLabelText("名称"), "实现");
  await user.click(screen.getByLabelText("允许修改文件"));
  await user.click(screen.getByRole("button", { name: "保存" }));

  await waitFor(() => {
    expect(createAgent).toHaveBeenCalledWith("main", expect.objectContaining({
      id: "impl",
      cluster: expect.objectContaining({ allowWrite: true }),
    }));
  });
});

test("settings screen hides agent management for assistant bot", async () => {
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "assistant1",
    botMode: "assistant",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\assistant1",
    avatarName: "avatar_01.png",
  });

  render(<SettingsScreen botAlias="assistant1" client={client} onLogout={() => undefined} />);

  expect(await screen.findByLabelText("工作目录")).toBeInTheDocument();
  expect(screen.queryByText("子 agent")).not.toBeInTheDocument();
});

test("settings can browse and pick a workdir before saving", async () => {
  const user = userEvent.setup();
  const client = new SettingsDirectoryPickerClient();

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  expect(await screen.findByLabelText("工作目录")).toHaveValue("C:\\workspace");

  await user.click(screen.getByRole("button", { name: "浏览工作目录" }));

  const dialog = await screen.findByRole("dialog", { name: "选择工作目录" });
  expect(within(dialog).getByText("C:\\workspace")).toBeInTheDocument();

  await user.click(within(dialog).getByRole("button", { name: "进入目录 repos" }));
  await user.click(await within(dialog).findByRole("button", { name: "进入目录 team-a" }));

  expect(within(dialog).getByText("C:\\workspace\\repos\\team-a")).toBeInTheDocument();
  await user.click(within(dialog).getByRole("button", { name: "使用当前目录" }));

  await waitFor(() => {
    expect(screen.queryByRole("dialog", { name: "选择工作目录" })).not.toBeInTheDocument();
  });

  expect(screen.getByLabelText("工作目录")).toHaveValue("C:\\workspace\\repos\\team-a");
  expect(client.browserPath).toBe("C:\\workspace");
});

test("settings screen asks for confirmation before resetting the current workdir conversation", async () => {
  const user = userEvent.setup();
  const updateBotWorkdir = vi.fn()
    .mockRejectedValueOnce(
      Object.assign(new Error("切换工作目录会丢失当前会话，确认后重试"), {
        name: "WebApiClientError",
        code: "workdir_change_requires_reset",
        status: 409,
        data: {
          currentWorkingDir: "C:\\workspace\\old",
          requestedWorkingDir: "C:\\workspace\\new",
          historyCount: 2,
          messageCount: 5,
          botMode: "cli",
        },
      }),
    )
    .mockResolvedValueOnce({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\new",
      lastActiveText: "运行中",
      avatarName: "avatar_01.png",
    });

  const client = new MockWebBotClient();
  vi.spyOn(client, "updateBotWorkdir").mockImplementation(updateBotWorkdir);

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  const input = await screen.findByLabelText("工作目录");
  await user.clear(input);
  await user.type(input, "C:\\workspace\\new");
  await user.click(screen.getByRole("button", { name: "保存工作目录" }));

  expect(await screen.findByRole("dialog", { name: "确认切换工作目录" })).toBeInTheDocument();
  expect(screen.getByText("切换工作目录会丢失当前会话。")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "确认并切换" }));

  await waitFor(() => {
    expect(updateBotWorkdir).toHaveBeenNthCalledWith(2, "main", "C:\\workspace\\new", { forceReset: true });
  });
  expect(await screen.findByText("工作目录已更新")).toBeInTheDocument();
});

test("main settings split update controls into separate card", async () => {
  const client = new MockWebBotClient();

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  const opsRegion = await screen.findByRole("region", { name: "主 Bot 运维" });
  expect(within(opsRegion).getByRole("heading", { name: "运行配置" })).toBeInTheDocument();
  expect(within(opsRegion).getByLabelText("CLI 类型")).toBeInTheDocument();
  expect(within(opsRegion).getByLabelText("工作目录")).toBeInTheDocument();
  expect(within(opsRegion).queryByRole("heading", { name: "版本更新" })).not.toBeInTheDocument();
  const updateRegion = screen.getByRole("region", { name: "版本更新" });
  expect(within(updateRegion).getByText("当前版本")).toBeInTheDocument();
  expect(within(updateRegion).getByText("自动下载更新")).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { name: "版本更新" })).toHaveLength(1);
});

test("main settings saves Git proxy address and port shortcut", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateGitProxySettings = vi.spyOn(client, "updateGitProxySettings");

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  const input = await screen.findByLabelText("Git 代理地址");
  await user.clear(input);
  await user.type(input, "192.168.1.10:7897");
  await user.click(screen.getByRole("button", { name: "保存 Git 代理" }));

  await waitFor(() => {
    expect(updateGitProxySettings).toHaveBeenLastCalledWith("192.168.1.10:7897");
  });
  expect(await screen.findByText("当前状态: 192.168.1.10:7897")).toBeInTheDocument();

  await user.clear(input);
  await user.type(input, "7898");
  await user.click(screen.getByRole("button", { name: "保存 Git 代理" }));

  await waitFor(() => {
    expect(updateGitProxySettings).toHaveBeenLastCalledWith("7898");
  });
  expect(await screen.findByText("当前状态: 127.0.0.1:7898")).toBeInTheDocument();
});

test("desktop settings show migration notice instead of bot runtime forms", async () => {
  const user = userEvent.setup();
  const onOpenBotManager = vi.fn();
  const client = new MockWebBotClient();

  render(
    <SettingsScreen
      botAlias="main"
      client={client}
      onLogout={() => undefined}
      showBotRuntimeSettings={false}
      onOpenBotManager={onOpenBotManager}
    />,
  );

  expect(await screen.findByText("智能体配置已迁移")).toBeInTheDocument();
  expect(screen.queryByLabelText("工作目录")).not.toBeInTheDocument();
  expect(screen.queryByText("子 agent")).not.toBeInTheDocument();
  expect(screen.queryByText("CLI 参数")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "打开智能体管理" }));
  expect(onOpenBotManager).toHaveBeenCalledTimes(1);
});

test("main settings show update log modal and restart guidance after download", async () => {
  const user = userEvent.setup();
  const client = new StreamingUpdateClient();

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  await user.click(await screen.findByRole("button", { name: "下载更新" }));

  const dialog = await screen.findByRole("dialog", { name: "更新日志" });
  expect(dialog).toBeInTheDocument();
  expect(dialog).toHaveTextContent("开始下载更新包");
  expect(dialog).toHaveTextContent("已下载 50%");
  expect(screen.queryByText("下载进行中，请不要刷新或离开当前页面。")).not.toBeInTheDocument();

  const beforeUnloadEvent = new Event("beforeunload", { cancelable: true }) as Event & { returnValue?: unknown };
  Object.defineProperty(beforeUnloadEvent, "returnValue", {
    configurable: true,
    enumerable: true,
    writable: true,
    value: undefined,
  });
  window.dispatchEvent(beforeUnloadEvent);

  expect(beforeUnloadEvent.defaultPrevented).toBe(true);
  expect(beforeUnloadEvent.returnValue).toBe("");

  client.releaseDownload?.();

  await waitFor(() => {
    expect(dialog).toHaveTextContent(/重新运行 start\.bat/);
    expect(dialog).toHaveTextContent(/不要在页面里重启程序/);
  });
  await waitFor(() => {
    expect(screen.getByText(/待应用更新: .*（安装版）/)).toBeInTheDocument();
  });
  await waitFor(() => {
    expect(screen.getByRole("dialog", { name: "更新日志" })).toBeInTheDocument();
  });
});
