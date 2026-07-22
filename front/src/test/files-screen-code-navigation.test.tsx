import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { FilesScreen } from "../screens/FilesScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";


test("mobile files editor exposes semantic navigation and applies the exact reveal position", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const resolveCodeNavigation = vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => ({
    requestId: request.requestId,
    message: "",
    items: [{
      targetType: "workspace",
      path: "server.ts",
      provider: "test-semantic",
      range: {
        start: { line: 1, column: 1 },
        end: { line: 1, column: 20 },
      },
      selectionRange: {
        start: { line: 1, column: 6 },
        end: { line: 1, column: 12 },
      },
    }],
  }));

  render(<FilesScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "进入 src" }));
  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const editor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  editor.focus();
  editor.setSelectionRange(2, 2);

  await user.click(screen.getByRole("button", { name: "编辑器操作" }));
  await user.click(screen.getByRole("menuitem", { name: "转到定义" }));

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
  ));
  await waitFor(() => {
    expect(editor.selectionStart).toBe(5);
    expect(editor.selectionEnd).toBe(5);
    expect(editor).toHaveFocus();
  });
});
