import { EditorView } from "@codemirror/view";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { EditorTab } from "../workbench/workbenchTypes";
import { EditorPane } from "../workbench/EditorPane";

class TestResizeObserver {
  constructor(_callback: ResizeObserverCallback) {}
  observe(_target: Element) {}
  unobserve(_target: Element) {}
  disconnect() {}
}

function createTab(content: string): EditorTab {
  return {
    path: "app.ts",
    basename: "app.ts",
    content,
    documentVersion: 7,
    savedContent: content,
    kind: "file",
    dirty: false,
    loading: false,
    saving: false,
    statusText: "",
    error: "",
    cold: false,
    missing: false,
    contentPersistence: "clean_snapshot",
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

test("Ctrl-hover probes a definition without navigating, while Ctrl-click navigates", async () => {
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
  const content = "const greet = 1;\ngreet();";
  const activeTab = createTab(content);
  const client = new MockWebBotClient();
  const resolveCodeNavigation = vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => ({
    requestId: request.requestId,
    message: "",
    items: [{
      targetType: "workspace",
      path: "lib/greet.ts",
      provider: "test-semantic",
      range: { start: { line: 1, column: 1 }, end: { line: 1, column: 10 } },
      selectionRange: { start: { line: 1, column: 1 }, end: { line: 1, column: 6 } },
    }],
  }));
  const onResolveCodeNavigation = vi.fn();
  vi.spyOn(EditorView.prototype, "posAtCoords").mockReturnValue(content.lastIndexOf("greet") + 2);

  const { container } = render(
    <EditorPane
      botAlias="main" client={client} tabs={[activeTab]} activeTab={activeTab} activeTabPath={activeTab.path} focused={false}
      onResolveCodeNavigation={onResolveCodeNavigation} onActivateTab={vi.fn()} onCloseTab={vi.fn(() => true)}
      onChangeActiveContent={vi.fn()} onSaveActiveTab={vi.fn()} onCloseAll={vi.fn()} onCloseOthers={vi.fn()} onCloseTabsToRight={vi.fn()}
      onReopenLastClosed={vi.fn()} onRevealInTree={vi.fn()} onToggleFocus={vi.fn()}
    />,
  );
  const editorContent = await waitFor(() => {
    const element = container.querySelector<HTMLElement>(".cm-content");
    expect(element).not.toBeNull();
    return element as HTMLElement;
  });

  fireEvent.mouseMove(editorContent, { clientX: 24, clientY: 24, ctrlKey: true });
  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalled());
  expect(onResolveCodeNavigation).not.toHaveBeenCalled();
  const editorHost = container.querySelector<HTMLElement>("[data-testid='file-editor-host']");
  fireEvent.mouseDown(editorHost as HTMLElement, { button: 0, clientX: 24, clientY: 24, ctrlKey: true });
  expect(onResolveCodeNavigation).toHaveBeenCalledWith({ kind: "definition", path: "app.ts", line: 2, column: 3, symbol: "greet" });
});
