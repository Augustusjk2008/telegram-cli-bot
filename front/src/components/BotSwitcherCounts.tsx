import type { BotSummary } from "../services/types";

export function BotSwitcherCounts({ bots }: { bots: BotSummary[] }) {
  const archived = bots.filter((bot) => bot.archived === true).length;
  const offline = bots.filter((bot) => bot.archived !== true
    && (bot.serviceStatus === "offline" || bot.status === "offline")).length;
  const online = bots.length - archived - offline;

  return (
    <span className="shrink-0 whitespace-nowrap text-xs text-[var(--muted)]">
      在线 {online} / 离线 {offline} / 归档 {archived}
    </span>
  );
}
