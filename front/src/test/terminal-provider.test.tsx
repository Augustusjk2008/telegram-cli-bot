import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { PersistentTerminalProvider, usePersistentTerminal } from "../terminal/PersistentTerminalProvider";
import type { PersistentTerminalSnapshot } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

const snapshot = (cwd = "C:/workspace"): PersistentTerminalSnapshot => ({
  started: true,
  closed: false,
  cwd,
  ptyMode: true,
  connectionText: "运行中",
  lastSeq: 0,
});

function Harness() {
  const terminal = usePersistentTerminal();
  return (
    <div>
      <span data-testid="tab-count">{terminal.tabs.length}</span>
      <span data-testid="active-owner">{terminal.ownerId}</span>
      {terminal.tabs.map((tab) => (
        <button key={tab.id} data-testid={`select-${tab.id}`} onClick={() => terminal.selectTab(tab.id)}>
          {tab.title}
        </button>
      ))}
      <button onClick={() => void terminal.createTab({ cwd: "C:/new" })}>新建</button>
      {terminal.tabs.map((tab) => (
        <button key={`close-${tab.id}`} data-testid={`close-${tab.id}`} onClick={() => void terminal.closeTab(tab.id)}>
          关闭 {tab.title}
        </button>
      ))}
    </div>
  );
}

beforeEach(() => {
  localStorage.clear();
});

test("新建 tab 使用独立 owner，关闭 tab 会先关闭对应后台终端", async () => {
  const client = {
    getTerminalSession: vi.fn(async () => snapshot()),
    createTerminalSession: vi.fn(async (_ownerId: string, cwd: string) => snapshot(cwd)),
    closeTerminalSession: vi.fn(async () => ({ ...snapshot(), started: false, closed: true, connectionText: "终端已关闭" })),
  } as unknown as WebBotClient;

  render(
    <PersistentTerminalProvider client={client}>
      <Harness />
    </PersistentTerminalProvider>,
  );

  await waitFor(() => expect(screen.getByTestId("tab-count")).toHaveTextContent("1"));
  const firstOwner = screen.getByTestId("active-owner").textContent;
  fireEvent.click(screen.getByRole("button", { name: "新建" }));

  await waitFor(() => expect(screen.getByTestId("tab-count")).toHaveTextContent("2"));
  const secondOwner = screen.getByTestId("active-owner").textContent;
  expect(secondOwner).not.toBe(firstOwner);
  expect(client.createTerminalSession).toHaveBeenCalledWith(secondOwner, "C:/new", "auto");

  fireEvent.click(screen.getByTestId(`close-${firstOwner}`));
  await waitFor(() => expect(screen.getByTestId("tab-count")).toHaveTextContent("1"));
  expect(client.closeTerminalSession).toHaveBeenCalledWith(firstOwner);
  expect(screen.getByTestId("active-owner").textContent).toBe(secondOwner);
});
