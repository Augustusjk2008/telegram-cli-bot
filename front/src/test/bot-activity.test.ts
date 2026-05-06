import { expect, test } from "vitest";
import type { BotSummary } from "../services/types";
import {
  applyBotActivityOverrides,
  updateBotAgentActivityOverrides,
  type BotAgentActivityOverrides,
} from "../app/botActivity";

function bot(overrides: Partial<BotSummary> = {}): BotSummary {
  return {
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    lastActiveText: "运行中",
    serviceStatus: "online",
    activityStatus: "idle",
    busyAgentIds: [],
    busyAgentNames: [],
    busyAgentCount: 0,
    ...overrides,
  };
}

test("merges backend busy agents with local busy override", () => {
  const overrides: BotAgentActivityOverrides = {
    main: {
      reviewer: { name: "代码审查", busy: true, updatedAt: 1000 },
    },
  };

  const [merged] = applyBotActivityOverrides([
    bot({
      status: "busy",
      activityStatus: "busy",
      busyAgentIds: ["main"],
      busyAgentNames: ["主 agent"],
      busyAgentCount: 1,
      lastActiveText: "处理中",
    }),
  ], overrides, 1000);

  expect(merged.status).toBe("busy");
  expect(merged.activityStatus).toBe("busy");
  expect(merged.busyAgentIds).toEqual(["main", "reviewer"]);
  expect(merged.busyAgentNames).toEqual(["主 agent", "代码审查"]);
  expect(merged.busyAgentCount).toBe(2);
  expect(merged.lastActiveText).toBe("处理中");
});

test("idle patch removes only the same local agent", () => {
  const busy = updateBotAgentActivityOverrides({}, "main", {
    activityStatus: "busy",
    agentId: "reviewer",
    agentName: "代码审查",
    busyAgentIds: ["reviewer"],
    busyAgentNames: ["代码审查"],
    busyAgentCount: 1,
  }, 1000);

  const idle = updateBotAgentActivityOverrides(busy, "main", {
    activityStatus: "idle",
    agentId: "reviewer",
    agentName: "代码审查",
    busyAgentIds: [],
    busyAgentNames: [],
    busyAgentCount: 0,
  }, 1200);

  expect(idle).toEqual({});
});

test("local idle does not clear backend busy agents", () => {
  const [merged] = applyBotActivityOverrides([
    bot({
      status: "busy",
      activityStatus: "busy",
      busyAgentIds: ["main"],
      busyAgentNames: ["主 agent"],
      busyAgentCount: 1,
      lastActiveText: "处理中",
    }),
  ], {}, 1000);

  expect(merged.busyAgentIds).toEqual(["main"]);
  expect(merged.busyAgentNames).toEqual(["主 agent"]);
  expect(merged.busyAgentCount).toBe(1);
});

test("falls back to main agent when backend only reports busy status", () => {
  const [merged] = applyBotActivityOverrides([
    bot({
      status: "busy",
      activityStatus: "busy",
      busyAgentIds: [],
      busyAgentNames: [],
      busyAgentCount: 0,
      lastActiveText: "处理中",
    }),
  ], {}, 1000);

  expect(merged.status).toBe("busy");
  expect(merged.activityStatus).toBe("busy");
  expect(merged.busyAgentIds).toEqual(["main"]);
  expect(merged.busyAgentNames).toEqual(["主 agent"]);
  expect(merged.busyAgentCount).toBe(1);
  expect(merged.lastActiveText).toBe("处理中");
});

test("ignores stale local busy override", () => {
  const overrides: BotAgentActivityOverrides = {
    main: {
      reviewer: { name: "代码审查", busy: true, updatedAt: 0 },
    },
  };

  const [merged] = applyBotActivityOverrides([bot()], overrides, 3 * 60 * 1000);

  expect(merged.status).toBe("running");
  expect(merged.activityStatus).toBe("idle");
  expect(merged.busyAgentIds).toEqual([]);
  expect(merged.busyAgentNames).toEqual([]);
  expect(merged.busyAgentCount).toBe(0);
});
