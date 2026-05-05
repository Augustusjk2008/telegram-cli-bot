import { BotSummary } from "../services/types";
import { BotActivitySummary } from "./BotActivitySummary";
import { StatusPill } from "./StatusPill";

type Props = {
  bot: BotSummary;
  onClick: () => void;
};

export function BotCard({ bot, onClick }: Props) {
  return (
    <button 
      onClick={onClick}
      className="w-full text-left bg-[var(--surface)] p-4 rounded-xl shadow-sm border border-[var(--border)] active:scale-[0.98] transition-transform"
    >
      <div className="flex justify-between items-center gap-3 mb-2">
        <h3 className="font-semibold text-lg">{bot.alias}</h3>
        <div className="flex shrink-0 items-center gap-1">
          {bot.status === "unread" ? <StatusPill status="unread" /> : null}
          <StatusPill status={bot.serviceStatus === "offline" || bot.status === "offline" ? "offline" : "online"} />
        </div>
      </div>
      <div className="text-sm text-[var(--muted)] space-y-1">
        <p>类型: {bot.cliType}</p>
        <p className="truncate">目录: {bot.workingDir}</p>
        <BotActivitySummary bot={bot} />
      </div>
    </button>
  );
}
