import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { EditorPane } from "../workbench/EditorPane";
import type { EditorTab } from "../workbench/workbenchTypes";

function createTab(overrides: Partial<EditorTab> = {}): EditorTab {
  return {
    path: "src/No8Demo/demo_basic.h",
    basename: "demo_basic.h",
    content: "#pragma once\n",
    documentVersion: 1,
    savedContent: "#pragma once\n",
    kind: "file",
    dirty: false,
    loading: false,
    saving: false,
    statusText: "",
    error: "",
    cold: false,
    missing: false,
    contentPersistence: "clean_snapshot",
    ...overrides,
  };
}

function renderEditor(
  activeTab: EditorTab,
  tabs: EditorTab[] = [activeTab],
  overrides: Partial<ComponentProps<typeof EditorPane>> = {},
) {
  const callbacks = {
    onActivateTab: vi.fn(),
    onCloseTab: vi.fn(() => true),
    onChangeActiveContent: vi.fn(),
    onSaveActiveTab: vi.fn(),
    onCloseOthers: vi.fn(),
    onCloseTabsToRight: vi.fn(),
    onReopenLastClosed: vi.fn(),
    onRevealInTree: vi.fn(),
    onToggleFocus: vi.fn(),
  };
  const view = render(
    <EditorPane
      botAlias="main"
      client={new MockWebBotClient()}
      tabs={tabs}
      activeTab={activeTab}
      activeTabPath={activeTab.path}
      focused={false}
      {...callbacks}
      {...overrides}
    />,
  );
  return { ...view, callbacks };
}

function breadcrumbParts() {
  const breadcrumb = screen.getByRole("navigation", { name: "文件路径" });
  return within(breadcrumb).getAllByRole("listitem").map((item) => item.textContent);
}

test("editor pane renders a file breadcrumb and preserves tab callbacks", async () => {
  const user = userEvent.setup();
  const activeTab = createTab();
  const secondTab = createTab({
    path: "src/server.ts",
    basename: "server.ts",
    content: "export {};\n",
    savedContent: "export {};\n",
  });
  const { callbacks } = renderEditor(activeTab, [activeTab, secondTab]);

  expect(breadcrumbParts()).toEqual(["src", "No8Demo", "demo_basic.h"]);
  expect(within(screen.getByRole("navigation", { name: "文件路径" })).getByText("demo_basic.h"))
    .toHaveAttribute("aria-current", "page");

  await user.click(screen.getByRole("tab", { name: "server.ts" }));
  expect(callbacks.onActivateTab).toHaveBeenCalledWith("src/server.ts");

  await user.click(screen.getByRole("button", { name: "关闭 src/No8Demo/demo_basic.h" }));
  expect(callbacks.onCloseTab).toHaveBeenCalledWith("src/No8Demo/demo_basic.h");

  fireEvent.contextMenu(screen.getByRole("tab", { name: "server.ts" }));
  await user.click(screen.getByRole("button", { name: "关闭其他标签页" }));
  expect(callbacks.onCloseOthers).toHaveBeenCalledWith("src/server.ts");
});

test("editor pane derives git and plugin breadcrumbs without exposing internal tab identities", () => {
  const gitTab = createTab({
    path: "git-diff:src/No8Demo/demo_basic.h",
    basename: "demo_basic.h (Diff)",
    kind: "git-diff",
    sourcePath: "src/No8Demo/demo_basic.h",
    content: "@@ -1 +1 @@\n-old\n+new\n",
  });
  const pluginSourceTab = createTab({
    path: "plugin://vivado/waveform/source",
    basename: "波形查看器",
    kind: "plugin-view",
    sourcePath: "waves/demo.vcd",
    content: "",
    savedContent: "",
  });
  const pluginTab = createTab({
    path: "plugin://reports/summary/session-1",
    basename: "资源报告",
    kind: "plugin-view",
    sourcePath: undefined,
    content: "",
    savedContent: "",
  });
  const callbacks = {
    onActivateTab: vi.fn(),
    onCloseTab: vi.fn(() => true),
    onChangeActiveContent: vi.fn(),
    onSaveActiveTab: vi.fn(),
    onCloseOthers: vi.fn(),
    onCloseTabsToRight: vi.fn(),
    onReopenLastClosed: vi.fn(),
    onRevealInTree: vi.fn(),
    onToggleFocus: vi.fn(),
  };
  const client = new MockWebBotClient();
  const tabs = [gitTab, pluginSourceTab, pluginTab];
  const { rerender } = render(
    <EditorPane
      botAlias="main"
      client={client}
      tabs={tabs}
      activeTab={gitTab}
      activeTabPath={gitTab.path}
      focused={false}
      {...callbacks}
    />,
  );

  expect(breadcrumbParts()).toEqual(["src", "No8Demo", "demo_basic.h"]);

  rerender(
    <EditorPane
      botAlias="main"
      client={client}
      tabs={tabs}
      activeTab={pluginSourceTab}
      activeTabPath={pluginSourceTab.path}
      focused={false}
      {...callbacks}
    />,
  );
  expect(breadcrumbParts()).toEqual(["waves", "demo.vcd", "波形查看器"]);

  rerender(
    <EditorPane
      botAlias="main"
      client={client}
      tabs={tabs}
      activeTab={pluginTab}
      activeTabPath={pluginTab.path}
      focused={false}
      {...callbacks}
    />,
  );
  expect(breadcrumbParts()).toEqual(["插件", "资源报告"]);
  expect(screen.getByRole("navigation", { name: "文件路径" })).not.toHaveTextContent("plugin://");
});

test("editor pane sends definition and implementation intents from F12 shortcuts", () => {
  const content = "def greet():\n    return None\n\ngreet()\n";
  const activeTab = createTab({
    path: "main.py",
    basename: "main.py",
    content,
    savedContent: content,
  });
  const onResolveCodeNavigation = vi.fn();
  renderEditor(activeTab, [activeTab], { onResolveCodeNavigation });
  const editor = screen.getByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  const callOffset = content.lastIndexOf("greet") + 2;
  editor.focus();
  editor.setSelectionRange(callOffset, callOffset);

  fireEvent.keyDown(editor, { key: "F12" });
  fireEvent.keyDown(editor, { key: "F12", ctrlKey: true });

  expect(onResolveCodeNavigation).toHaveBeenNthCalledWith(1, {
    kind: "definition",
    path: "main.py",
    line: 4,
    column: 3,
    symbol: "greet",
  });
  expect(onResolveCodeNavigation).toHaveBeenNthCalledWith(2, {
    kind: "implementation",
    path: "main.py",
    line: 4,
    column: 3,
    symbol: "greet",
  });
});

test("editor pane suppresses implementation navigation when the server capability is absent", () => {
  const content = "def greet():\n    return None\n\ngreet()\n";
  const activeTab = createTab({
    path: "main.py",
    basename: "main.py",
    content,
    savedContent: content,
  });
  const onResolveCodeNavigation = vi.fn();
  renderEditor(activeTab, [activeTab], {
    canNavigateImplementation: false,
    onResolveCodeNavigation,
  });
  const editor = screen.getByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  const callOffset = content.lastIndexOf("greet") + 2;
  editor.focus();
  editor.setSelectionRange(callOffset, callOffset);

  fireEvent.keyDown(editor, { key: "F12", ctrlKey: true });

  expect(onResolveCodeNavigation).not.toHaveBeenCalled();
});

test("editor pane keeps Ctrl-click bound to semantic definition navigation", () => {
  const content = "def greet():\n    return None\n\ngreet()\n";
  const activeTab = createTab({
    path: "main.py",
    basename: "main.py",
    content,
    savedContent: content,
  });
  const onResolveCodeNavigation = vi.fn();
  renderEditor(activeTab, [activeTab], { onResolveCodeNavigation });
  const editor = screen.getByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  const callOffset = content.lastIndexOf("greet") + 3;
  editor.setSelectionRange(callOffset, callOffset);

  fireEvent.click(editor, { button: 0, ctrlKey: true });

  expect(onResolveCodeNavigation).toHaveBeenCalledWith({
    kind: "definition",
    path: "main.py",
    line: 4,
    column: 4,
    symbol: "greet",
  });
});

test("editor pane exposes code navigation through the touch action menu", async () => {
  const user = userEvent.setup();
  const content = "def greet():\n    return None\n\ngreet()\n";
  const activeTab = createTab({
    path: "main.py",
    basename: "main.py",
    content,
    savedContent: content,
  });
  const onResolveCodeNavigation = vi.fn();
  renderEditor(activeTab, [activeTab], { onResolveCodeNavigation });
  const editor = screen.getByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  const callOffset = content.lastIndexOf("greet") + 1;
  editor.focus();
  editor.setSelectionRange(callOffset, callOffset);

  await user.click(screen.getByRole("button", { name: "编辑器操作" }));
  await user.click(screen.getByRole("menuitem", { name: "转到定义" }));

  expect(onResolveCodeNavigation).toHaveBeenCalledWith(expect.objectContaining({
    kind: "definition",
    path: "main.py",
    line: 4,
    column: 2,
    symbol: "greet",
  }));
});

test("editor reveal moves the real cursor to the requested line and column", async () => {
  const content = "first\n  greet()\nlast\n";
  const activeTab = createTab({
    path: "main.py",
    basename: "main.py",
    content,
    savedContent: content,
  });
  renderEditor(activeTab, [activeTab], {
    currentLine: 3,
    editorReveal: {
      path: "main.py",
      line: 2,
      column: 3,
      requestId: "reveal-1",
    },
  });
  const editor = screen.getByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;

  await waitFor(() => {
    expect(editor.selectionStart).toBe(8);
    expect(editor.selectionEnd).toBe(8);
    expect(editor).toHaveFocus();
  });
});

test("editor navigation reports Unicode code-point columns after an emoji", () => {
  const content = "😀greet()\n";
  const activeTab = createTab({
    path: "main.py",
    basename: "main.py",
    content,
    savedContent: content,
  });
  const onResolveCodeNavigation = vi.fn();
  renderEditor(activeTab, [activeTab], { onResolveCodeNavigation });
  const editor = screen.getByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  const greetOffset = content.indexOf("greet");
  editor.focus();
  editor.setSelectionRange(greetOffset, greetOffset);

  fireEvent.keyDown(editor, { key: "F12" });

  expect(onResolveCodeNavigation).toHaveBeenCalledWith(expect.objectContaining({
    line: 1,
    column: 2,
    symbol: "greet",
  }));
});

test("editor reveal converts a Unicode code-point column back to the UTF-16 cursor offset", async () => {
  const content = "😀greet()\n";
  const activeTab = createTab({
    path: "main.py",
    basename: "main.py",
    content,
    savedContent: content,
  });
  renderEditor(activeTab, [activeTab], {
    editorReveal: {
      path: "main.py",
      line: 1,
      column: 2,
      requestId: "emoji-reveal",
    },
  });
  const editor = screen.getByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;

  await waitFor(() => {
    expect(editor.selectionStart).toBe(content.indexOf("greet"));
    expect(editor.selectionEnd).toBe(content.indexOf("greet"));
  });
});
