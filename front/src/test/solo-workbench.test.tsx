import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { SoloWorkbench } from "../workbench/SoloWorkbench";
import type { SoloSessionSnapshot } from "../workbench/soloTypes";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const snapshot: SoloSessionSnapshot = {
  botAlias: "main",
  executionMode: "native_agent",
  conversationId: "conv-1",
  conversationTitle: "当前会话",
  workingDir: "C:\\workspace\\main",
  model: "claude-sonnet-4-5",
  nativeSessionId: "native-session-1",
  workspaceHistoryHead: "head-1",
  linearIndex: 1,
  rollbackSupported: true,
  degraded: false,
  degradedReason: "",
  contextStatusText: "上下文正常",
};

function renderSoloWorkbench(
  client: MockWebBotClient,
  chatPaneContent: Parameters<typeof SoloWorkbench>[0]["chatPaneContent"],
  botAlias = "main",
) {
  return render(
    <SoloWorkbench
      botAlias={botAlias}
      client={client}
      workspaceName="main"
      viewMode="desktop"
      chatPaneContent={chatPaneContent}
      sessionSnapshot={{ ...snapshot, botAlias }}
      productMode="solo"
      soloAvailable
      onProductModeChange={() => {}}
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
      onLogout={() => {}}
    />,
  );
}

test("renders solo layout with session tab and no manual file controls", () => {
  renderSoloWorkbench(new MockWebBotClient(), <div>chat</div>);

  expect(screen.getByTestId("solo-workbench-root")).toBeInTheDocument();
  expect(screen.getByTestId("solo-chat-pane")).toBeInTheDocument();
  expect(screen.getByTestId("solo-tabs-pane")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "会话信息" })).toHaveAttribute("aria-selected", "true");
  expect(screen.queryByText("打开系统文件夹")).not.toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: /路径|文件路径|path/i })).not.toBeInTheDocument();
});

test("opens a readonly file preview tab from chat request", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const readFile = vi.spyOn(client, "readFile");

  renderSoloWorkbench(client, ({ requestPreview }) => (
    <button type="button" onClick={() => requestPreview("README.md")}>打开 README.md</button>
  ));

  await user.click(screen.getByRole("button", { name: "打开 README.md" }));

  await waitFor(() => {
    expect(readFile).toHaveBeenCalledWith("main", "README.md");
  });
  expect(await screen.findByRole("tab", { name: "README.md" })).toBeInTheDocument();
  expect(await screen.findByText(/Mock full content for README\.md/)).toBeInTheDocument();
});

test("solo chat forces native_agent send for a mixed-mode bot", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "mixed",
    botMode: "cli",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\mixed",
    avatarName: "avatar_01.png",
    supportedExecutionModes: ["cli", "native_agent"],
    defaultExecutionMode: "cli",
    nativeAgent: {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      piAgent: "reviewer",
    },
  });
  const sendMessage = vi.spyOn(client, "sendMessage");

  renderSoloWorkbench(client, (
    <ChatScreen
      botAlias="mixed"
      client={client}
      embedded
      forcedExecutionMode="native_agent"
    />
  ), "mixed");

  await user.type(await screen.findByPlaceholderText("输入消息"), "hello");
  await user.click(screen.getByLabelText("发送"));

  await waitFor(() => {
    expect(sendMessage).toHaveBeenCalled();
  });
  expect(sendMessage.mock.calls[0][5]).toMatchObject({ executionMode: "native_agent" });
});
