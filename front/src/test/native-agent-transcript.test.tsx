import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { NativeAgentTranscript } from "../components/NativeAgentTranscript";
import type { NativeAgentTranscriptEntry } from "../utils/agUiRunReducer";

function entry(partial: Partial<NativeAgentTranscriptEntry> & Pick<NativeAgentTranscriptEntry, "id" | "seq" | "kind" | "label" | "summary">): NativeAgentTranscriptEntry {
  const { collapsedByDefault = false, ...rest } = partial;
  return {
    ...rest,
    collapsedByDefault,
  };
}

test("native transcript groups sequential process, tool, result, and event entries", async () => {
  const user = userEvent.setup();
  render(
    <NativeAgentTranscript
      entries={[
        entry({ id: "process-1", seq: 1, kind: "process", label: "过程", summary: "准备执行" }),
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
        entry({ id: "event-1", seq: 4, kind: "event", label: "事件", summary: "thread.updated" }),
        entry({ id: "process-2", seq: 5, kind: "process", label: "过程", summary: "收尾" }),
      ]}
      resultText=""
    />,
  );

  const group = screen.getByTestId("native-agent-event-group") as HTMLDetailsElement;
  expect(group.tagName).toBe("DETAILS");
  expect(group).not.toHaveAttribute("open");
  expect(group.textContent).toContain("阶段 1");
  expect(group.textContent).toContain("4 条事件 · 1 次工具");
  await user.click(within(group).getByText("阶段 1"));
  expect(group).toHaveAttribute("open");
  expect(group.textContent).toContain("准备执行");
  expect(group.textContent).toContain("shell_command");
  expect(group.textContent).toContain("Exit code: 0");
  expect(group.textContent).toContain("thread.updated");
  expect(group.textContent).not.toContain("收尾");
  expect(screen.getByText("收尾")).toBeInTheDocument();
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
