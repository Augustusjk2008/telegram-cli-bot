import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { SettingsScreen } from "../screens/SettingsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { AppUpdateStatus, CreateAssistantCronJobInput, DirectoryListing } from "../services/types";

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
  expect(screen.queryByRole("button", { name: "浏览工作目录" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存工作目录" })).not.toBeInTheDocument();
  expect(screen.getByText("assistant 型 Bot 的默认工作目录已锁定")).toBeInTheDocument();
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

test("embedded settings can prefill the workdir without rendering logout controls", async () => {
  const client = new MockWebBotClient();

  render(
    <SettingsScreen
      botAlias="main"
      client={client}
      onLogout={() => undefined}
      embedded
      prefilledWorkdir="C:\\workspace\\picked"
    />,
  );

  expect(await screen.findByLabelText("工作目录")).toHaveValue("C:\\workspace\\picked");
  expect(screen.queryByRole("button", { name: "退出登录" })).not.toBeInTheDocument();
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

test("CLI type selector only shows codex and claude", async () => {
  const client = new MockWebBotClient();

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  const select = await screen.findByLabelText("CLI 类型");
  const options = within(select).getAllByRole("option").map((item) => item.textContent);

  expect(options).toEqual(["codex", "claude"]);
});

test("main settings merge update controls into the main bot operations card", async () => {
  const client = new MockWebBotClient();

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  const opsRegion = await screen.findByRole("region", { name: "主 Bot 运维" });
  expect(within(opsRegion).getByRole("heading", { name: "运行配置" })).toBeInTheDocument();
  expect(within(opsRegion).getByLabelText("CLI 类型")).toBeInTheDocument();
  expect(within(opsRegion).getByLabelText("工作目录")).toBeInTheDocument();
  expect(within(opsRegion).getByRole("heading", { name: "版本更新" })).toBeInTheDocument();
  expect(within(opsRegion).getByText("当前版本")).toBeInTheDocument();
  expect(within(opsRegion).getByText("自动下载更新")).toBeInTheDocument();
  expect(within(opsRegion).queryByRole("button", { name: "立即检查" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重建前端" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重启服务" })).not.toBeInTheDocument();
  expect(screen.getAllByRole("heading", { name: "版本更新" })).toHaveLength(1);
});

test("assistant settings hide the update controls", async () => {
  const client = new MockWebBotClient();

  render(<SettingsScreen botAlias="assistant1" client={client} onLogout={() => undefined} />);
  expect(screen.queryByText("版本更新")).not.toBeInTheDocument();
});

test("manual assistant automation dispatches a chat handoff event", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const dispatchSpy = vi.spyOn(window, "dispatchEvent");

  await client.addBot({
    alias: "assistant1",
    botMode: "assistant",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\assistant1",
    avatarName: "avatar_01.png",
  });
  await client.createAssistantCronJob("assistant1", {
    id: "email_recvbox_check",
    enabled: true,
    title: "收件箱检查",
    schedule: {
      type: "interval",
      everySeconds: 300,
      timezone: "Asia/Shanghai",
      misfirePolicy: "skip",
    },
    task: {
      prompt: "检查最近邮件并总结重点",
    },
    execution: {
      timeoutSeconds: 600,
    },
  } satisfies CreateAssistantCronJobInput);

  render(<SettingsScreen botAlias="assistant1" client={client} onLogout={() => undefined} />);

  await user.click(await screen.findByRole("button", { name: "立即运行 收件箱检查" }));

  await waitFor(() => {
    expect(dispatchSpy).toHaveBeenCalled();
  });

  const event = dispatchSpy.mock.calls.find(([value]) => value instanceof CustomEvent)?.[0] as CustomEvent | undefined;
  expect(event?.type).toBe("assistant-cron-run-enqueued");
  expect(event?.detail).toMatchObject({
    botAlias: "assistant1",
    runId: expect.stringMatching(/^run_/),
    prompt: "检查最近邮件并总结重点",
  });
});

test("dream assistant automation stays silent and does not dispatch a chat handoff event", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const dispatchSpy = vi.spyOn(window, "dispatchEvent");

  await client.addBot({
    alias: "assistant1",
    botMode: "assistant",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\assistant1",
    avatarName: "avatar_01.png",
  });
  await client.createAssistantCronJob("assistant1", {
    id: "daily_dream",
    enabled: true,
    title: "晨间 Dream",
    schedule: {
      type: "interval",
      everySeconds: 300,
      timezone: "Asia/Shanghai",
      misfirePolicy: "skip",
    },
    task: {
      prompt: "根据近期工作做自我完善",
      mode: "dream",
      lookbackHours: 24,
      historyLimit: 40,
      captureLimit: 20,
      deliverMode: "silent",
    },
    execution: {
      timeoutSeconds: 600,
    },
  } satisfies CreateAssistantCronJobInput);
  vi.spyOn(client, "runAssistantCronJob").mockResolvedValue({
    runId: "run_dream_1",
    status: "queued",
    taskMode: "dream",
    deliverMode: "silent",
  });

  render(<SettingsScreen botAlias="assistant1" client={client} onLogout={() => undefined} />);
  dispatchSpy.mockClear();

  await user.click(await screen.findByRole("button", { name: "立即运行 晨间 Dream" }));

  await waitFor(() => {
    expect(screen.getByText(/Dream 任务已入队，将在后台静默执行/)).toBeInTheDocument();
  });

  const handoffEvent = dispatchSpy.mock.calls
    .map(([event]) => event)
    .find((event) => event instanceof CustomEvent && event.type === "assistant-cron-run-enqueued");
  expect(handoffEvent).toBeUndefined();
});

test("settings screen shows dream fields when cron mode switches to dream", async () => {
  const user = userEvent.setup();
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

  await user.selectOptions(await screen.findByLabelText("任务模式"), "dream");

  expect(screen.getByLabelText("回看小时数")).toBeInTheDocument();
  expect(screen.getByLabelText("聊天历史条数")).toBeInTheDocument();
  expect(screen.getByLabelText("Capture 条数")).toBeInTheDocument();
  expect(screen.getByLabelText("投递方式")).toHaveValue("silent");
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
    expect(screen.getByRole("dialog", { name: "更新日志" })).toBeInTheDocument();
  });
});
