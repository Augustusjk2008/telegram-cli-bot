import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { FilesScreen } from "../screens/FilesScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileOpenTarget } from "../services/types";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";


function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

test("horizontal workbench renders built-in file previews inside the editor pane", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "readFile").mockResolvedValue({
    content: "# Inline preview\n",
    mode: "head",
    isFullContent: true,
  });

  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench
        botAlias="main"
        client={client}
        chatPaneContent={({ requestPreview }) => (
          <button type="button" onClick={() => requestPreview("README.md")}>预览 README</button>
        )}
      />
    </PersistentTerminalProvider>,
  );

  await user.click(await screen.findByRole("button", { name: "预览 README" }));

  const editorPane = await screen.findByTestId("desktop-pane-editor");
  await waitFor(() => {
    expect(within(editorPane).getByRole("tab", { name: "README.md 预览" })).toBeInTheDocument();
  });
  expect(within(editorPane).getByText("Inline preview")).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "README.md" })).not.toBeInTheDocument();
});

test("file previews and editable files coexist as switchable editor tabs", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "readFile").mockResolvedValue({
    content: "# Inline preview\n",
    mode: "head",
    isFullContent: true,
  });

  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench
        botAlias="main"
        client={client}
        chatPaneContent={({ requestPreview }) => (
          <button type="button" onClick={() => requestPreview("README.md")}>预览 README</button>
        )}
      />
    </PersistentTerminalProvider>,
  );

  await user.click(await screen.findByRole("button", { name: "展开 src" }));
  await user.click(await screen.findByRole("button", { name: "打开 src/index.ts" }));
  expect(await screen.findByRole("textbox", { name: "文件内容" })).toBeInTheDocument();

  await user.click(await screen.findByRole("button", { name: "预览 README" }));
  await screen.findByTestId("desktop-inline-file-preview");

  const editorPane = screen.getByTestId("desktop-pane-editor");
  const sourceTab = within(editorPane).getByRole("tab", { name: "index.ts" });
  const previewTab = within(editorPane).getByRole("tab", { name: "README.md 预览" });

  await user.click(sourceTab);
  expect(await screen.findByRole("textbox", { name: "文件内容" })).toBeInTheDocument();
  expect(screen.queryByTestId("desktop-inline-file-preview")).not.toBeInTheDocument();

  await user.click(previewTab);
  expect(await screen.findByTestId("desktop-inline-file-preview")).toBeInTheDocument();
  expect(screen.getByText("Inline preview")).toBeInTheDocument();

  await user.click(within(editorPane).getByRole("button", { name: "关闭 README.md 预览" }));
  expect(within(editorPane).queryByRole("tab", { name: "README.md 预览" })).not.toBeInTheDocument();
  expect(within(editorPane).getByRole("tab", { name: "index.ts" })).toBeInTheDocument();
  expect(await screen.findByRole("textbox", { name: "文件内容" })).toBeInTheDocument();
});

test("horizontal workbench renders raster previews in the editor pane", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "readFile").mockResolvedValue({
    content: "",
    mode: "head",
    previewKind: "image",
    contentType: "image/png",
    contentBase64: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  });

  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench
        botAlias="main"
        client={client}
        chatPaneContent={({ requestPreview }) => (
          <button type="button" onClick={() => requestPreview("diagram.png")}>预览图片</button>
        )}
      />
    </PersistentTerminalProvider>,
  );

  await user.click(await screen.findByRole("button", { name: "预览图片" }));
  const editorPane = await screen.findByTestId("desktop-pane-editor");
  expect(await within(editorPane).findByRole("img", { name: "diagram.png" })).toHaveAttribute(
    "src",
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  );
  expect(screen.queryByRole("dialog", { name: "diagram.png" })).not.toBeInTheDocument();
});

test("horizontal HTML previews omit edit and download actions", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const html = "<!doctype html><title>Preview</title><main>Editable</main>";
  vi.spyOn(client, "readFile").mockResolvedValue({
    content: html,
    mode: "head",
    isFullContent: true,
  });
  vi.spyOn(client, "readFileFull").mockResolvedValue({
    content: html,
    mode: "cat",
    isFullContent: true,
  });

  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench
        botAlias="main"
        client={client}
        chatPaneContent={({ requestPreview }) => (
          <button type="button" onClick={() => requestPreview("index.html")}>预览 HTML</button>
        )}
      />
    </PersistentTerminalProvider>,
  );

  await user.click(await screen.findByRole("button", { name: "预览 HTML" }));
  const editorPane = await screen.findByTestId("desktop-pane-editor");
  expect(await within(editorPane).findByRole("tab", { name: "index.html 预览" })).toBeInTheDocument();
  expect(within(editorPane).queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
  expect(within(editorPane).queryByRole("button", { name: "下载" })).not.toBeInTheDocument();
  expect(within(editorPane).queryByRole("tab", { name: "index.html" })).not.toBeInTheDocument();
});

test("plugin file views and file previews remain switchable editor tabs", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "readFile").mockResolvedValue({
    content: "# Inline preview\n",
    mode: "head",
    isFullContent: true,
  });
  vi.spyOn(client, "resolveFileOpenTarget").mockImplementation(async (_botAlias, path) => {
    if (path === "src/index.ts") {
      return {
        kind: "plugin_view",
        pluginId: "demo-plugin",
        viewId: "report",
        title: "插件报告",
        input: { path },
      };
    }
    return { kind: "file" };
  });
  vi.spyOn(client, "openPluginView").mockResolvedValue({
    pluginId: "demo-plugin",
    viewId: "report",
    title: "插件报告",
    renderer: "document",
    mode: "snapshot",
    payload: {
      path: "src/index.ts",
      blocks: [{ type: "heading", level: 1, runs: [{ text: "插件内容" }] }],
    },
  });

  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench
        botAlias="main"
        client={client}
        chatPaneContent={({ requestPreview }) => (
          <button type="button" onClick={() => requestPreview("README.md")}>预览 README</button>
        )}
      />
    </PersistentTerminalProvider>,
  );

  await user.click(await screen.findByRole("button", { name: "预览 README" }));
  await screen.findByTestId("desktop-inline-file-preview");
  const expandSrc = screen.queryByRole("button", { name: "展开 src" });
  if (expandSrc) {
    await user.click(expandSrc);
  }
  await user.click(await screen.findByRole("button", { name: "打开 src/index.ts" }));

  await waitFor(() => {
    expect(screen.queryByTestId("desktop-inline-file-preview")).not.toBeInTheDocument();
  });
  expect(await screen.findByTestId("desktop-plugin-view")).toBeInTheDocument();
  expect(screen.getByText("插件内容")).toBeInTheDocument();

  const editorPane = screen.getByTestId("desktop-pane-editor");
  const previewTab = within(editorPane).getByRole("tab", { name: "README.md 预览" });
  const pluginTab = within(editorPane).getByRole("tab", { name: "插件报告" });
  await user.click(previewTab);
  expect(await screen.findByTestId("desktop-inline-file-preview")).toBeInTheDocument();
  expect(screen.getByText("Inline preview")).toBeInTheDocument();

  await user.click(pluginTab);
  expect(await screen.findByTestId("desktop-plugin-view")).toBeInTheDocument();
});

test("a delayed file target from an old bot cannot open in the new bot workspace", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const targetRead = deferred<FileOpenTarget>();
  vi.spyOn(client, "resolveFileOpenTarget").mockReturnValue(targetRead.promise);
  const readFileFull = vi.spyOn(client, "readFileFull");
  const workbench = (botAlias: string) => (
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias={botAlias} client={client} />
    </PersistentTerminalProvider>
  );
  const { rerender } = render(workbench("main"));

  await user.click(await screen.findByRole("button", { name: "展开 src" }));
  await user.click(await screen.findByRole("button", { name: "打开 src/index.ts" }));
  await waitFor(() => expect(client.resolveFileOpenTarget).toHaveBeenCalledWith("main", "src/index.ts"));

  rerender(workbench("team"));
  await screen.findByTestId("editor-empty-state");
  await act(async () => {
    targetRead.resolve({ kind: "file" });
    await targetRead.promise;
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });

  expect(screen.getByTestId("editor-empty-state")).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "index.ts" })).not.toBeInTheDocument();
  expect(readFileFull).not.toHaveBeenCalled();
});

test("vertical file screen keeps file previews in a dialog", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "readFile").mockResolvedValue({
    content: "# Mobile preview\n",
    mode: "head",
    isFullContent: true,
  });

  render(<FilesScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));
  expect(await screen.findByRole("dialog", { name: "README.md" })).toBeInTheDocument();
  expect(screen.queryByTestId("desktop-inline-file-preview")).not.toBeInTheDocument();
});
