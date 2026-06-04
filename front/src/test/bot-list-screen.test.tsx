import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { BotListScreen } from "../screens/BotListScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotSummary, CreateBotInput } from "../services/types";

class BotListClient extends MockWebBotClient {
  addBotCalls: CreateBotInput[] = [];

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
        isMain: true,
        supportedExecutionModes: ["cli"],
        defaultExecutionMode: "cli",
        nativeAgent: { command: "opencode", hostname: "127.0.0.1", port: 0 },
      },
    ];
  }

  async addBot(input: CreateBotInput): Promise<BotSummary> {
    this.addBotCalls.push(input);
    return {
      alias: input.alias,
      cliType: input.cliType,
      cliPath: input.cliPath,
      botMode: input.botMode,
      status: "running",
      serviceStatus: "online",
      activityStatus: "idle",
      workingDir: input.workingDir,
      lastActiveText: "运行中",
      supportedExecutionModes: input.supportedExecutionModes || ["cli"],
      defaultExecutionMode: input.defaultExecutionMode || "cli",
      nativeAgent: input.nativeAgent,
    };
  }
}

test("bot list creates bot with native agent config", async () => {
  const user = userEvent.setup();
  const client = new BotListClient();

  render(<BotListScreen client={client} onSelect={vi.fn()} onBotsChange={vi.fn()} />);

  await screen.findByRole("heading", { name: "智能体管理" });
  await user.type(screen.getByLabelText("新智能体别名"), "native1");
  await user.type(screen.getByLabelText("新智能体工作目录"), "C:\\workspace\\native1");
  await user.click(screen.getByLabelText("启用原生 agent"));
  await user.selectOptions(screen.getByLabelText("默认执行模式"), "native_agent");
  fireEvent.change(screen.getByLabelText("原生 agent 命令"), { target: { value: "C:\\tools\\opencode.exe" } });
  await user.clear(screen.getByLabelText("原生 agent 端口"));
  await user.type(screen.getByLabelText("原生 agent 端口"), "4096");
  await user.click(screen.getByRole("button", { name: "创建智能体" }));

  await waitFor(() => {
    expect(client.addBotCalls).toHaveLength(1);
  });
  expect(client.addBotCalls[0]).toMatchObject({
    alias: "native1",
    supportedExecutionModes: ["cli", "native_agent"],
    defaultExecutionMode: "native_agent",
    nativeAgent: {
      command: "C:\\tools\\opencode.exe",
      hostname: "127.0.0.1",
      port: 4096,
    },
  });
});
