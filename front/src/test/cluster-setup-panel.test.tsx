import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { ClusterSetupPanel } from "../components/ClusterSetupPanel";
import { MockWebBotClient } from "../services/mockWebBotClient";

test("cluster setup panel shows status and prepare command", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  render(<ClusterSetupPanel botAlias="main" client={client} />);

  expect(await screen.findByText("集群 MCP")).toBeInTheDocument();
  expect(screen.getByText("tcb-cluster")).toBeInTheDocument();
  expect(screen.getByText(/Codex：/)).toBeInTheDocument();
  expect(screen.queryByText(/Claude：/)).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "生成安装命令" }));

  await waitFor(() => {
    expect(screen.getByText(/codex mcp add tcb-cluster/)).toBeInTheDocument();
  });
});

test("cluster setup panel shows kimi status and prepare command for kimi bot", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "kimi-team",
    botMode: "cli",
    cliType: "kimi",
    cliPath: "kimi",
    workingDir: "C:\\workspace\\kimi-team",
    avatarName: "avatar_01.png",
  });

  render(<ClusterSetupPanel botAlias="kimi-team" client={client} />);

  expect(await screen.findByText("集群 MCP")).toBeInTheDocument();
  expect(screen.getByText(/Kimi：/)).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "生成安装命令" }));

  await waitFor(() => {
    expect(screen.getByText(/kimi mcp add --transport stdio tcb-cluster --/)).toBeInTheDocument();
  });
});
