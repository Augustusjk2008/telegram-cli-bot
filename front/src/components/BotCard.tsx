import { BotSummary } from "../services/types";
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
      <div className="flex justify-between items-center mb-2">
        <h3 className="font-semibold text-lg">{bot.alias}</h3>
        <StatusPill status={bot.status} />
      </div>
      <div className="text-sm text-[var(--muted)] space-y-1">
        <p>类型: {bot.cliType}</p>
        <p className="truncate">目录: {bot.workingDir}</p>
        <p>最后活跃: {bot.lastActiveText}</p>
      </div>
    </button>
  );
}
