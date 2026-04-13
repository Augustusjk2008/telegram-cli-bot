type Props = {
  name: string;
  createdAt: string;
  align?: "left" | "right";
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

export function ChatMessageMeta({ name, createdAt, align = "left" }: Props) {
  return (
    <div className={align === "right" ? "mb-1 flex justify-end gap-2 text-xs text-[var(--muted)]" : "mb-1 flex gap-2 text-xs text-[var(--muted)]"}>
      <span>{name}</span>
      <span>{formatTime(createdAt)}</span>
    </div>
  );
}

