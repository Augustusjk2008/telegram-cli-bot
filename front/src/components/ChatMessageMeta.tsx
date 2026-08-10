import type { ChatMessageContextUsage } from "../services/types";
import { ChatContextUsageBadge } from "./ChatContextUsageBadge";

type Props = {
  name: string;
  createdAt: string;
  align?: "left" | "right";
  contextUsage?: ChatMessageContextUsage;
};

function formatTime(createdAt: string) {
  const parsed = Date.parse(createdAt);
  if (Number.isNaN(parsed)) {
    return "--:--";
  }
  const createdDate = new Date(parsed);
  const timeText = createdDate.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const now = new Date();
  const isSameDay = createdDate.getFullYear() === now.getFullYear()
    && createdDate.getMonth() === now.getMonth()
    && createdDate.getDate() === now.getDate();
  if (isSameDay) {
    return timeText;
  }
  const dateText = createdDate.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return `${dateText} ${timeText}`;
}

export function ChatMessageMeta({ name, createdAt, align = "left", contextUsage }: Props) {
  return (
    <div
      className={align === "right"
        ? "mb-1.5 flex min-w-0 items-center justify-end gap-2 text-xs"
        : "mb-1.5 flex min-w-0 items-center gap-2 text-xs"}
    >
      <span
        className={align === "left"
          ? "min-w-0 max-w-[12rem] truncate text-sm font-semibold text-[var(--text)]"
          : "min-w-0 max-w-[12rem] truncate font-medium text-[var(--text)]"}
      >
        {name}
      </span>
      <span className="shrink-0 text-[var(--muted)]">{formatTime(createdAt)}</span>
      <ChatContextUsageBadge contextUsage={contextUsage} testId="chat-message-context-usage-text" />
    </div>
  );
}
