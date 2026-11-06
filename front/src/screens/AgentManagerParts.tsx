import type { CSSProperties } from "react";
import { clsx } from "clsx";
import { getBotAccentColor } from "../utils/botVisual";

export type FleetStatus = "running" | "busy" | "unread" | "offline" | "online";

const STATUS_VIEW: Record<FleetStatus, { label: string; tone: string; dot: string }> = {
  online: { label: "在线", tone: "success", dot: "online" },
  running: { label: "运行中", tone: "success", dot: "online" },
  busy: { label: "处理中", tone: "accent", dot: "running" },
  unread: { label: "未读", tone: "info", dot: "info" },
  offline: { label: "离线", tone: "danger", dot: "offline" },
};

/** Soft status chip with a status light; busy breathes with the theme light. */
export function FleetStatusChip({ status }: { status: FleetStatus }) {
  const view = STATUS_VIEW[status];
  return (
    <span className="orbit-chip am-status-chip" data-tone={view.tone}>
      <span aria-hidden="true" className="orbit-dot" data-state={view.dot} />
      {view.label}
    </span>
  );
}

function initialOf(alias: string) {
  const trimmed = alias.trim();
  return trimmed ? Array.from(trimmed)[0] : "?";
}

/** The bot's identity color as a small initial badge. */
export function FleetAvatar({ alias, large = false }: { alias: string; large?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={clsx("am-avatar", large && "am-avatar--lg")}
      style={{ "--am-identity": getBotAccentColor(alias) } as CSSProperties}
    >
      {initialOf(alias)}
    </span>
  );
}

type Stats = { total: number; online: number; busy: number; offline: number };

/** Four glass stat tiles for the cover banner. */
export function FleetStats({ stats }: { stats: Stats }) {
  return (
    <dl className="am-stats" aria-label="智能体统计">
      <div className="am-stat">
        <dt>总数</dt>
        <dd>{stats.total}</dd>
      </div>
      <div className="am-stat" data-tone="online">
        <dt><span aria-hidden="true" className="orbit-dot" data-state={stats.online > 0 ? "online" : undefined} />在线</dt>
        <dd>{stats.online}</dd>
      </div>
      <div className="am-stat" data-tone="busy">
        <dt><span aria-hidden="true" className="orbit-dot" data-state={stats.busy > 0 ? "running" : undefined} />处理中</dt>
        <dd>{stats.busy}</dd>
      </div>
      <div className="am-stat" data-tone="offline" data-empty={stats.offline === 0 ? "true" : "false"}>
        <dt><span aria-hidden="true" className="orbit-dot" data-state={stats.offline > 0 ? "offline" : undefined} />离线</dt>
        <dd>{stats.offline}</dd>
      </div>
    </dl>
  );
}
