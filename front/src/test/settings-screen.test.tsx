import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { SettingsScreen } from "../screens/SettingsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";

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
  expect(within(opsRegion).getByRole("button", { name: "立即检查" })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { name: "版本更新" })).toHaveLength(1);
});

test("assistant settings hide the update controls", async () => {
  const client = new MockWebBotClient();

  render(<SettingsScreen botAlias="assistant1" client={client} onLogout={() => undefined} />);
  expect(screen.queryByText("版本更新")).not.toBeInTheDocument();
});
