import { describe, expect, test } from "vitest";
import { buildCreateDraft, resolveDefaultCliPath } from "../screens/useBotManager";
import type { BotSummary } from "../services/types";

function bot(overrides: Partial<BotSummary>): BotSummary {
  return {
    alias: "main",
    cliType: "codex",
    cliPath: "codex",
    botMode: "cli",
    status: "running",
    serviceStatus: "online",
    activityStatus: "idle",
    workingDir: "C:\\workspace\\main",
    lastActiveText: "运行中",
    ...overrides,
  };
}

describe("useBotManager defaults", () => {
  test("resolves create cli path from main env path, existing same cli path, then cli name", () => {
    expect(resolveDefaultCliPath("codex", [
      bot({ alias: "main", isMain: true, cliType: "codex", cliPath: "C:\\tools\\codex.exe" }),
    ])).toBe("C:\\tools\\codex.exe");

    expect(resolveDefaultCliPath("claude", [
      bot({ alias: "main", isMain: true, cliType: "codex", cliPath: "codex" }),
      bot({ alias: "review", cliType: "claude", cliPath: "C:\\tools\\claude.cmd" }),
    ])).toBe("C:\\tools\\claude.cmd");

    expect(resolveDefaultCliPath("kimi", [])).toBe("kimi");
  });

  test("create draft includes the resolved cli path", () => {
    const draft = buildCreateDraft("claude", [
      bot({ alias: "review", cliType: "claude", cliPath: "C:\\tools\\claude.cmd" }),
    ]);

    expect(draft).toMatchObject({
      cliType: "claude",
      cliPath: "C:\\tools\\claude.cmd",
    });
  });
});
