import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";
import { WORKBENCH_PANE_STATE_STORAGE_KEY } from "../workbench/useWorkbenchState";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("横板四区全部收起后仍可从顶部布局开关恢复", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias="main" client={client} />
    </PersistentTerminalProvider>,
  );

  const editorPane = screen.getByTestId("desktop-pane-editor");
  const terminalPane = screen.getByTestId("desktop-pane-terminal");

  await user.click(screen.getByRole("button", { name: "隐藏编辑/预览区" }));
  expect(editorPane).toHaveAttribute("data-collapsed", "true");

  await user.click(screen.getByRole("button", { name: "隐藏底部终端" }));
  expect(terminalPane).toHaveAttribute("data-collapsed", "true");
  expect(screen.getAllByRole("separator")).toHaveLength(1);
  expect(screen.getByRole("separator", { name: "调整文件区宽度" })).toBeVisible();

  await user.click(screen.getByRole("button", { name: "隐藏左侧栏" }));
  await user.click(screen.getByRole("button", { name: "隐藏右侧聊天" }));

  expect(screen.getByRole("button", { name: "显示左侧栏" })).toBeVisible();
  expect(screen.getByRole("button", { name: "显示编辑/预览区" })).toBeVisible();
  expect(screen.getByRole("button", { name: "显示底部终端" })).toBeVisible();
  expect(screen.getByRole("button", { name: "显示右侧聊天" })).toBeVisible();
  expect(screen.queryByRole("separator")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "显示编辑/预览区" }));
  expect(editorPane).toHaveAttribute("data-collapsed", "false");
});

test("旧布局状态默认显示编辑区并在收起后持久恢复", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  localStorage.setItem(WORKBENCH_PANE_STATE_STORAGE_KEY, JSON.stringify({
    sidebarCollapsed: false,
    terminalCollapsed: false,
    chatCollapsed: false,
    sidebarWidthPx: 320,
    chatWidthPx: 384,
    editorHeightPx: 420,
  }));

  const renderWorkbench = () => render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias="main" client={client} />
    </PersistentTerminalProvider>,
  );

  const firstRender = renderWorkbench();
  expect(screen.getByRole("button", { name: "隐藏编辑/预览区" })).toBeVisible();
  expect(screen.getByTestId("desktop-pane-editor")).toHaveAttribute("data-collapsed", "false");

  await user.click(screen.getByRole("button", { name: "隐藏编辑/预览区" }));
  await waitFor(() => {
    expect(JSON.parse(localStorage.getItem(WORKBENCH_PANE_STATE_STORAGE_KEY) || "{}"))
      .toMatchObject({ editorCollapsed: true });
  });

  firstRender.unmount();
  renderWorkbench();
  expect(screen.getByRole("button", { name: "显示编辑/预览区" })).toBeVisible();
  expect(screen.getByTestId("desktop-pane-editor")).toHaveAttribute("data-collapsed", "true");
});

test("以内层内容尺寸约束保存的布局，并响应容器变化、拖拽和聚焦恢复", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  let columnsClientWidth = 1266;
  const resizeCallbacks = new Map<Element, () => void>();
  vi.stubGlobal("ResizeObserver", class {
    private targets: Element[] = [];
    constructor(private callback: () => void) {}
    observe(target: Element) {
      this.targets.push(target);
      resizeCallbacks.set(target, this.callback);
    }
    unobserve(target: Element) { resizeCallbacks.delete(target); }
    disconnect() { this.targets.forEach((target) => resizeCallbacks.delete(target)); }
  });
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (this: HTMLElement) {
    return this.dataset.testid === "desktop-workbench-columns" ? columnsClientWidth : 0;
  });
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.dataset.testid === "desktop-workbench-center-rows" ? 700 : 0;
  });
  localStorage.setItem(WORKBENCH_PANE_STATE_STORAGE_KEY, JSON.stringify({
    sidebarWidthPx: 800,
    chatWidthPx: 700,
    editorHeightPx: 800,
  }));
  const view = render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias="main" client={client} themeName="paper-daylight" />
    </PersistentTerminalProvider>,
  );
  const columns = screen.getByTestId("desktop-workbench-columns");
  const centerRows = screen.getByTestId("desktop-workbench-center-rows");
  columns.style.padding = "2px";
  columns.style.border = "1px solid";
  centerRows.style.padding = "3px";
  centerRows.style.border = "1px solid";
  act(() => resizeCallbacks.get(columns)!());
  expect(columns.style.gridTemplateColumns).toBe("516px 3px minmax(0, 1fr) 3px 260px");
  expect(centerRows.style.gridTemplateRows).toBe("531px 3px minmax(160px, 1fr)");

  columnsClientWidth = 1106;
  act(() => resizeCallbacks.get(columns)!());
  expect(columns.style.gridTemplateColumns).toBe("356px 3px minmax(0, 1fr) 3px 260px");
  expect(JSON.parse(localStorage.getItem(WORKBENCH_PANE_STATE_STORAGE_KEY)!)).toMatchObject({ sidebarWidthPx: 800 });

  fireEvent.pointerDown(screen.getByRole("separator", { name: "调整文件区宽度" }), { clientX: 356 });
  fireEvent.pointerMove(window, { clientX: 316 });
  fireEvent.pointerUp(window);
  expect(columns.style.gridTemplateColumns).toBe("316px 3px minmax(0, 1fr) 3px 260px");
  expect(JSON.parse(localStorage.getItem(WORKBENCH_PANE_STATE_STORAGE_KEY)!)).toMatchObject({ sidebarWidthPx: 316 });

  await user.click(await screen.findByRole("button", { name: "聚焦文件区" }));
  expect(columns.style.gridTemplateColumns).toBe("minmax(0, 1fr) 0px 0px 0px 0px");
  await user.click(screen.getByRole("button", { name: "退出聚焦文件区" }));
  await user.click(screen.getByRole("button", { name: "隐藏左侧栏" }));
  await user.click(screen.getByRole("button", { name: "显示左侧栏" }));
  expect(columns.style.gridTemplateColumns).toBe("316px 3px minmax(0, 1fr) 3px 260px");
  view.unmount();
  expect(resizeCallbacks.has(columns)).toBe(false);
});
