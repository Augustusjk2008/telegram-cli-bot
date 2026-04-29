import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { test, expect, vi } from "vitest";
import { AssistantOpsScreen } from "../screens/AssistantOpsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { CreateAssistantCronJobInput } from "../services/types";

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

test("assistant ops screen approves, generates patch, dry-runs and applies proposal", async () => {
  const user = userEvent.setup();
  const client = await buildAssistantClient();

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  expect(await screen.findByRole("heading", { name: "Assistant 运维台" })).toBeInTheDocument();
  expect(await screen.findByText("补 memory index 审计")).toBeInTheDocument();

  await user.click(screen.getByText("补 memory index 审计"));
  await user.click(await screen.findByRole("button", { name: "批准" }));

  expect(await screen.findByText("proposal 已批准")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Dry-run" })).toBeDisabled();
  await user.selectOptions(await screen.findByLabelText("目标工程"), "main");
  await user.click(screen.getByRole("button", { name: "生成 Patch" }));
  expect(await screen.findByText("patch 已生成")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "批准 Patch" }));
  expect(await screen.findByText("patch 已批准")).toBeInTheDocument();

  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Dry-run" })).toBeEnabled();
  });
  await user.click(screen.getByRole("button", { name: "Dry-run" }));
  expect(await screen.findByText("dry-run 通过")).toBeInTheDocument();

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

  expect((await screen.findAllByText("cron 根因")).length).toBeGreaterThan(0);
  await user.click(screen.getByRole("button", { name: "Invalidate" }));
  expect(await screen.findByText("memory 已失效")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Re-index" }));
  expect(await screen.findByText("已重建索引：working 4，knowledge 2")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "运行 Eval" }));
  expect(await screen.findByText(/eval 完成：hit@5=1\.00/)).toBeInTheDocument();
  expect(await screen.findAllByText(/hit@5 1\.00 · stale 0\.00/)).not.toHaveLength(0);

  await user.click(screen.getByRole("tab", { name: "Diagnostics" }));
  expect((await screen.findAllByText("run_perf_1")).length).toBeGreaterThan(0);
  expect(screen.getByText("慢阶段排行")).toBeInTheDocument();
  expect(screen.getByText("错误聚合")).toBeInTheDocument();
  expect(screen.getByText(/sync 18ms · index 11ms · recall 24ms · cli 1320ms/)).toBeInTheDocument();
});

test("assistant ops supports bulk invalidate and audit", async () => {
  const user = userEvent.setup();
  const client = await buildAssistantClient();

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  await user.click(screen.getByRole("tab", { name: "Memory / Knowledge" }));
  await user.type(await screen.findByLabelText("memory 查询"), "默认");
  await user.click(screen.getByRole("button", { name: "搜索" }));
  await user.click(await screen.findByLabelText("选择 memory 回复偏好"));
  await user.click(screen.getByRole("button", { name: "批量 Invalidate" }));

  expect(await screen.findByText("已失效 1 条")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Audit" }));
  expect(await screen.findByText("assistant.memory.bulk_invalidate")).toBeInTheDocument();
  expect((await screen.findAllByText("ok")).length).toBeGreaterThan(0);
  await user.click(screen.getByRole("button", { name: "查看审计详情" }));
  expect(await screen.findByText(/"resourceId": "bulk"/)).toBeInTheDocument();
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
      upgrade: {
        ...detail.upgrade,
        state: "pending",
        canDryRun: false,
        canApply: false,
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

test("assistant ops owns automation queue cron and runs", async () => {
  const user = userEvent.setup();
  const client = await buildAssistantClient();

  await client.createAssistantCronJob("assistant1", {
    id: "daily_repo_review",
    enabled: true,
    title: "Daily Repo Review",
    schedule: {
      type: "daily",
      time: "09:00",
      timezone: "Asia/Shanghai",
      misfirePolicy: "once",
    },
    task: {
      prompt: "检查当前仓库状态并输出日报",
      mode: "standard",
      deliverMode: "chat_handoff",
    },
    execution: { timeoutSeconds: 600 },
  } satisfies CreateAssistantCronJobInput);

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  await user.click(await screen.findByRole("tab", { name: "Queue" }));
  expect(await screen.findByText("当前队列")).toBeInTheDocument();
  expect(await screen.findByText("暂无排队任务")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Cron" }));
  expect(await screen.findByRole("heading", { name: "Automation 定时任务" })).toBeInTheDocument();
  expect(await screen.findByText("Daily Repo Review")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "立即运行 Daily Repo Review" }));
  expect(await screen.findByText(/任务已投递到聊天会话: run_/)).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Queue" }));
  expect((await screen.findAllByText(/run_/)).length).toBeGreaterThan(0);

  await user.click(screen.getByRole("tab", { name: "Runs" }));
  expect(await screen.findByText("daily_repo_review")).toBeInTheDocument();
});

test("assistant ops automation dispatches a chat handoff event", async () => {
  const user = userEvent.setup();
  const client = await buildAssistantClient();
  const dispatchSpy = vi.spyOn(window, "dispatchEvent");

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

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  await user.click(await screen.findByRole("tab", { name: "Cron" }));
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

test("assistant ops cron shows dream fields when mode switches to dream", async () => {
  const user = userEvent.setup();
  const client = await buildAssistantClient();

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  await user.click(await screen.findByRole("tab", { name: "Cron" }));
  await user.selectOptions(await screen.findByLabelText("任务模式"), "dream");

  expect(screen.getByLabelText("回看小时数")).toBeInTheDocument();
  expect(screen.getByLabelText("聊天历史条数")).toBeInTheDocument();
  expect(screen.getByLabelText("Capture 条数")).toBeInTheDocument();
  expect(screen.getByLabelText("投递方式")).toHaveValue("silent");
});
