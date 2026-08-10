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

test("editor pane keeps breadcrumbs and tab actions scoped to the selected tab", async () => {
  const user = userEvent.setup();
  const activeTab = createTab();
  const secondTab = createTab({ path: "src/server.ts", basename: "server.ts" });
  const onActivateTab = vi.fn();
  const onCloseTab = vi.fn(() => true);
  const onCloseOthers = vi.fn();

  render(
    <EditorPane
      botAlias="main"
      client={new MockWebBotClient()}
      tabs={[activeTab, secondTab]}
      activeTab={activeTab}
      activeTabPath={activeTab.path}
      focused={false}
      onActivateTab={onActivateTab}
      onCloseTab={onCloseTab}
      onChangeActiveContent={vi.fn()}
      onSaveActiveTab={vi.fn()}
      onCloseAll={vi.fn()}
      onCloseOthers={onCloseOthers}
      onCloseTabsToRight={vi.fn()}
      onReopenLastClosed={vi.fn()}
      onRevealInTree={vi.fn()}
      onToggleFocus={vi.fn()}
    />,
  );

  const breadcrumb = screen.getByRole("navigation", { name: "文件路径" });
  expect(within(breadcrumb).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    "src", "No8Demo", "demo_basic.h",
  ]);
  await user.click(screen.getByRole("tab", { name: "server.ts" }));
  expect(onActivateTab).toHaveBeenCalledWith("src/server.ts");
  fireEvent.contextMenu(screen.getByRole("tab", { name: "server.ts" }));
  await user.click(screen.getByRole("button", { name: "关闭其他标签页" }));
  expect(onCloseOthers).toHaveBeenCalledWith("src/server.ts");
});

test("editor pane offers one-click close all when multiple tabs are open", async () => {
  const user = userEvent.setup();
  const activeTab = createTab();
  const onCloseAll = vi.fn();

  render(
    <EditorPane
      botAlias="main"
      client={new MockWebBotClient()}
      tabs={[activeTab, createTab({ path: "src/server.ts", basename: "server.ts" })]}
      activeTab={activeTab}
      activeTabPath={activeTab.path}
      focused={false}
      onActivateTab={vi.fn()}
      onCloseTab={vi.fn(() => true)}
      onChangeActiveContent={vi.fn()}
      onSaveActiveTab={vi.fn()}
      onCloseAll={onCloseAll}
      onCloseOthers={vi.fn()}
      onCloseTabsToRight={vi.fn()}
      onReopenLastClosed={vi.fn()}
      onRevealInTree={vi.fn()}
      onToggleFocus={vi.fn()}
    />,
  );

  await user.click(screen.getByRole("button", { name: "关闭全部标签页" }));
  expect(onCloseAll).toHaveBeenCalledOnce();
});
