import { useEffect, useMemo, useRef, useState } from "react";
import type {
  CodexUsageConfig,
  CodexUsageDailyProviderStats,
  CodexUsageMetrics,
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

function formatNumber(value: number) {
  return numberFormat.format(value);
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

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="codex-usage-metric-card">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function MetricCells({ metrics }: { metrics: CodexUsageMetrics }) {
  return (
    <>
      <td>{formatNumber(metrics.requestCount)}</td>
      <td>{formatNumber(metrics.inputTokens)}</td>
      <td>{formatNumber(metrics.cachedInputTokens)}</td>
      <td>{formatNumber(metrics.uncachedInputTokens)}</td>
      <td>{formatNumber(metrics.outputTokens)}</td>
      <td>{formatNumber(metrics.reasoningOutputTokens)}</td>
      <td>{formatNumber(metrics.totalTokens)}</td>
      <td>{formatRate(metrics.cacheHitRate)}</td>
    </>
  );
}

export function CodexUsagePanel({ client, refreshKey = 0 }: Props) {
  const [config, setConfig] = useState<CodexUsageConfig | null>(null);
  const [stats, setStats] = useState<CodexUsageStats | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  // null 表示全部 Provider；空数组表示用户明确清空了全部选择。
  const [selectedProviderKeys, setSelectedProviderKeys] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [querying, setQuerying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const queryRequestIdRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    queryRequestIdRef.current += 1;

    const load = async () => {
      setLoading(true);
      setError("");
      setNotice("");
      setSelectedProviderKeys(null);
      try {
        const nextConfig = await client.getCodexUsageConfig();
        if (cancelled) return;
        const range = defaultRange(nextConfig.timeBasis.today);
        setConfig(nextConfig);
        setStartDate(range.startDate);
        setEndDate(range.endDate);

        const nextStats = await client.getCodexUsageStats(range);
        if (cancelled) return;
        setStats(nextStats);
      } catch (nextError) {
        if (!cancelled) {
          setError(getErrorMessage(nextError, "加载 Codex 用量失败"));
        }
      } finally {
        if (!cancelled) setLoading(false);
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

  const providerRows = useMemo(
    () => [...(stats?.byProvider || [])].sort((left, right) => sortProviders(left.provider, right.provider)),
    [stats],
  );

  const dailyRows = useMemo<CodexUsageDailyProviderStats[]>(() => {
    const detailedRows = stats?.dailyByProvider || [];
    const rows = detailedRows.length
      ? detailedRows
      : (stats?.byDay || []).map((item) => ({
          ...item,
          provider: {
            key: "all-providers",
            kind: "unknown" as const,
            label: "全部 Provider",
            baseUrl: null,
          },
        }));
    return [...rows].sort((left, right) => (
      right.date.localeCompare(left.date) || sortProviders(left.provider, right.provider)
    ));
  }, [stats]);

  const runStatsQuery = async (
    nextStartDate = startDate,
    nextEndDate = endDate,
    nextSelectedProviderKeys = selectedProviderKeys,
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
    setQuerying(true);
    setError("");
    setNotice("");
    try {
      const nextStats = await client.getCodexUsageStats({
        startDate: normalizedStartDate,
        endDate: normalizedEndDate,
        ...(nextSelectedProviderKeys === null ? {} : { providerKeys: nextSelectedProviderKeys }),
      });
      if (requestId === queryRequestIdRef.current) {
        setStats(nextStats);
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
    void runStatsQuery(range.startDate, range.endDate);
  };

  const resetFilters = () => {
    const range = defaultRange(config?.timeBasis.today || stats?.timeBasis.today || "");
    setStartDate(range.startDate);
    setEndDate(range.endDate);
    setSelectedProviderKeys(null);
    void runStatsQuery(range.startDate, range.endDate, null);
  };

  const toggleProvider = (providerKey: string) => {
    setSelectedProviderKeys((current) => {
      const currentKeys = current === null ? providers.map((provider) => provider.key) : current;
      return currentKeys.includes(providerKey)
        ? currentKeys.filter((key) => key !== providerKey)
        : [...currentKeys, providerKey];
    });
  };

  const hasHistoricalData = Boolean(stats && stats.totals.requestCount > 0);
  const noResults = Boolean(stats && !stats.byProvider.length && !stats.byDay.length && !stats.dailyByProvider.length);

  return (
    <section aria-labelledby="codex-usage-title" className="codex-usage-panel">
      <div className="codex-usage-heading">
        <div>
          <h2 id="codex-usage-title">Codex 用量</h2>
          <p>按服务端本地自然日和根 config.toml 的 base URL 汇总，不区分 Bot、用户或 Agent。</p>
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
                <p>仅统计开启后新启动的 Codex 调用；关闭不会删除历史记录。</p>
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
            <p className="codex-usage-helper">Provider 按根 config.toml 的 base URL 归因；不会显示认证参数。</p>
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
                <p>日期按服务端本地自然日计算。</p>
              </div>
              <div className="codex-usage-quick-actions" aria-label="日期快捷范围">
                <button type="button" onClick={() => applyQuickRange(1)}>今天</button>
                <button type="button" onClick={() => applyQuickRange(7)}>近 7 天</button>
                <button type="button" onClick={() => applyQuickRange(30)}>近 30 天</button>
                <button type="button" onClick={() => applyQuickRange(90)}>近 90 天</button>
                <button type="button" onClick={() => applyQuickRange(null)}>全部</button>
              </div>
            </div>

            <div className="codex-usage-date-fields">
              <label>
                起始日期
                <input aria-label="起始日期" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
              </label>
              <label>
                结束日期
                <input aria-label="结束日期" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
              </label>
            </div>

            <fieldset className="codex-usage-provider-filters">
              <legend>Provider</legend>
              <div className="codex-usage-provider-actions">
                <button type="button" onClick={() => setSelectedProviderKeys(null)}>全选</button>
                <button type="button" onClick={() => setSelectedProviderKeys([])}>清空</button>
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
                  <MetricCard label="请求次数" value={formatNumber(stats.totals.requestCount)} />
                  <MetricCard label="输入 token" value={formatNumber(stats.totals.inputTokens)} />
                  <MetricCard label="缓存命中 token" value={formatNumber(stats.totals.cachedInputTokens)} />
                  <MetricCard label="非缓存输入" value={formatNumber(stats.totals.uncachedInputTokens)} />
                  <MetricCard label="输出 token" value={formatNumber(stats.totals.outputTokens)} />
                  <MetricCard label="总 token" value={formatNumber(stats.totals.totalTokens)} />
                  <MetricCard label="缓存命中率" value={formatRate(stats.totals.cacheHitRate)} />
                </dl>
              </section>

              {noResults ? <p className="codex-usage-empty">暂无符合筛选条件的 Codex 用量数据。</p> : null}

              {!noResults ? (
                <section className="codex-usage-section" aria-labelledby="codex-usage-by-provider-title">
                  <h3 id="codex-usage-by-provider-title">按 Provider 汇总</h3>
                  <div className="codex-usage-table-wrap">
                    <table aria-label="Codex 用量 Provider 汇总">
                      <caption>按 Provider 汇总</caption>
                      <thead>
                        <tr>
                          <th scope="col">Provider</th>
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
                          <tr key={item.provider.key}>
                            <th scope="row">
                              <span>{providerLabel(item.provider)}</span>
                              {item.provider.baseUrl ? <small>{item.provider.baseUrl}</small> : null}
                            </th>
                            <MetricCells metrics={item} />
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}

              {!noResults ? (
                <section className="codex-usage-section" aria-labelledby="codex-usage-daily-title">
                  <h3 id="codex-usage-daily-title">每日明细</h3>
                  <div className="codex-usage-table-wrap">
                    <table aria-label="Codex 用量每日明细">
                      <caption>按日期和 Provider 的每日明细</caption>
                      <thead>
                        <tr>
                          <th scope="col">日期</th>
                          <th scope="col">Provider</th>
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
                          <tr key={`${item.date}:${item.provider.key}`}>
                            <th scope="row">{item.date}</th>
                            <td className="codex-usage-provider-cell">{providerLabel(item.provider)}</td>
                            <MetricCells metrics={item} />
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}
            </>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
