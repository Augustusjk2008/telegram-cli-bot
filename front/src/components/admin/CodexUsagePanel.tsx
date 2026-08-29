import { useEffect, useMemo, useRef, useState } from "react";
import {
  GENERAL_CODEX_RATE_LIMIT_ID,
  GPT_RESERVE_RATE_LIMIT_ID,
  SECONDARY_CODEX_RATE_LIMIT_ID,
} from "../../services/types";
import type {
  CodexRateLimitSample,
  CodexUsageConfig,
  CodexUsageProvider,
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

const providerResolutionLabels: Record<NonNullable<CodexUsageProvider["resolution"]>, string> = {
  resolved: "已解析",
  config_missing: "未找到 config.toml，按官方 Provider 处理",
  config_invalid: "config.toml 无法解析",
  provider_missing: "配置的 Provider 不存在",
  invalid_base_url: "base URL 无效",
  unsupported_override: "检测到不支持的运行时覆盖",
};

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

const percentValueFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });
const durationDaysFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const RATE_LIMIT_AXIS_STEP_PERCENT = 10;
const RATE_LIMIT_AXIS_INTERVALS = 4;

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
  return Math.min(sample.windowMinutes * 60 * 1000, Math.max(0, resetsAt - sampledAt));
}

function remainingDurationPercent(sample: CodexRateLimitSample) {
  return (remainingDurationMs(sample) / (sample.windowMinutes * 60 * 1000)) * 100;
}

function rateLimitAxisBounds(samples: CodexRateLimitSample[]) {
  const values = samples.flatMap((sample) => [
    remainingPercent(sample),
    remainingDurationPercent(sample),
  ]);
  let min = Math.floor(Math.min(...values) / RATE_LIMIT_AXIS_STEP_PERCENT) * RATE_LIMIT_AXIS_STEP_PERCENT;
  let max = Math.ceil(Math.max(...values) / RATE_LIMIT_AXIS_STEP_PERCENT) * RATE_LIMIT_AXIS_STEP_PERCENT;
  if (min === max) {
    if (max < 100) max += RATE_LIMIT_AXIS_STEP_PERCENT;
    else min -= RATE_LIMIT_AXIS_STEP_PERCENT;
  }
  return { min, max };
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

function formatPlanType(planType: string | null) {
  const normalized = planType?.trim().toLowerCase();
  if (!normalized) return "套餐未知";
  if (normalized === "free") return "Free";
  if (normalized === "pro") return "Pro";
  return planType?.trim() || "套餐未知";
}

function CodexRateLimitBucketChart({
  label,
  samples,
}: {
  label: string;
  samples: CodexRateLimitSample[];
}) {
  const orderedSamples = useMemo(
    () => [...samples].sort((left, right) => Date.parse(left.sampledAt) - Date.parse(right.sampledAt)),
    [samples],
  );
  const latest = orderedSamples.at(-1);
  if (!latest) {
    return (
      <article className="codex-usage-rate-limit-group">
        <h4>{label}</h4>
        <p className="codex-usage-empty-state">
          {label === "通用 Codex" ? "暂无通用 Codex 限额样本。" : `暂无 ${label} 限额样本。`}
        </p>
      </article>
    );
  }

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
  const axisBounds = rateLimitAxisBounds(orderedSamples);
  const axisRange = axisBounds.max - axisBounds.min;
  const axisTicks = Array.from(
    { length: RATE_LIMIT_AXIS_INTERVALS + 1 },
    (_, index) => axisBounds.min + (axisRange * index) / RATE_LIMIT_AXIS_INTERVALS,
  );
  const yForPercent = (value: number) => (
    top + ((axisBounds.max - value) / axisRange) * plotHeight
  );
  const points = orderedSamples.map((sample, index) => ({
    x: left + Math.min(1, Math.max(0, (
      orderedSamples.length === 1
        ? 0.5
        : timestampRange > 0
          ? (timestamps[index] - minTimestamp) / timestampRange
          : index / (orderedSamples.length - 1)
    ))) * plotWidth,
    quotaY: yForPercent(remainingPercent(sample)),
    durationY: yForPercent(remainingDurationPercent(sample)),
  }));
  const latestRemaining = remainingPercent(latest);
  const latestDuration = formatRemainingDuration(remainingDurationMs(latest));
  const durationWindowDays = latest.windowMinutes / 1440;
  const durationDaysForPercent = (remaining: number) => (
    durationDaysFormat.format((remaining / 100) * durationWindowDays)
  );
  const accessibleLabel = `${label} 剩余额度与剩余时长趋势，共 ${orderedSamples.length} 个样本，当前剩余 ${formatPercentValue(latestRemaining)}，剩余时长 ${latestDuration}`;

  return (
    <article className="codex-usage-rate-limit-group">
      <div className="codex-usage-section-heading codex-usage-rate-limit-heading">
        <div>
          <h4>{label}</h4>
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
          <title>{label} 剩余额度与剩余时长趋势</title>
          <desc>
            按采样时间展示该额度桶的剩余额度与剩余时长；左右纵轴按当前数据范围同步缩放，
            左轴为{formatPercentValue(axisBounds.min)}到{formatPercentValue(axisBounds.max)}，
            右轴为{durationDaysForPercent(axisBounds.min)}天到{durationDaysForPercent(axisBounds.max)}天。
          </desc>
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
          {axisTicks.map((remaining) => {
            const y = yForPercent(remaining);
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
                  {durationDaysForPercent(remaining)} 天
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
  const limitGroups = useMemo(() => {
    const grouped = new Map<string, {
      limitId: string;
      planType: string | null;
      samples: CodexRateLimitSample[];
    }>();
    for (const sample of samples) {
      const planType = sample.planType?.trim().toLowerCase() || null;
      const key = `${sample.limitId}\u0000${planType || ""}`;
      const group = grouped.get(key) || { limitId: sample.limitId, planType, samples: [] };
      group.samples.push(sample);
      grouped.set(key, group);
    }
    const groups = Array.from(grouped.values());
    const limitIds = [
      GENERAL_CODEX_RATE_LIMIT_ID,
      SECONDARY_CODEX_RATE_LIMIT_ID,
      GPT_RESERVE_RATE_LIMIT_ID,
      ...samples
        .map((sample) => sample.limitId)
        .filter((limitId) => (
          limitId !== GENERAL_CODEX_RATE_LIMIT_ID
          && limitId !== SECONDARY_CODEX_RATE_LIMIT_ID
          && limitId !== GPT_RESERVE_RATE_LIMIT_ID
        )),
    ];
    return [...new Set(limitIds)].flatMap((limitId) => {
      const matches = groups.filter((group) => group.limitId === limitId);
      return matches.length ? matches : [{ limitId, planType: null, samples: [] }];
    });
  }, [samples]);

  const limitLabel = (limitId: string) => {
    if (limitId === GENERAL_CODEX_RATE_LIMIT_ID) return "通用 Codex";
    if (limitId === SECONDARY_CODEX_RATE_LIMIT_ID) return "gpt-5.3-codex-spark";
    if (limitId === GPT_RESERVE_RATE_LIMIT_ID) return "gpt-reserve";
    return limitId;
  };

  return (
    <section className="codex-usage-section" aria-labelledby="codex-rate-limit-title">
      <h3 id="codex-rate-limit-title">Codex 剩余额度趋势</h3>
      <div className="codex-usage-rate-limit-groups">
        {limitGroups.map(({ limitId, planType, samples: limitSamples }) => (
          <CodexRateLimitBucketChart
            key={`${limitId}:${planType || "empty"}`}
            label={limitSamples.length ? `${limitLabel(limitId)} · ${formatPlanType(planType)}` : limitLabel(limitId)}
            samples={limitSamples}
          />
        ))}
      </div>
    </section>
  );
}

export function CodexUsagePanel({ client, refreshKey = 0 }: Props) {
  const [config, setConfig] = useState<CodexUsageConfig | null>(null);
  const [stats, setStats] = useState<CodexUsageStats | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
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
      try {
        const nextConfig = await client.getCodexUsageConfig();
        if (cancelled || requestId !== queryRequestIdRef.current) return;
        const range = defaultRange(nextConfig.timeBasis.today);
        setConfig(nextConfig);
        setStartDate(range.startDate);
        setEndDate(range.endDate);

        const nextStats = await client.getCodexUsageStats(range);
        if (cancelled || requestId !== queryRequestIdRef.current) return;
        setStats(nextStats);
      } catch (nextError) {
        if (!cancelled && requestId === queryRequestIdRef.current) {
          setError(getErrorMessage(nextError, "加载 Codex 额度失败"));
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

  const runStatsQuery = async (
    nextStartDate = startDate,
    nextEndDate = endDate,
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
    const requestId = ++queryRequestIdRef.current;
    setQuerying(true);
    setError("");
    setNotice("");
    try {
      const nextStats = await client.getCodexUsageStats({
        startDate: normalizedStartDate,
        endDate: normalizedEndDate,
      });
      if (requestId === queryRequestIdRef.current) {
        setStats(nextStats);
      }
    } catch (nextError) {
      if (requestId === queryRequestIdRef.current) {
        setError(getErrorMessage(nextError, "查询 Codex 额度失败"));
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
      setNotice(enabled ? "Codex 额度采集已开启。" : "Codex 额度采集已关闭，历史额度仍可查询。");
    } catch (nextError) {
      setError(`保存 Codex 额度采集设置失败：${getErrorMessage(nextError, "请稍后重试")}`);
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
    void runStatsQuery(range.startDate, range.endDate);
  };

  const resetFilters = () => {
    const range = defaultRange(config?.timeBasis.today || stats?.timeBasis.today || "");
    setStartDate(range.startDate);
    setEndDate(range.endDate);
    void runStatsQuery(range.startDate, range.endDate);
  };

  const hasRateLimitSamples = Boolean(stats?.rateLimitSamples.length);

  return (
    <section aria-labelledby="codex-usage-title" className="codex-usage-panel">
      <div className="codex-usage-heading">
        <div>
          <h2 id="codex-usage-title">Codex 额度</h2>
        </div>
        <span className="codex-usage-time-basis">
          服务端本地时间 {config?.timeBasis.utcOffset || stats?.timeBasis.utcOffset || "—"}
        </span>
      </div>

      {error ? <div role="alert" className="codex-usage-alert codex-usage-alert-error">{error}</div> : null}
      {notice ? <div role="status" className="codex-usage-alert codex-usage-alert-success">{notice}</div> : null}

      {loading ? <p role="status" className="codex-usage-loading">正在加载 Codex 额度…</p> : null}

      {!loading && config ? (
        <>
          <section className="codex-usage-section" aria-labelledby="codex-usage-settings-title">
            <div className="codex-usage-section-heading">
              <div>
                <h3 id="codex-usage-settings-title">采集设置</h3>
              </div>
              <label className="codex-usage-switch">
                <span>启用 Codex 额度采集</span>
                <input
                  aria-label="启用 Codex 额度采集"
                  type="checkbox"
                  checked={config.enabled}
                  disabled={saving}
                  onChange={(event) => void saveEnabled(event.target.checked)}
                />
              </label>
            </div>
            {!config.enabled && hasRateLimitSamples ? (
              <p className="codex-usage-disabled-history">额度采集已关闭，历史额度仍可查询。</p>
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

            <div className="codex-usage-form-actions">
              <button type="submit" className="codex-usage-primary" disabled={querying}>
                {querying ? "查询中…" : "查询"}
              </button>
              <button type="button" onClick={resetFilters} disabled={querying}>重置</button>
            </div>
          </form>

          {stats ? (
            <>
              <CodexRateLimitChart samples={stats.rateLimitSamples} />
              {!hasRateLimitSamples ? <p className="codex-usage-empty">暂无符合筛选条件的 Codex 额度数据。</p> : null}
            </>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
