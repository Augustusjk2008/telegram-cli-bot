import type { WaveformViewSummary } from "../../../services/types";

type Props = {
  summary: WaveformViewSummary;
  loading: boolean;
  dense: boolean;
  onOpenLogLine?: (line: number) => void;
  onJumpToTime?: (time: number) => void;
};

const statusLabels = { pass: "PASS", fail: "FAIL", unknown: "UNKNOWN" } as const;

export function WaveformStatusPanel({ summary, loading, dense, onOpenLogLine, onJumpToTime }: Props) {
  const log = summary.log;
  const stats = summary.indexStats;
  const status = log?.testStatus || "unknown";
  return (
    <aside className="border-t border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-xs text-[var(--muted)]" data-testid="waveform-status-panel">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <strong className={status === "pass" ? "text-[var(--status-success)]" : status === "fail" ? "text-[var(--danger)]" : "text-[var(--status-warning)]"}>{statusLabels[status]}</strong>
        {log?.testName ? <span>{log.testName}</span> : null}
        <span>{summary.timescale}</span>
        {log?.finishTime != null ? <span>仿真 {log.finishTime}</span> : null}
        {log?.elapsed != null ? <span>耗时 {log.elapsed}</span> : null}
        {stats ? <span>VCD {stats.fileSizeBytes} B · 信号 {stats.declaredSignalCount} · 记录 {stats.recordedSignalCount}</span> : <span>信号 {summary.signals.length}</span>}
        {stats ? <span>{stats.indexCacheHit ? "索引命中" : `索引 ${stats.indexBuildMs} ms`}</span> : null}
        {summary.lodEnabled ? <span>LOD 已启用</span> : null}
        {dense ? <span className="text-[var(--status-warning)]">当前窗口已降采样</span> : null}
        {loading ? <span className="text-[var(--status-info)]">正在加载当前窗口…</span> : null}
      </div>
      {log?.warnings?.length ? <div className="mt-1 text-[var(--status-warning)]">警告：{log.warnings.join("；")}</div> : null}
      {log?.missingSignals?.length ? <div className="mt-1 text-[var(--status-warning)]">未记录信号：{log.missingSignals.join("、")}</div> : null}
      {log?.events?.length ? (
        <div className="mt-2 flex max-h-16 flex-wrap gap-1 overflow-auto" aria-label="日志事件">
          {log.events.map((event) => (
            <button key={event.id} type="button" disabled={event.simTime == null} onClick={() => { if (event.simTime == null) return; onJumpToTime?.(event.simTime); if (event.line) onOpenLogLine?.(event.line); }} className="rounded border border-[var(--border)] px-1.5 py-0.5 text-left hover:bg-[var(--surface)] disabled:cursor-default disabled:opacity-70">
              <span className={event.kind === "pass" ? "text-[var(--status-success)]" : event.kind === "error" || event.kind === "fail" ? "text-[var(--danger)]" : "text-[var(--muted)]"}>{event.kind}</span> {event.message}
            </button>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
