import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ScheduledTasksPanel } from "../components/admin/ScheduledTasksPanel";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { ScheduledTask, ScheduledTaskInput, ScheduledTaskListResult } from "../services/types";

function scheduleList(overrides: Partial<ScheduledTaskListResult> = {}): ScheduledTaskListResult {
  const task: ScheduledTask = {
    id: "sch_1",
    name: "每日晨报",
    enabled: true,
    revision: 2,
    botAlias: "main",
    agentId: "main",
    prompt: "汇总昨天的合并记录",
    trigger: { type: "daily", time: "09:00", weekdays: [1, 2, 3, 4, 5] },
    timezone: "Asia/Shanghai",
    busyPolicy: "wait",
    maxWaitMinutes: 15,
    misfireGraceMinutes: 30,
    allowUnsafeCli: false,
    nextRunAt: "2026-11-17T01:00:00Z",
    disabledReason: "",
    createdBy: { accountId: "admin", username: "admin" },
    createdAt: "2026-11-10T00:00:00Z",
    updatedAt: "2026-11-10T00:00:00Z",
    activeRunId: "",
    lastRun: {
      id: "run_1",
      scheduleId: "sch_1",
      plannedAt: "2026-11-16T01:00:00Z",
      trigger: "schedule",
      status: "failed",
      reasonCode: "cli_error",
      reasonMessage: "CLI 退出",
      botAlias: "main",
      conversationId: "conv_1",
      turnId: "",
      assistantMessageId: "",
      preview: "",
      unsafeDowngraded: false,
      createdAt: "2026-11-16T01:00:00Z",
      startedAt: "2026-11-16T01:00:01Z",
      finishedAt: "2026-11-16T01:00:05Z",
    },
  };
  return {
    items: [task],
    defaultTimezone: "Asia/Shanghai",
    canAllowUnsafeCli: false,
    targets: [{ alias: "main", cliType: "codex" }, { alias: "team2", cliType: "claude" }],
    limits: { minIntervalMinutes: 5, maxPromptChars: 20000, maxWaitMinutes: 120, maxMisfireGraceMinutes: 1440 },
    ...overrides,
  };
}

function createClient(list = scheduleList()) {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
    listScheduledTasks: vi.fn(async () => list),
    createScheduledTask: vi.fn(async (input: ScheduledTaskInput) => ({ ...list.items[0], ...input, id: "sch_new" })),
  });
}

test("管理中心的定时任务页列出客户端返回的计划", async () => {
  const user = userEvent.setup();
  const client = createClient();
  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "定时任务" }));

  const item = await screen.findByRole("listitem", { name: "每日晨报" });
  expect(item).toHaveTextContent("每周一至周五 09:00");
  expect(item).toHaveTextContent("Asia/Shanghai");
  expect(within(item).getByText("失败")).toBeInTheDocument();
  expect(within(item).getByRole("checkbox", { name: "启用 每日晨报" })).toBeChecked();
});

test("新建每周计划发送完整载荷，且无高风险权限时不显示高风险开关", async () => {
  const user = userEvent.setup();
  const client = createClient();
  render(<ScheduledTasksPanel client={client} />);

  await user.click(await screen.findByRole("button", { name: "新建定时任务" }));
  const editor = screen.getByRole("group", { name: "新建定时任务" });
  expect(within(editor).queryByText("允许高风险 CLI 参数")).not.toBeInTheDocument();
  expect(editor).toHaveTextContent("新建会话");

  await user.type(within(editor).getByRole("textbox", { name: "任务名称" }), "周报");
  await user.selectOptions(within(editor).getByRole("combobox", { name: "目标 Bot" }), "team2");
  await user.type(within(editor).getByRole("textbox", { name: "指令内容" }), "整理本周进展");
  fireEvent.change(within(editor).getByLabelText("触发时间"), { target: { value: "08:30" } });
  await user.click(within(editor).getByRole("button", { name: "工作日" }));
  await user.click(within(editor).getByRole("button", { name: "周三" }));
  await user.click(within(editor).getByRole("button", { name: "创建定时任务" }));

  expect(client.createScheduledTask).toHaveBeenCalledWith({
    name: "周报",
    botAlias: "team2",
    prompt: "整理本周进展",
    trigger: { type: "daily", time: "08:30", weekdays: [1, 2, 4, 5] },
    timezone: "Asia/Shanghai",
    busyPolicy: "wait",
    maxWaitMinutes: 15,
    misfireGraceMinutes: 30,
    allowUnsafeCli: false,
    enabled: true,
  });
  expect(screen.queryByRole("group", { name: "新建定时任务" })).not.toBeInTheDocument();
});
