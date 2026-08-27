import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";
import { WORKBENCH_PANE_STATE_STORAGE_KEY } from "../workbench/useWorkbenchState";

beforeEach(() => {
  localStorage.clear();
});

test("横板四区全部收起后仍可从顶部布局开关恢复", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias="main" client={client} />
    </PersistentTerminalProvider>,
  );

  const centerRows = screen.getByTestId("desktop-workbench-center-rows");
  const columns = screen.getByTestId("desktop-workbench-columns");
  const editorPane = screen.getByTestId("desktop-pane-editor");
  const terminalPane = screen.getByTestId("desktop-pane-terminal");

  await user.click(screen.getByRole("button", { name: "隐藏编辑/预览区" }));
  expect(editorPane).toHaveAttribute("data-collapsed", "true");
  expect(editorPane).toHaveClass("hidden");
  expect(terminalPane).not.toHaveClass("hidden");
  expect(terminalPane).toHaveClass("row-start-3");
  expect(centerRows).toHaveStyle({ gridTemplateRows: "0px 0px minmax(160px, 1fr)" });

  await user.click(screen.getByRole("button", { name: "隐藏底部终端" }));
  expect(terminalPane).toHaveAttribute("data-collapsed", "true");
  expect(terminalPane).toHaveClass("hidden");
  expect(centerRows).toHaveStyle({ gridTemplateRows: "0px 0px 0px" });
  expect(columns).toHaveStyle({ gridTemplateColumns: "320px 3px 0px 0px minmax(0, 1fr)" });
  expect(screen.getAllByRole("separator")).toHaveLength(1);
  expect(screen.getByRole("separator", { name: "调整文件区宽度" })).toBeVisible();

  await user.click(screen.getByRole("button", { name: "隐藏左侧栏" }));
  await user.click(screen.getByRole("button", { name: "隐藏右侧聊天" }));

  expect(screen.getByRole("button", { name: "显示左侧栏" })).toBeVisible();
  expect(screen.getByRole("button", { name: "显示编辑/预览区" })).toBeVisible();
  expect(screen.getByRole("button", { name: "显示底部终端" })).toBeVisible();
  expect(screen.getByRole("button", { name: "显示右侧聊天" })).toBeVisible();
  expect(columns).toHaveStyle({ gridTemplateColumns: "48px 0px 0px 0px 0px" });
  expect(screen.queryByRole("separator")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "显示编辑/预览区" }));
  expect(editorPane).toHaveAttribute("data-collapsed", "false");
  expect(editorPane).not.toHaveClass("hidden");
  expect(centerRows).toHaveStyle({ gridTemplateRows: "minmax(0, 1fr) 0px 0px" });
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

test("聚焦终端时终端仍固定在可见的第三行", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias="main" client={client} />
    </PersistentTerminalProvider>,
  );

  await user.click(await screen.findByRole("button", { name: "聚焦终端" }));

  expect(screen.getByTestId("desktop-workbench-root"))
    .toHaveAttribute("data-focused-pane", "terminal");
  expect(screen.getByTestId("desktop-workbench-center-rows"))
    .toHaveStyle({ gridTemplateRows: "0px 0px minmax(160px, 1fr)" });
  expect(screen.getByTestId("desktop-pane-terminal")).not.toHaveClass("hidden");
  expect(screen.getByTestId("desktop-pane-terminal")).toHaveClass("row-start-3");
});
