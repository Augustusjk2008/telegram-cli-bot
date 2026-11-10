import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";
import { WORKBENCH_PANE_STATE_STORAGE_KEY } from "../workbench/useWorkbenchState";

// Geometry is covered by workbench-layout.test.ts; this file only checks the wiring.

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

function workbench(client: MockWebBotClient, botAlias = "main") {
  return (
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias={botAlias} client={client} chatPaneContent={<div data-testid="chat-probe">Chat</div>} />
    </PersistentTerminalProvider>
  );
}

function storedPaneState() {
  return JSON.parse(localStorage.getItem(WORKBENCH_PANE_STATE_STORAGE_KEY) || "{}");
}

async function openLayoutMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "窗口布局" }));
  return within(await screen.findByRole("dialog", { name: "窗口布局" }));
}

test("choosing a preset only re-places the panes and saves the choice", async () => {
  const user = userEvent.setup();
  render(workbench(new MockWebBotClient()));

  const menu = await openLayoutMenu(user);
  expect(menu.getByRole("button", { name: "经典" })).toHaveAttribute("aria-pressed", "true");
  await user.click(menu.getByRole("button", { name: "底部通栏" }));

  expect(screen.queryByRole("dialog", { name: "窗口布局" })).not.toBeInTheDocument();
  expect(screen.getByTestId("desktop-workbench-columns")).toHaveAttribute("data-layout-template", "bottomPanel");
  expect(screen.getByTestId("desktop-pane-terminal")).toHaveAttribute("data-layout-slot", "bottom");
  await waitFor(() => expect(storedPaneState()).toMatchObject({ layoutVersion: 1, activeLayout: "bottomPanel" }));
});

test("rearrange mode swaps panes without remounting them and Escape leaves it", async () => {
  const user = userEvent.setup();
  render(workbench(new MockWebBotClient()));
  const chatProbe = screen.getByTestId("chat-probe");
  const terminal = screen.getByTestId("desktop-pane-terminal");

  await user.click((await openLayoutMenu(user)).getByRole("button", { name: "底部通栏" }));
  await user.click((await openLayoutMenu(user)).getByRole("button", { name: "调整窗口位置…" }));
  expect(screen.getByTestId("desktop-workbench-columns")).toHaveAttribute("data-layout-editing", "true");
  expect(screen.getByRole("toolbar", { name: "窗口布局编辑" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "将侧边栏与聊天交换位置" }));

  expect(screen.getByTestId("desktop-pane-files")).toHaveAttribute("data-layout-slot", "right");
  expect(screen.getByTestId("desktop-pane-chat")).toHaveAttribute("data-layout-slot", "left");
  expect(screen.getByTestId("chat-probe")).toBe(chatProbe);
  expect(screen.getByTestId("desktop-pane-terminal")).toBe(terminal);

  await user.keyboard("{Escape}");

  expect(screen.queryByTestId("workbench-layout-slot-chat")).not.toBeInTheDocument();
  expect(screen.getByTestId("desktop-workbench-columns")).toHaveAttribute("data-layout-editing", "false");
  expect(screen.getByRole("button", { name: "窗口布局" })).toHaveFocus();
  await waitFor(() => expect(storedPaneState().layouts.bottomPanel.slots).toMatchObject({ left: "chat", right: "sidebar" }));
});

test("switching bots leaves rearrange mode", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const { rerender } = render(workbench(client));

  await user.click((await openLayoutMenu(user)).getByRole("button", { name: "调整窗口位置…" }));
  expect(screen.getByTestId("workbench-layout-slot-sidebar")).toBeInTheDocument();

  rerender(workbench(client, "other"));

  await waitFor(() => expect(screen.queryByTestId("workbench-layout-slot-sidebar")).not.toBeInTheDocument());
});

test("legacy pane sizes still size the classic layout", () => {
  localStorage.setItem(WORKBENCH_PANE_STATE_STORAGE_KEY, JSON.stringify({ sidebarWidthPx: 300, chatWidthPx: 400, editorHeightPx: 380 }));

  render(workbench(new MockWebBotClient()));

  // jsdom has no layout, so the grid keeps the 1440×900 fallback size.
  expect(screen.getByTestId("desktop-workbench-columns").style.gridTemplateColumns).toBe("300px 8px minmax(0, 1fr) 8px 400px");
});
