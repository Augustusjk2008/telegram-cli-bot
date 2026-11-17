import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type {
  CostStats,
  CostStatsConfig,
  CostStatsGranularity,
  CostStatsProvider,
} from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { getErrorMessage } from "../../utils/errorMessage";
import {
  COST_GROUP_DIMENSIONS,
  buildCostView,
  costAxisScale,
  costCurrencies,
  costDimensionLabel,
  costRangeDays,
  formatCostAmount,
  formatCostBucket,
  type CostGroupDimension,
  type CostSeries,
  type CostView,
} from "./costStatsModel";
// The shell (tabs, toolbar, date form, alerts) shares the Usage panel's look.
import "./UsagePanel.css";
import "./CostPanel.css";

type CostPanelProps = {
  client: WebBotClient;
  refreshKey?: number;
};

const PROVIDERS: readonly CostStatsProvider[] = ["codex", "claude"];
const PROVIDER_LABELS: Record<CostStatsProvider, string> = { codex: "Codex", claude: "Claude" };

type QuickRangeKey = "today" | "7d" | "30d" | "90d" | "all";
const QUICK_RANGES: readonly { key: QuickRangeKey; label: string; days: number | null }[] = [
  { key: "today", label: "今天", days: 1 },
  { key: "7d", label: "近 7 天", days: 7 },
  { key: "30d", label: "近 30 天", days: 30 },
  { key: "90d", label: "近 90 天", days: 90 },
  { key: "all", label: "全部", days: null },
];
const DEFAULT_QUICK_RANGE: QuickRangeKey = "30d";

type GranularityChoice = CostStatsGranularity | "auto";
const GRANULARITIES: readonly { key: GranularityChoice; label: string }[] = [
  { key: "auto", label: "自动" },
  { key: "hour", label: "时" },
  { key: "day", label: "日" },
  { key: "week", label: "周" },
  { key: "month", label: "月" },
];
const GRANULARITY_LABELS: Record<CostStatsGranularity, string> = { hour: "小时", day: "天", week: "周", month: "月" };

const RANKING_PREVIEW = 8;
const numberFormat = new Intl.NumberFormat("zh-CN");
const percentFormat = new Intl.NumberFormat("zh-CN", { style: "percent", maximumFractionDigits: 1 });

function formatDateValue(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function subtractDays(dateText: string, days: number) {
  const time = Date.parse(`${dateText}T00:00:00Z`);
  return Number.isFinite(time) ? new Date(time - days * 86_400_000).toISOString().slice(0, 10) : "";
}

function rangeForDays(today: string, days: number) {
  const endDate = today || formatDateValue(new Date());
  return { startDate: subtractDays(endDate, Math.max(0, days - 1)) || endDate, endDate };
}

function useMeasuredWidth(fallback: number) {
  const [width, setWidth] = useState(fallback);
  const observerRef = useRef<ResizeObserver | null>(null);
  const ref = useCallback((node: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node || typeof ResizeObserver === "undefined") return;
    const update = () => {
      const next = Math.round(node.clientWidth);
      if (next > 0) setWidth(Math.max(280, next));
    };
    update();
    observerRef.current = new ResizeObserver(update);
    observerRef.current.observe(node);
  }, []);
  return { width, ref };
}

function Swatch({ slot }: { slot: number }) {
  return <span className="cost-stats-swatch" data-slot={slot} aria-hidden="true" />;
}

/* ------------------------------------------------------------------ chart */

const CHART_HEIGHT = 248;
const CHART_MARGIN = { top: 10, right: 8, bottom: 24, left: 48 };
const BAR_MAX_WIDTH = 24;
const SEGMENT_GAP = 2;

function topRoundedBar(x: number, y: number, width: number, height: number, radius: number) {
  const r = Math.max(0, Math.min(radius, width / 2, height));
  return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
}

function CostTrendChart({
  view,
  granularity,
  currency,
  dimensionLabel,
}: {
  view: CostView;
  granularity: CostStatsGranularity;
  currency: string;
  dimensionLabel: string;
}) {
  const { width, ref } = useMeasuredWidth(720);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const bucketCount = view.buckets.length;
  const plotWidth = Math.max(1, width - CHART_MARGIN.left - CHART_MARGIN.right);
  const plotHeight = CHART_HEIGHT - CHART_MARGIN.top - CHART_MARGIN.bottom;
  const band = plotWidth / Math.max(1, bucketCount);
  const barWidth = Math.max(1.5, Math.min(BAR_MAX_WIDTH, band * 0.64));
  const scale = useMemo(() => costAxisScale(Math.max(0, ...view.bucketTotals)), [view.bucketTotals]);
  const y = (value: number) => CHART_MARGIN.top + plotHeight * (1 - value / scale.max);
  const labelStep = Math.max(1, Math.ceil(bucketCount / Math.max(1, Math.floor(plotWidth / 58))));
  const active = activeIndex !== null && activeIndex < bucketCount ? activeIndex : null;

  const indexFromPointer = (event: PointerEvent<SVGRectElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = bounds.width > 0 ? (event.clientX - bounds.left) / bounds.width : 0;
    return Math.max(0, Math.min(bucketCount - 1, Math.floor(ratio * bucketCount)));
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!bucketCount) return;
    const current = active ?? bucketCount - 1;
    let next: number;
    if (event.key === "ArrowLeft") next = Math.max(0, current - 1);
    else if (event.key === "ArrowRight") next = Math.min(bucketCount - 1, current + 1);
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = bucketCount - 1;
    else if (event.key === "Escape") { setActiveIndex(null); return; }
    else return;
    event.preventDefault();
    setActiveIndex(next);
  };

  const activeCenter = active === null ? 0 : CHART_MARGIN.left + band * (active + 0.5);
  const activeSeries = active === null ? [] : view.series.filter((series) => series.values[active] > 0);

  return (
    <div
      ref={ref}
      className="cost-stats-chart"
      role="group"
      tabIndex={0}
      aria-label={`按${dimensionLabel}堆叠的费用趋势，共 ${bucketCount} 个时间段。使用左右方向键逐段查看。`}
      onKeyDown={handleKeyDown}
      onFocus={() => setActiveIndex((current) => current ?? Math.max(0, bucketCount - 1))}
      onBlur={() => setActiveIndex(null)}
    >
      <svg width={width} height={CHART_HEIGHT} viewBox={`0 0 ${width} ${CHART_HEIGHT}`} aria-hidden="true">
        {scale.ticks.map((tick, index) => (
          <g key={tick}>
            <line
              className={index === 0 ? "cost-stats-axis" : "cost-stats-grid"}
              x1={CHART_MARGIN.left}
              x2={width - CHART_MARGIN.right}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text className="cost-stats-tick" x={CHART_MARGIN.left - 6} y={y(tick)} dy="0.32em" textAnchor="end">
              {formatCostAmount(tick, currency, { compact: true })}
            </text>
          </g>
        ))}
        {active !== null ? (
          <rect
            className="cost-stats-band"
            x={CHART_MARGIN.left + band * active}
            y={CHART_MARGIN.top}
            width={band}
            height={plotHeight}
          />
        ) : null}
        {view.buckets.map((bucket, bucketIndex) => {
          const x = CHART_MARGIN.left + band * (bucketIndex + 0.5) - barWidth / 2;
          const stacked = view.series.filter((series) => series.values[bucketIndex] > 0);
          let offset = 0;
          return (
            <g key={bucket} data-active={active === bucketIndex || undefined} className="cost-stats-bar">
              {stacked.map((series, order) => {
                const value = series.values[bucketIndex];
                const top = y(offset + value);
                const bottom = y(offset);
                offset += value;
                // 相邻分段之间留出与底色同色的缝，靠留白而不是描边区分。
                const gap = order > 0 && bottom - top > SEGMENT_GAP + 1 ? SEGMENT_GAP : 0;
                const height = Math.max(1, bottom - top - gap);
                const isTop = order === stacked.length - 1;
                return isTop ? (
                  <path key={series.key} data-slot={series.slot} d={topRoundedBar(x, top, barWidth, height, 4)} />
                ) : (
                  <rect key={series.key} data-slot={series.slot} x={x} y={top} width={barWidth} height={height} />
                );
              })}
            </g>
          );
        })}
        {view.buckets.map((bucket, index) => (
          index % labelStep === 0 ? (
            <text
              key={bucket}
              className="cost-stats-tick"
              x={CHART_MARGIN.left + band * (index + 0.5)}
              y={CHART_HEIGHT - 7}
              textAnchor="middle"
            >
              {formatCostBucket(bucket, granularity)}
            </text>
          ) : null
        ))}
        <rect
          className="cost-stats-hit"
          x={CHART_MARGIN.left}
          y={CHART_MARGIN.top}
          width={plotWidth}
          height={plotHeight}
          onPointerMove={(event) => setActiveIndex(indexFromPointer(event))}
          onPointerLeave={() => setActiveIndex(null)}
        />
      </svg>
      {active !== null ? (
        <div
          className="cost-stats-tooltip"
          role="status"
          data-align={activeCenter > width / 2 ? "end" : "start"}
          style={{ left: activeCenter, top: CHART_MARGIN.top + 8 }}
        >
          <time>{formatCostBucket(view.buckets[active], granularity, "full")}</time>
          <strong>{formatCostAmount(view.bucketTotals[active], currency)}</strong>
          {activeSeries.length > 1 || (activeSeries.length === 1 && view.series.length > 1) ? (
            <ul>
              {activeSeries.map((series) => (
                <li key={series.key}>
                  <span className="cost-stats-line-key" data-slot={series.slot} aria-hidden="true" />
                  <span>{series.label}</span>
                  <b>{formatCostAmount(series.values[active], currency)}</b>
                </li>
              ))}
            </ul>
          ) : null}
          {!activeSeries.length ? <span>无费用记录</span> : null}
        </div>
      ) : null}
    </div>
  );
}

function CostTrendTable({
  view,
  granularity,
  currency,
}: {
  view: CostView;
  granularity: CostStatsGranularity;
  currency: string;
}) {
  const indexes = view.buckets.map((_, index) => index).filter((index) => view.bucketTotals[index] > 0);
  return (
    <div className="cost-stats-table-scroll">
      <table className="cost-stats-table">
        <thead>
          <tr>
            <th scope="col">时间</th>
            {view.series.map((series) => <th key={series.key} scope="col">{series.label}</th>)}
            <th scope="col">合计</th>
          </tr>
        </thead>
        <tbody>
          {indexes.map((index) => (
            <tr key={view.buckets[index]}>
              <th scope="row">{formatCostBucket(view.buckets[index], granularity, "full")}</th>
              {view.series.map((series) => (
                <td key={series.key}>{series.values[index] > 0 ? formatCostAmount(series.values[index], currency) : "—"}</td>
              ))}
              <td>{formatCostAmount(view.bucketTotals[index], currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* --------------------------------------------------------------- sections */

function CostSummary({ view, stats, currency }: { view: CostView; stats: CostStats; currency: string }) {
  const days = costRangeDays(stats.range.startDate, stats.range.endDate);
  const previous = view.previous;
  const change = previous && previous.amount > 0 ? (view.total - previous.amount) / previous.amount : null;
  const previousTitle = `上一周期 ${stats.previousPeriod.startDate} 至 ${stats.previousPeriod.endDate}`
    + (previous ? `：${formatCostAmount(previous.amount, currency)}，${numberFormat.format(previous.turns)} 轮` : "：无记录");
  return (
    <dl className="cost-stats-summary">
      <div className="cost-stats-tile cost-stats-tile-hero">
        <dt>总费用</dt>
        <dd>{formatCostAmount(view.total, currency)}</dd>
        <p title={previousTitle}>
          {change === null ? "上一周期无记录" : (
            <>
              <span className="cost-stats-delta" data-direction={change > 0 ? "up" : change < 0 ? "down" : "flat"}>
                {change > 0 ? "▲" : change < 0 ? "▼" : "—"} {percentFormat.format(Math.abs(change))}
              </span>
              {" "}较前 {numberFormat.format(days)} 天
            </>
          )}
        </p>
      </div>
      <div className="cost-stats-tile">
        <dt>对话轮次</dt>
        <dd>{numberFormat.format(view.turns)}</dd>
        <p>{view.partialTurns ? `含 ${numberFormat.format(view.partialTurns)} 轮中断估算` : "有费用记录的轮次"}</p>
      </div>
      <div className="cost-stats-tile">
        <dt>平均每轮</dt>
        <dd>{view.turns ? formatCostAmount(view.total / view.turns, currency) : "—"}</dd>
        <p>总费用 ÷ 轮次</p>
      </div>
      <div className="cost-stats-tile">
        <dt>日均</dt>
        <dd>{formatCostAmount(view.total / days, currency)}</dd>
        <p>按所选 {numberFormat.format(days)} 天平均</p>
      </div>
      <div className="cost-stats-tile">
        <dt>峰值{GRANULARITY_LABELS[stats.granularity]}</dt>
        <dd>{view.peak ? formatCostAmount(view.peak.amount, currency) : "—"}</dd>
        <p>{view.peak ? formatCostBucket(view.peak.bucket, stats.granularity, "full") : "暂无记录"}</p>
      </div>
    </dl>
  );
}

function CostRanking({ view, currency, dimensionLabel }: { view: CostView; currency: string; dimensionLabel: string }) {
  const [expanded, setExpanded] = useState(false);
  const items = expanded ? view.ranking : view.ranking.slice(0, RANKING_PREVIEW);
  const largest = view.ranking[0]?.total || 0;
  return (
    <section className="codex-usage-section cost-stats-card" aria-labelledby="cost-stats-ranking-title">
      <div className="codex-usage-section-heading">
        <h3 id="cost-stats-ranking-title">按{dimensionLabel}排行</h3>
        <span className="cost-stats-caption">{numberFormat.format(view.ranking.length)} 项</span>
      </div>
      <ol className="cost-stats-ranking">
        {items.map((item) => (
          <li key={item.key}>
            <div className="cost-stats-ranking-head">
              <Swatch slot={item.slot} />
              <span className="cost-stats-ranking-name" title={item.label}>{item.label}</span>
              <b>{formatCostAmount(item.total, currency)}</b>
            </div>
            <div className="cost-stats-ranking-track" aria-hidden="true">
              <span data-slot={item.slot} style={{ width: `${largest > 0 ? Math.max(1.5, (item.total / largest) * 100) : 0}%` }} />
            </div>
            <p>
              占 {percentFormat.format(item.share)} · {numberFormat.format(item.turns)} 轮
              · 均 {formatCostAmount(item.turns ? item.total / item.turns : 0, currency)}
              {item.partialTurns ? ` · ${numberFormat.format(item.partialTurns)} 轮中断估算` : ""}
            </p>
          </li>
        ))}
      </ol>
      {view.ranking.length > RANKING_PREVIEW ? (
        <button type="button" className="cost-stats-more" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
          {expanded ? "收起" : `显示全部 ${numberFormat.format(view.ranking.length)} 项`}
        </button>
      ) : null}
    </section>
  );
}

/* ------------------------------------------------------------------ panel */

export function CostPanel({ client, refreshKey = 0 }: CostPanelProps) {
  const [provider, setProvider] = useState<CostStatsProvider>("codex");
  const [dimension, setDimension] = useState<CostGroupDimension>("user");
  const [granularity, setGranularity] = useState<GranularityChoice>("auto");
  const [config, setConfig] = useState<CostStatsConfig | null>(null);
  const [stats, setStats] = useState<CostStats | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [quickRange, setQuickRange] = useState<QuickRangeKey | "custom">(DEFAULT_QUICK_RANGE);
  const [selectedCurrency, setSelectedCurrency] = useState("");
  const [tableView, setTableView] = useState(false);
  const [loading, setLoading] = useState(true);
  const [querying, setQuerying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const requestIdRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++requestIdRef.current;
    const load = async () => {
      setLoading(true);
      setError("");
      setNotice("");
      try {
        const nextConfig = await client.getCostStatsConfig();
        if (cancelled || requestId !== requestIdRef.current) return;
        const range = rangeForDays(nextConfig.timeBasis.today, 30);
        setConfig(nextConfig);
        setStartDate(range.startDate);
        setEndDate(range.endDate);
        setQuickRange(DEFAULT_QUICK_RANGE);
        setGranularity("auto");
        const nextStats = await client.getCostStats(range);
        if (cancelled || requestId !== requestIdRef.current) return;
        setStats(nextStats);
      } catch (nextError) {
        if (!cancelled && requestId === requestIdRef.current) setError(getErrorMessage(nextError, "加载费用统计失败"));
      } finally {
        if (!cancelled && requestId === requestIdRef.current) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [client, refreshKey]);

  const runQuery = async (nextStartDate = startDate, nextEndDate = endDate, nextGranularity = granularity) => {
    const normalizedStart = nextStartDate.trim();
    const normalizedEnd = nextEndDate.trim();
    if (!normalizedStart || !normalizedEnd) {
      setError("请同时选择起止日期。");
      return;
    }
    if (normalizedStart > normalizedEnd) {
      setError("起始日期不能晚于结束日期。");
      return;
    }
    const requestId = ++requestIdRef.current;
    setQuerying(true);
    setError("");
    setNotice("");
    try {
      const nextStats = await client.getCostStats({
        startDate: normalizedStart,
        endDate: normalizedEnd,
        granularity: nextGranularity,
      });
      if (requestId === requestIdRef.current) setStats(nextStats);
    } catch (nextError) {
      if (requestId === requestIdRef.current) setError(getErrorMessage(nextError, "查询费用统计失败"));
    } finally {
      if (requestId === requestIdRef.current) setQuerying(false);
    }
  };

  const applyQuickRange = (key: QuickRangeKey, days: number | null) => {
    const today = config?.timeBasis.today || stats?.timeBasis.today || formatDateValue(new Date());
    const available = stats?.availableRange || config?.availableRange;
    const range = days === null
      ? { startDate: available?.firstDate || today, endDate: available?.lastDate || today }
      : rangeForDays(today, days);
    setQuickRange(key);
    setGranularity("auto");
    setStartDate(range.startDate);
    setEndDate(range.endDate);
    void runQuery(range.startDate, range.endDate, "auto");
  };

  const saveEnabled = async (enabled: boolean) => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const nextConfig = await client.updateCostStatsConfig({ provider, enabled });
      setConfig(nextConfig);
      setStats((current) => current ? { ...current, enabled: nextConfig.enabled } : current);
      setNotice(enabled
        ? `${PROVIDER_LABELS[provider]} 费用统计已开启，之后每轮对话结束时记录一条费用。`
        : `${PROVIDER_LABELS[provider]} 费用统计已关闭，历史记录仍可查询。`);
    } catch (nextError) {
      setError(`保存 ${PROVIDER_LABELS[provider]} 费用统计设置失败：${getErrorMessage(nextError, "请稍后重试")}`);
    } finally {
      setSaving(false);
    }
  };

  const handleProviderKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const lastIndex = PROVIDERS.length - 1;
    let nextIndex: number;
    if (event.key === "ArrowRight") nextIndex = index === lastIndex ? 0 : index + 1;
    else if (event.key === "ArrowLeft") nextIndex = index === 0 ? lastIndex : index - 1;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = lastIndex;
    else return;
    event.preventDefault();
    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[nextIndex]?.focus();
    setProvider(PROVIDERS[nextIndex]);
  };

  const currencies = useMemo(() => (stats ? costCurrencies(stats, provider) : []), [provider, stats]);
  const currency = currencies.includes(selectedCurrency) ? selectedCurrency : currencies[0] || "USD";
  const view = useMemo(
    () => (stats ? buildCostView(stats, { provider, currency, dimension }) : null),
    [currency, dimension, provider, stats],
  );
  const enabled = config?.enabled[provider] ?? false;
  const providerName = PROVIDER_LABELS[provider];
  const dimensionLabel = COST_GROUP_DIMENSIONS.find((item) => item.key === dimension)?.label || "";
  const utcOffset = config?.timeBasis.utcOffset || stats?.timeBasis.utcOffset || "";
  const hasData = Boolean(view && view.turns > 0);

  return (
    <section aria-labelledby="cost-stats-title" className="codex-usage-panel cost-stats-panel">
      <div className="codex-usage-heading">
        <div className="codex-usage-title-group">
          <h2 id="cost-stats-title">Cost</h2>
          <div role="tablist" aria-label="费用来源" className="codex-usage-provider-tabs">
            {PROVIDERS.map((id, index) => {
              const selected = id === provider;
              return (
                <button
                  key={id}
                  id={`cost-stats-provider-tab-${id}`}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-controls={selected ? "cost-stats-provider-panel" : undefined}
                  tabIndex={selected ? 0 : -1}
                  className={selected ? "tcb-selected-accent" : undefined}
                  onClick={() => setProvider(id)}
                  onKeyDown={(event) => handleProviderKeyDown(event, index)}
                >
                  {PROVIDER_LABELS[id]}
                </button>
              );
            })}
          </div>
        </div>
        <div className="codex-usage-heading-actions">
          <span className="codex-usage-time-basis">服务端本地时间 {utcOffset || "—"}</span>
        </div>
      </div>

      {error ? <div role="alert" className="codex-usage-alert codex-usage-alert-error">{error}</div> : null}
      {notice ? <div role="status" className="codex-usage-alert codex-usage-alert-success">{notice}</div> : null}
      {loading ? <p role="status" className="codex-usage-loading">正在加载费用统计…</p> : null}

      {!loading && config ? (
        <div
          role="tabpanel"
          id="cost-stats-provider-panel"
          aria-labelledby={`cost-stats-provider-tab-${provider}`}
          className="codex-usage-provider-panel"
        >
          <section className="codex-usage-section codex-usage-toolbar" aria-labelledby="cost-stats-toolbar-title">
            <h3 id="cost-stats-toolbar-title" className="codex-usage-visually-hidden">统计与筛选</h3>
            <div className="codex-usage-toolbar-row">
              <label className="codex-usage-switch">
                <span>{enabled ? "统计中" : "统计已关闭"}</span>
                <input
                  aria-label={`启用 ${providerName} 费用统计`}
                  type="checkbox"
                  checked={enabled}
                  disabled={saving}
                  onChange={(event) => void saveEnabled(event.target.checked)}
                />
              </label>
            </div>
            <form
              className="codex-usage-filter-form"
              aria-label="筛选条件"
              onSubmit={(event) => {
                event.preventDefault();
                setQuickRange("custom");
                void runQuery();
              }}
            >
              <div className="codex-usage-segmented" role="group" aria-label="日期快捷范围">
                {QUICK_RANGES.map(({ key, label, days }) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={quickRange === key}
                    disabled={querying}
                    onClick={() => applyQuickRange(key, days)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="codex-usage-date-fields">
                <input
                  aria-label="起始日期"
                  type="date"
                  value={startDate}
                  disabled={querying}
                  onChange={(event) => {
                    setQuickRange("custom");
                    setStartDate(event.target.value);
                  }}
                />
                <span aria-hidden="true">→</span>
                <input
                  aria-label="结束日期"
                  type="date"
                  value={endDate}
                  disabled={querying}
                  onChange={(event) => {
                    setQuickRange("custom");
                    setEndDate(event.target.value);
                  }}
                />
              </div>
              <div className="codex-usage-form-actions">
                <button type="submit" className="codex-usage-primary" disabled={querying}>
                  {querying ? "查询中…" : "查询"}
                </button>
                <button type="button" disabled={querying} onClick={() => applyQuickRange(DEFAULT_QUICK_RANGE, 30)}>重置</button>
              </div>
            </form>
          </section>

          {stats && view && hasData ? (
            <div className="cost-stats-content" data-querying={querying || undefined} aria-busy={querying}>
              <CostSummary view={view} stats={stats} currency={currency} />

              <section className="codex-usage-section cost-stats-card" aria-labelledby="cost-stats-trend-title">
                <div className="cost-stats-card-head">
                  <h3 id="cost-stats-trend-title">费用趋势</h3>
                  <div className="cost-stats-controls">
                    {currencies.length > 1 ? (
                      <div className="codex-usage-segmented" role="group" aria-label="币种">
                        {currencies.map((item) => (
                          <button key={item} type="button" aria-pressed={item === currency} onClick={() => setSelectedCurrency(item)}>
                            {item}
                          </button>
                        ))}
                      </div>
                    ) : null}
                    <div className="codex-usage-segmented" role="group" aria-label="分组维度">
                      {COST_GROUP_DIMENSIONS.map((item) => (
                        <button key={item.key} type="button" aria-pressed={dimension === item.key} onClick={() => setDimension(item.key)}>
                          按{item.label}
                        </button>
                      ))}
                    </div>
                    <div className="codex-usage-segmented" role="group" aria-label="时间粒度">
                      {GRANULARITIES.map((item) => (
                        <button
                          key={item.key}
                          type="button"
                          aria-pressed={granularity === item.key}
                          disabled={querying}
                          onClick={() => {
                            setGranularity(item.key);
                            void runQuery(stats.range.startDate, stats.range.endDate, item.key);
                          }}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                    <div className="codex-usage-segmented" role="group" aria-label="展示方式">
                      <button type="button" aria-pressed={!tableView} onClick={() => setTableView(false)}>图表</button>
                      <button type="button" aria-pressed={tableView} onClick={() => setTableView(true)}>表格</button>
                    </div>
                  </div>
                </div>
                {view.series.length > 1 ? (
                  <ul className="cost-stats-legend" aria-label={`${dimensionLabel}图例`}>
                    {view.series.map((series: CostSeries) => (
                      <li key={series.key}>
                        <Swatch slot={series.slot} />
                        <span title={series.label}>{series.label}</span>
                        <b>{formatCostAmount(series.total, currency)}</b>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {tableView
                  ? <CostTrendTable view={view} granularity={stats.granularity} currency={currency} />
                  : <CostTrendChart view={view} granularity={stats.granularity} currency={currency} dimensionLabel={dimensionLabel} />}
              </section>

              <CostRanking key={`${provider}:${dimension}`} view={view} currency={currency} dimensionLabel={dimensionLabel} />
            </div>
          ) : null}

          {stats && !hasData ? (
            <div className="codex-usage-empty cost-stats-empty" data-querying={querying || undefined}>
              {enabled ? (
                <p>所选时间范围内暂无 {providerName} 费用记录。</p>
              ) : (
                <>
                  <p>尚未开启 {providerName} 费用统计。开启后每轮对话结束时记录一条费用；关闭时不产生任何读写。</p>
                  <button type="button" className="cost-stats-enable" disabled={saving} onClick={() => void saveEnabled(true)}>
                    开启 {providerName} 费用统计
                  </button>
                </>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
