import { EditorView } from "@codemirror/view";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { FileEditorSurface } from "../components/FileEditorSurface";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { CodeNavigationIntent } from "../services/types";
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

test("EditorPane resolves Ctrl-hover without triggering navigation and keeps Ctrl-click navigation", async () => {
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
      range: {
        start: { line: 1, column: 1 },
        end: { line: 1, column: 10 },
      },
      selectionRange: {
        start: { line: 1, column: 1 },
        end: { line: 1, column: 6 },
      },
    }],
  }));
  const onResolveCodeNavigation = vi.fn();
  vi.spyOn(EditorView.prototype, "posAtCoords").mockReturnValue(content.lastIndexOf("greet") + 2);

  const { container } = render(
    <EditorPane
      botAlias="main"
      client={client}
      tabs={[activeTab]}
      activeTab={activeTab}
      activeTabPath={activeTab.path}
      focused={false}
      onResolveCodeNavigation={onResolveCodeNavigation}
      onActivateTab={vi.fn()}
      onCloseTab={vi.fn(() => true)}
      onChangeActiveContent={vi.fn()}
      onSaveActiveTab={vi.fn()}
      onCloseOthers={vi.fn()}
      onCloseTabsToRight={vi.fn()}
      onReopenLastClosed={vi.fn()}
      onRevealInTree={vi.fn()}
      onToggleFocus={vi.fn()}
    />,
  );
  const editorContent = await waitFor(() => {
    const element = container.querySelector<HTMLElement>(".cm-content");
    expect(element).not.toBeNull();
    return element as HTMLElement;
  });

  fireEvent.mouseMove(editorContent, { clientX: 24, clientY: 24, ctrlKey: true });

  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledWith(
    "main",
    expect.objectContaining({
      kind: "definition",
      document: expect.objectContaining({ path: "app.ts", version: 7, content }),
      position: { line: 2, column: 3 },
    }),
    expect.any(AbortSignal),
  ));
  const link = await waitFor(() => {
    const element = container.querySelector<HTMLElement>(".cm-code-navigation-link");
    expect(element?.textContent).toBe("greet");
    return element as HTMLElement;
  });
  expect(onResolveCodeNavigation).not.toHaveBeenCalled();

  const editorHost = container.querySelector<HTMLElement>("[data-testid='file-editor-host']");
  expect(editorHost).not.toBeNull();
  fireEvent.mouseDown(editorHost as HTMLElement, { button: 0, clientX: 24, clientY: 24, ctrlKey: true });

  expect(onResolveCodeNavigation).toHaveBeenCalledTimes(1);
  expect(onResolveCodeNavigation).toHaveBeenCalledWith({
    kind: "definition",
    path: "app.ts",
    line: 2,
    column: 3,
    symbol: "greet",
  });
});

test("EditorPane keeps a pending Ctrl-hover probe when only its navigation callback identity changes", async () => {
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
  const content = "greet();";
  const activeTab = createTab(content);
  const client = new MockWebBotClient();
  let probeSignal: AbortSignal | undefined;
  let resolveProbe: (() => void) | undefined;
  const resolveCodeNavigation = vi.spyOn(client, "resolveCodeNavigation").mockImplementation((_alias, request, signal) => {
    probeSignal = signal;
    return new Promise((resolve) => {
      resolveProbe = () => resolve({ requestId: request.requestId, message: "", items: [] });
    });
  });
  vi.spyOn(EditorView.prototype, "posAtCoords").mockReturnValue(2);
  const pane = (onResolveCodeNavigation: (input: CodeNavigationIntent) => void) => (
    <EditorPane
      botAlias="main"
      client={client}
      tabs={[activeTab]}
      activeTab={activeTab}
      activeTabPath={activeTab.path}
      focused={false}
      onResolveCodeNavigation={onResolveCodeNavigation}
      onActivateTab={vi.fn()}
      onCloseTab={vi.fn(() => true)}
      onChangeActiveContent={vi.fn()}
      onSaveActiveTab={vi.fn()}
      onCloseOthers={vi.fn()}
      onCloseTabsToRight={vi.fn()}
      onReopenLastClosed={vi.fn()}
      onRevealInTree={vi.fn()}
      onToggleFocus={vi.fn()}
    />
  );
  const { container, rerender } = render(pane(vi.fn()));
  const editorContent = await waitFor(() => {
    const element = container.querySelector<HTMLElement>(".cm-content");
    expect(element).not.toBeNull();
    return element as HTMLElement;
  });

  fireEvent.mouseMove(editorContent, { clientX: 24, clientY: 24, ctrlKey: true });
  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledTimes(1));

  rerender(pane(vi.fn()));

  expect(probeSignal?.aborted).toBe(false);
  resolveProbe?.();
  await waitFor(() => expect(container.querySelector(".cm-code-navigation-link")).toBeNull());
});

test("FileEditorSurface does not offer Ctrl-hover without a navigation action", async () => {
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
  const request = vi.fn(async () => true);
  const content = "greet();";
  vi.spyOn(EditorView.prototype, "posAtCoords").mockReturnValue(2);
  const { container } = render(
    <FileEditorSurface
      path="app.ts"
      value={content}
      codeNavigationHover={{ contextKey: "app.ts@1", hoverDelayMs: 0, request }}
      onChange={vi.fn()}
      onSave={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  const editorContent = await waitFor(() => {
    const element = container.querySelector<HTMLElement>(".cm-content");
    expect(element).not.toBeNull();
    return element as HTMLElement;
  });

  fireEvent.mouseMove(editorContent as HTMLElement, { clientX: 24, clientY: 24, ctrlKey: true });
  await new Promise((resolve) => window.setTimeout(resolve, 0));

  expect(request).not.toHaveBeenCalled();
  expect(container.querySelector(".cm-code-navigation-link")).toBeNull();
});

test("FileEditorSurface keeps a pending Ctrl-hover probe across an unrelated rerender", async () => {
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
  const content = "greet();";
  let probeSignal: AbortSignal | undefined;
  let resolveProbe: ((available: boolean) => void) | undefined;
  const request = vi.fn((_input, signal: AbortSignal) => {
    probeSignal = signal;
    return new Promise<boolean>((resolve) => {
      resolveProbe = resolve;
    });
  });
  vi.spyOn(EditorView.prototype, "posAtCoords").mockReturnValue(2);
  const onResolveCodeNavigation = vi.fn();
  const { container, rerender } = render(
    <FileEditorSurface
      path="app.ts"
      value={content}
      codeNavigationHover={{ contextKey: "app.ts@1", hoverDelayMs: 0, request }}
      onResolveCodeNavigation={onResolveCodeNavigation}
      onChange={vi.fn()}
      onSave={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  const editorContent = await waitFor(() => {
    const element = container.querySelector<HTMLElement>(".cm-content");
    expect(element).not.toBeNull();
    return element as HTMLElement;
  });

  fireEvent.mouseMove(editorContent, { clientX: 24, clientY: 24, ctrlKey: true });
  await waitFor(() => expect(request).toHaveBeenCalledTimes(1));

  rerender(
    <FileEditorSurface
      path="app.ts"
      value={content}
      currentLine={1}
      statusText="后台状态刷新"
      codeNavigationHover={{ contextKey: "app.ts@1", hoverDelayMs: 0, request }}
      onResolveCodeNavigation={onResolveCodeNavigation}
      onChange={vi.fn()}
      onSave={vi.fn()}
      onClose={vi.fn()}
    />,
  );

  expect(probeSignal?.aborted).toBe(false);
  resolveProbe?.(true);
  await waitFor(() => expect(container.querySelector(".cm-code-navigation-link")).not.toBeNull());
});

test("FileEditorSurface clears a decorated link after rerender when Ctrl is released", async () => {
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
  const content = "greet();";
  const request = vi.fn(async () => true);
  vi.spyOn(EditorView.prototype, "posAtCoords").mockReturnValue(2);
  const onResolveCodeNavigation = vi.fn();
  const { container, rerender } = render(
    <FileEditorSurface
      path="app.ts"
      value={content}
      codeNavigationHover={{ contextKey: "app.ts@1", hoverDelayMs: 0, request }}
      onResolveCodeNavigation={onResolveCodeNavigation}
      onChange={vi.fn()}
      onSave={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  const editorContent = await waitFor(() => {
    const element = container.querySelector<HTMLElement>(".cm-content");
    expect(element).not.toBeNull();
    return element as HTMLElement;
  });

  fireEvent.mouseMove(editorContent, { clientX: 24, clientY: 24, ctrlKey: true });
  await waitFor(() => expect(container.querySelector(".cm-code-navigation-link")).not.toBeNull());

  rerender(
    <FileEditorSurface
      path="app.ts"
      value={content}
      currentLine={1}
      statusText="后台状态刷新"
      codeNavigationHover={{ contextKey: "app.ts@1", hoverDelayMs: 0, request }}
      onResolveCodeNavigation={onResolveCodeNavigation}
      onChange={vi.fn()}
      onSave={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  window.dispatchEvent(new KeyboardEvent("keyup", { key: "Control" }));

  expect(container.querySelector(".cm-code-navigation-link")).toBeNull();
});

test("FileEditorSurface aborts a pending Ctrl-hover probe when its semantic context changes", async () => {
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
  const content = "greet();";
  let firstSignal: AbortSignal | undefined;
  let resolveFirstProbe: ((available: boolean) => void) | undefined;
  const firstRequest = vi.fn((_input, signal: AbortSignal) => {
    firstSignal = signal;
    return new Promise<boolean>((resolve) => {
      resolveFirstProbe = resolve;
    });
  });
  const secondRequest = vi.fn(async () => true);
  vi.spyOn(EditorView.prototype, "posAtCoords").mockReturnValue(2);
  const onResolveCodeNavigation = vi.fn();
  const { container, rerender } = render(
    <FileEditorSurface
      path="app.ts"
      value={content}
      codeNavigationHover={{ contextKey: "client-a:app.ts@1", hoverDelayMs: 0, request: firstRequest }}
      onResolveCodeNavigation={onResolveCodeNavigation}
      onChange={vi.fn()}
      onSave={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  const editorContent = await waitFor(() => {
    const element = container.querySelector<HTMLElement>(".cm-content");
    expect(element).not.toBeNull();
    return element as HTMLElement;
  });

  fireEvent.mouseMove(editorContent, { clientX: 24, clientY: 24, ctrlKey: true });
  await waitFor(() => expect(firstRequest).toHaveBeenCalledTimes(1));

  rerender(
    <FileEditorSurface
      path="app.ts"
      value={content}
      codeNavigationHover={{ contextKey: "client-b:app.ts@1", hoverDelayMs: 0, request: secondRequest }}
      onResolveCodeNavigation={onResolveCodeNavigation}
      onChange={vi.fn()}
      onSave={vi.fn()}
      onClose={vi.fn()}
    />,
  );

  expect(firstSignal?.aborted).toBe(true);
  resolveFirstProbe?.(true);
  await Promise.resolve();
  expect(container.querySelector(".cm-code-navigation-link")).toBeNull();
  expect(secondRequest).not.toHaveBeenCalled();

  fireEvent.mouseMove(editorContent, { clientX: 24, clientY: 24, ctrlKey: true });
  await waitFor(() => expect(secondRequest).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(container.querySelector(".cm-code-navigation-link")).not.toBeNull());
});
