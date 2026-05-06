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

  await user.click(screen.getByRole("button", { name: "生成安装命令" }));

  await waitFor(() => {
    expect(screen.getByText(/codex mcp add tcb-cluster/)).toBeInTheDocument();
  });
});
