import { clsx } from "clsx";

type Props = {
  label: string;
  percent?: number;
  className?: string;
};

/** Without a known percentage the bar stays full and pulses to show the transfer is still running. */
export function TransferProgressBar({ label, percent, className }: Props) {
  const value = typeof percent === "number" && Number.isFinite(percent)
    ? Math.min(100, Math.max(0, Math.round(percent)))
    : undefined;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      className={clsx("overflow-hidden rounded-full bg-[var(--surface-strong)]", className)}
    >
      <div
        className={clsx("h-full rounded-full bg-[var(--accent)] transition-[width]", value === undefined && "animate-pulse")}
        style={{ width: `${value ?? 100}%` }}
      />
    </div>
  );
}
