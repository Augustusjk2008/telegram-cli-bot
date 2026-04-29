import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { test, expect } from "vitest";
import { AssistantOpsScreen } from "../screens/AssistantOpsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";

async function buildAssistantClient() {
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "assistant1",
    botMode: "assistant",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\assistant1",
    avatarName: "avatar_01.png",
  });
  return client;
}

test("assistant ops screen approves and applies proposal", async () => {
  const user = userEvent.setup();
  const client = await buildAssistantClient();

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  expect(await screen.findByRole("heading", { name: "Assistant 运维台" })).toBeInTheDocument();
  expect(await screen.findByText("补 memory index 审计")).toBeInTheDocument();

  await user.click(screen.getByText("补 memory index 审计"));
  await user.click(await screen.findByRole("button", { name: "批准" }));

  expect(await screen.findByText("proposal 已批准")).toBeInTheDocument();

  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
  });
  await user.click(screen.getByRole("button", { name: "Apply" }));

  expect(await screen.findByText("upgrade 已 apply")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看日志" }));
  expect(await screen.findByText(/"status": "applied"/)).toBeInTheDocument();
});

test("assistant ops screen manages memory and diagnostics", async () => {
  const user = userEvent.setup();
  const client = await buildAssistantClient();

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  await user.click(screen.getByRole("tab", { name: "Memory / Knowledge" }));
  await user.type(await screen.findByLabelText("memory 查询"), "cron");
  await user.click(screen.getByRole("button", { name: "搜索" }));

  expect(await screen.findByText("cron 根因")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Invalidate" }));
  expect(await screen.findByText("memory 已失效")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Re-index" }));
  expect(await screen.findByText("已重建索引：working 4，knowledge 2")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "运行 Eval" }));
  expect(await screen.findByText(/eval 完成：hit@5=1\.00/)).toBeInTheDocument();
  expect(await screen.findAllByText(/hit@5 1\.00 · stale 0\.00/)).not.toHaveLength(0);

  await user.click(screen.getByRole("tab", { name: "Diagnostics" }));
  expect(await screen.findByText("run_perf_1")).toBeInTheDocument();
  expect(screen.getByText(/sync 18ms · index 11ms · recall 24ms · cli 1320ms/)).toBeInTheDocument();
});

test("assistant ops disables apply when detail says patch is not applyable", async () => {
  const client = await buildAssistantClient();
  const originalGetProposal = client.getAssistantProposal.bind(client);
  client.getAssistantProposal = async (botAlias, proposalId) => {
    const detail = await originalGetProposal(botAlias, proposalId);
    return {
      ...detail,
      proposal: {
        ...detail.proposal,
        status: "approved",
      },
      diff: {
        ...detail.diff,
        available: true,
        source: `upgrades/pending/${proposalId}.patch`,
      },
      apply: {
        ...detail.apply,
        available: false,
        applied: false,
      },
    };
  };

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  await screen.findByText("补 memory index 审计");
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
  });
});

test("assistant ops memory actions do not hardcode user id", async () => {
  const user = userEvent.setup();
  const client = await buildAssistantClient();
  const searchOptions: Array<{ userId?: number; limit?: number } | undefined> = [];
  const reindexOptions: Array<{ userId?: number; force?: boolean } | undefined> = [];
  const evalInputs: Array<{ userId?: number }> = [];

  const originalSearch = client.searchAssistantMemories.bind(client);
  client.searchAssistantMemories = async (botAlias, query, options) => {
    searchOptions.push(options);
    return originalSearch(botAlias, query, options);
  };
  const originalReindex = client.reindexAssistantMemory.bind(client);
  client.reindexAssistantMemory = async (botAlias, options) => {
    reindexOptions.push(options);
    return originalReindex(botAlias, options);
  };
  const originalEval = client.runAssistantMemoryEval.bind(client);
  client.runAssistantMemoryEval = async (botAlias, input) => {
    evalInputs.push({ userId: input.userId });
    return originalEval(botAlias, input);
  };

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  await user.click(screen.getByRole("tab", { name: "Memory / Knowledge" }));
  await user.type(await screen.findByLabelText("memory 查询"), "cron");
  await user.click(screen.getByRole("button", { name: "搜索" }));
  await waitFor(() => expect(searchOptions).toHaveLength(1));
  await user.click(await screen.findByRole("button", { name: "Re-index" }));
  await waitFor(() => expect(reindexOptions).toHaveLength(1));
  await user.click(screen.getByRole("button", { name: "运行 Eval" }));
  await waitFor(() => expect(evalInputs).toHaveLength(1));

  expect(searchOptions[0]).toEqual({ limit: 12 });
  expect(reindexOptions[0]).toEqual({ force: true });
  expect(evalInputs[0]).toEqual({ userId: undefined });
});
