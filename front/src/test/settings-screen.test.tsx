import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { SettingsScreen } from "../screens/SettingsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { DirectoryListing, TunnelSnapshot } from "../services/types";
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

test("git proxy controls stack on narrow screens", async () => {
  render(<SettingsScreen botAlias="main" client={new MockWebBotClient()} onLogout={() => undefined} />);

  const row = await screen.findByTestId("git-proxy-control-row");
  expect(row).toHaveClass("flex-col", "sm:flex-row", "sm:items-center");
  expect(screen.getByLabelText("Git 代理地址")).toHaveClass("w-full", "min-w-0", "flex-1");
  expect(screen.getByRole("button", { name: "保存 Git 代理" })).toHaveClass("tcb-solid-accent", "w-full", "sm:w-auto");
});

class FixedForwardSettingsClient extends MockWebBotClient {
  async getTunnelStatus(): Promise<TunnelSnapshot> {
    return {
      mode: "fixed_public_forward",
      status: "running",
      source: "fixed_public_forward",
      publicUrl: "http://124.221.226.63:18088/node/nanjing-laptop",
      localUrl: "http://127.0.0.1:8765",
      lastError: "",
      verified: true,
      fixedPublicForwardEnabled: true,
      nodeId: "nanjing-laptop",
      basePath: "/node/nanjing-laptop",
    };
  }
}

test("fixed public forward hides quick tunnel controls in settings", async () => {
  render(<SettingsScreen botAlias="main" client={new FixedForwardSettingsClient()} onLogout={() => undefined} />);

  expect(await screen.findByText("固定公网转发")).toBeInTheDocument();
  expect(screen.getByText("固定公网转发在管理中心配置")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "启动 Tunnel" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "停止 Tunnel" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /重启 Tunnel/ })).not.toBeInTheDocument();
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








test("settings screen supports kimi cli type", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);

  const cliTypeSelect = await screen.findByLabelText("CLI 类型");
  expect(screen.getByRole("option", { name: "kimi" })).toBeInTheDocument();
  await user.selectOptions(cliTypeSelect, "kimi");
  expect(cliTypeSelect).toHaveValue("kimi");
  expect(screen.getByLabelText("CLI 路径")).toHaveAttribute("placeholder", "kimi");
});







