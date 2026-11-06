import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { WebBotClient } from "../services/webBotClient";
import { EditorPane } from "../workbench/EditorPane";

function renderEmptyEditor(focused: boolean, onToggleFocus = vi.fn()) {
  render(
    <EditorPane
      botAlias="main"
      client={{} as WebBotClient}
      tabs={[]}
      activeTab={null}
      activeTabPath=""
      onActivateTab={vi.fn()}
      onCloseTab={vi.fn(() => true)}
      onChangeActiveContent={vi.fn()}
      onSaveActiveTab={vi.fn()}
      onCloseAll={vi.fn()}
      onCloseOthers={vi.fn()}
      onCloseTabsToRight={vi.fn()}
      onReopenLastClosed={vi.fn()}
      onRevealInTree={vi.fn()}
      focused={focused}
      onToggleFocus={onToggleFocus}
    />,
  );
  return onToggleFocus;
}

test("focused editor keeps an exit-focus control after the last tab closes", () => {
  const onToggleFocus = renderEmptyEditor(true);

  expect(screen.getByTestId("editor-empty-state")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "退出聚焦编辑器" }));
  expect(onToggleFocus).toHaveBeenCalledTimes(1);
});

test("unfocused empty editor does not show the focus control", () => {
  renderEmptyEditor(false);

  expect(screen.queryByRole("button", { name: /聚焦编辑器/ })).not.toBeInTheDocument();
});
