import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { FilesScreen } from "../screens/FilesScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";

function navigationItem(path: string, line: number, column: number) {
  return {
    targetType: "workspace" as const,
    path,
    provider: "test-semantic",
    range: {
      start: { line, column: 1 },
      end: { line, column: 20 },
    },
    selectionRange: {
      start: { line, column },
      end: { line, column: column + 6 },
    },
  };
}

async function openMobileEditor(user: ReturnType<typeof userEvent.setup>, client: MockWebBotClient) {
  render(<FilesScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "进入 src" }));
  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const editor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  editor.focus();
  editor.setSelectionRange(2, 2);
  return editor;
}

async function requestDefinition(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "编辑器操作" }));
  await user.click(screen.getByRole("menuitem", { name: "转到定义" }));
}

test("mobile files editor exposes semantic navigation and applies the exact reveal position", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const resolveCodeNavigation = vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => ({
    requestId: request.requestId,
    message: "",
    items: [navigationItem("server.ts", 1, 6)],
  }));

  const editor = await openMobileEditor(user, client);
  await requestDefinition(user);

  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledWith(
    "main",
    expect.objectContaining({
      kind: "definition",
      document: expect.objectContaining({
        path: "server.ts",
        languageId: "typescript",
        content: expect.stringContaining("Mock full content for server.ts"),
      }),
      position: { line: 1, column: 3 },
    }),
    expect.anything(),
  ));
  await waitFor(() => {
    expect(editor.selectionStart).toBe(5);
    expect(editor.selectionEnd).toBe(5);
    expect(editor).toHaveFocus();
  });
});

test("mobile files editor shows multiple semantic destinations and an empty-result message", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  let invocation = 0;
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => {
    invocation += 1;
    return {
      requestId: request.requestId,
      message: "",
      items: invocation === 1
        ? [
          navigationItem("pkg/one.py", 3, 5),
          navigationItem("pkg/two.py", 8, 2),
        ]
        : [],
    };
  });

  await openMobileEditor(user, client);
  await requestDefinition(user);

  const dialog = await screen.findByRole("dialog", { name: "代码跳转" });
  expect(dialog).toHaveTextContent("pkg/one.py");
  expect(dialog).toHaveTextContent("pkg/two.py");
  await user.click(screen.getByRole("button", { name: "关闭代码跳转" }));

  await requestDefinition(user);

  expect(await screen.findByRole("dialog", { name: "代码跳转" })).toHaveTextContent("未找到语义定义");
});

test("mobile files editor cancels a superseded navigation request without showing an error", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const signals: AbortSignal[] = [];
  let invocation = 0;
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation((_alias, request, signal) => {
    invocation += 1;
    if (signal) {
      signals.push(signal);
    }
    if (invocation === 1) {
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("请求已取消", "AbortError"));
        }, { once: true });
      });
    }
    return Promise.resolve({
      requestId: request.requestId,
      message: "",
      items: [],
    });
  });

  await openMobileEditor(user, client);
  await requestDefinition(user);
  await requestDefinition(user);

  await waitFor(() => expect(signals[0]?.aborted).toBe(true));
  expect(await screen.findByRole("dialog", { name: "代码跳转" })).toHaveTextContent("未找到语义定义");
  expect(screen.queryByText("代码导航失败")).not.toBeInTheDocument();
});
