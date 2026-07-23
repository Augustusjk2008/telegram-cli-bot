import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { CommandPalette } from "../workbench/CommandPalette";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";
import {
  useCodeNavigationHistory,
  type CodeNavigationHistoryLocation,
} from "../workbench/useCodeNavigationHistory";


function location(path: string, line = 1, column = 1): CodeNavigationHistoryLocation {
  return { path, line, column };
}


test("navigation history moves backward and forward through recorded semantic jumps", async () => {
  const onNavigate = vi.fn(async () => true);
  const { result } = renderHook(() => useCodeNavigationHistory({ scopeKey: "main:root-a", onNavigate }));
  const a = location("a.py", 1, 2);
  const b = location("b.py", 3, 4);
  const c = location("c.py", 5, 6);

  act(() => {
    result.current.recordNavigation(a, b);
    result.current.recordNavigation(b, c);
  });
  expect(result.current.backStack).toEqual([a, b]);
  expect(result.current.currentLocation).toEqual(c);

  await act(async () => {
    expect(await result.current.goBack()).toBe(true);
  });
  expect(onNavigate).toHaveBeenLastCalledWith(b);
  expect(result.current.backStack).toEqual([a]);
  expect(result.current.forwardStack).toEqual([c]);

  await act(async () => {
    expect(await result.current.goForward()).toBe(true);
  });
  expect(onNavigate).toHaveBeenLastCalledWith(c);
  expect(result.current.backStack).toEqual([a, b]);
  expect(result.current.forwardStack).toEqual([]);
});


test("navigation history deduplicates consecutive locations and keeps at most one hundred entries", () => {
  const { result } = renderHook(() => useCodeNavigationHistory({
    scopeKey: "main:root-a",
    onNavigate: async () => true,
  }));

  const a = location("same.py", 1, 1);
  const b = location("target.py", 2, 2);
  act(() => {
    result.current.recordNavigation(a, b);
    result.current.recordNavigation(a, b);
  });
  expect(result.current.backStack).toEqual([a]);

  act(() => {
    for (let index = 0; index < 105; index += 1) {
      result.current.recordNavigation(location(`source-${index}.py`), location(`target-${index}.py`));
    }
  });

  expect(result.current.backStack).toHaveLength(100);
  expect(result.current.backStack.at(-1)).toEqual(location("source-104.py"));
  expect(result.current.backStack.filter((item) => item.path === "same.py")).toHaveLength(0);
});


test("a new semantic jump after going back clears the forward stack", async () => {
  const { result } = renderHook(() => useCodeNavigationHistory({
    scopeKey: "main:root-a",
    onNavigate: async () => true,
  }));
  const a = location("a.py");
  const b = location("b.py");
  const c = location("c.py");
  const d = location("d.py");

  act(() => {
    result.current.recordNavigation(a, b);
    result.current.recordNavigation(b, c);
  });
  await act(async () => {
    await result.current.goBack();
  });
  expect(result.current.canGoForward).toBe(true);

  act(() => result.current.recordNavigation(b, d));

  expect(result.current.forwardStack).toEqual([]);
  expect(result.current.canGoForward).toBe(false);
});


test("changing the bot or workspace scope clears navigation history", async () => {
  const onNavigate = vi.fn(async () => true);
  const { result, rerender } = renderHook(
    ({ scopeKey }) => useCodeNavigationHistory({ scopeKey, onNavigate }),
    { initialProps: { scopeKey: "main:root-a" } },
  );

  act(() => result.current.recordNavigation(location("a.py"), location("b.py")));
  expect(result.current.canGoBack).toBe(true);

  rerender({ scopeKey: "team:root-b" });

  await waitFor(() => expect(result.current.canGoBack).toBe(false));
  expect(result.current.currentLocation).toBeNull();
});


test("changing scope discards an in-flight back navigation result", async () => {
  let resolveNavigation: (opened: boolean) => void = () => undefined;
  const pendingNavigation = new Promise<boolean>((resolve) => {
    resolveNavigation = resolve;
  });
  const onNavigate = vi.fn(() => pendingNavigation);
  const { result, rerender } = renderHook(
    ({ scopeKey }) => useCodeNavigationHistory({ scopeKey, onNavigate }),
    { initialProps: { scopeKey: "main:root-a" } },
  );

  act(() => result.current.recordNavigation(location("a.py"), location("b.py")));
  let goBackResult: Promise<boolean> | undefined;
  act(() => {
    goBackResult = result.current.goBack();
  });
  expect(result.current.navigating).toBe(true);

  rerender({ scopeKey: "team:root-b" });
  await waitFor(() => expect(result.current.currentLocation).toBeNull());

  await act(async () => {
    resolveNavigation(true);
    expect(await goBackResult).toBe(false);
  });
  expect(result.current.backStack).toEqual([]);
  expect(result.current.forwardStack).toEqual([]);
  expect(result.current.currentLocation).toBeNull();
});


test("changing scope discards an in-flight forward navigation result", async () => {
  let resolveNavigation: (opened: boolean) => void = () => undefined;
  const pendingNavigation = new Promise<boolean>((resolve) => {
    resolveNavigation = resolve;
  });
  const onNavigate = vi
    .fn<(_location: CodeNavigationHistoryLocation) => Promise<boolean>>()
    .mockResolvedValueOnce(true)
    .mockImplementationOnce(() => pendingNavigation);
  const { result, rerender } = renderHook(
    ({ scopeKey }) => useCodeNavigationHistory({ scopeKey, onNavigate }),
    { initialProps: { scopeKey: "main:root-a" } },
  );

  act(() => result.current.recordNavigation(location("a.py"), location("b.py")));
  await act(async () => {
    expect(await result.current.goBack()).toBe(true);
  });
  expect(result.current.canGoForward).toBe(true);

  let goForwardResult: Promise<boolean> | undefined;
  act(() => {
    goForwardResult = result.current.goForward();
  });
  expect(result.current.navigating).toBe(true);

  rerender({ scopeKey: "team:root-b" });
  await waitFor(() => expect(result.current.currentLocation).toBeNull());

  await act(async () => {
    resolveNavigation(true);
    expect(await goForwardResult).toBe(false);
  });
  expect(result.current.backStack).toEqual([]);
  expect(result.current.forwardStack).toEqual([]);
  expect(result.current.currentLocation).toBeNull();
});


test("Alt+Left and Alt+Right are handled only when navigation can execute", async () => {
  const onNavigate = vi.fn(async () => true);
  const { result } = renderHook(() => useCodeNavigationHistory({ scopeKey: "main:root-a", onNavigate }));
  const unavailable = new KeyboardEvent("keydown", { key: "ArrowLeft", altKey: true, cancelable: true });

  expect(result.current.handleShortcut(unavailable)).toBe(false);
  expect(unavailable.defaultPrevented).toBe(false);

  act(() => result.current.recordNavigation(location("a.py"), location("b.py")));
  const back = new KeyboardEvent("keydown", { key: "ArrowLeft", altKey: true, cancelable: true });
  act(() => {
    if (result.current.handleShortcut(back)) {
      back.preventDefault();
    }
  });

  expect(back.defaultPrevented).toBe(true);
  await waitFor(() => expect(onNavigate).toHaveBeenCalledWith(location("a.py")));

  const forward = new KeyboardEvent("keydown", { key: "ArrowRight", altKey: true, cancelable: true });
  act(() => {
    if (result.current.handleShortcut(forward)) {
      forward.preventDefault();
    }
  });
  expect(forward.defaultPrevented).toBe(true);
  await waitFor(() => expect(onNavigate).toHaveBeenCalledWith(location("b.py")));
});


test("failed history navigation preserves both stacks", async () => {
  const { result } = renderHook(() => useCodeNavigationHistory({
    scopeKey: "main:root-a",
    onNavigate: async () => false,
  }));
  act(() => result.current.recordNavigation(location("a.py"), location("b.py")));

  await act(async () => {
    expect(await result.current.goBack()).toBe(false);
  });

  expect(result.current.backStack).toEqual([location("a.py")]);
  expect(result.current.forwardStack).toEqual([]);
  expect(result.current.currentLocation).toEqual(location("b.py"));
});


test("command palette exposes definition, implementation, back, and forward commands", async () => {
  const user = userEvent.setup();
  const onClose = vi.fn();
  const onNavigateDefinition = vi.fn();
  const onNavigateImplementation = vi.fn();
  const onNavigateBack = vi.fn(async () => true);
  const onNavigateForward = vi.fn(async () => true);

  render(
    <CommandPalette
      open
      botAlias="main"
      client={new MockWebBotClient()}
      onClose={onClose}
      onOpenFile={vi.fn()}
      canNavigateDefinition
      canNavigateImplementation
      canNavigateBack
      canNavigateForward={false}
      onNavigateDefinition={onNavigateDefinition}
      onNavigateImplementation={onNavigateImplementation}
      onNavigateBack={onNavigateBack}
      onNavigateForward={onNavigateForward}
    />,
  );

  const palette = screen.getByRole("dialog", { name: "命令面板" });
  expect(within(palette).getByRole("button", { name: /转到定义/ })).toBeEnabled();
  expect(within(palette).getByRole("button", { name: /转到实现/ })).toBeEnabled();
  expect(within(palette).getByRole("button", { name: /导航后退/ })).toBeEnabled();
  expect(within(palette).getByRole("button", { name: /导航前进/ })).toBeDisabled();

  await user.click(within(palette).getByRole("button", { name: /转到定义/ }));
  expect(onNavigateDefinition).toHaveBeenCalledTimes(1);
  expect(onClose).toHaveBeenCalledTimes(1);
});


test("desktop history reopens a closed workspace file and command navigation uses the active cursor", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const readFileFull = vi.spyOn(client, "readFileFull");
  const navigationRequests: Array<{
    kind: string;
    path: string;
    line: number;
    column: number;
  }> = [];
  let navigationIndex = 0;
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => {
    navigationRequests.push({
      kind: request.kind,
      path: request.document.path,
      line: request.position.line,
      column: request.position.column,
    });
    const targetPath = navigationIndex === 0 ? "src/server.ts" : "src/third.ts";
    navigationIndex += 1;
    return {
      requestId: request.requestId,
      message: "",
      items: [{
        targetType: "workspace",
        path: targetPath,
        provider: "test-semantic",
        range: {
          start: { line: 1, column: 1 },
          end: { line: 1, column: 12 },
        },
        selectionRange: {
          start: { line: 1, column: 6 },
          end: { line: 1, column: 10 },
        },
      }],
    };
  });

  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias="main" client={client} />
    </PersistentTerminalProvider>,
  );
  await user.click(await screen.findByRole("button", { name: "展开 src" }));
  await user.click(await screen.findByRole("button", { name: "打开 src/index.ts" }));
  const initialEditor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  initialEditor.focus();
  initialEditor.setSelectionRange(2, 2);

  fireEvent.keyDown(window, { key: "p", ctrlKey: true });
  const palette = await screen.findByRole("dialog", { name: "命令面板" });
  await user.click(within(palette).getByRole("button", { name: /转到定义/ }));
  expect(await screen.findByRole("tab", { name: "server.ts" })).toHaveAttribute("aria-selected", "true");
  expect(navigationRequests[0]).toEqual({
    kind: "definition",
    path: "src/index.ts",
    line: 1,
    column: 3,
  });

  const serverEditor = screen.getByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  serverEditor.focus();
  serverEditor.setSelectionRange(3, 3);
  fireEvent.keyDown(serverEditor, { key: "F12" });
  expect(await screen.findByRole("tab", { name: "third.ts" })).toHaveAttribute("aria-selected", "true");
  expect(navigationRequests[1]).toEqual({
    kind: "definition",
    path: "src/server.ts",
    line: 1,
    column: 4,
  });

  await user.click(screen.getByRole("button", { name: "关闭 src/third.ts" }));
  expect(screen.queryByRole("tab", { name: "third.ts" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "导航后退" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "导航前进" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "导航前进" }));

  expect(await screen.findByRole("tab", { name: "third.ts" })).toHaveAttribute("aria-selected", "true");
  expect(readFileFull.mock.calls.filter((call) => call[1] === "src/third.ts")).toHaveLength(2);
});

test("desktop code navigation cancels a superseded request and shows multiple destinations", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  window.localStorage.clear();
  const signals: AbortSignal[] = [];
  let invocation = 0;
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation((_alias, request, signal) => {
    invocation += 1;
    if (signal) {
      signals.push(signal);
    }
    if (invocation === 1) {
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("请求已取消", "AbortError"));
        }, { once: true });
      });
    }
    return Promise.resolve({
      requestId: request.requestId,
      message: "",
      items: [
        {
          targetType: "workspace" as const,
          path: "src/one.ts",
          provider: "test-semantic",
          range: {
            start: { line: 1, column: 1 },
            end: { line: 1, column: 12 },
          },
          selectionRange: {
            start: { line: 1, column: 5 },
            end: { line: 1, column: 8 },
          },
        },
        {
          targetType: "workspace" as const,
          path: "src/two.ts",
          provider: "test-semantic",
          range: {
            start: { line: 4, column: 1 },
            end: { line: 4, column: 12 },
          },
          selectionRange: {
            start: { line: 4, column: 3 },
            end: { line: 4, column: 6 },
          },
        },
      ],
    });
  });

  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias="main" client={client} />
    </PersistentTerminalProvider>,
  );
  await user.click(await screen.findByRole("button", { name: "展开 src" }));
  await user.click(await screen.findByRole("button", { name: "打开 src/index.ts" }));
  const editor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  editor.focus();
  editor.setSelectionRange(2, 2);

  fireEvent.keyDown(editor, { key: "F12" });
  fireEvent.keyDown(editor, { key: "F12" });

  await waitFor(() => expect(invocation).toBe(2));
  expect(signals).toHaveLength(2);
  await waitFor(() => expect(signals[0]?.aborted).toBe(true));
  expect(signals[1]?.aborted).toBe(false);
  expect(await screen.findByText("src/one.ts")).toBeVisible();
  expect(screen.getByText("src/two.ts")).toBeVisible();
  expect(screen.queryByText("代码导航失败")).not.toBeInTheDocument();
});
