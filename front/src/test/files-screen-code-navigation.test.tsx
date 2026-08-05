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

test("mobile files editor sends semantic definition context and reveals the resolved position", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const resolveCodeNavigation = vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => ({
    requestId: request.requestId,
    message: "",
    items: [navigationItem("server.ts", 1, 6)],
  }));

  const editor = await openMobileEditor(user, client);
  await user.click(screen.getByRole("button", { name: "编辑器操作" }));
  await user.click(screen.getByRole("menuitem", { name: "转到定义" }));

  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledWith(
    "main",
    expect.objectContaining({
      kind: "definition",
      document: expect.objectContaining({ path: "server.ts", languageId: "typescript" }),
      position: { line: 1, column: 3 },
    }),
    expect.anything(),
  ));
  await waitFor(() => expect(editor.selectionStart).toBe(5));
  expect(editor).toHaveFocus();
});
