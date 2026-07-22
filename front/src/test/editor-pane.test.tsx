import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { EditorPane } from "../workbench/EditorPane";
import type { EditorTab } from "../workbench/workbenchTypes";

function createTab(overrides: Partial<EditorTab> = {}): EditorTab {
  return {
    path: "src/No8Demo/demo_basic.h",
    basename: "demo_basic.h",
    content: "#pragma once\n",
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

function renderEditor(activeTab: EditorTab, tabs: EditorTab[] = [activeTab]) {
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
