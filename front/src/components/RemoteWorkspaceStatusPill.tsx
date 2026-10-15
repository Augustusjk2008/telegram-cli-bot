import { clsx } from "clsx";
import type { RemoteWorkspaceConnectionStatus } from "../services/types";

type Props = {
  status: RemoteWorkspaceConnectionStatus;
  className?: string;
};

export function RemoteWorkspaceStatusPill({ status, className }: Props) {
  const connected = status === "connected";
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] leading-none",
        connected
          ? "border-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success)]"
          : "border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] font-semibold text-[var(--status-danger)]",
        className,
      )}
    >
      ssh
    </span>
  );
}
