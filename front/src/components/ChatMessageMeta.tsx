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
  return new Date(parsed).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function ChatMessageMeta({ name, createdAt, align = "left", avatar }: Props) {
  return (
    <div
      className={align === "right"
        ? "mb-1 flex items-center justify-end gap-2 text-xs text-[var(--muted)]"
        : "mb-1 flex items-center gap-2 text-xs text-[var(--muted)]"}
    >
      {align === "left" ? avatar : null}
      <span>{name}</span>
      <span>{formatTime(createdAt)}</span>
      {align === "right" ? avatar : null}
    </div>
  );
}
