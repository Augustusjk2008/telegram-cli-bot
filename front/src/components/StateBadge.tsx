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
  success: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warning: "border-yellow-200 bg-yellow-50 text-yellow-700",
  danger: "border-red-200 bg-red-50 text-red-700",
  accent: "border-[var(--workbench-hover-border)] bg-[var(--workbench-active-bg)] text-[var(--accent)]",
};

export function StateBadge({ tone = "neutral", className, children }: Props) {
  return (
    <span className={clsx("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", toneClass[tone], className)}>
      {children}
    </span>
  );
}
