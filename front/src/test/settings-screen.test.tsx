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

test("main settings show update controls", async () => {
  const client = new MockWebBotClient();

  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);
  expect(await screen.findByText("版本更新")).toBeInTheDocument();
  expect(screen.getByText("当前版本")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "立即检查" })).toBeInTheDocument();
});

test("assistant settings hide the update controls", async () => {
  const client = new MockWebBotClient();

  render(<SettingsScreen botAlias="assistant1" client={client} onLogout={() => undefined} />);
  expect(screen.queryByText("版本更新")).not.toBeInTheDocument();
});
