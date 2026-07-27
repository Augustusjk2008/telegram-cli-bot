import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { FilesScreen } from "../screens/FilesScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";

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
    expect(within(editorPane).getByRole("heading", { name: "README.md" })).toBeInTheDocument();
  });
  expect(within(editorPane).getByText("Inline preview")).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "README.md" })).not.toBeInTheDocument();
});

test("opening a workspace file replaces the inline preview with the editor", async () => {
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
  await screen.findByTestId("desktop-inline-file-preview");
  await user.click(await screen.findByRole("button", { name: "展开 src" }));
  await user.click(await screen.findByRole("button", { name: "打开 src/index.ts" }));

  await waitFor(() => {
    expect(screen.queryByTestId("desktop-inline-file-preview")).not.toBeInTheDocument();
  });
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

test("opening a plugin file view takes over the inline preview area", async () => {
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
  await user.click(await screen.findByRole("button", { name: "展开 src" }));
  await user.click(await screen.findByRole("button", { name: "打开 src/index.ts" }));

  await waitFor(() => {
    expect(screen.queryByTestId("desktop-inline-file-preview")).not.toBeInTheDocument();
  });
  expect(await screen.findByTestId("desktop-plugin-view")).toBeInTheDocument();
  expect(screen.getByText("插件内容")).toBeInTheDocument();
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
