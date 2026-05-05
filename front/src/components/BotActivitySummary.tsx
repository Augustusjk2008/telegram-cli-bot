import { LoaderCircle } from "lucide-react";
import type { BotSummary } from "../services/types";

type Props = {
  bot: BotSummary;
  className?: string;
};

export function getBotActivityText(bot: BotSummary): string {
  const count = Math.max(
    bot.busyAgentCount ?? 0,
    bot.busyAgentIds?.length ?? 0,
    bot.busyAgentNames?.length ?? 0,
  );
  if (count <= 0 && bot.activityStatus !== "busy" && bot.status !== "busy") {
    return "全部空闲";
  }
  if (count <= 0) {
    return "任务处理中";
  }
  const names = bot.busyAgentNames || [];
  if (count === 1) {
    return `${names[0] || "agent"} 处理中`;
  }
  return `${count} 个 agent 处理中`;
}

export function BotActivitySummary({ bot, className = "" }: Props) {
  const count = Math.max(
    bot.busyAgentCount ?? 0,
    bot.busyAgentIds?.length ?? 0,
    bot.busyAgentNames?.length ?? 0,
  );
  const busy = count > 0 || bot.activityStatus === "busy" || bot.status === "busy";
  const text = getBotActivityText(bot);

  return (
    <div className={`inline-flex min-h-5 items-center gap-1.5 text-xs ${busy ? "text-amber-700" : "text-[var(--muted)]"} ${className}`}>
      {busy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : null}
      <span>{text}</span>
    </div>
  );
}
