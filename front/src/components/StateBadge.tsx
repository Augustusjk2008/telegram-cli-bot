import { clsx } from "clsx";
import type { ReactNode } from "react";

type Tone = "neutral" | "success" | "warning" | "danger" | "accent";

type Props = {
  tone?: Tone;
  className?: string;
  children: ReactNode;
};

const toneClass: Record<Tone, string> = {
  neutral: "border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] text-[var(--muted)]",
  success: "border-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success)]",
  warning: "border-[var(--status-warning-border)] bg-[var(--status-warning-bg)] text-[var(--status-warning)]",
  danger: "border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] text-[var(--status-danger)]",
  accent: "border-[var(--status-info-border)] bg-[var(--status-info-bg)] text-[var(--status-info)]",
};

export function StateBadge({ tone = "neutral", className, children }: Props) {
  return (
    <span className={clsx("inline-flex items-center rounded-full border px-1.5 py-0.5 text-xs font-medium", toneClass[tone], className)}>
      {children}
    </span>
  );
}
