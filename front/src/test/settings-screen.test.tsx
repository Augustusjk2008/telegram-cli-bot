import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { SettingsScreen } from "../screens/SettingsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";

test("assistant bots lock the default workdir in settings", async () => {
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "assistant1",
    token: "",
    botMode: "assistant",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\assistant1",
  });

  render(<SettingsScreen botAlias="assistant1" client={client} onLogout={() => undefined} />);

  expect(await screen.findByLabelText("工作目录")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存工作目录" })).not.toBeInTheDocument();
  expect(screen.getByText("assistant 型 Bot 的默认工作目录已锁定")).toBeInTheDocument();
});
