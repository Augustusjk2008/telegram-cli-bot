import { cliTypeLabel } from "../utils/cliType";
import type { BotSummary } from "../services/types";

export function getBotRuntimeLabel(bot: Pick<BotSummary, "cliType">) {
  return `CLI / ${cliTypeLabel(bot.cliType || "cli")}`;
}
