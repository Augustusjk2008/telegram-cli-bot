import { render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { BotSwitcherSheet } from "../components/BotSwitcherSheet";
import { DesktopBotSwitcherPopover } from "../components/DesktopBotSwitcherPopover";
import type { BotSummary } from "../services/types";

function bot(overrides: Partial<BotSummary>): BotSummary {
  return {
    alias: "pi",
    cliType: "codex",
    cliPath: "codex",
    botMode: "cli",
    status: "running",
    serviceStatus: "online",
    activityStatus: "idle",
    workingDir: "C:\\workspace\\pi",
    lastActiveText: "运行中",
    supportedExecutionModes: ["native_agent"],
    defaultExecutionMode: "native_agent",
    executionMode: "native_agent",
    nativeAgent: { provider: "", model: "", piAgent: "" },
    ...overrides,
  };
}

test("desktop bot switcher labels pure native bot as native agent instead of codex", () => {
  render(
    <DesktopBotSwitcherPopover
      bots={[bot({})]}
      currentAlias="pi"
      onSelect={vi.fn()}
      onManage={vi.fn()}
      onClose={vi.fn()}
    />,
  );

  const dialog = screen.getByRole("dialog", { name: "智能体切换" });
  expect(within(dialog).getAllByText("cli · 原生 agent").length).toBeGreaterThan(0);
  expect(within(dialog).queryByText("cli · codex")).not.toBeInTheDocument();
});

test("mobile bot switcher labels pure native bot as native agent instead of codex", () => {
  render(
    <BotSwitcherSheet
      bots={[bot({})]}
      currentAlias="pi"
      onSelect={vi.fn()}
      onManage={vi.fn()}
      onClose={vi.fn()}
    />,
  );

  expect(screen.getByText("原生 agent: C:\\workspace\\pi")).toBeInTheDocument();
  expect(screen.queryByText("codex: C:\\workspace\\pi")).not.toBeInTheDocument();
});
