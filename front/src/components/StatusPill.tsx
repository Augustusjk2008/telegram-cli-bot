import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

type Props = {
  status: "running" | "busy" | "unread" | "offline" | "online";
  className?: string;
};

export function StatusPill({ status, className }: Props) {
  const statusMap = {
    online: { label: "在线", color: "border-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success)]" },
    running: { label: "运行中", color: "border-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success)]" },
    busy: { label: "处理中", color: "border-[var(--status-warning-border)] bg-[var(--status-warning-bg)] text-[var(--status-warning)]" },
    unread: { label: "未读", color: "border-[var(--status-info-border)] bg-[var(--status-info-bg)] text-[var(--status-info)]" },
    offline: { label: "离线", color: "border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] font-semibold text-[var(--status-danger)]" },
  };

  const config = statusMap[status];

  return (
    <span className={twMerge(clsx("rounded-full border px-1.5 py-0.5 text-xs", config.color), className)}>
      {config.label}
    </span>
  );
}
