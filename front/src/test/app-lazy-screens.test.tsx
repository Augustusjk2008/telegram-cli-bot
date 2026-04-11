import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const lazyModuleTracker = vi.hoisted(() => ({
  terminalLoads: 0,
}));

vi.mock("../screens/TerminalScreen", () => {
  lazyModuleTracker.terminalLoads += 1;
  return {
    TerminalScreen: ({ botAlias }: { botAlias: string }) => (
      <main data-testid="terminal-screen-root">终端模块: {botAlias}</main>
    ),
  };
});

beforeEach(() => {
  lazyModuleTracker.terminalLoads = 0;
  localStorage.clear();
  sessionStorage.clear();
  vi.resetModules();
});

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

test("terminal screen module is not loaded before the terminal tab is opened", async () => {
  const { App } = await import("../app/App");
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "终端" });

  expect(lazyModuleTracker.terminalLoads).toBe(0);

  await user.click(screen.getByRole("button", { name: "终端" }));

  expect(await screen.findByTestId("terminal-screen-root")).toHaveTextContent("终端模块: main");
  expect(lazyModuleTracker.terminalLoads).toBe(1);
});
