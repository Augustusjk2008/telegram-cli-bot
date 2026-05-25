import type { ReactNode } from "react";
import type { ChatMessageContextUsage } from "../services/types";

type Props = {
  name: string;
  createdAt: string;
  align?: "left" | "right";
  avatar?: ReactNode;
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

function formatContextUsage(contextUsage?: ChatMessageContextUsage) {
  if (!contextUsage) {
    return null;
  }
  const percent = typeof contextUsage.contextLeftPercent === "number"
    ? `${contextUsage.contextLeftPercent}% left`
    : "";
  const usage = contextUsage.usedDisplay && contextUsage.windowDisplay
    ? `${contextUsage.usedDisplay} / ${contextUsage.windowDisplay}`
    : "";
  const text = (contextUsage.statusText || [percent, usage].filter(Boolean).join(" · "))
    .replace(/\bcontext left\b/g, "left");
  if (!text) {
    return null;
  }
  const title = contextUsage.usedDisplay && contextUsage.windowDisplay
    ? `${contextUsage.usedDisplay} used / ${contextUsage.windowDisplay} window`
    : text;
  return { text, title, isLow: typeof contextUsage.contextLeftPercent === "number" && contextUsage.contextLeftPercent < 25 };
}

export function ChatMessageMeta({ name, createdAt, align = "left", avatar, contextUsage }: Props) {
  const context = formatContextUsage(contextUsage);
  return (
    <div
      className={align === "right"
        ? "mb-1 flex items-center justify-end gap-2 text-xs"
        : "mb-1 flex items-center gap-2 text-xs"}
    >
      {align === "left" ? avatar : null}
      <span className="max-w-[12rem] truncate text-[var(--text)]">{name}</span>
      <span className="text-[var(--muted)]">{formatTime(createdAt)}</span>
      {context ? (
        <span
          className={context.isLow ? "font-medium text-red-600" : "text-[var(--muted)]"}
          title={context.title}
        >
          {context.text}
        </span>
      ) : null}
      {align === "right" ? avatar : null}
    </div>
  );
}
