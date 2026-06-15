import type { BotSummary } from "../services/types";

export function getBotRuntimeLabel(bot: Pick<BotSummary, "cliType" | "supportedExecutionModes" | "defaultExecutionMode" | "executionMode">) {
  const supported = bot.supportedExecutionModes || [];
  const preferred = bot.executionMode || bot.defaultExecutionMode || "";
  if (preferred === "native_agent" || (supported.length === 1 && supported[0] === "native_agent")) {
    return "原生 agent";
  }
  return `CLI / ${bot.cliType || "cli"}`;
}
