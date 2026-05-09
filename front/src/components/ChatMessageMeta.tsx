import type { ReactNode } from "react";

type Props = {
  name: string;
  createdAt: string;
  align?: "left" | "right";
  avatar?: ReactNode;
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

export function ChatMessageMeta({ name, createdAt, align = "left", avatar }: Props) {
  return (
    <div
      className={align === "right"
        ? "mb-1 flex items-center justify-end gap-2 text-xs"
        : "mb-1 flex items-center gap-2 text-xs"}
    >
      {align === "left" ? avatar : null}
      <span className="max-w-[12rem] truncate text-[var(--text)]">{name}</span>
      <span className="text-[var(--muted)]">{formatTime(createdAt)}</span>
      {align === "right" ? avatar : null}
    </div>
  );
}
