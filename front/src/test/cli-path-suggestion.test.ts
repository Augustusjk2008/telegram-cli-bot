import { expect, test } from "vitest";
import { suggestCliPath } from "../utils/cliType";

const current = { alias: "worker", cliType: "codex", cliPath: "/opt/codex/bin/codex" };

test("switching CLI reuses another agent's path, preferring the main agent's explicit path", () => {
  const bots = [
    current,
    { alias: "reviewer", cliType: "claude", cliPath: "claude" },
    { alias: "writer", cliType: "claude", cliPath: "/home/me/.local/bin/claude" },
    { alias: "main", cliType: "claude", cliPath: "C:\\tools\\claude.cmd", isMain: true },
  ];
  expect(suggestCliPath("claude", bots, current)).toBe("C:\\tools\\claude.cmd");
  expect(suggestCliPath("claude", bots.filter((bot) => bot.alias !== "main"), current)).toBe("/home/me/.local/bin/claude");
});

test("switching CLI falls back to the default command and restores the agent's own saved path", () => {
  const bots = [current, { alias: "main", cliType: "codex", cliPath: "codex", isMain: true }];
  expect(suggestCliPath("claude", bots, current)).toBe("claude");
  expect(suggestCliPath("antigravity", bots, current)).toBe("agy");
  expect(suggestCliPath("codex", bots, current)).toBe("/opt/codex/bin/codex");
});

test("codex and codex server share one executable path", () => {
  expect(suggestCliPath("codex_server", [current], current)).toBe("/opt/codex/bin/codex");
  const claudeAgent = { alias: "reviewer", cliType: "claude", cliPath: "claude" };
  expect(suggestCliPath("codex_server", [claudeAgent, current], claudeAgent)).toBe("/opt/codex/bin/codex");
});
