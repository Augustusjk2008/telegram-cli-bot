import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { DebugState } from "../services/types";
import { MobileDebugScreen } from "../screens/MobileDebugScreen";

vi.mock("../services/debugSession", () => ({
  createDebugSession: vi.fn(() => ({
    connect: vi.fn(async () => undefined),
    send: vi.fn(() => true),
    dispose: vi.fn(),
  })),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

test("mobile debug screen renders controls, views, and collapsed remote params", async () => {
  const user = userEvent.setup();

  render(<MobileDebugScreen authToken="123" botAlias="main" client={new MockWebBotClient()} />);

  expect(await screen.findByTestId("mobile-debug-screen")).toBeInTheDocument();
  expect(screen.getByRole("toolbar", { name: "调试控制" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "启动调试" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "源码" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "栈" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "变量" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "日志" })).toBeInTheDocument();
  expect(screen.queryByLabelText("host")).not.toBeInTheDocument();

  await user.click(screen.getByText("远端参数"));

  expect(screen.getByLabelText("host")).toHaveValue("192.168.1.29");
  expect(screen.getByLabelText("准备命令")).toHaveValue(".\\debug.bat");
});

test("mobile debug screen opens current frame source", async () => {
  const client = new MockWebBotClient();
  const pausedState: DebugState = {
    phase: "paused",
    message: "调试已暂停",
    breakpoints: [{ source: "src/main.cpp", line: 10, verified: true }],
    frames: [{ id: "frame-0", name: "main", source: "src/main.cpp", line: 10 }],
    currentFrameId: "frame-0",
    scopes: [],
    variables: {},
  };
  vi.spyOn(client, "getDebugState").mockResolvedValue(pausedState);
  vi.spyOn(client, "readFileFull").mockResolvedValue({
    content: "int main(int argc, char *argv[]) {\n  return 0;\n}\n",
    mode: "cat",
    fileSizeBytes: 48,
    isFullContent: true,
    lastModifiedNs: "1",
  });

  render(<MobileDebugScreen authToken="123" botAlias="main" client={client} />);

  await waitFor(() => {
    expect(client.readFileFull).toHaveBeenCalledWith("main", "src/main.cpp");
  });
  expect(await screen.findByDisplayValue(/int main/)).toBeInTheDocument();
});
