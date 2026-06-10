import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { NativeAgentTranscript } from "../components/NativeAgentTranscript";
import type { NativeAgentTranscriptEntry } from "../utils/agUiRunReducer";

function entry(partial: Partial<NativeAgentTranscriptEntry> & Pick<NativeAgentTranscriptEntry, "id" | "seq" | "kind" | "label" | "summary">): NativeAgentTranscriptEntry {
  const { collapsedByDefault = false, ...rest } = partial;
  return {
    ...rest,
    collapsedByDefault,
  };
}

test("native transcript groups sequential tool, result, and event entries", async () => {
  const user = userEvent.setup();
  render(
    <NativeAgentTranscript
      entries={[
        entry({
          id: "tool-1",
          seq: 1,
          kind: "tool",
          label: "shell_command",
          summary: "shell_command",
          trace: { kind: "tool_call", summary: "shell_command", callId: "call-1" },
        }),
        entry({
          id: "result-1",
          seq: 2,
          kind: "event",
          label: "工具结果",
          summary: "Exit code: 0",
          trace: { kind: "tool_result", summary: "Exit code: 0", callId: "call-1" },
        }),
        entry({ id: "event-1", seq: 3, kind: "event", label: "事件", summary: "thread.updated" }),
        entry({
          id: "process-1",
          seq: 4,
          kind: "process",
          label: "过程",
          summary: "收尾",
          trace: { kind: "commentary", summary: "收尾" },
        }),
      ]}
      resultText=""
    />,
  );

  const group = screen.getByTestId("native-agent-event-group") as HTMLDetailsElement;
  expect(group.tagName).toBe("DETAILS");
  expect(group).not.toHaveAttribute("open");
  expect(group.textContent).toContain("过程 1");
  expect(group.textContent).toContain("3 条事件 · 1 次工具");
  const summary = within(group).getByText("过程 1").closest("summary");
  expect(summary).toHaveTextContent("过程 1");
  expect(summary).toHaveTextContent("3 条事件 · 1 次工具");
  await user.click(within(group).getByText("过程 1"));
  expect(group).toHaveAttribute("open");
  expect(group.textContent).toContain("shell_command");
  expect(group.textContent).toContain("Exit code: 0");
  expect(group.textContent).toContain("thread.updated");
  expect(group.textContent).not.toContain("收尾");
  expect(screen.getByText("收尾")).toBeInTheDocument();
});

test("native transcript keeps commentary outside event groups and splits surrounding events", () => {
  render(
    <NativeAgentTranscript
      entries={[
        entry({
          id: "tool-1",
          seq: 1,
          kind: "tool",
          label: "shell_command",
          summary: "first tool",
          trace: { kind: "tool_call", summary: "first tool", callId: "call-1" },
        }),
        entry({
          id: "result-1",
          seq: 2,
          kind: "event",
          label: "工具结果",
          summary: "first result",
          trace: { kind: "tool_result", summary: "first result", callId: "call-1" },
        }),
        entry({
          id: "process-1",
          seq: 3,
          kind: "process",
          label: "过程",
          summary: "中间说明",
          trace: { kind: "commentary", summary: "中间说明" },
        }),
        entry({
          id: "tool-2",
          seq: 4,
          kind: "tool",
          label: "read",
          summary: "second tool",
          trace: { kind: "tool_call", summary: "second tool", callId: "call-2" },
        }),
        entry({
          id: "result-2",
          seq: 5,
          kind: "event",
          label: "工具结果",
          summary: "second result",
          trace: { kind: "tool_result", summary: "second result", callId: "call-2" },
        }),
      ]}
      resultText=""
    />,
  );

  const transcript = screen.getByTestId("native-agent-transcript");
  const groups = screen.getAllByTestId("native-agent-event-group");

  expect(groups).toHaveLength(2);
  expect(groups[0].textContent).toContain("first tool");
  expect(groups[0].textContent).toContain("first result");
  expect(groups[0].textContent).not.toContain("中间说明");
  expect(groups[0].textContent).not.toContain("second tool");
  expect(screen.getByText("中间说明")).toBeInTheDocument();
  expect(groups[1].textContent).toContain("second tool");
  expect(groups[1].textContent).toContain("second result");

  expect(Array.from(transcript.children).map((child) => child.textContent || "")).toEqual([
    expect.stringContaining("first tool"),
    expect.stringContaining("中间说明"),
    expect.stringContaining("second tool"),
  ]);
});

test("native transcript keeps permission entries outside adjacent tool groups", () => {
  render(
    <NativeAgentTranscript
      entries={[
        entry({
          id: "permission-1",
          seq: 1,
          kind: "permission",
          label: "权限",
          summary: "权限请求",
          permissionId: "perm-1",
          pending: true,
        }),
        entry({
          id: "tool-1",
          seq: 2,
          kind: "tool",
          label: "shell_command",
          summary: "shell_command",
          trace: { kind: "tool_call", summary: "shell_command", callId: "call-1" },
        }),
        entry({
          id: "result-1",
          seq: 3,
          kind: "event",
          label: "工具结果",
          summary: "Exit code: 0",
          trace: { kind: "tool_result", summary: "Exit code: 0", callId: "call-1" },
        }),
      ]}
      resultText=""
    />,
  );

  expect(screen.getByTestId("native-agent-permission")).toHaveTextContent("权限请求");
  const group = screen.getByTestId("native-agent-event-group");
  expect(group.textContent).toContain("2 条事件 · 1 次工具");
  expect(group.textContent).toContain("shell_command");
  expect(group.textContent).toContain("Exit code: 0");
  expect(within(group).queryByText("权限请求")).not.toBeInTheDocument();
});

test("native transcript shows streaming status as the last row until done", () => {
  const { rerender } = render(
    <NativeAgentTranscript
      entries={[entry({ id: "process-1", seq: 1, kind: "process", label: "过程", summary: "运行中" })]}
      resultText="partial answer"
      state="streaming"
    />,
  );

  const transcript = screen.getByTestId("native-agent-transcript");
  const status = screen.getByTestId("native-agent-streaming-status");
  expect(status).toHaveTextContent("正在输出...");
  expect(transcript.lastElementChild).toBe(status);

  rerender(
    <NativeAgentTranscript
      entries={[entry({ id: "process-1", seq: 1, kind: "process", label: "过程", summary: "运行中" })]}
      resultText="partial answer"
      state="done"
    />,
  );

  expect(screen.queryByTestId("native-agent-streaming-status")).not.toBeInTheDocument();
});

test.each([
  ["select", "权限选项", "beta"],
  ["input", "权限输入", "typed value"],
  ["editor", "权限输入", "typed value"],
])("native transcript renders %s permission control", async (uiKind, label, submittedValue) => {
  const user = userEvent.setup();
  const onReplyPermission = vi.fn(async () => undefined);
  render(
    <NativeAgentTranscript
      entries={[
        entry({
          id: `permission-${uiKind}`,
          seq: 1,
          kind: "permission",
          label: "权限",
          summary: "需要输入",
          permissionId: `perm-${uiKind}`,
          pending: true,
          permission: {
            permissionId: `perm-${uiKind}`,
            summary: "需要输入",
            state: "permission.updated",
            source: "native_agent",
            content: {},
            uiKind,
            options: ["alpha", "beta"],
            defaultValue: "alpha",
            placeholder: "请输入",
          },
        }),
      ]}
      resultText=""
      onReplyPermission={onReplyPermission}
    />,
  );

  const control = screen.getByLabelText(label);
  if (uiKind === "select") {
    await user.selectOptions(control, submittedValue);
  } else {
    await user.clear(control);
    await user.type(control, submittedValue);
  }
  await user.click(screen.getByRole("button", { name: "提交" }));

  expect(onReplyPermission).toHaveBeenCalledWith({
    requestId: `perm-${uiKind}`,
    accepted: true,
    value: submittedValue,
  });
});

test("native transcript disables handled permission controls", () => {
  render(
    <NativeAgentTranscript
      entries={[
        entry({
          id: "permission-done",
          seq: 1,
          kind: "permission",
          label: "权限",
          summary: "已处理",
          permissionId: "perm-done",
          pending: false,
          permission: {
            permissionId: "perm-done",
            summary: "已处理",
            state: "permission.replied",
            source: "native_agent",
            content: {},
            uiKind: "input",
          },
        }),
      ]}
      resultText="**完成**"
      state="done"
      onReplyPermission={async () => undefined}
    />,
  );

  expect(screen.queryByRole("button", { name: "提交" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("权限输入")).not.toBeInTheDocument();
  expect(screen.getByTestId("native-agent-final-result")).toHaveTextContent("完成");
});
