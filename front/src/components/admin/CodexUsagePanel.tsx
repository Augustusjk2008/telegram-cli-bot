import { useEffect, useMemo, useRef, useState } from "react";
import { DEFAULT_CODEX_USAGE_MODEL } from "../../services/types";
import type {
  CodexRateLimitSample,
  CodexUsageConfig,
  CodexUsageDailyProviderModelStats,
  CodexUsageMetrics,
  CodexUsageProvider,
  CodexUsageProviderModelStats,
  CodexUsageStats,
} from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { getErrorMessage } from "../../utils/errorMessage";
import "./CodexUsagePanel.css";

type Props = {
  client: WebBotClient;
  refreshKey?: number;
};

const numberFormat = new Intl.NumberFormat("zh-CN");
const percentFormat = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  maximumFractionDigits: 1,
});

const providerKindOrder: Record<CodexUsageProvider["kind"], number> = {
  openai_official: 0,
  base_url: 1,
  unknown: 2,
};

const providerResolutionLabels: Record<NonNullable<CodexUsageProvider["resolution"]>, string> = {
  resolved: "已解析",
  config_missing: "未找到 config.toml，按官方 Provider 处理",
  config_invalid: "config.toml 无法解析",
  provider_missing: "配置的 Provider 不存在",
  invalid_base_url: "base URL 无效",
  unsupported_override: "检测到不支持的运行时覆盖",
};

const COLLAPSED_DAILY_PAGE_SIZE = 10;
const EXPANDED_DAILY_PAGE_SIZE = 100;

function compactNumber(value: number) {
  const exact = numberFormat.format(value);
  const magnitude = Math.abs(value);
  const units = [
    { threshold: 1_000_000_000_000, suffix: "T" },
    { threshold: 1_000_000_000, suffix: "B" },
    { threshold: 1_000_000, suffix: "M" },
    { threshold: 1_000, suffix: "K" },
  ];
  const unit = units.find((candidate) => magnitude >= candidate.threshold);
  if (!unit) return { display: exact, exact };
  const scaled = value / unit.threshold;
  const display = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 0,
  }).format(scaled);
  return { display: `${display}${unit.suffix}`, exact };
}

function formatRate(value: number | null) {
  return value === null ? "—" : percentFormat.format(value);
}

function formatDateValue(date: Date) {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function subtractDays(dateText: string, days: number) {
  const parsed = new Date(`${dateText}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return "";
  parsed.setUTCDate(parsed.getUTCDate() - days);
  return formatDateValue(parsed);
}

function defaultRange(today: string) {
  const endDate = today || formatDateValue(new Date());
  return {
    startDate: subtractDays(endDate, 29) || endDate,
    endDate,
  };
}

function providerLabel(provider: CodexUsageProvider) {
  return provider.label || (provider.kind === "openai_official" ? "OpenAI 官方" : "无法识别");
}

function sortProviders(left: CodexUsageProvider, right: CodexUsageProvider) {
  const kindDifference = providerKindOrder[left.kind] - providerKindOrder[right.kind];
  if (kindDifference) return kindDifference;
  return providerLabel(left).localeCompare(providerLabel(right), "zh-CN");
}

function CompactNumber({ value }: { value: number }) {
  const formatted = compactNumber(value);
  return (
    <span className="codex-usage-number" title={formatted.exact} aria-label={formatted.exact}>
      {formatted.display}
    </span>
  );
}

function MetricCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="codex-usage-metric-card">
      <dt>{label}</dt>
      <dd>{typeof value === "number" ? <CompactNumber value={value} /> : value}</dd>
    </div>
  );
}

function MetricCells({ metrics }: { metrics: CodexUsageMetrics }) {
  return (
    <>
      <td><CompactNumber value={metrics.requestCount} /></td>
      <td><CompactNumber value={metrics.inputTokens} /></td>
      <td><CompactNumber value={metrics.cachedInputTokens} /></td>
      <td><CompactNumber value={metrics.uncachedInputTokens} /></td>
      <td><CompactNumber value={metrics.outputTokens} /></td>
      <td><CompactNumber value={metrics.reasoningOutputTokens} /></td>
      <td><CompactNumber value={metrics.totalTokens} /></td>
      <td>{formatRate(metrics.cacheHitRate)}</td>
    </>
  );
}

const percentValueFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });
const durationDaysFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const MAX_RATE_LIMIT_DURATION_MS = 7 * 24 * 60 * 60 * 1000;

function formatPercentValue(value: number) {
  return `${percentValueFormat.format(value)}%`;
}

function remainingPercent(sample: CodexRateLimitSample) {
  return Math.min(100, Math.max(0, 100 - sample.usedPercent));
}

function remainingDurationMs(sample: CodexRateLimitSample) {
  const sampledAt = Date.parse(sample.sampledAt);
  const resetsAt = Date.parse(sample.resetsAt);
  if (!Number.isFinite(sampledAt) || !Number.isFinite(resetsAt)) return 0;
  return Math.min(MAX_RATE_LIMIT_DURATION_MS, Math.max(0, resetsAt - sampledAt));
}

function remainingDurationPercent(sample: CodexRateLimitSample) {
  return (remainingDurationMs(sample) / MAX_RATE_LIMIT_DURATION_MS) * 100;
}

function formatRemainingDuration(durationMs: number) {
  const totalMinutes = Math.floor(durationMs / (60 * 1000));
  const days = Math.floor(totalMinutes / (24 * 60));
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60);
  const minutes = totalMinutes % 60;
  const parts = [
    ...(days ? [`${numberFormat.format(days)} 天`] : []),
    ...(hours ? [`${numberFormat.format(hours)} 小时`] : []),
    ...(minutes ? [`${numberFormat.format(minutes)} 分钟`] : []),
  ];
  return parts.length ? parts.join(" ") : "0 分钟";
}

function formatServerLocalTime(value: string) {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/.exec(value);
  return match ? `${match[1]} ${match[2]}` : value;
}

function formatAxisTime(value: string) {
  const match = /^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/.exec(value);
  return match ? `${match[1]} ${match[2]}` : value;
}

function formatWindow(minutes: number) {
  if (minutes % 1440 === 0) return `${numberFormat.format(minutes / 1440)} 天`;
  if (minutes % 60 === 0) return `${numberFormat.format(minutes / 60)} 小时`;
  return `${numberFormat.format(minutes)} 分钟`;
}

function CodexRateLimitModelChart({
  model,
  samples,
}: {
  model: string;
  samples: CodexRateLimitSample[];
}) {
  const orderedSamples = useMemo(
    () => [...samples].sort((left, right) => Date.parse(left.sampledAt) - Date.parse(right.sampledAt)),
    [samples],
  );
  const latest = orderedSamples.at(-1);
  if (!latest) return null;

  const width = 640;
  const height = 250;
  const left = 64;
  const right = 64;
  const top = 32;
  const bottom = 42;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const timestamps = orderedSamples.map((sample) => Date.parse(sample.sampledAt));
  const hasValidTimestamps = timestamps.every(Number.isFinite);
  const minTimestamp = hasValidTimestamps ? timestamps[0] : 0;
  const maxTimestamp = hasValidTimestamps ? timestamps[timestamps.length - 1] : 0;
  const timestampRange = maxTimestamp - minTimestamp;
  const points = orderedSamples.map((sample, index) => ({
    x: left + Math.min(1, Math.max(0, (
      orderedSamples.length === 1
        ? 0.5
        : timestampRange > 0
          ? (timestamps[index] - minTimestamp) / timestampRange
          : index / (orderedSamples.length - 1)
    ))) * plotWidth,
    quotaY: top + ((100 - remainingPercent(sample)) / 100) * plotHeight,
    durationY: top + ((100 - remainingDurationPercent(sample)) / 100) * plotHeight,
  }));
  const latestRemaining = remainingPercent(latest);
  const latestDuration = formatRemainingDuration(remainingDurationMs(latest));
  const accessibleLabel = `${model} Codex 剩余额度与剩余时长趋势，共 ${orderedSamples.length} 个样本，当前剩余 ${formatPercentValue(latestRemaining)}，剩余时长 ${latestDuration}`;

  return (
    <article className="codex-usage-rate-limit-group">
      <div className="codex-usage-section-heading codex-usage-rate-limit-heading">
        <div>
          <h4>{model}</h4>
        </div>
        <div className="codex-usage-rate-limit-summary" aria-label="最新限额样本摘要">
          <strong>当前剩余 {formatPercentValue(latestRemaining)}</strong>
          <span>剩余时长 {latestDuration}</span>
          <span>已用 {formatPercentValue(latest.usedPercent)}</span>
          <span>{formatWindow(latest.windowMinutes)}窗口</span>
          <span>重置时间 {formatServerLocalTime(latest.resetsAt)}</span>
        </div>
      </div>
      <div className="codex-usage-rate-limit-chart">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={accessibleLabel}>
          <title>{model} Codex 剩余额度与剩余时长趋势</title>
          <desc>按采样时间展示该模型的 Codex 剩余额度与剩余时长；左纵轴为百分之零到百分之一百，右纵轴为零天到七天。</desc>
          <line
            className="codex-usage-rate-limit-quota-axis"
            x1={left}
            x2={left}
            y1={top}
            y2={top + plotHeight}
          />
          <line
            className="codex-usage-rate-limit-duration-axis"
            x1={width - right}
            x2={width - right}
            y1={top}
            y2={top + plotHeight}
          />
          <text
            className="codex-usage-rate-limit-quota-axis-title"
            x={left}
            y={18}
            textAnchor="start"
          >
            剩余额度
          </text>
          <text
            className="codex-usage-rate-limit-duration-axis-title"
            x={width - right}
            y={18}
            textAnchor="end"
          >
            剩余时长
          </text>
          {[0, 25, 50, 75, 100].map((remaining) => {
            const y = top + ((100 - remaining) / 100) * plotHeight;
            return (
              <g key={remaining} className="codex-usage-rate-limit-grid">
                <line x1={left} x2={width - right} y1={y} y2={y} />
                <text
                  className="codex-usage-rate-limit-quota-tick"
                  x={left - 10}
                  y={y + 4}
                  textAnchor="end"
                >
                  {remaining}%
                </text>
                <text
                  className="codex-usage-rate-limit-duration-tick"
                  x={width - right + 10}
                  y={y + 4}
                  textAnchor="start"
                >
                  {durationDaysFormat.format(remaining * 0.07)} 天
                </text>
              </g>
            );
          })}
          {points.length > 1 ? (
            <>
              <polyline
                className="codex-usage-rate-limit-line"
                points={points.map((point) => `${point.x},${point.quotaY}`).join(" ")}
              />
              <polyline
                className="codex-usage-rate-limit-duration-line"
                points={points.map((point) => `${point.x},${point.durationY}`).join(" ")}
              />
            </>
          ) : null}
          <text className="codex-usage-rate-limit-axis-label" x={left} y={height - 12} textAnchor="start">
            {formatAxisTime(orderedSamples[0].sampledAt)}
          </text>
          {orderedSamples.length > 1 ? (
            <text className="codex-usage-rate-limit-axis-label" x={width - right} y={height - 12} textAnchor="end">
              {formatAxisTime(latest.sampledAt)}
            </text>
          ) : null}
        </svg>
      </div>
    </article>
  );
}

function CodexRateLimitChart({ samples }: { samples: CodexRateLimitSample[] }) {
  const modelGroups = useMemo(() => {
    const grouped = new Map<string, CodexRateLimitSample[]>();
    for (const sample of samples) {
      grouped.set(sample.model, [...(grouped.get(sample.model) || []), sample]);
    }
    return Array.from(grouped.entries()).sort(([left], [right]) => {
      if (left === right) return 0;
      if (left === DEFAULT_CODEX_USAGE_MODEL) return -1;
      if (right === DEFAULT_CODEX_USAGE_MODEL) return 1;
      return left.localeCompare(right);
    });
  }, [samples]);

  return (
    <section className="codex-usage-section" aria-labelledby="codex-rate-limit-title">
      <h3 id="codex-rate-limit-title">Codex 剩余额度趋势</h3>
      {modelGroups.length ? (
        <div className="codex-usage-rate-limit-groups">
          {modelGroups.map(([model, modelSamples]) => (
            <CodexRateLimitModelChart key={model} model={model} samples={modelSamples} />
          ))}
        </div>
      ) : (
        <p className="codex-usage-empty-state">
          暂无 Codex 限额样本；开启采集并完成一次 OpenAI 官方 Codex turn 后显示。
        </p>
      )}
    </section>
  );
}

export function CodexUsagePanel({ client, refreshKey = 0 }: Props) {
  const [config, setConfig] = useState<CodexUsageConfig | null>(null);
  const [stats, setStats] = useState<CodexUsageStats | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  // null 表示全部 Provider；空数组表示用户明确清空了全部选择。
  const [selectedProviderKeys, setSelectedProviderKeys] = useState<string[] | null>(null);
  const [dailyPage, setDailyPage] = useState(1);
  const [dailyPageSize, setDailyPageSize] = useState(COLLAPSED_DAILY_PAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const [querying, setQuerying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const queryRequestIdRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++queryRequestIdRef.current;

    const load = async () => {
      setLoading(true);
      setError("");
      setNotice("");
      setSelectedProviderKeys(null);
      setDailyPage(1);
      setDailyPageSize(COLLAPSED_DAILY_PAGE_SIZE);
      try {
        const nextConfig = await client.getCodexUsageConfig();
        if (cancelled || requestId !== queryRequestIdRef.current) return;
        const range = defaultRange(nextConfig.timeBasis.today);
        setConfig(nextConfig);
        setStartDate(range.startDate);
        setEndDate(range.endDate);

        const nextStats = await client.getCodexUsageStats({
          ...range,
          dailyPage: 1,
          dailyPageSize: COLLAPSED_DAILY_PAGE_SIZE,
        });
        if (cancelled || requestId !== queryRequestIdRef.current) return;
        setStats(nextStats);
      } catch (nextError) {
        if (!cancelled && requestId === queryRequestIdRef.current) {
          setError(getErrorMessage(nextError, "加载 Codex 用量失败"));
        }
      } finally {
        if (!cancelled && requestId === queryRequestIdRef.current) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [client, refreshKey]);

  const providers = useMemo(() => {
    const byKey = new Map<string, CodexUsageProvider>();
    for (const provider of stats?.availableProviders || []) {
      byKey.set(provider.key, provider);
    }
    if (config?.currentProvider) {
      byKey.set(config.currentProvider.key, config.currentProvider);
    }
    return Array.from(byKey.values()).sort(sortProviders);
  }, [config, stats]);

  const providerRows = useMemo<CodexUsageProviderModelStats[]>(
    () => {
      const detailedRows = stats?.byProviderModel || [];
      const rows = detailedRows.length
        ? detailedRows
        : (stats?.byProvider || []).map((item) => ({ ...item, model: DEFAULT_CODEX_USAGE_MODEL }));
      return [...rows].sort((left, right) => (
        sortProviders(left.provider, right.provider) || left.model.localeCompare(right.model)
      ));
    },
    [stats],
  );

  const dailyRows = useMemo<CodexUsageDailyProviderModelStats[]>(() => {
    const detailedRows = stats?.dailyByProviderModel || [];
    const rows = detailedRows.length
      ? detailedRows
      : (stats?.dailyByProvider || []).map((item) => ({
          ...item,
          model: DEFAULT_CODEX_USAGE_MODEL,
        }));
    return rows;
  }, [stats]);

  const runStatsQuery = async (
    nextStartDate = startDate,
    nextEndDate = endDate,
    nextSelectedProviderKeys = selectedProviderKeys,
    nextDailyPage = 1,
    nextDailyPageSize = COLLAPSED_DAILY_PAGE_SIZE,
  ) => {
    const normalizedStartDate = nextStartDate.trim();
    const normalizedEndDate = nextEndDate.trim();
    if (!normalizedStartDate || !normalizedEndDate) {
      setError("请同时选择起止日期。");
      return;
    }
    if (normalizedStartDate > normalizedEndDate) {
      setError("起始日期不能晚于结束日期。");
      return;
    }
    if (nextSelectedProviderKeys !== null && nextSelectedProviderKeys.length === 0) {
      setError("请至少选择一个 Provider 后再查询。");
      return;
    }

    const requestId = ++queryRequestIdRef.current;
    const requestedDailyPage = Math.max(1, Math.floor(nextDailyPage));
    const requestedDailyPageSize = Math.min(
      EXPANDED_DAILY_PAGE_SIZE,
      Math.max(1, Math.floor(nextDailyPageSize)),
    );
    setQuerying(true);
    setError("");
    setNotice("");
    try {
      const nextStats = await client.getCodexUsageStats({
        startDate: normalizedStartDate,
        endDate: normalizedEndDate,
        ...(nextSelectedProviderKeys === null ? {} : { providerKeys: nextSelectedProviderKeys }),
        dailyPage: requestedDailyPage,
        dailyPageSize: requestedDailyPageSize,
      });
      if (requestId === queryRequestIdRef.current) {
        setStats(nextStats);
        setDailyPage(requestedDailyPage);
        setDailyPageSize(requestedDailyPageSize);
      }
    } catch (nextError) {
      if (requestId === queryRequestIdRef.current) {
        setError(getErrorMessage(nextError, "查询 Codex 用量失败"));
      }
    } finally {
      if (requestId === queryRequestIdRef.current) {
        setQuerying(false);
      }
    }
  };

  const saveEnabled = async (enabled: boolean) => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const nextConfig = await client.updateCodexUsageConfig({ enabled });
      setConfig(nextConfig);
      setStats((current) => current ? { ...current, enabled: nextConfig.enabled } : current);
      setNotice(enabled ? "Codex 用量采集已开启。" : "Codex 用量采集已关闭，历史数据仍可查询。");
    } catch (nextError) {
      setError(`保存 Codex 用量采集设置失败：${getErrorMessage(nextError, "请稍后重试")}`);
    } finally {
      setSaving(false);
    }
  };

  const applyQuickRange = (days: number | null) => {
    const today = config?.timeBasis.today || stats?.timeBasis.today || formatDateValue(new Date());
    const availableRange = stats?.availableRange || config?.availableRange;
    const range = days === null
      ? {
          startDate: availableRange?.firstDate || today,
          endDate: availableRange?.lastDate || today,
        }
      : {
          startDate: subtractDays(today, Math.max(0, days - 1)) || today,
          endDate: today,
    };
    setStartDate(range.startDate);
    setEndDate(range.endDate);
    void runStatsQuery(
      range.startDate,
      range.endDate,
      selectedProviderKeys,
      1,
      COLLAPSED_DAILY_PAGE_SIZE,
    );
  };

  const resetFilters = () => {
    const range = defaultRange(config?.timeBasis.today || stats?.timeBasis.today || "");
    setStartDate(range.startDate);
    setEndDate(range.endDate);
    setSelectedProviderKeys(null);
    void runStatsQuery(range.startDate, range.endDate, null, 1, COLLAPSED_DAILY_PAGE_SIZE);
  };

  const toggleProvider = (providerKey: string) => {
    setSelectedProviderKeys((current) => {
      const currentKeys = current === null ? providers.map((provider) => provider.key) : current;
      return currentKeys.includes(providerKey)
        ? currentKeys.filter((key) => key !== providerKey)
        : [...currentKeys, providerKey];
    });
  };

  const expandDailyRows = () => {
    void runStatsQuery(
      startDate,
      endDate,
      selectedProviderKeys,
      1,
      EXPANDED_DAILY_PAGE_SIZE,
    );
  };

  const collapseDailyRows = () => {
    void runStatsQuery(
      startDate,
      endDate,
      selectedProviderKeys,
      1,
      COLLAPSED_DAILY_PAGE_SIZE,
    );
  };

  const changeDailyPage = (nextPage: number) => {
    void runStatsQuery(
      startDate,
      endDate,
      selectedProviderKeys,
      nextPage,
      EXPANDED_DAILY_PAGE_SIZE,
    );
  };

  const hasRateLimitSamples = Boolean(stats?.rateLimitSamples.length);
  const hasHistoricalData = Boolean(stats && (stats.totals.requestCount > 0 || hasRateLimitSamples));
  const hasUsageRows = Boolean(providerRows.length || dailyRows.length);
  const noResults = Boolean(stats && !hasUsageRows && !hasRateLimitSamples);
  const dailyPagination = stats?.dailyPagination;
  const dailyExpanded = dailyPageSize > COLLAPSED_DAILY_PAGE_SIZE;

  return (
    <section aria-labelledby="codex-usage-title" className="codex-usage-panel">
      <div className="codex-usage-heading">
        <div>
          <h2 id="codex-usage-title">Codex 用量</h2>
        </div>
        <span className="codex-usage-time-basis">
          服务端本地时间 {config?.timeBasis.utcOffset || stats?.timeBasis.utcOffset || "—"}
        </span>
      </div>

      {error ? <div role="alert" className="codex-usage-alert codex-usage-alert-error">{error}</div> : null}
      {notice ? <div role="status" className="codex-usage-alert codex-usage-alert-success">{notice}</div> : null}

      {loading ? <p role="status" className="codex-usage-loading">正在加载 Codex 用量…</p> : null}

      {!loading && config ? (
        <>
          <section className="codex-usage-section" aria-labelledby="codex-usage-settings-title">
            <div className="codex-usage-section-heading">
              <div>
                <h3 id="codex-usage-settings-title">采集设置</h3>
              </div>
              <label className="codex-usage-switch">
                <span>启用 Codex 用量采集</span>
                <input
                  aria-label="启用 Codex 用量采集"
                  type="checkbox"
                  checked={config.enabled}
                  disabled={saving}
                  onChange={(event) => void saveEnabled(event.target.checked)}
                />
              </label>
            </div>
            {!config.enabled && hasHistoricalData ? (
              <p className="codex-usage-disabled-history">统计采集已关闭，历史数据仍可查询。</p>
            ) : null}
          </section>

          <section className="codex-usage-section" aria-labelledby="codex-usage-provider-title">
            <h3 id="codex-usage-provider-title">当前 Provider</h3>
            <dl className="codex-usage-provider-details">
              <div>
                <dt>Provider</dt>
                <dd>{providerLabel(config.currentProvider)}</dd>
              </div>
              <div>
                <dt>规范化地址</dt>
                <dd className="codex-usage-breakable">{config.currentProvider.baseUrl || "OpenAI 官方"}</dd>
              </div>
              <div>
                <dt>解析状态</dt>
                <dd>
                  {config.currentProvider.resolution
                    ? providerResolutionLabels[config.currentProvider.resolution]
                    : "未知/未提供"}
                </dd>
              </div>
            </dl>
          </section>

          <form
            className="codex-usage-section codex-usage-filter-form"
            onSubmit={(event) => {
              event.preventDefault();
              void runStatsQuery();
            }}
          >
            <div className="codex-usage-section-heading">
              <div>
                <h3>筛选条件</h3>
              </div>
              <div className="codex-usage-quick-actions" aria-label="日期快捷范围">
                <button type="button" disabled={querying} onClick={() => applyQuickRange(1)}>今天</button>
                <button type="button" disabled={querying} onClick={() => applyQuickRange(7)}>近 7 天</button>
                <button type="button" disabled={querying} onClick={() => applyQuickRange(30)}>近 30 天</button>
                <button type="button" disabled={querying} onClick={() => applyQuickRange(90)}>近 90 天</button>
                <button type="button" disabled={querying} onClick={() => applyQuickRange(null)}>全部</button>
              </div>
            </div>

            <div className="codex-usage-date-fields">
              <label>
                起始日期
                <input aria-label="起始日期" type="date" value={startDate} disabled={querying} onChange={(event) => setStartDate(event.target.value)} />
              </label>
              <label>
                结束日期
                <input aria-label="结束日期" type="date" value={endDate} disabled={querying} onChange={(event) => setEndDate(event.target.value)} />
              </label>
            </div>

            <fieldset className="codex-usage-provider-filters">
              <legend>Provider</legend>
              <div className="codex-usage-provider-actions">
                <button type="button" disabled={querying} onClick={() => setSelectedProviderKeys(null)}>全选</button>
                <button type="button" disabled={querying} onClick={() => setSelectedProviderKeys([])}>清空</button>
              </div>
              <div className="codex-usage-provider-options">
                {providers.map((provider) => {
                  const checked = selectedProviderKeys === null || selectedProviderKeys.includes(provider.key);
                  return (
                    <label key={provider.key} className="codex-usage-provider-option">
                      <input
                        aria-label={`筛选 Provider：${providerLabel(provider)}`}
                        type="checkbox"
                        checked={checked}
                        disabled={querying}
                        onChange={() => toggleProvider(provider.key)}
                      />
                      <span>{providerLabel(provider)}</span>
                      {provider.baseUrl ? <small>{provider.baseUrl}</small> : null}
                    </label>
                  );
                })}
                {!providers.length ? <p>暂无可筛选的 Provider。</p> : null}
              </div>
            </fieldset>

            <div className="codex-usage-form-actions">
              <button type="submit" className="codex-usage-primary" disabled={querying}>
                {querying ? "查询中…" : "查询"}
              </button>
              <button type="button" onClick={resetFilters} disabled={querying}>重置</button>
            </div>
          </form>

          {stats ? (
            <>
              <section className="codex-usage-section" aria-labelledby="codex-usage-summary-title">
                <div className="codex-usage-section-heading">
                  <div>
                    <h3 id="codex-usage-summary-title">汇总</h3>
                    <p>{stats.range.startDate} 至 {stats.range.endDate}</p>
                  </div>
                </div>
                <dl className="codex-usage-metric-grid">
                  <MetricCard label="请求次数" value={stats.totals.requestCount} />
                  <MetricCard label="输入 token" value={stats.totals.inputTokens} />
                  <MetricCard label="缓存命中 token" value={stats.totals.cachedInputTokens} />
                  <MetricCard label="非缓存输入" value={stats.totals.uncachedInputTokens} />
                  <MetricCard label="输出 token" value={stats.totals.outputTokens} />
                  <MetricCard label="总 token" value={stats.totals.totalTokens} />
                  <MetricCard label="缓存命中率" value={formatRate(stats.totals.cacheHitRate)} />
                </dl>
              </section>

              <CodexRateLimitChart samples={stats.rateLimitSamples} />

              {noResults ? <p className="codex-usage-empty">暂无符合筛选条件的 Codex 用量数据。</p> : null}

              {hasUsageRows ? (
                <section className="codex-usage-section" aria-labelledby="codex-usage-by-provider-title">
                  <h3 id="codex-usage-by-provider-title">按 Provider / 模型汇总</h3>
                  <div className="codex-usage-table-wrap">
                    <table aria-label="Codex 用量 Provider 汇总">
                      <caption>按 Provider 和模型汇总</caption>
                      <thead>
                        <tr>
                          <th scope="col">Provider</th>
                          <th scope="col">模型</th>
                          <th scope="col">请求</th>
                          <th scope="col">输入</th>
                          <th scope="col">缓存输入</th>
                          <th scope="col">非缓存输入</th>
                          <th scope="col">输出</th>
                          <th scope="col">推理输出</th>
                          <th scope="col">总 token</th>
                          <th scope="col">缓存命中率</th>
                        </tr>
                      </thead>
                      <tbody>
                        {providerRows.map((item) => (
                          <tr key={`${item.provider.key}:${item.model}`}>
                            <th scope="row">
                              <span>{providerLabel(item.provider)}</span>
                              {item.provider.baseUrl ? <small>{item.provider.baseUrl}</small> : null}
                            </th>
                            <td className="codex-usage-model-cell">{item.model}</td>
                            <MetricCells metrics={item} />
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}

              {hasUsageRows ? (
                <section className="codex-usage-section" aria-labelledby="codex-usage-daily-title">
                  <div className="codex-usage-section-heading">
                    <div>
                      <h3 id="codex-usage-daily-title">每日明细</h3>
                    </div>
                  </div>
                  <div className="codex-usage-table-wrap">
                    <table aria-label="Codex 用量每日明细">
                      <caption>按日期、Provider 和模型的每日明细</caption>
                      <thead>
                        <tr>
                          <th scope="col">日期</th>
                          <th scope="col">Provider</th>
                          <th scope="col">模型</th>
                          <th scope="col">请求</th>
                          <th scope="col">输入</th>
                          <th scope="col">缓存输入</th>
                          <th scope="col">非缓存输入</th>
                          <th scope="col">输出</th>
                          <th scope="col">推理输出</th>
                          <th scope="col">总 token</th>
                          <th scope="col">缓存命中率</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dailyRows.map((item) => (
                          <tr key={`${item.date}:${item.provider.key}:${item.model}`}>
                            <th scope="row">{item.date}</th>
                            <td className="codex-usage-provider-cell">{providerLabel(item.provider)}</td>
                            <td className="codex-usage-model-cell">{item.model}</td>
                            <MetricCells metrics={item} />
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {dailyPagination ? (
                    <div className="codex-usage-daily-pagination">
                      {!dailyExpanded && dailyPagination.totalItems > COLLAPSED_DAILY_PAGE_SIZE ? (
                        <button type="button" disabled={querying} onClick={expandDailyRows}>展开更多</button>
                      ) : null}
                      {dailyExpanded ? (
                        <>
                          <button type="button" disabled={querying} onClick={collapseDailyRows}>收起</button>
                          {dailyPagination.totalPages > 1 ? (
                            <div className="codex-usage-daily-page-controls">
                              <button
                                type="button"
                                disabled={querying || !dailyPagination.hasPrevious}
                                onClick={() => changeDailyPage(dailyPagination.page - 1)}
                              >
                                上一页
                              </button>
                              <span>第 {dailyPagination.page} / {dailyPagination.totalPages} 页，共 {dailyPagination.totalItems} 条</span>
                              <button
                                type="button"
                                disabled={querying || !dailyPagination.hasNext}
                                onClick={() => changeDailyPage(dailyPagination.page + 1)}
                              >
                                下一页
                              </button>
                            </div>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              ) : null}
            </>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
