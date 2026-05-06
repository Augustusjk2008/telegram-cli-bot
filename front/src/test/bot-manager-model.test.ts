import { describe, expect, test } from "vitest";
import {
  buildBulkActionPlan,
  detectBotIssues,
  getBotConfigSnapshot,
  getVisibleManagedBots,
  isBotOffline,
  isMainBot,
  type ManagerViewFilter,
} from "../screens/botManagerModel";
import type { BotSummary } from "../services/types";

function bot(input: Partial<BotSummary> & { alias: string }): BotSummary {
  return {
    alias: input.alias,
    cliType: input.cliType || "codex",
    cliPath: input.cliPath,
    botMode: input.botMode || "cli",
    status: input.status || "running",
    serviceStatus: input.serviceStatus || "online",
    activityStatus: input.activityStatus || "idle",
    busyAgentIds: input.busyAgentIds,
    busyAgentNames: input.busyAgentNames,
    busyAgentCount: input.busyAgentCount,
    workingDir: input.workingDir ?? `C:\\workspace\\${input.alias}`,
    lastActiveText: input.lastActiveText || "运行中",
    agents: input.agents,
    isMain: input.isMain,
    avatarName: input.avatarName,
  };
}

describe("botManagerModel", () => {
  const bots: BotSummary[] = [
    bot({ alias: "main", isMain: true, workingDir: "C:\\workspace\\main", cliPath: "codex" }),
    bot({
      alias: "review",
      status: "busy",
      activityStatus: "busy",
      busyAgentNames: ["代码审查"],
      busyAgentCount: 1,
      workingDir: "C:\\workspace\\shared",
      cliPath: "claude",
      cliType: "claude",
      agents: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true, isProcessing: true },
        { id: "reviewer", name: "代码审查", systemPrompt: "", enabled: true, isMain: false, isProcessing: true },
      ],
    }),
    bot({
      alias: "offline-team",
      status: "offline",
      serviceStatus: "offline",
      workingDir: "C:\\workspace\\offline",
      cliPath: "codex",
    }),
    bot({
      alias: "duplicate-a",
      workingDir: "C:\\workspace\\shared",
      cliPath: "",
      status: "unread",
    }),
  ];

  test("detects offline, busy, unread, duplicate workdir, and empty explicit cliPath", () => {
    expect(isMainBot(bots[0])).toBe(true);
    expect(isBotOffline(bots[2])).toBe(true);

    expect(detectBotIssues(bots[1], bots).map((issue) => issue.code)).toEqual([
      "busy",
      "duplicate_workdir",
    ]);
    expect(detectBotIssues(bots[2], bots).map((issue) => issue.code)).toEqual(["offline"]);
    expect(detectBotIssues(bots[3], bots).map((issue) => issue.code)).toEqual([
      "unread",
      "missing_cli_path",
      "duplicate_workdir",
    ]);
  });

  test("filters attention bots with stable sort", () => {
    const aliases = getVisibleManagedBots({
      bots,
      query: "",
      filter: "attention" satisfies ManagerViewFilter,
    }).map((item) => item.alias);

    expect(aliases).toEqual(["duplicate-a", "review", "offline-team"]);
  });

  test("matches query against busy agent names", () => {
    const aliases = getVisibleManagedBots({
      bots,
      query: "代码审查",
      filter: "all",
    }).map((item) => item.alias);

    expect(aliases).toEqual(["review"]);
  });

  test("builds bulk action plans and skips unsafe targets", () => {
    expect(buildBulkActionPlan("start", bots).targets.map((item) => item.alias)).toEqual(["offline-team"]);
    expect(buildBulkActionPlan("stop", bots).targets.map((item) => item.alias)).toEqual([
      "review",
      "duplicate-a",
    ]);
    expect(buildBulkActionPlan("delete", bots).targets.map((item) => item.alias)).toEqual([
      "review",
      "offline-team",
      "duplicate-a",
    ]);
    expect(buildBulkActionPlan("delete", bots).skipped).toEqual([
      { alias: "main", reason: "主 bot 不可删除" },
    ]);
  });

  test("creates config snapshots for future clone and diff features", () => {
    expect(getBotConfigSnapshot(bots[1])).toMatchObject({
      alias: "review",
      botMode: "cli",
      cliType: "claude",
      cliPath: "claude",
      workingDir: "C:\\workspace\\shared",
      agents: [
        { id: "main", name: "主 agent" },
        { id: "reviewer", name: "代码审查" },
      ],
    });
  });
});
