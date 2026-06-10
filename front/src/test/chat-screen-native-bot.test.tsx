import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { EventType } from "../services/agUiProtocol";
import { MockWebBotClient } from "../services/mockWebBotClient";

afterEach(() => {
  localStorage.clear();
});

test("pure native bot hides execution switch and sends native mode by default", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "native1",
    botMode: "cli",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\native1",
    avatarName: "avatar_01.png",
    supportedExecutionModes: ["native_agent"],
    defaultExecutionMode: "native_agent",
    nativeAgent: {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      piAgent: "reviewer",
    },
  });
  const sendMessage = vi.spyOn(client, "sendMessage");

  render(<ChatScreen botAlias="native1" client={client} />);

  const composer = await screen.findByPlaceholderText("输入消息");
  expect(screen.queryByRole("button", { name: "CLI" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "原生 agent" })).not.toBeInTheDocument();

  await user.type(composer, "hello");
  await user.click(screen.getByLabelText("发送"));

  await waitFor(() => {
    expect(sendMessage).toHaveBeenCalled();
  });
  expect(sendMessage.mock.calls[0][5]).toMatchObject({ executionMode: "native_agent" });
});

test("native bot shows ag-ui process tool permission and submits input value", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "native2",
    botMode: "cli",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\native2",
    supportedExecutionModes: ["native_agent"],
    defaultExecutionMode: "native_agent",
    nativeAgent: {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      piAgent: "reviewer",
    },
  });
  vi.spyOn(client, "sendMessage").mockImplementation(async (
    _botAlias,
    _text,
    onChunk,
    _onStatus,
    _onTrace,
    _options,
    onAgUiEvent,
  ) => {
    onAgUiEvent?.({ type: EventType.RUN_STARTED, threadId: "thread-1", runId: "run-1" });
    onAgUiEvent?.({
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "status-1",
      activityType: "TCB_STATUS",
      replace: true,
      content: { id: "status-1", summary: "准备执行", source: "native_agent", rawKind: "status", uiKind: "notify" },
    });
    onAgUiEvent?.({ type: EventType.TOOL_CALL_START, toolCallId: "call-1", toolCallName: "shell_command" });
    onAgUiEvent?.({ type: EventType.TOOL_CALL_ARGS, toolCallId: "call-1", delta: "{\"command\":\"dir\"}" });
    onAgUiEvent?.({ type: EventType.TOOL_CALL_RESULT, messageId: "tool-result-1", toolCallId: "call-1", content: "Exit code: 0" });
    onAgUiEvent?.({
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "perm-1",
      activityType: "TCB_PERMISSION_REQUEST",
      replace: true,
      content: {
        id: "perm-1",
        permissionId: "perm-1",
        summary: "输入名称",
        state: "permission.updated",
        source: "native_agent",
        uiKind: "input",
        placeholder: "名称",
      },
    });
    onChunk("**完成**");
    return {
      id: "assistant-native2",
      role: "assistant",
      text: "**完成**",
      createdAt: new Date().toISOString(),
      state: "done",
      meta: { tracePresentation: "native_agent_flat" },
    };
  });
  const replyNativeAgentPermission = vi.spyOn(client, "replyNativeAgentPermission");

  render(<ChatScreen botAlias="native2" client={client} />);
  await user.type(await screen.findByPlaceholderText("输入消息"), "hello");
  await user.click(screen.getByLabelText("发送"));
  await screen.findByText("准备执行");
  expect(await screen.findByText("shell_command")).toBeInTheDocument();
  expect(await screen.findAllByText("Exit code: 0")).not.toHaveLength(0);
  await user.type(await screen.findByLabelText("权限输入"), "orbit");
  await user.click(screen.getByRole("button", { name: "提交" }));

  await waitFor(() => expect(replyNativeAgentPermission).toHaveBeenCalledWith(
    "native2",
    "perm-1",
    expect.objectContaining({ approved: true, value: "orbit" }),
  ));
  expect(screen.getByTestId("native-agent-final-result")).toHaveTextContent("完成");
});
