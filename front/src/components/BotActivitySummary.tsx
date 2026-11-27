import { LoaderCircle } from "lucide-react";
import type { BotSummary } from "../services/types";
import { getBusyActivityNames, isBotBusy } from "../app/botActivity";

type Props = {
  bot: BotSummary;
  className?: string;
  showLatestAnswerTime?: boolean;
};

function formatLatestAnswerTime(value: string | undefined) {
  if (!value) {
    return "暂无回答";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "暂无回答";
  }
  return `上次回答 ${date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })}`;
}

export function BotActivitySummary({ bot, className = "", showLatestAnswerTime = false }: Props) {
  if (!isBotBusy(bot)) {
    return <span className={`inline-flex min-h-5 items-center text-xs text-[var(--muted)] ${className}`}>
      {showLatestAnswerTime ? formatLatestAnswerTime(bot.lastAnswerCompletedAt) : "全部空闲"}
    </span>;
  }
  return (
    <span className={`inline-flex min-h-5 min-w-0 max-w-full flex-wrap items-center gap-1 text-xs ${className}`}>
      <span className="inline-flex shrink-0 items-center gap-1 text-[var(--feedback-warning-text-deep)]">
        <LoaderCircle aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />处理中
      </span>
      {getBusyActivityNames(bot).map((name, index) => (
        <span key={`${index}-${name}`} className="min-w-0 max-w-full rounded border border-[var(--feedback-warning-border-light)] bg-[var(--feedback-warning-background-subtle)] px-1.5 py-0.5 text-[var(--text)] [overflow-wrap:anywhere]">
          {name}
        </span>
      ))}
    </span>
  );
}
