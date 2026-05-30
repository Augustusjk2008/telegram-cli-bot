import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { test, expect, vi } from "vitest";
import { AssistantOpsScreen } from "../screens/AssistantOpsScreen";
import type { CreateAssistantCronJobInput } from "../services/types";
import {
  assistantProposalIds,
  assistantProposalTitles,
  buildAssistantClient,
} from "./fixtures/assistantOps";

test("assistant ops screen approves, generates patch, dry-runs and applies proposal", async () => {
  const user = userEvent.setup();
  const client = await buildAssistantClient();
  const dispatchSpy = vi.spyOn(window, "dispatchEvent");

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  expect(await screen.findByRole("heading", { name: "Assistant 运维台" })).toBeInTheDocument();
  expect(await screen.findByText(assistantProposalTitles.syncMemoryIndex)).toBeInTheDocument();

  await user.click(screen.getByText(assistantProposalTitles.syncMemoryIndex));
  await user.click(await screen.findByRole("button", { name: "批准" }));

  expect(await screen.findByText("proposal 已批准")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Dry-run" })).toBeDisabled();
  await user.selectOptions(await screen.findByLabelText("目标工程"), "main");
  dispatchSpy.mockClear();
  await user.click(screen.getByRole("button", { name: "聊天里生成" }));
  await waitFor(() => {
    expect(dispatchSpy).toHaveBeenCalled();
  });
  await act(async () => {
    await client.generateAssistantProposalPatch("assistant1", assistantProposalIds.syncMemoryIndex, {
      targetAlias: "main",
    });
    window.dispatchEvent(new CustomEvent("assistant-proposal-patch-completed", {
      detail: {
        botAlias: "assistant1",
        proposalId: assistantProposalIds.syncMemoryIndex,
        ok: true,
        targetAlias: "main",
        summary: "patch 已生成\n目标工程: main",
      },
    }));
  });
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

test("assistant ops screen dispatches patch request to chat and shows completion summary", async () => {
  const user = userEvent.setup();
  const client = await buildAssistantClient();
  const dispatchSpy = vi.spyOn(window, "dispatchEvent");

  render(<AssistantOpsScreen botAlias="assistant1" client={client} />);

  await user.click(await screen.findByText(assistantProposalTitles.syncMemoryIndex));
  await user.click(await screen.findByRole("button", { name: "批准" }));
  await user.selectOptions(await screen.findByLabelText("目标工程"), "main");
  dispatchSpy.mockClear();
  await user.click(screen.getByRole("button", { name: "聊天里生成" }));

  const requestEvent = dispatchSpy.mock.calls
    .map(([value]) => value)
    .find((value) => value instanceof CustomEvent && value.type === "assistant-proposal-patch-requested") as CustomEvent | undefined;
  expect(requestEvent?.detail).toMatchObject({
    botAlias: "assistant1",
    proposalId: assistantProposalIds.syncMemoryIndex,
    targetAlias: "main",
  });

  await act(async () => {
    await client.generateAssistantProposalPatch("assistant1", assistantProposalIds.syncMemoryIndex, {
      targetAlias: "main",
    });
    window.dispatchEvent(new CustomEvent("assistant-proposal-patch-completed", {
      detail: {
        botAlias: "assistant1",
        proposalId: assistantProposalIds.syncMemoryIndex,
        ok: true,
        targetAlias: "main",
        summary: "patch 已生成\n目标工程: main\n变更文件: 2",
      },
    }));
  });

  expect(await screen.findByText(/patch 已生成\s*目标工程: main\s*变更文件: 2/)).toBeInTheDocument();
  expect(await screen.findByText("生成日志")).toBeInTheDocument();
  expect(await screen.findByText("upgrades/logs/pr_sync_memory_index.generate.jsonl")).toBeInTheDocument();
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


