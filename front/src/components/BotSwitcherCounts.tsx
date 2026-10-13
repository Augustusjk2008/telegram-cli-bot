import type { BotSummary } from "../services/types";

export function BotSwitcherCounts({ bots }: { bots: BotSummary[] }) {
  const archived = bots.filter((bot) => bot.archived === true).length;
  const stopped = bots.filter((bot) => bot.archived !== true
    && (bot.serviceStatus === "offline" || bot.status === "offline")).length;
  const running = bots.length - archived - stopped;

  return (
    <span className="shrink-0 whitespace-nowrap text-xs text-[var(--muted)]">
      运行 {running} / 停止 {stopped} / 归档 {archived}
    </span>
  );
}
