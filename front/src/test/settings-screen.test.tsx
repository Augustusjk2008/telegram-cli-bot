import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { SettingsScreen } from "../screens/SettingsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { AppUpdateStatus, CreateAssistantCronJobInput } from "../services/types";

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

test("assistant bots lock the default workdir in settings", async () => {
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "assistant1",
    botMode: "assistant",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\assistant1",
    avatarName: "bot-default.png",
  });

  render(<SettingsScreen botAlias="assistant1" client={client} onLogout={() => undefined} />);

  expect(await screen.findByLabelText("工作目录")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存工作目录" })).not.toBeInTheDocument();
  expect(screen.getByText("assistant 型 Bot 的默认工作目录已锁定")).toBeInTheDocument();
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
    avatarName: "bot-default.png",
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

  const beforeUnloadEvent = new Event("beforeunload", { cancelable: true }) as Event & { returnValue?: string };
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
