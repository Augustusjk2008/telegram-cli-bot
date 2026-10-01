import { useMemo, useState, type ReactNode } from "react";
import type { WaveformSignalSummary } from "../../../services/types";

export type WaveformSignalTreeNode = {
  id: string;
  label: string;
  scope: boolean;
  signal?: WaveformSignalSummary;
  children: WaveformSignalTreeNode[];
};

export function buildSignalTree(signals: WaveformSignalSummary[]): WaveformSignalTreeNode[] {
  const roots: WaveformSignalTreeNode[] = [];
  for (const signal of signals) {
    const parts = signal.scopeParts?.length ? signal.scopeParts : signal.label.split(".").slice(0, -1);
    const name = signal.name || signal.label.split(".").pop() || signal.label;
    let children = roots;
    let path = "";
    for (const part of parts) {
      path = path ? `${path}.${part}` : part;
      let node = children.find((candidate) => candidate.scope && candidate.id === path);
      if (!node) {
        node = { id: path, label: part, scope: true, children: [] };
        children.push(node);
      }
      children = node.children;
    }
    children.push({ id: signal.signalId, label: name, scope: false, signal, children: [] });
  }
  return roots;
}

type Props = {
  signals: WaveformSignalSummary[];
  selectedSignalIds: string[];
  favoriteSignalIds: string[];
  expandedScopes: string[];
  onToggleSignal: (signalId: string) => void;
  onToggleFavorite: (signalId: string) => void;
  onToggleScope: (scopeId: string) => void;
};

type KindFilter = "all" | "scalar" | "bus";
type RecordFilter = "all" | "recorded" | "unrecorded";
type ActivityFilter = "all" | "changed" | "unchanged";

function signalMatches(
  signal: WaveformSignalSummary,
  query: string,
  kind: KindFilter,
  recorded: RecordFilter,
  activity: ActivityFilter,
  favoritesOnly: boolean,
  favoriteIds: Set<string>,
) {
  const normalizedQuery = query.trim().toLowerCase();
  const isRecorded = signal.recorded !== false;
  const hasActivity = (signal.changeCount ?? (isRecorded ? 1 : 0)) > 0;
  return (!normalizedQuery || `${signal.signalId} ${signal.label} ${signal.name || ""}`.toLowerCase().includes(normalizedQuery))
    && (kind === "all" || signal.kind === kind)
    && (recorded === "all" || (recorded === "recorded" ? isRecorded : !isRecorded))
    && (activity === "all" || (activity === "changed" ? hasActivity : !hasActivity))
    && (!favoritesOnly || favoriteIds.has(signal.signalId));
}

function filterTree(nodes: WaveformSignalTreeNode[], predicate: (signal: WaveformSignalSummary) => boolean): WaveformSignalTreeNode[] {
  return nodes.flatMap((node) => {
    if (node.signal) return predicate(node.signal) ? [node] : [];
    const children = filterTree(node.children, predicate);
    return children.length ? [{ ...node, children }] : [];
  });
}

export function WaveformSignalNavigator({
  signals,
  selectedSignalIds,
  favoriteSignalIds,
  expandedScopes,
  onToggleSignal,
  onToggleFavorite,
  onToggleScope,
}: Props) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [recorded, setRecorded] = useState<RecordFilter>("all");
  const [activity, setActivity] = useState<ActivityFilter>("all");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const selected = useMemo(() => new Set(selectedSignalIds), [selectedSignalIds]);
  const favorites = useMemo(() => new Set(favoriteSignalIds), [favoriteSignalIds]);
  const tree = useMemo(() => filterTree(
    buildSignalTree(signals),
    (signal) => signalMatches(signal, query, kind, recorded, activity, favoritesOnly, favorites),
  ), [activity, favorites, favoritesOnly, kind, query, recorded, signals]);
  const showFilteredScopes = Boolean(query.trim()) || kind !== "all" || recorded !== "all" || activity !== "all" || favoritesOnly;

  const renderNode = (node: WaveformSignalTreeNode, depth: number): ReactNode => {
    if (node.signal) {
      const signal = node.signal;
      const isRecorded = signal.recorded !== false;
      return (
        <div key={node.id} className="flex min-w-0 items-center gap-1 py-1" style={{ paddingLeft: depth * 12 }} data-testid="waveform-signal-row">
          <input
            type="checkbox"
            aria-label={`加载 ${signal.signalId}`}
            checked={selected.has(signal.signalId)}
            onChange={() => onToggleSignal(signal.signalId)}
            className="accent-[var(--accent)]"
          />
          <button type="button" className="min-w-0 flex-1 truncate text-left text-xs text-[var(--text)]" onClick={() => onToggleSignal(signal.signalId)} title={signal.signalId}>
            {node.label}
          </button>
          <span className="shrink-0 text-[10px] text-[var(--muted)]">{signal.width}b</span>
          {signal.changeCount != null ? <span className="shrink-0 text-[10px] text-[var(--muted)]">{signal.changeCount}</span> : null}
          {!isRecorded ? <span title="未记录" aria-label="未记录" className="shrink-0 text-[var(--status-warning)]">⚠</span> : null}
          <button type="button" aria-label={`${favorites.has(signal.signalId) ? "取消" : "添加"}收藏 ${signal.signalId}`} onClick={() => onToggleFavorite(signal.signalId)} className="shrink-0 px-1 text-xs text-[var(--muted)] hover:text-[var(--accent)]">
            {favorites.has(signal.signalId) ? "★" : "☆"}
          </button>
        </div>
      );
    }
    const expanded = showFilteredScopes || expandedScopes.includes(node.id);
    return (
      <div key={node.id}>
        <button type="button" onClick={() => onToggleScope(node.id)} className="flex w-full items-center gap-1 py-1 text-left text-xs font-medium text-[var(--muted)]" style={{ paddingLeft: depth * 12 }} aria-expanded={expanded}>
          <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
          <span className="truncate">{node.label}</span>
        </button>
        {expanded ? node.children.map((child) => renderNode(child, depth + 1)) : null}
      </div>
    );
  };

  return (
    <aside className="flex min-h-0 min-w-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] p-2" data-testid="waveform-signal-navigator">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold text-[var(--text)]">信号 ({signals.length})</h3>
        <button type="button" onClick={() => setFavoritesOnly((value) => !value)} aria-pressed={favoritesOnly} className="text-xs text-[var(--muted)] hover:text-[var(--accent)]">★ 收藏</button>
      </div>
      <input value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder="搜索信号" aria-label="搜索信号" className="mb-2 h-8 rounded border border-[var(--border)] bg-[var(--surface-strong)] px-2 text-xs text-[var(--text)]" />
      <div className="mb-2 grid grid-cols-3 gap-1">
        <select aria-label="信号类型" value={kind} onChange={(event) => setKind(event.currentTarget.value as KindFilter)} className="h-7 min-w-0 rounded border border-[var(--border)] bg-[var(--surface-strong)] px-1 text-[10px] text-[var(--text)]">
          <option value="all">全部类型</option><option value="scalar">标量</option><option value="bus">总线</option>
        </select>
        <select aria-label="记录状态" value={recorded} onChange={(event) => setRecorded(event.currentTarget.value as RecordFilter)} className="h-7 min-w-0 rounded border border-[var(--border)] bg-[var(--surface-strong)] px-1 text-[10px] text-[var(--text)]">
          <option value="all">全部记录</option><option value="recorded">有记录</option><option value="unrecorded">未记录</option>
        </select>
        <select aria-label="活动状态" value={activity} onChange={(event) => setActivity(event.currentTarget.value as ActivityFilter)} className="h-7 min-w-0 rounded border border-[var(--border)] bg-[var(--surface-strong)] px-1 text-[10px] text-[var(--text)]">
          <option value="all">全部活动</option><option value="changed">有变化</option><option value="unchanged">无变化</option>
        </select>
      </div>
      <div className="min-h-0 flex-1 overflow-auto" data-testid="waveform-signal-tree">
        {tree.length ? tree.map((node) => renderNode(node, 0)) : <p className="p-2 text-xs text-[var(--muted)]">没有匹配信号</p>}
      </div>
    </aside>
  );
}
